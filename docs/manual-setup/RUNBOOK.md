# Manual Setup Runbook (AWS Console + Databricks UI)

This is the non-Terraform path — either as a full alternative for teams not using Terraform yet, or (recommended, even for Terraform users) for the one-time, rarely-repeated bootstrap steps that most orgs do by hand regardless: AWS account creation and SSO. Repeat this whole runbook once per environment (dev/staging/uat).

## 0. Prerequisites
- AWS Organizations set up (or a single AWS account if following the single-account fallback from [ADR-0001](../adr/0001-cloud-and-iac-choice.md))
- A Databricks account (account console access) with permission to create workspaces
- GitHub org access to create environment secrets

## 1. AWS account bootstrap (one time per environment)
1. AWS Organizations console → **Add an AWS account** → name it `wtb-pdm-<env>` (e.g. `wtb-pdm-dev`).
2. IAM Identity Center (SSO) → assign the account to the appropriate permission set / user group for this environment's operators.
3. In the new account, enable **S3 Block Public Access** at the account level (Preferences → Block Public Access) — the platform never needs public buckets.
4. Create a Terraform state bucket + lock table even if you plan to stay manual for now, so a later switch to Terraform doesn't require re-bootstrapping: S3 bucket `wtb-pdm-<env>-tfstate` (versioning ON), DynamoDB table `wtb-pdm-<env>-tflock` (partition key `LockID`, string).

## 2. S3 medallion buckets
Create three buckets (S3 console → Create bucket), all with versioning ON, default SSE-S3 encryption, Block Public Access ON:
- `wtb-pdm-<env>-bronze`
- `wtb-pdm-<env>-silver`
- `wtb-pdm-<env>-gold`

Under `bronze`, create prefixes `farm=A/`, `farm=B/`, `farm=C/` (upload the SCADA CSVs here, mirroring the source folder structure — one prefix per turbine/event file, e.g. `farm=C/turbine=<asset_id>/<event_id>.csv`).

## 3. Databricks workspace + Unity Catalog
1. Databricks account console → **Create workspace**, region matching your S3 buckets, attach to a new or existing Unity Catalog metastore for this account.
2. Workspace admin console → **Catalogs** → create catalog `wtb_<env>` with schemas `bronze`, `silver`, `gold`.
3. **External Locations** → create one per bucket (`bronze-loc`, `silver-loc`, `gold-loc`), each pointing at the matching S3 bucket via a storage credential (IAM role — create via Databricks' quick-start IAM role wizard, which generates the trust policy for you).
4. Import the notebooks under `data-platform/notebooks/` into a workspace folder `/Repos/wtb-pdm/<env>/`.
5. Create a Databricks Workflow (Jobs UI) with three tasks in sequence: bronze ingest → silver clean → gold features, matching `data-platform/resources/jobs.yml`. Schedule per environment (e.g. dev: manual trigger only; staging/uat: nightly).
6. MLflow: no setup needed — it's built into the workspace. Create a **Registered Model** per component (`gearbox_fault_classifier`, `hydraulics_fault_classifier`, `pitch_fault_classifier`, plus RUL/forecast model equivalents) so the training notebooks have somewhere to log to.

## 4. Serving stores
- **Timestream**: console → Create database `wtb_pdm_<env>`, create table `sensor_readings` (memory-store retention 24h, magnetic-store retention 1 year — adjust per environment).
- **DynamoDB**: create tables `wtb-pdm-<env>-assets`, `wtb-pdm-<env>-alerts`, `wtb-pdm-<env>-config`, each with partition key `id` (string), on-demand capacity mode.
- **RDS Postgres**: console → Create database, engine PostgreSQL, `db.t3.micro` for dev / `db.t3.small`+ for staging/uat, single-AZ for dev, multi-AZ for staging/uat, private subnet only (no public access). Create the schema from `services/telemetry-api/README.md`'s referenced SQL, or the Terraform module's `init.sql` if you have it, once the DB is reachable.

## 5. Lambda services + AppSync
1. For each service under `services/` (telemetry-api, prediction-api, alerting-service, digital-twin-service, ingestion-trigger): zip the package, Lambda console → Create function → upload zip → attach an execution role scoped only to that service's stores (Timestream/DynamoDB/RDS/S3 as applicable — see each service's README for the exact permissions needed).
2. AppSync console → Create API → GraphQL → import the schema from `infra/terraform/modules/appsync-api/schema.graphql` → attach each Lambda as a data source → wire resolvers per field to the matching service.
3. Cognito → Create user pool `wtb-pdm-<env>` → attach as an additional AppSync authorization mode.

## 6. Frontend hosting
1. S3 → create bucket `wtb-pdm-<env>-dashboard` (static website hosting off — served via CloudFront, not directly).
2. CloudFront → Create distribution, origin = the bucket (via Origin Access Control, not public bucket policy), default root object `index.html`, custom error response 404 → `/index.html` 200 (SPA routing).
3. Build the frontend (`npm run build` in `frontend/dashboard-app`) and upload `dist/` to the bucket, then create a CloudFront invalidation (`/*`).

## 7. Alerting
1. EventBridge → create a rule triggered on the schedule/event source matching new Gold-layer predictions (or on a fixed schedule polling `prediction-api` if push-based eventing isn't wired yet) → target = `alerting-service` Lambda.
2. SNS → create topic `wtb-pdm-<env>-alerts`, subscribe the relevant email/Slack integration, grant `alerting-service`'s role `sns:Publish` on it.

## 8. Verify
- Upload one sample event CSV to `bronze/farm=A/...`, run the Databricks Workflow manually, confirm rows land in `silver.farm_a` then `gold.gearbox_features`.
- Hit the AppSync GraphQL playground with a `telemetry` query for that turbine and confirm live data returns.
- Load the CloudFront URL and confirm the Fleet Overview module renders.

Once comfortable, consider migrating this environment to Terraform (`infra/terraform/envs/<env>`) by importing the manually-created resources (`terraform import`) rather than recreating them — avoids downtime and duplicate resources.
