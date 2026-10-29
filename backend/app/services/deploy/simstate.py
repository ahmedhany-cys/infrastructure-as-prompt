"""Builds a Terraform state file for SIMULATED deployments.

After a simulated apply, the planned values are turned into a state file with
placeholder identifiers (clearly prefixed ``sim-``). Later plans run with
``-refresh=false`` against this state, so Terraform's real diff logic decides
what would be updated, replaced or destroyed — without any AWS API calls.
The state never describes real infrastructure and is kept separate from any
real-mode workspace.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any

PROVIDER = 'provider["registry.terraform.io/hashicorp/aws"]'
# Only identifier-like computed attributes (the ones other resources reference)
# get placeholder values; other unknown computed attributes stay null so the
# provider does not see spurious differences.
REF_ATTR = re.compile(r"^(id|arn|name|dns_name|zone_id|address|endpoint|owner_id|arn_suffix|latest_version|.*_id|.*_arn|.*_ids)$")


# AWS-style identifier prefixes; the provider validates some of these formats.
ID_PREFIX = {
    "aws_vpc": "vpc-",
    "aws_subnet": "subnet-",
    "aws_security_group": "sg-",
    "aws_default_security_group": "sg-",
    "aws_internet_gateway": "igw-",
    "aws_nat_gateway": "nat-",
    "aws_eip": "eipalloc-",
    "aws_route_table": "rtb-",
    "aws_route_table_association": "rtbassoc-",
    "aws_launch_template": "lt-",
    "aws_flow_log": "fl-",
    "aws_vpc_security_group_ingress_rule": "sgr-",
    "aws_vpc_security_group_egress_rule": "sgr-",
    "aws_instance": "i-",
}


def _fake_string(attr: str, rtype: str, address: str, region: str) -> str:
    h = hashlib.sha256(f"{address}:{attr}".encode()).hexdigest()[:17]
    svc = rtype.removeprefix("aws_").split("_")[0]
    if attr == "id" and rtype in ID_PREFIX:
        return ID_PREFIX[rtype] + h
    if attr == "allocation_id":
        return "eipalloc-" + h
    if attr == "arn" or attr.endswith("_arn"):
        return f"arn:aws:{svc}:{region}:000000000000:sim/{rtype}/{h}"
    if attr in ("dns_name", "address", "endpoint", "public_dns", "private_dns"):
        return f"sim-{h}.{region}.simulated.invalid"
    if attr.endswith("ip") or attr in ("public_ip", "private_ip"):
        return "192.0.2.10"
    if attr == "owner_id" or attr.endswith("account_id"):
        return "000000000000"
    return f"sim-{svc}-{h}"


def _fake(typ: Any, attr: str, rtype: str, address: str, region: str) -> Any:
    if typ == "string":
        return _fake_string(attr, rtype, address, region)
    if typ == "number":
        return 1
    if typ == "bool":
        return False
    if isinstance(typ, list):
        kind = typ[0]
        if kind in ("list", "set"):
            elem = typ[1]
            # Computed nested objects (e.g. master_user_secret) get one element so
            # expressions such as ``x[0].secret_arn`` remain valid.
            if isinstance(elem, list) and elem and elem[0] == "object":
                return [_fake(elem, attr, rtype, address, region)]
            return []
        if kind == "map":
            return {}
        if kind == "object":
            return {k: (_fake(v, k, rtype, address, region) if REF_ATTR.match(k) else None) for k, v in typ[1].items()}
    return None


def _fake_block(block: dict[str, Any], rtype: str, address: str, region: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, a in (block.get("attributes") or {}).items():
        out[name] = _fake(a.get("type"), name, rtype, address, region) if a.get("computed") and REF_ATTR.match(name) else None
    for name, b in (block.get("block_types") or {}).items():
        out[name] = [] if b.get("nesting_mode") in ("list", "set") else None
    return out


def _fill(values: dict[str, Any], unknown: dict[str, Any], block: dict[str, Any], rtype: str, address: str, region: str) -> None:
    attrs = block.get("attributes") or {}
    blocks = block.get("block_types") or {}
    for name, flag in unknown.items():
        if flag is True:
            if name in attrs:
                typ = attrs[name].get("type")
                collection = isinstance(typ, list) and typ[0] in ("list", "set", "map")
                values[name] = _fake(typ, name, rtype, address, region) if (REF_ATTR.match(name) or collection) else None
            elif name in blocks:
                values[name] = [_fake_block(blocks[name]["block"], rtype, address, region)]
        elif isinstance(flag, list) and isinstance(values.get(name), list):
            sub = blocks.get(name, {}).get("block")
            for i, item_flag in enumerate(flag):
                if i < len(values[name]) and isinstance(item_flag, dict) and isinstance(values[name][i], dict) and sub:
                    _fill(values[name][i], item_flag, sub, rtype, address, region)
        elif isinstance(flag, dict) and isinstance(values.get(name), dict):
            sub = blocks.get(name, {}).get("block")
            if sub:
                _fill(values[name], flag, sub, rtype, address, region)


def _sensitive_paths(marks: Any, prefix: list[dict[str, Any]] | None = None) -> list[list[dict[str, Any]]]:
    """Convert plan ``sensitive_values`` marks into state ``sensitive_attributes`` paths."""
    prefix = prefix or []
    out: list[list[dict[str, Any]]] = []
    if marks is True:
        return [prefix]
    if isinstance(marks, dict):
        for k, v in marks.items():
            out += _sensitive_paths(v, [*prefix, {"type": "get_attr", "value": k}])
    elif isinstance(marks, list):
        for i, v in enumerate(marks):
            out += _sensitive_paths(v, [*prefix, {"type": "index", "value": {"value": i, "type": "number"}}])
    return out


def build_state(
    plan: dict[str, Any], schema: dict[str, Any], region: str, previous: dict[str, Any] | None = None
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Return (state document, list of simulated resource records)."""
    unknown = {rc["address"]: (rc.get("change") or {}).get("after_unknown") or {} for rc in plan.get("resource_changes", [])}
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    records: list[dict[str, Any]] = []
    for res in (plan.get("planned_values") or {}).get("root_module", {}).get("resources", []):
        if res.get("mode") != "managed":
            continue
        rschema = schema.get(res["type"])
        if rschema is None:
            continue
        values = json.loads(json.dumps(res.get("values") or {}))
        _fill(values, unknown.get(res["address"], {}), rschema["block"], res["type"], res["address"], region)
        key = (res["type"], res["name"])
        entry = grouped.setdefault(
            key, {"mode": "managed", "type": res["type"], "name": res["name"], "provider": PROVIDER, "instances": []}
        )
        inst: dict[str, Any] = {
            "schema_version": rschema.get("version", 0),
            "attributes": values,
            "sensitive_attributes": _sensitive_paths(res.get("sensitive_values") or {}),
            "dependencies": [],
        }
        if "index" in res:
            inst["index_key"] = res["index"]
        entry["instances"].append(inst)
        records.append(
            {"address": res["address"], "type": res["type"], "id": values.get("id"), "arn": values.get("arn"), "simulated": True}
        )
    state = {
        "version": 4,
        "terraform_version": "1.6.0",
        "serial": (previous or {}).get("serial", 0) + 1,
        "lineage": (previous or {}).get("lineage") or str(uuid.uuid4()),
        "outputs": {},
        "resources": list(grouped.values()),
        "check_results": None,
    }
    return state, records


def schema_index(schema_json: dict[str, Any]) -> dict[str, Any]:
    ps = schema_json.get("provider_schemas", {})
    aws: dict[str, Any] = next((v for k, v in ps.items() if k.endswith("hashicorp/aws")), {})
    return aws.get("resource_schemas", {})
