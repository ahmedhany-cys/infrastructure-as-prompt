"""Architecture engine: derives candidate architectures from the requirements
specification, filters out options that would violate a "must" requirement,
and produces diagram components and costs from the same parameters that the
Terraform generator consumes."""

from __future__ import annotations

from datetime import UTC, datetime

from app.domain.architecture import (
    ArchitectureOption,
    ArchitectureParams,
    ArchitectureSpec,
    Component,
    Connection,
    Decision,
    ExcludedOption,
    TradeoffScore,
)
from app.domain.requirements import Priority, RequirementsSpec, RequirementStatus
from app.services import pricing
from app.services.compiler import RUNTIME_LABELS

INSTANCE_BY_TRAFFIC = {"low": "t4g.small", "moderate": "t4g.medium", "high": "t4g.large"}
# JVM / .NET runtimes reserve more memory: one size up.
INSTANCE_UPSIZE = {"t4g.small": "t4g.medium", "t4g.medium": "t4g.large", "t4g.large": "t4g.xlarge"}
DB_BY_TRAFFIC = {"low": "db.t4g.micro", "moderate": "db.t4g.small", "high": "db.t4g.medium"}
DB_UPSIZE = {
    "db.t4g.micro": "db.t4g.small",
    "db.t4g.small": "db.t4g.medium",
    "db.t4g.medium": "db.t4g.large",
    "db.t4g.large": "db.t4g.large",
}
ASG_MAX = {"low": 3, "moderate": 6, "high": 10}

OPTION_NAMES = {"lean": "Lean", "balanced": "Balanced", "resilient": "Resilient"}


def _params(option: str, f: dict) -> ArchitectureParams:
    traffic = f.get("traffic", "low")
    region = f.get("region", "us-east-1")
    env = f.get("environment", "development")
    prod = env == "production"
    db_class = DB_BY_TRAFFIC[traffic]
    instance = INSTANCE_BY_TRAFFIC[traffic]
    if f.get("memory_heavy"):
        instance = INSTANCE_UPSIZE[instance]
    spiky = f.get("traffic_pattern") == "spiky"
    asg_max = ASG_MAX[traffic] * (2 if spiky else 1)
    log_floor = int(f.get("log_retention_days") or 0)
    common = dict(
        app_port=int(f.get("app_port", 8080)),
        app_runtime=str(f.get("app_runtime", "other")),
        scale_out_cpu=int(f.get("scale_out_cpu", 60)),
        scheduled_scaling=bool(f.get("off_hours_shutdown")),
        schedule_timezone=str(f.get("schedule_timezone", "UTC")),
        uploads_bucket=bool(f.get("file_uploads")),
        alerts=bool(f.get("alerting")),
        alert_email=f.get("alert_email"),
        db_storage_gb=int(f.get("db_storage_gb", 20)),
        region=region,
        availability_zones=[f"{region}a", f"{region}b"],
        environment=env,
        db_enabled=bool(f.get("needs_database", True)),
        https=f.get("tls", "acm") == "acm",
        admin_access="ssh" if f.get("admin_access") == "ssh" else "ssm",
        admin_cidr=f.get("admin_cidr"),
        cloudtrail=bool(f.get("audit_logging", True)),
        flow_logs=bool(f.get("audit_logging", True)) or prod,
        alb_access_logs=bool(f.get("audit_logging", True)) or prod,
        backup_retention_days=int(f.get("backup_days", 7)),
        allowed_regions=list(f.get("allowed_regions") or []),
    )
    min_instances = int(f.get("min_app_instances", 1))
    if option == "lean":
        return ArchitectureParams(
            **common,
            app_subnets_private=False,
            nat_gateways=0,
            instance_type=instance,
            asg_min=min_instances,
            asg_desired=min_instances,
            asg_max=max(asg_max // 2, min_instances + 1),
            db_instance_class=db_class,
            db_multi_az=False,
            deletion_protection=prod,
            waf=bool(f.get("require_waf")),
            log_retention_days=max(30, log_floor),
        )
    if option == "balanced":
        return ArchitectureParams(
            **common,
            app_subnets_private=True,
            nat_gateways=1,
            instance_type=instance,
            asg_min=max(2, min_instances),
            asg_desired=max(2, min_instances),
            asg_max=asg_max,
            db_instance_class=db_class,
            db_multi_az=True,
            deletion_protection=prod,
            waf=bool(f.get("require_waf")),
            log_retention_days=max(90, log_floor),
        )
    return ArchitectureParams(
        **{**common, "backup_retention_days": max(int(f.get("backup_days", 7)), 14)},
        app_subnets_private=True,
        nat_gateways=2,
        instance_type=instance,
        asg_min=2,
        asg_desired=2,
        asg_max=asg_max * 2,
        db_instance_class=DB_UPSIZE[db_class],
        db_multi_az=True,
        deletion_protection=True,
        waf=True,
        log_retention_days=max(365, log_floor),
    )


def _violations(params: ArchitectureParams, spec: RequirementsSpec, cost_total: float) -> list[tuple[str, str]]:
    """Requirements an option cannot satisfy, with a reason."""
    out: list[tuple[str, str]] = []
    for req in spec.requirements:
        if req.status == RequirementStatus.not_applicable:
            continue
        if req.id == "REQ-AVL-002" and not params.db_multi_az:
            out.append((req.id, "single-AZ database cannot survive an availability-zone outage"))
        if req.id == "REQ-NET-002" and not params.app_subnets_private:
            out.append((req.id, "application servers would have public IP addresses"))
        if req.id == "REQ-SEC-009" and not params.waf:
            out.append((req.id, "no web application firewall"))
        if req.id == "REQ-AVL-001" and params.asg_min < int(spec.facts.get("min_app_instances", 1)):
            out.append((req.id, "too few application servers"))
        if req.id == "REQ-CST-001" and spec.facts.get("budget") is not None and cost_total > float(spec.facts["budget"]):
            out.append((req.id, f"estimated ${cost_total:,.0f}/month exceeds the ${float(spec.facts['budget']):,.0f} budget"))
    return out


def _components(o: str, p: ArchitectureParams, spec: RequirementsSpec) -> tuple[list[Component], list[Connection]]:
    req_ids = {r.id for r in spec.requirements}

    def reqs(*ids: str) -> list[str]:
        return [i for i in ids if i in req_ids]

    app_tier = "private_app" if p.app_subnets_private else "public"
    comps: list[Component] = [
        Component(
            id="users",
            kind="users",
            label="Customers",
            tier="edge",
            rationale="Internet users reach the application only through the load balancer.",
        ),
        Component(
            id="account",
            kind="account",
            label="AWS account",
            tier="account",
            details={"Guard": "allowed_account_ids pins the target account"},
            rationale="Terraform refuses to run against any other account.",
            terraform_addresses=["provider.aws"],
            requirements=reqs("REQ-OPS-002"),
        ),
        Component(
            id="region",
            kind="region",
            label=f"Region {p.region}",
            parent="account",
            tier="regional",
            details={"Allowed regions": ", ".join(p.allowed_regions) or "any"},
            rationale="Region selected in the interview.",
            requirements=reqs("REQ-CMP-001"),
        ),
        Component(
            id="vpc",
            kind="vpc",
            label="VPC 10.20.0.0/16",
            parent="region",
            details={"AZs": ", ".join(p.availability_zones)},
            rationale="Private network with separate tiers per availability zone.",
            terraform_addresses=["aws_vpc.main", "aws_default_security_group.default"],
            security_boundary="Network boundary",
        ),
        Component(
            id="public_subnets",
            kind="subnet",
            label="Public subnets (2 AZs)",
            parent="vpc",
            tier="public",
            details={
                "Route": "0.0.0.0/0 → internet gateway",
                "Contains": "load balancer" + ("" if p.app_subnets_private else ", app servers") + (", NAT" if p.nat_gateways else ""),
            },
            rationale="Only components that must face the internet live here.",
            terraform_addresses=["aws_subnet.public", "aws_route_table.public", "aws_internet_gateway.main"],
        ),
    ]
    if p.app_subnets_private:
        comps.append(
            Component(
                id="app_subnets",
                kind="subnet",
                label="Private app subnets (2 AZs)",
                parent="vpc",
                tier="private_app",
                details={"Route": f"0.0.0.0/0 → NAT ({p.nat_gateways})"},
                rationale="Servers are not directly reachable from the internet.",
                terraform_addresses=["aws_subnet.app", "aws_route_table.app"],
                requirements=reqs("REQ-NET-002"),
            )
        )
        comps.append(
            Component(
                id="nat",
                kind="nat",
                label=f"NAT gateway ×{p.nat_gateways}",
                parent="public_subnets",
                tier="public",
                details={"Purpose": "outbound updates and AWS API calls"},
                rationale="One per AZ removes a single point of failure for outbound traffic."
                if p.nat_gateways > 1
                else "A single NAT keeps cost down; if its AZ fails, outbound traffic from servers stops.",
                terraform_addresses=["aws_nat_gateway.main", "aws_eip.nat"],
            )
        )
    if p.db_enabled:
        comps.append(
            Component(
                id="data_subnets",
                kind="subnet",
                label="Isolated data subnets (2 AZs)",
                parent="vpc",
                tier="private_data",
                details={"Route": "none (no internet route)"},
                rationale="The database has no path to or from the internet.",
                terraform_addresses=["aws_subnet.data", "aws_route_table.data"],
                requirements=reqs("REQ-SEC-001"),
                security_boundary="Data boundary",
            )
        )
    if p.waf:
        comps.append(
            Component(
                id="waf",
                kind="waf",
                label="AWS WAF",
                tier="edge",
                details={"Rules": "Common, KnownBadInputs, IP reputation"},
                rationale="Filters common web exploits before they reach the application.",
                terraform_addresses=["aws_wafv2_web_acl.main", "aws_wafv2_web_acl_association.main"],
                requirements=reqs("REQ-SEC-009"),
            )
        )
    comps.append(
        Component(
            id="alb",
            kind="alb",
            label="Application Load Balancer",
            parent="public_subnets",
            tier="public",
            details={
                "Listeners": "443 HTTPS (TLS 1.2+), 80 → 301 redirect" if p.https else "80 HTTP",
                "Invalid headers": "dropped",
                "Access logs": "S3" if p.alb_access_logs else "off",
            },
            rationale="Single public entry point; terminates TLS and spreads load across zones.",
            terraform_addresses=[
                "aws_lb.app",
                "aws_lb_target_group.app",
                "aws_lb_listener.https" if p.https else "aws_lb_listener.http",
                "aws_security_group.alb",
            ],
            requirements=reqs("REQ-SEC-003", "REQ-AUD-002"),
            security_boundary="Ingress: 80/443 from internet only",
        )
    )
    comps.append(
        Component(
            id="app",
            kind="asg",
            label="App servers (auto scaling)",
            parent="app_subnets" if p.app_subnets_private else "public_subnets",
            tier=app_tier,  # type: ignore[arg-type]  # validated by pydantic at runtime
            details={
                "Runtime": f"{RUNTIME_LABELS.get(p.app_runtime, 'application')} on port {p.app_port}",
                "Instance": p.instance_type,
                "Capacity": f"{p.asg_min}–{p.asg_max} (desired {p.asg_desired})",
                "Scale out": f"above {p.scale_out_cpu}% CPU",
                **({"Schedule": "off nights & weekends"} if p.scheduled_scaling else {}),
                "Metadata": "IMDSv2 required",
                "Disk": "encrypted gp3",
                "Public IP": "no" if p.app_subnets_private else "yes (ingress only from ALB)",
            },
            rationale="Replaced automatically when unhealthy; scales on CPU"
            + ("; switched off outside business hours." if p.scheduled_scaling else "."),
            terraform_addresses=[
                "aws_autoscaling_group.app",
                "aws_launch_template.app",
                "aws_autoscaling_policy.cpu_target",
                "aws_security_group.app",
            ]
            + (
                ["aws_autoscaling_schedule.business_hours_start", "aws_autoscaling_schedule.business_hours_stop"]
                if p.scheduled_scaling
                else []
            ),
            requirements=reqs("REQ-NET-001", "REQ-SEC-007", "REQ-AVL-001", "REQ-PRF-001", "REQ-SEC-002", "REQ-CST-002"),
            security_boundary="Ingress: ALB security group only",
        )
    )
    comps.append(
        Component(
            id="iam",
            kind="iam",
            label="Instance role",
            tier="regional",
            details={"Grants": "SSM Session Manager" + (", read own DB secret" if p.db_enabled else "")},
            rationale="Temporary credentials with only the permissions the servers need.",
            terraform_addresses=["aws_iam_role.app", "aws_iam_instance_profile.app", "aws_iam_role_policy_attachment.app_ssm"]
            + (["aws_iam_role_policy.app_read_db_secret"] if p.db_enabled else []),
            requirements=reqs("REQ-SEC-005"),
            security_boundary="IAM boundary",
        )
    )
    comps.append(
        Component(
            id="ssm",
            kind="ssm",
            label="SSM Session Manager" if p.admin_access == "ssm" else f"SSH from {p.admin_cidr}",
            tier="regional",
            details={"Open ports": "none" if p.admin_access == "ssm" else "22 from admin range"},
            rationale="Administrative access without exposing ports to the internet.",
            requirements=reqs("REQ-SEC-004"),
        )
    )
    if p.db_enabled:
        comps.append(
            Component(
                id="db",
                kind="rds",
                label=f"RDS PostgreSQL {p.db_engine_version}",
                parent="data_subnets",
                tier="private_data",
                details={
                    "Class": p.db_instance_class,
                    "Multi-AZ": "yes" if p.db_multi_az else "no",
                    "Encryption": "at rest + TLS enforced",
                    "Backups": f"{p.backup_retention_days} days",
                    "Deletion protection": "on" if p.deletion_protection else "off",
                    "Public": "no",
                },
                rationale="Managed PostgreSQL with automated backups and patching.",
                terraform_addresses=[
                    "aws_db_instance.main",
                    "aws_db_subnet_group.main",
                    "aws_db_parameter_group.main",
                    "aws_security_group.db",
                ],
                requirements=reqs("REQ-SEC-001", "REQ-SEC-002", "REQ-SEC-003", "REQ-AVL-002", "REQ-AVL-003", "REQ-OPS-001"),
                security_boundary="Ingress: app security group, 5432 only",
            )
        )
        comps.append(
            Component(
                id="secrets",
                kind="secrets",
                label="Secrets Manager",
                tier="regional",
                details={"Holds": "RDS-managed master password"},
                rationale="Credentials are generated and rotated by AWS, never stored in Terraform.",
                terraform_addresses=["aws_db_instance.main"],
                requirements=reqs("REQ-SEC-006"),
            )
        )
    if p.uploads_bucket:
        comps.append(
            Component(
                id="uploads",
                kind="s3",
                label="Uploads bucket (S3)",
                tier="regional",
                details={"Public access": "blocked", "Encryption": "SSE-S3", "Versioning": "on", "Access": "app role only, TLS only"},
                rationale="User files live outside the servers so they survive replacement and scaling.",
                terraform_addresses=[
                    "aws_s3_bucket.uploads",
                    "aws_s3_bucket_public_access_block.uploads",
                    "aws_s3_bucket_policy.uploads",
                    "aws_iam_role_policy.app_uploads",
                ],
                requirements=reqs("REQ-SEC-010"),
                security_boundary="Data boundary",
            )
        )
    if p.alerts:
        comps.append(
            Component(
                id="alerts",
                kind="alerts",
                label="Alerts (CloudWatch → email)",
                tier="regional",
                details={
                    "Alarms": "5xx errors, unhealthy servers" + (", DB CPU, DB free storage" if p.db_enabled else ""),
                    "Notify": p.alert_email or "",
                    "Topic": "SNS, KMS-encrypted",
                },
                rationale="Your team hears about problems before customers do.",
                terraform_addresses=[
                    "aws_sns_topic.alerts",
                    "aws_sns_topic_subscription.email",
                    "aws_kms_key.alerts",
                    "aws_cloudwatch_metric_alarm.alb_5xx",
                    "aws_cloudwatch_metric_alarm.unhealthy_hosts",
                ]
                + (["aws_cloudwatch_metric_alarm.db_cpu", "aws_cloudwatch_metric_alarm.db_free_storage"] if p.db_enabled else []),
                requirements=reqs("REQ-OPS-003"),
            )
        )
    comps.append(
        Component(
            id="logs",
            kind="s3",
            label="Log bucket (S3)",
            tier="regional",
            details={"Public access": "blocked", "Encryption": "SSE-S3", "Versioning": "on", "Retention": f"{p.log_retention_days} days"},
            rationale="Private, tamper-resistant store for access, flow and audit logs.",
            terraform_addresses=["aws_s3_bucket.logs", "aws_s3_bucket_public_access_block.logs", "aws_s3_bucket_policy.logs"],
            requirements=reqs("REQ-SEC-008"),
        )
    )
    if p.cloudtrail:
        comps.append(
            Component(
                id="cloudtrail",
                kind="cloudtrail",
                label="CloudTrail",
                tier="account",
                details={"Scope": "all regions", "Integrity": "log file validation"},
                rationale="Records every AWS API call for auditing.",
                terraform_addresses=["aws_cloudtrail.main"],
                requirements=reqs("REQ-AUD-001"),
            )
        )
    if p.flow_logs:
        comps.append(
            Component(
                id="flowlogs",
                kind="flowlogs",
                label="VPC flow logs",
                parent="vpc",
                tier="regional",
                details={"Traffic": "ALL"},
                rationale="Network-level record of accepted and rejected connections.",
                terraform_addresses=["aws_flow_log.vpc"],
                requirements=reqs("REQ-AUD-002"),
            )
        )

    conns = [
        Connection(id="c-users", source="users", target="waf" if p.waf else "alb", label="HTTPS 443" if p.https else "HTTP 80"),
        Connection(id="c-alb-app", source="alb", target="app", label=f"HTTP {p.app_port}"),
        Connection(
            id="c-app-egress",
            source="app",
            target="nat" if p.nat_gateways else "users",
            label="HTTPS out (updates, AWS APIs)",
            kind="egress",
        ),
        Connection(id="c-alb-logs", source="alb", target="logs", label="access logs", kind="logs"),
        Connection(id="c-admin", source="ssm", target="app", label="admin sessions", kind="admin"),
    ]
    if p.waf:
        conns.append(Connection(id="c-waf-alb", source="waf", target="alb", label="filtered requests"))
    if p.db_enabled:
        conns.append(Connection(id="c-app-db", source="app", target="db", label="PostgreSQL 5432 (TLS)", kind="data"))
        conns.append(Connection(id="c-app-secret", source="app", target="secrets", label="read DB secret", kind="data"))
    if p.uploads_bucket:
        conns.append(Connection(id="c-app-uploads", source="app", target="uploads", label="files over TLS (IAM-scoped)", kind="data"))
    if p.alerts:
        conns.append(Connection(id="c-alb-alerts", source="alb", target="alerts", label="metrics → alarms", kind="logs"))
    if p.cloudtrail:
        conns.append(Connection(id="c-trail", source="cloudtrail", target="logs", label="audit logs", kind="logs"))
    if p.flow_logs:
        conns.append(Connection(id="c-flow", source="flowlogs", target="logs", label="flow logs", kind="logs"))
    if not p.alb_access_logs:
        conns = [c for c in conns if c.id != "c-alb-logs"]
    if not p.nat_gateways:
        conns = [c for c in conns if c.id != "c-app-egress"]
    return comps, conns


def _decisions(o: str, p: ArchitectureParams, spec: RequirementsSpec) -> list[Decision]:
    ids = {r.id for r in spec.requirements}
    keep = lambda *r: [i for i in r if i in ids]  # noqa: E731
    d = [
        Decision(
            id="DEC-NET-TIERS",
            title="Network tiers",
            choice="Public / private app / isolated data subnets"
            if p.app_subnets_private
            else "Public subnets for servers (ingress only from the ALB), isolated data subnets",
            rationale="Each tier can only be reached from the tier in front of it."
            if p.app_subnets_private
            else "Avoids ~$33/month per NAT gateway; servers keep public IPs for outbound traffic but accept no direct inbound traffic.",
            alternatives=["Private app subnets with NAT"]
            if not p.app_subnets_private
            else ["Public app subnets (cheaper, weaker isolation)"],
            requirements=keep("REQ-SEC-001", "REQ-NET-001", "REQ-NET-002"),
        ),
        Decision(
            id="DEC-ADMIN-ACCESS",
            title="Administrative access",
            choice="AWS Systems Manager Session Manager" if p.admin_access == "ssm" else f"SSH restricted to {p.admin_cidr}",
            rationale="No inbound administrative ports; sessions are authenticated with IAM and can be logged.",
            alternatives=["Bastion host", "SSH from a fixed range"],
            requirements=keep("REQ-SEC-004"),
        ),
        Decision(
            id="DEC-IAM",
            title="Workload identity",
            choice="EC2 instance role with SSM core policy" + (" and a tag-scoped secret read" if p.db_enabled else ""),
            rationale="Temporary credentials, no access keys on servers.",
            requirements=keep("REQ-SEC-005", "REQ-SEC-007"),
        ),
        Decision(
            id="DEC-ENCRYPTION",
            title="Encryption at rest",
            choice="AWS-managed keys for RDS, EBS and S3",
            rationale="Encryption with no key-management overhead.",
            alternatives=["Customer-managed KMS keys (~$1/key/month, more control)"],
            requirements=keep("REQ-SEC-002"),
        ),
        Decision(
            id="DEC-LOGGING",
            title="Logging",
            choice=", ".join(
                x
                for x in [
                    "CloudTrail" if p.cloudtrail else "",
                    "VPC flow logs" if p.flow_logs else "",
                    "ALB access logs" if p.alb_access_logs else "",
                ]
                if x
            )
            or "Minimal",
            rationale=f"Delivered to one private bucket with {p.log_retention_days}-day retention.",
            requirements=keep("REQ-AUD-001", "REQ-AUD-002", "REQ-AUD-003", "REQ-SEC-008"),
        ),
        Decision(
            id="DEC-COMPUTE",
            title="Compute",
            choice=f"Auto scaling group of {p.instance_type} ({p.asg_min}–{p.asg_max}), scaling out above {p.scale_out_cpu}% CPU",
            rationale="Self-healing and elastic without container-platform complexity"
            + ("; sized up one step because JVM/.NET runtimes reserve more memory." if p.app_runtime in ("java", "dotnet") else "."),
            alternatives=["ECS Fargate (no server management, higher unit cost)"],
            requirements=keep("REQ-AVL-001", "REQ-PRF-001"),
        ),
        Decision(
            id="DEC-COST",
            title="Cost posture",
            choice=OPTION_NAMES[o],
            rationale="See the cost breakdown and trade-offs.",
            requirements=keep("REQ-CST-001"),
        ),
        Decision(
            id="DEC-TAGS",
            title="Tagging",
            choice="Provider default_tags",
            rationale="Every resource is attributable to this project.",
            requirements=keep("REQ-OPS-002"),
        ),
    ]
    if p.https:
        d.append(
            Decision(
                id="DEC-TLS",
                title="TLS",
                choice="TLS 1.2+ at the load balancer, TLS enforced to the database",
                rationale="Encrypts every hop that crosses a network boundary.",
                requirements=keep("REQ-SEC-003"),
            )
        )
    if p.db_enabled:
        d.append(
            Decision(
                id="DEC-DB-PLACEMENT",
                title="Database placement",
                choice="RDS in isolated subnets",
                rationale="No route to or from the internet.",
                requirements=keep("REQ-SEC-001"),
            )
        )
        d.append(
            Decision(
                id="DEC-DB-HA",
                title="Database resilience",
                choice=("Multi-AZ" if p.db_multi_az else "Single-AZ") + f", {p.backup_retention_days}-day backups",
                rationale="Multi-AZ fails over automatically in 1–2 minutes."
                if p.db_multi_az
                else "Single-AZ halves database cost; an AZ outage or maintenance causes downtime until recovery.",
                alternatives=["Single-AZ" if p.db_multi_az else "Multi-AZ (~2× database cost)"],
                requirements=keep("REQ-AVL-002", "REQ-AVL-003", "REQ-OPS-001"),
            )
        )
        d.append(
            Decision(
                id="DEC-SECRETS",
                title="Database credentials",
                choice="RDS-managed master password in Secrets Manager",
                rationale="Credentials never touch Terraform state or the repository.",
                requirements=keep("REQ-SEC-006"),
            )
        )
    if p.uploads_bucket:
        d.append(
            Decision(
                id="DEC-STORAGE",
                title="File storage",
                choice="Private S3 bucket with an IAM policy scoped to the app role",
                rationale="Durable, encrypted object storage that servers can be replaced around; never public.",
                alternatives=["EFS shared file system (more expensive, POSIX semantics)"],
                requirements=keep("REQ-SEC-010"),
            )
        )
    if p.alerts:
        d.append(
            Decision(
                id="DEC-MONITORING",
                title="Alerting",
                choice=f"CloudWatch alarms → KMS-encrypted SNS topic → {p.alert_email}",
                rationale="A customer-managed key is used because CloudWatch cannot publish to topics encrypted with the AWS-managed SNS key.",
                alternatives=["Third-party monitoring (Datadog, PagerDuty) via the same SNS topic"],
                requirements=keep("REQ-OPS-003"),
            )
        )
    if p.scheduled_scaling:
        d.append(
            Decision(
                id="DEC-SCHEDULE",
                title="Off-hours schedule",
                choice=f"Scale to zero 19:00–07:00 and weekends ({p.schedule_timezone})",
                rationale="Non-production servers are idle overnight; the database keeps running so nothing is lost.",
                requirements=keep("REQ-CST-002"),
            )
        )
    if p.waf:
        d.append(
            Decision(
                id="DEC-WAF",
                title="Web application firewall",
                choice="AWS WAF with AWS managed rule groups",
                rationale="Blocks common exploit patterns.",
                requirements=keep("REQ-SEC-009"),
            )
        )
    if p.allowed_regions:
        d.append(
            Decision(
                id="DEC-REGION",
                title="Region",
                choice=p.region,
                rationale=f"Within the allowed set {p.allowed_regions}.",
                requirements=keep("REQ-CMP-001"),
            )
        )
    return d


TRADEOFFS = {
    "lean": {
        "security": TradeoffScore(
            score=3, note="Same encryption, IAM and logging controls; servers have public IPs (inbound blocked except from the ALB)."
        ),
        "availability": TradeoffScore(score=2, note="Single-AZ database: an AZ outage or failover-requiring maintenance causes downtime."),
        "cost": TradeoffScore(score=5, note="No NAT gateways, smallest database."),
        "complexity": TradeoffScore(score=5, note="Fewest moving parts."),
        "operations": TradeoffScore(score=3, note="Fewer resources to manage; recovery from DB failure is manual-ish (restore)."),
    },
    "balanced": {
        "security": TradeoffScore(score=4, note="Servers in private subnets with no public IPs."),
        "availability": TradeoffScore(
            score=4, note="Multi-AZ database and servers in two AZs; single NAT is an egress single point of failure."
        ),
        "cost": TradeoffScore(score=3, note="Multi-AZ doubles database cost; one NAT gateway."),
        "complexity": TradeoffScore(score=4, note="Standard three-tier layout."),
        "operations": TradeoffScore(score=4, note="Automatic database failover."),
    },
    "resilient": {
        "security": TradeoffScore(score=5, note="Adds AWS WAF, deletion protection and year-long log retention."),
        "availability": TradeoffScore(score=5, note="NAT per AZ, Multi-AZ database, larger scaling range."),
        "cost": TradeoffScore(score=2, note="Highest fixed cost (WAF, two NAT gateways, larger database)."),
        "complexity": TradeoffScore(score=3, note="More resources and rules to manage."),
        "operations": TradeoffScore(score=5, note="Survives a full AZ loss without manual action."),
    },
}

SUMMARIES = {
    "lean": "Lowest-cost viable layout: load-balanced servers without NAT gateways and a single-AZ database.",
    "balanced": "Three-tier layout with private application servers, one NAT gateway and a Multi-AZ database.",
    "resilient": "Production-grade resilience: NAT per zone, Multi-AZ database, WAF, deletion protection and long log retention.",
}


def build_architecture(spec: RequirementsSpec) -> ArchitectureSpec:
    f = spec.facts
    budget = f.get("budget")
    options: list[ArchitectureOption] = []
    excluded: list[ExcludedOption] = []
    must_ids = {r.id for r in spec.requirements if r.priority == Priority.must and r.status != RequirementStatus.not_applicable}
    for oid in ("lean", "balanced", "resilient"):
        params = _params(oid, f)
        cost = pricing.estimate(params, f.get("traffic", "low"), budget)
        if oid == "resilient" and f.get("environment") == "development" and f.get("availability") != "high":
            excluded.append(
                ExcludedOption(
                    id=oid,
                    name=OPTION_NAMES[oid],
                    reason="Not appropriate for a development environment: WAF, per-AZ NAT and deletion protection add cost without matching requirements.",
                )
            )
            continue
        violations = _violations(params, spec, cost.total_monthly_usd)
        hard = [(rid, why) for rid, why in violations if rid in must_ids and rid != "REQ-CST-001"]
        if hard:
            excluded.append(
                ExcludedOption(id=oid, name=OPTION_NAMES[oid], reason="Violates " + "; ".join(f"{rid} ({why})" for rid, why in hard))
            )
            continue
        comps, conns = _components(oid, params, spec)
        options.append(
            ArchitectureOption(
                id=oid,
                name=OPTION_NAMES[oid],
                summary=SUMMARIES[oid],
                params=params,
                components=comps,
                connections=conns,
                decisions=_decisions(oid, params, spec),
                cost=cost,
                tradeoffs=TRADEOFFS[oid],
                satisfies=sorted({r.id for r in spec.requirements} - {rid for rid, _ in violations}),
                violates=[rid for rid, _ in violations],
            )
        )
    if not options:
        raise ValueError("No architecture option satisfies the confirmed requirements.")
    within = [o for o in options if o.cost.within_budget is not False]
    pool = within or options
    # Prefer balanced for production when affordable; otherwise the cheapest compliant option.
    # Teams without dedicated operations staff benefit from automatic database failover outside development too.
    prefer_balanced = f.get("environment") == "production" or (f.get("ops_team") == "none" and f.get("environment") != "development")
    recommended = next((o for o in pool if o.id == "balanced" and prefer_balanced), None) or min(
        pool, key=lambda o: o.cost.total_monthly_usd
    )
    return ArchitectureSpec(
        generated_at=datetime.now(UTC),
        requirements_revision=spec.revision,
        recommended=recommended.id,
        selected=None,
        options=options,
        excluded=excluded,
    )


def minimum_viable_cost(spec: RequirementsSpec) -> tuple[float, str] | None:
    """Cheapest option that satisfies all non-cost must requirements."""
    spec_wo_budget = spec.model_copy(update={"facts": {**spec.facts, "budget": None}})
    try:
        arch = build_architecture(spec_wo_budget)
    except ValueError:
        return None
    best = min(arch.options, key=lambda o: o.cost.total_monthly_usd)
    return best.cost.total_monthly_usd, best.name
