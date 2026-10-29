"""Evidence report (JSON and Markdown)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.config import Settings
from app.models import AuditLog, Deployment, Plan, Project, ScanRun
from app.services import projects as P

STAGES = [
    ("configuration_validated", "Configuration validated locally (terraform validate)"),
    ("policies_passed", "Deterministic policies pass on the Terraform plan"),
    ("plan_reviewed", "Plan reviewed and approved"),
    ("deployment_attempted", "Deployment attempted"),
    ("deployment_succeeded", "Deployment succeeded"),
    ("resources_inspected", "Resource configuration inspected in a live AWS account"),
]


def build(db: Session, project: Project, settings: Settings) -> dict[str, Any]:
    spec = P.spec(project)
    option = P.selected_option(project)
    scan = db.query(ScanRun).filter(ScanRun.project_id == project.id).order_by(ScanRun.created_at.desc()).first()
    plans = db.query(Plan).filter(Plan.project_id == project.id).order_by(Plan.created_at.desc()).limit(10).all()
    deps = db.query(Deployment).filter(Deployment.project_id == project.id).order_by(Deployment.started_at.desc()).limit(10).all()
    audits = db.query(AuditLog).filter(AuditLog.project_id == project.id).order_by(AuditLog.at.desc()).limit(50).all()
    last_dep = deps[0] if deps else None
    steps = {s["name"]: s["status"] for s in (scan.steps if scan else [])}
    stages = {
        "configuration_validated": steps.get("terraform validate") == "passed",
        "policies_passed": bool(scan)
        and steps.get("Policy evaluation") in ("passed", "warning")
        and not ((scan.summary if scan else None) or {}).get("blocking"),
        "plan_reviewed": any(p.status in ("approved", "applied") for p in plans),
        "deployment_attempted": bool(last_dep),
        "deployment_succeeded": bool(last_dep and last_dep.status == "succeeded"),
        "resources_inspected": bool(last_dep and last_dep.mode == "aws" and last_dep.verification),
    }
    simulated = bool(last_dep and last_dep.mode == "simulation")
    reqs = spec.model_dump(mode="json")["requirements"] if spec else []
    counts: dict[str, int] = {}
    for r in reqs:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    limitations = [
        "Policy checks are static analysis of the Terraform plan; they do not prove the running environment is secure.",
        "Cost figures are approximate estimates from a static price table, not AWS billing data.",
        "Checkov and Trivy findings are advisory and do not gate deployment.",
        "References through Terraform locals or child modules are not resolved by the policy engine.",
    ]
    if simulated or not deps:
        limitations.insert(
            0,
            "No real AWS deployment has been performed for this project. Deployment results are SIMULATED and are not evidence of real infrastructure."
            if simulated
            else "No deployment has been performed for this project.",
        )
    if not stages["resources_inspected"]:
        limitations.append(
            "No requirement has been verified against a live AWS environment (highest verification level reached: static configuration analysis)."
        )
    return {
        "report_version": "1.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "generator": "Infrastructure as Prompt",
        "project": {
            "id": project.id,
            "name": project.name,
            "description": project.description,
            "status": project.status,
            "settings": P.project_settings(project),
        },
        "deployment_mode": P.project_settings(project)["deployment_mode"],
        "simulated": simulated,
        "lifecycle_stages": [{"id": k, "label": label, "reached": stages[k]} for k, label in STAGES],
        "requirements_summary": counts,
        "requirements": reqs,
        "assumptions": spec.model_dump(mode="json")["assumptions"] if spec else [],
        "unresolved": spec.unresolved if spec else [],
        "architecture": option.model_dump(mode="json") if option else None,
        "latest_scan": None
        if not scan
        else {
            "id": scan.id,
            "at": scan.created_at.isoformat(),
            "status": scan.status,
            "config_sha256": scan.config_sha256,
            "summary": scan.summary,
            "steps": scan.steps,
            "policy_results": scan.policy_results,
            "external_findings": scan.external_findings,
        },
        "plans": [
            {
                "id": p.id,
                "kind": p.kind,
                "mode": p.mode,
                "status": p.status,
                "created_at": p.created_at.isoformat(),
                "plan_sha256": p.plan_sha256,
                "config_sha256": p.config_sha256,
                "headline": (p.review or {}).get("headline"),
                "approval": p.approval,
            }
            for p in plans
        ],
        "deployments": [
            {
                "id": d.id,
                "kind": d.kind,
                "mode": d.mode,
                "status": d.status,
                "started_at": d.started_at.isoformat(),
                "finished_at": d.finished_at.isoformat() if d.finished_at else None,
                "resources": d.resources,
                "verification": d.verification,
            }
            for d in deps
        ],
        "audit_log": [{"at": a.at.isoformat(), "action": a.action, "detail": a.detail} for a in audits],
        "tooling": {
            "terraform": settings.terraform_path() is not None,
            "checkov": settings.checkov_argv() is not None,
            "trivy": settings.trivy_path() is not None,
        },
        "limitations": limitations,
    }


def to_markdown(rep: dict[str, Any]) -> str:
    L: list[str] = []
    p = rep["project"]
    L.append(f"# Evidence report — {p['name']}")
    L.append("")
    L.append(f"Generated {rep['generated_at']} by Infrastructure as Prompt. Deployment mode: **{rep['deployment_mode']}**.")
    if rep["simulated"]:
        L.append("")
        L.append("> **SIMULATION** — deployment results in this report come from the simulation adapter. No AWS resources were created.")
    L.append("")
    L.append("## Lifecycle")
    L.append("")
    for s in rep["lifecycle_stages"]:
        L.append(f"- [{'x' if s['reached'] else ' '}] {s['label']}")
    L.append("")
    L.append("## Requirements")
    L.append("")
    L.append("| ID | Requirement | Status | Evidence level | Policies | Reason |")
    L.append("|---|---|---|---|---|---|")
    for r in rep["requirements"]:
        L.append(
            f"| {r['id']} | {r['title']} | {r['status']} | {r['verification_level']} | {', '.join(r['policies']) or '—'} | {r['status_reason'].replace('|', '/')} |"
        )
    if rep["assumptions"]:
        L.append("")
        L.append("## Assumptions")
        L.append("")
        for a in rep["assumptions"]:
            L.append(f"- **{a['id']}** {a['statement']} _{a['reason']}_")
    if rep["unresolved"]:
        L.append("")
        L.append("## Unresolved items")
        L.append("")
        for u in rep["unresolved"]:
            L.append(f"- {u}")
    arch = rep["architecture"]
    if arch:
        L.append("")
        L.append(f"## Architecture — {arch['name']}")
        L.append("")
        L.append(arch["summary"])
        L.append("")
        L.append(f"Estimated cost: ~${arch['cost']['total_monthly_usd']:,.0f}/month (approximate). {arch['cost']['budget_note']}")
        L.append("")
        for c in arch["components"]:
            L.append(f"- **{c['label']}** — {c['rationale']} ({', '.join(c['terraform_addresses']) or 'n/a'})")
    scan = rep["latest_scan"]
    if scan:
        L.append("")
        L.append(f"## Latest validation ({scan['status']}, config `{scan['config_sha256'][:12]}`)")
        L.append("")
        for s in scan["steps"]:
            L.append(f"- **{s['name']}**: {s['status']} — {s['summary']}")
        fails = [r for r in scan["policy_results"] if r["outcome"] == "fail"]
        L.append("")
        L.append(f"### Policy findings ({len(fails)})")
        L.append("")
        if not fails:
            L.append("No deterministic policy failures.")
        for r in fails:
            L.append(f"- **[{r['severity'].upper()}] {r['policy_id']}** `{r['resource']}` — {r['message']} Remediation: {r['remediation']}")
        if scan["external_findings"]:
            L.append("")
            L.append(f"### Advisory findings from external scanners ({len(scan['external_findings'])}, not gating)")
            L.append("")
            for f in scan["external_findings"][:40]:
                L.append(f"- {f['tool']} {f['rule_id']} ({f['severity']}) {f['resource'] or ''}: {f['title']}")
    if rep["plans"]:
        L.append("")
        L.append("## Plans")
        L.append("")
        for pl in rep["plans"]:
            L.append(f"- {pl['created_at']} {pl['kind']} plan `{pl['plan_sha256'][:12]}` ({pl['mode']}): {pl['status']} — {pl['headline']}")
    if rep["deployments"]:
        L.append("")
        L.append("## Deployments")
        L.append("")
        for d in rep["deployments"]:
            L.append(f"- {d['started_at']} {d['kind']} ({d['mode'].upper()}): {d['status']}, {len(d['resources'])} resources")
            for c in d["verification"]:
                L.append(f"  - {c['requirement']} {c['check']}: {c['outcome']} — {c['detail']} [{c['source']}]")
    L.append("")
    L.append("## Limitations")
    L.append("")
    for item in rep["limitations"]:
        L.append(f"- {item}")
    L.append("")
    return "\n".join(L)
