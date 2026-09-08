variable "env" {
  description = "Environment name (dev, staging, uat)."
  type        = string
}

variable "name_prefix" {
  description = "Prefix used for the catalog name, e.g. wtb -> catalog wtb_<env>."
  type        = string
  default     = "wtb"
}

variable "databricks_account_id" {
  description = "AWS account ID Databricks uses to assume the storage-credential IAM role for this region/shard (see Databricks 'Manage storage credentials' docs)."
  type        = string
  default     = "414351767826" # Databricks' published us-east-1 Unity Catalog account; override per Databricks docs for your region.
}

variable "external_id" {
  description = <<-EOT
    Storage-credential external ID. Unity Catalog issues this per storage credential
    *after* it is created, so it cannot be computed by Terraform ahead of time on a
    first-ever apply -- it is a variable so a real run either (a) pre-creates a
    placeholder credential to obtain the ID once, or (b) supplies the org's
    already-known external ID on subsequent applies. See Databricks docs:
    "Create a storage credential for connecting to AWS S3".
  EOT
  type        = string
}

variable "bucket_names" {
  description = "Map of layer (bronze/silver/gold) to S3 bucket name, from module.s3-medallion."
  type        = map(string)
}

variable "bucket_arns" {
  description = "Map of layer (bronze/silver/gold) to S3 bucket ARN, from module.s3-medallion."
  type        = map(string)
}
