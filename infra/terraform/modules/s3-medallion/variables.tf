variable "env" {
  description = "Environment name (dev, staging, uat)."
  type        = string
}

variable "name_prefix" {
  description = "Prefix applied to all bucket names."
  type        = string
  default     = "wtb-pdm"
}

variable "bronze_glacier_transition_days" {
  description = "Age (days) at which bronze objects transition to Glacier."
  type        = number
  default     = 90
}
