output "table_names" {
  value = { for name, table in aws_dynamodb_table.this : name => table.name }
}

output "table_arns" {
  value = { for name, table in aws_dynamodb_table.this : name => table.arn }
}
