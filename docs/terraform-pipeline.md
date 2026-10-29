# Terraform generation, validation and policies

## Generation

Templates live in `backend/app/services/terraform/templates/` and are rendered with Jinja2 (`StrictUndefined`) from the selected architecture option. Output is passed through `terraform fmt` and is byte-identical for the same specification (except the README timestamp).

Generated project layout ([example](examples/generated-terraform)):

| File | Contents |
|---|---|
| `versions.tf` | Terraform ≥ 1.6, `hashicorp/aws ~> 6.70` (lock file pins the exact version, 6.70.0 when tested) |
| `providers.tf` | region, `allowed_account_ids`, `default_tags` (Project, Environment, ManagedBy, IaPProject); naming locals |
| `variables.tf` | validated inputs: region (restricted to allowed regions), 12-digit account ID, slug, environment, AZs, VPC CIDR, ACM ARN, admin CIDR (never `0.0.0.0/0`) |
| `network.tf` | VPC, locked-down default SG, public / private-app / isolated-data subnets, IGW, NAT (0–2), route tables, VPC flow logs to S3 |
| `security_groups.tf` | ALB ← internet (80/443) → app (runtime port, e.g. 3000) → DB (5432), rules as separate resources referencing security groups |
| `compute.tf` | instance role (SSM core + tag-scoped read of the RDS-managed secret), launch template (IMDSv2, encrypted gp3, AL2023 via SSM parameter), ASG with ELB health checks and target tracking (50 % or 60 % CPU), optional business-hours schedules |
| `load_balancer.tf` | ALB (drop invalid headers, access logs), target group with `/health`, HTTPS listener (`ELBSecurityPolicy-TLS13-1-2-2021-06`), HTTP→HTTPS redirect, optional WAFv2 with AWS managed rule groups |
| `storage.tf` | *(file uploads only)* private uploads bucket: public access block, SSE-S3 with bucket key, versioning, lifecycle for old versions, TLS-only bucket policy, and an app-role policy limited to that bucket |
| `monitoring.tf` | *(alerts only)* customer-managed KMS key (rotation on; CloudWatch allowed to use it), encrypted SNS topic with a CloudWatch-only publish policy, email subscription, alarms for ALB 5xx and unhealthy targets, plus database CPU and free storage |
| `database.tf` | DB subnet group, parameter group with `rds.force_ssl=1`, PostgreSQL 16 with `manage_master_user_password`, encryption, backups, optional Multi-AZ/deletion protection, log group with retention |
| `logging.tf` | private, encrypted, versioned log bucket with lifecycle, TLS-only bucket policy, delivery permissions, CloudTrail (multi-region, log file validation) |
| `outputs.tf` | ALB DNS, VPC, ASG, log bucket, DB endpoint and secret ARN, trail ARN |
| `terraform.tfvars.example` | placeholders only |
| `README.md`, `traceability.json` | usage, state warning, teardown notes; requirement ↔ resource mapping |

Every generated configuration is validated by `terraform validate` in the test suite (lean, balanced, resilient, no-database, SSH-admin and EU-residency variants).

## Pipeline steps

| # | Step | Failure handling |
|---|---|---|
| 1 | Validate requirements specification | stops; requirements → `blocked` |
| 2 | Validate architecture (selected, generated, same requirements revision) | stops |
| 3 | Write configuration (generated + manual edits), compute config SHA-256 | stops on invalid files |
| 3b | Configuration safety gate (no provisioners, external/http data sources, modules, backends, filesystem functions) | stops before Terraform runs |
| 4 | `terraform fmt -check -diff` | warning only |
| 5 | `terraform init -input=false` (lock file, shared plugin cache, no upgrade), then provider allow-list (`hashicorp/aws` only) | stops |
| 6 | `terraform validate -json` (diagnostics shown with file:line) | stops |
| 7 | `terraform plan -out=<id>.tfplan` (+ `-refresh=false` in simulation), `terraform show -json` | stops |
| 8 | Deterministic policy evaluation | blocks approval on critical (standard) / critical+high (strict) |
| 9 | Checkov (advisory) | `unavailable` if not installed |
| 10 | Trivy config (advisory) | `unavailable` if not installed |
| 11 | Cost estimate | warning if over budget |
| 12 | Plan review | — |

If Terraform is not installed, steps 4–8 are reported as **unavailable** and requirements as **blocked** — never as passed.

## Policy engine

`policy/graph.py` builds a resource list from `planned_values` and a reference graph from `configuration.root_module.resources[*].expressions` (e.g. which security group a rule belongs to, which subnets a DB subnet group uses, which route table routes to an internet gateway). This matters because IDs are unknown at plan time.

38 policies (`policy/rules.py`):

| Area | Policies |
|---|---|
| Database | RDS-001 not public · RDS-002 encrypted · RDS-003 backup retention ≥ requirement · RDS-004 deletion protection + final snapshot · RDS-005 managed master password / no password in config · RDS-006 TLS enforced · NET-001 DB subnets have no IGW route · AVL-002 Multi-AZ |
| Network | SG-001 no internet ingress to admin/DB/all ports (80/443 allowed only on internet-facing LB SGs) · SG-002 DB only from app SG · SG-003 app only from LB SG (or approved SSH CIDR) · SG-004 default SG empty · EC2-002 app servers have no public IPs · WAF-001 · REG-001 region in allowed set |
| IAM | IAM-001 no `*` actions, `NotAction`, service wildcards or privilege-escalation actions on `*` · IAM-002 no admin managed policies · IAM-003 no IAM users / access keys |
| Compute & storage | EC2-001 IMDSv2 · EC2-003 encrypted volumes · S3-001 public access block / no public ACL or anonymous policy · S3-002 explicit default encryption · S3-003 versioning |
| TLS & web | ALB-001 HTTPS with TLS 1.2+ policy · ALB-002 HTTP only redirects · ALB-003 drop invalid headers |
| Logging & ops | LOG-001 CloudTrail multi-region + validation · LOG-002 VPC flow logs · LOG-003 ALB access logs · LOG-004 log retention ≥ requirement · AVL-001 ASG min size, ≥ 2 subnets, ELB health checks · PRF-001 target tracking + headroom · OPS-001 LB alarms notify a subscribed topic · OPS-002 alert topic encrypted with a customer-managed key · CST-001 off-hours schedules · TAG-001 required tags |
| Secrets & change | SEC-002 credential patterns in user data/tags (supplementary pattern scan, values redacted) · CHG-001 destruction/replacement of stateful resources |

Baseline policies always run; others are enabled by the requirements that reference them. A policy that raises an exception produces an `error` result, which blocks deployment.

Tests: positive (the real generated plan passes everything), negative on a real plan with three deliberate misconfigurations, and targeted negative tests for each family on minimal synthetic plans (`backend/tests/test_policy_engine.py`).

### External scanners

Checkov and Trivy findings are stored and shown as **advisory**. On the generated configuration they report items such as "CloudTrail should use a customer-managed KMS key", "enable RDS Performance Insights", or "load balancer is exposed to the internet" — some are reasonable hardening suggestions, others contradict deliberate design (a public web application needs a public load balancer; SSE-S3 is required for ALB log delivery). They therefore inform but do not gate. Note that on the deliberately insecure configuration Checkov independently reports `CKV_AWS_17` (RDS publicly accessible), corroborating the deterministic finding.

## Manual edits and the insecure-change demo

Edits are stored as per-file overrides, separate from generated files, and bump the configuration revision (so earlier scans are marked stale and earlier plans can no longer be applied). "Introduce insecure test change" applies one of three documented literal edits — public database, SSH from `0.0.0.0/0`, wildcard IAM policy — exactly as a user edit would. Detection comes from the normal pipeline; there is no special-casing in the UI.

## Plan review

`plan_review.py` classifies each change (create/update/replace/delete), marks stateful resources, assigns a risk level, explains replacements using Terraform's `replace_paths`, and lists data-loss risks, downtime risks (replacement of LB/ASG/NAT/DB; DB instance class/Multi-AZ/version updates) and security-relevant changes.
