"""Current state of the fleet at each turbine's replay cursor: latest health per sub-part,
replay position and the active alert. Shared by the fleet/turbine routers and the stream."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from wtpdm.api import schemas
from wtpdm.db.models import Alert, AlertStatus, Component, ReplayState, Subcomponent, Turbine
from wtpdm.realtime.champion import TURBINE

ACTIVE = (AlertStatus.OPEN, AlertStatus.ACKNOWLEDGED)
# A sub-part whose latest score is older than this at the cursor is shown as "no data"
# (e.g. its sensors were missing) rather than with a stale value.
FRESH_HOURS = 6

LATEST_HEALTH = text(
    """
    SELECT DISTINCT ON (h.turbine_id, h.subcomponent_code)
           h.turbine_id, h.subcomponent_code, h.ts, h.health, h.residual_z,
           h.anomaly_score, h.alarm, h.model_version
    FROM health_score h
    JOIN replay_state r ON r.turbine_id = h.turbine_id
    WHERE h.ts <= r.cursor_ts AND h.ts > r.cursor_ts - make_interval(hours => :hours)
      AND (CAST(:turbine AS text) IS NULL OR h.turbine_id = CAST(:turbine AS text))
    ORDER BY h.turbine_id, h.subcomponent_code, h.ts DESC
    """
)


def latest_health(s: Session, turbine_id: str | None = None) -> dict[str, dict[str, dict]]:
    """turbine -> sub-part code (or "turbine") -> latest row at the cursor."""
    out: dict[str, dict[str, dict]] = defaultdict(dict)
    for r in s.execute(LATEST_HEALTH, {"hours": FRESH_HOURS, "turbine": turbine_id}).mappings():
        out[r["turbine_id"]][r["subcomponent_code"]] = dict(r)
    return out


def names(s: Session) -> tuple[dict[str, str], dict[str, Subcomponent]]:
    components = {c.code: c.name for c in s.scalars(select(Component))}
    subparts = {sc.code: sc for sc in s.scalars(select(Subcomponent))}
    return components, subparts


def replay_out(state: ReplayState | None) -> schemas.ReplayOut | None:
    if state is None:
        return None
    return schemas.ReplayOut(
        cursor_ts=state.cursor_ts,
        cycle=state.cycle,
        position=state.position,
        total_rows=state.total_rows,
        progress=round(state.position / state.total_rows, 4) if state.total_rows else 0.0,
        source_event_id=state.source_event_id,
        operating_status=state.operating_status,
        operating_status_label=schemas.OPERATING_STATUS.get(state.operating_status)
        if state.operating_status is not None
        else None,
        updated_at=state.updated_at,
    )


def active_alerts(s: Session, turbine_id: str | None = None) -> dict[str, Alert]:
    q = select(Alert).where(Alert.status.in_(ACTIVE)).order_by(Alert.opened_at)
    if turbine_id:
        q = q.where(Alert.turbine_id == turbine_id)
    return {a.turbine_id: a for a in s.scalars(q)}  # one active alert per turbine


def component_health(rows: dict[str, dict]) -> dict[str, float]:
    worst: dict[str, float] = {}
    for code, r in rows.items():
        if code == TURBINE:
            continue
        comp = code.split(".")[0]
        worst[comp] = min(worst.get(comp, 100.0), round(float(r["health"]), 1))
    return worst


def worst_subpart(rows: dict[str, dict]) -> str | None:
    subs = [(r["health"], code) for code, r in rows.items() if code != TURBINE]
    return min(subs)[1] if subs else None


def summary(
    turbine: Turbine, rows: dict[str, dict], state: ReplayState | None, alert: Alert | None
) -> schemas.TurbineSummary:
    t = rows.get(TURBINE)
    return schemas.TurbineSummary(
        id=turbine.id,
        farm_id=turbine.farm_id,
        name=turbine.name,
        health=round(float(t["health"]), 1) if t else None,
        alarm=t["alarm"] if t else None,
        worst_subcomponent=worst_subpart(rows),
        components=component_health(rows),
        model_version=t["model_version"] if t else None,
        replay=replay_out(state),
        active_alert=schemas.AlertBrief.model_validate(alert) if alert else None,
    )


def fleet(s: Session, farm: str | None = None) -> list[schemas.TurbineSummary]:
    q = select(Turbine).order_by(Turbine.farm_id, Turbine.asset_id)
    if farm:
        q = q.where(Turbine.farm_id == farm)
    turbines = s.scalars(q).all()
    health = latest_health(s)
    states = {r.turbine_id: r for r in s.scalars(select(ReplayState))}
    alerts = active_alerts(s)
    return [summary(t, health.get(t.id, {}), states.get(t.id), alerts.get(t.id)) for t in turbines]


def cursor(s: Session, turbine_id: str) -> datetime | None:
    state = s.get(ReplayState, turbine_id)
    return state.cursor_ts if state else None


def pairs(rows) -> dict[Any, int]:
    """(key, count) result rows -> dict."""
    return {k: v for k, v in rows}
