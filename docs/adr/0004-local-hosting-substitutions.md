# ADR-0004: Local (Linux) Hosting Substitutions

## Status
Accepted

## Context
The platform needed to run entirely on a single local Linux box, including the data
pipeline and ML training — not just the dashboard against mock data (see
`docs/DEVELOPER_SETUP.md` for that lighter path). Databricks and several AWS managed
services (Timestream, DynamoDB, SNS, AppSync, Cognito, CloudFront) have no literal
self-hosted equivalent. Each needed a real decision: a genuine open-source
substitute, a documented simplification, or explicitly out of scope.

## Decision

| Cloud service | Local substitute | Why |
|---|---|---|
| S3 (bronze/silver/gold) | Local disk paths, Delta Lake via `delta-spark` | Simplest default for a single box; LocalStack S3 buckets are still created (`local-stack/init/localstack-init.sh`) for anyone who wants closer fidelity |
| DynamoDB | **LocalStack** (`localstack/localstack`, free/community) | Genuine DynamoDB API; the AWS SDK v3 already pinned in `services/*/package.json` auto-honors `AWS_ENDPOINT_URL` — zero code change |
| SNS | **LocalStack** (same container) | Same reasoning — zero code change to `snsClient.ts` |
| Amazon Timestream | **TimescaleDB** (Postgres + extension) | No free local Timestream emulator exists, and its SQL dialect differs enough from standard SQL that this needed a real second client (`services/telemetry-api/src/postgresClient.ts`), not just an env var — selected via `TELEMETRY_BACKEND=postgres`, the cloud path is untouched |
| Databricks (Spark + Unity Catalog + Jobs) | Local **Apache Spark** (`pyspark` + `delta-spark`), plain `.py` scripts | Databricks *is* Spark + Delta Lake with proprietary orchestration/catalog on top — running the identical bronze/silver/gold logic locally (same `COMPONENT_KEYWORDS`/`FAULT_CATEGORY_KEYWORDS`) is a real substitution, not an approximation |
| Databricks Model Serving | Local **FastAPI** server (`local-stack/inference/serve.py`) loading real models via `mlflow.pyfunc` | `prediction-api` was already env-var driven (`DATABRICKS_SERVING_URL`/`_TOKEN` per ADR-0002) — zero code change needed there |
| MLflow tracking/registry | Local `mlflow server` | Not a substitute — the same open-source tool, self-hosted instead of Databricks-managed |
| AppSync (GraphQL + subscriptions) | Local **Apollo Server** + `graphql-ws` (`local-stack/gateway`) serving the same `schema.graphql` unchanged | Resolvers call the 5 Lambda handlers in-process — verified they resolve correctly across the package boundary (each service's own relative imports and `node_modules` still work, since Node resolves relative to the importing file, not the entry point) |
| EventBridge (alerting-service, digital-twin-service triggers) | `setInterval` in the gateway process (`local-stack/gateway/src/scheduler.ts`) | Documented simplification — not worth a local EventBridge-equivalent for one box |
| S3 `ObjectCreated` → `ingestion-trigger` | Manual/cron re-run of `run_pipeline.sh` | `ingestion-trigger` calls the real Databricks Jobs REST API, which has no local equivalent — out of scope, not faked |
| CloudFront + S3 (frontend) | **nginx** | Standard |
| Cognito | Skipped (no auth locally) | Matches the frontend's existing scaffold scope (assumes already authenticated) |

**A real bug was found and fixed while building this, independent of local hosting**:
`infra/terraform/modules/appsync-api/main.tf` wired `Query.activeAlerts` to invoke
`alerting-service`, but that service's `handler()` only ever accepted an
EventBridge-shaped event and would have thrown on every real AppSync call. Fixed in
`services/alerting-service/src/{handler,dynamoClient}.ts` (dispatches on event shape
now) — this was necessary for the local gateway to have anything to call, and is
equally a cloud-side correctness fix.

**digital-twin-service is deliberately not wired into the local scheduler.** Both the
cloud and local architectures assume something populates a "latest twin state" table
that, on inspection, nothing currently writes (see
`services/digital-twin-service/src/twinStateStore.ts`'s own comment) — a pre-existing
gap, not one introduced here. The frontend's Digital Twin page keeps using its own
client-side mock ticker, which already works standalone; building a real state writer
is a distinct follow-up, not part of "host the existing platform locally."

## Consequences
- Real end-to-end local data flow exists for telemetry, fault classification, RUL,
  and alerting (write path via the scheduler, read path via the Phase-0-fixed
  `Query.activeAlerts`) — all backed by real locally-trained models on real data,
  not mocks.
- The digital twin visualization stays mock-driven locally until a real twin-state
  writer is built (cloud or local) — this is an existing gap, now documented instead
  of silently absent.
- `docs/LINUX_HOSTING_GUIDE.md` is the operational walkthrough; this ADR is the
  record of *why* each substitution was chosen, for anyone auditing the local setup
  against the cloud architecture in `BLUEPRINT.md`.
