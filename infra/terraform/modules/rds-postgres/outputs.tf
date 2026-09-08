output "endpoint" {
  value = aws_db_instance.this.endpoint
}

output "db_instance_arn" {
  value = aws_db_instance.this.arn
}

output "security_group_id" {
  value = aws_security_group.this.id
}

output "master_user_secret_arn" {
  description = "Secrets Manager ARN holding the RDS-managed master password (manage_master_user_password = true)."
  value        = try(aws_db_instance.this.master_user_secret[0].secret_arn, null)
}
