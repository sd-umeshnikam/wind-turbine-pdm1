"""Farms and fleet overview."""

from __future__ import annotations

from collections import Counter

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from wtpdm.api import live, schemas
from wtpdm.api.deps import db
from wtpdm.api.security import Principal, viewer
from wtpdm.db.models import Alert, Event, Farm, ModelDeployment, Sensor, Turbine
from wtpdm.settings import get_settings

router = APIRouter(tags=["fleet"])


@router.get("/farms", response_model=list[schemas.FarmOut])
def farms(_: Principal = Depends(viewer), s: Session = Depends(db)):
    turbines = live.pairs(s.execute(select(Turbine.farm_id, func.count()).group_by(Turbine.farm_id)).all())
    sensors = live.pairs(s.execute(select(Sensor.farm_id, func.count()).group_by(Sensor.farm_id)).all())
    events: dict[str, dict[str, int]] = {}
    for farm_id, label, n in s.execute(
        select(Event.farm_id, Event.label, func.count()).group_by(Event.farm_id, Event.label)
    ):
        events.setdefault(farm_id, {})[label.value] = n
    champions = {
        d.farm_id: f"{d.model_name}/{d.version}"
        for d in s.scalars(select(ModelDeployment).where(ModelDeployment.alias == "champion"))
    }
    alerts = live.pairs(
        s.execute(
            select(Turbine.farm_id, func.count())
            .join(Alert, Alert.turbine_id == Turbine.id)
            .where(Alert.status.in_(live.ACTIVE))
            .group_by(Turbine.farm_id)
        ).all()
    )
    return [
        schemas.FarmOut(
            id=f.id,
            name=f.name,
            description=f.description,
            turbines=turbines.get(f.id, 0),
            sensors=sensors.get(f.id, 0),
            events=events.get(f.id, {}),
            champion=champions.get(f.id),
            active_alerts=alerts.get(f.id, 0),
        )
        for f in s.scalars(select(Farm).order_by(Farm.id))
    ]


@router.get("/fleet", response_model=schemas.FleetOut)
def fleet(
    farm: str | None = Query(default=None, pattern=r"^[ABC]$"),
    _: Principal = Depends(viewer),
    s: Session = Depends(db),
):
    """Every turbine at its replay cursor, with fleet KPIs."""
    turbines = live.fleet(s, farm)
    healths = [t.health for t in turbines if t.health is not None]
    active = [t.active_alert for t in turbines if t.active_alert is not None]
    severity = Counter(a.severity.value for a in active)
    kpis = schemas.FleetKpis(
        turbines=len(turbines),
        reporting=len(healths),
        in_alarm=sum(1 for t in turbines if t.alarm),
        mean_health=round(sum(healths) / len(healths), 1) if healths else None,
        active_alerts={k: severity.get(k, 0) for k in ("critical", "high", "medium", "low")},
        unacknowledged=sum(1 for a in active if a.status.value == "open"),
    )
    return schemas.FleetOut(kpis=kpis, turbines=turbines, replay_speed=get_settings().replay_speed)
