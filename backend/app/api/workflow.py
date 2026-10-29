"""Terraform files, validation pipeline, operations, plans, deployments and evidence."""

from __future__ import annotations

import io
import re
import zipfile
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.models import AuditLog, Deployment, Operation, Plan, Project, ScanRun, WorkspaceSession
from app.security import current_session, limiter, owned_project
from app.services import evidence
from app.services import projects as P
from app.services.deploy import service as deploy
from app.services.operations import Busy, manager
from app.services.pipeline import run_pipeline
from app.services.terraform.workspace import MAX_FILE_BYTES, Workspace, WorkspaceError, effective_files, validate_filename

router = APIRouter(prefix="/api")

# Documented, deliberately insecure test mutations used to demonstrate that the
# policy engine catches real misconfigurations. Each is a literal text edit.
INSECURE_SCENARIOS: dict[str, dict[str, Any]] = {
    "public_database": {
        "title": "Make the database publicly accessible",
        "file": "database.tf",
        "find": r"publicly_accessible(\s*)= false",
        "replace": r"publicly_accessible\1= true",
    },
    "open_ssh": {
        "title": "Open SSH (port 22) to the whole internet",
        "file": "security_groups.tf",
        "append": '\n# INSECURE TEST CHANGE: SSH from anywhere\nresource "aws_vpc_security_group_ingress_rule" "debug_ssh" {\n  security_group_id = aws_security_group.app.id\n'
        '  description       = "Temporary debugging access"\n  cidr_ipv4         = "0.0.0.0/0"\n  from_port         = 22\n  to_port           = 22\n  ip_protocol       = "tcp"\n}\n',
    },
    "wildcard_iam": {
        "title": "Grant the application role every permission",
        "file": "compute.tf",
        "append": '\n# INSECURE TEST CHANGE: wildcard permissions\nresource "aws_iam_role_policy" "debug_admin" {\n  name = "debug-everything"\n  role = aws_iam_role.app.id\n\n'
        '  policy = jsonencode({\n    Version = "2012-10-17"\n    Statement = [{\n      Effect   = "Allow"\n      Action   = "*"\n      Resource = "*"\n    }]\n  })\n}\n',
    },
}


def _op_json(op: Operation) -> dict[str, Any]:
    return {
        "id": op.id,
        "kind": op.kind,
        "status": op.status,
        "progress": op.progress,
        "log": op.log,
        "result": op.result,
        "error": op.error,
        "created_at": op.created_at.isoformat(),
        "finished_at": op.finished_at.isoformat() if op.finished_at else None,
    }


def _plan_json(p: Plan) -> dict[str, Any]:
    return {
        "id": p.id,
        "kind": p.kind,
        "mode": p.mode,
        "status": p.status,
        "plan_sha256": p.plan_sha256,
        "config_sha256": p.config_sha256,
        "review": p.review,
        "scan_id": p.scan_id,
        "blocked_reason": p.blocked_reason,
        "approval": p.approval,
        "approved_at": p.approved_at.isoformat() if p.approved_at else None,
        "created_at": p.created_at.isoformat(),
    }


# --- terraform files ---------------------------------------------------------


@router.get("/projects/{project_id}/terraform")
def get_files(project: Project = Depends(owned_project), settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    if not project.generated_files:
        return {"files": {}, "generated": {}, "overrides": [], "lock_file": None, "revision": project.config_revision}
    ws = Workspace(settings, project.id, P.project_settings(project)["deployment_mode"])
    return {
        "files": effective_files(project.generated_files, project.file_overrides or {}),
        "generated": project.generated_files,
        "overrides": sorted((project.file_overrides or {}).keys()),
        "lock_file": ws.lock_file(),
        "revision": project.config_revision,
        "insecure_scenarios": {k: v["title"] for k, v in INSECURE_SCENARIOS.items()},
    }


class FileBody(BaseModel):
    content: str = Field(max_length=MAX_FILE_BYTES)


def _bump(project: Project) -> None:
    project.config_revision += 1
    project.status = "modified"


@router.put("/projects/{project_id}/terraform/files/{name}")
def put_file(
    name: str,
    body: FileBody,
    project: Project = Depends(owned_project),
    ws: WorkspaceSession = Depends(current_session),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    if not project.generated_files:
        raise HTTPException(409, "Generate Terraform first.")
    try:
        validate_filename(name)
    except WorkspaceError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not name.endswith(".tf"):
        raise HTTPException(400, "Only .tf files can be edited.")
    overrides = dict(project.file_overrides or {})
    if project.generated_files.get(name) == body.content:
        overrides.pop(name, None)
    else:
        overrides[name] = body.content
    project.file_overrides = overrides
    _bump(project)
    P.audit(db, "terraform.file_edited", project.id, ws.id, file=name, bytes=len(body.content))
    db.commit()
    return {"overrides": sorted(overrides), "revision": project.config_revision}


@router.delete("/projects/{project_id}/terraform/files/{name}")
def revert_file(
    name: str, project: Project = Depends(owned_project), ws: WorkspaceSession = Depends(current_session), db: Session = Depends(get_db)
) -> dict[str, Any]:
    overrides = dict(project.file_overrides or {})
    if name not in overrides:
        raise HTTPException(404, "No manual edit for that file.")
    overrides.pop(name)
    project.file_overrides = overrides
    _bump(project)
    P.audit(db, "terraform.file_reverted", project.id, ws.id, file=name)
    db.commit()
    return {"overrides": sorted(overrides), "revision": project.config_revision}


class InsecureBody(BaseModel):
    scenario: str


@router.post("/projects/{project_id}/terraform/insecure-change")
def insecure_change(
    body: InsecureBody,
    project: Project = Depends(owned_project),
    ws: WorkspaceSession = Depends(current_session),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    sc = INSECURE_SCENARIOS.get(body.scenario)
    if sc is None:
        raise HTTPException(400, "Unknown scenario.")
    files = effective_files(project.generated_files or {}, project.file_overrides or {})
    if sc["file"] not in files:
        raise HTTPException(409, f"{sc['file']} is not part of this configuration.")
    text = files[sc["file"]]
    if "find" in sc:
        new, n = re.subn(sc["find"], sc["replace"], text, count=1)
        if n == 0:
            raise HTTPException(409, "The configuration no longer contains the text this test changes (already changed?).")
    else:
        if sc["append"].strip() in text:
            raise HTTPException(409, "This insecure change is already present.")
        new = text + sc["append"]
    overrides = dict(project.file_overrides or {})
    overrides[sc["file"]] = new
    project.file_overrides = overrides
    _bump(project)
    P.audit(db, "terraform.insecure_test_change", project.id, ws.id, scenario=body.scenario, file=sc["file"])
    db.commit()
    return {"file": sc["file"], "title": sc["title"], "revision": project.config_revision}


@router.get("/projects/{project_id}/terraform/download")
def download(project: Project = Depends(owned_project), settings: Settings = Depends(get_settings)) -> Response:
    if not project.generated_files:
        raise HTTPException(409, "Generate Terraform first.")
    files = effective_files(project.generated_files, project.file_overrides or {})
    lock = Workspace(settings, project.id, P.project_settings(project)["deployment_mode"]).lock_file()
    buf = io.BytesIO()
    slug = re.sub(r"[^a-z0-9-]+", "-", project.name.lower()).strip("-") or "project"
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, text in sorted(files.items()):
            zf.writestr(f"{slug}/{name}", text)
        if lock:
            zf.writestr(f"{slug}/.terraform.lock.hcl", lock)
        zf.writestr(f"{slug}/.gitignore", ".terraform/\n*.tfstate\n*.tfstate.*\n*.tfplan\nterraform.tfvars\n")
    return Response(
        buf.getvalue(), media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{slug}-terraform.zip"'}
    )


# --- pipeline & operations ---------------------------------------------------


@router.post("/projects/{project_id}/validate", status_code=202)
def validate(
    project: Project = Depends(owned_project),
    ws: WorkspaceSession = Depends(current_session),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    limiter.check(ws.id, "pipeline", settings.rate_limit_pipeline_per_minute)
    if not project.generated_files:
        raise HTTPException(409, "Generate Terraform first.")
    try:
        op_id = manager.submit(project.id, "pipeline", lambda ctx: run_pipeline(ctx, settings))
    except Busy as exc:
        raise HTTPException(409, str(exc)) from exc
    P.audit(db, "pipeline.started", project.id, ws.id, operation=op_id)
    db.commit()
    return {"operation_id": op_id}


def _owned_op(op_id: str, ws: WorkspaceSession, db: Session) -> Operation:
    op = db.get(Operation, op_id)
    if op is None:
        raise HTTPException(404, "Operation not found.")
    project = db.get(Project, op.project_id)
    if project is None or project.owner_id != ws.id:
        raise HTTPException(404, "Operation not found.")
    return op


@router.get("/operations/{op_id}")
def get_operation(op_id: str, ws: WorkspaceSession = Depends(current_session), db: Session = Depends(get_db)) -> dict[str, Any]:
    return _op_json(_owned_op(op_id, ws, db))


@router.post("/operations/{op_id}/cancel")
def cancel_operation(op_id: str, ws: WorkspaceSession = Depends(current_session), db: Session = Depends(get_db)) -> dict[str, Any]:
    op = _owned_op(op_id, ws, db)
    if op.status not in ("queued", "running"):
        raise HTTPException(409, f"Operation is already {op.status}.")
    manager.cancel(op_id)
    P.audit(db, "operation.cancel_requested", op.project_id, ws.id, operation=op_id, kind=op.kind)
    db.commit()
    return {"cancelling": True}


@router.get("/projects/{project_id}/operations")
def list_operations(project: Project = Depends(owned_project), db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    ops = db.query(Operation).filter(Operation.project_id == project.id).order_by(Operation.created_at.desc()).limit(20).all()
    return [_op_json(o) for o in ops]


@router.get("/projects/{project_id}/scans/latest")
def latest_scan(project: Project = Depends(owned_project), db: Session = Depends(get_db)) -> dict[str, Any] | None:
    scan = db.query(ScanRun).filter(ScanRun.project_id == project.id).order_by(ScanRun.created_at.desc()).first()
    if scan is None:
        return None
    return {
        "id": scan.id,
        "status": scan.status,
        "created_at": scan.created_at.isoformat(),
        "config_revision": scan.config_revision,
        "stale": scan.config_revision != project.config_revision,
        "config_sha256": scan.config_sha256,
        "steps": scan.steps,
        "policy_results": scan.policy_results,
        "external_findings": scan.external_findings,
        "summary": scan.summary,
    }


@router.get("/projects/{project_id}/scans")
def list_scans(project: Project = Depends(owned_project), db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    scans = db.query(ScanRun).filter(ScanRun.project_id == project.id).order_by(ScanRun.created_at.desc()).limit(20).all()
    return [
        {"id": s.id, "status": s.status, "created_at": s.created_at.isoformat(), "summary": s.summary, "config_revision": s.config_revision}
        for s in scans
    ]


# --- plans & deployment ------------------------------------------------------


@router.get("/projects/{project_id}/plans")
def list_plans(project: Project = Depends(owned_project), db: Session = Depends(get_db)) -> dict[str, Any]:
    plans = db.query(Plan).filter(Plan.project_id == project.id).order_by(Plan.created_at.desc()).limit(20).all()
    latest_apply = next((p for p in plans if p.kind == "apply"), None)
    latest_destroy = next((p for p in plans if p.kind == "destroy"), None)
    return {
        "plans": [_plan_json(p) for p in plans],
        "latest_apply": _plan_json(latest_apply) if latest_apply else None,
        "latest_destroy": _plan_json(latest_destroy) if latest_destroy else None,
        "config_revision": project.config_revision,
    }


class ApproveBody(BaseModel):
    plan_sha256: str = Field(min_length=64, max_length=64)
    acknowledge_destructive: bool = False
    confirmation_text: str | None = Field(default=None, max_length=100)
    account_confirmation: str | None = Field(default=None, max_length=20)


@router.post("/projects/{project_id}/plans/{plan_id}/approve")
def approve_plan(
    plan_id: str,
    body: ApproveBody,
    project: Project = Depends(owned_project),
    ws: WorkspaceSession = Depends(current_session),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    try:
        plan = deploy.approve(db, project, plan_id, body.model_dump(), ws.id, settings)
    except deploy.DeployError as exc:
        db.commit()  # persist superseded status if integrity check failed
        P.audit(db, "plan.approval_refused", project.id, ws.id, plan_id=plan_id, reason=str(exc))
        db.commit()
        raise HTTPException(exc.status, str(exc)) from exc
    return _plan_json(plan)


@router.post("/projects/{project_id}/plans/{plan_id}/apply", status_code=202)
def apply_plan(
    plan_id: str,
    project: Project = Depends(owned_project),
    ws: WorkspaceSession = Depends(current_session),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    limiter.check(ws.id, "pipeline", settings.rate_limit_pipeline_per_minute)
    try:
        plan = deploy.preflight_apply(db, project, plan_id, settings)
    except deploy.DeployError as exc:
        db.commit()
        P.audit(db, "deployment.refused", project.id, ws.id, plan_id=plan_id, reason=str(exc))
        db.commit()
        raise HTTPException(exc.status, str(exc)) from exc
    session_id = ws.id
    try:
        op_id = manager.submit(
            project.id, "destroy" if plan.kind == "destroy" else "apply", lambda ctx: deploy.run_apply(ctx, settings, plan_id, session_id)
        )
    except Busy as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"operation_id": op_id}


@router.post("/projects/{project_id}/teardown/plan", status_code=202)
def teardown_plan(
    project: Project = Depends(owned_project),
    ws: WorkspaceSession = Depends(current_session),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    limiter.check(ws.id, "pipeline", settings.rate_limit_pipeline_per_minute)
    mode = P.project_settings(project)["deployment_mode"]
    if not (settings.workspaces_dir / project.id / mode / "terraform.tfstate").exists():
        raise HTTPException(409, "Nothing is deployed for this project in the current mode.")
    try:
        op_id = manager.submit(project.id, "destroy_plan", lambda ctx: deploy.run_destroy_plan(ctx, settings))
    except Busy as exc:
        raise HTTPException(409, str(exc)) from exc
    P.audit(db, "teardown.plan_requested", project.id, ws.id)
    db.commit()
    return {"operation_id": op_id}


@router.get("/projects/{project_id}/deployments")
def list_deployments(project: Project = Depends(owned_project), db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    deps = db.query(Deployment).filter(Deployment.project_id == project.id).order_by(Deployment.started_at.desc()).limit(20).all()
    return [
        {
            "id": d.id,
            "plan_id": d.plan_id,
            "kind": d.kind,
            "mode": d.mode,
            "status": d.status,
            "resources": d.resources,
            "verification": d.verification,
            "log": d.log,
            "started_at": d.started_at.isoformat(),
            "finished_at": d.finished_at.isoformat() if d.finished_at else None,
        }
        for d in deps
    ]


@router.get("/projects/{project_id}/evidence")
def get_evidence(
    format: str = "json",
    project: Project = Depends(owned_project),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Any:
    rep = evidence.build(db, project, settings)
    slug = re.sub(r"[^a-z0-9-]+", "-", project.name.lower()).strip("-") or "project"
    if format == "md":
        return Response(
            evidence.to_markdown(rep),
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{slug}-evidence.md"'},
        )
    if format == "json-download":
        import json

        return Response(
            json.dumps(rep, indent=2),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{slug}-evidence.json"'},
        )
    return rep


@router.get("/projects/{project_id}/audit")
def audit_log(project: Project = Depends(owned_project), db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    rows = db.query(AuditLog).filter(AuditLog.project_id == project.id).order_by(AuditLog.at.desc()).limit(100).all()
    return [{"at": a.at.isoformat(), "action": a.action, "detail": a.detail} for a in rows]
