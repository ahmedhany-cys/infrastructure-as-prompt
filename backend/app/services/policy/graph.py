"""Normalised resource graph built from ``terraform show -json <planfile>``.

Planned values give attribute values; the ``configuration`` section gives the
reference graph (which security group a rule belongs to, which subnets a
database uses), because many IDs are unknown until apply.

Limitations (documented in docs/security-model.md): references that pass
through ``locals`` or child modules are not resolved; the generator therefore
references resources directly in security-relevant attributes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_INDEX_RE = re.compile(r"\[[^\]]*\]")


def base_address(address: str) -> str:
    """``aws_subnet.app[0]`` -> ``aws_subnet.app``; ``aws_sg.a.id`` -> ``aws_sg.a``."""
    addr = _INDEX_RE.sub("", address)
    parts = addr.split(".")
    if parts[0] == "data" and len(parts) >= 3:
        return ".".join(parts[:3])
    if parts[0] in {"var", "local", "module", "each", "count", "path", "terraform", "self"}:
        return ".".join(parts[:2])
    return ".".join(parts[:2])


@dataclass
class Resource:
    address: str
    base: str
    type: str
    name: str
    values: dict[str, Any]
    unknown: dict[str, Any] = field(default_factory=dict)
    refs: dict[str, set[str]] = field(default_factory=dict)

    def get(self, path: str, default: Any = None) -> Any:
        cur: Any = self.values
        for part in path.split("."):
            if isinstance(cur, list):
                if not cur:
                    return default
                cur = cur[0]
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return cur

    def is_unknown(self, attr: str) -> bool:
        return bool(self.unknown.get(attr))

    def refs_for(self, *paths: str) -> set[str]:
        out: set[str] = set()
        for path in paths:
            for key, val in self.refs.items():
                if key == path or key.startswith(path + "."):
                    out |= val
        return out

    def all_refs(self) -> set[str]:
        out: set[str] = set()
        for v in self.refs.values():
            out |= v
        return out


@dataclass
class ResourceChangeInfo:
    address: str
    type: str
    name: str
    actions: list[str]
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    after_unknown: dict[str, Any]
    replace_paths: list[Any]


@dataclass
class PlanGraph:
    resources: list[Resource]
    changes: list[ResourceChangeInfo]
    variables: dict[str, Any]
    provider_region: str | None

    def of_type(self, *types: str) -> list[Resource]:
        return [r for r in self.resources if r.type in types]

    def by_base(self, base: str) -> list[Resource]:
        return [r for r in self.resources if r.base == base]

    def referencing(self, target_base: str, *types: str) -> list[Resource]:
        """Resources of ``types`` whose configuration references ``target_base``."""
        return [r for r in self.of_type(*types) if target_base in r.all_refs()]


def _flatten_expressions(expr: Any, prefix: str, out: dict[str, set[str]]) -> None:
    if isinstance(expr, dict):
        if "references" in expr and isinstance(expr["references"], list):
            refs = {base_address(ref) for ref in expr["references"]}
            out.setdefault(prefix, set()).update(refs)
            return
        if "constant_value" in expr:
            return
        for key, val in expr.items():
            _flatten_expressions(val, f"{prefix}.{key}" if prefix else key, out)
    elif isinstance(expr, list):
        for item in expr:
            _flatten_expressions(item, prefix, out)


def _walk_modules(module: dict[str, Any] | None):  # type: ignore[no-untyped-def]
    if not module:
        return
    yield from module.get("resources", [])
    for child in module.get("child_modules", []):
        yield from _walk_modules(child)


def build_graph(plan: dict[str, Any]) -> PlanGraph:
    config_root = (plan.get("configuration") or {}).get("root_module") or {}
    config_refs: dict[str, dict[str, set[str]]] = {}
    for res in config_root.get("resources", []):
        refs: dict[str, set[str]] = {}
        _flatten_expressions(res.get("expressions", {}), "", refs)
        config_refs[res["address"]] = refs

    unknown_by_addr: dict[str, dict[str, Any]] = {}
    changes: list[ResourceChangeInfo] = []
    for rc in plan.get("resource_changes", []):
        ch = rc.get("change", {})
        unknown_by_addr[rc["address"]] = ch.get("after_unknown") or {}
        if rc.get("mode") == "data":
            continue
        changes.append(
            ResourceChangeInfo(
                address=rc["address"],
                type=rc["type"],
                name=rc["name"],
                actions=list(ch.get("actions", [])),
                before=ch.get("before"),
                after=ch.get("after"),
                after_unknown=ch.get("after_unknown") or {},
                replace_paths=ch.get("replace_paths") or [],
            )
        )

    resources: list[Resource] = []
    for res in _walk_modules((plan.get("planned_values") or {}).get("root_module")):
        if res.get("mode") != "managed":
            continue
        base = base_address(res["address"])
        resources.append(
            Resource(
                address=res["address"],
                base=base,
                type=res["type"],
                name=res["name"],
                values=res.get("values") or {},
                unknown=unknown_by_addr.get(res["address"], {}),
                refs=config_refs.get(base, {}),
            )
        )

    variables = {k: v.get("value") for k, v in (plan.get("variables") or {}).items()}
    region: str | None = None
    provider_cfg = ((plan.get("configuration") or {}).get("provider_config") or {}).get("aws") or {}
    region_expr = (provider_cfg.get("expressions") or {}).get("region") or {}
    if "constant_value" in region_expr:
        region = region_expr["constant_value"]
    else:
        for ref in region_expr.get("references", []):
            if ref.startswith("var."):
                region = variables.get(ref.split(".", 1)[1])
                break
    return PlanGraph(resources=resources, changes=changes, variables=variables, provider_region=region)
