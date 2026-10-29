"""Infrastructure Requirements Compiler.

Turns confirmed interview facts into a structured, machine-checkable
requirements specification. Every requirement names the deterministic
policies (or other verification method) that decide its status — the compiler
never marks anything as verified.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.domain.interview import InterviewState
from app.domain.requirements import (
    Assumption,
    Category,
    Origin,
    Priority,
    Requirement,
    RequirementsSpec,
    RequirementStatus,
    Severity,
)

EU_REGIONS = ["eu-west-1", "eu-central-1", "eu-west-2"]
RUNTIME_PORTS = {"node": 3000, "python": 8000, "java": 8080, "dotnet": 5000, "go": 8080, "php": 8080, "ruby": 3000, "other": 8080}
RUNTIME_LABELS = {
    "node": "Node.js",
    "python": "Python",
    "java": "Java / Kotlin",
    "dotnet": ".NET",
    "go": "Go",
    "php": "PHP",
    "ruby": "Ruby",
    "other": "your application",
}
DB_STORAGE_GB = {"small": 20, "medium": 100, "large": 500}
# Time zone used for business-hours schedules, by region.
REGION_TIMEZONES = {
    "us-east-1": "America/New_York",
    "us-east-2": "America/New_York",
    "us-west-2": "America/Los_Angeles",
    "eu-west-1": "Europe/Dublin",
    "eu-west-2": "Europe/London",
    "eu-central-1": "Europe/Berlin",
}
US_REGIONS = ["us-east-1", "us-east-2", "us-west-2"]


class CompileError(ValueError):
    pass


def facts_from_interview(state: InterviewState) -> dict[str, Any]:
    """Normalise confirmed answers into compiler facts (and derived values)."""
    a = {k: v.value for k, v in state.answers.items()}
    env = a.get("environment", "development")
    compliance = a.get("compliance", "none")
    sensitivity = a.get("data_sensitivity", "internal")
    availability = a.get("availability", "tolerate_minutes")
    residency = a.get("data_residency", "none")
    facts: dict[str, Any] = {
        "environment": env,
        "deployment_type": a.get("deployment_type", "new"),
        "needs_database": a.get("needs_database", "yes") == "yes",
        "traffic": a.get("traffic", "low"),
        "data_sensitivity": sensitivity,
        "compliance": compliance,
        "data_residency": residency,
        "region": a.get("region", "us-east-1"),
        "availability": availability,
        "tls": a.get("tls", "acm"),
        "admin_access": a.get("admin_access", "ssm"),
        "admin_cidr": a.get("admin_cidr"),
        "audit_logging": a.get("audit_logging", "yes") == "yes" or compliance in ("hipaa", "pci"),
        "budget": float(a["budget"]) if a.get("budget") is not None else None,
        # Customer profile
        "industry": a.get("industry", "other"),
        "user_geography": a.get("user_geography"),
        "app_runtime": a.get("app_runtime", "other"),
        "traffic_pattern": a.get("traffic_pattern", "steady"),
        "off_hours_shutdown": a.get("off_hours") == "yes",
        "db_size": a.get("db_size", "small"),
        "file_uploads": a.get("file_uploads") == "yes",
        "ops_team": a.get("ops_team", "some"),
        "alerting": a.get("alerting") == "email",
        "alert_email": a.get("alert_email") if a.get("alerting") == "email" else None,
    }
    if a.get("recovery_window") is not None:
        facts["backup_days"] = int(a["recovery_window"])
    elif compliance in ("hipaa", "pci"):
        facts["backup_days"] = 35
    elif availability == "high":
        facts["backup_days"] = 14
    elif env == "development":
        facts["backup_days"] = 1
    else:
        facts["backup_days"] = 7
    facts["log_retention_days"] = int(a["log_retention"]) if a.get("log_retention") is not None else None
    facts["app_port"] = RUNTIME_PORTS.get(facts["app_runtime"], 8080)
    facts["memory_heavy"] = facts["app_runtime"] in ("java", "dotnet")
    facts["db_storage_gb"] = DB_STORAGE_GB.get(facts["db_size"], 20)
    facts["scale_out_cpu"] = 50 if facts["traffic_pattern"] == "spiky" else 60
    facts["schedule_timezone"] = REGION_TIMEZONES.get(facts["region"], "UTC")
    facts["min_app_instances"] = 2 if (env == "production" or availability == "high") else 1
    facts["require_private_app"] = sensitivity == "regulated" or compliance in ("hipaa", "pci")
    facts["require_waf"] = compliance == "pci" or (env == "production" and sensitivity == "regulated")
    facts["allowed_regions"] = EU_REGIONS if residency == "eu" else US_REGIONS if residency == "us" else []
    return facts


def _origin(state: InterviewState, *qids: str) -> Origin:
    return Origin.confirmed if any(q in state.answers for q in qids) else Origin.derived


def _src(state: InterviewState, *qids: str) -> str:
    parts = [f"{q} = {state.answers[q].display}" for q in qids if q in state.answers]
    return "Interview: " + "; ".join(parts) if parts else "Security-first baseline (always applied)"


def compile_requirements(state: InterviewState, revision: int = 1, require_complete: bool = True) -> RequirementsSpec:
    """``require_complete=False`` is used only internally to estimate budget
    feasibility while the interview is in progress; such specs are never stored."""
    if require_complete and not state.complete:
        raise CompileError("The interview is not complete; requirements cannot be compiled from unconfirmed answers.")
    f = facts_from_interview(state)
    reqs: list[Requirement] = []
    db = f["needs_database"]
    prod = f["environment"] == "production"

    def add(**kw: Any) -> None:
        reqs.append(Requirement(**kw))

    if db:
        add(
            id="REQ-SEC-001",
            title="Database is not reachable from the internet",
            description="The database has no public endpoint, lives in subnets without an internet route, and accepts connections only from the application tier.",
            category=Category.security,
            priority=Priority.must,
            severity=Severity.critical,
            origin=_origin(state, "data_sensitivity"),
            source=_src(state, "data_sensitivity", "needs_database"),
            rationale="A publicly reachable database is the most common cause of customer data exposure.",
            decisions=["DEC-NET-TIERS", "DEC-DB-PLACEMENT"],
            resources=[
                "aws_db_instance.main",
                "aws_db_subnet_group.main",
                "aws_security_group.db",
                "aws_vpc_security_group_ingress_rule.db_from_app",
            ],
            policies=["POL-RDS-001", "POL-NET-001", "POL-SG-002"],
            verification_method="Plan-based policies; live check of PubliclyAccessible and security group rules after a real deployment.",
        )
    add(
        id="REQ-SEC-002",
        title="Data encrypted at rest",
        description="Database storage, server volumes and log storage are encrypted.",
        category=Category.security,
        priority=Priority.must,
        severity=Severity.high,
        origin=_origin(state, "data_sensitivity"),
        source=_src(state, "data_sensitivity"),
        rationale="Protects data in snapshots, backups and decommissioned disks.",
        decisions=["DEC-ENCRYPTION"],
        resources=[
            r
            for r in [
                "aws_db_instance.main" if db else "",
                "aws_launch_template.app",
                "aws_s3_bucket_server_side_encryption_configuration.logs",
            ]
            if r
        ],
        policies=[p for p in ["POL-RDS-002" if db else "", "POL-EC2-003", "POL-S3-002"] if p],
        verification_method="Plan-based policies on storage_encrypted, EBS and S3 encryption settings.",
    )
    if f["tls"] == "acm":
        add(
            id="REQ-SEC-003",
            title="Data encrypted in transit",
            description="Users connect over HTTPS (TLS 1.2+); HTTP redirects to HTTPS"
            + ("; database connections require TLS." if db else "."),
            category=Category.security,
            priority=Priority.must,
            severity=Severity.high,
            origin=_origin(state, "tls"),
            source=_src(state, "tls"),
            rationale="Prevents interception of credentials and customer data.",
            decisions=["DEC-TLS"],
            resources=["aws_lb_listener.https", "aws_lb_listener.http_redirect"] + (["aws_db_parameter_group.main"] if db else []),
            policies=["POL-ALB-001", "POL-ALB-002"] + (["POL-RDS-006"] if db else []),
            verification_method="Plan-based listener and parameter-group policies.",
        )
    else:
        add(
            id="REQ-SEC-003",
            title="Data encrypted in transit",
            description="Not required: user confirmed an HTTP-only development environment serving public data.",
            category=Category.security,
            priority=Priority.could,
            severity=Severity.medium,
            origin=Origin.confirmed,
            source=_src(state, "tls"),
            rationale="Accepted only because the data is public and the environment is development.",
            verification_method="Not applicable.",
            status=RequirementStatus.not_applicable,
            status_reason="User explicitly selected HTTP-only for a public-data development environment.",
        )
    add(
        id="REQ-SEC-004",
        title="No administrative or database ports exposed to the internet",
        description="No security group allows SSH, RDP, database or all-port access from 0.0.0.0/0 or ::/0. "
        + (
            "Administration uses AWS Systems Manager Session Manager."
            if f["admin_access"] != "ssh"
            else f"SSH is limited to {f['admin_cidr']}."
        ),
        category=Category.security,
        priority=Priority.must,
        severity=Severity.critical,
        origin=_origin(state, "admin_access"),
        source=_src(state, "admin_access", "admin_cidr"),
        rationale="Internet-exposed administrative interfaces are continuously scanned and brute-forced.",
        decisions=["DEC-ADMIN-ACCESS"],
        resources=["aws_security_group.alb", "aws_security_group.app", "aws_default_security_group.default"],
        policies=["POL-SG-001", "POL-SG-004"],
        verification_method="Plan-based analysis of every ingress rule.",
    )
    add(
        id="REQ-NET-001",
        title="Application servers reachable only through the load balancer",
        description="Application security group accepts traffic only from the load balancer security group.",
        category=Category.networking,
        priority=Priority.must,
        severity=Severity.critical,
        origin=Origin.derived,
        source="Security-first baseline (always applied)",
        rationale="Keeps servers off the internet even if they have public IPs for outbound traffic.",
        decisions=["DEC-NET-TIERS"],
        resources=["aws_security_group.app", "aws_vpc_security_group_ingress_rule.app_from_alb"],
        policies=["POL-SG-003"],
        verification_method="Plan-based security group reference analysis.",
    )
    if f["require_private_app"]:
        add(
            id="REQ-NET-002",
            title="Application servers have no public IP addresses",
            description="Application servers run in private subnets and reach the internet only through NAT.",
            category=Category.networking,
            priority=Priority.must,
            severity=Severity.high,
            origin=_origin(state, "data_sensitivity", "compliance"),
            source=_src(state, "data_sensitivity", "compliance"),
            rationale="Required defence in depth for regulated data.",
            decisions=["DEC-NET-TIERS"],
            resources=["aws_launch_template.app", "aws_autoscaling_group.app", "aws_subnet.app"],
            policies=["POL-EC2-002"],
            verification_method="Plan-based subnet routing analysis.",
        )
    add(
        id="REQ-SEC-005",
        title="Least-privilege access for workloads",
        description="Application servers use a role with only the permissions they need; no administrator policies, wildcard grants or IAM users with access keys.",
        category=Category.security,
        priority=Priority.must,
        severity=Severity.high,
        origin=Origin.derived,
        source="Security-first baseline (always applied)",
        rationale="Limits the blast radius of a compromised server.",
        decisions=["DEC-IAM"],
        resources=["aws_iam_role.app", "aws_iam_role_policy.app_read_db_secret", "aws_iam_role_policy_attachment.app_ssm"],
        policies=["POL-IAM-001", "POL-IAM-002", "POL-IAM-003"],
        verification_method="Plan-based IAM policy document analysis.",
    )
    add(
        id="REQ-SEC-006",
        title="Secrets are never stored in configuration",
        description="Database credentials are generated and held by AWS Secrets Manager; no credentials appear in Terraform, user data or tags.",
        category=Category.security,
        priority=Priority.must,
        severity=Severity.high,
        origin=Origin.derived,
        source="Security-first baseline (always applied)",
        rationale="Terraform state and plan files are widely readable and long-lived.",
        decisions=["DEC-SECRETS"],
        resources=["aws_db_instance.main"] if db else [],
        policies=(["POL-RDS-005"] if db else []) + ["POL-SEC-002"],
        verification_method="Plan-based attribute policy plus supplementary credential pattern scan.",
    )
    add(
        id="REQ-SEC-007",
        title="Server metadata service hardened",
        description="Instances require IMDSv2 session tokens.",
        category=Category.security,
        priority=Priority.must,
        severity=Severity.high,
        origin=Origin.derived,
        source="Security-first baseline (always applied)",
        rationale="Mitigates SSRF-based theft of instance credentials.",
        decisions=["DEC-IAM"],
        resources=["aws_launch_template.app"],
        policies=["POL-EC2-001"],
        verification_method="Plan-based launch template policy.",
    )
    add(
        id="REQ-SEC-008",
        title="Log storage is private and tamper-resistant",
        description="The log bucket blocks all public access, is encrypted and versioned.",
        category=Category.security,
        priority=Priority.must,
        severity=Severity.high,
        origin=Origin.derived,
        source="Security-first baseline (always applied)",
        rationale="Logs often contain sensitive data and are evidence during incidents.",
        decisions=["DEC-LOGGING"],
        resources=["aws_s3_bucket.logs", "aws_s3_bucket_public_access_block.logs", "aws_s3_bucket_versioning.logs"],
        policies=["POL-S3-001", "POL-S3-002", "POL-S3-003"],
        verification_method="Plan-based S3 policies.",
    )
    if f["require_waf"]:
        add(
            id="REQ-SEC-009",
            title="Web application firewall in front of the application",
            description="AWS WAF with AWS managed rule groups filters common web exploits.",
            category=Category.security,
            priority=Priority.must,
            severity=Severity.high,
            origin=_origin(state, "compliance", "data_sensitivity"),
            source=_src(state, "compliance", "data_sensitivity"),
            rationale="Expected control for payment-card and regulated workloads.",
            decisions=["DEC-WAF"],
            resources=["aws_wafv2_web_acl.main", "aws_wafv2_web_acl_association.main"],
            policies=["POL-WAF-001"],
            verification_method="Plan-based association check.",
        )
    if f["audit_logging"]:
        add(
            id="REQ-AUD-001",
            title="Audit trail of infrastructure changes",
            description="A multi-region CloudTrail trail with log file validation records every AWS API call.",
            category=Category.compliance,
            priority=Priority.must,
            severity=Severity.high,
            origin=_origin(state, "audit_logging", "compliance"),
            source=_src(state, "audit_logging", "compliance"),
            rationale="Answers who changed what, and when.",
            decisions=["DEC-LOGGING"],
            resources=["aws_cloudtrail.main"],
            policies=["POL-LOG-001"],
            verification_method="Plan-based CloudTrail policy; live trail status after a real deployment.",
        )
    if f["audit_logging"] or prod:
        add(
            id="REQ-AUD-002",
            title="Network and request logging",
            description="VPC flow logs and load balancer access logs are delivered to the private log bucket.",
            category=Category.operational,
            priority=Priority.should,
            severity=Severity.medium,
            origin=_origin(state, "audit_logging", "environment"),
            source=_src(state, "audit_logging", "environment"),
            rationale="Needed to investigate incidents and abuse.",
            decisions=["DEC-LOGGING"],
            resources=["aws_flow_log.vpc", "aws_lb.app"],
            policies=["POL-LOG-002", "POL-LOG-003"],
            verification_method="Plan-based logging policies.",
        )
    if f["availability"] != "best_effort":
        add(
            id="REQ-AVL-001",
            title="Application keeps running when a server fails",
            description=f"An auto scaling group with load balancer health checks keeps at least {f['min_app_instances']} instance(s) running across two availability zones"
            + (" during business hours." if f["off_hours_shutdown"] else "."),
            category=Category.availability,
            priority=Priority.must,
            severity=Severity.high,
            origin=_origin(state, "availability", "environment"),
            source=_src(state, "availability", "environment"),
            rationale="Servers fail; replacement must be automatic.",
            decisions=["DEC-COMPUTE"],
            resources=["aws_autoscaling_group.app"],
            policies=["POL-AVL-001"],
            verification_method="Plan-based ASG configuration policy.",
        )
    if db and f["availability"] == "high":
        add(
            id="REQ-AVL-002",
            title="Database survives an availability-zone outage",
            description="RDS Multi-AZ keeps a synchronous standby that takes over automatically (typically within 1–2 minutes).",
            category=Category.availability,
            priority=Priority.must,
            severity=Severity.high,
            origin=_origin(state, "availability"),
            source=_src(state, "availability"),
            rationale="User stated that service interruptions are not acceptable.",
            decisions=["DEC-DB-HA"],
            resources=["aws_db_instance.main"],
            policies=["POL-AVL-002"],
            verification_method="Plan-based multi_az policy.",
        )
    if db:
        add(
            id="REQ-AVL-003",
            title=f"Automated database backups retained ≥ {f['backup_days']} day(s)",
            description=f"Point-in-time recovery is available for at least {f['backup_days']} day(s).",
            category=Category.availability,
            priority=Priority.must if prod else Priority.should,
            severity=Severity.medium,
            origin=_origin(state, "recovery_window", "environment", "compliance", "availability"),
            source=_src(state, "recovery_window", "compliance"),
            rationale="Recovers from data corruption and accidental deletion.",
            decisions=["DEC-DB-HA"],
            resources=["aws_db_instance.main"],
            policies=["POL-RDS-003"],
            verification_method="Plan-based backup_retention_period policy.",
        )
    if db and prod:
        add(
            id="REQ-OPS-001",
            title="Production data protected from accidental deletion",
            description="Deletion protection is enabled and a final snapshot is taken if the database is ever deleted.",
            category=Category.operational,
            priority=Priority.must,
            severity=Severity.high,
            origin=_origin(state, "environment"),
            source=_src(state, "environment"),
            rationale="A single mistaken command must not destroy customer data.",
            decisions=["DEC-DB-HA"],
            resources=["aws_db_instance.main"],
            policies=["POL-RDS-004"],
            verification_method="Plan-based deletion settings policy.",
        )
    add(
        id="REQ-PRF-001",
        title="Capacity scales with traffic",
        description=f"Target-tracking auto scaling adds servers when average CPU exceeds {f['scale_out_cpu']}%"
        + (", with extra headroom for sudden spikes." if f["traffic_pattern"] == "spiky" else "."),
        category=Category.performance,
        priority=Priority.should,
        severity=Severity.medium,
        origin=_origin(state, "traffic", "traffic_pattern"),
        source=_src(state, "traffic", "traffic_pattern"),
        rationale="The original request mentioned handling increasing traffic."
        if "traffic" in state.initial_request.lower()
        else "Avoids over-provisioning for peak load.",
        decisions=["DEC-COMPUTE"],
        resources=["aws_autoscaling_group.app", "aws_autoscaling_policy.cpu_target"],
        policies=["POL-PRF-001"],
        verification_method="Plan-based scaling policy check.",
    )
    if f["allowed_regions"]:
        add(
            id="REQ-CMP-001",
            title=f"Data stays in {'the EU' if f['data_residency'] == 'eu' else 'the US'}",
            description=f"All resources are deployed in one of: {', '.join(f['allowed_regions'])}.",
            category=Category.compliance,
            priority=Priority.must,
            severity=Severity.critical,
            origin=_origin(state, "data_residency"),
            source=_src(state, "data_residency", "region"),
            rationale="Data residency obligations.",
            decisions=["DEC-REGION"],
            resources=["provider.aws"],
            policies=["POL-REG-001"],
            verification_method="Plan-based provider region policy; Terraform variable validation.",
        )
    if f["budget"] is not None:
        add(
            id="REQ-CST-001",
            title=f"Estimated monthly cost within ${f['budget']:,.0f}",
            description="The selected architecture's estimated monthly cost does not exceed the budget. Security controls are never removed to meet it.",
            category=Category.cost,
            priority=Priority.must,
            severity=Severity.medium,
            origin=_origin(state, "budget"),
            source=_src(state, "budget"),
            rationale="Stated monthly budget.",
            decisions=["DEC-COST"],
            verification_method="Cost model estimate (approximate; not a billing guarantee).",
        )
    if f["file_uploads"]:
        add(
            id="REQ-SEC-010",
            title="Uploaded files are private and encrypted",
            description="User files live in a dedicated S3 bucket that blocks all public access, is encrypted and versioned, rejects unencrypted connections, and is readable and writable only by the application's role.",
            category=Category.security,
            priority=Priority.must,
            severity=Severity.high,
            origin=_origin(state, "file_uploads"),
            source=_src(state, "file_uploads", "data_sensitivity"),
            rationale="Misconfigured file buckets are a leading cause of public data leaks.",
            decisions=["DEC-STORAGE"],
            resources=[
                "aws_s3_bucket.uploads",
                "aws_s3_bucket_public_access_block.uploads",
                "aws_s3_bucket_server_side_encryption_configuration.uploads",
                "aws_iam_role_policy.app_uploads",
            ],
            policies=["POL-S3-001", "POL-S3-002", "POL-S3-003", "POL-IAM-001"],
            verification_method="Plan-based S3 and IAM policies; every bucket in the plan is checked.",
        )
    if f["log_retention_days"]:
        days = f["log_retention_days"]
        add(
            id="REQ-AUD-003",
            title=f"Logs retained for at least {days // 365} year(s)" if days >= 365 else f"Logs retained for at least {days} days",
            description=f"Log bucket lifecycle rules and CloudWatch log groups keep logs for at least {days} days before deleting them.",
            category=Category.compliance,
            priority=Priority.must if f["compliance"] in ("pci", "hipaa") else Priority.should,
            severity=Severity.medium,
            origin=_origin(state, "log_retention"),
            source=_src(state, "log_retention", "compliance"),
            rationale="Logs are the evidence trail for incident investigations and audits.",
            decisions=["DEC-LOGGING"],
            resources=["aws_s3_bucket_lifecycle_configuration.logs"] + (["aws_cloudwatch_log_group.postgresql"] if db else []),
            policies=["POL-LOG-004"],
            verification_method="Plan-based lifecycle expiration and log group retention policy.",
        )
    if f["alerting"]:
        add(
            id="REQ-OPS-003",
            title="Someone is alerted when the service is unhealthy",
            description=f"CloudWatch alarms on load balancer errors and unhealthy servers{' and database CPU and free storage' if db else ''} notify {f['alert_email']} through an encrypted SNS topic.",
            category=Category.operational,
            priority=Priority.must if prod else Priority.should,
            severity=Severity.medium,
            origin=_origin(state, "alerting", "alert_email"),
            source=_src(state, "ops_team", "alerting", "alert_email"),
            rationale="Problems should reach your team before they reach your customers.",
            decisions=["DEC-MONITORING"],
            resources=[
                "aws_sns_topic.alerts",
                "aws_sns_topic_subscription.email",
                "aws_kms_key.alerts",
                "aws_cloudwatch_metric_alarm.alb_5xx",
                "aws_cloudwatch_metric_alarm.unhealthy_hosts",
            ]
            + (["aws_cloudwatch_metric_alarm.db_cpu", "aws_cloudwatch_metric_alarm.db_free_storage"] if db else []),
            policies=["POL-OPS-001", "POL-OPS-002"],
            verification_method="Plan-based check that alarms watch the load balancer and notify a subscribed, encrypted topic.",
        )
    if f["off_hours_shutdown"]:
        add(
            id="REQ-CST-002",
            title="Servers switch off outside business hours",
            description=f"Scheduled scaling sets the server count to zero at 19:00 and restores it at 07:00 on weekdays ({f['schedule_timezone']}); the database keeps running.",
            category=Category.cost,
            priority=Priority.should,
            severity=Severity.low,
            origin=_origin(state, "off_hours"),
            source=_src(state, "environment", "traffic_pattern", "off_hours"),
            rationale="Non-production servers that nobody uses overnight are wasted spend.",
            decisions=["DEC-SCHEDULE"],
            resources=["aws_autoscaling_schedule.business_hours_start", "aws_autoscaling_schedule.business_hours_stop"],
            policies=["POL-CST-001"],
            verification_method="Plan-based check for scale-to-zero schedules on the auto scaling group.",
        )
    add(
        id="REQ-OPS-002",
        title="Resources are tagged for ownership and cost tracking",
        description="Every taggable resource carries Project, Environment and ManagedBy tags.",
        category=Category.operational,
        priority=Priority.could,
        severity=Severity.low,
        origin=Origin.derived,
        source="Security-first baseline (always applied)",
        rationale="Enables cost allocation and safe cleanup.",
        decisions=["DEC-TAGS"],
        resources=["provider.aws"],
        policies=["POL-TAG-001"],
        verification_method="Plan-based tag policy.",
    )

    assumptions = [
        Assumption(
            id="A-01",
            statement=f"Application servers run Amazon Linux 2023 on Graviton (arm64) instances and {RUNTIME_LABELS.get(f['app_runtime'], 'the application')} listens on port {f['app_port']} behind the load balancer.",
            reason="Lowest-cost general-purpose option, with the usual default port for your runtime; a placeholder app is installed until you deploy your own.",
            can_change_in="Architecture workspace / Terraform variables",
        ),
        Assumption(
            id="A-02",
            statement="Two availability zones are used.",
            reason="The minimum for a load balancer and a Multi-AZ-capable database.",
            can_change_in="Terraform variable availability_zones",
        ),
        Assumption(
            id="A-03",
            statement="AWS-managed encryption keys are used (not customer-managed KMS keys).",
            reason="No extra cost or key administration; switch to customer-managed keys if your compliance program requires key control.",
            can_change_in="Terraform",
        ),
        Assumption(
            id="A-04",
            statement="Terraform state is stored locally for this MVP.",
            reason="Avoids creating a state bucket; not suitable for teams or production.",
            can_change_in="Generated README",
        ),
    ]
    if db:
        assumptions.insert(
            0,
            Assumption(
                id="A-00",
                statement="PostgreSQL 16 on Amazon RDS is the database engine.",
                reason="You indicated a relational database; PostgreSQL is a widely supported default.",
                can_change_in="Interview answer needs_database / Terraform",
            ),
        )
    if f["traffic_pattern"] == "business_hours" and f["off_hours_shutdown"]:
        assumptions.append(
            Assumption(
                id="A-06",
                statement=f"Business hours are 07:00–19:00, Monday to Friday, in {f['schedule_timezone']}.",
                reason="Derived from the selected region; change it if your team works in another time zone.",
                can_change_in="Terraform variable business_hours_timezone",
            )
        )
    if db:
        assumptions.append(
            Assumption(
                id="A-07",
                statement=f"The database starts with {f['db_storage_gb']} GB of storage and grows automatically up to {f['db_storage_gb'] * 5} GB.",
                reason="Sized from your first-year data estimate.",
                can_change_in="Interview answer db_size / Terraform",
            )
        )
    if f["tls"] == "acm":
        assumptions.append(
            Assumption(
                id="A-05",
                statement="You will supply an issued ACM certificate ARN for your domain before a real deployment.",
                reason="HTTPS requires a certificate; the simulation uses a placeholder ARN.",
                can_change_in="terraform.tfvars",
            )
        )

    unresolved = []
    if f["tls"] == "acm":
        unresolved.append("ACM certificate ARN for the application's domain (required before a real deployment).")
    if f["compliance"] in ("hipaa", "pci", "gdpr"):
        unresolved.append(
            f"Formal {f['compliance'].upper()} assessment: generated controls support but do not certify compliance (e.g. BAAs, processes, application-level controls are out of scope)."
        )
    if f["alerting"]:
        unresolved.append(
            f"Confirm the SNS email subscription: AWS sends a confirmation link to {f['alert_email']} after a real deployment."
        )
    if f["deployment_type"] == "existing":
        unresolved.append("Existing resources are not imported or modified; this project creates a separate, new environment.")

    return RequirementsSpec(
        revision=revision,
        generated_at=datetime.now(UTC),
        facts=f,
        requirements=reqs,
        assumptions=assumptions,
        unresolved=unresolved,
        conflicts=[c for c in state.conflicts if c.severity == "warning"],
        rejected=state.rejected,
    )
