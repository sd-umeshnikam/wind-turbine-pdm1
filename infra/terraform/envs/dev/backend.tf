# One S3 bucket + DynamoDB lock table per environment/AWS account (see ADR-0001
# and docs/manual-setup/RUNBOOK.md step 1, which creates these two resources by
# hand before the very first `terraform init` in a new environment).
terraform {
  backend "s3" {
    bucket         = "wtb-pdm-dev-tfstate"
    key            = "wtb-pdm/dev/terraform.tfstate"
    region         = "us-east-1" # TODO: set to this account's home region
    dynamodb_table = "wtb-pdm-dev-tflock"
    encrypt        = true
  }
}
