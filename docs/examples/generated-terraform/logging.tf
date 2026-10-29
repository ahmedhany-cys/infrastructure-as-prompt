locals {
  # Elastic Load Balancing log-delivery accounts (AWS documentation).
  elb_log_account_ids = {
    "us-east-1"    = "127311923021"
    "us-east-2"    = "033677994240"
    "us-west-2"    = "797873946194"
    "eu-west-1"    = "156460612806"
    "eu-west-2"    = "652711504416"
    "eu-central-1" = "054676820928"
  }
}

# Central, private, encrypted log bucket and CloudTrail audit trail.
# Implements REQ-SEC-008, REQ-AUD-001.

resource "aws_s3_bucket" "logs" {
  bucket        = local.logs_bucket
  force_destroy = false
}

resource "aws_s3_bucket_ownership_controls" "logs" {
  bucket = aws_s3_bucket.logs.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_public_access_block" "logs" {
  bucket = aws_s3_bucket.logs.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Load balancer access logs only support SSE-S3 (AES256) destinations.
resource "aws_s3_bucket_server_side_encryption_configuration" "logs" {
  bucket = aws_s3_bucket.logs.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_versioning" "logs" {
  bucket = aws_s3_bucket.logs.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "logs" {
  bucket = aws_s3_bucket.logs.id

  rule {
    id     = "expire-logs"
    status = "Enabled"

    filter {}

    expiration {
      days = 90
    }

    noncurrent_version_expiration {
      noncurrent_days = 30
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

resource "aws_s3_bucket_policy" "logs" {
  bucket = aws_s3_bucket.logs.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "DenyInsecureTransport"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource  = [local.logs_bucket_arn, "${local.logs_bucket_arn}/*"]
        Condition = { Bool = { "aws:SecureTransport" = "false" } }
      },
      {
        Sid       = "LoadBalancerAccessLogs"
        Effect    = "Allow"
        Principal = { Service = "logdelivery.elasticloadbalancing.amazonaws.com" }
        Action    = "s3:PutObject"
        Resource  = "${local.logs_bucket_arn}/alb/AWSLogs/${var.aws_account_id}/*"
      },
      {
        # Regions launched before August 2022 deliver ALB logs from a regional
        # Elastic Load Balancing account instead of the service principal.
        Sid       = "LoadBalancerAccessLogsRegionalAccount"
        Effect    = "Allow"
        Principal = { AWS = "arn:aws:iam::${local.elb_log_account_ids[var.aws_region]}:root" }
        Action    = "s3:PutObject"
        Resource  = "${local.logs_bucket_arn}/alb/AWSLogs/${var.aws_account_id}/*"
      },
      {
        Sid       = "LogDeliveryAclCheck"
        Effect    = "Allow"
        Principal = { Service = ["delivery.logs.amazonaws.com", "cloudtrail.amazonaws.com"] }
        Action    = "s3:GetBucketAcl"
        Resource  = local.logs_bucket_arn
        Condition = { StringEquals = { "aws:SourceAccount" = var.aws_account_id } }
      },
      {
        Sid       = "LogDeliveryWrite"
        Effect    = "Allow"
        Principal = { Service = ["delivery.logs.amazonaws.com", "cloudtrail.amazonaws.com"] }
        Action    = "s3:PutObject"
        Resource  = ["${local.logs_bucket_arn}/vpc-flow-logs/AWSLogs/${var.aws_account_id}/*", "${local.logs_bucket_arn}/cloudtrail/AWSLogs/${var.aws_account_id}/*"]
        Condition = {
          StringEquals = {
            "aws:SourceAccount" = var.aws_account_id
            "s3:x-amz-acl"      = "bucket-owner-full-control"
          }
        }
      }
    ]
  })

  depends_on = [aws_s3_bucket_public_access_block.logs]
}

resource "aws_cloudtrail" "main" {
  name                          = "${local.name_prefix}-trail"
  s3_bucket_name                = aws_s3_bucket.logs.id
  s3_key_prefix                 = "cloudtrail"
  is_multi_region_trail         = true
  include_global_service_events = true
  enable_log_file_validation    = true
  enable_logging                = true

  depends_on = [aws_s3_bucket_policy.logs]
}
