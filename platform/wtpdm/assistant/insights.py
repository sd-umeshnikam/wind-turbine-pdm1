"""Proactive insights: what changed since the user's previous visit, from the audit log
and the live state. Deterministic; every item links to where it can be acted on."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from wtpdm.api import live
from wtpdm.api.routers.mlops import drift_snapshot, feature_names
from wtpdm.db.models import Alert, AuditLog, Farm, RetrainJob
from wtpdm.db.models import Severity as Sev

FIRST_VISIT_WINDOW = timedelta(hours=24)
MAX_LISTED = 5
SEVERITY_RANK = {Sev.LOW: 0, Sev.MEDIUM: 1, Sev.HIGH: 2, Sev.CRITICAL: 3}


def _item(kind: str, tone: str, title: str, detail: str, link: str | None, **extra: Any) -> dict:
    return {"kind": kind, "tone": tone, "title": title, "detail": detail, "link": link, **extra}


def since(s: Session, username: str, previous: datetime | None) -> dict[str, Any]:
    now = datetime.now(UTC)
    start = previous or now - FIRST_VISIT_WINDOW
    audit = s.scalars(select(AuditLog).where(AuditLog.ts > start).order_by(AuditLog.ts)).all()
    by_action = Counter(a.action for a in audit)
    items: list[dict] = []

    # New and escalated alerts, most severe first.
    raised_ids = {
        a.entity_id for a in audit if a.action in ("alert.raise", "alert.reoccur", "alert.escalate")
    }
    alerts = (
        s.scalars(select(Alert).where(Alert.id.in_([i for i in raised_ids if i]))).all() if raised_ids else []
    )
    alerts = sorted(alerts, key=lambda a: -SEVERITY_RANK[a.severity])
    if alerts:
        sev = Counter(a.severity.value for a in alerts)
        items.append(
            _item(
                "alerts",
                "critical" if sev.get("critical") else "warning",
                f"{by_action['alert.raise']} new, {by_action['alert.escalate']} escalated, "
                f"{by_action['alert.reoccur']} re-occurred alerts",
                ", ".join(
                    f"{a.turbine_id} {a.severity.value} ({a.component_code})" for a in alerts[:MAX_LISTED]
                ),
                "/alerts",
                alerts=[
                    {
                        "id": str(a.id),
                        "turbine_id": a.turbine_id,
                        "severity": a.severity.value,
                        "title": a.title,
                    }
                    for a in alerts[:MAX_LISTED]
                ],
            )
        )
    cleared = by_action["alert.clear"]
    resolved = [a for a in audit if a.action == "alert.resolve"]
    if cleared or resolved:
        who = Counter(a.actor for a in resolved)
        items.append(
            _item(
                "resolutions",
                "good",
                f"{len(resolved)} alerts resolved, {cleared} conditions cleared",
                ", ".join(f"{n} by {u}" for u, n in who.most_common(3))
                or "conditions returned to normal; awaiting resolution",
                "/alerts",
            )
        )

    # The user's own queue.
    mine = s.scalars(
        select(Alert)
        .where(Alert.assignee == username, Alert.status.in_(live.ACTIVE))
        .order_by(Alert.opened_at)
    ).all()
    if mine:
        items.append(
            _item(
                "my_queue",
                "info",
                f"{len(mine)} active alerts assigned to you",
                ", ".join(f"{a.turbine_id} {a.severity.value}" for a in mine[:MAX_LISTED]),
                "/alerts",
            )
        )

    # Models and retraining.
    promoted = [a for a in audit if a.action in ("model.promote", "model.approve")]
    registered = [a for a in audit if a.action == "model.register"]
    if promoted or registered:
        detail = [f"{a.entity_id} promoted to champion" for a in promoted]
        for a in registered:
            d = a.details or {}
            state = "awaiting admin approval" if d.get("awaiting_approval") else "held by the promotion gate"
            detail.append(f"{a.entity_id} registered, {state}")
        items.append(
            _item("models", "info", "Model registry changed", "; ".join(detail[:MAX_LISTED]), "/models")
        )
    jobs = s.scalars(
        select(RetrainJob).where(RetrainJob.finished_at > start).order_by(RetrainJob.finished_at)
    ).all()
    if jobs:
        failed = [j for j in jobs if j.status == "failed"]
        items.append(
            _item(
                "retraining",
                "critical" if failed else "info",
                f"{len(jobs)} retrain jobs finished" + (f", {len(failed)} failed" if failed else ""),
                ", ".join(
                    f"#{j.id} {(j.scope or {}).get('farm', '?')} {j.trigger}: {j.status}"
                    for j in jobs[-MAX_LISTED:]
                ),
                "/drift",
            )
        )

    # Drift now.
    names = feature_names(s)
    drifting = [
        snap
        for f in s.scalars(select(Farm.id).order_by(Farm.id))
        if (snap := drift_snapshot(s, f, names)).status in ("drift", "warning")
    ]
    if drifting:
        items.append(
            _item(
                "drift",
                "critical" if any(d.status == "drift" for d in drifting) else "warning",
                "Drift detected"
                if any(d.status == "drift" for d in drifting)
                else "Informational drift breach",
                "; ".join(
                    f"farm {d.farm_id}: "
                    + ", ".join(
                        f"{r.metric} {r.feature_description or r.feature or ''}".strip()
                        for r in d.rows
                        if r.breached
                    )
                    for d in drifting
                ),
                "/drift",
            )
        )

    # Lowest-health turbines right now.
    fleet = [t for t in live.fleet(s) if t.health is not None and t.health < 65]
    fleet.sort(key=lambda t: t.health or 0)
    if fleet:
        items.append(
            _item(
                "health",
                "critical" if any((t.health or 100) < 50 for t in fleet) else "warning",
                f"{len(fleet)} turbines below the watch level",
                ", ".join(
                    f"{t.id} {t.health:.0f} ({t.worst_subcomponent or 'n/a'})" for t in fleet[:MAX_LISTED]
                ),
                f"/turbines/{fleet[0].id}",
            )
        )

    return {
        "since": start,
        "first_visit": previous is None,
        "generated_at": now,
        "counts": dict(by_action),
        "items": items,
    }
