variable "env" {
  type = string
}

variable "name_prefix" {
  type    = string
  default = "wtb_pdm"
}

variable "memory_store_retention_hours" {
  description = "Memory-store (hot) retention. Dashboard's read pattern favors recent data, so this stays short in every environment."
  type        = number
  default     = 24
}

variable "magnetic_store_retention_days" {
  description = "Magnetic-store (cold) retention. Short by default (dev); override longer for staging/uat in envs/<env>/main.tf."
  type        = number
  default     = 7
}
