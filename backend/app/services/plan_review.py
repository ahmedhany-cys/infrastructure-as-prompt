"""Human-readable review of a Terraform plan."""

from __future__ import annotations

from typing import Any

from app.domain.findings import PlanReview, ResourceChange
from app.services.policy.graph import ResourceChangeInfo, build_graph
from app.services.policy.rules import STATEFUL_TYPES

FRIENDLY = {
    "aws_db_instance": "database",
    "aws_s3_bucket": "storage bucket",
    "aws_lb": "load balancer",
    "aws_autoscaling_group": "application server group",
    "aws_launch_template": "server template",
    "aws_nat_gateway": "NAT gateway",
    "aws_security_group": "security group",
    "aws_vpc": "network (VPC)",
    "aws_subnet": "subnet",
    "aws_iam_role": "IAM role",
    "aws_iam_role_policy": "IAM permissions",
    "aws_cloudtrail": "audit trail",
    "aws_wafv2_web_acl": "web application firewall",
}
DOWNTIME_TYPES = {
    "aws_lb",
    "aws_lb_listener",
    "aws_autoscaling_group",
    "aws_nat_gateway",
    "aws_db_instance",
    "aws_subnet",
    "aws_vpc",
    "aws_route_table",
    "aws_lb_target_group",
}
SECURITY_TYPES = (
    "aws_security_group",
    "aws_vpc_security_group_",
    "aws_iam_",
    "aws_s3_bucket_policy",
    "aws_s3_bucket_public_access_block",
    "aws_wafv2",
    "aws_kms",
)
DB_DOWNTIME_ATTRS = {"instance_class", "multi_az", "engine_version", "allocated_storage", "storage_type", "parameter_group_name"}


def _action(actions: list[str]) -> str:
    if actions in (["delete", "create"], ["create", "delete"]):
        return "replace"
    if actions == ["no-op"]:
        return "no-op"
    return actions[0] if actions else "no-op"


def _changed(ch: ResourceChangeInfo) -> list[str]:
    before, after = ch.before or {}, ch.after or {}
    keys = set(before) | set(after) | {k for k, v in ch.after_unknown.items() if v is True}
    out = []
    for k in sorted(keys):
        if k in ("tags_all",):
            continue
        if before.get(k) != after.get(k) or ch.after_unknown.get(k) is True and ch.before is not None:
            out.append(k)
    return out


def review(plan_json: dict[str, Any], cost_note: str = "") -> PlanReview:
    graph = build_graph(plan_json)
    changes: list[ResourceChange] = []
    counts = {"create": 0, "update": 0, "delete": 0, "replace": 0, "no-op": 0}
    data_loss: list[str] = []
    downtime: list[str] = []
    security: list[str] = []
    for ch in graph.changes:
        action = _action(ch.actions)
        counts[action] = counts.get(action, 0) + 1
        if action == "no-op":
            continue
        stateful = ch.type in STATEFUL_TYPES
        attrs = _changed(ch) if action in ("update", "replace") else []
        notes: list[str] = []
        risk = "none"
        friendly = FRIENDLY.get(ch.type, ch.type.removeprefix("aws_").replace("_", " "))
        if action == "replace":
            forcing = [".".join(str(p) for p in path) for path in ch.replace_paths] or attrs[:3]
            notes.append(
                f"Replaced because {', '.join(forcing) or 'a non-updatable attribute'} changed: the existing {friendly} is destroyed and a new one created."
            )
            risk = "critical" if stateful else "high"
        elif action == "delete":
            notes.append(f"The {friendly} will be permanently deleted.")
            risk = "critical" if stateful else "high"
        elif action == "update":
            notes.append(f"Updated in place: {', '.join(attrs[:6]) or 'attributes'}{'…' if len(attrs) > 6 else ''}.")
            risk = "medium" if ch.type in DOWNTIME_TYPES else "low"
        else:
            risk = "low" if ch.type.startswith(SECURITY_TYPES) else "none"
        if stateful and action in ("delete", "replace"):
            data_loss.append(
                f"{ch.address}: {friendly} will be {'destroyed and recreated' if action == 'replace' else 'destroyed'} — existing data may be lost unless a snapshot or backup is restored."
            )
        if action in ("delete", "replace") and ch.type in DOWNTIME_TYPES:
            downtime.append(f"{ch.address}: {action} of the {friendly} interrupts service while it is recreated.")
        if action == "update" and ch.type == "aws_db_instance" and set(attrs) & DB_DOWNTIME_ATTRS:
            downtime.append(
                f"{ch.address}: changing {', '.join(sorted(set(attrs) & DB_DOWNTIME_ATTRS))} may cause a database restart or failover (applied in the maintenance window unless applied immediately)."
            )
        if ch.type.startswith(SECURITY_TYPES) and action != "no-op":
            security.append(
                f"{ch.address}: {action} — {friendly} controls who can reach or do what; review the policy findings for this resource."
            )
        changes.append(
            ResourceChange(
                address=ch.address,
                type=ch.type,
                name=ch.name,
                actions=ch.actions,
                action=action,  # type: ignore[arg-type]
                stateful=stateful,
                risk=risk,  # type: ignore[arg-type]  # validated by pydantic at runtime
                notes=notes,
                changed_attributes=attrs,
            )
        )  # type: ignore[arg-type]
    destructive = counts["delete"] + counts["replace"] > 0
    parts = [f"{counts[k]} to {k}" for k in ("create", "update", "replace", "delete") if counts[k]]
    headline = ("Plan: " + ", ".join(parts)) if parts else "No changes. The infrastructure matches the configuration."
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "none": 4}
    changes.sort(key=lambda c: (order[c.risk], c.address))
    return PlanReview(
        counts=counts,
        changes=changes,
        destructive=destructive,
        data_loss_risks=data_loss,
        downtime_risks=downtime,
        security_notes=security[:30],
        cost_note=cost_note,
        headline=headline,
    )
