# PostgreSQL on Amazon RDS in isolated data subnets.
# Implements REQ-SEC-001, REQ-SEC-002, REQ-SEC-006, REQ-SEC-003, REQ-AVL-003, REQ-OPS-001.

resource "aws_db_subnet_group" "main" {
  name       = "${local.name_prefix}-db"
  subnet_ids = aws_subnet.data[*].id
}

resource "aws_db_parameter_group" "main" {
  name   = "${local.name_prefix}-pg16"
  family = "postgres16"

  parameter {
    name  = "rds.force_ssl"
    value = "1"
  }

  parameter {
    name  = "log_connections"
    value = "1"
  }
}

resource "aws_cloudwatch_log_group" "postgresql" {
  name              = "/aws/rds/instance/${local.db_identifier}/postgresql"
  retention_in_days = 90
}

resource "aws_db_instance" "main" {
  identifier     = local.db_identifier
  engine         = "postgres"
  engine_version = "16"
  instance_class = var.db_instance_class

  allocated_storage     = 20
  max_allocated_storage = 100
  storage_type          = "gp3"
  storage_encrypted     = true

  db_name  = "app"
  username = "app_admin"
  # The master password is generated and stored by RDS in AWS Secrets Manager;
  # it never appears in Terraform configuration, plan files or state.
  manage_master_user_password         = true
  iam_database_authentication_enabled = true

  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.db.id]
  parameter_group_name   = aws_db_parameter_group.main.name
  publicly_accessible    = false
  multi_az               = true

  backup_retention_period   = 7
  backup_window             = "03:00-04:00"
  maintenance_window        = "sun:04:30-sun:05:30"
  copy_tags_to_snapshot     = true
  deletion_protection       = true
  skip_final_snapshot       = false
  final_snapshot_identifier = "${local.db_identifier}-final"

  auto_minor_version_upgrade      = true
  enabled_cloudwatch_logs_exports = ["postgresql"]
  apply_immediately               = false

  depends_on = [aws_cloudwatch_log_group.postgresql]
}
