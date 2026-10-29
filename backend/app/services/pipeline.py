"""Validation pipeline: requirements -> architecture -> Terraform -> fmt ->
init -> validate -> plan -> policy evaluation -> external scanners -> cost ->
plan review -> requirement statuses. Every step's real status is recorded;
unavailable tools are reported as unavailable, never as passed."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, cast

from app.config import Settings
from app.db import SessionLocal
from app.domain.findings import ExternalFinding, PipelineStep, PolicyResult, ScanSummary, StepStatus
from app.domain.requirements import RequirementStatus
from app.models import Plan, Project, ScanRun
from app.services import projects as P
from app.services import traceability
from app.services.operations import OpContext
from app.services.plan_review import review
from app.services.policy import engine, external
from app.services.terraform import safety
from app.services.terraform.runner import Terraform, ToolUnavailable
from app.services.terraform.workspace import Workspace, effective_files, file_sha256


def _now() -> datetime:
    return datetime.now(UTC)


class StepRecorder:
    def __init__(self, ctx: OpContext) -> None:
        self.ctx = ctx
        self.steps: list[PipelineStep] = []

    def add(self, name: str, status: str, summary: str, output: str = "", started: datetime | None = None) -> PipelineStep:
        step = PipelineStep(
            name=name,
            status=cast(StepStatus, status),
            summary=summary,
            output=output[-8000:],
            started_at=started or _now(),
            finished_at=_now(),
        )
        self.steps.append(step)
        self.ctx.log(f"{name}: {status} — {summary}")
        return step


def _validate_diagnostics(stdout: str) -> tuple[bool, str]:
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return False, "Could not parse terraform validate output."
    diags = data.get("diagnostics") or []
    lines = []
    for d in diags:
        rng = d.get("range") or {}
        lines.append(
            f"{d.get('severity', '').upper()}: {d.get('summary')} ({rng.get('filename', '?')}:{(rng.get('start') or {}).get('line', '?')}) {d.get('detail', '')}".strip()
        )
    return bool(data.get("valid")), "\n".join(lines)


def run_pipeline(ctx: OpContext, settings: Settings) -> dict[str, Any]:
    rec = StepRecorder(ctx)
    with SessionLocal() as db:
        project = db.get(Project, ctx.project_id)
        assert project is not None
        mode = P.project_settings(project)["deployment_mode"]
        profile = P.project_settings(project)["policy_profile"]
        spec = P.spec(project)
        arch = P.arch(project)
        option = P.selected_option(project)
        generated = dict(project.generated_files or {})
        overrides = dict(project.file_overrides or {})
        revision = project.config_revision
        tfvars = P.tfvars(project, settings, mode)

    results: list[PolicyResult] | None = None
    external_findings: list[ExternalFinding] = []
    summary = ScanSummary()
    plan_json: dict[str, Any] | None = None
    blocked_reason: str | None = None
    plan_id: str | None = None
    config_sha = ""

    def finish(status: str) -> dict[str, Any]:
        nonlocal spec
        with SessionLocal() as db:
            project = db.get(Project, ctx.project_id)
            assert project is not None
            scan = ScanRun(
                project_id=project.id,
                config_revision=revision,
                config_sha256=config_sha or "-",
                status=status,
                steps=[s.model_dump(mode="json") for s in rec.steps],
                policy_results=[r.model_dump(mode="json") for r in (results or [])],
                external_findings=[f.model_dump(mode="json") for f in external_findings],
                summary=summary.model_dump(mode="json"),
            )
            db.add(scan)
            db.flush()
            if spec is not None:
                spec = traceability.apply_scan(spec, results, scan.id, blocked_reason, option)
                project.requirements = spec.model_dump(mode="json")
            if plan_id:
                plan = db.get(Plan, plan_id)
                if plan:
                    plan.scan_id = scan.id
                    if summary.blocking:
                        plan.status = "rejected"
                        plan.blocked_reason = summary.blocking_reason
            project.status = {"passed": "validated", "blocked": "blocked", "failed": "validation_failed"}[status]
            db.commit()
            return {"scan_id": scan.id, "status": status, "plan_id": plan_id, "summary": summary.model_dump(mode="json")}

    # 1. Requirements
    if spec is None:
        rec.add("Validate requirements specification", "failed", "No compiled requirements. Complete the interview first.")
        blocked_reason = "Requirements have not been compiled."
        return finish("failed")
    open_items = [
        r.id for r in spec.requirements if r.status != RequirementStatus.not_applicable and not r.policies and r.id != "REQ-CST-001"
    ]
    rec.add(
        "Validate requirements specification",
        "passed",
        f"{len(spec.requirements)} requirements (revision {spec.revision}); {len(spec.assumptions)} assumptions; {len(spec.unresolved)} unresolved items"
        + (f"; without automated checks: {', '.join(open_items)}" if open_items else ""),
    )
    # 2. Architecture
    if arch is None or option is None or not generated:
        rec.add("Validate architecture specification", "failed", "No architecture option selected or Terraform not generated.")
        blocked_reason = "Architecture not selected / Terraform not generated."
        return finish("failed")
    if arch.requirements_revision != spec.revision:
        rec.add(
            "Validate architecture specification", "failed", "Architecture was produced from an older requirements revision; regenerate it."
        )
        blocked_reason = "Architecture is stale relative to the requirements."
        return finish("failed")
    rec.add(
        "Validate architecture specification",
        "passed",
        f"Option '{option.name}' with {len(option.components)} components; estimated ${option.cost.total_monthly_usd:,.0f}/month.",
    )
    ctx.check_cancel()

    # 3. Write configuration
    ws = Workspace(settings, ctx.project_id, mode)
    files = effective_files(generated, overrides)
    try:
        _, config_sha = ws.write(files, tfvars)
    except ValueError as exc:
        rec.add("Write configuration", "failed", str(exc))
        blocked_reason = str(exc)
        return finish("failed")
    rec.add(
        "Write configuration",
        "passed",
        f"{sum(1 for f in files if f.endswith('.tf'))} Terraform files written ({'with ' + str(len(overrides)) + ' manual edit(s)' if overrides else 'no manual edits'}); config sha256 {config_sha[:12]}…",
    )

    try:
        tf = Terraform(settings, ws.dir, mode, ctx.cancel)
    except ToolUnavailable as exc:
        for name in ("terraform fmt", "terraform init", "terraform validate", "terraform plan", "Policy evaluation"):
            rec.add(name, "unavailable", str(exc))
        blocked_reason = "Terraform is not installed, so the configuration could not be validated or planned."
        return finish("failed")

    # 3b. Execution-safety gate: nothing that could run code or read server files may reach init/plan.
    violations = safety.precheck(files)
    if violations:
        rec.add(
            "Configuration safety gate",
            "failed",
            f"{len(violations)} disallowed construct(s); Terraform was not run.",
            "\n".join(violations),
        )
        blocked_reason = "Configuration contains constructs that are not allowed to run on this server."
        return finish("failed")
    rec.add(
        "Configuration safety gate", "passed", "No provisioners, external/http data sources, modules, backends or filesystem functions."
    )

    # 4. fmt
    started = _now()
    res = tf("fmt", "-check", "-diff", "-no-color")
    rec.add(
        "terraform fmt",
        "passed" if res.ok else "warning",
        "Formatting is canonical." if res.ok else "Some files are not canonically formatted (not blocking).",
        res.combined(4000),
        started,
    )
    ctx.check_cancel()

    # 5. init
    started = _now()
    res = tf("init", "-input=false", "-no-color", timeout=600)
    if not res.ok:
        rec.add("terraform init", "failed", "Initialization failed (provider download or configuration error).", res.combined(), started)
        blocked_reason = "terraform init failed."
        return finish("failed")
    rec.add("terraform init", "passed", "Providers installed from the lock file / plugin cache (no upgrade).", res.combined(1500), started)
    prov = tf("providers", "-no-color")
    bad = safety.provider_violations(prov.stdout) if prov.ok else ["could not list providers"]
    if bad:
        rec.add("Provider allow-list", "failed", f"Providers outside the allow-list: {', '.join(bad)}", prov.combined(2000))
        blocked_reason = "Configuration requires providers that are not allowed."
        return finish("failed")
    ctx.check_cancel()

    # 6. validate
    started = _now()
    res = tf("validate", "-json", "-no-color")
    valid, diag = _validate_diagnostics(res.stdout)
    if not valid:
        rec.add("terraform validate", "failed", "Configuration is invalid.", diag or res.combined(), started)
        blocked_reason = "terraform validate failed."
        return finish("failed")
    rec.add(
        "terraform validate",
        "passed",
        "Configuration is syntactically valid and internally consistent." + (" (with warnings)" if diag else ""),
        diag,
        started,
    )
    ctx.check_cancel()

    # 7. plan
    with SessionLocal() as db:
        plan_row = Plan(project_id=ctx.project_id, kind="apply", mode=mode, config_sha256=config_sha, plan_sha256="", plan_path="")
        db.add(plan_row)
        db.commit()
        plan_id = plan_row.id
    plan_file = ws.plan_path(plan_id)
    started = _now()
    plan_args = ["plan", "-input=false", "-no-color", "-lock-timeout=30s", f"-out={plan_file}"]
    if mode == "simulation":
        plan_args.append("-refresh=false")  # simulated state has nothing real to refresh
    res = tf(*plan_args, timeout=900)
    if not res.ok:
        rec.add("terraform plan", "failed", "Plan failed.", res.combined(), started)
        blocked_reason = "terraform plan failed."
        with SessionLocal() as db:
            p = db.get(Plan, plan_id)
            if p:
                p.status = "failed"
                db.commit()
        return finish("failed")
    show = tf("show", "-json", "-no-color", str(plan_file))
    if not show.ok:
        rec.add("terraform plan", "failed", "Could not read the saved plan.", show.combined(), started)
        blocked_reason = "terraform show failed."
        return finish("failed")
    plan_json = json.loads(show.stdout)
    rec.add(
        "terraform plan",
        "passed",
        ("SIMULATION plan (placeholder credentials, no AWS API calls). " if mode == "simulation" else "") + f"Saved plan {plan_id[:8]}.",
        "\n".join(line for line in res.stdout.splitlines() if line.startswith(("Plan:", "No changes", "  #")))[-6000:],
        started,
    )
    ctx.check_cancel()

    # 8. Policies
    started = _now()
    pctx = engine.context_from_requirements(spec)
    results = engine.evaluate(plan_json, pctx, spec)
    ctx.check_cancel()

    # 9-10. External scanners (advisory)
    step, found = external.run_checkov(settings, ws.dir, ctx.cancel)
    rec.steps.append(step)
    ctx.log(f"{step.name}: {step.status} — {step.summary}")
    external_findings += found
    ctx.check_cancel()
    step, found = external.run_trivy(settings, ws.dir, ctx.cancel)
    rec.steps.append(step)
    ctx.log(f"{step.name}: {step.status} — {step.summary}")
    external_findings += found

    summary = engine.summarize(results, external_findings, profile)
    fails = [r for r in results if r.outcome == "fail"]
    rec.add(
        "Policy evaluation",
        "failed" if summary.blocking else ("warning" if fails else "passed"),
        (summary.blocking_reason if summary.blocking else f"{summary.passed} checks passed, {len(fails)} non-blocking finding(s)")
        + f" (profile: {profile}).",
        "\n".join(f"[{r.severity.value.upper()}] {r.policy_id} {r.resource or ''}: {r.message}" for r in fails),
        started,
    )

    # 11. Cost
    rec.add(
        "Cost estimate",
        "passed" if option.cost.within_budget is not False else "warning",
        f"~${option.cost.total_monthly_usd:,.0f}/month (approximate, static price table). {option.cost.budget_note}",
    )

    # 12. Plan review
    plan_review = review(
        plan_json, cost_note=f"Selected option '{option.name}' is estimated at ~${option.cost.total_monthly_usd:,.0f}/month."
    )
    rec.add("Plan review", "passed", plan_review.headline + (" — includes DESTRUCTIVE changes." if plan_review.destructive else ""))
    with SessionLocal() as db:
        p = db.get(Plan, plan_id)
        assert p is not None
        p.plan_path = str(plan_file)
        p.plan_sha256 = file_sha256(plan_file)
        p.review = plan_review.model_dump(mode="json")
        p.status = "pending_review"
        for older in db.query(Plan).filter(
            Plan.project_id == ctx.project_id, Plan.id != plan_id, Plan.status.in_(["pending_review", "approved"])
        ):
            older.status = "superseded"
        db.commit()
    return finish("blocked" if summary.blocking else "passed")
