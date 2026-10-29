"""Terraform generator: renders a reviewed template set from the selected
architecture option. The generator is deterministic — the same specification
always produces byte-identical files — and never uses model output as code."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from app.domain.architecture import ArchitectureOption
from app.domain.requirements import RequirementsSpec, RequirementStatus

TEMPLATE_DIR = Path(__file__).parent / "templates"
_env = Environment(
    loader=FileSystemLoader(TEMPLATE_DIR),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=True,
    autoescape=False,  # noqa: S701 - output is HCL/Markdown, never rendered as HTML
)

TF_FILES = [
    "versions.tf",
    "providers.tf",
    "variables.tf",
    "network.tf",
    "security_groups.tf",
    "compute.tf",
    "load_balancer.tf",
    "database.tf",
    "storage.tf",
    "logging.tf",
    "monitoring.tf",
    "outputs.tf",
]
WAF_RULES = ["AWSManagedRulesCommonRuleSet", "AWSManagedRulesKnownBadInputsRuleSet", "AWSManagedRulesAmazonIpReputationList"]


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    if not s or not s[0].isalpha():
        s = "app-" + s
    return s[:20].strip("-") or "app"


def _req_labels(spec: RequirementsSpec) -> dict[str, str]:
    present = {r.id for r in spec.requirements if r.status != RequirementStatus.not_applicable}

    def pick(*ids: str) -> str:
        return ", ".join(i for i in ids if i in present)

    return {
        "default_sg": pick("REQ-SEC-004") or "REQ-SEC-004",
        "db_private": pick("REQ-SEC-001"),
        "flow_logs": pick("REQ-AUD-002") or "network logging",
        "app_via_lb": pick("REQ-NET-001"),
        "db_sg": pick("REQ-SEC-001"),
        "no_admin_exposure": pick("REQ-SEC-004"),
        "imds": pick("REQ-SEC-007"),
        "least_privilege": pick("REQ-SEC-005"),
        "app_avail": pick("REQ-AVL-001"),
        "scaling": pick("REQ-PRF-001"),
        "tls": pick("REQ-SEC-003"),
        "alb_logs": pick("REQ-AUD-002"),
        "waf": pick("REQ-SEC-009"),
        "encrypt_rest": pick("REQ-SEC-002"),
        "secrets": pick("REQ-SEC-006"),
        "tls_db": pick("REQ-SEC-003"),
        "db_ha": pick("REQ-AVL-002"),
        "backups": pick("REQ-AVL-003"),
        "deletion": pick("REQ-OPS-001"),
        "log_bucket": pick("REQ-SEC-008"),
        "audit": pick("REQ-AUD-001"),
        "uploads": pick("REQ-SEC-010") or "private file storage",
        "alerts": pick("REQ-OPS-003") or "alerting",
        "schedule": pick("REQ-CST-002") or "Off-hours schedule",
    }


def generate(project_id: str, project_name: str, spec: RequirementsSpec, option: ArchitectureOption) -> dict[str, str]:
    p = option.params
    regions = p.allowed_regions or ["us-east-1", "us-east-2", "us-west-2", "eu-west-1", "eu-west-2", "eu-central-1"]
    if p.region not in regions:
        regions = [p.region, *regions]
    ctx = {
        "project_id": project_id,
        "project_name": project_name,
        "slug": slugify(project_name),
        "p": p,
        "db": p.db_enabled,
        "ssh": p.admin_access == "ssh" and bool(p.admin_cidr),
        "req": _req_labels(spec),
        "allowed_regions_hcl": json.dumps(regions),
        "allowed_regions_text": ", ".join(regions),
        "azs_hcl": json.dumps(p.availability_zones),
        "waf_rules": WAF_RULES,
    }
    files: dict[str, str] = {}
    for name in TF_FILES:
        if (
            (name == "database.tf" and not p.db_enabled)
            or (name == "storage.tf" and not p.uploads_bucket)
            or (name == "monitoring.tf" and not p.alerts)
        ):
            continue
        files[name] = _env.get_template(f"{name}.j2").render(**ctx)
    files["terraform.tfvars.example"] = _env.get_template("terraform.tfvars.example.j2").render(**ctx)
    files["README.md"] = _env.get_template("README.md.j2").render(
        project_name=project_name,
        generated_at=datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        requirements_revision=spec.revision,
        option_name=option.name,
        components=[c for c in option.components if c.kind not in ("users", "account", "region")],
        cost=option.cost,
        requirements=[r for r in spec.requirements if r.status != RequirementStatus.not_applicable],
        https=p.https,
        region=p.region,
        deletion_protection=p.deletion_protection,
    )
    files["traceability.json"] = (
        json.dumps(
            {
                "project_id": project_id,
                "requirements_revision": spec.revision,
                "architecture_option": option.id,
                "requirements": [
                    {"id": r.id, "title": r.title, "policies": r.policies, "resources": r.resources, "decisions": r.decisions}
                    for r in spec.requirements
                ],
                "components": [
                    {"id": c.id, "label": c.label, "terraform": c.terraform_addresses, "requirements": c.requirements}
                    for c in option.components
                ],
            },
            indent=2,
        )
        + "\n"
    )
    return files


def format_files(files: dict[str, str], fmt) -> dict[str, str]:  # type: ignore[no-untyped-def]
    """Canonicalise .tf files with ``terraform fmt`` when available."""
    out = dict(files)
    for name, text in files.items():
        if name.endswith(".tf"):
            formatted = fmt(text)
            if formatted is not None:
                out[name] = formatted
    return out
