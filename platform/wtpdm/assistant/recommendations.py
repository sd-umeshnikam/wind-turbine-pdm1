"""Maintenance recommendations: the playbook entries of the sub-parts implicated by a live
alert (its attributed sub-part, then the sub-parts of its driver sensors), with the
evidence from the alert, a response window from its severity, and citations.

Deterministic and always advisory: the assistant may phrase them, never invent them.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from wtpdm.api import live
from wtpdm.assistant.knowledge import playbook
from wtpdm.db.models import Alert, Sensor, Severity, Turbine

DISCLAIMER = (
    "Advisory only: based on the condition model and the maintenance playbook. Site procedures, the OEM "
    "manual, lockout/tagout and the responsible engineer's judgement take precedence."
)
# Sub-parts whose failure affects a safety function.
SAFETY_RELEVANT = {"pitch.battery", "rotor_brake.caliper", "transformer.oil", "transformer.windings"}
WATCH_BELOW = 65.0  # sub-part health below this gets a monitoring recommendation without an alert
MAX_ITEMS = 3


def _sensor_subparts(s: Session, farm: str, sensors: list[str]) -> dict[str, str | None]:
    codes = [x.removesuffix("_avg") for x in sensors]
    rows = s.execute(
        select(Sensor.code, Sensor.subcomponent_code).where(Sensor.farm_id == farm, Sensor.code.in_(codes))
    )
    return {f"{code}_avg": sub for code, sub in rows}


def _item(code: str, evidence: list[dict]) -> dict | None:
    entry = playbook()["entries"].get(code)
    if entry is None:
        return None
    return {
        "subcomponent": code,
        "name": entry["name"],
        "safety_relevant": code in SAFETY_RELEVANT,
        "evidence": evidence,
        "failure_modes": [
            {
                "id": fm["id"],
                "mode": fm["mode"],
                "signals": fm["signals"],
                "checks": fm["checks"],
                "actions": fm["actions"],
            }
            for fm in entry["failure_modes"]
        ],
    }


def for_alert(s: Session, alert: Alert) -> dict[str, Any]:
    farm = s.get(Turbine, alert.turbine_id).farm_id  # type: ignore[union-attr]
    drivers = alert.drivers or []
    mapping = _sensor_subparts(s, farm, [d["sensor"] for d in drivers])
    ordered: list[str] = []
    if alert.subcomponent_code:
        ordered.append(alert.subcomponent_code)
    for d in drivers:
        sub = mapping.get(d["sensor"])
        if sub and sub not in ordered:
            ordered.append(sub)
    evidence: dict[str, list[dict]] = {}
    for d in drivers:
        sub = mapping.get(d["sensor"])
        if sub:
            evidence.setdefault(sub, []).append(
                {"sensor": d["sensor"], "description": d["description"], "z": d["z"]}
            )
    items = [i for code in ordered if (i := _item(code, evidence.get(code, [])))][:MAX_ITEMS]
    response = playbook()["response"][alert.severity.value]
    notes = []
    if not alert.condition_active:
        notes.append(
            "The condition has cleared since the alert was raised: "
            "confirm the trend before dispatching a crew."
        )
    if any(i["safety_relevant"] for i in items):
        notes.append(
            "A safety-relevant sub-part is implicated: "
            "verify the protective function before return to service."
        )
    unmapped = [d["description"] for d in drivers if not mapping.get(d["sensor"])]
    if unmapped:
        notes.append(f"Drivers without a sub-part mapping (context only): {', '.join(unmapped)}.")
    return {
        "scope": "alert",
        "alert_id": str(alert.id),
        "turbine_id": alert.turbine_id,
        "severity": alert.severity.value,
        "status": alert.status.value,
        "condition_active": alert.condition_active,
        "response": response,
        "items": items,
        "notes": notes,
        "disclaimer": DISCLAIMER,
        "citations": [f"alert:{alert.id}", *(fm["id"] for i in items for fm in i["failure_modes"])],
    }


def for_turbine(s: Session, turbine_id: str) -> dict[str, Any]:
    """With an active alert: its recommendation. Otherwise sub-parts trending low get a
    monitoring recommendation; a healthy turbine gets none."""
    active = live.active_alerts(s, turbine_id).get(turbine_id)
    if active is not None:
        return for_alert(s, active)
    rows = live.latest_health(s, turbine_id).get(turbine_id, {})
    weak = sorted(
        ((code, float(r["health"]), r["residual_z"]) for code, r in rows.items() if code != "turbine"),
        key=lambda x: x[1],
    )
    weak = [w for w in weak if w[1] < WATCH_BELOW][:MAX_ITEMS]
    items = [
        i
        for code, health, z in weak
        if (
            i := _item(
                code, [{"health": round(health, 1), "residual_z": None if z is None else round(float(z), 2)}]
            )
        )
    ]
    severity = Severity.MEDIUM if any(h < 50 for _, h, _ in weak) else Severity.LOW
    return {
        "scope": "turbine",
        "alert_id": None,
        "turbine_id": turbine_id,
        "severity": severity.value if items else None,
        "status": None,
        "condition_active": None,
        "response": playbook()["response"][severity.value] if items else None,
        "items": items,
        "notes": []
        if items
        else ["No active alert and every monitored sub-part is above the watch level: no action needed."],
        "disclaimer": DISCLAIMER,
        "citations": [fm["id"] for i in items for fm in i["failure_modes"]],
    }
