# ADR-0001: Cloud Provider, IaC Tooling, and Environment Isolation

## Status
Accepted

## Context
The platform needs a cloud provider, an infrastructure-as-code approach, and an environment isolation strategy across dev/staging/uat, decided before any resource is provisioned.

## Decision

**Cloud provider: AWS.** Databricks runs natively on AWS (Databricks on AWS), so the medallion pipeline is unaffected by this choice; AWS is used for everything around it — storage (S3), serverless compute (Lambda), API layer (AppSync), serving stores (Timestream/DynamoDB/RDS), auth (Cognito), and static hosting (CloudFront + S3). This is a separate, new build from the existing Azure-based `windfarm-etl` pilot — that platform is untouched.

**IaC: Terraform, with a manual-console runbook as the explicit alternative** (not AWS CDK). Terraform is provider-agnostic HCL with a mature Databricks provider (needed for Unity Catalog resources), and the manual runbook exists for two reasons: (1) teams evaluating the platform before committing to Terraform tooling, (2) the genuinely one-time, rarely-automated steps — AWS Organizations account creation, IAM Identity Center/SSO setup — that most orgs do by hand regardless of their IaC maturity elsewhere.

**Environment isolation: separate AWS accounts per environment (dev/staging/uat), recommended over a single-account/prefix model.** Account-level isolation means an IAM misconfiguration or runaway resource in `dev` cannot touch `staging`/`uat` data or budgets, and it lets Databricks Unity Catalog metastore/catalog boundaries line up cleanly with AWS account boundaries. The single-account+prefix fallback is documented in the runbook for orgs not yet using AWS Organizations, but is not the default.

## Consequences
- Terraform state is per-environment (separate S3 backend + DynamoDB lock table per account), so there is no risk of one `terraform apply` touching another environment's resources by mistake.
- Cross-account resource sharing (e.g., a shared Databricks metastore) requires explicit Unity Catalog metastore assignment per account — documented in the Databricks Unity Terraform module and the runbook, not assumed.
- Bootstrapping a brand-new environment means: create the AWS account (manual, via Organizations) → run the manual runbook's one-time steps (SSO, metastore assignment) → `terraform apply` the rest. This is a deliberate two-stage process, not a single command.
