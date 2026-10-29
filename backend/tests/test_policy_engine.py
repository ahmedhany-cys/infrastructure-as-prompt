"""Policy engine: positive tests on a real secure plan, negative tests on a real
insecure plan, and targeted negative tests on minimal synthetic plans."""

import json
from typing import Any

import pytest

from app.domain.requirements import RequirementsSpec, Severity
from app.services.policy.engine import context_from_requirements, evaluate, summarize
from app.services.policy.rules import POLICIES, PolicyContext
from tests.conftest import FIXTURES

ALL = {p.id for p in POLICIES}


def load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text())


def spec() -> RequirementsSpec:
    return RequirementsSpec.model_validate_json((FIXTURES / "spec_balanced.json").read_text())


def plan(
    resources: list[dict[str, Any]],
    config: list[dict[str, Any]] | None = None,
    changes: list[dict[str, Any]] | None = None,
    region: str = "us-east-1",
) -> dict[str, Any]:
    """Minimal plan JSON. resources: {address, type, values}; config: {address, expressions}."""
    rs = []
    for r in resources:
        name = r["address"].split(".")[1].split("[")[0]
        rs.append({"address": r["address"], "mode": "managed", "type": r["type"], "name": name, "values": r["values"]})
    return {
        "planned_values": {"root_module": {"resources": rs}},
        "resource_changes": changes
        or [
            {
                "address": r["address"],
                "mode": "managed",
                "type": r["type"],
                "name": r["address"].split(".")[1],
                "change": {"actions": ["create"], "before": None, "after": r["values"], "after_unknown": {}},
            }
            for r in rs
        ],
        "configuration": {
            "provider_config": {"aws": {"expressions": {"region": {"constant_value": region}}}},
            "root_module": {"resources": config or []},
        },
        "variables": {},
    }


def ref(*targets: str) -> dict[str, Any]:
    return {"references": list(targets)}


def run(p: dict[str, Any], **ctx: Any) -> list:
    return evaluate(p, PolicyContext(enabled=set(ALL), **ctx))


def fails(results: list, policy_id: str) -> list:
    return [r for r in results if r.policy_id == policy_id and r.outcome == "fail"]


# --- real plans ----------------------------------------------------------------


def test_secure_generated_plan_passes_all_enabled_policies():
    s = spec()
    results = evaluate(load("plan_secure_balanced.json"), context_from_requirements(s), s)
    assert [r for r in results if r.outcome in ("fail", "error")] == []
    summary = summarize(results, [])
    assert not summary.blocking and summary.passed >= 25


def test_insecure_plan_is_blocked_with_specific_evidence():
    s = spec()
    results = evaluate(load("plan_insecure_balanced.json"), context_from_requirements(s), s)
    failed = {(r.policy_id, r.resource) for r in results if r.outcome == "fail"}
    assert ("POL-RDS-001", "aws_db_instance.main") in failed
    assert ("POL-SG-001", "aws_vpc_security_group_ingress_rule.debug_ssh") in failed
    assert ("POL-IAM-001", "aws_iam_role_policy.app_read_db_secret") in failed
    rds = fails(results, "POL-RDS-001")[0]
    assert rds.expected is False and rds.actual is True and rds.requirements == ["REQ-SEC-001"] and rds.remediation
    summary = summarize(results, [])
    assert summary.blocking and summary.critical >= 3


def test_strict_profile_blocks_on_high():
    results = run(
        plan(
            [
                {
                    "address": "aws_launch_template.app",
                    "type": "aws_launch_template",
                    "values": {"metadata_options": [{"http_tokens": "optional"}], "block_device_mappings": []},
                }
            ]
        )
    )
    assert fails(results, "POL-EC2-001")
    assert not summarize(results, [], "standard").blocking
    assert summarize(results, [], "strict").blocking


# --- targeted negative / positive tests ----------------------------------------------


@pytest.mark.parametrize(
    "port,severity", [(22, Severity.critical), (3389, Severity.critical), (5432, Severity.critical), (8080, Severity.high)]
)
def test_world_ingress_detected(port, severity):
    p = plan(
        [
            {"address": "aws_security_group.x", "type": "aws_security_group", "values": {}},
            {
                "address": "aws_vpc_security_group_ingress_rule.r",
                "type": "aws_vpc_security_group_ingress_rule",
                "values": {"cidr_ipv4": "0.0.0.0/0", "from_port": port, "to_port": port, "ip_protocol": "tcp"},
            },
        ],
        [
            {
                "address": "aws_vpc_security_group_ingress_rule.r",
                "expressions": {"security_group_id": ref("aws_security_group.x.id", "aws_security_group.x")},
            }
        ],
    )
    f = fails(run(p), "POL-SG-001")
    assert f and f[0].severity == severity


def test_all_ports_inline_ipv6_rule_detected():
    p = plan(
        [
            {
                "address": "aws_security_group.x",
                "type": "aws_security_group",
                "values": {"ingress": [{"from_port": 0, "to_port": 0, "protocol": "-1", "cidr_blocks": [], "ipv6_cidr_blocks": ["::/0"]}]},
            }
        ]
    )
    assert fails(run(p), "POL-SG-001")[0].severity == Severity.critical


def test_https_to_internet_facing_lb_is_allowed():
    p = plan(
        [
            {"address": "aws_security_group.alb", "type": "aws_security_group", "values": {}},
            {"address": "aws_lb.app", "type": "aws_lb", "values": {"internal": False}},
            {
                "address": "aws_vpc_security_group_ingress_rule.https",
                "type": "aws_vpc_security_group_ingress_rule",
                "values": {"cidr_ipv4": "0.0.0.0/0", "from_port": 443, "to_port": 443, "ip_protocol": "tcp"},
            },
        ],
        [
            {"address": "aws_lb.app", "expressions": {"security_groups": ref("aws_security_group.alb.id")}},
            {
                "address": "aws_vpc_security_group_ingress_rule.https",
                "expressions": {"security_group_id": ref("aws_security_group.alb.id")},
            },
        ],
    )
    results = run(p)
    assert not fails(results, "POL-SG-001")
    assert any(r.policy_id == "POL-SG-001" and r.outcome == "pass" for r in results)


def test_database_in_public_subnet_detected():
    p = plan(
        [
            {
                "address": "aws_db_instance.db",
                "type": "aws_db_instance",
                "values": {"publicly_accessible": False, "storage_encrypted": True},
            },
            {"address": "aws_db_subnet_group.g", "type": "aws_db_subnet_group", "values": {}},
            {"address": "aws_subnet.pub[0]", "type": "aws_subnet", "values": {"map_public_ip_on_launch": False}},
            {"address": "aws_internet_gateway.igw", "type": "aws_internet_gateway", "values": {}},
            {"address": "aws_route_table.rt", "type": "aws_route_table", "values": {}},
            {"address": "aws_route_table_association.a[0]", "type": "aws_route_table_association", "values": {}},
        ],
        [
            {"address": "aws_db_subnet_group.g", "expressions": {"subnet_ids": ref("aws_subnet.pub")}},
            {"address": "aws_route_table.rt", "expressions": {"route": [{"gateway_id": ref("aws_internet_gateway.igw.id")}]}},
            {
                "address": "aws_route_table_association.a",
                "expressions": {"subnet_id": ref("aws_subnet.pub[0].id"), "route_table_id": ref("aws_route_table.rt.id")},
            },
        ],
    )
    assert fails(run(p), "POL-NET-001")


def test_database_cidr_ingress_detected():
    p = plan(
        [
            {"address": "aws_db_instance.db", "type": "aws_db_instance", "values": {}},
            {"address": "aws_security_group.db", "type": "aws_security_group", "values": {}},
            {
                "address": "aws_vpc_security_group_ingress_rule.r",
                "type": "aws_vpc_security_group_ingress_rule",
                "values": {"cidr_ipv4": "10.0.0.0/8", "from_port": 5432, "to_port": 5432, "ip_protocol": "tcp"},
            },
        ],
        [
            {"address": "aws_db_instance.db", "expressions": {"vpc_security_group_ids": ref("aws_security_group.db.id")}},
            {"address": "aws_vpc_security_group_ingress_rule.r", "expressions": {"security_group_id": ref("aws_security_group.db.id")}},
        ],
    )
    assert fails(run(p), "POL-SG-002")


def test_rds_encryption_secret_and_deletion_policies():
    p = plan(
        [
            {
                "address": "aws_db_instance.db",
                "type": "aws_db_instance",
                "values": {
                    "storage_encrypted": False,
                    "password": "hunter2-not-real",
                    "deletion_protection": False,
                    "skip_final_snapshot": True,
                    "backup_retention_period": 1,
                    "multi_az": False,
                },
            }
        ]
    )
    results = run(p, required_backup_days=7)
    assert (
        fails(results, "POL-RDS-002") and fails(results, "POL-RDS-004") and fails(results, "POL-RDS-003") and fails(results, "POL-AVL-002")
    )
    secret = fails(results, "POL-RDS-005")[0]
    assert secret.actual == "<redacted>" and "hunter2" not in json.dumps([r.model_dump(mode="json") for r in results])


@pytest.mark.parametrize(
    "statement,severity",
    [
        ({"Effect": "Allow", "Action": "*", "Resource": "*"}, Severity.critical),
        ({"Effect": "Allow", "Action": "s3:*", "Resource": "*"}, Severity.high),
        ({"Effect": "Allow", "NotAction": "iam:*", "Resource": "*"}, Severity.high),
        ({"Effect": "Allow", "Action": ["iam:PassRole"], "Resource": "*"}, Severity.high),
    ],
)
def test_iam_wildcards_detected(statement, severity):
    p = plan(
        [
            {
                "address": "aws_iam_policy.p",
                "type": "aws_iam_policy",
                "values": {"policy": json.dumps({"Version": "2012-10-17", "Statement": [statement]})},
            }
        ]
    )
    f = fails(run(p), "POL-IAM-001")
    assert f and f[0].severity == severity


def test_scoped_iam_policy_passes():
    doc = {"Statement": [{"Effect": "Allow", "Action": ["s3:GetObject"], "Resource": "arn:aws:s3:::bucket/*"}]}
    p = plan([{"address": "aws_iam_policy.p", "type": "aws_iam_policy", "values": {"policy": json.dumps(doc)}}])
    assert not fails(run(p), "POL-IAM-001")


def test_admin_policy_attachment_and_iam_user_detected():
    p = plan(
        [
            {
                "address": "aws_iam_role_policy_attachment.a",
                "type": "aws_iam_role_policy_attachment",
                "values": {"policy_arn": "arn:aws:iam::aws:policy/AdministratorAccess"},
            },
            {"address": "aws_iam_access_key.k", "type": "aws_iam_access_key", "values": {}},
        ]
    )
    results = run(p)
    assert fails(results, "POL-IAM-002") and fails(results, "POL-IAM-003")


def test_s3_without_public_access_block_or_encryption_detected():
    p = plan(
        [
            {"address": "aws_s3_bucket.b", "type": "aws_s3_bucket", "values": {}},
            {"address": "aws_s3_bucket_acl.b", "type": "aws_s3_bucket_acl", "values": {"acl": "public-read"}},
        ],
        [{"address": "aws_s3_bucket_acl.b", "expressions": {"bucket": ref("aws_s3_bucket.b.id")}}],
    )
    results = run(p)
    assert len(fails(results, "POL-S3-001")) == 2  # missing PAB + public ACL
    assert fails(results, "POL-S3-002")


def test_http_listener_without_redirect_detected():
    p = plan(
        [
            {"address": "aws_lb.app", "type": "aws_lb", "values": {"internal": False, "drop_invalid_header_fields": False}},
            {
                "address": "aws_lb_listener.http",
                "type": "aws_lb_listener",
                "values": {"protocol": "HTTP", "default_action": [{"type": "forward"}]},
            },
        ],
        [{"address": "aws_lb_listener.http", "expressions": {"load_balancer_arn": ref("aws_lb.app.arn")}}],
    )
    results = run(p)
    assert fails(results, "POL-ALB-001") and fails(results, "POL-ALB-002") and fails(results, "POL-ALB-003")


def test_region_outside_residency_detected():
    p = plan([{"address": "aws_vpc.v", "type": "aws_vpc", "values": {}}], region="us-east-1")
    assert fails(run(p, allowed_regions=["eu-west-1"]), "POL-REG-001")
    assert not fails(run(p, allowed_regions=["us-east-1"]), "POL-REG-001")


def test_credentials_in_user_data_detected_and_redacted():
    import base64

    fake_key = "AKIA" + "ABCDEFGHIJKLMNOP"  # assembled at runtime so secret scanners do not flag the repo
    ud = base64.b64encode(f"#!/bin/bash\nexport AWS_ACCESS_KEY_ID={fake_key}\n".encode()).decode()
    p = plan(
        [
            {
                "address": "aws_launch_template.lt",
                "type": "aws_launch_template",
                "values": {"user_data": ud, "metadata_options": [{"http_tokens": "required"}]},
            }
        ]
    )
    f = fails(run(p), "POL-SEC-002")
    assert f and "AKIA" not in json.dumps([x.model_dump(mode="json") for x in f])


def test_destructive_change_to_database_flagged():
    p = plan(
        [],
        changes=[
            {
                "address": "aws_db_instance.db",
                "mode": "managed",
                "type": "aws_db_instance",
                "name": "db",
                "change": {"actions": ["delete", "create"], "before": {}, "after": {}, "after_unknown": {}, "replace_paths": [["engine"]]},
            }
        ],
    )
    results = run(p)
    assert fails(results, "POL-CHG-001")
    assert not summarize(results, []).blocking, "destructive changes are gated by explicit approval, not by blocking"


def test_policy_crash_is_an_error_that_blocks(monkeypatch):
    from app.services.policy import rules

    def boom(*_a: Any) -> list:
        raise RuntimeError("bug")

    target = next(p for p in rules.POLICIES if p.id == "POL-RDS-001")
    monkeypatch.setattr(target, "check", boom)
    results = run(plan([]))
    assert any(r.policy_id == "POL-RDS-001" and r.outcome == "error" for r in results)
    assert summarize(results, []).blocking


def test_disabled_policies_are_reported_not_applicable():
    results = evaluate(plan([]), PolicyContext(enabled=set()))
    assert all(r.outcome == "not_applicable" for r in results) and len(results) == len(POLICIES)


# --- customer-tailored requirements -------------------------------------------------


def _log_plan(expire_days: int, group_days: int) -> dict[str, Any]:
    return plan(
        [
            {"address": "aws_s3_bucket.logs", "type": "aws_s3_bucket", "values": {}},
            {"address": "aws_cloudtrail.main", "type": "aws_cloudtrail", "values": {"is_multi_region_trail": True}},
            {
                "address": "aws_s3_bucket_lifecycle_configuration.logs",
                "type": "aws_s3_bucket_lifecycle_configuration",
                "values": {"rule": [{"status": "Enabled", "expiration": [{"days": expire_days}]}]},
            },
            {"address": "aws_cloudwatch_log_group.pg", "type": "aws_cloudwatch_log_group", "values": {"retention_in_days": group_days}},
        ],
        config=[
            {"address": "aws_cloudtrail.main", "expressions": {"s3_bucket_name": ref("aws_s3_bucket.logs.id", "aws_s3_bucket.logs")}},
            {"address": "aws_s3_bucket_lifecycle_configuration.logs", "expressions": {"bucket": ref("aws_s3_bucket.logs.id")}},
        ],
    )


def test_log_retention_policy():
    assert fails(run(_log_plan(365, 365), log_retention_days=365), "POL-LOG-004") == []
    short = fails(run(_log_plan(90, 365), log_retention_days=365), "POL-LOG-004")
    assert len(short) == 1 and short[0].resource == "aws_s3_bucket.logs" and short[0].actual == 90
    group = fails(run(_log_plan(365, 30), log_retention_days=365), "POL-LOG-004")
    assert len(group) == 1 and group[0].resource == "aws_cloudwatch_log_group.pg"
    assert fails(run(_log_plan(365, 0), log_retention_days=365), "POL-LOG-004") == []  # 0 = never expire
    na = [r for r in run(_log_plan(1, 1)) if r.policy_id == "POL-LOG-004"]
    assert na[0].outcome == "not_applicable"


def _alert_plan(subscribed: bool = True, alarm_on_lb: bool = True, key: Any = "arn:aws:kms:us-east-1:000000000000:key/x") -> dict[str, Any]:
    resources = [
        {"address": "aws_lb.app", "type": "aws_lb", "values": {"internal": False}},
        {"address": "aws_sns_topic.alerts", "type": "aws_sns_topic", "values": {"kms_master_key_id": key}},
        {"address": "aws_cloudwatch_metric_alarm.alb_5xx", "type": "aws_cloudwatch_metric_alarm", "values": {}},
    ]
    config = [
        {
            "address": "aws_cloudwatch_metric_alarm.alb_5xx",
            "expressions": {
                "alarm_actions": ref("aws_sns_topic.alerts.arn"),
                **({"dimensions": ref("aws_lb.app.arn_suffix")} if alarm_on_lb else {}),
            },
        }
    ]
    if subscribed:
        resources.append({"address": "aws_sns_topic_subscription.email", "type": "aws_sns_topic_subscription", "values": {}})
        config.append({"address": "aws_sns_topic_subscription.email", "expressions": {"topic_arn": ref("aws_sns_topic.alerts.arn")}})
    return plan(resources, config=config)


def test_alerting_policies():
    ok = run(_alert_plan())
    assert fails(ok, "POL-OPS-001") == [] and fails(ok, "POL-OPS-002") == []
    assert len(fails(run(_alert_plan(subscribed=False)), "POL-OPS-001")) == 1
    assert len(fails(run(_alert_plan(alarm_on_lb=False)), "POL-OPS-001")) == 1
    managed = fails(run(_alert_plan(key="alias/aws/sns")), "POL-OPS-002")
    assert len(managed) == 1 and "AWS-managed" in managed[0].message
    assert len(fails(run(_alert_plan(key=None)), "POL-OPS-002")) == 1


def _schedule_plan(stop_capacity: int) -> dict[str, Any]:
    return plan(
        [
            {"address": "aws_autoscaling_group.app", "type": "aws_autoscaling_group", "values": {"min_size": 1, "max_size": 3}},
            {
                "address": "aws_autoscaling_schedule.start",
                "type": "aws_autoscaling_schedule",
                "values": {"desired_capacity": 1, "max_size": 3, "recurrence": "0 7 * * MON-FRI"},
            },
            {
                "address": "aws_autoscaling_schedule.stop",
                "type": "aws_autoscaling_schedule",
                "values": {"desired_capacity": stop_capacity, "max_size": stop_capacity, "recurrence": "0 19 * * MON-FRI"},
            },
        ],
        config=[
            {"address": "aws_autoscaling_schedule.start", "expressions": {"autoscaling_group_name": ref("aws_autoscaling_group.app.name")}},
            {"address": "aws_autoscaling_schedule.stop", "expressions": {"autoscaling_group_name": ref("aws_autoscaling_group.app.name")}},
        ],
    )


def test_off_hours_schedule_policy():
    assert fails(run(_schedule_plan(0)), "POL-CST-001") == []
    assert len(fails(run(_schedule_plan(1)), "POL-CST-001")) == 1
