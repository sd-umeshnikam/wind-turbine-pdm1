# Terraform — Wind Turbine PdM Platform

Implements the architecture in [`docs/architecture/BLUEPRINT.md`](../../docs/architecture/BLUEPRINT.md) and
[ADR-0001](../../docs/adr/0001-cloud-and-iac-choice.md). See
[`docs/manual-setup/RUNBOOK.md`](../../docs/manual-setup/RUNBOOK.md) for the manual-console alternative and
for the one-time, rarely-repeated bootstrap steps below that Terraform deliberately does not automate.

## Layout

```
modules/            reusable building blocks, one Terraform module per AWS/Databricks concern
  s3-medallion/        bronze/silver/gold buckets
  databricks-unity/    Unity Catalog catalog/schemas/external locations (databricks provider)
  lambda-service/       generic "one Lambda + its own role + its own log group" building block,
                        instantiated once per backend service (no monolith)
  appsync-api/          GraphQL API, schema.graphql, Lambda data sources, resolvers
  timestream/          sensor_readings database/table
  dynamodb/            assets/alerts/config tables
  rds-postgres/        work-order Postgres, private-subnet only
  cognito/             user pool + app client, shared by AppSync auth and the React app
  cloudfront-spa/      dashboard static hosting (S3 + OAC + CloudFront)
envs/<env>/          thin root modules (dev, staging, uat) composing the modules above
```

## Environments and accounts

**Each environment is intended to be its own AWS account** (ADR-0001) — this is the recommended
isolation boundary, not a single account with name-prefixed resources. Terraform cannot create AWS
accounts itself (that's AWS Organizations + IAM Identity Center, done by hand once per environment —
see RUNBOOK.md §0-1). What Terraform *does* own, per environment/account:

- Its own remote state: S3 bucket `wtb-pdm-<env>-tfstate` + DynamoDB lock table `wtb-pdm-<env>-tflock`
  (create these two by hand first, per environment — see RUNBOOK.md step 1 — before the first `init`).
- Its own Databricks workspace / Unity Catalog catalog (`wtb_<env>`).
- Its own copy of every module below.

There is deliberately no shared/global Terraform state across environments; promotion between
dev → staging → uat is "apply the same code with that environment's tfvars," not resource sharing.

## Bootstrapping a new environment

1. Create the AWS account (AWS Organizations) and assign SSO access (manual — RUNBOOK.md §1).
2. Create the two backend resources by hand: `wtb-pdm-<env>-tfstate` (S3, versioned) and
   `wtb-pdm-<env>-tflock` (DynamoDB, partition key `LockID`).
3. Create/attach a Databricks workspace for the account and note its host URL.
4. Copy `envs/<env>/terraform.tfvars.example` to `terraform.tfvars`, fill in the account's real
   VPC/subnet IDs, Databricks host, and Unity Catalog storage-credential external ID (see
   `modules/databricks-unity/variables.tf` for why the external ID can't be computed by Terraform
   on a from-scratch first apply).
5. `cd envs/<env> && terraform init && terraform plan`.

## Known placeholders a real deployment must replace

- `vpc_id` / `private_subnet_ids` — this platform assumes a VPC with private subnets already exists
  per account; VPC/subnet provisioning itself is out of scope for this module set.
- `databricks_external_id` — genuinely can't be known before a storage credential exists once; see
  the comment in `modules/databricks-unity/variables.tf`.
- `aws_region` — defaults to `us-east-1` in every env; change to match where the account's
  resources should actually live.
- Lambda `source_dir`s point at `services/<name>/` in this repo, which are currently empty
  scaffolds — each needs real handler code and a build step before a real `terraform apply`
  produces a working function (the zip will otherwise be empty).
- `modules/cloudfront-spa` uses the CloudFront default certificate (no custom domain) — swap in an
  ACM certificate + Route 53 record once a domain is chosen.
