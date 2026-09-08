# Wind Turbine Predictive Maintenance Platform

An AWS + Databricks predictive-maintenance platform for wind turbines — fault classification, Remaining Useful Life (RUL) estimation, and trend forecasting for Gearbox, Hydraulics, Pitch System, Generator, Transformer, Rotor Brake, and Bearing (via vibration analysis), built on the public wind-turbine SCADA benchmark dataset (Farms A/B/C, sibling folder `../wind-turbine-scada-data-for-early-fault-detection/`).

**Status:** architecture blueprint + repo scaffold. Real EDA has been run against the actual data; infrastructure, data pipeline, backend, and frontend are scaffolded with working starter code, not yet deployed to AWS.

## Start here

1. **Set up locally**: [`docs/DEVELOPER_SETUP.md`](docs/DEVELOPER_SETUP.md) (Windows: `.\scripts\setup-all.ps1` / `scripts\setup.bat`; Linux/macOS: `./scripts/setup-all.sh`) — dashboard against mock data, no AWS needed. For the **full stack including the real data pipeline and model training self-hosted on Linux**, see [`docs/LINUX_HOSTING_GUIDE.md`](docs/LINUX_HOSTING_GUIDE.md) and [ADR-0004](docs/adr/0004-local-hosting-substitutions.md) instead.
2. **Read the blueprint**: [`docs/architecture/BLUEPRINT.md`](docs/architecture/BLUEPRINT.md) — the full architecture, decisions, and rationale. Then the three ADRs in `docs/adr/` for the specific choices (cloud/IaC, serving stores, digital-twin scope), and [`docs/architecture/ANOMALY_DETECTION_GUIDE.md`](docs/architecture/ANOMALY_DETECTION_GUIDE.md) for *why* each component's anomalies are flagged, grounded in the real charted evidence.
3. **See the real data findings**: [`eda/EDA_REPORT.md`](eda/EDA_REPORT.md) — data quality, fault taxonomy (grounded in the real event descriptions, not guesses), sensor profiling, and the degradation-trend charts that motivate the whole platform. Every number traces back to a script in `eda/scripts/` you can re-run yourself.
4. **Deploying**: either Terraform (`infra/terraform/`) or the manual console path (`docs/manual-setup/RUNBOOK.md`) — see [ADR-0001](docs/adr/0001-cloud-and-iac-choice.md) for why both exist.

## Repository layout

| Path | What it is |
|---|---|
| `docs/` | Architecture blueprint, ADRs, manual setup runbook, diagrams |
| `eda/` | Exploratory data analysis — scripts, real charts, findings report |
| `data-platform/` | Databricks Asset Bundle: bronze/silver/gold notebooks, ML training notebooks, job definitions |
| `infra/terraform/` | Terraform modules + dev/staging/uat environment configs |
| `services/` | Five independently-deployable backend Lambda services behind one AppSync API |
| `frontend/dashboard-app/` | React + TypeScript dashboard (Fleet Overview, Asset Detail, Digital Twin, Forecasts & RUL, Alerts) |
| `.github/workflows/` | CI/CD: Terraform, Databricks bundle, backend, and frontend deploy pipelines |
| `scripts/` | Setup scripts for the lightweight (mock-data) path — `setup-all.{ps1,sh}`, `setup-eda`, `setup-services`, `setup-frontend`, for Windows and Linux/macOS |
| `docs/deliverables/` | Word documents: `Sales_Briefing.docx`, `Domain_Expert_Briefing.docx`, `Developer_Setup_Guide.docx` — each generated from real EDA data, regeneratable via the scripts in `docs/deliverables/scripts/` |
| `local-stack/` | Full local-Linux-hosting stack: LocalStack + TimescaleDB, a real Spark/Delta pipeline + model training, a local inference server, and a local AppSync-substitute gateway — see `docs/LINUX_HOSTING_GUIDE.md` |

## How the pieces fit together

```
Raw SCADA CSVs → S3 Bronze → Databricks Auto Loader → Silver (cleaned) → Gold (features/labels)
                                                                              │
                                                        ┌─────────────────────┼─────────────────────┐
                                                        ▼                     ▼                     ▼
                                                   MLflow training     Amazon Timestream        DynamoDB / RDS
                                                   (fault/RUL/trend)   (telemetry serving)      (assets/alerts/work orders)
                                                        │                     │                     │
                                                        └─────────► AppSync GraphQL API ◄────────────┘
                                                                    (telemetry-api, prediction-api,
                                                                     alerting-service, digital-twin-service)
                                                                              │
                                                                              ▼
                                                                    React dashboard (CloudFront + S3)
```

See `docs/architecture/diagrams/` for the full mermaid diagrams (medallion flow, service map, environment topology).

## Running each piece locally

**Lightweight path (mock data, no AWS)** — Windows: `.\scripts\setup-all.ps1` (or double-click `scripts\setup.bat`); Linux/macOS: `./scripts/setup-all.sh` — see [`docs/DEVELOPER_SETUP.md`](docs/DEVELOPER_SETUP.md) for prerequisites, flags, and troubleshooting. Individually:

- **EDA**: `.\scripts\setup-eda.ps1` / `./scripts/setup-eda.sh` (or manually: `pip install pandas matplotlib numpy pyarrow` then `python eda/scripts/01_data_quality.py` …`02`…`05` from the repo root). Outputs land in `eda/outputs/`.
- **Backend services**: `.\scripts\setup-services.ps1` / `./scripts/setup-services.sh` (or manually: `cd services/<service-name> && npm install && npm test`) — each service is independently testable; see each service's own README for its specific responsibility and IAM needs.
- **Frontend**: `.\scripts\setup-frontend.ps1 -Dev` / `./scripts/setup-frontend.sh --dev` (or manually: `cd frontend/dashboard-app && npm install && npm run dev`) — runs against mock data matching the real GraphQL schema when `VITE_APPSYNC_URL` isn't set, so it's demoable without live AWS infra.
- **Data platform**: see `data-platform/README.md` (`databricks bundle deploy -t dev`, requires a real Databricks workspace).
- **Terraform**: see `infra/terraform/README.md` for the per-environment bootstrap sequence (`terraform init`, `plan`, `apply` per env — requires real AWS accounts/credentials).

**Full stack, self-hosted on Linux** (real Spark/Delta pipeline, real model training, real local serving — no AWS account needed at all): see [`docs/LINUX_HOSTING_GUIDE.md`](docs/LINUX_HOSTING_GUIDE.md) and `local-stack/`.

## Scope notes

- Covers all three farms (A, B, C) — not the Farm-C-only pilot from an earlier, separate Azure-based effort (`windfarm-etl`), which this platform does not touch or depend on.
- Farm B's dominant real issue is main/rotor bearing damage — 3 of its 6 real anomaly events are now captured by the Bearing category (via its real vibration sensors); the other 3 (generic "high temperature" reports) still fall outside all seven target categories (see `eda/EDA_REPORT.md` §2) and are called out as a scope consideration rather than papered over.
- "Digital twin" here means a live-data-bound visualization, not a physics simulation — see [ADR-0003](docs/adr/0003-digital-twin-scope.md).
