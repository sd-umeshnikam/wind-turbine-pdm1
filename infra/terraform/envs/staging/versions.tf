terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.40, < 6.0.0" # >= 5.16 needed for aws_db_instance.manage_master_user_password
    }
    databricks = {
      source  = "databricks/databricks"
      version = "~> 1.50"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

# Auth via DATABRICKS_TOKEN or DATABRICKS_CLIENT_ID/DATABRICKS_CLIENT_SECRET
# environment variables (CI secrets) rather than in-file, so no credential
# material lives in tfvars or state provider config.
provider "databricks" {
  host = var.databricks_host
}
