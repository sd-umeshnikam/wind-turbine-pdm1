# ingestion-trigger

Kicks off the Databricks bronze->silver->gold workflow run when a new raw SCADA file
lands in the bronze S3 bucket. Follows `telemetry-api`'s file layout; see that
service's README for shared conventions.

## What it does

Triggered by an **S3 `ObjectCreated` event** (not AppSync, not EventBridge — a direct
S3 bucket notification), scoped in the bucket's notification configuration to the
bronze prefix. `src/handler.ts`:

1. Extracts `(bucket, key)` from every record in the event batch.
2. Defensively re-checks each key against `BRONZE_KEY_PATTERN`
   (`farm=A|B|C/turbine=<id>/...`, per BLUEPRINT.md section 3) even though the S3
   notification rule should already be scoped to this prefix — belt-and-suspenders
   against a misconfigured rule. A non-matching key is recorded as `skipped`, not an
   error.
3. Fetches the Databricks Jobs API auth token from Secrets Manager
   (`src/secretsClient.ts`, cached per warm Lambda container).
4. Calls the Databricks Jobs `run-now` REST API (`src/databricksJobsClient.ts`) once
   per matching object, passing the object's bucket/key as `notebook_params` so the
   job can scope its ingestion to (at least) the newly landed file's farm/turbine.
5. Processes every record in the batch independently — one failing trigger doesn't
   block the others — but if any trigger fails, the handler throws after attempting
   all of them, so the S3 event invocation is recorded as failed (visible in
   CloudWatch/Lambda metrics) rather than silently swallowing a partial failure.

## IAM permissions needed

- `secretsmanager:GetSecretValue` scoped to the specific Databricks token secret ARN
- No S3 permissions are required beyond what the bucket notification itself needs
  (the event is pushed to Lambda; this function does not call `s3:GetObject`)

## Environment variables

| Variable | Purpose |
|---|---|
| `DATABRICKS_HOST` | Base URL of the Databricks workspace (e.g. `https://<workspace>.cloud.databricks.com`) |
| `DATABRICKS_JOB_ID` | Job ID of the bronze->silver->gold workflow (`data-platform/resources/jobs.yml`) |
| `DATABRICKS_TOKEN_SECRET_ID` | Secrets Manager secret ID holding the Jobs API auth token |

## Running locally

```bash
npm install
npm test
npm run build
npm run typecheck
```

## Assumption

The Databricks Jobs `run-now` request/response shape (`notebook_params`, `run_id`) is
assumed per the public Databricks Jobs API 2.1 contract; if the actual job is a
multi-task job needing `job_parameters` instead of `notebook_params`, adjust
`src/databricksJobsClient.ts` accordingly — the handler itself doesn't care which
param shape is used.
