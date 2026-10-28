"""The real-time worker: one process, three schedules.

    python -m wtpdm.realtime.worker

- every `replay_tick_seconds`: replay the next rows of every turbine -> telemetry,
  score them with the farm's champion -> health_score, update alerts
- every `drift_interval_minutes`: drift check per farm; a breach of a retrain-triggering
  metric queues a drift retrain (rate-limited)
- `retrain_cron`: queue a scheduled retrain of every farm

Training itself runs in the separate retrain runner (`wtpdm.mlops.retrain run`), so a
multi-minute training job never stalls the live stream.
"""

from __future__ import annotations

import logging
import signal
import time
from pathlib import Path

import mlflow
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from wtpdm import catalog
from wtpdm.db.session import get_engine
from wtpdm.logging import configure_logging, get_logger
from wtpdm.mlops.retrain import enqueue
from wtpdm.realtime import drift
from wtpdm.realtime.alerts import AlertEngine
from wtpdm.realtime.replay import Replay
from wtpdm.realtime.scorer import OnlineScorer
from wtpdm.settings import get_settings

log = get_logger("worker")
HEARTBEAT = Path("/tmp/wtpdm-worker.heartbeat")


class Worker:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.engine = get_engine()
        self.farms = catalog.available_farms(self.settings.lake_root)
        self.replay = Replay(
            self.engine,
            self.settings.lake_root,
            self.farms,
            self.settings.replay_speed,
            self.settings.replay_tick_seconds,
        )
        self.scorers = {f: OnlineScorer(f, self.engine, self.settings.lake_root) for f in self.farms}
        self.alerts = AlertEngine()

    def tick(self) -> None:
        started = time.perf_counter()
        batches = self.replay.tick()
        timings = {"replay": time.perf_counter() - started}
        for farm, rows in batches.items():
            t0 = time.perf_counter()
            try:
                batch = self.scorers[farm].process(rows)
                t1 = time.perf_counter()
                if batch is not None:
                    self.alerts.process(batch)
                timings[f"score_{farm}"], timings[f"alerts_{farm}"] = t1 - t0, time.perf_counter() - t1
            except Exception:  # one farm's failure must not stop the others
                log.exception("scoring failed", farm=farm)
        HEARTBEAT.touch()
        total = time.perf_counter() - started
        if total > self.settings.replay_tick_seconds:
            log.warning(
                "tick slower than its interval: the replay runs below the configured speed",
                seconds=round(total, 2),
                stages={k: round(v, 2) for k, v in timings.items()},
            )

    def check_drift(self) -> None:
        for farm in self.farms:
            model = self.scorers[farm].model
            if model is None:
                continue
            try:
                results = drift.check_farm(
                    self.engine, self.settings.lake_root, farm, model, self.settings.drift_window_days
                )
            except Exception:
                log.exception("drift check failed", farm=farm)
                continue
            triggered = [r for r in results if r.breached and r.triggers_retrain]
            if triggered:
                reason = ", ".join(f"{r.metric}:{r.feature}={r.value} > {r.threshold}" for r in triggered)
                enqueue(farm, "drift", "system:drift-monitor", reason)

    def scheduled_retrain(self) -> None:
        for farm in self.farms:
            enqueue(farm, "schedule", "system:scheduler", f"cron {self.settings.retrain_cron}")

    def run(self) -> None:
        mlflow.set_tracking_uri(self.settings.mlflow_tracking_uri)
        self.replay.start()
        sched = BlockingScheduler(timezone="UTC")
        sched.add_job(
            self.tick, "interval", seconds=self.settings.replay_tick_seconds, max_instances=1, coalesce=True
        )
        sched.add_job(
            self.check_drift,
            "interval",
            minutes=self.settings.drift_interval_minutes,
            max_instances=1,
            coalesce=True,
        )
        sched.add_job(
            self.scheduled_retrain, CronTrigger.from_crontab(self.settings.retrain_cron, timezone="UTC")
        )

        def stop(signum, _frame):
            log.info("worker stopping", signal=signum)
            sched.shutdown(wait=False)

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        log.info(
            "worker started",
            farms=self.farms,
            speed=self.settings.replay_speed,
            tick_seconds=self.settings.replay_tick_seconds,
            retrain_cron=self.settings.retrain_cron,
        )
        sched.start()


def main() -> None:
    configure_logging(get_settings().log_level)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)  # one INFO line per tick otherwise
    Worker().run()


if __name__ == "__main__":
    main()
