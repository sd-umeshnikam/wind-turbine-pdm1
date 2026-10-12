"""Live per-turbine predictions from the inference server, added to the chat context
when a question names a turbine (or the user is on that turbine's page)."""
from __future__ import annotations

import os
import re

import httpx

INFERENCE_URL = os.environ.get("INFERENCE_URL", "http://localhost:8080/invocations")
GATEWAY_GRAPHQL_URL = os.environ.get("GATEWAY_GRAPHQL_URL", "http://localhost:4000/graphql")
ALERT_WORDS = re.compile(r"\b(alerts?|alarms?|critical|urgent|attention|priority|priorities|worst|riskiest|at risk)\b", re.I)
SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}
RUL_IN_MESSAGE = re.compile(r"rulHoursP50=(-?[\d.]+)")
PROB_IN_MESSAGE = re.compile(r"faultProbability=([\d.]+)")
# "C-3" / "C3" / "c-3"; no spaces allowed, so "a 5 day delay" isn't read as turbine A-5.
TURBINE_RE = re.compile(r"\b([ABC])-?(\d{1,2})\b", re.IGNORECASE)


def turbine_ids_in(text: str, known: set[str]) -> list[str]:
    found = []
    for farm, n in TURBINE_RE.findall(text):
        tid = f"{farm.upper()}-{int(n)}"
        if tid in known and tid not in found:
            found.append(tid)
    return found


def _rul_text(hours: float) -> str:
    if hours <= 0:
        return "0 days"
    days = hours / 24
    return f"{days:.0f} days" if days < 60 else f"{days / 30:.1f} months"


def asks_about_alerts(text: str) -> bool:
    return bool(ALERT_WORDS.search(text))


def active_alerts(turbine_ids: list[str] | None = None, limit: int = 8) -> str | None:
    query = "query{ activeAlerts { turbineId component severity message createdAt acknowledged } }"
    try:
        resp = httpx.post(GATEWAY_GRAPHQL_URL, json={"query": query}, timeout=15)
        resp.raise_for_status()
        alerts = resp.json()["data"]["activeAlerts"]
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return None
    alerts = [a for a in alerts if not a.get("acknowledged")]
    if turbine_ids:
        alerts = [a for a in alerts if a["turbineId"] in turbine_ids]
    if not alerts:
        scope = f" for {', '.join(turbine_ids)}" if turbine_ids else ""
        return f"There are no open (unacknowledged) alerts{scope} right now."

    def rul(a: dict) -> float:
        m = RUL_IN_MESSAGE.search(a.get("message", ""))
        return float(m.group(1)) if m else float("inf")

    alerts.sort(key=lambda a: (SEVERITY_RANK.get(a["severity"].lower(), 9), rul(a)))
    counts: dict[str, int] = {}
    for a in alerts:
        counts[a["severity"]] = counts.get(a["severity"], 0) + 1
    summary = ", ".join(f"{n} {sev}" for sev, n in sorted(counts.items(), key=lambda kv: SEVERITY_RANK.get(kv[0], 9)))
    lines = []
    for a in alerts[:limit]:
        prob = PROB_IN_MESSAGE.search(a.get("message", ""))
        detail = [f"{a['severity'].upper()}: {a['component']} on turbine {a['turbineId']}"]
        if prob:
            detail.append(f"fault probability {round(float(prob.group(1)) * 100)}%")
        if rul(a) != float("inf"):
            detail.append(f"remaining life P50 {_rul_text(rul(a))}")
        lines.append("- " + ", ".join(detail))
    return (f"Open alerts ({len(alerts)} total: {summary}), most urgent first:\n" + "\n".join(lines)
            + (f"\n(and {len(alerts) - limit} more)" if len(alerts) > limit else ""))


def live_predictions(turbine_id: str) -> str | None:
    try:
        resp = httpx.post(INFERENCE_URL, json={"dataframe_records": [{"turbine_id": turbine_id}]}, timeout=20)
        resp.raise_for_status()
        preds = resp.json().get("predictions", [])
    except (httpx.HTTPError, ValueError):
        return None
    if not preds:
        return f"No live model predictions are available for turbine {turbine_id}."
    lines = [
        f"- {p['component']}: fault probability {round(p['fault_probability'] * 100)}%, "
        f"remaining life P50 {_rul_text(p['rul_hours_p50'])} "
        f"(P10 {_rul_text(p['rul_hours_p10'])}, P90 {_rul_text(p['rul_hours_p90'])})"
        for p in preds
    ]
    return f"Current model predictions for turbine {turbine_id}:\n" + "\n".join(lines)
