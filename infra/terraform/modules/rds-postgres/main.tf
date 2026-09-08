resource "aws_db_subnet_group" "this" {
  name       = "${var.name_prefix}-${var.env}-db-subnets"
  subnet_ids = var.private_subnet_ids
}

resource "aws_security_group" "this" {
  name        = "${var.name_prefix}-${var.env}-rds-sg"
  description = "Postgres access for ${var.env}, restricted to the Lambda services' security group"
  vpc_id      = var.vpc_id

  ingress {
    description     = "Postgres from Lambda services"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [var.lambda_security_group_id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_db_instance" "this" {
  identifier     = "${var.name_prefix}-${var.env}"
  engine         = "postgres"
  engine_version = var.engine_version
  instance_class = var.instance_class

  allocated_storage            = var.allocated_storage_gb
  storage_encrypted            = true
  db_name                      = var.database_name
  username                     = var.master_username
  manage_master_user_password  = true

  db_subnet_group_name   = aws_db_subnet_group.this.name
  vpc_security_group_ids = [aws_security_group.this.id]
  publicly_accessible    = false
  multi_az               = var.multi_az

  backup_retention_period   = var.backup_retention_days
  deletion_protection       = var.deletion_protection
  skip_final_snapshot       = var.skip_final_snapshot
  final_snapshot_identifier = var.skip_final_snapshot ? null : "${var.name_prefix}-${var.env}-final"
}
