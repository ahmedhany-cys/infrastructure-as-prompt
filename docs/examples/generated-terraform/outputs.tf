output "load_balancer_dns_name" {
  description = "Public DNS name of the load balancer. Point your domain's CNAME/alias here."
  value       = aws_lb.app.dns_name
}

output "vpc_id" {
  description = "VPC identifier."
  value       = aws_vpc.main.id
}

output "autoscaling_group_name" {
  description = "Application auto scaling group."
  value       = aws_autoscaling_group.app.name
}

output "logs_bucket" {
  description = "Private bucket receiving access, flow and audit logs."
  value       = aws_s3_bucket.logs.id
}

output "database_endpoint" {
  description = "Private database endpoint (reachable only from the application tier)."
  value       = aws_db_instance.main.address
}

output "database_master_secret_arn" {
  description = "Secrets Manager secret holding the RDS-managed master credentials."
  value       = aws_db_instance.main.master_user_secret[0].secret_arn
}

output "uploads_bucket" {
  description = "Private bucket for user files (readable and writable only by the application role)."
  value       = aws_s3_bucket.uploads.id
}

output "alerts_topic_arn" {
  description = "SNS topic that receives CloudWatch alarm notifications."
  value       = aws_sns_topic.alerts.arn
}

output "cloudtrail_arn" {
  description = "Audit trail ARN."
  value       = aws_cloudtrail.main.arn
}
