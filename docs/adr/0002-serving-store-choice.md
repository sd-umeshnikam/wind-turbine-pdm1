# ADR-0002: Serving-Layer Data Stores and Model-Serving Platform

## Status
Accepted

## Context
The Gold Delta layer is the analytical source of truth, but it is not built for the dashboard's read pattern (low-latency "latest value + recent window per turbine", plus alert/config lookups, plus relational maintenance records). A serving layer is needed between Gold and the API services, and model inference needs a hosting decision.

## Decision

**Amazon Timestream for sensor time-series serving.** Synced from `gold.*_features` on a schedule (or via CDC in a later iteration). Timestream's storage tiering (memory store for recent data, magnetic store for history) matches the dashboard's actual access pattern — recent readings hit far more often than historical ones — without hand-rolling that tiering in DynamoDB or paying Databricks SQL Warehouse latency on every dashboard page load.

**DynamoDB for asset registry, alert state, and dashboard config.** These are small, key-value-shaped, and need single-digit-millisecond reads from Lambda — a relational store would be unnecessary overhead here.

**RDS Postgres for maintenance/work-order data.** Assets ↔ work orders ↔ technicians ↔ parts is a genuinely relational domain with joins and referential integrity that matter (you cannot close a work order that doesn't exist, a technician is assigned to exactly one open work order at a time, etc.) — forcing this into DynamoDB would mean reimplementing relational integrity in application code.

**Databricks Model Serving as the default inference host, SageMaker documented as an alternative.** Keeping training (MLflow) and serving on the same platform means one registry, one promotion workflow (`dev → staging → uat` via registry stage transitions), and one place to look at model lineage. SageMaker is the right call instead if/when the org wants inference cost and scaling fully decoupled from Databricks cluster billing, or needs SageMaker-specific features (multi-model endpoints, inference pipelines) — this is called out as a swap-in, not a parallel build.

## Consequences
- Three serving stores means three sync/ETL paths from Gold rather than one — each is intentionally small and single-purpose (Gold → Timestream, Gold/application → DynamoDB, application → RDS), not a single generic "sync everything everywhere" pipeline.
- Switching model serving to SageMaker later means changing `prediction-api`'s single upstream call target — it does not touch `telemetry-api`, `alerting-service`, or the frontend, because `prediction-api` is the only service that knows which inference platform is in use.
- Timestream and DynamoDB both require Lambda IAM permissions scoped narrowly per service (see `infra/terraform/modules/lambda-service` — each service instance gets only the store access it declares).
