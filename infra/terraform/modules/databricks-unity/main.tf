locals {
  layers = toset(["bronze", "silver", "gold"])
}

data "aws_caller_identity" "current" {}

# Standard Databricks-documented Unity Catalog storage-credential trust policy:
# Databricks' own AWS account may assume this role, gated by the per-credential
# external_id, and the role is also allowed to assume itself (required for the
# cross-account AssumeRole chain Unity Catalog performs when reading/writing).
data "aws_iam_policy_document" "trust" {
  for_each = local.layers

  statement {
    sid     = "DatabricksUnityCatalogAssume"
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "AWS"
      identifiers = [var.databricks_account_id]
    }

    condition {
      test     = "StringEquals"
      variable = "sts:ExternalId"
      values   = [var.external_id]
    }
  }

  # Databricks requires the role be able to assume itself, for the cross-account
  # role-chaining Unity Catalog performs. The ARN is built from the deterministic
  # role name below rather than referencing aws_iam_role.uc_storage's own output,
  # which would create a self-referential cycle.
  statement {
    sid     = "SelfAssume"
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${var.name_prefix}-${var.env}-uc-${each.key}"]
    }
  }
}

data "aws_iam_policy_document" "access" {
  for_each = local.layers

  statement {
    sid    = "UnityCatalogBucketAccess"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject",
      "s3:ListBucket",
      "s3:GetBucketLocation",
    ]
    resources = [
      var.bucket_arns[each.key],
      "${var.bucket_arns[each.key]}/*",
    ]
  }
}

resource "aws_iam_role" "uc_storage" {
  for_each = local.layers

  name               = "${var.name_prefix}-${var.env}-uc-${each.key}"
  assume_role_policy = data.aws_iam_policy_document.trust[each.key].json
}

resource "aws_iam_role_policy" "uc_storage" {
  for_each = local.layers

  name   = "s3-access"
  role   = aws_iam_role.uc_storage[each.key].id
  policy = data.aws_iam_policy_document.access[each.key].json
}

resource "databricks_storage_credential" "this" {
  for_each = local.layers

  name = "${var.name_prefix}-${var.env}-${each.key}-cred"

  aws_iam_role {
    role_arn = aws_iam_role.uc_storage[each.key].arn
  }
}

resource "databricks_external_location" "this" {
  for_each = local.layers

  name            = "${var.name_prefix}-${var.env}-${each.key}-loc"
  url             = "s3://${var.bucket_names[each.key]}/"
  credential_name = databricks_storage_credential.this[each.key].id
}

resource "databricks_catalog" "this" {
  name    = "${var.name_prefix}_${var.env}"
  comment = "Wind turbine PdM medallion catalog for ${var.env}"

  properties = {
    env = var.env
  }
}

resource "databricks_schema" "this" {
  for_each = local.layers

  catalog_name = databricks_catalog.this.name
  name         = each.key
  storage_root = databricks_external_location.this[each.key].url
  comment      = "${each.key} layer"
}
