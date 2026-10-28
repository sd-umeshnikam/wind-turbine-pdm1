"""The assistant's conversation loop.

question -> input guardrails -> LLM with tools (up to MAX_TOOL_ROUNDS of calls, executed
read-only in the user's session) -> output guardrails (grounding: every figure must appear
in what the tools returned) -> citations from the tool calls -> follow-up suggestions.
Every turn is stored (conversation memory, review, feedback).
"""

from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from wtpdm.api.security import Principal
from wtpdm.assistant import guardrails, suggestions, tools
from wtpdm.assistant.knowledge import KnowledgeBase
from wtpdm.assistant.llm import ChatModel, LLMError
from wtpdm.db.models import AssistantMessage
from wtpdm.logging import get_logger
from wtpdm.settings import get_settings

log = get_logger("assistant")
MAX_TOOL_ROUNDS = 5
HISTORY_MESSAGES = 8
PLAYBOOK_ID = re.compile(r"\b[A-Z]{3}-[A-Z]{2,4}-\d\b")

SYSTEM_PROMPT = """You are the maintenance assistant of a wind-turbine predictive-maintenance platform used by
reliability and O&M engineers. You answer from the platform's live data through your tools.

Grounding rules:
- Use tools for every fact about turbines, components, alerts, models, drift, retraining or events. Never invent
  numbers, ids, dates, sensor names or metrics. If the tools do not return something, say it is not available.
- Turbine health is 0-100, calibrated so that 50 is the alarm level; describe it only with the platform bands
  (alarm below 50, degraded below 65, watch below 80, healthy 80+), never with thresholds of your own. Sub-part
  attribution and alert drivers are
  contributing signals, not a confirmed diagnosis: say so when you discuss causes.
- "Live" data is a replay of recorded SCADA history. Each turbine has its own anonymised data clock: call these
  "data time", and never compare dates between turbines.
- For "what should we do" questions use maintenance_recommendation and present it as advisory: response window,
  checks, actions, naming every failure mode with its playbook id in brackets, e.g. "(GBX-OIL-1)". Never advise bypassing, disabling or overriding any
  safety function; site procedures, the OEM manual and lockout/tagout always take precedence.
- For how the platform works (scores, alerts, drift, retraining, evaluation) use search_knowledge.
- You cannot change anything (acknowledge, assign, resolve, retrain, approve). Tell the user where to do it in the
  console: Alerts page, Drift & retraining page, Models page.

Style: lead with the answer in one or two sentences, then short bullets. Name turbine ids, alert severities and
sub-parts exactly as the tools return them. Round figures sensibly. Use Markdown; keep tables to six rows or fewer.
Do not mention tool names or JSON."""

GREETING_ANSWER = (
    "Hi! I'm the maintenance assistant. I answer from the platform's live data: fleet and turbine health, "
    "sub-part trends, measured vs expected sensor values, alerts and their drivers, maintenance recommendations "
    "from the playbook, model performance, drift and retraining. What would you like to know?"
)


@dataclass
class ChatResult:
    conversation_id: uuid.UUID
    message_id: int | None
    answer: str
    blocked: bool = False
    reason: str | None = None
    flags: list[str] = field(default_factory=list)
    tools: list[dict] = field(default_factory=list)
    citations: list[dict] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    suggestion_source: str = "rules"
    model: str | None = None
    latency_ms: int = 0


class AssistantUnavailable(RuntimeError):
    pass


def _context_note(user: Principal, context: dict[str, Any]) -> str:
    parts = [
        f"User: {user.display_name} ({user.username}), role {user.role.value}.",
        f"Wall-clock time: {datetime.now(UTC):%Y-%m-%d %H:%M} UTC.",
    ]
    if context.get("turbine_id"):
        parts.append(f"The user is looking at turbine {context['turbine_id']} ('this turbine').")
    if context.get("alert_id"):
        parts.append(f"The user has alert {context['alert_id']} open ('this alert').")
    if context.get("page"):
        parts.append(f"Console page: {context['page']}.")
    return " ".join(parts)


def _entities(calls: list[dict]) -> dict[str, Any]:
    """Turbines, alerts, farms and playbook ids touched by the tool calls."""
    turbines: list[str] = []
    alerts: list[str] = []
    farms: list[str] = []
    alert_turbines: dict[str, Any] = {}
    playbook_ids: list[str] = []
    knowledge: list[dict] = []

    def add(lst: list, v: Any) -> None:
        if v and v not in lst:
            lst.append(v)

    for c in calls:
        args, result = c["args"], c.get("result") or {}
        add(turbines, (args.get("turbine_id") or "").upper() or None)
        add(farms, (args.get("farm") or "").upper() or None)
        if c["name"] in ("turbine_health", "health_trend", "sensor_vs_expected", "sensor_deviations"):
            add(turbines, result.get("turbine_id"))
        if c["name"] == "alert_details" and result.get("id"):
            add(alerts, result["id"])
            alert_turbines[result["id"]] = result.get("turbine_id")
            add(turbines, result.get("turbine_id"))
        if c["name"] == "maintenance_recommendation":
            if result.get("alert_id"):
                add(alerts, result["alert_id"])
                alert_turbines[result["alert_id"]] = result.get("turbine_id")
            add(turbines, result.get("turbine_id"))
            for cid in result.get("citations", []):
                if not cid.startswith("alert:"):
                    add(playbook_ids, cid)
        if c["name"] == "list_alerts":
            for a in result.get("alerts", [])[:3]:
                alert_turbines.setdefault(a["id"], a["turbine_id"])
        if c["name"] == "model_overview" and result.get("model"):
            add(farms, result["model"][-1])
        if c["name"] == "search_knowledge":
            for r in result.get("results", []):
                if r not in knowledge:
                    knowledge.append({"source": r["source"], "title": r["title"], "ref": r["ref"]})
    return {
        "turbines": turbines,
        "alerts": alerts,
        "farms": farms,
        "alert_turbines": alert_turbines,
        "playbook": playbook_ids,
        "knowledge": knowledge,
    }


def _citations(entities: dict[str, Any], answer: str, calls: list[dict]) -> list[dict]:
    """Sources behind the answer, each with a console link where one exists."""
    out: list[dict] = []
    for t in entities["turbines"]:
        out.append({"kind": "turbine", "label": f"Turbine {t}", "ref": t, "link": f"/turbines/{t}"})
    for a in entities["alerts"]:
        turbine = entities["alert_turbines"].get(a)
        out.append(
            {
                "kind": "alert",
                "label": f"Alert on {turbine}" if turbine else "Alert",
                "ref": a,
                "link": f"/alerts?id={a}",
            }
        )
    mentioned = set(PLAYBOOK_ID.findall(answer))
    for pid in entities["playbook"]:
        if pid in mentioned or not mentioned:
            out.append({"kind": "playbook", "label": f"Playbook {pid}", "ref": pid, "link": None})
    for k in entities["knowledge"][:3]:
        link = "/models" if k["source"] == "model_card" else None
        out.append({"kind": k["source"], "label": k["title"], "ref": k["ref"], "link": link})
    if any(c["name"] in ("model_overview", "retrain_jobs") for c in calls):
        out.append({"kind": "registry", "label": "MLflow model registry", "ref": "models", "link": "/models"})
    if any(c["name"] == "drift_status" for c in calls):
        out.append({"kind": "drift", "label": "Drift monitor", "ref": "drift", "link": "/drift"})
    return out


class Assistant:
    def __init__(
        self, model: ChatModel | None, knowledge: KnowledgeBase, suggestion_model: ChatModel | None = None
    ):
        self.model = model
        self.knowledge = knowledge
        self.suggestion_model = suggestion_model or model

    # ------------------------------------------------------------ persistence

    def _history(self, s: Session, conversation_id: uuid.UUID, username: str) -> list[dict]:
        rows = s.scalars(
            select(AssistantMessage)
            .where(AssistantMessage.conversation_id == conversation_id, AssistantMessage.username == username)
            .order_by(AssistantMessage.id.desc())
            .limit(HISTORY_MESSAGES)
        ).all()
        return [{"role": r.role, "content": r.content} for r in reversed(rows)]

    def _store(self, s: Session, result: ChatResult, user: Principal, question: str, context: dict) -> None:
        s.add(
            AssistantMessage(
                conversation_id=result.conversation_id,
                username=user.username,
                role="user",
                content=question,
                context=context or None,
            )
        )
        answer = AssistantMessage(
            conversation_id=result.conversation_id,
            username=user.username,
            role="assistant",
            content=result.answer,
            context=context or None,
            tools=[{k: c[k] for k in ("name", "args", "ok")} for c in result.tools] or None,
            citations=result.citations or None,
            flags=result.flags or None,
            model=result.model,
            latency_ms=result.latency_ms,
        )
        s.add(answer)
        s.flush()
        result.message_id = answer.id

    # ------------------------------------------------------------ the loop

    def chat(
        self,
        s: Session,
        user: Principal,
        question: str,
        conversation_id: uuid.UUID | None = None,
        context: dict[str, Any] | None = None,
    ) -> ChatResult:
        started = time.perf_counter()
        context = {k: v for k, v in (context or {}).items() if v}
        conv = conversation_id or uuid.uuid4()
        check = guardrails.check_input(question)
        result = ChatResult(conversation_id=conv, message_id=None, answer="", flags=list(check.flags))

        def finish() -> ChatResult:
            result.latency_ms = round((time.perf_counter() - started) * 1000)
            self._store(s, result, user, check.text or question[: guardrails.MAX_INPUT_CHARS], context)
            return result

        if check.blocked:
            result.blocked, result.reason, result.answer = True, check.reason, check.message or ""
            result.suggestions = suggestions.starters(
                s, context.get("turbine_id"), context.get("alert_id"), context.get("page")
            )
            return finish()
        if guardrails.is_greeting(check.text):
            result.answer = GREETING_ANSWER
            result.suggestions = suggestions.starters(
                s, context.get("turbine_id"), context.get("alert_id"), context.get("page")
            )
            return finish()
        top = self.knowledge.search(check.text, k=1)
        if not guardrails.is_on_topic(check.text, top[0].score if top else 0.0, has_context=bool(context)):
            result.blocked, result.reason, result.answer = True, "off_topic", guardrails.OFF_TOPIC_MESSAGE
            result.suggestions = suggestions.starters(
                s, context.get("turbine_id"), context.get("alert_id"), context.get("page")
            )
            return finish()
        if self.model is None:
            raise AssistantUnavailable("The assistant has no language model configured (WTPDM_LLM_API_KEY)")

        result.model = self.model.name
        messages: list[dict] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "system", "content": _context_note(user, context)},
            *self._history(s, conv, user.username),
            {"role": "user", "content": check.text},
        ]
        ctx = tools.ToolContext(session=s, user=user, knowledge=self.knowledge)
        calls: list[dict] = []
        grounding: list[str] = [SYSTEM_PROMPT, check.text, _context_note(user, context)]
        answer: str | None = None
        for _round in range(MAX_TOOL_ROUNDS + 1):
            allow_tools = _round < MAX_TOOL_ROUNDS
            reply = self.model.complete(messages, tools.specs() if allow_tools else None)
            if not reply.tool_calls or not allow_tools:
                answer = (reply.content or "").strip()
                break
            messages.append(reply.as_message())
            for call in reply.tool_calls:
                ok, payload = tools.run(ctx, call.name, call.arguments)
                text = tools.dumps(payload)
                grounding.append(text)
                try:
                    args = json.loads(call.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                calls.append(
                    {
                        "name": call.name,
                        "args": args if isinstance(args, dict) else {},
                        "ok": ok,
                        "result": payload,
                    }
                )
                messages.append({"role": "tool", "tool_call_id": call.id, "content": text[:12000]})
        if not answer:
            raise LLMError("The model returned an empty answer")

        secrets = (
            get_settings().llm_api_key.get_secret_value(),
            get_settings().jwt_secret.get_secret_value(),
        )
        checked = guardrails.check_output(answer, "\n".join(grounding), secrets=secrets)
        result.answer = checked.text
        result.flags = sorted(set(result.flags) | set(checked.flags))
        result.tools = calls
        entities = _entities(calls)
        result.citations = _citations(entities, checked.text, calls)
        result.suggestions, result.suggestion_source = suggestions.follow_ups(
            self.suggestion_model, check.text, checked.text, entities
        )
        log.info(
            "assistant answer",
            user=user.username,
            tools=[c["name"] for c in calls],
            flags=result.flags,
            ms=round((time.perf_counter() - started) * 1000),
        )
        return finish()
