resource "aws_timestream_database" "this" {
  database_name = "${var.name_prefix}_${var.env}"
}

resource "aws_timestream_table" "sensor_readings" {
  database_name = aws_timestream_database.this.database_name
  table_name    = "sensor_readings"

  retention_properties {
    memory_store_retention_period_in_hours = var.memory_store_retention_hours
    magnetic_store_retention_period_in_days = var.magnetic_store_retention_days
  }
}
