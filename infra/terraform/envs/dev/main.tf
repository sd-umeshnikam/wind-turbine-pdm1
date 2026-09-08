data "aws_caller_identity" "current" {}

module "s3_medallion" {
  source      = "../../modules/s3-medallion"
  env         = var.env
  name_prefix = var.name_prefix
}

module "databricks_unity" {
  source                = "../../modules/databricks-unity"
  env                   = var.env
  name_prefix           = "wtb"
  databricks_account_id = var.databricks_account_id
  external_id           = var.databricks_external_id
  bucket_names          = module.s3_medallion.bucket_names
  bucket_arns           = module.s3_medallion.bucket_arns
}

module "dynamodb" {
  source      = "../../modules/dynamodb"
  env         = var.env
  name_prefix = var.name_prefix
}

module "timestream" {
  source                        = "../../modules/timestream"
  env                            = var.env
  name_prefix                    = "wtb_pdm"
  magnetic_store_retention_days  = var.timestream_magnetic_store_retention_days
}

module "cognito" {
  source      = "../../modules/cognito"
  env         = var.env
  name_prefix = var.name_prefix
}

resource "aws_sns_topic" "alerts" {
  name = "${var.name_prefix}-${var.env}-alerts"
}

resource "aws_sns_topic_subscription" "alerts_email" {
  count     = var.alert_notification_email == null ? 0 : 1
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_notification_email
}

# Declared standalone (not inside modules.rds-postgres or modules.lambda-service)
# so both module.rds_postgres and module.alerting_service can depend on the
# same security group without depending on each other -- avoids a module cycle,
# since alerting-service's env vars/IAM need the RDS endpoint/secret, and RDS's
# ingress rule needs alerting-service's security group.
resource "aws_security_group" "alerting_service_lambda" {
  name        = "${var.name_prefix}-${var.env}-alerting-service-lambda-sg"
  description = "ENI security group for alerting-service Lambda (VPC-attached for RDS access)"
  vpc_id      = var.vpc_id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

module "rds_postgres" {
  source                    = "../../modules/rds-postgres"
  env                       = var.env
  name_prefix               = var.name_prefix
  vpc_id                    = var.vpc_id
  private_subnet_ids        = var.private_subnet_ids
  lambda_security_group_id  = aws_security_group.alerting_service_lambda.id
  instance_class            = var.rds_instance_class
  multi_az                  = var.rds_multi_az
}

module "telemetry_api" {
  source       = "../../modules/lambda-service"
  service_name = "telemetry-api"
  env          = var.env
  handler      = "index.handler"
  runtime      = "nodejs20.x"
  source_dir   = "${path.module}/../../../../services/telemetry-api"

  environment_variables = {
    TIMESTREAM_DATABASE = module.timestream.database_name
    TIMESTREAM_TABLE    = module.timestream.table_name
  }

  iam_policy_statements = [
    {
      sid       = "TimestreamReadTable"
      actions   = ["timestream:Select", "timestream:DescribeTable", "timestream:ListMeasures"]
      resources = [module.timestream.table_arn]
    },
    {
      sid       = "TimestreamDescribeEndpoints" # action does not support resource-level restriction
      actions   = ["timestream:DescribeEndpoints"]
      resources = ["*"]
    },
  ]
}

module "prediction_api" {
  source       = "../../modules/lambda-service"
  service_name = "prediction-api"
  env          = var.env
  handler      = "index.handler"
  runtime      = "nodejs20.x"
  source_dir   = "${path.module}/../../../../services/prediction-api"

  environment_variables = {
    DATABRICKS_HOST = var.databricks_host
  }

  iam_policy_statements = [
    {
      sid       = "ReadModelServingConfig"
      actions   = ["ssm:GetParameter"]
      resources = ["arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter/${var.name_prefix}/${var.env}/prediction-api/*"]
    },
  ]
}

module "alerting_service" {
  source       = "../../modules/lambda-service"
  service_name = "alerting-service"
  env          = var.env
  handler      = "index.handler"
  runtime      = "nodejs20.x"
  source_dir   = "${path.module}/../../../../services/alerting-service"

  vpc_id                 = var.vpc_id
  subnet_ids             = var.private_subnet_ids
  create_security_group  = false
  security_group_ids     = [aws_security_group.alerting_service_lambda.id]

  environment_variables = {
    ALERTS_TABLE   = module.dynamodb.table_names["alerts"]
    CONFIG_TABLE   = module.dynamodb.table_names["config"]
    SNS_TOPIC_ARN  = aws_sns_topic.alerts.arn
    RDS_ENDPOINT   = module.rds_postgres.endpoint
    RDS_SECRET_ARN = module.rds_postgres.master_user_secret_arn
  }

  iam_policy_statements = [
    {
      sid       = "DynamoDbAlertsConfig"
      actions   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:Query", "dynamodb:Scan"]
      resources = [module.dynamodb.table_arns["alerts"], module.dynamodb.table_arns["config"]]
    },
    {
      sid       = "PublishAlerts"
      actions   = ["sns:Publish"]
      resources = [aws_sns_topic.alerts.arn]
    },
    {
      sid       = "ReadRdsSecret"
      actions   = ["secretsmanager:GetSecretValue"]
      resources = [module.rds_postgres.master_user_secret_arn]
    },
  ]
}

module "digital_twin_service" {
  source       = "../../modules/lambda-service"
  service_name = "digital-twin-service"
  env          = var.env
  handler      = "index.handler"
  runtime      = "nodejs20.x"
  source_dir   = "${path.module}/../../../../services/digital-twin-service"

  environment_variables = {
    TIMESTREAM_DATABASE = module.timestream.database_name
    TIMESTREAM_TABLE    = module.timestream.table_name
    ASSETS_TABLE        = module.dynamodb.table_names["assets"]
  }

  iam_policy_statements = [
    {
      sid       = "TimestreamReadTable"
      actions   = ["timestream:Select", "timestream:DescribeTable"]
      resources = [module.timestream.table_arn]
    },
    {
      sid       = "TimestreamDescribeEndpoints"
      actions   = ["timestream:DescribeEndpoints"]
      resources = ["*"]
    },
    {
      sid       = "DynamoDbAssets"
      actions   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:Query"]
      resources = [module.dynamodb.table_arns["assets"]]
    },
  ]
}

module "ingestion_trigger" {
  source       = "../../modules/lambda-service"
  service_name = "ingestion-trigger"
  env          = var.env
  handler      = "handler.lambda_handler"
  runtime      = "python3.12"
  source_dir   = "${path.module}/../../../../services/ingestion-trigger"

  environment_variables = {
    DATABRICKS_HOST = var.databricks_host
  }

  iam_policy_statements = [
    {
      sid       = "ReadBronzeObjects"
      actions   = ["s3:GetObject"]
      resources = ["${module.s3_medallion.bronze_bucket_arn}/*"]
    },
    {
      sid       = "TriggerDatabricksJobConfig"
      actions   = ["ssm:GetParameter"]
      resources = ["arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter/${var.name_prefix}/${var.env}/ingestion-trigger/*"]
    },
  ]
}

resource "aws_lambda_permission" "ingestion_trigger_s3" {
  statement_id  = "AllowS3Invoke"
  action        = "lambda:InvokeFunction"
  function_name = module.ingestion_trigger.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = module.s3_medallion.bronze_bucket_arn
}

resource "aws_s3_bucket_notification" "bronze" {
  bucket = module.s3_medallion.bronze_bucket_name

  lambda_function {
    lambda_function_arn = module.ingestion_trigger.function_arn
    events               = ["s3:ObjectCreated:*"]
  }

  depends_on = [aws_lambda_permission.ingestion_trigger_s3]
}

module "appsync_api" {
  source               = "../../modules/appsync-api"
  env                  = var.env
  name_prefix          = var.name_prefix
  aws_region           = var.aws_region
  cognito_user_pool_id = module.cognito.user_pool_id

  lambda_data_sources = {
    "telemetry-api"        = { function_arn = module.telemetry_api.function_arn }
    "prediction-api"       = { function_arn = module.prediction_api.function_arn }
    "alerting-service"     = { function_arn = module.alerting_service.function_arn }
    "digital-twin-service" = { function_arn = module.digital_twin_service.function_arn }
  }
}

# See the comment on aws_security_group.alerting_service_lambda above for why
# this grant is a standalone resource rather than living inside a module: it
# depends on both module.digital_twin_service and module.appsync_api, and
# appsync-api itself depends on digital-twin-service's Lambda ARN, so the grant
# can only be expressed after both exist.
resource "aws_iam_role_policy" "digital_twin_appsync_publish" {
  name = "appsync-publish"
  role = module.digital_twin_service.role_name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "appsync:GraphQL"
        Resource = "${module.appsync_api.graphql_api_arn}/types/Mutation/fields/publishTwinUpdate"
      },
    ]
  })
}

module "cloudfront_spa" {
  source      = "../../modules/cloudfront-spa"
  env         = var.env
  name_prefix = var.name_prefix
}
