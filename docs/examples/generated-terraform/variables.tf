variable "aws_region" {
  description = "AWS region to deploy into."
  type        = string
  default     = "us-east-1"

  validation {
    condition     = contains(["us-east-1", "us-east-2", "us-west-2", "eu-west-1", "eu-west-2", "eu-central-1"], var.aws_region)
    error_message = "aws_region must be one of the regions allowed by this project's requirements: us-east-1, us-east-2, us-west-2, eu-west-1, eu-west-2, eu-central-1."
  }
}

variable "aws_account_id" {
  description = "The 12-digit AWS account ID you intend to deploy into. The provider refuses to run against any other account."
  type        = string

  validation {
    condition     = can(regex("^[0-9]{12}$", var.aws_account_id))
    error_message = "aws_account_id must be a 12-digit AWS account ID."
  }
}

variable "project_slug" {
  description = "Short lowercase name used in resource names."
  type        = string
  default     = "customer-portal"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,23}$", var.project_slug))
    error_message = "project_slug must be 3-24 characters: lowercase letters, digits and hyphens."
  }
}

variable "environment" {
  description = "Deployment environment."
  type        = string
  default     = "production"

  validation {
    condition     = contains(["development", "staging", "production"], var.environment)
    error_message = "environment must be development, staging or production."
  }
}

variable "availability_zones" {
  description = "Two availability zones in the selected region."
  type        = list(string)
  default     = ["us-east-1a", "us-east-1b"]

  validation {
    condition     = length(var.availability_zones) == 2
    error_message = "Exactly two availability zones are required."
  }
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC."
  type        = string
  default     = "10.20.0.0/16"

  validation {
    condition     = can(cidrhost(var.vpc_cidr, 0)) && tonumber(split("/", var.vpc_cidr)[1]) <= 20
    error_message = "vpc_cidr must be a valid IPv4 CIDR of /20 or larger."
  }
}

variable "instance_type" {
  description = "EC2 instance type for application servers."
  type        = string
  default     = "t4g.medium"
}

variable "app_ami_ssm_parameter" {
  description = "Public SSM parameter resolving to the latest Amazon Linux 2023 AMI."
  type        = string
  default     = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-arm64"
}

variable "acm_certificate_arn" {
  description = "ARN of an issued ACM certificate for the application's domain (required for HTTPS)."
  type        = string

  validation {
    condition     = can(regex("^arn:aws[a-z-]*:acm:[a-z0-9-]+:[0-9]{12}:certificate/.+$", var.acm_certificate_arn))
    error_message = "acm_certificate_arn must be an ACM certificate ARN."
  }
}

variable "db_instance_class" {
  description = "RDS instance class."
  type        = string
  default     = "db.t4g.small"
}

variable "alert_email" {
  description = "Email address that receives CloudWatch alarm notifications."
  type        = string
  default     = "ops@example.com"

  validation {
    condition     = can(regex("^[^@\\s]+@[^@\\s]+\\.[A-Za-z]{2,}$", var.alert_email))
    error_message = "alert_email must be an email address."
  }
}
