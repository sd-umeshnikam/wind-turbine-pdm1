output "database_name" {
  value = aws_timestream_database.this.database_name
}

output "database_arn" {
  value = aws_timestream_database.this.arn
}

output "table_name" {
  value = aws_timestream_table.sensor_readings.table_name
}

output "table_arn" {
  value = aws_timestream_table.sensor_readings.arn
}
