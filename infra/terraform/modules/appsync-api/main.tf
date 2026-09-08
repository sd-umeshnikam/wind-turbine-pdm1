locals {
  # Query-field -> Lambda-data-source mapping. publishTwinUpdate deliberately
  # excluded: it's resolved locally (NONE data source), not by invoking a Lambda -
  # see the publish_twin_update resolver below and schema.graphql.
  field_to_service = {
    telemetry    = "telemetry-api"
    predictions  = "prediction-api"
    activeAlerts = "alerting-service"
  }
}

resource "aws_appsync_graphql_api" "this" {
  name                = "${var.name_prefix}-${var.env}"
  schema              = file("${path.module}/schema.graphql")
  authentication_type = "AMAZON_COGNITO_USER_POOLS"

  user_pool_config {
    aws_region     = var.aws_region
    default_action = "ALLOW"
    user_pool_id   = var.cognito_user_pool_id
  }
}

data "aws_iam_policy_document" "assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["appsync.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "invoke_lambda" {
  name               = "${var.name_prefix}-${var.env}-appsync-invoke"
  assume_role_policy = data.aws_iam_policy_document.assume.json
}

data "aws_iam_policy_document" "invoke_lambda" {
  statement {
    sid       = "InvokeServiceLambdas"
    effect    = "Allow"
    actions   = ["lambda:InvokeFunction"]
    resources = [for ds in var.lambda_data_sources : ds.function_arn]
  }
}

resource "aws_iam_role_policy" "invoke_lambda" {
  name   = "invoke-lambda"
  role   = aws_iam_role.invoke_lambda.id
  policy = data.aws_iam_policy_document.invoke_lambda.json
}

resource "aws_appsync_datasource" "lambda" {
  for_each = var.lambda_data_sources

  api_id           = aws_appsync_graphql_api.this.id
  name             = replace(each.key, "-", "_")
  type             = "AWS_LAMBDA"
  service_role_arn = aws_iam_role.invoke_lambda.arn

  lambda_config {
    function_arn = each.value.function_arn
  }
}

resource "aws_appsync_datasource" "none" {
  api_id = aws_appsync_graphql_api.this.id
  name   = "no_op"
  type   = "NONE"
}

resource "aws_appsync_resolver" "query" {
  for_each = { telemetry = "telemetry", predictions = "predictions", activeAlerts = "activeAlerts" }

  api_id      = aws_appsync_graphql_api.this.id
  type        = "Query"
  field       = each.value
  data_source = aws_appsync_datasource.lambda[local.field_to_service[each.value]].name

  request_template  = file("${path.module}/templates/invoke_request.vtl")
  response_template = file("${path.module}/templates/invoke_response.vtl")
}

resource "aws_appsync_resolver" "publish_twin_update" {
  api_id      = aws_appsync_graphql_api.this.id
  type        = "Mutation"
  field       = "publishTwinUpdate"
  # NONE data source, not the digital-twin-service Lambda: this mutation exists only
  # to fan the input out to onTwinUpdate subscribers (see schema.graphql comment) -
  # digital-twin-service calls it as a client over HTTP, it is never itself invoked
  # as AppSync's resolver target.
  data_source = aws_appsync_datasource.none.name

  request_template  = file("${path.module}/templates/local_mutation_request.vtl")
  response_template = file("${path.module}/templates/invoke_response.vtl")
}

resource "aws_appsync_resolver" "on_twin_update" {
  api_id      = aws_appsync_graphql_api.this.id
  type        = "Subscription"
  field       = "onTwinUpdate"
  data_source = aws_appsync_datasource.none.name

  request_template  = file("${path.module}/templates/subscribe_request.vtl")
  response_template = file("${path.module}/templates/subscribe_response.vtl")
}
