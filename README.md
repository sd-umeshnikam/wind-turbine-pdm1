# Wind Turbine Predictive Maintenance Platform (v2)

Condition monitoring and predictive maintenance for wind fleets, built on the public CARE
wind-farm SCADA dataset (3 farms, 36 turbines, 95 labelled events). Everything the console
shows comes from the real data: there is no mock or dummy data anywhere.

- **Health models per farm, evaluated per event.** Each farm has its own normal-behaviour
  models and anomaly detectors, rolled up from sensor to sub-part, component and turbine.
  They are evaluated per event with leave-turbine-out grouping and compared in MLflow, and
  promoted from challenger to champion only through a gate.
- **Real-time operation.** A replay of the recorded SCADA history streams into TimescaleDB.
  Online scoring, an alert engine with an engineer workflow, drift monitoring, and
  retraining (drift-triggered plus scheduled) all run on that stream.
- **Enterprise console.** Fleet heatmap, turbine drill-down (components, sub-parts,
  sensors, measured vs expected, digital twin), alert work queue, model operations,
  drift and retraining, data quality, users and audit. Sign-in is role-based
  (viewer, engineer, admin).
- **Maintenance assistant.** A tool-calling LLM over the live data. It gives grounded
  answers with sources, suggests follow-up questions, reports what changed since your
  last visit, and gives playbook-based maintenance recommendations.

Architecture and the reasons behind it: [ADR-0005](docs/adr/0005-platform-v2.md).
Model results: [docs/ml/MODEL_EVALUATION.md](docs/ml/MODEL_EVALUATION.md).

```
Raw CARE CSVs ─► ingest (polars) ─► curated Parquet lake + sensor catalog + data quality
                                         │
        training & evaluation (MLflow) ◄─┴─ drift / schedule ── drift monitor
                 │ champion / challenger aliases, promotion gate
                 ▼
 replay of SCADA history ─► TimescaleDB ─► online scorer ─► health scores ─► alert engine
                                                                  │
                  Platform API (FastAPI · REST + SSE · JWT/RBAC · audit) ◄─┘
                        ▲                                   ▲
              React console (nginx)              Assistant (tool-calling LLM + RAG)
```

## Run it

Requirements: Docker Desktop (16 GB RAM for training) and the CARE dataset on disk.
The host needs no Python or Node.

```sh
cd deploy/compose
cp .env.example .env    # then set passwords, JWT secret, admin account and LLM key
docker compose up -d db mlflow migrate
docker compose run --rm migrate python -m wtpdm.ingest.pipeline   # ~1 h: raw CSVs -> lake + catalog
docker compose run --rm migrate python -m wtpdm.ml.train          # 2-3 h: train, evaluate, register
docker compose up -d                                              # api, worker, retrainer, web
```

| Service | URL | What |
|---|---|---|
| Console | http://localhost:3000 | Sign in with the admin account from `.env` |
| API docs | http://localhost:8000/api/docs | OpenAPI (Swagger) |
| MLflow | http://localhost:5001 | Runs, comparisons, registry |

Operations (start/stop, backups, retraining, users, troubleshooting):
[docs/RUNBOOK.md](docs/RUNBOOK.md). Security: [docs/SECURITY.md](docs/SECURITY.md).
Data: [docs/DATA_DICTIONARY.md](docs/DATA_DICTIONARY.md).

## Repository

| Path | What |
|---|---|
| `platform/` | Python package `wtpdm`: ingest, ML, real-time worker, API, assistant; Alembic migrations; pytest suite ([README](platform/README.md)) |
| `frontend/console/` | React + TypeScript console, Playwright end-to-end suite ([README](frontend/console/README.md)) |
| `deploy/compose/` | Docker Compose stack; `deploy/loadtest/` k6 load test |
| `docs/` | ADRs, runbook, security, data dictionary, model evaluation |
| `eda/` | Exploratory data analysis of the dataset |
| `infra/terraform/` | v1 AWS infrastructure, superseded by ADR-0005 (to be reworked for v2) |

## Quality gates

- `platform/`: ruff, mypy and pytest (unit, data-contract, API, assistant), plus an Alembic
  round trip.
- `frontend/console/`: tsc, eslint and vitest, plus a fail-closed check that rejects
  mock, random or fixture data.
- `frontend/console/e2e/`: Playwright drives every page against the live stack.
- `python -m wtpdm.assistant.eval`: the assistant against the real model and live data.
- `deploy/loadtest/api.js`: an API load test with latency and error thresholds.

The v1 code (Spark/Databricks pipeline, Lambda services, Apollo gateway, LocalStack, v1
chatbot and dashboard) was retired in v2. It remains in git history (last present at commit `ea386b2`);
see ADR-0005.
