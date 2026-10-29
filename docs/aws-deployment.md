# Real AWS deployment, cost and cleanup

> **Not yet exercised against a real AWS account.** The real-mode code path (`terraform apply <saved plan>`, read-only verification calls) is implemented and its logic is unit-tested with fake clients, but no real deployment has been performed. Treat the first real run as a test in a sandbox account.

## Prerequisites

1. A dedicated **sandbox AWS account** (never production for a first run).
2. An AWS CLI profile using SSO or an assumed role — not long-lived access keys, never root.
3. A deployment role with only the permissions the generated configuration needs (starting point below). Review and tighten for your account.
4. An **issued ACM certificate** in the target region for your domain (HTTPS is required for personal data).
5. Budget alerts in AWS Budgets.

## Enable real mode (server operator only)

```bash
# backend/.env
IAP_ALLOW_REAL_DEPLOY=true
IAP_AWS_PROFILE=iap-sandbox-deployer
IAP_AWS_EXPECTED_ACCOUNT_ID=123456789012
```

Restart the backend. Then, in the project: **Settings → Deployment mode → Real AWS** and set the ACM certificate ARN. Changing mode invalidates existing plans. Run validation again (real-mode plans refresh against AWS), review the plan, approve by typing the account ID, and apply. The provider block's `allowed_account_ids` refuses any other account.

Post-deployment, IAP calls read-only APIs (`rds:DescribeDBInstances`, `ec2:DescribeSecurityGroupRules`, `s3:GetPublicAccessBlock`, `cloudtrail:GetTrailStatus`) and requests `https://<alb>/health`, recording results as live evidence.

## Deployment role — starting point

The generated stack creates VPC networking, security groups, an ALB, an ASG with a launch template and instance role, RDS, S3, CloudTrail, flow logs and (Resilient) WAF — and, depending on the interview, an uploads bucket, business-hours schedules, and CloudWatch alarms with an SNS topic and a KMS key. A practical approach is to scope by service and require the project tag on creates:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {"Sid": "Provision", "Effect": "Allow", "Action": [
      "ec2:*", "elasticloadbalancing:*", "autoscaling:*", "rds:*", "s3:*", "cloudtrail:*",
      "logs:*", "wafv2:*", "ssm:GetParameter", "ssm:GetParameters", "secretsmanager:DescribeSecret",
      "cloudwatch:*", "sns:*", "kms:CreateKey", "kms:CreateAlias", "kms:DeleteAlias", "kms:DescribeKey",
      "kms:EnableKeyRotation", "kms:GetKeyPolicy", "kms:GetKeyRotationStatus", "kms:ListResourceTags",
      "kms:PutKeyPolicy", "kms:ScheduleKeyDeletion", "kms:TagResource"
    ], "Resource": "*", "Condition": {"StringEquals": {"aws:RequestedRegion": ["us-east-1"]}}},
    {"Sid": "ScopedIam", "Effect": "Allow", "Action": [
      "iam:CreateRole", "iam:DeleteRole", "iam:GetRole", "iam:TagRole", "iam:PutRolePolicy", "iam:GetRolePolicy",
      "iam:DeleteRolePolicy", "iam:AttachRolePolicy", "iam:DetachRolePolicy", "iam:ListRolePolicies",
      "iam:ListAttachedRolePolicies", "iam:CreateInstanceProfile", "iam:DeleteInstanceProfile", "iam:GetInstanceProfile",
      "iam:AddRoleToInstanceProfile", "iam:RemoveRoleFromInstanceProfile", "iam:ListInstanceProfilesForRole", "iam:PassRole",
      "iam:CreateServiceLinkedRole"
    ], "Resource": ["arn:aws:iam::*:role/*-app", "arn:aws:iam::*:instance-profile/*-app", "arn:aws:iam::*:role/aws-service-role/*"]}
  ]
}
```

This is broader than ideal (service-level wildcards for provisioning); tightening it to specific actions and tag conditions is on the roadmap. It deliberately does not allow creating IAM users, access keys or attaching arbitrary roles outside the `*-app` naming pattern.

## Cost

Estimates for the example (moderate traffic, us-east-1, on-demand, Node.js, file uploads and email alerts, approximate): Lean ~$137, Balanced ~$194, Resilient ~$297 per month. Main drivers: RDS (doubles with Multi-AZ), EC2, NAT gateways (~$33 each + $0.045/GB), the ALB, and public IPv4 addresses ($0.005/hour each). Variable charges — data transfer, LCUs, NAT processing, log volume, scale-out — can exceed the estimate. Prices come from a static table, not the AWS Price List API; verify with the AWS Pricing Calculator.

## Cleanup

Use **Deployment → Plan teardown**, review the destroy plan, approve with the typed project name, apply. Then check:

- **Deletion protection**: production/Resilient stacks enable it on RDS and the ALB. Teardown fails until you disable it through a reviewed change (edit `database.tf`/`load_balancer.tf`, validate, approve, apply), by design.
- **Final DB snapshot** is retained and billed until you delete it.
- **Uploads bucket** is not force-destroyed either: teardown fails while it contains files, so customer files are never deleted by accident. Empty it deliberately first.
- **KMS key** for the alert topic is scheduled for deletion with a 30-day waiting period (billed until then).
- **Alert subscription**: AWS emails a confirmation link after the first real deployment; alerts are not delivered until it is confirmed.
- **Log bucket** is not force-destroyed; empty it deliberately if you really want to delete audit logs (versioned objects included).
- **CloudWatch log groups** created by AWS services outside Terraform, ENIs still detaching, and Secrets Manager secrets pending deletion (7–30 days) may remain.
- Review the AWS Billing console and Cost Explorer the next day. Teardown cannot guarantee that every billable item is removed.

## State

Real-mode state is local (`backend/var/workspaces/<project>/aws/terraform.tfstate`). It is not locked, not backed up, and contains resource identifiers. For anything beyond a sandbox, migrate to an S3 backend with encryption, versioning and locking.
