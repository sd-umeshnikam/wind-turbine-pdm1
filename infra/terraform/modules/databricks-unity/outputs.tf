output "catalog_name" {
  value = databricks_catalog.this.name
}

output "schema_names" {
  value = { for layer, schema in databricks_schema.this : layer => schema.name }
}

output "external_location_names" {
  value = { for layer, loc in databricks_external_location.this : layer => loc.name }
}

output "storage_credential_names" {
  value = { for layer, cred in databricks_storage_credential.this : layer => cred.name }
}

output "storage_role_arns" {
  value = { for layer, role in aws_iam_role.uc_storage : layer => role.arn }
}
