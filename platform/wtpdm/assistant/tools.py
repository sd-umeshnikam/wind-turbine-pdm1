"""Tools the assistant's LLM may call. All read-only, executed in the requesting user's
database session, returning compact JSON (the model's context is the grounding for its
answer, so every figure it may quote must come from here).

The API routers' functions are reused where their parameters are plain; FastAPI `Query`
defaults are always passed explicitly.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import numpy as np
import pandas as pd
from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from wtpdm.api import live, models_service
from wtpdm.api.routers import turbines as turbines_router
from wtpdm.api.routers.mlops import drift_snapshot, feature_names
from wtpdm.api.security import Principal
from wtpdm.assistant import recommendations
from wtpdm.assistant.knowledge import KnowledgeBase
from wtpdm.db.models import Alert, AlertStatus, Event, Farm, RetrainJob, Sensor, SensorRole, Severity, Turbine
from wtpdm.ml.nbm import expected_value

MAX_ROWS = 10
HEADLINE_METRICS = (
    "care_style_score",
    "event_recall",
    "normal_accuracy",
    "earliness",
    "median_warning_hours",
    "false_alarm_days_per_turbine_year",
)


class ToolError(Exception):
    pass


@dataclass
class ToolContext:
    session: Session
    user: Principal
    knowledge: KnowledgeBase


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict
    handler: Callable[..., Any]

    def spec(self) -> dict:
        return {
            "type": "function",
            "function": {"name": self.name, "description": self.description, "parameters": self.parameters},
        }


def _r(v: Any, digits: int = 2) -> Any:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    return round(float(v), digits) if isinstance(v, int | float) else v


def _turbine(s: Session, turbine_id: str) -> Turbine:
    t = s.get(Turbine, turbine_id.strip().upper())
    if t is None:
        raise ToolError(f"No turbine {turbine_id}. Turbine ids look like A-1, B-7, C-13.")
    return t


def _farm(farm: str | None) -> str | None:
    if farm is None or farm == "":
        return None
    f = farm.strip().upper().removeprefix("FARM ").strip()
    if f not in ("A", "B", "C"):
        raise ToolError("Farm must be A, B or C")
    return f


# ---------------------------------------------------------------- fleet & turbines


HEALTH_SCALE = "health 0-100: 50 = alarm level; below 65 degraded, below 80 watch, 80+ healthy"


def _brief(t) -> dict:
    return {
        "turbine_id": t.id,
        "health": t.health,
        "worst_subcomponent": t.worst_subcomponent,
        "active_alert": t.active_alert.severity.value if t.active_alert else None,
    }


def fleet_status(ctx: ToolContext) -> dict:
    """Whole fleet, with a per-farm breakdown (the model answers farm questions from it)."""
    turbines = live.fleet(ctx.session)
    scored = [t for t in turbines if t.health is not None]
    active = [t.active_alert for t in turbines if t.active_alert]
    by_farm: dict[str, dict] = {}
    for farm in sorted({t.farm_id for t in turbines}):
        of = [t for t in scored if t.farm_id == farm]
        by_farm[farm] = {
            "turbines": sum(1 for t in turbines if t.farm_id == farm),
            "mean_health": _r(sum(t.health or 0 for t in of) / len(of), 1) if of else None,
            "active_alerts": sum(1 for t in turbines if t.farm_id == farm and t.active_alert),
            "lowest": [_brief(t) for t in sorted(of, key=lambda t: t.health or 0)[:3]],
        }
    return {
        "health_scale": HEALTH_SCALE,
        "turbines": len(turbines),
        "reporting": len(scored),
        "mean_health": _r(sum(t.health or 0 for t in scored) / len(scored), 1) if scored else None,
        "in_detector_alarm": [t.id for t in turbines if t.alarm],
        "active_alerts_by_severity": {
            sv.value: len([a for a in active if a and a.severity == sv]) for sv in Severity
        },
        "lowest_health_fleet": [_brief(t) for t in sorted(scored, key=lambda t: t.health or 0)[:8]],
        "by_farm": by_farm,
    }


def turbine_health(ctx: ToolContext, turbine_id: str) -> dict:
    t = _turbine(ctx.session, turbine_id)
    d = turbines_router.turbine_detail(t.id, _=ctx.user, s=ctx.session)
    return {
        "turbine_id": d.id,
        "farm": d.farm_id,
        "health": d.health,
        "detector_alarm": d.alarm,
        "detector_score": d.anomaly_score,
        "model_version": d.model_version,
        "data_time": d.replay.cursor_ts if d.replay else None,
        "operating_status": d.replay.operating_status_label if d.replay else None,
        "active_alert": {
            "id": str(d.active_alert.id),
            "severity": d.active_alert.severity.value,
            "status": d.active_alert.status.value,
            "title": d.active_alert.title,
            "condition_active": d.active_alert.condition_active,
        }
        if d.active_alert
        else None,
        "components": [
            {
                "component": c.name,
                "health": c.health,
                "subparts": [
                    {
                        "code": sp.code,
                        "name": sp.name,
                        "health": sp.health,
                        "residual_z": sp.residual_z,
                        "sensors": len(sp.sensors),  # per-sensor deviations: sensor_deviations
                    }
                    for sp in c.subparts
                ],
            }
            for c in d.components_tree
        ],
    }


def health_trend(ctx: ToolContext, turbine_id: str, subcomponent: str = "turbine", days: int = 7) -> dict:
    t = _turbine(ctx.session, turbine_id)
    days = max(1, min(int(days), 90))
    cursor = live.cursor(ctx.session, t.id)
    if cursor is None:
        raise ToolError("The replay has not reached this turbine yet")
    out = turbines_router.health_trend(
        t.id,
        subcomponents=subcomponent,
        start=cursor - timedelta(days=days),
        end=None,
        points=48,
        _=ctx.user,
        s=ctx.session,
    )
    if not out.series:
        return {"turbine_id": t.id, "subcomponent": subcomponent, "days": days, "points": 0}
    series = out.series[0]
    values = [p.avg for p in series.points if p.avg is not None]
    return {
        "turbine_id": t.id,
        "subcomponent": series.subcomponent,
        "name": series.name,
        "days": days,
        "window": {"from": out.window.start, "to": out.window.end},
        "first": _r(values[0], 1) if values else None,
        "last": _r(values[-1], 1) if values else None,
        "min": _r(min(values), 1) if values else None,
        "max": _r(max(values), 1) if values else None,
        "mean": _r(sum(values) / len(values), 1) if values else None,
        "alarm_buckets": len(series.alarm_ts),
        "samples": [
            {"ts": p.ts, "health": p.avg} for p in series.points[:: max(1, len(series.points) // 12)]
        ],
    }


def _resolve_sensor(s: Session, farm: str, query: str) -> Sensor:
    q = query.strip().removesuffix("_avg")
    exact = s.scalars(select(Sensor).where(Sensor.farm_id == farm, Sensor.code == q)).first()
    if exact:
        return exact
    words = set(re.findall(r"[a-z0-9]+", q.lower()))
    candidates = s.scalars(
        select(Sensor).where(Sensor.farm_id == farm, Sensor.role == SensorRole.MONITORED)
    ).all()
    scored = sorted(
        ((len(words & set(re.findall(r"[a-z0-9]+", c.description.lower()))), c) for c in candidates),
        key=lambda x: -x[0],
    )
    if not scored or scored[0][0] == 0:
        raise ToolError(f"No monitored sensor matching '{query}' on farm {farm}")
    return scored[0][1]


def sensor_deviations(ctx: ToolContext, turbine_id: str, hours: int = 6, top: int = 8) -> dict:
    """Every monitored sensor of the turbine against the champion's expected value over the
    last `hours` of data time, ranked by mean |residual z|."""
    t = _turbine(ctx.session, turbine_id)
    cursor = live.cursor(ctx.session, t.id)
    if cursor is None:
        raise ToolError("The replay has not reached this turbine yet")
    hours = max(1, min(int(hours), 48))
    bundle = models_service.champion(t.farm_id).bundle
    conditions, targets = bundle.conditions, list(bundle.target_models)
    raw = pd.DataFrame(
        ctx.session.execute(
            turbines_router.RAW_TELEMETRY,
            {
                "turbine": t.id,
                "farm": t.farm_id,
                "codes": [c.removesuffix("_avg") for c in {*conditions, *targets}],
                "start": cursor - timedelta(hours=hours),
                "end": cursor,
            },
        ).all(),
        columns=["ts", "code", "value"],
    )
    if raw.empty:
        return {"turbine_id": t.id, "hours": hours, "sensors": []}
    frame = raw.pivot_table(index="ts", columns="code", values="value", aggfunc="first")
    frame.columns = [f"{c}_avg" for c in frame.columns]
    frame = frame.reindex(columns=sorted({*conditions, *targets})).reset_index()
    frame["turbine_id"] = t.id
    subpart_of = {target: sub for sub, names in bundle.targets.items() for target in names}
    rows = []
    for target, tm in bundle.target_models.items():
        actual = frame[target].to_numpy(np.float64)
        if np.isnan(actual).all():
            continue
        expected = expected_value(tm, frame, conditions)
        z = (actual - expected) / tm.resid_std.get(t.id, tm.fallback_std)
        if np.isnan(z).all():
            continue
        rows.append(
            {
                "sensor": target.removesuffix("_avg"),
                "description": bundle.descriptions.get(target, target),
                "unit": bundle.units.get(target),
                "subcomponent": subpart_of.get(target),
                "mean_measured": _r(np.nanmean(actual)),
                "mean_expected": _r(np.nanmean(expected)),
                "mean_residual_z": _r(np.nanmean(z)),
                "latest_residual_z": _r(z[~np.isnan(z)][-1]),
            }
        )
    rows.sort(key=lambda r: -abs(r["mean_residual_z"] or 0))
    return {
        "turbine_id": t.id,
        "model_version": models_service.champion(t.farm_id).label,
        "hours": hours,
        "data_time": cursor,
        "sensors_scored": len(rows),
        "sensors": rows[: max(1, min(int(top), 15))],
    }


def sensor_vs_expected(ctx: ToolContext, turbine_id: str, sensor: str, days: int = 7) -> dict:
    t = _turbine(ctx.session, turbine_id)
    target = _resolve_sensor(ctx.session, t.farm_id, sensor)
    days = max(1, min(int(days), 30))
    cursor = live.cursor(ctx.session, t.id)
    if cursor is None:
        raise ToolError("The replay has not reached this turbine yet")
    out = turbines_router.expected_vs_actual(
        t.id,
        sensor=target.code,
        start=cursor - timedelta(days=days),
        end=None,
        points=96,
        _=ctx.user,
        s=ctx.session,
    )
    pts = [p for p in out.points if p.actual is not None and p.expected is not None]
    zs = [p.residual_z for p in pts if p.residual_z is not None]
    return {
        "turbine_id": t.id,
        "sensor": target.code,
        "description": target.description,
        "unit": target.unit,
        "subcomponent": target.subcomponent_code,
        "model_version": out.model_version,
        "regressor": out.nbm_candidate,
        "days": days,
        "mean_measured": _r(np.mean([p.actual for p in pts])) if pts else None,
        "mean_expected": _r(np.mean([p.expected for p in pts])) if pts else None,
        "latest": {
            "ts": pts[-1].ts,
            "measured": pts[-1].actual,
            "expected": pts[-1].expected,
            "residual_z": pts[-1].residual_z,
        }
        if pts
        else None,
        "mean_residual_z": _r(np.mean(zs)) if zs else None,
        "max_abs_residual_z": _r(max(abs(z) for z in zs)) if zs else None,
    }


# ---------------------------------------------------------------- alerts


def list_alerts(
    ctx: ToolContext,
    status: str = "active",
    severity: str | None = None,
    farm: str | None = None,
    turbine_id: str | None = None,
    assignee: str | None = None,
    limit: int = 10,
) -> dict:
    q = select(Alert, Turbine.farm_id).join(Turbine, Turbine.id == Alert.turbine_id)
    if status == "active":
        q = q.where(Alert.status.in_(live.ACTIVE))
    elif status in {s.value for s in AlertStatus}:
        q = q.where(Alert.status == AlertStatus(status))
    elif status != "all":
        raise ToolError("status must be active, open, acknowledged, resolved or all")
    if severity:
        q = q.where(Alert.severity == Severity(severity.lower()))
    if (f := _farm(farm)) is not None:
        q = q.where(Turbine.farm_id == f)
    if turbine_id:
        q = q.where(Alert.turbine_id == turbine_id.strip().upper())
    if assignee == "me":
        q = q.where(Alert.assignee == ctx.user.username)
    elif assignee == "none":
        q = q.where(Alert.assignee.is_(None))
    elif assignee:
        q = q.where(Alert.assignee == assignee)
    rows = ctx.session.execute(
        q.order_by(Alert.severity.desc(), Alert.opened_at.desc()).limit(min(int(limit), MAX_ROWS))
    ).all()
    return {
        "count": len(rows),
        "alerts": [
            {
                "id": str(a.id),
                "turbine_id": a.turbine_id,
                "farm": farm_id,
                "severity": a.severity.value,
                "status": a.status.value,
                "title": a.title,
                "subcomponent": a.subcomponent_code,
                "condition_active": a.condition_active,
                "assignee": a.assignee,
                "opened_at": a.opened_at,
                "data_time": a.data_ts,
            }
            for a, farm_id in rows
        ],
    }


def _alert(s: Session, alert_id: str) -> Alert:
    try:
        key = uuid.UUID(alert_id.strip())
    except ValueError as exc:
        raise ToolError("alert_id must be an alert UUID (use list_alerts to find it)") from exc
    alert = s.get(Alert, key)
    if alert is None:
        raise ToolError(f"No alert {alert_id}")
    return alert


def alert_details(ctx: ToolContext, alert_id: str) -> dict:
    a = _alert(ctx.session, alert_id)
    return {
        "id": str(a.id),
        "turbine_id": a.turbine_id,
        "component": a.component_code,
        "subcomponent": a.subcomponent_code,
        "severity": a.severity.value,
        "status": a.status.value,
        "title": a.title,
        "message": a.message,
        "drivers": a.drivers,
        "model_version": a.model_version,
        "condition_active": a.condition_active,
        "assignee": a.assignee,
        "acknowledged_by": a.acknowledged_by,
        "opened_at": a.opened_at,
        "data_time_first": a.data_ts,
        "data_time_last": a.last_data_ts,
        "notes": [{"author": n.author, "body": n.body, "at": n.created_at} for n in a.notes][-5:],
    }


def maintenance_recommendation(
    ctx: ToolContext, alert_id: str | None = None, turbine_id: str | None = None
) -> dict:
    if alert_id:
        return recommendations.for_alert(ctx.session, _alert(ctx.session, alert_id))
    if turbine_id:
        return recommendations.for_turbine(ctx.session, _turbine(ctx.session, turbine_id).id)
    raise ToolError("Give alert_id or turbine_id")


# ---------------------------------------------------------------- models, drift, events, knowledge


def model_overview(ctx: ToolContext, farm: str) -> dict:
    f = _farm(farm)
    if f is None:
        raise ToolError("Give a farm: A, B or C")
    versions = models_service.versions(f)

    def brief(v: dict) -> dict:
        return {
            "version": v["version"],
            "aliases": v["aliases"],
            "detector": v["selected_detector"],
            "trigger": v["trigger"],
            "gate": v["gate"],
            "registered": v["created_at"],
            "metrics": {m: _r(v["metrics"].get(m), 4) for m in HEADLINE_METRICS},
        }

    return {
        "model": f"wtpdm-health-{f}",
        "champion": next((brief(v) for v in versions if "champion" in v["aliases"]), None),
        "challenger": next(
            (brief(v) for v in versions if "challenger" in v["aliases"] and "champion" not in v["aliases"]),
            None,
        ),
        "versions": len(versions),
        "metric_notes": "care_style_score = mean of event F1, accuracy on normal events and earliness; higher is better. "
        "false_alarm_days_per_turbine_year: lower is better.",
    }


def drift_status(ctx: ToolContext, farm: str | None = None) -> dict:
    names = feature_names(ctx.session)
    farms = [f] if (f := _farm(farm)) else list(ctx.session.scalars(select(Farm.id).order_by(Farm.id)))
    out = []
    for fid in farms:
        snap = drift_snapshot(ctx.session, fid, names)
        out.append(
            {
                "farm": fid,
                "status": snap.status,
                "checked_at": snap.checked_at,
                "breached": [
                    {
                        "metric": r.metric,
                        "feature": r.feature_description or r.feature,
                        "value": r.value,
                        "threshold": r.threshold,
                        "triggers_retrain": r.triggers_retrain,
                    }
                    for r in snap.rows
                    if r.breached
                ],
                "metrics_checked": len(snap.rows),
            }
        )
    return {"farms": out}


def retrain_jobs(ctx: ToolContext, farm: str | None = None, limit: int = 5) -> dict:
    q = select(RetrainJob).order_by(RetrainJob.requested_at.desc())
    if (f := _farm(farm)) is not None:
        q = q.where(RetrainJob.scope["farm"].as_string() == f)
    jobs = ctx.session.scalars(q.limit(min(int(limit), MAX_ROWS))).all()
    return {
        "jobs": [
            {
                "id": j.id,
                "farm": (j.scope or {}).get("farm"),
                "trigger": j.trigger,
                "status": j.status,
                "reason": (j.scope or {}).get("reason"),
                "requested_at": j.requested_at,
                "finished_at": j.finished_at,
                "version": ((j.result or {}).get("registry") or {}).get("version"),
                "promoted": ((j.result or {}).get("registry") or {}).get("promoted"),
                "gate_reasons": ((j.result or {}).get("registry") or {}).get("gate_reasons"),
                "care_style_score": ((j.result or {}).get("metrics") or {}).get("care_style_score"),
            }
            for j in jobs
        ]
    }


def labelled_events(
    ctx: ToolContext,
    turbine_id: str | None = None,
    farm: str | None = None,
    label: str | None = None,
    component: str | None = None,
) -> dict:
    q = select(Event).order_by(Event.farm_id, Event.source_event_id)
    if turbine_id:
        q = q.where(Event.turbine_id == _turbine(ctx.session, turbine_id).id)
    if (f := _farm(farm)) is not None:
        q = q.where(Event.farm_id == f)
    if label:
        q = q.where(Event.label == label.lower())
    if component:
        q = q.where(Event.component_code == component.strip().lower())
    events = ctx.session.scalars(q).all()
    return {
        "count": len(events),
        "events": [
            {
                "event_id": e.source_event_id,
                "turbine_id": e.turbine_id,
                "label": e.label.value,
                "description": e.description,
                "component": e.component_code,
                "event_start": e.event_start,
                "event_end": e.event_end,
            }
            for e in events[:25]
        ],
        "truncated": len(events) > 25,
    }


def search_knowledge(ctx: ToolContext, query: str) -> dict:
    hits = ctx.knowledge.search(query, k=4)
    return {
        "results": [
            {
                "source": h.chunk.source,
                "title": h.chunk.title,
                "ref": h.chunk.ref,
                "text": h.chunk.text[:1500],
            }
            for h in hits
        ]
    }


def find_turbines(ctx: ToolContext, query: str) -> dict:
    """Turbines whose active alert or weakest sub-part matches a component word."""
    like = f"%{query.strip()}%"
    rows = ctx.session.scalars(
        select(Alert).where(
            Alert.status.in_(live.ACTIVE),
            or_(
                Alert.title.ilike(like), Alert.component_code.ilike(like), Alert.subcomponent_code.ilike(like)
            ),
        )
    ).all()
    return {
        "active_alerts": [
            {"turbine_id": a.turbine_id, "id": str(a.id), "severity": a.severity.value, "title": a.title}
            for a in rows[:MAX_ROWS]
        ]
    }


def _obj(props: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props, "required": required or [], "additionalProperties": False}


FARM = {"type": "string", "enum": ["A", "B", "C"], "description": "Wind farm"}
TURBINE = {"type": "string", "description": "Turbine id such as A-1, B-7, C-13"}

TOOLS: dict[str, Tool] = {
    t.name: t
    for t in [
        Tool(
            "fleet_status",
            "Fleet KPIs now: turbines reporting, mean health, detector alarms, active alerts by severity, the lowest-health turbines of the whole fleet, and a per-farm breakdown.",
            _obj({}),
            fleet_status,
        ),
        Tool(
            "turbine_health",
            "Current health of one turbine: every component and sub-part with health (0-100, 50 = alarm level), residual z, its sensors, the active alert and operating status.",
            _obj({"turbine_id": TURBINE}, ["turbine_id"]),
            turbine_health,
        ),
        Tool(
            "health_trend",
            "Health of a turbine or one sub-part over the last N data-days: first/last/min/max/mean and samples. subcomponent is 'turbine' or a code like gearbox.oil.",
            _obj(
                {
                    "turbine_id": TURBINE,
                    "subcomponent": {"type": "string"},
                    "days": {"type": "integer", "minimum": 1, "maximum": 90},
                },
                ["turbine_id"],
            ),
            health_trend,
        ),
        Tool(
            "sensor_deviations",
            "Which sensors of a turbine deviate most from expected (normal-behaviour model) over the last N data-hours, ranked by mean standardised residual z.",
            _obj(
                {
                    "turbine_id": TURBINE,
                    "hours": {"type": "integer", "minimum": 1, "maximum": 48},
                    "top": {"type": "integer", "minimum": 1, "maximum": 15},
                },
                ["turbine_id"],
            ),
            sensor_deviations,
        ),
        Tool(
            "sensor_vs_expected",
            "Measured vs expected (normal-behaviour model) for one monitored sensor of a turbine over N data-days, with the standardised residual. sensor = code (sensor_11) or words of its description.",
            _obj(
                {
                    "turbine_id": TURBINE,
                    "sensor": {"type": "string"},
                    "days": {"type": "integer", "minimum": 1, "maximum": 30},
                },
                ["turbine_id", "sensor"],
            ),
            sensor_vs_expected,
        ),
        Tool(
            "list_alerts",
            "Alerts with filters. status: active (default), open, acknowledged, resolved, all. assignee: a username, 'me' or 'none'. Most severe first.",
            _obj(
                {
                    "status": {"type": "string"},
                    "severity": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
                    "farm": FARM,
                    "turbine_id": TURBINE,
                    "assignee": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 10},
                }
            ),
            list_alerts,
        ),
        Tool(
            "alert_details",
            "One alert: message, drivers (sensors with the largest deviation), severity, status, owner, data times, latest notes.",
            _obj({"alert_id": {"type": "string"}}, ["alert_id"]),
            alert_details,
        ),
        Tool(
            "maintenance_recommendation",
            "Advisory maintenance recommendation from the playbook for an alert (preferred) or a turbine: implicated sub-parts, evidence, likely failure modes, checks, actions and the response window. In the answer, name each failure mode with its id (e.g. GBX-OIL-1) so engineers can look it up.",
            _obj({"alert_id": {"type": "string"}, "turbine_id": TURBINE}),
            maintenance_recommendation,
        ),
        Tool(
            "model_overview",
            "Champion and challenger health model of a farm with evaluation metrics and promotion-gate result.",
            _obj({"farm": FARM}, ["farm"]),
            model_overview,
        ),
        Tool(
            "drift_status",
            "Latest drift check per farm with breached metrics.",
            _obj({"farm": FARM}),
            drift_status,
        ),
        Tool(
            "retrain_jobs",
            "Recent retrain jobs (schedule, drift, manual) with outcome: promoted, or held with the gate reasons.",
            _obj({"farm": FARM, "limit": {"type": "integer", "minimum": 1, "maximum": 10}}),
            retrain_jobs,
        ),
        Tool(
            "labelled_events",
            "Labelled CARE events (anomaly = a real fault with its description, or normal) per turbine, farm and/or component (e.g. gearbox, hydraulics, pitch). Use this for questions about past faults or the evaluation data.",
            _obj(
                {
                    "turbine_id": TURBINE,
                    "farm": FARM,
                    "label": {"type": "string", "enum": ["anomaly", "normal"]},
                    "component": {
                        "type": "string",
                        "description": "Component code, e.g. gearbox, generator, hydraulics, pitch",
                    },
                }
            ),
            labelled_events,
        ),
        Tool(
            "find_turbines",
            "Turbines whose ACTIVE alert concerns a component, e.g. gearbox or hydraulics (current alerts only, not past events).",
            _obj({"query": {"type": "string"}}, ["query"]),
            find_turbines,
        ),
        Tool(
            "search_knowledge",
            "Search the platform guide (how health, alerts, drift, retraining and evaluation work), the maintenance playbook and the champion model cards.",
            _obj({"query": {"type": "string"}}, ["query"]),
            search_knowledge,
        ),
    ]
}


def specs() -> list[dict]:
    return [t.spec() for t in TOOLS.values()]


def run(ctx: ToolContext, name: str, arguments: str) -> tuple[bool, dict]:
    """Execute a tool call; errors become a result the model can read and recover from."""
    tool = TOOLS.get(name)
    if tool is None:
        return False, {"error": f"Unknown tool {name}"}
    try:
        args = json.loads(arguments or "{}")
        if not isinstance(args, dict):
            raise ToolError("Arguments must be a JSON object")
        args = {k: v for k, v in args.items() if v is not None}
        return True, tool.handler(ctx, **args)
    except ToolError as exc:
        return False, {"error": str(exc)}
    except HTTPException as exc:
        return False, {"error": str(exc.detail)}
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        return False, {"error": f"Invalid arguments for {name}: {exc}"}


def dumps(payload: Any) -> str:
    return json.dumps(payload, default=str, separators=(",", ":"))
