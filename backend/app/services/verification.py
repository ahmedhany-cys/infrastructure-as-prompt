"""Post-deployment verification.

``live_checks`` reads configuration back from AWS APIs (read-only calls) after
a REAL deployment. ``simulated_checks`` runs the same assertions against the
simulated state and is always labelled as simulation; it never counts as
verification. Both return plain dicts: requirement, check, source, outcome,
detail.
"""

from __future__ import annotations

from typing import Any


def _check(requirement: str, check: str, source: str, ok: bool | None, detail: str) -> dict[str, Any]:
    return {
        "requirement": requirement,
        "check": check,
        "source": source,
        "outcome": "error" if ok is None else ("pass" if ok else "fail"),
        "detail": detail,
    }


def _attrs(state: dict[str, Any], rtype: str) -> list[dict[str, Any]]:
    out = []
    for res in state.get("resources", []):
        if res.get("type") == rtype and res.get("mode") == "managed":
            out += [i.get("attributes") or {} for i in res.get("instances", [])]
    return out


def simulated_checks(state: dict[str, Any]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for db in _attrs(state, "aws_db_instance"):
        checks.append(
            _check(
                "REQ-SEC-001",
                "Database not publicly accessible",
                "simulated-state:aws_db_instance",
                db.get("publicly_accessible") is False,
                f"publicly_accessible={db.get('publicly_accessible')}",
            )
        )
        checks.append(
            _check(
                "REQ-SEC-002",
                "Database storage encrypted",
                "simulated-state:aws_db_instance",
                db.get("storage_encrypted") is True,
                f"storage_encrypted={db.get('storage_encrypted')}",
            )
        )
    for blk in _attrs(state, "aws_s3_bucket_public_access_block"):
        ok = all(blk.get(k) is True for k in ("block_public_acls", "block_public_policy", "ignore_public_acls", "restrict_public_buckets"))
        checks.append(
            _check(
                "REQ-SEC-008",
                "Log bucket public access blocked",
                "simulated-state:aws_s3_bucket_public_access_block",
                ok,
                f"all four settings true: {ok}",
            )
        )
    for trail in _attrs(state, "aws_cloudtrail"):
        checks.append(
            _check(
                "REQ-AUD-001",
                "CloudTrail logging",
                "simulated-state:aws_cloudtrail",
                trail.get("enable_logging") is True,
                f"enable_logging={trail.get('enable_logging')}",
            )
        )
    checks.append(
        _check("REQ-AVL-001", "Application health check", "simulation", None, "Not run: simulated resources have no endpoint to call.")
    )
    return checks


def live_checks(session: Any, outputs: dict[str, Any], state: dict[str, Any], http_get: Any | None = None) -> list[dict[str, Any]]:
    """Read-only AWS API checks after a real deployment. ``session`` is a boto3 Session."""
    checks: list[dict[str, Any]] = []
    for db in _attrs(state, "aws_db_instance"):
        ident = db.get("identifier")
        try:
            resp = session.client("rds").describe_db_instances(DBInstanceIdentifier=ident)
            inst = resp["DBInstances"][0]
            checks.append(
                _check(
                    "REQ-SEC-001",
                    "Database not publicly accessible",
                    "aws:rds:DescribeDBInstances",
                    inst.get("PubliclyAccessible") is False,
                    f"{ident}: PubliclyAccessible={inst.get('PubliclyAccessible')}",
                )
            )
            checks.append(
                _check(
                    "REQ-SEC-002",
                    "Database storage encrypted",
                    "aws:rds:DescribeDBInstances",
                    inst.get("StorageEncrypted") is True,
                    f"{ident}: StorageEncrypted={inst.get('StorageEncrypted')}",
                )
            )
            if "MultiAZ" in inst:
                checks.append(
                    _check(
                        "REQ-AVL-002",
                        "Database Multi-AZ",
                        "aws:rds:DescribeDBInstances",
                        inst.get("MultiAZ") is True,
                        f"{ident}: MultiAZ={inst.get('MultiAZ')}",
                    )
                )
        except Exception as exc:  # noqa: BLE001 - recorded as evidence of a failed check
            checks.append(
                _check(
                    "REQ-SEC-001",
                    "Database not publicly accessible",
                    "aws:rds:DescribeDBInstances",
                    None,
                    f"API error: {type(exc).__name__}",
                )
            )
    sg_ids = [sg.get("id") for sg in _attrs(state, "aws_security_group") if sg.get("id")]
    if sg_ids:
        try:
            rules = session.client("ec2").describe_security_group_rules(Filters=[{"Name": "group-id", "Values": sg_ids}])[
                "SecurityGroupRules"
            ]
            lb_sgs = {sg.get("id") for sg in _attrs(state, "aws_security_group") if str(sg.get("name", "")).endswith("-alb")}
            bad = [
                r
                for r in rules
                if not r.get("IsEgress")
                and r.get("CidrIpv4") in ("0.0.0.0/0",)
                and not (r.get("GroupId") in lb_sgs and r.get("FromPort") in (80, 443))
            ]
            checks.append(
                _check(
                    "REQ-SEC-004",
                    "No internet ingress except 80/443 on the load balancer",
                    "aws:ec2:DescribeSecurityGroupRules",
                    not bad,
                    f"{len(rules)} rules inspected; {len(bad)} unexpected internet ingress rule(s)",
                )
            )
        except Exception as exc:  # noqa: BLE001
            checks.append(
                _check(
                    "REQ-SEC-004", "Security group rules", "aws:ec2:DescribeSecurityGroupRules", None, f"API error: {type(exc).__name__}"
                )
            )
    for bucket in _attrs(state, "aws_s3_bucket"):
        name = bucket.get("bucket")
        try:
            cfg = session.client("s3").get_public_access_block(Bucket=name)["PublicAccessBlockConfiguration"]
            ok = all(cfg.get(k) for k in ("BlockPublicAcls", "BlockPublicPolicy", "IgnorePublicAcls", "RestrictPublicBuckets"))
            checks.append(_check("REQ-SEC-008", "Bucket public access blocked", "aws:s3:GetPublicAccessBlock", ok, f"{name}: {cfg}"))
        except Exception as exc:  # noqa: BLE001
            checks.append(
                _check(
                    "REQ-SEC-008", "Bucket public access blocked", "aws:s3:GetPublicAccessBlock", None, f"API error: {type(exc).__name__}"
                )
            )
    for trail in _attrs(state, "aws_cloudtrail"):
        try:
            status = session.client("cloudtrail").get_trail_status(Name=trail.get("arn") or trail.get("name"))
            checks.append(
                _check(
                    "REQ-AUD-001",
                    "CloudTrail is logging",
                    "aws:cloudtrail:GetTrailStatus",
                    status.get("IsLogging") is True,
                    f"IsLogging={status.get('IsLogging')}",
                )
            )
        except Exception as exc:  # noqa: BLE001
            checks.append(
                _check("REQ-AUD-001", "CloudTrail is logging", "aws:cloudtrail:GetTrailStatus", None, f"API error: {type(exc).__name__}")
            )
    dns = outputs.get("load_balancer_dns_name")
    if dns and http_get is not None:
        try:
            code = http_get(f"https://{dns}/health")
            checks.append(
                _check(
                    "REQ-AVL-001", "Application health endpoint", "http:GET /health", code == 200, f"HTTP {code} from https://{dns}/health"
                )
            )
        except Exception as exc:  # noqa: BLE001
            checks.append(
                _check(
                    "REQ-AVL-001",
                    "Application health endpoint",
                    "http:GET /health",
                    None,
                    f"Request failed ({type(exc).__name__}); certificate must match the ALB name or a DNS record must exist.",
                )
            )
    return checks
