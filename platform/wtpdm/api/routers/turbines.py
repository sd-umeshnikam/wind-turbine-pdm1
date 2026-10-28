"""One turbine: component / sub-part health, health trends, sensor telemetry, expected vs
actual (normal-behaviour model), CARE events."""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from wtpdm.api import live, models_service, schemas, timewindow
from wtpdm.api.deps import db
from wtpdm.api.security import Principal, viewer
from wtpdm.db.models import Event, ReplayState, Sensor, SensorRole, Turbine
from wtpdm.ml.nbm import expected_value
from wtpdm.realtime.champion import TURBINE

router = APIRouter(prefix="/turbines", tags=["turbines"])

HEALTH_SERIES = text(
    """
    SELECT subcomponent_code AS key,
           time_bucket(make_interval(secs => :bucket), ts) AS bucket,
           avg(health) AS avg, min(health) AS min, max(health) AS max, bool_or(alarm) AS alarm
    FROM health_score
    WHERE turbine_id = :turbine AND subcomponent_code = ANY(:codes) AND ts > :start AND ts <= :end
    GROUP BY 1, 2 ORDER BY 1, 2
    """
)

TELEMETRY_SERIES = text(
    """
    SELECT sensor_id AS key,
           time_bucket(make_interval(secs => :bucket), ts) AS bucket,
           avg(value) AS avg, min(value) AS min, max(value) AS max
    FROM telemetry
    WHERE turbine_id = :turbine AND sensor_id = ANY(:ids) AND ts > :start AND ts <= :end
    GROUP BY 1, 2 ORDER BY 1, 2
    """
)

RAW_TELEMETRY = text(
    """
    SELECT t.ts, s.code, t.value
    FROM telemetry t JOIN sensor s ON s.id = t.sensor_id
    WHERE t.turbine_id = :turbine AND s.farm_id = :farm AND s.code = ANY(:codes)
      AND t.ts > :start AND t.ts <= :end
    """
)


def _turbine(s: Session, turbine_id: str) -> Turbine:
    turbine = s.get(Turbine, turbine_id)
    if turbine is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No turbine {turbine_id}")
    return turbine


def _codes(raw: str | None) -> list[str]:
    return [c.strip() for c in (raw or "").split(",") if c.strip()]


def _window_out(w: timewindow.Window) -> schemas.WindowOut:
    return schemas.WindowOut(start=w.start, end=w.end, bucket_seconds=w.bucket_seconds)


def _grouped(rows) -> dict:
    out: dict = {}
    for r in rows.mappings():
        out.setdefault(r["key"], []).append(r)
    return out


def _round(v: float | None, digits: int = 3) -> float | None:
    return None if v is None or (isinstance(v, float) and np.isnan(v)) else round(float(v), digits)


@router.get("", response_model=list[schemas.TurbineSummary])
def list_turbines(
    farm: str | None = Query(default=None, pattern=r"^[ABC]$"),
    _: Principal = Depends(viewer),
    s: Session = Depends(db),
):
    return live.fleet(s, farm)


@router.get("/{turbine_id}", response_model=schemas.TurbineDetail)
def turbine_detail(turbine_id: str, _: Principal = Depends(viewer), s: Session = Depends(db)):
    """Health of every component and sub-part at the turbine's replay cursor, with the
    sensors that feed each sub-part."""
    turbine = _turbine(s, turbine_id)
    rows = live.latest_health(s, turbine_id).get(turbine_id, {})
    state = s.get(ReplayState, turbine_id)
    alert = live.active_alerts(s, turbine_id).get(turbine_id)
    base = live.summary(turbine, rows, state, alert)
    comp_names, subparts = live.names(s)

    sensors: dict[str, list[schemas.SensorOut]] = {}
    for sensor in s.scalars(
        select(Sensor)
        .where(Sensor.farm_id == turbine.farm_id, Sensor.role == SensorRole.MONITORED)
        .order_by(Sensor.id)
    ):
        sensors.setdefault(sensor.subcomponent_code or "", []).append(
            schemas.SensorOut.model_validate(sensor)
        )

    tree: dict[str, schemas.ComponentHealth] = {}
    for code in sorted(set(sensors) | {c for c in rows if c != TURBINE}):
        if code not in subparts:
            continue
        r = rows.get(code)
        comp = subparts[code].component_code
        node = tree.setdefault(
            comp,
            schemas.ComponentHealth(code=comp, name=comp_names.get(comp, comp), health=None, subparts=[]),
        )
        health = _round(r["health"], 1) if r else None
        node.subparts.append(
            schemas.SubpartHealth(
                code=code,
                name=subparts[code].name,
                health=health,
                residual_z=_round(r["residual_z"], 2) if r else None,
                ts=r["ts"] if r else None,
                sensors=sensors.get(code, []),
            )
        )
        if health is not None:
            node.health = health if node.health is None else min(node.health, health)
    ordered = sorted(tree.values(), key=lambda c: (c.health is None, c.health if c.health is not None else 0))
    t = rows.get(TURBINE)
    return schemas.TurbineDetail(
        **base.model_dump(),
        asset_id=turbine.asset_id,
        anomaly_score=_round(t["anomaly_score"], 4) if t else None,
        components_tree=ordered,
    )


@router.get("/{turbine_id}/health", response_model=schemas.HealthSeriesOut)
def health_trend(
    turbine_id: str,
    subcomponents: str | None = Query(
        default=None, description="Comma-separated sub-part codes; default: turbine + every sub-part"
    ),
    start: datetime | None = Query(default=None, alias="from"),
    end: datetime | None = Query(default=None, alias="to"),
    points: int = Query(default=500, ge=10, le=timewindow.MAX_POINTS),
    _: Principal = Depends(viewer),
    s: Session = Depends(db),
):
    """Health over time (bucketed avg/min/max) on the turbine's data clock. The turbine
    series also lists the buckets in which the detector was in alarm."""
    _turbine(s, turbine_id)
    w = timewindow.resolve(live.cursor(s, turbine_id), start, end, points)
    subparts = live.names(s)[1]
    codes = _codes(subcomponents) or [TURBINE, *subparts]
    unknown = [c for c in codes if c != TURBINE and c not in subparts]
    if unknown:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown sub-parts: {unknown}")
    grouped = _grouped(
        s.execute(
            HEALTH_SERIES,
            {
                "turbine": turbine_id,
                "codes": codes,
                "bucket": w.bucket_seconds,
                "start": w.start,
                "end": w.end,
            },
        )
    )
    series = [
        schemas.HealthSeries(
            subcomponent=code,
            name="Turbine" if code == TURBINE else subparts[code].name,
            points=[
                schemas.SeriesPoint(
                    ts=r["bucket"], avg=_round(r["avg"], 2), min=_round(r["min"], 2), max=_round(r["max"], 2)
                )
                for r in grouped[code]
            ],
            alarm_ts=[r["bucket"] for r in grouped[code] if r["alarm"]] if code == TURBINE else [],
        )
        for code in codes
        if code in grouped
    ]
    return schemas.HealthSeriesOut(turbine_id=turbine_id, window=_window_out(w), series=series)


@router.get("/{turbine_id}/telemetry", response_model=schemas.TelemetryOut)
def telemetry(
    turbine_id: str,
    sensors: str = Query(description="Comma-separated sensor codes, e.g. sensor_11,power_30"),
    start: datetime | None = Query(default=None, alias="from"),
    end: datetime | None = Query(default=None, alias="to"),
    points: int = Query(default=500, ge=10, le=timewindow.MAX_POINTS),
    _: Principal = Depends(viewer),
    s: Session = Depends(db),
):
    """Replayed SCADA readings (10-minute averages), downsampled to at most `points`
    buckets per sensor with the min/max envelope kept."""
    turbine = _turbine(s, turbine_id)
    codes = _codes(sensors)
    if not codes or len(codes) > 12:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Give 1-12 sensor codes")
    catalog = {
        x.code: x
        for x in s.scalars(select(Sensor).where(Sensor.farm_id == turbine.farm_id, Sensor.code.in_(codes)))
    }
    unknown = [c for c in codes if c not in catalog]
    if unknown:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown sensors for farm {turbine.farm_id}: {unknown}"
        )
    w = timewindow.resolve(live.cursor(s, turbine_id), start, end, points)
    grouped = _grouped(
        s.execute(
            TELEMETRY_SERIES,
            {
                "turbine": turbine_id,
                "ids": [catalog[c].id for c in codes],
                "bucket": w.bucket_seconds,
                "start": w.start,
                "end": w.end,
            },
        )
    )
    return schemas.TelemetryOut(
        turbine_id=turbine_id,
        window=_window_out(w),
        series=[
            schemas.SensorSeries(
                code=c,
                description=catalog[c].description,
                unit=catalog[c].unit,
                points=[
                    schemas.SeriesPoint(
                        ts=r["bucket"], avg=_round(r["avg"]), min=_round(r["min"]), max=_round(r["max"])
                    )
                    for r in grouped.get(catalog[c].id, [])
                ],
            )
            for c in codes
        ],
    )


@router.get("/{turbine_id}/expected", response_model=schemas.ExpectedOut)
def expected_vs_actual(
    turbine_id: str,
    sensor: str = Query(description="A monitored sensor code, e.g. sensor_11"),
    start: datetime | None = Query(default=None, alias="from"),
    end: datetime | None = Query(default=None, alias="to"),
    points: int = Query(default=500, ge=10, le=timewindow.MAX_POINTS),
    _: Principal = Depends(viewer),
    s: Session = Depends(db),
):
    """Measured value vs what the champion's normal-behaviour model expects a healthy
    turbine to read under the same operating conditions, with the standardised residual.
    Computed on demand from the replayed telemetry (window up to 31 days)."""
    turbine = _turbine(s, turbine_id)
    target_sensor = s.scalars(
        select(Sensor).where(Sensor.farm_id == turbine.farm_id, Sensor.code == sensor)
    ).first()
    if target_sensor is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No sensor {sensor} on farm {turbine.farm_id}")
    model = models_service.champion(turbine.farm_id)
    target = f"{sensor}_avg"
    tm = model.bundle.target_models.get(target)
    if tm is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"{sensor} has no normal-behaviour model in {model.label}"
            " (not monitored, or excluded in training)",
        )
    w = timewindow.resolve(live.cursor(s, turbine_id), start, end, points, max_span=timedelta(days=31))
    conditions = model.bundle.conditions
    codes = [c.removesuffix("_avg") for c in {*conditions, target}]
    raw = pd.DataFrame(
        s.execute(
            RAW_TELEMETRY,
            {"turbine": turbine_id, "farm": turbine.farm_id, "codes": codes, "start": w.start, "end": w.end},
        ).all(),
        columns=["ts", "code", "value"],
    )
    points_out: list[schemas.ExpectedPoint] = []
    if len(raw):
        frame = raw.pivot_table(index="ts", columns="code", values="value", aggfunc="first")
        frame.columns = [f"{c}_avg" for c in frame.columns]
        frame = frame.reindex(columns=sorted({*conditions, target})).reset_index()
        frame["turbine_id"] = turbine_id
        actual = frame[target].to_numpy(np.float64)
        expected = expected_value(tm, frame, conditions)
        std = tm.resid_std.get(turbine_id, tm.fallback_std)
        df = pd.DataFrame(
            {
                "ts": frame["ts"],
                "actual": actual,
                "expected": expected,
                "residual_z": (actual - expected) / std,
            }
        )
        df = df.set_index("ts").resample(w.bucket, origin="epoch").mean().dropna(how="all").reset_index()
        points_out = [
            schemas.ExpectedPoint(
                ts=r.ts,
                actual=_round(r.actual),
                expected=_round(r.expected),
                residual_z=_round(r.residual_z, 2),
            )
            for r in df.itertuples()
        ]
    return schemas.ExpectedOut(
        turbine_id=turbine_id,
        sensor=schemas.SensorOut.model_validate(target_sensor),
        model_version=model.label,
        nbm_candidate=tm.candidate,
        window=_window_out(w),
        points=points_out,
    )


@router.get("/{turbine_id}/events", response_model=list[schemas.EventOut])
def events(turbine_id: str, _: Principal = Depends(viewer), s: Session = Depends(db)):
    """The CARE events of this turbine (labelled outcomes its replay timeline leads into)."""
    _turbine(s, turbine_id)
    return s.scalars(select(Event).where(Event.turbine_id == turbine_id).order_by(Event.event_start)).all()
