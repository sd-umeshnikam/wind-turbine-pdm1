variable "service_name" {
  description = "Short service name, e.g. telemetry-api. Used to name every resource this module creates."
  type        = string
}

variable "env" {
  description = "Environment name (dev, staging, uat)."
  type        = string
}

variable "handler" {
  description = "Lambda handler, e.g. index.handler."
  type        = string
}

variable "runtime" {
  description = "Lambda runtime, e.g. nodejs20.x, python3.12."
  type        = string
}

variable "source_dir" {
  description = "Path to the service's built source directory; zipped by this module via hashicorp/archive."
  type        = string
}

variable "memory_size" {
  type    = number
  default = 256
}

variable "timeout" {
  type    = number
  default = 30
}

variable "log_retention_days" {
  type    = number
  default = 14
}

variable "environment_variables" {
  description = "Environment variables passed to the Lambda function."
  type        = map(string)
  default     = {}
}

variable "iam_policy_statements" {
  description = <<-EOT
    Service-specific IAM permissions, so each Lambda instance declares only the
    access it needs (e.g. telemetry-api gets Timestream read, alerting-service gets
    DynamoDB+RDS+SNS) instead of one shared over-broad execution role.
  EOT
  type = list(object({
    sid       = optional(string)
    effect    = optional(string, "Allow")
    actions   = list(string)
    resources = list(string)
  }))
  default = []
}

variable "vpc_id" {
  description = "VPC to attach this Lambda to. Leave null for services that only call regional AWS APIs (Timestream/DynamoDB/S3) and don't need VPC access."
  type        = string
  default     = null
}

variable "subnet_ids" {
  description = "Subnet IDs to attach this Lambda to (e.g. private subnets, required for RDS access). Empty means no VPC attachment."
  type        = list(string)
  default     = []
}

variable "create_security_group" {
  description = "Create a dedicated security group for this Lambda's ENIs (e.g. so RDS can allow ingress from it)."
  type        = bool
  default     = false
}

variable "security_group_ids" {
  description = "Existing security group IDs to attach when create_security_group is false but subnet_ids is set."
  type        = list(string)
  default     = []
}
