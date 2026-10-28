"""Model operations: registry versions and comparisons, model cards, deployment history,
drift reports, retrain jobs (trigger: admin) and challenger approval (admin)."""

from __future__ import annotations

from datetime import UTC, datetime

from apscheduler.triggers.cron import CronTrigger
from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import PlainTextResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from wtpdm.api import models_service, schemas
from wtpdm.api.deps import db
from wtpdm.api.security import Principal, admin, viewer
from wtpdm.db.models import DriftReport, Farm, ModelDeployment, RetrainJob, Sensor
from wtpdm.db.session import session_scope
from wtpdm.ml.train import MIN_IMPROVEMENT
from wtpdm.mlops import retrain
from wtpdm.realtime import drift
from wtpdm.settings import get_settings

router = APIRouter(tags=["mlops"])
FarmPath = Path(pattern=r"^[ABC]$")
# Which drift metrics may trigger a retrain (the others are informational).
RETRAIN_TRIGGERS = {"out_of_support", "residual_shift"}


# ---------------------------------------------------------------- models


@router.get("/models", summary="Registered health models per farm, newest version first")
def list_models(_: Principal = Depends(viewer), s: Session = Depends(db)) -> list[dict]:
    farms = s.scalars(select(Farm.id).order_by(Farm.id)).all()
    return [{"farm": f, "versions": models_service.versions(f)} for f in farms]


@router.get("/models/deployments", response_model=list[schemas.DeploymentOut])
def deployments(
    farm: str | None = Query(default=None, pattern=r"^[ABC]$"),
    _: Principal = Depends(viewer),
    s: Session = Depends(db),
):
    """Promotion history mirrored from the registry (champion / challenger / retired)."""
    q = select(ModelDeployment).order_by(ModelDeployment.promoted_at.desc())
    if farm:
        q = q.where(ModelDeployment.farm_id == farm)
    return s.scalars(q).all()


@router.get("/models/{farm}/versions/{version}")
def model_version(
    farm: str = FarmPath, version: str = Path(pattern=r"^\d+$"), _: Principal = Depends(viewer)
) -> dict:
    return models_service.version(farm, version)


@router.get("/models/{farm}/versions/{version}/comparison")
def model_comparison(
    farm: str = FarmPath, version: str = Path(pattern=r"^\d+$"), _: Principal = Depends(viewer)
) -> dict:
    """The candidate comparison of that training run: detectors on CARE-style event metrics,
    normal-behaviour regressors per sensor, per-component evaluation, RUL (experimental)."""
    return models_service.comparison(farm, version)


@router.get("/models/{farm}/versions/{version}/card", response_class=PlainTextResponse)
def model_card(
    farm: str = FarmPath, version: str = Path(pattern=r"^\d+$"), _: Principal = Depends(viewer)
) -> str:
    """Model card (Markdown)."""
    return models_service.card(farm, version)


@router.get("/models/{farm}/compare")
def compare_versions(
    farm: str = FarmPath,
    a: str | None = Query(default=None, pattern=r"^\d+$", description="Default: champion"),
    b: str | None = Query(default=None, pattern=r"^\d+$", description="Default: challenger"),
    _: Principal = Depends(viewer),
) -> dict:
    """Side-by-side metrics of two versions (default champion vs challenger)."""
    if a is None or b is None:
        by_alias = {alias: v["version"] for v in models_service.versions(farm) for alias in v["aliases"]}
        a = a or by_alias.get("champion")
        b = b or by_alias.get("challenger")
        if a is None or b is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, f"Farm {farm} has no champion and challenger to compare"
            )
    return models_service.compare(farm, a, b)


@router.post("/models/{farm}/versions/{version}/approve", summary="Promote a challenger (admin)")
def approve(
    farm: str = FarmPath, version: str = Path(pattern=r"^\d+$"), user: Principal = Depends(admin)
) -> dict:
    """Human approval path for a challenger that passed the promotion gate but was held
    (auto-promotion off). A version that failed the gate cannot be approved."""
    try:
        retrain.approve(farm, version, user.username)
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return models_service.version(farm, version)


# ---------------------------------------------------------------- drift


def feature_names(s: Session) -> dict[tuple[str, str], str]:
    return {(x.farm_id, f"{x.code}_avg"): x.description for x in s.scalars(select(Sensor))}


def drift_snapshot(s: Session, farm: str, names: dict) -> schemas.DriftSnapshot:
    last = s.scalar(select(func.max(DriftReport.ts)).where(DriftReport.farm_id == farm))
    if last is None:
        return schemas.DriftSnapshot(farm_id=farm, checked_at=None, status="no_data", rows=[])
    rows = [
        schemas.DriftRow(
            metric=r.metric,
            feature=r.feature,
            feature_description=names.get((farm, r.feature or "")),
            value=r.value,
            threshold=r.threshold,
            breached=r.breached,
            triggers_retrain=r.metric in RETRAIN_TRIGGERS,
        )
        for r in s.scalars(
            select(DriftReport)
            .where(DriftReport.farm_id == farm, DriftReport.ts == last)
            .order_by(DriftReport.metric, DriftReport.feature)
        )
    ]
    if any(r.breached and r.triggers_retrain for r in rows):
        state = "drift"
    elif any(r.breached for r in rows):
        state = "warning"
    else:
        state = "ok"
    return schemas.DriftSnapshot(farm_id=farm, checked_at=last, status=state, rows=rows)


@router.get("/drift", response_model=list[schemas.DriftSnapshot])
def drift_status(_: Principal = Depends(viewer), s: Session = Depends(db)):
    """Latest drift check per farm. `drift` = a retrain-triggering metric breached;
    `warning` = only an informational metric (input PSI, alert rate) breached."""
    names = feature_names(s)
    return [drift_snapshot(s, f, names) for f in s.scalars(select(Farm.id).order_by(Farm.id))]


@router.get("/drift/history")
def drift_history(
    farm: str = Query(pattern=r"^[ABC]$"),
    metric: str = Query(pattern=r"^(psi_input|out_of_support|residual_shift|alert_rate)$"),
    feature: str | None = None,
    limit: int = Query(default=500, ge=1, le=5000),
    _: Principal = Depends(viewer),
    s: Session = Depends(db),
) -> dict:
    """One drift metric over successive checks (per feature for input metrics)."""
    q = select(DriftReport).where(DriftReport.farm_id == farm, DriftReport.metric == metric)
    if feature:
        q = q.where(DriftReport.feature == feature)
    rows = list(reversed(s.scalars(q.order_by(DriftReport.ts.desc()).limit(limit)).all()))
    series: dict[str, list] = {}
    for r in rows:
        series.setdefault(r.feature or metric, []).append(
            {"ts": r.ts, "value": r.value, "threshold": r.threshold, "breached": r.breached}
        )
    return {"farm": farm, "metric": metric, "triggers_retrain": metric in RETRAIN_TRIGGERS, "series": series}


@router.get("/drift/policy")
def drift_policy(_: Principal = Depends(viewer)) -> dict:
    settings = get_settings()
    return {
        "interval_minutes": settings.drift_interval_minutes,
        "window_days": settings.drift_window_days,
        "min_rows": drift.MIN_RECENT_ROWS,
        "metrics": {
            "psi_input": {"threshold": drift.PSI_THRESHOLD, "triggers_retrain": False},
            "out_of_support": {"threshold": drift.OUT_OF_SUPPORT_THRESHOLD, "triggers_retrain": True},
            "residual_shift": {"threshold": drift.RESIDUAL_SHIFT_THRESHOLD, "triggers_retrain": True},
            "alert_rate": {
                "threshold": f"max({drift.ALERT_RATE_FACTOR} x reference, {drift.ALERT_RATE_FLOOR})",
                "triggers_retrain": False,
            },
        },
    }


# ---------------------------------------------------------------- retraining


@router.get("/retrain/jobs", response_model=list[schemas.RetrainJobOut])
def retrain_jobs(
    farm: str | None = Query(default=None, pattern=r"^[ABC]$"),
    status_: str | None = Query(default=None, alias="status", pattern=r"^(queued|running|succeeded|failed)$"),
    limit: int = Query(default=50, ge=1, le=500),
    _: Principal = Depends(viewer),
    s: Session = Depends(db),
):
    q = select(RetrainJob).order_by(RetrainJob.requested_at.desc())
    if status_:
        q = q.where(RetrainJob.status == status_)
    if farm:
        q = q.where(RetrainJob.scope["farm"].as_string() == farm)
    return s.scalars(q.limit(limit)).all()


@router.get("/retrain/jobs/{job_id}", response_model=schemas.RetrainJobOut)
def retrain_job(job_id: int, _: Principal = Depends(viewer), s: Session = Depends(db)):
    job = s.get(RetrainJob, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No retrain job {job_id}")
    return job


@router.post("/retrain/jobs", response_model=schemas.RetrainJobOut, status_code=status.HTTP_202_ACCEPTED)
async def request_retrain(body: schemas.RetrainIn, user: Principal = Depends(admin)):
    """Queue a manual retrain of a farm (admin). It runs the full training and evaluation
    protocol and goes through the same promotion gate as scheduled and drift retrains."""
    job_id = await run_in_threadpool(retrain.enqueue, body.farm, "manual", user.username, body.reason)
    if job_id is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"A retrain of farm {body.farm} is already queued or running"
        )
    with session_scope() as s:
        return schemas.RetrainJobOut.model_validate(s.get(RetrainJob, job_id))


@router.get("/retrain/schedule")
def retrain_schedule(_: Principal = Depends(viewer)) -> dict:
    settings = get_settings()
    trigger = CronTrigger.from_crontab(settings.retrain_cron, timezone=UTC)
    return {
        "cron": settings.retrain_cron,
        "timezone": "UTC",
        "next_run": trigger.get_next_fire_time(None, datetime.now(UTC)),
        "drift_cooldown_hours": settings.retrain_cooldown_hours,
        "auto_promote": settings.retrain_auto_promote,
        "promotion_gate": {
            "min_care_score_improvement": MIN_IMPROVEMENT,
            "false_alarms": "no more false-alarm days per turbine-year than the baseline detector allows",
        },
    }
