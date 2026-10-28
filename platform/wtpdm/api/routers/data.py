"""Data catalog and quality: sensors with real names and units, sub-part coverage, the
ingest data-quality report, CARE events, replay status, and the audit log."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from wtpdm import catalog
from wtpdm.api import live, schemas
from wtpdm.api.deps import db
from wtpdm.api.security import Principal, engineer, viewer
from wtpdm.db.models import AuditLog, Event, EventLabel, ReplayState, Sensor, SensorRole, Turbine
from wtpdm.settings import get_settings

router = APIRouter(tags=["data"])


def _lake_json(reader, farm: str):
    try:
        return reader(get_settings().lake_root, farm)
    except FileNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Farm {farm} has not been ingested") from exc


@router.get("/data/sensors", response_model=list[schemas.SensorOut])
def sensors(
    farm: str = Query(pattern=r"^[ABC]$"),
    role: SensorRole | None = None,
    _: Principal = Depends(viewer),
    s: Session = Depends(db),
):
    q = select(Sensor).where(Sensor.farm_id == farm).order_by(Sensor.id)
    if role:
        q = q.where(Sensor.role == role)
    return s.scalars(q).all()


@router.get("/data/coverage")
def coverage(_: Principal = Depends(viewer), s: Session = Depends(db)) -> dict:
    """Monitored sensors per farm x component x sub-part (0 = the farm cannot see it)."""
    subparts = live.names(s)[1]
    farms = catalog.available_farms(get_settings().lake_root)
    matrix = {f: _lake_json(catalog.coverage, f) for f in farms}
    return {
        "farms": farms,
        "subparts": [
            {"code": c, "name": sp.name, "component": sp.component_code} for c, sp in subparts.items()
        ],
        "matrix": matrix,
    }


@router.get("/data/quality")
def quality(
    farm: str = Query(pattern=r"^[ABC]$"), _: Principal = Depends(viewer), s: Session = Depends(db)
) -> dict:
    """Ingest data-quality report per sensor: missing, stuck and out-of-range shares (%)."""
    report = _lake_json(catalog.data_quality, farm)
    names = {x.code: (x.description, x.unit) for x in s.scalars(select(Sensor).where(Sensor.farm_id == farm))}
    rows = [
        {
            "sensor": code,
            "description": names.get(code, (None, None))[0],
            "unit": names.get(code, (None, None))[1],
            **m,
        }
        for code, m in sorted(report.items())
    ]
    return {
        "farm": farm,
        "data_version": catalog.data_version(get_settings().lake_root, farm),
        "sensors": rows,
    }


@router.get("/data/events", response_model=list[schemas.EventOut])
def events(
    farm: str | None = Query(default=None, pattern=r"^[ABC]$"),
    label: EventLabel | None = None,
    _: Principal = Depends(viewer),
    s: Session = Depends(db),
):
    q = select(Event).order_by(Event.farm_id, Event.source_event_id)
    if farm:
        q = q.where(Event.farm_id == farm)
    if label:
        q = q.where(Event.label == label)
    return s.scalars(q).all()


@router.get("/replay")
def replay(_: Principal = Depends(viewer), s: Session = Depends(db)) -> dict:
    """Status of the live replay of real SCADA history (each turbine on its own data clock)."""
    settings = get_settings()
    rows = s.execute(
        select(ReplayState, Turbine.farm_id)
        .join(Turbine, Turbine.id == ReplayState.turbine_id)
        .order_by(Turbine.farm_id, Turbine.asset_id)
    ).all()
    last_update = max((st.updated_at for st, _farm in rows), default=None)
    return {
        "mode": "replay of recorded SCADA history",
        "speed": settings.replay_speed,
        "tick_seconds": settings.replay_tick_seconds,
        "last_update": last_update,
        "turbines": [
            {"turbine_id": st.turbine_id, "farm_id": farm, **out.model_dump()}
            for st, farm in rows
            if (out := live.replay_out(st)) is not None
        ],
    }


@router.get("/audit", response_model=dict)
def audit_log(
    entity: str | None = None,
    entity_id: str | None = None,
    actor: str | None = None,
    action: str | None = Query(
        default=None, description="Exact action, or a prefix ending in `.` (e.g. `alert.`)"
    ),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    _: Principal = Depends(engineer),
    s: Session = Depends(db),
):
    q = select(AuditLog)
    if entity:
        q = q.where(AuditLog.entity == entity)
    if entity_id:
        q = q.where(AuditLog.entity_id == entity_id)
    if actor:
        q = q.where(AuditLog.actor == actor)
    if action:
        q = q.where(AuditLog.action.startswith(action) if action.endswith(".") else AuditLog.action == action)
    total = s.scalar(select(func.count()).select_from(q.subquery())) or 0
    items = s.scalars(q.order_by(AuditLog.id.desc()).limit(limit).offset(offset)).all()
    return {"total": total, "items": [schemas.AuditOut.model_validate(a) for a in items]}
