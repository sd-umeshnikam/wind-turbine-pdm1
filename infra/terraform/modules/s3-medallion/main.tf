locals {
  layers = toset(["bronze", "silver", "gold"])
}

resource "aws_s3_bucket" "this" {
  for_each = local.layers

  bucket = "${var.name_prefix}-${var.env}-${each.key}"

  tags = {
    Environment = var.env
    Layer       = each.key
    Platform    = "wtb-pdm"
  }
}

resource "aws_s3_bucket_versioning" "this" {
  for_each = local.layers

  bucket = aws_s3_bucket.this[each.key].id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "this" {
  for_each = local.layers

  bucket = aws_s3_bucket.this[each.key].id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "this" {
  for_each = local.layers

  bucket                  = aws_s3_bucket.this[each.key].id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Only bronze ages into Glacier: silver/gold are actively queried Delta table
# storage and Databricks Auto Loader relies on standard-tier read latency for them.
resource "aws_s3_bucket_lifecycle_configuration" "bronze" {
  bucket = aws_s3_bucket.this["bronze"].id

  rule {
    id     = "bronze-to-glacier"
    status = "Enabled"

    filter {}

    transition {
      days          = var.bronze_glacier_transition_days
      storage_class = "GLACIER"
    }
  }
}
