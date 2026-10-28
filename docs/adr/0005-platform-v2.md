# ADR-0005: Platform v2 — event-correct data, per-farm health models, one Python platform

## Status
Accepted. Supersedes ADR-0002 (serving stores), ADR-0003 (digital-twin scope) and
ADR-0004 (local hosting substitutions). ADR-0001 (cloud and IaC) stands for the cloud
path; `infra/terraform` targets the retired v1 services and must be reworked for v2
before a cloud deployment.

## Context
The v1 platform was a demo:
- CARE event labels were attached to turbines by time only, so 65–78% of fault rows were
  mislabelled.
- Models were pooled across farms (Farm B scored 100% everywhere).
- Evaluation was a random row split, and RUL labels were degenerate.
- The dashboard fell back to mock data on any error, the digital twin was a random ticker,
  and acknowledging an alert was a stub.

Five runtimes (Spark, Node Lambdas, an Apollo gateway, LocalStack, a separate chatbot)
shared no code. That is how the same mistakes were repeated in each one.

## Decision

**Data.** Ingest the raw CARE CSVs directly (polars), taking each event's turbine from its
file name (`comma_<event_id>.csv`), the only reliable link. Write a curated Parquet lake
partitioned by farm and turbine, with:
- a sensor catalog carrying real descriptions and units;
- a taxonomy (component → sub-part → sensor) per farm;
- validation (range, stuck values, counters) and a data-quality report.

Timestamps are anonymised per turbine, so all times are per-turbine data clocks.

**Models.** One health model per farm, registered in MLflow as `wtpdm-health-{A,B,C}`.
- *Normal-behaviour models:* ridge, LightGBM and MLP per monitored sensor; the best on
  held-out normal data is selected.
- *Health index:* standardised residuals, EWMA-smoothed, rolled up to sub-part, component
  and turbine.
- *Detectors:* threshold baseline, Isolation Forest and a supervised early-warning
  classifier.
- *Evaluation:* event-level, leave-turbine-out, with a CARE-style score. Detection counts
  only alarms inside the abnormal period; false alarms are reported per turbine-year.
- *Selection:* per farm. No detector wins everywhere.
- *RUL:* experimental only.

**Promotion.** Champion and challenger are MLflow registry aliases. The gate requires the
CARE-style score to improve by ≥ 0.005 with no more false-alarm days than the baseline
allows. Promotion is automatic or by admin approval, and every change is mirrored to
`model_deployment` and the audit log.

**Real time without invented data.** A replay service streams each turbine's recorded
SCADA rows into TimescaleDB on that turbine's own clock. The online scorer, alert engine
and drift monitor run on that stream:
- the alert engine applies hysteresis, persistence escalation and a cool-down, and an
  engineer resolves each alert;
- the drift monitor checks PSI, out-of-support inputs, residual shift and alert rate;
- retraining is drift-triggered (with a cool-down) plus a weekly schedule, and goes through
  the same gate.

**One platform.** A single Python package (`wtpdm`) serves ingest, ML, scoring, the
FastAPI API and the assistant:
- *API:* REST, SSE and OpenAPI, with JWT auth and viewer/engineer/admin roles. Every
  mutation is audited.
- *Console:* React. It renders only what the API returns; CI fails the build on mock,
  random or fixture data.
- *Assistant:* a tool-calling LLM restricted to read-only tools. Answers are grounded (a
  figure missing from the tool results is flagged), with retrieval over the platform
  guide, the playbook and the model cards, follow-ups, proactive insights and playbook
  recommendations.

**Retired** (kept in git history, last present at commit `ea386b2`):
- the Spark/Databricks pipeline (`local-stack/pipeline`, `data-platform/`);
- the Apollo gateway and the Lambda services (`services/`);
- LocalStack;
- the v1 chatbot;
- the v1 dashboard (`frontend/dashboard-app/`);
- the mock-data setup scripts;
- their deploy workflows.

The v1 bronze/silver output on disk is not used by v2. Deleting it needs the owner's
approval.

## Consequences
- **Correct labels and per-farm models.** The scores in `docs/ml/MODEL_EVALUATION.md` are
  real and reproducible. They are also modest, because few faults exist per farm. The
  console and the assistant say so rather than hiding it.
- **Smaller stack.** It runs on one Docker host: TimescaleDB, MLflow, api, worker,
  retrainer and web. Cloud deployment maps one-to-one to managed Postgres and Timescale,
  a container platform and object storage for MLflow artifacts.
- **Honest "live" data.** The console labels it as a replay of recorded SCADA history.
  A real SCADA feed replaces the replay service without changes downstream.
- **External dependency.** The assistant needs an OpenAI-compatible LLM endpoint (Groq by
  default). Without a key it reports itself unavailable instead of answering ungrounded.
