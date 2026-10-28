"""Evaluate the assistant against the live platform and the configured LLM.

    python -m wtpdm.assistant.eval [--min-pass 0.85] [--report /tmp/assistant-eval.json]

Each case checks tool selection, entity mentions, grounding (no unverified figures),
guardrail verdicts and that follow-up suggestions are offered. Answers are generated as a
dedicated evaluation user and rolled back, so the eval leaves no conversation rows.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

import mlflow
import yaml
from sqlalchemy import select

from wtpdm.api import live
from wtpdm.api.security import Principal
from wtpdm.assistant.knowledge import KnowledgeBase
from wtpdm.assistant.llm import default_model, suggestion_model
from wtpdm.assistant.service import Assistant
from wtpdm.db.models import Alert, Role
from wtpdm.db.session import get_engine
from wtpdm.settings import get_settings

EVAL_SET = Path(__file__).with_name("eval_set.yaml")
SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}


def placeholders(s) -> dict[str, str]:
    fleet = [t for t in live.fleet(s) if t.health is not None]
    worst = min(fleet, key=lambda t: t.health or 100)
    alerts = s.scalars(select(Alert).where(Alert.status.in_(live.ACTIVE))).all()
    alert = max(alerts, key=lambda a: SEVERITY_RANK[a.severity.value]) if alerts else None
    return {
        "worst_turbine": worst.id,
        "farm": worst.farm_id,
        "alert_id": str(alert.id) if alert else "",
        "alert_turbine": alert.turbine_id if alert else worst.id,
    }


def fill(value: Any, ph: dict[str, str]) -> Any:
    if isinstance(value, str):
        for key, val in ph.items():
            value = value.replace("{" + key + "}", val)
        return value
    if isinstance(value, list):
        return [fill(v, ph) for v in value]
    if isinstance(value, dict):
        return {k: fill(v, ph) for k, v in value.items()}
    return value


def check(case: dict, result) -> list[str]:
    failures = []
    if "blocked" in case:
        if not result.blocked or result.reason != case["blocked"]:
            failures.append(
                f"expected blocked={case['blocked']}, got blocked={result.blocked} reason={result.reason}"
            )
        return failures
    if result.blocked:
        return [f"unexpectedly blocked ({result.reason})"]
    called = {c["name"] for c in result.tools}
    if case.get("tools_any") and not called & set(case["tools_any"]):
        failures.append(f"expected one of {case['tools_any']}, called {sorted(called) or 'nothing'}")
    for m in case.get("mentions", []):
        if m and m not in result.answer:
            failures.append(f"answer does not mention {m}")
    for rx in case.get("mentions_regex", []):
        if not re.search(rx, result.answer):
            failures.append(f"answer does not match /{rx}/")
    if case.get("grounded", True) and "ungrounded_figures" in result.flags:
        failures.append("unverified figures in the answer")
    if not result.suggestions:
        failures.append("no follow-up suggestions")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-pass", type=float, default=0.85)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--only", help="run the cases whose id contains this text")
    parser.add_argument("--show-answers", action="store_true", help="print the answer of failing cases")
    parser.add_argument(
        "--pause", type=float, default=20.0, help="seconds between model cases (provider rate limits)"
    )
    args = parser.parse_args()

    mlflow.set_tracking_uri(get_settings().mlflow_tracking_uri)  # artifact downloads (model cards)
    model = default_model()
    if model is None:
        print("No LLM configured (WTPDM_LLM_API_KEY); the eval needs the real model.", file=sys.stderr)
        return 2
    assistant = Assistant(model, KnowledgeBase(), suggestion_model=suggestion_model())
    user = Principal("assistant-eval", "Assistant evaluation", Role.ENGINEER)
    cases = yaml.safe_load(EVAL_SET.read_text(encoding="utf-8"))["cases"]
    if args.only:
        cases = [c for c in cases if args.only in c["id"]]

    rows = []
    with get_engine().connect() as conn:
        from sqlalchemy.orm import Session

        outer = conn.begin()
        s = Session(bind=conn, join_transaction_mode="create_savepoint")
        ph = placeholders(s)
        try:
            for raw in cases:
                case = fill(raw, ph)
                if case.get("context", {}).get("alert_id") == "":
                    rows.append(
                        {"id": case["id"], "ok": None, "failures": ["skipped: no active alert"], "ms": 0}
                    )
                    continue
                if "blocked" not in case and rows:
                    time.sleep(args.pause)
                started = time.perf_counter()
                try:
                    result = assistant.chat(s, user, case["question"], context=case.get("context"))
                    failures = check(case, result)
                    answer, tools_called = result.answer, [c["name"] for c in result.tools]
                except Exception as exc:  # a failing case must not stop the run
                    failures, answer, tools_called = [f"error: {type(exc).__name__}: {exc}"], "", []
                rows.append(
                    {
                        "id": case["id"],
                        "ok": not failures,
                        "failures": failures,
                        "tools": tools_called,
                        "ms": round((time.perf_counter() - started) * 1000),
                        "question": case["question"],
                        "answer": answer,
                    }
                )
                status = "PASS" if not failures else "FAIL"
                print(
                    f"{status:4}  {case['id']:<24} {rows[-1]['ms']:>6} ms  {', '.join(tools_called) or '-'}"
                )
                for f in failures:
                    print(f"        - {f}")
                if failures and args.show_answers and answer:
                    for line in answer.splitlines():
                        print(f"        > {line}")
        finally:
            s.close()
            outer.rollback()

    scored = [r for r in rows if r["ok"] is not None]
    rate = sum(r["ok"] for r in scored) / len(scored) if scored else 0.0
    print(f"\n{sum(r['ok'] for r in scored)}/{len(scored)} passed ({rate:.0%}), model {model.name}")
    if args.report:
        args.report.write_text(
            json.dumps({"pass_rate": rate, "model": model.name, "cases": rows}, indent=2, default=str)
        )
    return 0 if rate >= args.min_pass else 1


if __name__ == "__main__":
    sys.exit(main())
