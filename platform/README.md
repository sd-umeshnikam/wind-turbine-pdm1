# wtpdm — Wind Turbine PdM Platform v2

One Python package shared by every backend role: data ingest, model training and
evaluation, online scoring, drift/retraining, the Platform API and the assistant.

| Path | Purpose |
|---|---|
| `wtpdm/settings.py` | All configuration, from `WTPDM_*` environment variables |
| `wtpdm/db/` | SQLAlchemy models, Alembic migrations (TimescaleDB hypertables for telemetry and health scores) |
| `wtpdm/api/` | FastAPI Platform API (`/api/docs`) |
| `tests/` | pytest; tests marked `integration` need the compose database |

## Run locally (Docker only — no host Python needed)

```bash
cd deploy/compose
cp .env.example .env        # set passwords/secrets
docker compose up -d --build   # db, mlflow, migrate, api
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
