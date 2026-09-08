locals {
  function_name   = "${var.service_name}-${var.env}"
  attach_vpc      = length(var.subnet_ids) > 0
  security_groups = var.create_security_group ? [aws_security_group.this[0].id] : var.security_group_ids
}

data "archive_file" "this" {
  type        = "zip"
  source_dir  = var.source_dir
  output_path = "${path.module}/.build/${local.function_name}.zip"
}

resource "aws_cloudwatch_log_group" "this" {
  name              = "/aws/lambda/${local.function_name}"
  retention_in_days = var.log_retention_days
}

data "aws_iam_policy_document" "assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "this" {
  name               = "${local.function_name}-role"
  assume_role_policy = data.aws_iam_policy_document.assume.json
}

data "aws_iam_policy_document" "logs" {
  statement {
    sid       = "WriteOwnLogGroup"
    effect    = "Allow"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.this.arn}:*"]
  }
}

resource "aws_iam_role_policy" "logs" {
  name   = "logs"
  role   = aws_iam_role.this.id
  policy = data.aws_iam_policy_document.logs.json
}

data "aws_iam_policy_document" "service" {
  count = length(var.iam_policy_statements) > 0 ? 1 : 0

  dynamic "statement" {
    for_each = var.iam_policy_statements
    content {
      sid       = try(statement.value.sid, null)
      effect    = try(statement.value.effect, "Allow")
      actions   = statement.value.actions
      resources = statement.value.resources
    }
  }
}

resource "aws_iam_role_policy" "service" {
  count  = length(var.iam_policy_statements) > 0 ? 1 : 0
  name   = "service-permissions"
  role   = aws_iam_role.this.id
  policy = data.aws_iam_policy_document.service[0].json
}

resource "aws_iam_role_policy_attachment" "vpc_access" {
  count      = local.attach_vpc ? 1 : 0
  role       = aws_iam_role.this.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

resource "aws_security_group" "this" {
  count       = var.create_security_group ? 1 : 0
  name        = "${local.function_name}-lambda-sg"
  description = "ENI security group for ${local.function_name}"
  vpc_id      = var.vpc_id

  egress {
    description = "Allow all outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_lambda_function" "this" {
  function_name    = local.function_name
  role             = aws_iam_role.this.arn
  handler          = var.handler
  runtime          = var.runtime
  memory_size      = var.memory_size
  timeout          = var.timeout
  filename         = data.archive_file.this.output_path
  source_code_hash = data.archive_file.this.output_base64sha256

  environment {
    variables = var.environment_variables
  }

  dynamic "vpc_config" {
    for_each = local.attach_vpc ? [1] : []
    content {
      subnet_ids         = var.subnet_ids
      security_group_ids = local.security_groups
    }
  }

  depends_on = [aws_cloudwatch_log_group.this, aws_iam_role_policy.logs]
}
