variable "env" {
  type = string
}

variable "name_prefix" {
  type    = string
  default = "wtb-pdm"
}

variable "vpc_id" {
  description = "TODO: org-specific. VPC that owns the private subnets below."
  type        = string
}

variable "private_subnet_ids" {
  description = "TODO: org-specific. At least two private subnets in different AZs."
  type        = list(string)
}

variable "lambda_security_group_id" {
  description = "Security group of the Lambda service(s) allowed to reach Postgres (e.g. alerting-service's), from module.lambda-service's security_group_id output."
  type        = string
}

variable "instance_class" {
  type    = string
  default = "db.t3.micro"
}

variable "allocated_storage_gb" {
  type    = number
  default = 20
}

variable "multi_az" {
  description = "Single-AZ for dev; override true for staging/uat."
  type        = bool
  default     = false
}

variable "engine_version" {
  type    = string
  default = "16.4"
}

variable "database_name" {
  type    = string
  default = "wtb_pdm"
}

variable "master_username" {
  type    = string
  default = "wtb_pdm_admin"
}

variable "backup_retention_days" {
  type    = number
  default = 7
}

variable "deletion_protection" {
  type    = bool
  default = false
}

variable "skip_final_snapshot" {
  type    = bool
  default = true
}
