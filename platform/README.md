# wtpdm — Wind Turbine PdM Platform v2

One Python package shared by every backend role: data ingest, model training and
evaluation, online scoring, drift/retraining, the Platform API and the assistant.

| Path | Purpose |
|---|---|
| `wtpdm/settings.py` | All configuration, from `WTPDM_*` environment variables |
| `wtpdm/db/` | SQLAlchemy models, Alembic migrations (TimescaleDB hypertables for telemetry and health scores) |
| `wtpdm/ingest/`, `wtpdm/catalog.py` | Raw CARE CSVs -> curated Parquet lake + sensor/event catalog |
| `wtpdm/ml/` | Normal-behaviour models, health index, detectors, CARE-style evaluation, MLflow training |
| `wtpdm/realtime/` | Replay of real SCADA history, online scoring, alert engine, drift monitor, worker |
| `wtpdm/mlops/` | Retrain job queue and runner, challenger approval |
| `wtpdm/api/` | FastAPI Platform API (`/api/docs`) |
| `tests/` | pytest; tests marked `integration` need the compose database |

## Run locally (Docker only — no host Python needed)

```bash
cd deploy/compose
cp .env.example .env        # set passwords/secrets
docker compose up -d --build   # db, mlflow, migrate, api, worker, retrainer
curl localhost:8000/api/ready
```

| Service | URL |
|---|---|
| Platform API | http://localhost:8000/api/docs |
| MLflow | http://localhost:5001 |
| PostgreSQL/TimescaleDB | localhost:5434 (db `wtpdm`; MLflow uses db `mlflow`) |

## Checks

```bash
docker compose run --rm --no-deps -e RUFF_CACHE_DIR=/tmp/ruff migrate \
  sh -c 'ruff check wtpdm tests && mypy wtpdm && pytest -q'
```

New migration after changing `wtpdm/db/models.py`:

```bash
docker compose run --rm --no-deps -v "$PWD/../../platform:/src" -w /src -e PYTHONPATH=/src migrate \
  alembic -c wtpdm/db/alembic.ini revision --autogenerate -m "<message>"
```

## Real-time operation (P3)

The dataset is historical, so "live" means replaying it: the `worker` streams each
turbine's **actual** 10-minute SCADA rows (the prediction window of each of its CARE events
plus 24 h warm-up) into `telemetry` at `WTPDM_REPLAY_SPEED` (default 60x: one row per 10 s
tick). Timestamps stay the dataset's own, anonymised per turbine. Each tick:

1. **Replay** writes the next rows to `telemetry`; `replay_state` holds each turbine's
   cursor, loop count, current CARE event and operating status.
2. **Online scorer** runs the farm's `@champion` bundle from the MLflow registry over a 48 h
   rolling buffer and writes `health_score` (one row per sub-part plus a `turbine` row with
   the detector score and alarm flag). Health is calibrated per model version against its
   normal-operation profile: 100 = typical, 50 = alarm level (as unusual as the worst 0.5%
   of normal operation), 25 = one more step beyond. The alias is re-checked every minute,
   so a promotion goes live without a restart.
3. **Alert engine** raises one alert per turbine on a persistent alarm, sets severity from
   calibrated health (>= 50 low, 25-50 medium, 10-25 high, < 10 critical; +1 after 48 h),
   records return-to-normal (6 h below 90% of threshold) without
   closing the alert, and applies a 24 h cool-down after a human resolves it. Every
   transition is written to `alert_note` and `audit_log`.

Every 15 min the **drift monitor** compares the last 30 days of each farm's live data with a
reference profile of the champion's training data and writes `drift_report`. Out-of-support
operating conditions or a 1.5x shift in residual level queue a `drift` retrain (max one per
farm per 24 h); input PSI and alert rate are reported but never trigger one (see
`wtpdm/realtime/drift.py`). A weekly cron (`WTPDM_RETRAIN_CRON`) queues `schedule` retrains.

The `retrainer` runs queued jobs one at a time with the full training and evaluation
protocol. A challenger is promoted only if it passes the gate (no more false alarms than
the baseline + 2 days/turbine-year, and a care score at least 0.005 above the champion).
With `WTPDM_RETRAIN_AUTO_PROMOTE=false` it waits for approval:

```bash
docker compose run --rm migrate python -m wtpdm.mlops.retrain enqueue --farm A --reason "sensor swap"
docker compose run --rm migrate python -m wtpdm.mlops.retrain approve --farm A --version 3 --actor <name>
```
