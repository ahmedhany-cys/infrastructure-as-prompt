# Evidence report — Customer Portal

Generated 2026-10-29T06:27:04.422645+00:00 by Infrastructure as Prompt. Deployment mode: **simulation**.

> **SIMULATION** — deployment results in this report come from the simulation adapter. No AWS resources were created.

## Lifecycle

- [x] Configuration validated locally (terraform validate)
- [x] Deterministic policies pass on the Terraform plan
- [x] Plan reviewed and approved
- [x] Deployment attempted
- [x] Deployment succeeded
- [ ] Resource configuration inspected in a live AWS account

## Requirements

| ID | Requirement | Status | Evidence level | Policies | Reason |
|---|---|---|---|---|---|
| REQ-SEC-001 | Database is not reachable from the internet | passing | static_config | POL-RDS-001, POL-NET-001, POL-SG-002 | All mapped policies pass on the Terraform plan (POL-NET-001, POL-RDS-001, POL-SG-002). Static analysis only — not verified against a live environment. |
| REQ-SEC-002 | Data encrypted at rest | passing | static_config | POL-RDS-002, POL-EC2-003, POL-S3-002 | All mapped policies pass on the Terraform plan (POL-EC2-003, POL-RDS-002, POL-S3-002). Static analysis only — not verified against a live environment. |
| REQ-SEC-003 | Data encrypted in transit | passing | static_config | POL-ALB-001, POL-ALB-002, POL-RDS-006 | All mapped policies pass on the Terraform plan (POL-ALB-001, POL-ALB-002, POL-RDS-006). Static analysis only — not verified against a live environment. |
| REQ-SEC-004 | No administrative or database ports exposed to the internet | passing | static_config | POL-SG-001, POL-SG-004 | All mapped policies pass on the Terraform plan (POL-SG-001, POL-SG-004). Static analysis only — not verified against a live environment. |
| REQ-NET-001 | Application servers reachable only through the load balancer | passing | static_config | POL-SG-003 | All mapped policies pass on the Terraform plan (POL-SG-003). Static analysis only — not verified against a live environment. |
| REQ-SEC-005 | Least-privilege access for workloads | passing | static_config | POL-IAM-001, POL-IAM-002, POL-IAM-003 | All mapped policies pass on the Terraform plan (POL-IAM-001, POL-IAM-002, POL-IAM-003). Static analysis only — not verified against a live environment. |
| REQ-SEC-006 | Secrets are never stored in configuration | passing | static_config | POL-RDS-005, POL-SEC-002 | All mapped policies pass on the Terraform plan (POL-RDS-005, POL-SEC-002). Static analysis only — not verified against a live environment. |
| REQ-SEC-007 | Server metadata service hardened | passing | static_config | POL-EC2-001 | All mapped policies pass on the Terraform plan (POL-EC2-001). Static analysis only — not verified against a live environment. |
| REQ-SEC-008 | Log storage is private and tamper-resistant | passing | static_config | POL-S3-001, POL-S3-002, POL-S3-003 | All mapped policies pass on the Terraform plan (POL-S3-001, POL-S3-002, POL-S3-003). Static analysis only — not verified against a live environment. |
| REQ-AUD-001 | Audit trail of infrastructure changes | passing | static_config | POL-LOG-001 | All mapped policies pass on the Terraform plan (POL-LOG-001). Static analysis only — not verified against a live environment. |
| REQ-AUD-002 | Network and request logging | passing | static_config | POL-LOG-002, POL-LOG-003 | All mapped policies pass on the Terraform plan (POL-LOG-002, POL-LOG-003). Static analysis only — not verified against a live environment. |
| REQ-AVL-001 | Application keeps running when a server fails | passing | static_config | POL-AVL-001 | All mapped policies pass on the Terraform plan (POL-AVL-001). Static analysis only — not verified against a live environment. |
| REQ-AVL-003 | Automated database backups retained ≥ 7 day(s) | passing | static_config | POL-RDS-003 | All mapped policies pass on the Terraform plan (POL-RDS-003). Static analysis only — not verified against a live environment. |
| REQ-OPS-001 | Production data protected from accidental deletion | passing | static_config | POL-RDS-004 | All mapped policies pass on the Terraform plan (POL-RDS-004). Static analysis only — not verified against a live environment. |
| REQ-PRF-001 | Capacity scales with traffic | passing | static_config | POL-PRF-001 | All mapped policies pass on the Terraform plan (POL-PRF-001). Static analysis only — not verified against a live environment. |
| REQ-CST-001 | Estimated monthly cost within $400 | passing | estimate | — | Estimated $194/month against a $400 budget ($206 headroom). Variable charges can exceed this estimate. (approximate estimate, not a billing guarantee) |
| REQ-SEC-010 | Uploaded files are private and encrypted | passing | static_config | POL-S3-001, POL-S3-002, POL-S3-003, POL-IAM-001 | All mapped policies pass on the Terraform plan (POL-IAM-001, POL-S3-001, POL-S3-002, POL-S3-003). Static analysis only — not verified against a live environment. |
| REQ-AUD-003 | Logs retained for at least 90 days | passing | static_config | POL-LOG-004 | All mapped policies pass on the Terraform plan (POL-LOG-004). Static analysis only — not verified against a live environment. |
| REQ-OPS-003 | Someone is alerted when the service is unhealthy | passing | static_config | POL-OPS-001, POL-OPS-002 | All mapped policies pass on the Terraform plan (POL-OPS-001, POL-OPS-002). Static analysis only — not verified against a live environment. |
| REQ-OPS-002 | Resources are tagged for ownership and cost tracking | passing | static_config | POL-TAG-001 | All mapped policies pass on the Terraform plan (POL-TAG-001). Static analysis only — not verified against a live environment. |

## Assumptions

- **A-00** PostgreSQL 16 on Amazon RDS is the database engine. _You indicated a relational database; PostgreSQL is a widely supported default._
- **A-01** Application servers run Amazon Linux 2023 on Graviton (arm64) instances and Node.js listens on port 3000 behind the load balancer. _Lowest-cost general-purpose option, with the usual default port for your runtime; a placeholder app is installed until you deploy your own._
- **A-02** Two availability zones are used. _The minimum for a load balancer and a Multi-AZ-capable database._
- **A-03** AWS-managed encryption keys are used (not customer-managed KMS keys). _No extra cost or key administration; switch to customer-managed keys if your compliance program requires key control._
- **A-04** Terraform state is stored locally for this MVP. _Avoids creating a state bucket; not suitable for teams or production._
- **A-07** The database starts with 20 GB of storage and grows automatically up to 100 GB. _Sized from your first-year data estimate._
- **A-05** You will supply an issued ACM certificate ARN for your domain before a real deployment. _HTTPS requires a certificate; the simulation uses a placeholder ARN._

## Unresolved items

- ACM certificate ARN for the application's domain (required before a real deployment).
- Confirm the SNS email subscription: AWS sends a confirmation link to ops@example.com after a real deployment.

## Architecture — Balanced

Three-tier layout with private application servers, one NAT gateway and a Multi-AZ database.

Estimated cost: ~$194/month (approximate). Estimated $194/month against a $400 budget ($206 headroom). Variable charges can exceed this estimate.

- **Customers** — Internet users reach the application only through the load balancer. (n/a)
- **AWS account** — Terraform refuses to run against any other account. (provider.aws)
- **Region us-east-1** — Region selected in the interview. (n/a)
- **VPC 10.20.0.0/16** — Private network with separate tiers per availability zone. (aws_vpc.main, aws_default_security_group.default)
- **Public subnets (2 AZs)** — Only components that must face the internet live here. (aws_subnet.public, aws_route_table.public, aws_internet_gateway.main)
- **Private app subnets (2 AZs)** — Servers are not directly reachable from the internet. (aws_subnet.app, aws_route_table.app)
- **NAT gateway ×1** — A single NAT keeps cost down; if its AZ fails, outbound traffic from servers stops. (aws_nat_gateway.main, aws_eip.nat)
- **Isolated data subnets (2 AZs)** — The database has no path to or from the internet. (aws_subnet.data, aws_route_table.data)
- **Application Load Balancer** — Single public entry point; terminates TLS and spreads load across zones. (aws_lb.app, aws_lb_target_group.app, aws_lb_listener.https, aws_security_group.alb)
- **App servers (auto scaling)** — Replaced automatically when unhealthy; scales on CPU. (aws_autoscaling_group.app, aws_launch_template.app, aws_autoscaling_policy.cpu_target, aws_security_group.app)
- **Instance role** — Temporary credentials with only the permissions the servers need. (aws_iam_role.app, aws_iam_instance_profile.app, aws_iam_role_policy_attachment.app_ssm, aws_iam_role_policy.app_read_db_secret)
- **SSM Session Manager** — Administrative access without exposing ports to the internet. (n/a)
- **RDS PostgreSQL 16** — Managed PostgreSQL with automated backups and patching. (aws_db_instance.main, aws_db_subnet_group.main, aws_db_parameter_group.main, aws_security_group.db)
- **Secrets Manager** — Credentials are generated and rotated by AWS, never stored in Terraform. (aws_db_instance.main)
- **Uploads bucket (S3)** — User files live outside the servers so they survive replacement and scaling. (aws_s3_bucket.uploads, aws_s3_bucket_public_access_block.uploads, aws_s3_bucket_policy.uploads, aws_iam_role_policy.app_uploads)
- **Alerts (CloudWatch → email)** — Your team hears about problems before customers do. (aws_sns_topic.alerts, aws_sns_topic_subscription.email, aws_kms_key.alerts, aws_cloudwatch_metric_alarm.alb_5xx, aws_cloudwatch_metric_alarm.unhealthy_hosts, aws_cloudwatch_metric_alarm.db_cpu, aws_cloudwatch_metric_alarm.db_free_storage)
- **Log bucket (S3)** — Private, tamper-resistant store for access, flow and audit logs. (aws_s3_bucket.logs, aws_s3_bucket_public_access_block.logs, aws_s3_bucket_policy.logs)
- **CloudTrail** — Records every AWS API call for auditing. (aws_cloudtrail.main)
- **VPC flow logs** — Network-level record of accepted and rejected connections. (aws_flow_log.vpc)

## Latest validation (passed, config `1b4f6524d733`)

- **Validate requirements specification**: passed — 20 requirements (revision 1); 7 assumptions; 2 unresolved items
- **Validate architecture specification**: passed — Option 'Balanced' with 19 components; estimated $194/month.
- **Write configuration**: passed — 12 Terraform files written (no manual edits); config sha256 1b4f6524d733…
- **Configuration safety gate**: passed — No provisioners, external/http data sources, modules, backends or filesystem functions.
- **terraform fmt**: passed — Formatting is canonical.
- **terraform init**: passed — Providers installed from the lock file / plugin cache (no upgrade).
- **terraform validate**: passed — Configuration is syntactically valid and internally consistent.
- **terraform plan**: passed — SIMULATION plan (placeholder credentials, no AWS API calls). Saved plan b83654a7.
- **Checkov scan**: warning — 167 checks passed, 17 advisory findings (not gating).
- **Trivy config scan**: warning — 10 advisory findings (not gating).
- **Policy evaluation**: passed — 39 checks passed, 0 non-blocking finding(s) (profile: standard).
- **Cost estimate**: passed — ~$194/month (approximate, static price table). Estimated $194/month against a $400 budget ($206 headroom). Variable charges can exceed this estimate.
- **Plan review**: passed — Plan: 72 to create

### Policy findings (0)

No deterministic policy failures.

### Advisory findings from external scanners (27, not gating)

- checkov CKV_AWS_338 (UNRATED) aws_cloudwatch_log_group.postgresql: Ensure CloudWatch log groups retains logs for at least 1 year
- checkov CKV_AWS_158 (UNRATED) aws_cloudwatch_log_group.postgresql: Ensure that CloudWatch Log Group is encrypted by KMS
- checkov CKV_AWS_353 (UNRATED) aws_db_instance.main: Ensure that RDS instances have performance insights enabled
- checkov CKV_AWS_118 (UNRATED) aws_db_instance.main: Ensure that enhanced monitoring is enabled for Amazon RDS instances
- checkov CKV_AWS_252 (UNRATED) aws_cloudtrail.main: Ensure CloudTrail defines an SNS Topic
- checkov CKV_AWS_35 (UNRATED) aws_cloudtrail.main: Ensure CloudTrail logs are encrypted at rest using KMS CMKs
- checkov CKV_AWS_260 (UNRATED) aws_vpc_security_group_ingress_rule.alb_http: Ensure no security groups allow ingress from 0.0.0.0:0 to port 80
- checkov CKV2_AWS_62 (UNRATED) aws_s3_bucket.logs: Ensure S3 buckets should have event notifications enabled
- checkov CKV2_AWS_62 (UNRATED) aws_s3_bucket.uploads: Ensure S3 buckets should have event notifications enabled
- checkov CKV2_AWS_10 (UNRATED) aws_cloudtrail.main: Ensure CloudTrail trails are integrated with CloudWatch Logs
- checkov CKV_AWS_18 (UNRATED) aws_s3_bucket.logs: Ensure the S3 bucket has access logging enabled
- checkov CKV_AWS_18 (UNRATED) aws_s3_bucket.uploads: Ensure the S3 bucket has access logging enabled
- checkov CKV2_AWS_28 (UNRATED) aws_lb.app: Ensure public facing ALB are protected by WAF
- checkov CKV_AWS_144 (UNRATED) aws_s3_bucket.logs: Ensure that S3 bucket has cross-region replication enabled
- checkov CKV_AWS_144 (UNRATED) aws_s3_bucket.uploads: Ensure that S3 bucket has cross-region replication enabled
- checkov CKV_AWS_145 (UNRATED) aws_s3_bucket.logs: Ensure that S3 buckets are encrypted with KMS by default
- checkov CKV_AWS_145 (UNRATED) aws_s3_bucket.uploads: Ensure that S3 buckets are encrypted with KMS by default
- trivy AWS-0017 (LOW) aws_cloudwatch_log_group.postgresql: CloudWatch log groups should be encrypted using CMK
- trivy AWS-0133 (LOW) aws_db_instance.main: Enable Performance Insights to detect potential problems
- trivy AWS-0053 (HIGH) aws_lb.app: Load balancer is exposed to the internet.
- trivy AWS-0015 (HIGH) aws_cloudtrail.main: CloudTrail should use Customer managed keys to encrypt the logs
- trivy AWS-0089 (LOW) aws_s3_bucket.logs: S3 Bucket Logging
- trivy AWS-0132 (HIGH) aws_s3_bucket_server_side_encryption_configuration.logs: S3 encryption should use Customer Managed Keys
- trivy AWS-0162 (LOW) aws_cloudtrail.main: CloudTrail logs should be stored in S3 and also sent to CloudWatch Logs
- trivy AWS-0104 (CRITICAL) aws_vpc_security_group_egress_rule.app_https_out: A security group rule should not allow unrestricted egress to any IP address.
- trivy AWS-0089 (LOW) aws_s3_bucket.uploads: S3 Bucket Logging
- trivy AWS-0132 (HIGH) aws_s3_bucket_server_side_encryption_configuration.uploads: S3 encryption should use Customer Managed Keys

## Plans

- 2026-10-29T06:26:41.682185+00:00 apply plan `3fad6ceb73c5` (simulation): applied — Plan: 72 to create
- 2026-10-29T06:26:30.314485+00:00 apply plan `4da9e2a95e5a` (simulation): rejected — Plan: 73 to create

## Deployments

- 2026-10-29T06:26:48.018770+00:00 apply (SIMULATION): succeeded, 72 resources
  - REQ-SEC-001 Database not publicly accessible: pass — publicly_accessible=False [simulated-state:aws_db_instance]
  - REQ-SEC-002 Database storage encrypted: pass — storage_encrypted=True [simulated-state:aws_db_instance]
  - REQ-SEC-008 Log bucket public access blocked: pass — all four settings true: True [simulated-state:aws_s3_bucket_public_access_block]
  - REQ-SEC-008 Log bucket public access blocked: pass — all four settings true: True [simulated-state:aws_s3_bucket_public_access_block]
  - REQ-AUD-001 CloudTrail logging: pass — enable_logging=True [simulated-state:aws_cloudtrail]
  - REQ-AVL-001 Application health check: error — Not run: simulated resources have no endpoint to call. [simulation]

## Limitations

- No real AWS deployment has been performed for this project. Deployment results are SIMULATED and are not evidence of real infrastructure.
- Policy checks are static analysis of the Terraform plan; they do not prove the running environment is secure.
- Cost figures are approximate estimates from a static price table, not AWS billing data.
- Checkov and Trivy findings are advisory and do not gate deployment.
- References through Terraform locals or child modules are not resolved by the policy engine.
- No requirement has been verified against a live AWS environment (highest verification level reached: static configuration analysis).
