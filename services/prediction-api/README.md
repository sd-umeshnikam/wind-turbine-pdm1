# prediction-api

Serves fault probability, RUL bands (P10/P50/P90), and a forecast series for a
turbine/component. Follows the same file layout as `telemetry-api` (see that
service's README for the shared conventions); this file only calls out what differs.

## What it does

Implements `Query.predictions(turbineId, component?): [Prediction]` as an AppSync
direct Lambda data source resolver. Instead of a database, its one upstream is a
**Databricks Model Serving** real-time endpoint (ADR-0002) — `src/databricksClient.ts`
POSTs a Databricks-standard `dataframe_records` payload and parses the
`predictions` array back.

- Model has no prediction for this turbine/component → returns `[]`.
- Endpoint unreachable, non-2xx, or times out (8s) → thrown as an upstream error,
  logged server-side, surfaced to AppSync as a GraphQL error — this is deliberately
  not silently mapped to `[]`, so a real outage doesn't look like "nothing to report."
- Missing/invalid `turbineId` → validation error before any network call.

**Swapping to SageMaker later** (documented alternative in ADR-0002) only touches
`src/databricksClient.ts` and its two env vars — the handler and GraphQL contract
stay the same, which is the reason this service isolates the upstream call behind one
thin client module rather than inlining `fetch` in the handler.

## IAM permissions needed

This function makes an outbound HTTPS call to Databricks, not an AWS API call, so it
needs no AWS resource IAM permissions beyond the default Lambda execution role
(CloudWatch Logs). If the auth token is stored in Secrets Manager rather than passed
as a plain env var, add `secretsmanager:GetSecretValue` scoped to that one secret's
ARN.

## Environment variables

| Variable | Purpose |
|---|---|
| `DATABRICKS_SERVING_URL` | Full URL of the Model Serving endpoint's invocations path |
| `DATABRICKS_SERVING_TOKEN` | Bearer token (from a secret, not committed) |

## Running locally

```bash
npm install
npm test
npm run build
npm run typecheck
```

## Assumption

`schema.graphql` did not exist at scaffold time; `PredictionQueryArgs` and the
`Prediction` mapping follow the shape given in the scaffolding task. The Databricks
response shape (`predictions[].{turbine_id, component, fault_probability,
rul_hours_p10/p50/p90, forecast_series}`) is also assumed — reconcile against the
actual registered model's output signature once `data-platform/ml/05_train_rul_regressor.py`
and friends are deployed to a serving endpoint.
