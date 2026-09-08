variable "env" {
  type = string
}

variable "name_prefix" {
  type    = string
  default = "wtb-pdm"
}

variable "aws_region" {
  type = string
}

# Cognito is created once in modules/cognito and shared by both AppSync auth and
# the React app login, so this module takes the pool as an input rather than
# creating its own.
variable "cognito_user_pool_id" {
  type = string
}

variable "lambda_data_sources" {
  description = "Map of service name -> Lambda function ARN, for the 4 services with AppSync resolvers (ingestion-trigger is S3-triggered only and has none)."
  type = map(object({
    function_arn = string
  }))
}
