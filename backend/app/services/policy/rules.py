"""Deterministic AWS security and requirement policies.

Each policy inspects the normalised plan graph and returns explicit pass/fail
results with evidence. No policy depends on an AI model. Policies return
``not_applicable`` when no relevant resources exist; the traceability layer
decides whether that is acceptable for a given requirement.
"""

from __future__ import annotations

import base64
import binascii
import ipaddress
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.domain.findings import PolicyResult
from app.domain.requirements import Severity
from app.services.policy.graph import PlanGraph, Resource

WORLD_V4 = "0.0.0.0/0"
WORLD_V6 = "::/0"
SENSITIVE_PORTS = {
    22: "SSH",
    3389: "RDP",
    5432: "PostgreSQL",
    3306: "MySQL",
    1433: "SQL Server",
    1521: "Oracle",
    27017: "MongoDB",
    6379: "Redis",
    9200: "Elasticsearch",
    2375: "Docker API",
    2379: "etcd",
    5601: "Kibana",
    8443: "admin HTTPS",
}
STATEFUL_TYPES = {
    "aws_db_instance",
    "aws_rds_cluster",
    "aws_s3_bucket",
    "aws_ebs_volume",
    "aws_dynamodb_table",
    "aws_efs_file_system",
    "aws_elasticache_replication_group",
}
ADMIN_POLICY_ARNS = {
    "arn:aws:iam::aws:policy/AdministratorAccess",
    "arn:aws:iam::aws:policy/PowerUserAccess",
    "arn:aws:iam::aws:policy/IAMFullAccess",
}
MODERN_TLS_PREFIXES = ("ELBSecurityPolicy-TLS13-", "ELBSecurityPolicy-TLS-1-2", "ELBSecurityPolicy-FS-1-2")
SECRET_PATTERNS = [
    (re.compile(r"\b(AKIA|ASIA)[A-Z0-9]{16}\b"), "AWS access key ID"),
    (re.compile(r"-----BEGIN (RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"), "private key"),
    (re.compile(r"(?i)\b(password|passwd|secret|api_?key)\s*[:=]\s*['\"]?[^\s'\"$]{6,}"), "credential assignment"),
]


@dataclass
class PolicyContext:
    enabled: set[str]
    required_backup_days: int = 7
    min_app_instances: int = 1
    allowed_regions: list[str] = field(default_factory=list)
    admin_cidr: str | None = None
    require_private_app: bool = False
    log_retention_days: int = 0


@dataclass
class Policy:
    id: str
    title: str
    severity: Severity
    category: str
    description: str
    remediation: str
    check: Callable[[PlanGraph, PolicyContext, Policy], list[PolicyResult]]
    baseline: bool = False  # always enforced regardless of requirements


def _r(
    p: Policy,
    outcome: str,
    message: str,
    resource: str | None = None,
    attribute: str | None = None,
    expected: Any = None,
    actual: Any = None,
    severity: Severity | None = None,
) -> PolicyResult:
    return PolicyResult(
        policy_id=p.id,
        title=p.title,
        severity=severity or p.severity,
        category=p.category,
        outcome=outcome,  # type: ignore[arg-type]
        resource=resource,
        attribute=attribute,
        message=message,
        expected=expected,
        actual=actual,
        remediation=p.remediation if outcome == "fail" else "",
    )


def _na(p: Policy, why: str) -> list[PolicyResult]:
    return [_r(p, "not_applicable", why)]


def _truthy(v: Any) -> bool:
    return v is True or (isinstance(v, str) and v.lower() == "true")


# ---------------------------------------------------------------------------
# Helpers for network reasoning
# ---------------------------------------------------------------------------


def _public_subnet_bases(g: PlanGraph) -> set[str]:
    """Subnets associated with a route table that routes to an internet gateway."""
    igw_route_tables: set[str] = set()
    for rt in g.of_type("aws_route_table"):
        routes_ref_igw = any(ref.startswith("aws_internet_gateway.") for ref in rt.refs_for("route"))
        if routes_ref_igw:
            igw_route_tables.add(rt.base)
    for route in g.of_type("aws_route"):
        if any(ref.startswith("aws_internet_gateway.") for ref in route.refs_for("gateway_id")):
            igw_route_tables |= {ref for ref in route.refs_for("route_table_id") if ref.startswith("aws_route_table.")}
    public: set[str] = set()
    for assoc in g.of_type("aws_route_table_association"):
        if assoc.refs_for("route_table_id") & igw_route_tables:
            public |= {ref for ref in assoc.refs_for("subnet_id") if ref.startswith("aws_subnet.")}
    for sn in g.of_type("aws_subnet"):
        if _truthy(sn.values.get("map_public_ip_on_launch")):
            public.add(sn.base)
    return public


@dataclass
class IngressRule:
    owner_sg: str | None  # base address of the security group
    address: str
    from_port: int
    to_port: int
    protocol: str
    cidrs: list[str]
    source_sgs: set[str]


def _ingress_rules(g: PlanGraph) -> list[IngressRule]:
    rules: list[IngressRule] = []
    for sg in g.of_type("aws_security_group"):
        for i, ing in enumerate(sg.values.get("ingress") or []):
            rules.append(
                IngressRule(
                    owner_sg=sg.base,
                    address=f"{sg.address}.ingress[{i}]",
                    from_port=int(ing.get("from_port") or 0),
                    to_port=int(ing.get("to_port") or 0),
                    protocol=str(ing.get("protocol")),
                    cidrs=list(ing.get("cidr_blocks") or []) + list(ing.get("ipv6_cidr_blocks") or []),
                    source_sgs=sg.refs_for("ingress.security_groups"),
                )
            )
    for rule in g.of_type("aws_vpc_security_group_ingress_rule"):
        owner = next(iter(r for r in rule.refs_for("security_group_id") if r.startswith("aws_security_group.")), None)
        cidrs = [c for c in (rule.values.get("cidr_ipv4"), rule.values.get("cidr_ipv6")) if c]
        proto = str(rule.values.get("ip_protocol"))
        rules.append(
            IngressRule(
                owner_sg=owner,
                address=rule.address,
                from_port=int(rule.values.get("from_port") or 0) if proto != "-1" else 0,
                to_port=int(rule.values.get("to_port") or 0) if proto != "-1" else 65535,
                protocol=proto,
                cidrs=cidrs,
                source_sgs={r for r in rule.refs_for("referenced_security_group_id") if r.startswith("aws_security_group.")},
            )
        )
    for rule in g.of_type("aws_security_group_rule"):
        if rule.values.get("type") != "ingress":
            continue
        owner = next(iter(r for r in rule.refs_for("security_group_id") if r.startswith("aws_security_group.")), None)
        proto = str(rule.values.get("protocol"))
        rules.append(
            IngressRule(
                owner_sg=owner,
                address=rule.address,
                from_port=int(rule.values.get("from_port") or 0),
                to_port=int(rule.values.get("to_port") or 0) if proto not in {"-1", "all"} else 65535,
                protocol=proto,
                cidrs=list(rule.values.get("cidr_blocks") or []) + list(rule.values.get("ipv6_cidr_blocks") or []),
                source_sgs={r for r in rule.refs_for("source_security_group_id") if r.startswith("aws_security_group.")},
            )
        )
    return rules


def _is_world(cidr: str) -> bool:
    if cidr in (WORLD_V4, WORLD_V6):
        return True
    try:
        net = ipaddress.ip_network(cidr, strict=False)
    except ValueError:
        return False
    return net.prefixlen <= (8 if net.version == 4 else 16)


def _covers(rule: IngressRule, port: int) -> bool:
    if rule.protocol in {"-1", "all"}:
        return True
    return rule.from_port <= port <= rule.to_port


def _internet_facing_lb_sgs(g: PlanGraph) -> set[str]:
    out: set[str] = set()
    for lb in g.of_type("aws_lb", "aws_alb", "aws_elb"):
        if not _truthy(lb.values.get("internal")):
            out |= {r for r in lb.refs_for("security_groups") if r.startswith("aws_security_group.")}
    return out


def _db_sgs(g: PlanGraph) -> set[str]:
    out: set[str] = set()
    for db in g.of_type("aws_db_instance", "aws_rds_cluster"):
        out |= {r for r in db.refs_for("vpc_security_group_ids") if r.startswith("aws_security_group.")}
    return out


def _app_sgs(g: PlanGraph) -> set[str]:
    out: set[str] = set()
    for lt in g.of_type("aws_launch_template"):
        out |= {
            r for r in lt.refs_for("vpc_security_group_ids", "network_interfaces.security_groups") if r.startswith("aws_security_group.")
        }
    for inst in g.of_type("aws_instance"):
        out |= {r for r in inst.refs_for("vpc_security_group_ids") if r.startswith("aws_security_group.")}
    return out


def _parse_policy(doc: Any) -> dict[str, Any] | None:
    if isinstance(doc, dict):
        return doc
    if isinstance(doc, str) and doc.strip():
        try:
            return json.loads(doc)
        except json.JSONDecodeError:
            return None
    return None


def _as_list(v: Any) -> list[Any]:
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


# ---------------------------------------------------------------------------
# Policy checks
# ---------------------------------------------------------------------------


def chk_rds_public(g: PlanGraph, ctx: PolicyContext, p: Policy) -> list[PolicyResult]:
    dbs = g.of_type("aws_db_instance")
    if not dbs:
        return _na(p, "No RDS database instances in the plan.")
    out = []
    for db in dbs:
        val = db.values.get("publicly_accessible")
        if _truthy(val):
            out.append(
                _r(
                    p,
                    "fail",
                    "Database is configured to receive a public IP address and be reachable from the internet.",
                    db.address,
                    "publicly_accessible",
                    False,
                    val,
                )
            )
        else:
            out.append(_r(p, "pass", "Database is not publicly accessible.", db.address, "publicly_accessible", False, val))
    return out


def chk_rds_encrypted(g: PlanGraph, ctx: PolicyContext, p: Policy) -> list[PolicyResult]:
    dbs = g.of_type("aws_db_instance", "aws_rds_cluster")
    if not dbs:
        return _na(p, "No RDS databases in the plan.")
    return [
        _r(
            p,
            "pass" if _truthy(db.values.get("storage_encrypted")) else "fail",
            "Storage encryption is enabled."
            if _truthy(db.values.get("storage_encrypted"))
            else "Database storage is not encrypted at rest.",
            db.address,
            "storage_encrypted",
            True,
            db.values.get("storage_encrypted"),
        )
        for db in dbs
    ]


def chk_rds_backups(g: PlanGraph, ctx: PolicyContext, p: Policy) -> list[PolicyResult]:
    dbs = g.of_type("aws_db_instance")
    if not dbs:
        return _na(p, "No RDS database instances in the plan.")
    out = []
    for db in dbs:
        days = int(db.values.get("backup_retention_period") or 0)
        ok = days >= ctx.required_backup_days
        out.append(
            _r(
                p,
                "pass" if ok else "fail",
                f"Automated backups retained for {days} day(s); requirement is at least {ctx.required_backup_days}.",
                db.address,
                "backup_retention_period",
                f">= {ctx.required_backup_days}",
                days,
            )
        )
    return out


def chk_rds_deletion(g: PlanGraph, ctx: PolicyContext, p: Policy) -> list[PolicyResult]:
    dbs = g.of_type("aws_db_instance")
    if not dbs:
        return _na(p, "No RDS database instances in the plan.")
    out = []
    for db in dbs:
        prot = _truthy(db.values.get("deletion_protection"))
        skip = _truthy(db.values.get("skip_final_snapshot"))
        if prot and not skip:
            out.append(
                _r(
                    p,
                    "pass",
                    "Deletion protection is on and a final snapshot is taken on deletion.",
                    db.address,
                    "deletion_protection",
                    True,
                    True,
                )
            )
        else:
            problems = []
            if not prot:
                problems.append("deletion protection is off")
            if skip:
                problems.append("final snapshot is skipped")
            out.append(
                _r(
                    p,
                    "fail",
                    f"Production database could be deleted without a safety net: {', '.join(problems)}.",
                    db.address,
                    "deletion_protection/skip_final_snapshot",
                    {"deletion_protection": True, "skip_final_snapshot": False},
                    {"deletion_protection": prot, "skip_final_snapshot": skip},
                )
            )
    return out


def chk_rds_secret(g: PlanGraph, ctx: PolicyContext, p: Policy) -> list[PolicyResult]:
    dbs = g.of_type("aws_db_instance", "aws_rds_cluster")
    if not dbs:
        return _na(p, "No RDS databases in the plan.")
    out = []
    for db in dbs:
        has_password = db.values.get("password") not in (None, "") or db.values.get("master_password") not in (None, "")
        managed = _truthy(db.values.get("manage_master_user_password"))
        if has_password:
            out.append(
                _r(
                    p,
                    "fail",
                    "A master password is set directly in Terraform configuration; it will be stored in state and plan files (value redacted).",
                    db.address,
                    "password",
                    "unset (use manage_master_user_password)",
                    "<redacted>",
                )
            )
        elif not managed:
            out.append(
                _r(
                    p,
                    "fail",
                    "Master credentials are not managed by AWS Secrets Manager.",
                    db.address,
                    "manage_master_user_password",
                    True,
                    False,
                )
            )
        else:
            out.append(
                _r(
                    p,
                    "pass",
                    "Master password is generated and rotated by RDS in AWS Secrets Manager.",
                    db.address,
                    "manage_master_user_password",
                    True,
                    True,
                )
            )
    return out


def chk_rds_tls(g: PlanGraph, ctx: PolicyContext, p: Policy) -> list[PolicyResult]:
    dbs = g.of_type("aws_db_instance")
    if not dbs:
        return _na(p, "No RDS database instances in the plan.")
    forcing_groups = set()
    for pg in g.of_type("aws_db_parameter_group"):
        for param in pg.values.get("parameter") or []:
            if param.get("name") == "rds.force_ssl" and str(param.get("value")) == "1":
                forcing_groups.add(pg.base)
    out = []
    for db in dbs:
        groups = db.refs_for("parameter_group_name")
        ok = bool(groups & forcing_groups)
        out.append(
            _r(
                p,
                "pass" if ok else "fail",
                "Database parameter group enforces TLS connections (rds.force_ssl = 1)."
                if ok
                else "Database does not enforce TLS for client connections.",
                db.address,
                "parameter_group_name",
                "parameter group with rds.force_ssl = 1",
                sorted(groups) or None,
            )
        )
    return out


def chk_db_private_subnets(g: PlanGraph, ctx: PolicyContext, p: Policy) -> list[PolicyResult]:
    groups = g.of_type("aws_db_subnet_group")
    if not g.of_type("aws_db_instance", "aws_rds_cluster"):
        return _na(p, "No RDS databases in the plan.")
    if not groups:
        return [
            _r(p, "fail", "Database has no DB subnet group, so its network placement cannot be verified.", None, "db_subnet_group_name")
        ]
    public = _public_subnet_bases(g)
    out = []
    for grp in groups:
        subnets = {r for r in grp.refs_for("subnet_ids") if r.startswith("aws_subnet.")}
        exposed = sorted(subnets & public)
        if not subnets:
            out.append(
                _r(
                    p,
                    "fail",
                    "DB subnet group subnets could not be resolved to subnets defined in this configuration.",
                    grp.address,
                    "subnet_ids",
                )
            )
        elif exposed:
            out.append(
                _r(
                    p,
                    "fail",
                    f"Database subnets {', '.join(exposed)} route to an internet gateway.",
                    grp.address,
                    "subnet_ids",
                    "private subnets only",
                    exposed,
                )
            )
        else:
            out.append(
                _r(
                    p,
                    "pass",
                    f"Database subnets {', '.join(sorted(subnets))} have no route to an internet gateway.",
                    grp.address,
                    "subnet_ids",
                    "private subnets only",
                    sorted(subnets),
                )
            )
    return out


def chk_sg_world_ingress(g: PlanGraph, ctx: PolicyContext, p: Policy) -> list[PolicyResult]:
    rules = _ingress_rules(g)
    if not rules:
        return _na(p, "No security group ingress rules in the plan.")
    lb_sgs = _internet_facing_lb_sgs(g)
    out = []
    for rule in rules:
        world = [c for c in rule.cidrs if _is_world(c)]
        if not world:
            continue
        exposed_sensitive = [f"{port} ({name})" for port, name in SENSITIVE_PORTS.items() if _covers(rule, port)]
        all_ports = rule.protocol in {"-1", "all"} or (rule.from_port == 0 and rule.to_port >= 65535)
        web_only = rule.from_port in (80, 443) and rule.to_port == rule.from_port
        if exposed_sensitive or all_ports:
            what = "all ports" if all_ports else ", ".join(exposed_sensitive)
            out.append(
                _r(
                    p,
                    "fail",
                    f"Ingress from the internet ({', '.join(world)}) allowed to {what}.",
                    rule.address,
                    "cidr",
                    "no internet ingress to administrative or database ports",
                    world,
                    Severity.critical,
                )
            )
        elif web_only and rule.owner_sg in lb_sgs:
            out.append(
                _r(
                    p,
                    "pass",
                    f"Internet ingress on port {rule.from_port} is limited to the internet-facing load balancer.",
                    rule.address,
                    "cidr",
                    None,
                    world,
                )
            )
        else:
            out.append(
                _r(
                    p,
                    "fail",
                    f"Ingress from the internet allowed to ports {rule.from_port}-{rule.to_port} on a non-load-balancer security group.",
                    rule.address,
                    "cidr",
                    "internet ingress only on 80/443 to a load balancer",
                    world,
                    Severity.high,
                )
            )
    if not out:
        out.append(_r(p, "pass", "No security group allows ingress from the whole internet."))
    return out


def chk_db_sg_sources(g: PlanGraph, ctx: PolicyContext, p: Policy) -> list[PolicyResult]:
    db_sgs = _db_sgs(g)
    if not db_sgs:
        return _na(p, "No database security groups in the plan.")
    app_sgs = _app_sgs(g)
    out = []
    for rule in _ingress_rules(g):
        if rule.owner_sg not in db_sgs:
            continue
        if rule.cidrs:
            out.append(
                _r(
                    p,
                    "fail",
                    f"Database security group accepts traffic from IP ranges {rule.cidrs} instead of only the application tier.",
                    rule.address,
                    "cidr",
                    "source = application security group",
                    rule.cidrs,
                )
            )
        elif rule.source_sgs and not rule.source_sgs <= app_sgs:
            out.append(
                _r(
                    p,
                    "fail",
                    f"Database security group accepts traffic from {sorted(rule.source_sgs - app_sgs)}, which is not the application tier.",
                    rule.address,
                    "referenced_security_group_id",
                    sorted(app_sgs),
                    sorted(rule.source_sgs),
                )
            )
        else:
            out.append(
                _r(
                    p,
                    "pass",
                    f"Database accepts connections only from the application security group {sorted(rule.source_sgs)}.",
                    rule.address,
                    "referenced_security_group_id",
                    sorted(app_sgs),
                    sorted(rule.source_sgs),
                )
            )
    if not out:
        out.append(_r(p, "pass", "Database security groups have no ingress rules."))
    return out


def chk_app_sg_sources(g: PlanGraph, ctx: PolicyContext, p: Policy) -> list[PolicyResult]:
    app_sgs = _app_sgs(g)
    if not app_sgs:
        return _na(p, "No application server security groups in the plan.")
    lb_sgs = _internet_facing_lb_sgs(g) | {r for lb in g.of_type("aws_lb") for r in lb.refs_for("security_groups")}
    out = []
    for rule in _ingress_rules(g):
        if rule.owner_sg not in app_sgs:
            continue
        if rule.source_sgs and rule.source_sgs <= lb_sgs and not rule.cidrs:
            out.append(
                _r(
                    p,
                    "pass",
                    "Application servers accept traffic only from the load balancer.",
                    rule.address,
                    "referenced_security_group_id",
                    sorted(lb_sgs),
                    sorted(rule.source_sgs),
                )
            )
        elif (
            rule.cidrs
            and ctx.admin_cidr
            and set(rule.cidrs) == {ctx.admin_cidr}
            and _covers(rule, 22)
            and rule.from_port == rule.to_port == 22
        ):
            out.append(
                _r(
                    p,
                    "pass",
                    f"SSH allowed only from the approved administrator range {ctx.admin_cidr}.",
                    rule.address,
                    "cidr",
                    ctx.admin_cidr,
                    rule.cidrs,
                )
            )
        else:
            out.append(
                _r(
                    p,
                    "fail",
                    "Application servers accept traffic from a source other than the load balancer.",
                    rule.address,
                    "source",
                    "load balancer security group only",
                    rule.cidrs or sorted(rule.source_sgs),
                )
            )
    if not out:
        out.append(_r(p, "fail", "Application servers have no ingress from the load balancer; the application would be unreachable.", None))
    return out


def chk_default_sg(g: PlanGraph, ctx: PolicyContext, p: Policy) -> list[PolicyResult]:
    if not g.of_type("aws_vpc"):
        return _na(p, "No VPCs in the plan.")
    dsgs = g.of_type("aws_default_security_group")
    if not dsgs:
        return [
            _r(
                p,
                "fail",
                "The VPC's default security group is not managed; AWS's default allows all traffic between its members.",
                None,
                "aws_default_security_group",
            )
        ]
    out = []
    for d in dsgs:
        empty = not (d.values.get("ingress") or []) and not (d.values.get("egress") or [])
        out.append(
            _r(
                p,
                "pass" if empty else "fail",
                "Default security group denies all traffic." if empty else "Default security group has rules.",
                d.address,
                "ingress/egress",
                [],
                None,
            )
        )
    return out


def chk_iam_wildcards(g: PlanGraph, ctx: PolicyContext, p: Policy) -> list[PolicyResult]:
    docs: list[tuple[Resource, Any]] = []
    for res in g.of_type("aws_iam_policy", "aws_iam_role_policy", "aws_iam_user_policy", "aws_iam_group_policy"):
        docs.append((res, res.values.get("policy")))
    for role in g.of_type("aws_iam_role"):
        for inline in role.values.get("inline_policy") or []:
            docs.append((role, inline.get("policy")))
    if not docs:
        return _na(p, "No IAM permission policies in the plan.")
    out = []
    for res, raw in docs:
        doc = _parse_policy(raw)
        if doc is None:
            out.append(
                _r(
                    p,
                    "fail",
                    "Policy document is unknown at plan time or not valid JSON, so least privilege cannot be verified.",
                    res.address,
                    "policy",
                    "statically known policy document",
                    "unknown",
                    Severity.medium,
                )
            )
            continue
        problems = []
        for st in _as_list(doc.get("Statement")):
            if st.get("Effect") != "Allow":
                continue
            actions = [a for a in _as_list(st.get("Action")) if isinstance(a, str)]
            resources = [r for r in _as_list(st.get("Resource")) if isinstance(r, str)]
            if "NotAction" in st:
                problems.append(("Allow statement uses NotAction, which grants everything not listed", Severity.high))
            if "*" in actions and "*" in resources:
                problems.append(('grants every action on every resource (Action "*", Resource "*")', Severity.critical))
            elif "*" in actions:
                problems.append(('grants every action (Action "*")', Severity.critical))
            else:
                svc_wild = [a for a in actions if a.endswith(":*")]
                if svc_wild and "*" in resources:
                    problems.append((f"grants all actions of {', '.join(svc_wild)} on all resources", Severity.high))
                iam_priv = [
                    a for a in actions if a.lower().startswith(("iam:pass", "iam:create", "iam:attach", "iam:put", "sts:assumerole"))
                ]
                if iam_priv and "*" in resources:
                    problems.append((f"grants privilege-escalation-capable actions {', '.join(iam_priv)} on all resources", Severity.high))
        if problems:
            worst = max(problems, key=lambda x: {Severity.critical: 3, Severity.high: 2}.get(x[1], 1))
            out.append(
                _r(
                    p,
                    "fail",
                    "IAM policy " + "; ".join(msg for msg, _ in problems) + ".",
                    res.address,
                    "policy",
                    "specific actions on specific resources",
                    doc.get("Statement"),
                    worst[1],
                )
            )
        else:
            out.append(_r(p, "pass", "Policy grants specific actions only.", res.address, "policy"))
    return out


def chk_iam_admin(g: PlanGraph, ctx: PolicyContext, p: Policy) -> list[PolicyResult]:
    atts = g.of_type(
        "aws_iam_role_policy_attachment", "aws_iam_user_policy_attachment", "aws_iam_group_policy_attachment", "aws_iam_policy_attachment"
    )
    roles = g.of_type("aws_iam_role")
    if not atts and not roles:
        return _na(p, "No IAM roles or policy attachments in the plan.")
    out = []
    for a in atts:
        arn = a.values.get("policy_arn")
        bad = arn in ADMIN_POLICY_ARNS
        out.append(_r(p, "fail" if bad else "pass", f"Attaches {arn}.", a.address, "policy_arn", "not an administrator policy", arn))
    for role in roles:
        for arn in role.values.get("managed_policy_arns") or []:
            if arn in ADMIN_POLICY_ARNS:
                out.append(
                    _r(
                        p,
                        "fail",
                        f"Role has administrator policy {arn}.",
                        role.address,
                        "managed_policy_arns",
                        "not an administrator policy",
                        arn,
                    )
                )
    if not out:
        out.append(_r(p, "pass", "No administrator policies attached."))
    return out


def chk_iam_users(g: PlanGraph, ctx: PolicyContext, p: Policy) -> list[PolicyResult]:
    bad = g.of_type("aws_iam_user", "aws_iam_access_key", "aws_iam_user_login_profile")
    if not bad:
        return [_r(p, "pass", "No IAM users or long-lived access keys are created.")]
    return [
        _r(
            p,
            "fail",
            "Creates an IAM user or long-lived access key; workloads should use roles with temporary credentials.",
            r.address,
            r.type,
        )
        for r in bad
    ]


def chk_imdsv2(g: PlanGraph, ctx: PolicyContext, p: Policy) -> list[PolicyResult]:
    targets = g.of_type("aws_launch_template", "aws_instance")
    if not targets:
        return _na(p, "No EC2 instances or launch templates in the plan.")
    out = []
    for t in targets:
        tokens = t.get("metadata_options.http_tokens")
        ok = tokens == "required"
        out.append(
            _r(
                p,
                "pass" if ok else "fail",
                "Instance metadata requires session tokens (IMDSv2)."
                if ok
                else "IMDSv1 is allowed; SSRF bugs could expose instance credentials.",
                t.address,
                "metadata_options.http_tokens",
                "required",
                tokens,
            )
        )
    return out


def chk_app_private(g: PlanGraph, ctx: PolicyContext, p: Policy) -> list[PolicyResult]:
    asgs = g.of_type("aws_autoscaling_group")
    lts = g.of_type("aws_launch_template")
    if not asgs and not lts:
        return _na(p, "No application servers in the plan.")
    public = _public_subnet_bases(g)
    out = []
    for lt in lts:
        nics = lt.values.get("network_interfaces") or []
        assoc = any(_truthy(n.get("associate_public_ip_address")) for n in nics)
        out.append(
            _r(
                p,
                "fail" if assoc else "pass",
                "Launch template assigns public IP addresses." if assoc else "Launch template does not assign public IPs.",
                lt.address,
                "network_interfaces.associate_public_ip_address",
                False,
                assoc,
            )
        )
    for asg in asgs:
        subnets = {r for r in asg.refs_for("vpc_zone_identifier") if r.startswith("aws_subnet.")}
        exposed = sorted(subnets & public)
        out.append(
            _r(
                p,
                "fail" if exposed else "pass",
                f"Application servers launch into public subnets {exposed}."
                if exposed
                else "Application servers launch into private subnets.",
                asg.address,
                "vpc_zone_identifier",
                "private subnets",
                sorted(subnets),
            )
        )
    return out


def chk_ebs_encryption(g: PlanGraph, ctx: PolicyContext, p: Policy) -> list[PolicyResult]:
    lts = g.of_type("aws_launch_template")
    vols = g.of_type("aws_ebs_volume")
    insts = g.of_type("aws_instance")
    if not (lts or vols or insts):
        return _na(p, "No EC2 storage in the plan.")
    out = []
    for lt in lts:
        bdms = lt.values.get("block_device_mappings") or []
        if not bdms:
            out.append(
                _r(
                    p,
                    "fail",
                    "Launch template does not define encrypted root volumes.",
                    lt.address,
                    "block_device_mappings.ebs.encrypted",
                    True,
                    None,
                )
            )
        for b in bdms:
            enc = _truthy(((b.get("ebs") or [{}])[0] or {}).get("encrypted"))
            out.append(
                _r(
                    p,
                    "pass" if enc else "fail",
                    f"Volume {b.get('device_name')} encrypted." if enc else f"Volume {b.get('device_name')} is not encrypted.",
                    lt.address,
                    "block_device_mappings.ebs.encrypted",
                    True,
                    enc,
                )
            )
    for v in vols:
        enc = _truthy(v.values.get("encrypted"))
        out.append(
            _r(
                p,
                "pass" if enc else "fail",
                "EBS volume encrypted." if enc else "EBS volume not encrypted.",
                v.address,
                "encrypted",
                True,
                enc,
            )
        )
    for inst in insts:
        enc = _truthy(inst.get("root_block_device.encrypted"))
        out.append(
            _r(
                p,
                "pass" if enc else "fail",
                "Root volume encrypted." if enc else "Root volume not encrypted.",
                inst.address,
                "root_block_device.encrypted",
                True,
                enc,
            )
        )
    return out


def chk_s3_public(g: PlanGraph, ctx: PolicyContext, p: Policy) -> list[PolicyResult]:
    buckets = g.of_type("aws_s3_bucket")
    if not buckets:
        return _na(p, "No S3 buckets in the plan.")
    out = []
    for b in buckets:
        blocks = g.referencing(b.base, "aws_s3_bucket_public_access_block")
        flags = ("block_public_acls", "block_public_policy", "ignore_public_acls", "restrict_public_buckets")
        if not blocks:
            out.append(
                _r(
                    p,
                    "fail",
                    "Bucket has no public access block.",
                    b.address,
                    "aws_s3_bucket_public_access_block",
                    {f: True for f in flags},
                    None,
                )
            )
        for blk in blocks:
            vals = {f: _truthy(blk.values.get(f)) for f in flags}
            ok = all(vals.values())
            out.append(
                _r(
                    p,
                    "pass" if ok else "fail",
                    "All four public access block settings are enabled." if ok else "Public access block is incomplete.",
                    blk.address,
                    "public_access_block",
                    {f: True for f in flags},
                    vals,
                )
            )
        for acl in g.referencing(b.base, "aws_s3_bucket_acl"):
            if acl.values.get("acl") in {"public-read", "public-read-write", "authenticated-read"}:
                out.append(
                    _r(
                        p,
                        "fail",
                        f"Bucket ACL grants {acl.values.get('acl')}.",
                        acl.address,
                        "acl",
                        "private",
                        acl.values.get("acl"),
                        Severity.critical,
                    )
                )
        for pol in g.referencing(b.base, "aws_s3_bucket_policy"):
            doc = _parse_policy(pol.values.get("policy"))
            for st in _as_list((doc or {}).get("Statement")):
                principal = st.get("Principal")
                if st.get("Effect") == "Allow" and (principal == "*" or principal == {"AWS": "*"}) and not st.get("Condition"):
                    out.append(
                        _r(
                            p,
                            "fail",
                            "Bucket policy allows any principal without conditions.",
                            pol.address,
                            "policy",
                            "no anonymous access",
                            st,
                            Severity.critical,
                        )
                    )
    return out


def chk_s3_encryption(g: PlanGraph, ctx: PolicyContext, p: Policy) -> list[PolicyResult]:
    buckets = g.of_type("aws_s3_bucket")
    if not buckets:
        return _na(p, "No S3 buckets in the plan.")
    out = []
    for b in buckets:
        cfgs = g.referencing(b.base, "aws_s3_bucket_server_side_encryption_configuration")
        algos = [r.get("rule.apply_server_side_encryption_by_default.sse_algorithm") for r in cfgs]
        ok = any(a in ("AES256", "aws:kms", "aws:kms:dsse") for a in algos)
        out.append(
            _r(
                p,
                "pass" if ok else "fail",
                f"Default encryption {algos[0]} configured explicitly." if ok else "No explicit default encryption configuration.",
                b.address,
                "server_side_encryption_configuration",
                "AES256 or aws:kms",
                algos or None,
            )
        )
    return out


def chk_s3_versioning(g: PlanGraph, ctx: PolicyContext, p: Policy) -> list[PolicyResult]:
    buckets = g.of_type("aws_s3_bucket")
    if not buckets:
        return _na(p, "No S3 buckets in the plan.")
    out = []
    for b in buckets:
        vers = g.referencing(b.base, "aws_s3_bucket_versioning")
        status = [v.get("versioning_configuration.status") for v in vers]
        ok = "Enabled" in status
        out.append(
            _r(
                p,
                "pass" if ok else "fail",
                "Versioning enabled, protecting log objects from overwrite." if ok else "Versioning is not enabled.",
                b.address,
                "versioning",
                "Enabled",
                status or None,
            )
        )
    return out


def chk_alb_https(g: PlanGraph, ctx: PolicyContext, p: Policy) -> list[PolicyResult]:
    lbs = [lb for lb in g.of_type("aws_lb", "aws_alb") if not _truthy(lb.values.get("internal"))]
    if not lbs:
        return _na(p, "No internet-facing load balancers in the plan.")
    out = []
    for lb in lbs:
        listeners = g.referencing(lb.base, "aws_lb_listener", "aws_alb_listener")
        https = [lis for lis in listeners if lis.values.get("protocol") == "HTTPS"]
        if not https:
            out.append(
                _r(
                    p,
                    "fail",
                    "Internet-facing load balancer has no HTTPS listener.",
                    lb.address,
                    "listener.protocol",
                    "HTTPS",
                    [lis.values.get("protocol") for lis in listeners],
                )
            )
        for lis in https:
            pol = lis.values.get("ssl_policy") or ""
            ok = pol.startswith(MODERN_TLS_PREFIXES)
            out.append(
                _r(
                    p,
                    "pass" if ok else "fail",
                    f"HTTPS listener uses {pol}." if ok else f"HTTPS listener allows legacy TLS ({pol or 'default policy'}).",
                    lis.address,
                    "ssl_policy",
                    "TLS 1.2+ policy",
                    pol,
                )
            )
    return out


def chk_alb_redirect(g: PlanGraph, ctx: PolicyContext, p: Policy) -> list[PolicyResult]:
    listeners = [lis for lis in g.of_type("aws_lb_listener", "aws_alb_listener") if lis.values.get("protocol") == "HTTP"]
    if not listeners:
        return (
            [_r(p, "pass", "No plaintext HTTP listeners.")] if g.of_type("aws_lb", "aws_alb") else _na(p, "No load balancers in the plan.")
        )
    out = []
    for lis in listeners:
        action = (lis.values.get("default_action") or [{}])[0]
        redirect = (action.get("redirect") or [{}])[0] if action.get("type") == "redirect" else {}
        ok = action.get("type") == "redirect" and redirect.get("protocol") == "HTTPS"
        out.append(
            _r(
                p,
                "pass" if ok else "fail",
                "HTTP requests are redirected to HTTPS." if ok else "HTTP listener serves traffic without TLS.",
                lis.address,
                "default_action",
                "redirect to HTTPS",
                action.get("type"),
            )
        )
    return out


def chk_alb_headers(g: PlanGraph, ctx: PolicyContext, p: Policy) -> list[PolicyResult]:
    lbs = [lb for lb in g.of_type("aws_lb", "aws_alb") if (lb.values.get("load_balancer_type") or "application") == "application"]
    if not lbs:
        return _na(p, "No application load balancers in the plan.")
    return [
        _r(
            p,
            "pass" if _truthy(lb.values.get("drop_invalid_header_fields")) else "fail",
            "Invalid HTTP headers are dropped."
            if _truthy(lb.values.get("drop_invalid_header_fields"))
            else "Invalid HTTP headers are forwarded (request smuggling risk).",
            lb.address,
            "drop_invalid_header_fields",
            True,
            lb.values.get("drop_invalid_header_fields"),
        )
        for lb in lbs
    ]


def chk_cloudtrail(g: PlanGraph, ctx: PolicyContext, p: Policy) -> list[PolicyResult]:
    trails = g.of_type("aws_cloudtrail")
    if not trails:
        return [
            _r(p, "fail", "No CloudTrail trail is defined, so API activity is not recorded to durable storage.", None, "aws_cloudtrail")
        ]
    out = []
    for t in trails:
        problems = []
        if not _truthy(t.values.get("is_multi_region_trail")):
            problems.append("not multi-region")
        if not _truthy(t.values.get("enable_log_file_validation")):
            problems.append("log file validation disabled")
        if t.values.get("enable_logging") is False:
            problems.append("logging disabled")
        out.append(
            _r(
                p,
                "fail" if problems else "pass",
                "Trail: " + ", ".join(problems) if problems else "Multi-region trail with tamper-evident log validation.",
                t.address,
                "is_multi_region_trail/enable_log_file_validation",
                True,
                problems or True,
            )
        )
    return out


def chk_flow_logs(g: PlanGraph, ctx: PolicyContext, p: Policy) -> list[PolicyResult]:
    vpcs = g.of_type("aws_vpc")
    if not vpcs:
        return _na(p, "No VPCs in the plan.")
    out = []
    for vpc in vpcs:
        logs = g.referencing(vpc.base, "aws_flow_log")
        ok = any(fl.values.get("traffic_type") == "ALL" for fl in logs)
        out.append(
            _r(
                p,
                "pass" if ok else "fail",
                "VPC flow logs capture all traffic." if ok else "VPC has no flow log capturing all traffic.",
                vpc.address,
                "aws_flow_log",
                "traffic_type ALL",
                [fl.values.get("traffic_type") for fl in logs] or None,
            )
        )
    return out


def chk_alb_logs(g: PlanGraph, ctx: PolicyContext, p: Policy) -> list[PolicyResult]:
    lbs = g.of_type("aws_lb", "aws_alb")
    if not lbs:
        return _na(p, "No load balancers in the plan.")
    return [
        _r(
            p,
            "pass" if _truthy(lb.get("access_logs.enabled")) else "fail",
            "Access logs delivered to S3." if _truthy(lb.get("access_logs.enabled")) else "Access logging disabled.",
            lb.address,
            "access_logs.enabled",
            True,
            lb.get("access_logs.enabled"),
        )
        for lb in lbs
    ]


def chk_asg_availability(g: PlanGraph, ctx: PolicyContext, p: Policy) -> list[PolicyResult]:
    asgs = g.of_type("aws_autoscaling_group")
    if not asgs:
        return [_r(p, "fail", "No auto scaling group: a failed server would not be replaced automatically.", None)]
    out = []
    for asg in asgs:
        min_size = int(asg.values.get("min_size") or 0)
        subnet_bases = {r for r in asg.refs_for("vpc_zone_identifier") if r.startswith("aws_subnet.")}
        subnet_count = sum(len(g.by_base(b)) for b in subnet_bases)
        hc = asg.values.get("health_check_type")
        problems = []
        if min_size < ctx.min_app_instances:
            problems.append(f"min_size {min_size} < required {ctx.min_app_instances}")
        if subnet_count < 2:
            problems.append(f"spans {subnet_count} subnet(s); at least 2 availability zones required")
        if hc != "ELB":
            problems.append(f"health_check_type is {hc}, so unhealthy application instances are not replaced")
        out.append(
            _r(
                p,
                "fail" if problems else "pass",
                "; ".join(problems)
                if problems
                else f"At least {min_size} instance(s) across {subnet_count} subnets with load balancer health checks.",
                asg.address,
                "min_size/vpc_zone_identifier/health_check_type",
                {"min_size": f">= {ctx.min_app_instances}", "subnets": ">= 2", "health_check_type": "ELB"},
                {"min_size": min_size, "subnets": subnet_count, "health_check_type": hc},
            )
        )
    return out


def chk_rds_multi_az(g: PlanGraph, ctx: PolicyContext, p: Policy) -> list[PolicyResult]:
    dbs = g.of_type("aws_db_instance")
    if not dbs:
        return _na(p, "No RDS database instances in the plan.")
    return [
        _r(
            p,
            "pass" if _truthy(db.values.get("multi_az")) else "fail",
            "Database has a synchronous standby in a second availability zone."
            if _truthy(db.values.get("multi_az"))
            else "Database runs in a single availability zone.",
            db.address,
            "multi_az",
            True,
            db.values.get("multi_az"),
        )
        for db in dbs
    ]


def chk_scaling(g: PlanGraph, ctx: PolicyContext, p: Policy) -> list[PolicyResult]:
    asgs = g.of_type("aws_autoscaling_group")
    if not asgs:
        return _na(p, "No auto scaling groups in the plan.")
    out = []
    for asg in asgs:
        pols = [sp for sp in g.referencing(asg.base, "aws_autoscaling_policy") if sp.values.get("policy_type") == "TargetTrackingScaling"]
        mx, mn = int(asg.values.get("max_size") or 0), int(asg.values.get("min_size") or 0)
        ok = bool(pols) and mx > mn
        out.append(
            _r(
                p,
                "pass" if ok else "fail",
                f"Target-tracking scaling from {mn} to {mx} instances."
                if ok
                else "No automatic scaling headroom (target tracking policy and max_size > min_size required).",
                asg.address,
                "max_size/aws_autoscaling_policy",
                "max_size > min_size with target tracking",
                {"min": mn, "max": mx, "policies": len(pols)},
            )
        )
    return out


def chk_waf(g: PlanGraph, ctx: PolicyContext, p: Policy) -> list[PolicyResult]:
    lbs = [lb for lb in g.of_type("aws_lb", "aws_alb") if not _truthy(lb.values.get("internal"))]
    if not lbs:
        return _na(p, "No internet-facing load balancers in the plan.")
    out = []
    for lb in lbs:
        assoc = g.referencing(lb.base, "aws_wafv2_web_acl_association")
        out.append(
            _r(
                p,
                "pass" if assoc else "fail",
                "AWS WAF web ACL is associated." if assoc else "No web application firewall in front of the load balancer.",
                lb.address,
                "aws_wafv2_web_acl_association",
                "associated",
                bool(assoc),
            )
        )
    return out


def chk_region(g: PlanGraph, ctx: PolicyContext, p: Policy) -> list[PolicyResult]:
    if not ctx.allowed_regions:
        return _na(p, "No data residency restriction.")
    region = g.provider_region
    ok = region in ctx.allowed_regions
    return [
        _r(
            p,
            "pass" if ok else "fail",
            f"Provider region {region} is within the allowed set."
            if ok
            else f"Provider region {region} is outside the allowed regions {ctx.allowed_regions}.",
            "provider.aws",
            "region",
            ctx.allowed_regions,
            region,
        )
    ]


def chk_tags(g: PlanGraph, ctx: PolicyContext, p: Policy) -> list[PolicyResult]:
    required = {"Project", "Environment", "ManagedBy"}
    taggable = [r for r in g.resources if "tags_all" in r.values]
    if not taggable:
        return _na(p, "No taggable resources in the plan.")
    missing = [
        (r.address, sorted(required - set((r.values.get("tags_all") or {}).keys())))
        for r in taggable
        if r.values.get("tags_all") is not None
    ]
    missing = [m for m in missing if m[1]]
    if missing:
        return [_r(p, "fail", f"Missing tags {tags}.", addr, "tags_all", sorted(required), None) for addr, tags in missing[:20]]
    return [_r(p, "pass", f"All {len(taggable)} taggable resources carry Project, Environment and ManagedBy tags.")]


def _decode_user_data(v: Any) -> str:
    if not isinstance(v, str):
        return ""
    try:
        return base64.b64decode(v, validate=True).decode("utf-8", "replace")
    except (binascii.Error, ValueError):
        return v


def chk_hardcoded_secrets(g: PlanGraph, ctx: PolicyContext, p: Policy) -> list[PolicyResult]:
    out = []
    for res in g.resources:
        texts = []
        for key in ("user_data", "user_data_base64"):
            if key in res.values:
                texts.append((key, _decode_user_data(res.values.get(key))))
        for key in ("tags", "environment"):
            val = res.values.get(key)
            if isinstance(val, dict):
                texts.append((key, json.dumps(val)))  # type: ignore[arg-type]  # validated by pydantic at runtime
        for key, text in texts:
            for pattern, label in SECRET_PATTERNS:
                if pattern.search(text or ""):
                    out.append(
                        _r(
                            p,
                            "fail",
                            f"Possible {label} embedded in {key} (value redacted).",
                            res.address,
                            key,
                            "no embedded credentials",
                            "<redacted>",
                        )
                    )
    if not out:
        out.append(_r(p, "pass", "No credential patterns found in user data, tags or environment values."))
    return out


def chk_destructive(g: PlanGraph, ctx: PolicyContext, p: Policy) -> list[PolicyResult]:
    out = []
    for ch in g.changes:
        if "delete" in ch.actions and ch.type in STATEFUL_TYPES:
            verb = "replaced (destroyed and recreated)" if "create" in ch.actions else "destroyed"
            out.append(
                _r(
                    p,
                    "fail",
                    f"Stateful resource will be {verb}; data may be lost.",
                    ch.address,
                    "actions",
                    "no destruction of stateful resources without explicit approval",
                    ch.actions,
                )
            )
    if not out:
        out.append(_r(p, "pass", "No stateful resources are destroyed or replaced by this plan."))
    return out


def chk_log_retention(g: PlanGraph, ctx: PolicyContext, p: Policy) -> list[PolicyResult]:
    need = ctx.log_retention_days
    if not need:
        return _na(p, "No log retention requirement.")
    out = []
    lifecycles = g.of_type("aws_s3_bucket_lifecycle_configuration")
    buckets = g.of_type("aws_s3_bucket")
    log_buckets = [b for b in buckets if g.referencing(b.base, "aws_flow_log", "aws_cloudtrail", "aws_lb")] or [
        b for b in buckets if "log" in b.name
    ]
    for b in log_buckets:
        rules = [lc for lc in lifecycles if b.base in lc.all_refs()]
        days = [
            int(exp["days"])
            for lc in rules
            for rule in _as_list(lc.values.get("rule"))
            if isinstance(rule, dict) and rule.get("status") == "Enabled"
            for exp in _as_list(rule.get("expiration"))
            if isinstance(exp, dict) and exp.get("days")
        ]
        shortest = min(days) if days else None
        ok = shortest is None or shortest >= need
        out.append(
            _r(
                p,
                "pass" if ok else "fail",
                (f"Log objects expire after {shortest} days." if shortest is not None else "Log objects never expire.")
                + f" Requirement: at least {need} days.",
                b.address,
                "lifecycle.expiration.days",
                f">= {need}",
                shortest,
            )
        )
    for lg in g.of_type("aws_cloudwatch_log_group"):
        days_v = int(lg.values.get("retention_in_days") or 0)
        ok = days_v == 0 or days_v >= need
        out.append(
            _r(
                p,
                "pass" if ok else "fail",
                f"Log group keeps events for {'ever' if days_v == 0 else f'{days_v} days'}; requirement is at least {need} days.",
                lg.address,
                "retention_in_days",
                f">= {need} (or 0 = never expire)",
                days_v,
            )
        )
    return out or _na(p, "No log storage in the plan.")


def chk_alerting(g: PlanGraph, ctx: PolicyContext, p: Policy) -> list[PolicyResult]:
    lbs = [lb for lb in g.of_type("aws_lb", "aws_alb") if not _truthy(lb.values.get("internal"))]
    if not lbs:
        return _na(p, "No internet-facing load balancers in the plan.")
    subscribed = [t for t in g.of_type("aws_sns_topic") if g.referencing(t.base, "aws_sns_topic_subscription")]
    notifying = {a.address for t in subscribed for a in g.referencing(t.base, "aws_cloudwatch_metric_alarm")}
    out = []
    for lb in lbs:
        alarms = [a for a in g.referencing(lb.base, "aws_cloudwatch_metric_alarm") if a.address in notifying]
        out.append(
            _r(
                p,
                "pass" if alarms else "fail",
                f"{len(alarms)} alarm(s) on this load balancer notify a subscribed SNS topic."
                if alarms
                else "No alarm on this load balancer notifies anyone.",
                lb.address,
                "aws_cloudwatch_metric_alarm.alarm_actions",
                "alarm → SNS topic with a subscription",
                [a.address for a in alarms],
            )
        )
    return out


def chk_sns_encrypted(g: PlanGraph, ctx: PolicyContext, p: Policy) -> list[PolicyResult]:
    topics = g.of_type("aws_sns_topic")
    if not topics:
        return _na(p, "No SNS topics in the plan.")
    out = []
    for t in topics:
        key = t.values.get("kms_master_key_id")
        ok = bool(key) or t.is_unknown("kms_master_key_id") or bool(t.refs.get("kms_master_key_id"))
        managed = isinstance(key, str) and key.endswith("alias/aws/sns")
        out.append(
            _r(
                p,
                "pass" if ok and not managed else "fail",
                "Topic encrypted with a customer-managed KMS key."
                if ok and not managed
                else (
                    "Topic uses the AWS-managed SNS key, which CloudWatch alarms cannot publish to."
                    if managed
                    else "Topic is not encrypted at rest."
                ),
                t.address,
                "kms_master_key_id",
                "customer-managed KMS key",
                key,
            )
        )
    return out


def chk_off_hours(g: PlanGraph, ctx: PolicyContext, p: Policy) -> list[PolicyResult]:
    asgs = g.of_type("aws_autoscaling_group")
    if not asgs:
        return _na(p, "No auto scaling groups in the plan.")
    out = []
    for asg in asgs:
        schedules = g.referencing(asg.base, "aws_autoscaling_schedule")
        stops = [s for s in schedules if int(s.values.get("desired_capacity") or 0) == 0 and int(s.values.get("max_size") or 0) == 0]
        starts = [s for s in schedules if int(s.values.get("desired_capacity") or 0) > 0]
        ok = bool(stops) and bool(starts)
        out.append(
            _r(
                p,
                "pass" if ok else "fail",
                f"Scheduled scale-to-zero ({stops[0].values.get('recurrence')}) and restart ({starts[0].values.get('recurrence')})."
                if ok
                else "No schedule scales this group to zero outside business hours.",
                asg.address,
                "aws_autoscaling_schedule",
                "stop schedule (0 capacity) and start schedule",
                {"stop": [s.address for s in stops], "start": [s.address for s in starts]},
            )
        )
    return out


POLICIES: list[Policy] = [
    Policy(
        "POL-RDS-001",
        "Database is not publicly accessible",
        Severity.critical,
        "network",
        "RDS instances must not be assigned a public endpoint.",
        "Set publicly_accessible = false and place the database in private subnets.",
        chk_rds_public,
        baseline=True,
    ),
    Policy(
        "POL-RDS-002",
        "Database storage encrypted at rest",
        Severity.high,
        "encryption",
        "RDS storage must be encrypted.",
        "Set storage_encrypted = true (optionally with kms_key_id). Existing unencrypted databases require a snapshot-copy migration.",
        chk_rds_encrypted,
        baseline=True,
    ),
    Policy(
        "POL-RDS-003",
        "Automated backups meet retention requirement",
        Severity.medium,
        "availability",
        "Backup retention must meet the requirement derived from the interview.",
        "Increase backup_retention_period.",
        chk_rds_backups,
    ),
    Policy(
        "POL-RDS-004",
        "Production database protected from deletion",
        Severity.high,
        "operational",
        "Production databases need deletion protection and a final snapshot.",
        "Set deletion_protection = true and skip_final_snapshot = false with final_snapshot_identifier.",
        chk_rds_deletion,
    ),
    Policy(
        "POL-RDS-005",
        "Database credentials not stored in configuration",
        Severity.high,
        "secrets",
        "Master credentials must be managed by AWS Secrets Manager, never written in Terraform.",
        "Remove password and set manage_master_user_password = true.",
        chk_rds_secret,
        baseline=True,
    ),
    Policy(
        "POL-RDS-006",
        "Database enforces TLS connections",
        Severity.high,
        "encryption",
        "Client connections to the database must use TLS.",
        "Attach a parameter group with rds.force_ssl = 1.",
        chk_rds_tls,
    ),
    Policy(
        "POL-NET-001",
        "Database placed in private subnets",
        Severity.critical,
        "network",
        "Database subnets must have no route to an internet gateway.",
        "Use a DB subnet group containing only private (data-tier) subnets.",
        chk_db_private_subnets,
        baseline=True,
    ),
    Policy(
        "POL-SG-001",
        "No internet ingress to administrative or database ports",
        Severity.critical,
        "network",
        "Security groups must not expose SSH, RDP, database or all ports to 0.0.0.0/0 or ::/0.",
        "Remove the rule, use AWS Systems Manager Session Manager for administration, or restrict the source to a specific range.",
        chk_sg_world_ingress,
        baseline=True,
    ),
    Policy(
        "POL-SG-002",
        "Database reachable only from the application tier",
        Severity.critical,
        "network",
        "Database security groups may only accept traffic from the application security group.",
        "Replace CIDR-based rules with a rule referencing the application security group.",
        chk_db_sg_sources,
        baseline=True,
    ),
    Policy(
        "POL-SG-003",
        "Application servers reachable only through the load balancer",
        Severity.critical,
        "network",
        "Application security groups may only accept traffic from the load balancer (and SSH from an approved range if configured).",
        "Reference the load balancer security group as the only source.",
        chk_app_sg_sources,
    ),
    Policy(
        "POL-SG-004",
        "Default security group restricts all traffic",
        Severity.low,
        "network",
        "The VPC default security group should have no rules.",
        "Manage aws_default_security_group with no ingress or egress blocks.",
        chk_default_sg,
    ),
    Policy(
        "POL-IAM-001",
        "IAM policies follow least privilege",
        Severity.critical,
        "iam",
        "No wildcard actions, NotAction grants or privilege-escalation actions on all resources.",
        "Grant only the specific actions on specific resource ARNs the workload needs.",
        chk_iam_wildcards,
        baseline=True,
    ),
    Policy(
        "POL-IAM-002",
        "No administrator policies attached",
        Severity.critical,
        "iam",
        "AdministratorAccess, PowerUserAccess and IAMFullAccess must not be attached.",
        "Attach a scoped policy instead.",
        chk_iam_admin,
        baseline=True,
    ),
    Policy(
        "POL-IAM-003",
        "No IAM users or long-lived access keys",
        Severity.high,
        "iam",
        "Workloads must use roles and temporary credentials.",
        "Use an instance profile / role instead of IAM users and access keys.",
        chk_iam_users,
        baseline=True,
    ),
    Policy(
        "POL-EC2-001",
        "Instance metadata service v2 required",
        Severity.high,
        "compute",
        "IMDSv2 mitigates SSRF-based credential theft.",
        'Set metadata_options { http_tokens = "required" }.',
        chk_imdsv2,
        baseline=True,
    ),
    Policy(
        "POL-EC2-002",
        "Application servers have no public IP addresses",
        Severity.high,
        "network",
        "Application servers run in private subnets without public IPs.",
        "Launch into private subnets with NAT for egress and set associate_public_ip_address = false.",
        chk_app_private,
    ),
    Policy(
        "POL-EC2-003",
        "Instance storage encrypted",
        Severity.high,
        "encryption",
        "EBS volumes must be encrypted.",
        "Set encrypted = true on block device mappings / volumes.",
        chk_ebs_encryption,
        baseline=True,
    ),
    Policy(
        "POL-S3-001",
        "S3 buckets are not public",
        Severity.high,
        "storage",
        "Every bucket needs a full public access block and no public ACL or anonymous policy.",
        "Add aws_s3_bucket_public_access_block with all four settings true; remove public ACLs/policies.",
        chk_s3_public,
        baseline=True,
    ),
    Policy(
        "POL-S3-002",
        "S3 default encryption configured",
        Severity.high,
        "encryption",
        "Buckets must declare default server-side encryption.",
        "Add aws_s3_bucket_server_side_encryption_configuration (AES256 or aws:kms).",
        chk_s3_encryption,
        baseline=True,
    ),
    Policy(
        "POL-S3-003",
        "Log bucket versioning enabled",
        Severity.low,
        "logging",
        "Versioning protects audit logs from overwrite.",
        "Add aws_s3_bucket_versioning with status Enabled.",
        chk_s3_versioning,
    ),
    Policy(
        "POL-ALB-001",
        "HTTPS with modern TLS on internet-facing load balancers",
        Severity.high,
        "encryption",
        "Internet-facing load balancers must terminate TLS 1.2+.",
        "Add an HTTPS listener with an ACM certificate and ELBSecurityPolicy-TLS13-1-2-2021-06.",
        chk_alb_https,
    ),
    Policy(
        "POL-ALB-002",
        "HTTP redirects to HTTPS",
        Severity.high,
        "encryption",
        "Plaintext listeners must only redirect.",
        "Change the HTTP listener default action to a 301 redirect to HTTPS.",
        chk_alb_redirect,
    ),
    Policy(
        "POL-ALB-003",
        "Load balancer drops invalid headers",
        Severity.medium,
        "network",
        "Dropping invalid header fields mitigates request smuggling.",
        "Set drop_invalid_header_fields = true.",
        chk_alb_headers,
        baseline=True,
    ),
    Policy(
        "POL-LOG-001",
        "CloudTrail audit trail enabled",
        Severity.high,
        "logging",
        "A multi-region trail with log file validation records API activity.",
        "Add aws_cloudtrail with is_multi_region_trail and enable_log_file_validation.",
        chk_cloudtrail,
    ),
    Policy(
        "POL-LOG-002",
        "VPC flow logs enabled",
        Severity.medium,
        "logging",
        "Network flow logs support investigation.",
        'Add aws_flow_log with traffic_type = "ALL".',
        chk_flow_logs,
    ),
    Policy(
        "POL-LOG-003",
        "Load balancer access logs enabled",
        Severity.medium,
        "logging",
        "Access logs record every request.",
        "Enable access_logs on the load balancer.",
        chk_alb_logs,
    ),
    Policy(
        "POL-AVL-001",
        "Application tolerates instance and zone failure",
        Severity.high,
        "availability",
        "Auto scaling group with ELB health checks across two or more AZs.",
        'Use an ASG spanning two subnets in different AZs with health_check_type = "ELB".',
        chk_asg_availability,
    ),
    Policy(
        "POL-AVL-002",
        "Database survives an availability-zone failure",
        Severity.high,
        "availability",
        "Multi-AZ deployment keeps a synchronous standby.",
        "Set multi_az = true.",
        chk_rds_multi_az,
    ),
    Policy(
        "POL-PRF-001",
        "Application scales with demand",
        Severity.medium,
        "performance",
        "Target-tracking scaling with headroom above the minimum.",
        "Add a target-tracking aws_autoscaling_policy and set max_size above min_size.",
        chk_scaling,
    ),
    Policy(
        "POL-WAF-001",
        "Web application firewall in front of the application",
        Severity.high,
        "network",
        "AWS WAF filters common web exploits.",
        "Associate an aws_wafv2_web_acl with the load balancer.",
        chk_waf,
    ),
    Policy(
        "POL-REG-001",
        "Resources deployed only in allowed regions",
        Severity.critical,
        "compliance",
        "Data residency restricts the AWS region.",
        "Change aws_region to one of the allowed regions.",
        chk_region,
    ),
    Policy(
        "POL-LOG-004",
        "Logs kept for the required retention period",
        Severity.medium,
        "logging",
        "Log bucket lifecycle expiration and CloudWatch log group retention must meet the retention requirement.",
        "Increase the lifecycle expiration days and log group retention_in_days.",
        chk_log_retention,
    ),
    Policy(
        "POL-OPS-001",
        "Load balancer alarms notify the team",
        Severity.medium,
        "operational",
        "At least one CloudWatch alarm on each internet-facing load balancer must notify an SNS topic with a subscription.",
        "Add an aws_cloudwatch_metric_alarm with alarm_actions pointing to a subscribed aws_sns_topic.",
        chk_alerting,
    ),
    Policy(
        "POL-OPS-002",
        "Alert topic encrypted with a customer-managed key",
        Severity.low,
        "encryption",
        "SNS topics must be encrypted at rest with a key that CloudWatch alarms are allowed to use.",
        "Set kms_master_key_id to a customer-managed KMS key whose policy allows cloudwatch.amazonaws.com.",
        chk_sns_encrypted,
    ),
    Policy(
        "POL-CST-001",
        "Servers scheduled off outside business hours",
        Severity.low,
        "cost",
        "Non-production auto scaling groups must have scale-to-zero and restart schedules when the off-hours requirement applies.",
        "Add aws_autoscaling_schedule resources that set capacity to 0 in the evening and restore it in the morning.",
        chk_off_hours,
    ),
    Policy(
        "POL-TAG-001",
        "Resources tagged for ownership",
        Severity.low,
        "operational",
        "Project, Environment and ManagedBy tags on every resource.",
        "Use provider default_tags.",
        chk_tags,
    ),
    Policy(
        "POL-SEC-002",
        "No credentials embedded in configuration",
        Severity.high,
        "secrets",
        "Supplementary pattern scan of user data, tags and environment values for credential-like strings.",
        "Move secrets to AWS Secrets Manager or SSM Parameter Store and read them at runtime.",
        chk_hardcoded_secrets,
        baseline=True,
    ),
    Policy(
        "POL-CHG-001",
        "No destruction of stateful resources",
        Severity.high,
        "change-safety",
        "Deleting or replacing databases and buckets risks data loss and needs explicit approval.",
        "Avoid replacement (check which attribute forces it), take a snapshot, or approve the destructive change explicitly.",
        chk_destructive,
        baseline=True,
    ),
]

POLICY_INDEX = {p.id: p for p in POLICIES}
