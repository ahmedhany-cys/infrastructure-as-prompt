"""Deployment workflow: approval gate, apply (simulated or real), teardown.

Invariants enforced here (and covered by tests):
- Only the latest plan of a kind can be approved or applied.
- Approval binds to the exact plan file hash and configuration hash; if either
  changes, the approval is void and a new plan + review is required.
- Plans with blocking policy findings cannot be approved.
- Destructive plans need a separate explicit acknowledgement and typed confirmation.
- Real AWS mode requires server-side opt-in, a configured expected account,
  and a typed confirmation of that account ID. Simulation never touches AWS.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.config import Settings
from app.db import SessionLocal
from app.models import Deployment, Plan, Project, ScanRun
from app.services import projects as P
from app.services import traceability, verification
from app.services.deploy.simstate import build_state, schema_index
from app.services.operations import OpContext
from app.services.plan_review import review
from app.services.terraform import safety
from app.services.terraform.runner import Terraform
from app.services.terraform.workspace import Workspace, effective_files, file_sha256


class DeployError(Exception):
    def __init__(self, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.status = status


def _now() -> datetime:
    return datetime.now(UTC)


def latest_plan(db: Session, project_id: str, kind: str) -> Plan | None:
    return db.query(Plan).filter(Plan.project_id == project_id, Plan.kind == kind).order_by(Plan.created_at.desc()).first()


def check_real_mode(settings: Settings) -> None:
    if not settings.allow_real_deploy:
        raise DeployError("Real AWS deployment is disabled on this server (IAP_ALLOW_REAL_DEPLOY is not set). Use simulation mode.", 403)
    if not settings.aws_expected_account_id:
        raise DeployError("IAP_AWS_EXPECTED_ACCOUNT_ID must be configured before real deployments.", 403)


def _verify_plan_integrity(db: Session, project: Project, plan: Plan, settings: Settings) -> None:
    latest = latest_plan(db, project.id, plan.kind)
    if latest is None or latest.id != plan.id:
        plan.status = "superseded"
        raise DeployError("A newer plan exists. Review the latest plan instead.")
    ws = Workspace(settings, project.id, plan.mode)
    if plan.kind == "apply":
        files = effective_files(project.generated_files or {}, project.file_overrides or {})
        current = ws.current_hash(files, P.tfvars(project, settings, plan.mode))
        if current != plan.config_sha256:
            plan.status = "superseded"
            raise DeployError(
                "The configuration changed after this plan was created. Run validation again to produce and review a new plan."
            )
    from pathlib import Path

    path = Path(plan.plan_path)
    if not path.exists() or file_sha256(path) != plan.plan_sha256:
        plan.status = "superseded"
        raise DeployError("The saved plan file is missing or was modified. A new plan and review are required.")
    if P.project_settings(project)["deployment_mode"] != plan.mode:
        raise DeployError("The project's deployment mode changed after this plan was created.")


def approve(db: Session, project: Project, plan_id: str, body: dict[str, Any], session_id: str, settings: Settings) -> Plan:
    plan = db.get(Plan, plan_id)
    if plan is None or plan.project_id != project.id:
        raise DeployError("Plan not found.", 404)
    if plan.status != "pending_review":
        raise DeployError(f"Plan is {plan.status}; only a plan pending review can be approved.")
    if body.get("plan_sha256") != plan.plan_sha256:
        raise DeployError("The plan you reviewed is not the current saved plan (hash mismatch). Reload and review again.")
    _verify_plan_integrity(db, project, plan, settings)
    if plan.kind == "apply":
        scan = db.get(ScanRun, plan.scan_id) if plan.scan_id else None
        if scan is None or scan.summary.get("blocking"):
            raise DeployError("This plan has blocking policy findings (or no completed scan) and cannot be approved.")
    destructive = bool((plan.review or {}).get("destructive"))
    if destructive:
        if not body.get("acknowledge_destructive"):
            raise DeployError("This plan destroys or replaces resources. Explicitly acknowledge the destructive changes.", 400)
        if (body.get("confirmation_text") or "").strip() != project.name:
            raise DeployError("Type the project name exactly to confirm the destructive changes.", 400)
    if plan.mode == "aws":
        check_real_mode(settings)
        if (body.get("account_confirmation") or "").strip() != settings.aws_expected_account_id:
            raise DeployError("Type the target AWS account ID to confirm a real deployment.", 400)
    plan.status = "approved"
    plan.approved_at = _now()
    plan.approval = {
        "session": session_id,
        "at": plan.approved_at.isoformat(),
        "plan_sha256": plan.plan_sha256,
        "config_sha256": plan.config_sha256,
        "destructive_acknowledged": destructive,
        "mode": plan.mode,
    }
    P.audit(
        db,
        "plan.approved",
        project.id,
        session_id,
        plan_id=plan.id,
        kind=plan.kind,
        mode=plan.mode,
        destructive=destructive,
        plan_sha256=plan.plan_sha256,
    )
    db.commit()
    return plan


def preflight_apply(db: Session, project: Project, plan_id: str, settings: Settings) -> Plan:
    plan = db.get(Plan, plan_id)
    if plan is None or plan.project_id != project.id:
        raise DeployError("Plan not found.", 404)
    if plan.status != "approved" or not plan.approval:
        raise DeployError("This plan has not been approved. Review and approve it first.", 403)
    if plan.approval.get("plan_sha256") != plan.plan_sha256 or plan.approval.get("config_sha256") != plan.config_sha256:
        raise DeployError("The approval does not match this plan. A new review is required.", 403)
    _verify_plan_integrity(db, project, plan, settings)
    if plan.mode == "aws":
        check_real_mode(settings)
    return plan


def _schema(tf: Terraform, ws: Workspace) -> dict[str, Any]:
    cache = ws.dir / ".provider-schema.json"
    lock = ws.lock_file() or ""
    if cache.exists():
        data = json.loads(cache.read_text())
        if data.get("lock") == lock:
            return data["schema"]
    res = tf("providers", "schema", "-json")
    if not res.ok:
        raise RuntimeError("Could not read provider schema for simulation: " + res.combined(500))
    schema = schema_index(json.loads(res.stdout))
    cache.write_text(json.dumps({"lock": lock, "schema": schema}))
    return schema


def run_apply(ctx: OpContext, settings: Settings, plan_id: str, session_id: str) -> dict[str, Any]:
    with SessionLocal() as db:
        project = db.get(Project, ctx.project_id)
        assert project is not None
        plan = preflight_apply(db, project, plan_id, settings)
        mode, kind, plan_path = plan.mode, plan.kind, plan.plan_path
        dep = Deployment(project_id=project.id, plan_id=plan.id, kind=kind, mode=mode, status="running")
        db.add(dep)
        P.audit(db, "deployment.started", project.id, session_id, plan_id=plan.id, kind=kind, mode=mode)
        db.commit()
        dep_id = dep.id
        selected = P.selected_option(project)
        region = selected.params.region if selected else "us-east-1"
    ws = Workspace(settings, ctx.project_id, mode)
    tf = Terraform(settings, ws.dir, mode, ctx.cancel)
    logs: list[str] = []

    def log(line: str) -> None:
        logs.append(line)
        ctx.log(line)

    try:
        if mode == "simulation":
            log("SIMULATION: no AWS API calls are made. Resource identifiers below are placeholders prefixed 'sim-'.")
            show = tf("show", "-json", "-no-color", plan_path)
            if not show.ok:
                raise RuntimeError("Could not read approved plan: " + show.combined(500))
            plan_json = json.loads(show.stdout)
            if kind == "destroy":
                if ws.state_path.exists():
                    ws.state_path.rename(ws.dir / f"terraform.tfstate.destroyed-{dep_id[:8]}")
                records: list[dict[str, Any]] = []
                state: dict[str, Any] = {"resources": []}
                log(f"Simulated teardown removed {len(plan_json.get('resource_changes') or [])} resources from simulated state.")
            else:
                schema = _schema(tf, ws)
                previous = json.loads(ws.state_path.read_text()) if ws.state_path.exists() else None
                state, records = build_state(plan_json, schema, region, previous)
                # Converge placeholder identifiers so later plans show only real changes.
                for round_no in range(1, 9):
                    ctx.check_cancel()
                    ws.state_path.write_text(json.dumps(state))
                    probe = ws.plans_dir / f"converge-{dep_id[:8]}.tfplan"
                    res = tf("plan", "-input=false", "-no-color", "-refresh=false", f"-out={probe}")
                    if not res.ok:
                        raise RuntimeError("Simulation convergence plan failed: " + res.combined(800))
                    pj = json.loads(tf("show", "-json", "-no-color", str(probe)).stdout)
                    probe.unlink(missing_ok=True)
                    pending = [rc for rc in pj.get("resource_changes", []) if rc["change"]["actions"] not in (["no-op"], ["read"])]
                    log(f"Simulated state round {round_no}: {len(pending)} placeholder differences remaining.")
                    if not pending:
                        break
                    state, records = build_state(pj, schema, region, state)
                ws.state_path.write_text(json.dumps(state))
                log(f"Simulated apply recorded {len(records)} resources.")
            checks = verification.simulated_checks(state) if kind == "apply" else []
        else:
            log(
                f"REAL AWS {kind}: applying the approved saved plan {plan_id[:8]} with profile {settings.aws_profile or '(default chain)'}."
            )
            res = tf("apply", "-input=false", "-no-color", "-lock-timeout=60s", plan_path, timeout=3600)
            log(res.combined(20_000))
            if not res.ok:
                raise RuntimeError(
                    "terraform apply failed; the environment may be partially changed. Run validation to see the current state."
                )
            state = json.loads(ws.state_path.read_text()) if ws.state_path.exists() else {"resources": []}
            records = [
                {
                    "address": f"{r['type']}.{r['name']}",
                    "type": r["type"],
                    "id": (i.get("attributes") or {}).get("id"),
                    "arn": (i.get("attributes") or {}).get("arn"),
                    "simulated": False,
                }
                for r in state.get("resources", [])
                if r.get("mode") == "managed"
                for i in r.get("instances", [])
            ]
            checks = []
            if kind == "apply":
                import boto3  # type: ignore[import-untyped]
                import httpx

                outputs = {k: v.get("value") for k, v in (state.get("outputs") or {}).items()}
                session = boto3.Session(profile_name=settings.aws_profile) if settings.aws_profile else boto3.Session()
                checks = verification.live_checks(session, outputs, state, http_get=lambda url: httpx.get(url, timeout=10).status_code)
        with SessionLocal() as db:
            dep_row = db.get(Deployment, dep_id)
            plan_row = db.get(Plan, plan_id)
            project = db.get(Project, ctx.project_id)
            assert dep_row and plan_row and project
            dep_row.status = "succeeded"
            dep_row.resources = records
            dep_row.verification = checks
            dep_row.log = "\n".join(logs)[-50_000:]
            dep_row.finished_at = _now()
            plan_row.status = "applied"
            spec = P.spec(project)
            if spec and checks:
                spec = traceability.apply_verification(spec, checks, simulated=(mode == "simulation"))
                project.requirements = spec.model_dump(mode="json")
            project.status = ("torn_down" if kind == "destroy" else "deployed") + ("_simulated" if mode == "simulation" else "")
            P.audit(db, "deployment.succeeded", project.id, session_id, deployment_id=dep_id, kind=kind, mode=mode, resources=len(records))
            db.commit()
        return {"deployment_id": dep_id, "resources": len(records), "mode": mode, "kind": kind}
    except BaseException as exc:
        with SessionLocal() as db:
            failed_dep = db.get(Deployment, dep_id)
            if failed_dep:
                failed_dep.status = "failed" if not ctx.cancel.is_set() else "interrupted"
                failed_dep.log = ("\n".join(logs) + f"\n{type(exc).__name__}: {exc}")[-50_000:]
                failed_dep.finished_at = _now()
            failed_plan = db.get(Plan, plan_id)
            if failed_plan:
                failed_plan.status = "failed"
            P.audit(db, "deployment.failed", ctx.project_id, session_id, deployment_id=dep_id, error=f"{type(exc).__name__}")
            db.commit()
        raise


def run_destroy_plan(ctx: OpContext, settings: Settings) -> dict[str, Any]:
    with SessionLocal() as db:
        project = db.get(Project, ctx.project_id)
        assert project is not None
        mode = P.project_settings(project)["deployment_mode"]
        files = effective_files(project.generated_files or {}, project.file_overrides or {})
        tfvars = P.tfvars(project, settings, mode)
    ws = Workspace(settings, ctx.project_id, mode)
    if not ws.state_path.exists():
        raise RuntimeError("There is no deployed state for this project in the current mode; nothing to tear down.")
    violations = safety.precheck(files)
    if violations:
        raise RuntimeError("Configuration contains disallowed constructs: " + "; ".join(violations))
    _, config_sha = ws.write(files, tfvars)
    tf = Terraform(settings, ws.dir, mode, ctx.cancel)
    with SessionLocal() as db:
        plan = Plan(project_id=ctx.project_id, kind="destroy", mode=mode, config_sha256=config_sha, plan_sha256="", plan_path="")
        db.add(plan)
        db.commit()
        plan_id = plan.id
    path = ws.plan_path(plan_id)
    args = ["plan", "-destroy", "-input=false", "-no-color", f"-out={path}"] + (["-refresh=false"] if mode == "simulation" else [])
    res = tf(*args, timeout=900)
    ctx.log(res.combined(4000))
    if not res.ok:
        raise RuntimeError("Destroy plan failed.")
    pj = json.loads(tf("show", "-json", "-no-color", str(path)).stdout)
    rv = review(
        pj,
        cost_note="Removing these resources stops their charges; snapshots, retained logs and some CloudWatch data may continue to incur cost.",
    )
    with SessionLocal() as db:
        saved = db.get(Plan, plan_id)
        assert saved
        saved.plan_path = str(path)
        saved.plan_sha256 = file_sha256(path)
        saved.review = rv.model_dump(mode="json")
        saved.status = "pending_review"
        for older in db.query(Plan).filter(
            Plan.project_id == ctx.project_id, Plan.kind == "destroy", Plan.id != plan_id, Plan.status.in_(["pending_review", "approved"])
        ):
            older.status = "superseded"
        db.commit()
    return {"plan_id": plan_id, "headline": rv.headline}
