variable "env" {
  type    = string
  default = "uat"
}

variable "aws_region" {
  type    = string
  default = "us-east-1" # TODO: set to this account's home region
}

variable "name_prefix" {
  type    = string
  default = "wtb-pdm"
}

variable "databricks_host" {
  description = "Databricks workspace URL for this environment, e.g. https://<workspace-id>.cloud.databricks.com"
  type        = string
}

variable "databricks_account_id" {
  description = "AWS account ID Databricks assumes Unity Catalog storage-credential roles from."
  type        = string
  default     = "414351767826"
}

variable "databricks_external_id" {
  description = "Unity Catalog storage-credential external ID (see modules/databricks-unity for why this can't be computed)."
  type        = string
}

variable "vpc_id" {
  description = "TODO: org-specific. VPC hosting the private subnets used by RDS and the alerting-service Lambda."
  type        = string
}

variable "private_subnet_ids" {
  description = "TODO: org-specific. At least two private subnets in different AZs."
  type        = list(string)
}

variable "rds_instance_class" {
  type    = string
  default = "db.t3.small"
}

variable "rds_multi_az" {
  description = "Single-AZ for dev; staging/uat default to true."
  type        = bool
  default     = true
}

variable "timestream_magnetic_store_retention_days" {
  description = "Short in dev; staging/uat default longer."
  type        = number
  default     = 365
}

variable "alert_notification_email" {
  description = "TODO: org-specific. Email subscribed to the SNS alerts topic; leave null to skip."
  type        = string
  default     = null
}
