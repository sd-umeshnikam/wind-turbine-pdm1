"""Suggested questions.

- starters: context-aware openers built from the live state (the worst turbine, the
  most severe open alert, the alert or turbine on screen) so they always name real ids.
- follow-ups: the LLM proposes next questions from the exchange, constrained to what the
  tools can answer; each is validated, and a rule-based set (from the entities the answer
  touched) fills in when the model fails or proposes something unusable.
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from wtpdm.api import live
from wtpdm.assistant.guardrails import DOMAIN_TERMS, TURBINE_ID, check_input
from wtpdm.assistant.llm import ChatModel, LLMError
from wtpdm.db.models import Alert, AlertStatus, Severity

MAX_SUGGESTIONS = 3
MAX_CHARS = 110
SEVERITY_RANK = {Severity.LOW: 0, Severity.MEDIUM: 1, Severity.HIGH: 2, Severity.CRITICAL: 3}

FOLLOW_UP_PROMPT = """You suggest the next questions a wind-farm maintenance engineer would ask after this exchange.
Rules: at most 3 questions; each under 100 characters; each must be answerable from live platform data
(fleet and turbine health, sub-part health trends, measured vs expected sensor values, alerts and their drivers,
maintenance recommendations, model metrics, drift, retrain jobs, labelled events) or the platform guide;
reuse the exact turbine ids, farm letters and component names from the exchange; no yes/no questions;
do not repeat the user's question. Reply as JSON: {"questions": ["...", "..."]}"""


def valid(question: str) -> bool:
    q = question.strip()
    if not 8 <= len(q) <= MAX_CHARS or not q.endswith("?"):
        return False
    if check_input(q).blocked:
        return False
    words = set(re.findall(r"[a-z0-9-]+", q.lower()))
    return bool(words & DOMAIN_TERMS) or bool(TURBINE_ID.search(q))


def _dedupe(questions: list[str], asked: str) -> list[str]:
    seen = {asked.strip().lower()}
    out = []
    for q in questions:
        key = q.strip().lower()
        if key not in seen:
            seen.add(key)
            out.append(q.strip())
    return out


def rule_based(entities: dict[str, Any]) -> list[str]:
    """Follow-ups from what the answer touched (turbines, alerts, farms, sub-parts)."""
    out: list[str] = []
    for alert_id in entities.get("alerts", [])[:1]:
        turbine = entities.get("alert_turbines", {}).get(alert_id)
        out.append(f"What maintenance do you recommend for the {turbine or 'this'} alert?")
    for turbine in entities.get("turbines", [])[:2]:
        out.append(f"How has the health of {turbine} changed over the last 7 days?")
        out.append(f"Which sensors of {turbine} deviate most from expected?")
    for farm in entities.get("farms", [])[:1]:
        out.append(f"Is there any drift on farm {farm}?")
        out.append(f"How does the farm {farm} champion model perform?")
    out += [
        "Which turbines have the lowest health right now?",
        "Which critical or high alerts are still unassigned?",
    ]
    return out


def follow_ups(
    model: ChatModel | None, question: str, answer: str, entities: dict[str, Any]
) -> tuple[list[str], str]:
    """(questions, source) with source "llm", "rules" or "mixed"."""
    proposed: list[str] = []
    if model is not None:
        try:
            reply = model.complete(
                [
                    {"role": "system", "content": FOLLOW_UP_PROMPT},
                    {"role": "user", "content": f"Question: {question}\n\nAnswer: {answer[:2500]}"},
                ],
                max_tokens=600,
                temperature=0.3,
                json_mode=True,
            )
            data = json.loads(reply.content or "{}")
            proposed = [q for q in data.get("questions", []) if isinstance(q, str) and valid(q)]
        except (LLMError, ValueError, json.JSONDecodeError, AttributeError):
            proposed = []
    llm = _dedupe(proposed, question)[:MAX_SUGGESTIONS]
    if len(llm) == MAX_SUGGESTIONS:
        return llm, "llm"
    rules = [q for q in _dedupe(rule_based(entities), question) if q.lower() not in {x.lower() for x in llm}]
    merged = (llm + rules)[:MAX_SUGGESTIONS]
    return merged, "mixed" if llm else "rules"


def starters(
    s: Session, turbine_id: str | None = None, alert_id: str | None = None, page: str | None = None
) -> list[str]:
    out: list[str] = []
    if alert_id:
        alert = s.get(Alert, uuid.UUID(alert_id)) if _is_uuid(alert_id) else None
        if alert is not None:
            out += [
                f"Explain the {alert.severity.value} alert on {alert.turbine_id}: what are its drivers?",
                f"What maintenance do you recommend for the {alert.turbine_id} alert?",
            ]
    if turbine_id:
        out += [
            f"Summarise the health of {turbine_id}",
            f"Which sensors of {turbine_id} deviate most from expected?",
            f"How has the health of {turbine_id} changed over the last 7 days?",
        ]
    if page in ("models", "drift"):
        out += ["How do the champion models compare across farms?", "Has any farm drifted recently?"]
    if len(out) < 4:
        fleet = [t for t in live.fleet(s) if t.health is not None]
        worst = min(fleet, key=lambda t: t.health or 100, default=None)
        top = s.scalars(select(Alert).where(Alert.status == AlertStatus.OPEN)).all()
        top_alert = max(top, key=lambda a: SEVERITY_RANK[a.severity], default=None)
        out += ["What changed since my last visit?", "Which turbines need attention first?"]
        if worst is not None:
            out.append(f"Why is {worst.id} the lowest-health turbine?")
        if top_alert is not None:
            out.append(
                f"What should we do about the {top_alert.severity.value} alert on {top_alert.turbine_id}?"
            )
    return _dedupe(out, "")[:4]


def _is_uuid(value: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-fA-F-]{36}", value))
