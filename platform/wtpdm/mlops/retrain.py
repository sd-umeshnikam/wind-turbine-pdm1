"""Retraining orchestration: a durable job queue in the platform DB and a runner.

    python -m wtpdm.mlops.retrain run                      # the runner service
    python -m wtpdm.mlops.retrain enqueue --farm A         # manual request
    python -m wtpdm.mlops.retrain approve --farm A --version 3

Jobs come from three triggers: `schedule` (cron in the worker), `drift` (the drift
monitor) and `manual` (API / CLI). At most one job per farm is queued or running; drift
requests are additionally rate-limited per farm (`retrain_cooldown_hours`).

A job runs the full training protocol of `wtpdm.ml.train` - same data, same evaluation,
same promotion gate - and registers the result as the challenger. The challenger becomes
champion automatically when the gate passes and `retrain_auto_promote` is on; otherwise it
waits for `approve` (an engineer's decision, audited). The online scorer picks the new
champion up within a minute.
"""

from __future__ import annotations

import argparse
import time
from datetime import UTC, datetime, timedelta

from mlflow import MlflowClient
from sqlalchemy import select, text

from wtpdm.db.models import AuditLog, ModelDeployment, RetrainJob
from wtpdm.db.session import session_scope
from wtpdm.logging import configure_logging, get_logger
from wtpdm.settings import get_settings

log = get_logger("retrain")
POLL_SECONDS = 30
ACTIVE = ("queued", "running")


def _farm(job: RetrainJob) -> str | None:
    return (job.scope or {}).get("farm")


def enqueue(farm: str, trigger: str, actor: str, reason: str | None = None) -> int | None:
    """Queue a retrain of `farm`; returns the job id, or None when it was not queued
    (a job for the farm is already pending, or a drift request is inside the cool-down)."""
    settings = get_settings()
    with session_scope() as s:
        # Serialise requests for the same farm (worker, API and CLI can all enqueue).
        s.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"retrain:{farm}"})
        jobs = s.scalars(select(RetrainJob).order_by(RetrainJob.requested_at.desc()).limit(200)).all()
        mine = [j for j in jobs if _farm(j) == farm]
        if any(j.status in ACTIVE for j in mine):
            log.info("retrain not queued: already pending", farm=farm, trigger=trigger)
            return None
        if trigger == "drift":
            since = datetime.now(UTC) - timedelta(hours=settings.retrain_cooldown_hours)
            if any(j.trigger == "drift" and j.requested_at >= since for j in mine):
                log.info("retrain not queued: drift cool-down", farm=farm)
                return None
        job = RetrainJob(
            trigger=trigger, status="queued", requested_by=actor, scope={"farm": farm, "reason": reason}
        )
        s.add(job)
        s.flush()
        s.add(
            AuditLog(
                actor=actor,
                action="retrain.request",
                entity="retrain_job",
                entity_id=str(job.id),
                details={"farm": farm, "trigger": trigger, "reason": reason},
            )
        )
        log.info("retrain queued", job=job.id, farm=farm, trigger=trigger, reason=reason)
        return job.id


def recover_interrupted() -> int:
    """Jobs left `running` by a stopped runner can never finish: mark them failed."""
    with session_scope() as s:
        stale = s.scalars(select(RetrainJob).where(RetrainJob.status == "running")).all()
        for job in stale:
            job.status, job.finished_at = "failed", datetime.now(UTC)
            job.result = {"error": "interrupted: the retrain runner restarted while the job was running"}
        return len(stale)


def _claim() -> tuple[int, str, str] | None:
    with session_scope() as s:
        job = s.scalars(
            select(RetrainJob)
            .where(RetrainJob.status == "queued")
            .order_by(RetrainJob.requested_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        ).first()
        if job is None:
            return None
        job.status, job.started_at = "running", datetime.now(UTC)
        return job.id, _farm(job) or "", job.trigger


def run_next() -> bool:
    """Run the oldest queued job, if any. Returns whether a job was run."""
    from wtpdm.ml.train import train_farm  # heavy imports only where training happens

    claimed = _claim()
    if claimed is None:
        return False
    job_id, farm, trigger = claimed
    log.info("retrain started", job=job_id, farm=farm, trigger=trigger)
    status, result = "failed", {}
    try:
        result = train_farm(
            farm,
            trigger=trigger,
            actor=f"system:retrain-job-{job_id}",
            promote=get_settings().retrain_auto_promote,
        )
        status = "succeeded"
    except Exception as exc:  # the job records the failure; the runner keeps serving the queue
        log.exception("retrain failed", job=job_id, farm=farm)
        result = {"error": f"{type(exc).__name__}: {exc}"}
    with session_scope() as s:
        job = s.get(RetrainJob, job_id)
        assert job is not None
        job.status, job.finished_at, job.result = status, datetime.now(UTC), result
        s.add(
            AuditLog(
                actor=f"system:retrain-job-{job_id}",
                action=f"retrain.{status}",
                entity="retrain_job",
                entity_id=str(job_id),
                details={"farm": farm, "trigger": trigger, "registry": result.get("registry")},
            )
        )
    log.info("retrain finished", job=job_id, farm=farm, status=status)
    return True


def approve(farm: str, version: str, actor: str) -> None:
    """Promote a registered challenger to champion (human approval path)."""
    from wtpdm.ml.train import model_name

    name = model_name(farm)
    client = MlflowClient()
    mv = client.get_model_version(name, version)
    gate = mv.tags.get("gate", "")
    if gate != "passed":
        raise ValueError(f"{name} v{version} did not pass the promotion gate ({gate or 'no gate result'})")
    client.set_registered_model_alias(name, "champion", version)
    with session_scope() as s:
        s.query(ModelDeployment).filter(
            ModelDeployment.farm_id == farm, ModelDeployment.alias == "champion"
        ).update({"alias": "retired"})
        s.query(ModelDeployment).filter(
            ModelDeployment.farm_id == farm,
            ModelDeployment.model_name == name,
            ModelDeployment.version == version,
        ).update({"alias": "champion", "promoted_by": actor})
        s.add(
            AuditLog(
                actor=actor,
                action="model.approve",
                entity="model",
                entity_id=f"{name}/{version}",
                details={"farm": farm},
            )
        )
    log.info("challenger approved", model=name, version=version, actor=actor)


def run_forever() -> None:
    import mlflow

    mlflow.set_tracking_uri(get_settings().mlflow_tracking_uri)
    recovered = recover_interrupted()
    log.info("retrain runner started", recovered_jobs=recovered)
    while True:
        if not run_next():
            time.sleep(POLL_SECONDS)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run")
    q = sub.add_parser("enqueue")
    q.add_argument("--farm", required=True, choices=["A", "B", "C"])
    q.add_argument("--reason")
    a = sub.add_parser("approve")
    a.add_argument("--farm", required=True, choices=["A", "B", "C"])
    a.add_argument("--version", required=True)
    a.add_argument("--actor", default="cli")
    args = parser.parse_args()
    configure_logging(get_settings().log_level)
    if args.cmd == "run":
        run_forever()
    elif args.cmd == "enqueue":
        enqueue(args.farm, "manual", "cli", args.reason)
    else:
        import mlflow

        mlflow.set_tracking_uri(get_settings().mlflow_tracking_uri)
        approve(args.farm, args.version, args.actor)


if __name__ == "__main__":
    main()
