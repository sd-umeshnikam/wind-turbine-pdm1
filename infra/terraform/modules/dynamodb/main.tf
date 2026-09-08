locals {
  tables = toset(["assets", "alerts", "config"])
}

resource "aws_dynamodb_table" "this" {
  for_each = local.tables

  name         = "${var.name_prefix}-${var.env}-${each.key}"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "id"

  attribute {
    name = "id"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }

  tags = {
    Environment = var.env
    Platform    = "wtb-pdm"
  }
}
