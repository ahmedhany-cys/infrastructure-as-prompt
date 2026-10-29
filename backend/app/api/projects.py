"""Session, project, interview, requirements, architecture and settings routes."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.domain.interview import TranscriptEntry
from app.models import Deployment, Project, ScanRun, WorkspaceSession
from app.security import csrf_token, current_session, limiter, owned_project, parse_cookie_value, set_session_cookies
from app.services import ai_provider
from app.services import interview_engine as ie
from app.services import projects as P
from app.services.architect import build_architecture
from app.services.compiler import CompileError, compile_requirements
from app.services.terraform.generator import format_files, generate
from app.services.terraform.runner import Terraform, ToolUnavailable

router = APIRouter(prefix="/api")


# --- session / system --------------------------------------------------------


@router.post("/session")
def create_session(request: Request, response: Response, db: Session = Depends(get_db)) -> dict[str, Any]:
    sid = parse_cookie_value(request.cookies.get("iap_session"))
    ws = db.get(WorkspaceSession, sid) if sid else None
    if ws is None:
        ws = WorkspaceSession()
        db.add(ws)
        db.commit()
    set_session_cookies(response, ws.id)
    return {"csrf_token": csrf_token(ws.id)}


@router.get("/session")
def get_session(ws: WorkspaceSession = Depends(current_session)) -> dict[str, Any]:
    return {"csrf_token": csrf_token(ws.id), "created_at": ws.created_at.isoformat()}


@router.get("/system")
def system(settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    provider = ai_provider.get_provider(settings)
    return {
        "ai": {"live": provider.live, "label": ai_provider.engine_label(provider, settings)},
        "tools": {
            "terraform": settings.terraform_path() is not None,
            "checkov": settings.checkov_argv() is not None,
            "trivy": settings.trivy_path() is not None,
        },
        "real_deploy_enabled": settings.allow_real_deploy and bool(settings.aws_expected_account_id),
        "aws_expected_account_id": settings.aws_expected_account_id if settings.allow_real_deploy else None,
        "allowed_regions": settings.aws_allowed_regions,
    }


# --- projects ----------------------------------------------------------------


class CreateProject(BaseModel):
    name: str = Field(min_length=3, max_length=60, pattern=r"^[A-Za-z0-9][A-Za-z0-9 ._-]*$")
    request: str = Field(min_length=10, max_length=4000)


def _summary(db: Session, p: Project) -> dict[str, Any]:
    scan = db.query(ScanRun).filter(ScanRun.project_id == p.id).order_by(ScanRun.created_at.desc()).first()
    dep = db.query(Deployment).filter(Deployment.project_id == p.id).order_by(Deployment.started_at.desc()).first()
    opt = P.selected_option(p)
    spec = P.spec(p)
    return {
        "id": p.id,
        "name": p.name,
        "description": p.description,
        "status": p.status,
        "updated_at": p.updated_at.isoformat(),
        "created_at": p.created_at.isoformat(),
        "mode": P.project_settings(p)["deployment_mode"],
        "last_scan": None
        if not scan
        else {
            "id": scan.id,
            "status": scan.status,
            "at": scan.created_at.isoformat(),
            "summary": scan.summary,
            "stale": scan.config_revision != p.config_revision,
        },
        "deployment": None if not dep else {"status": dep.status, "mode": dep.mode, "kind": dep.kind, "at": dep.started_at.isoformat()},
        "cost": None
        if not opt
        else {"monthly_usd": opt.cost.total_monthly_usd, "option": opt.name, "within_budget": opt.cost.within_budget},
        "requirements": None
        if not spec
        else {
            s: sum(1 for r in spec.requirements if r.status.value == s)
            for s in ("passing", "failing", "unverified", "blocked", "not_applicable")
        },
    }


@router.get("/projects")
def list_projects(ws: WorkspaceSession = Depends(current_session), db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    rows = db.query(Project).filter(Project.owner_id == ws.id).order_by(Project.updated_at.desc()).all()
    return [_summary(db, p) for p in rows]


@router.post("/projects", status_code=201)
def create_project(
    body: CreateProject,
    ws: WorkspaceSession = Depends(current_session),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    limiter.check(ws.id, "interview", settings.rate_limit_interview_per_minute)
    provider = ai_provider.get_provider(settings)
    hints, notes = provider.extract_hints(body.request)
    state = ie.start(body.request, hints, "ai" if provider.live else "demo")
    state.ai_notes += notes
    p = Project(
        owner_id=ws.id, name=body.name.strip(), description=body.request[:500], interview=state.model_dump(mode="json"), settings={}
    )
    db.add(p)
    db.flush()
    P.audit(db, "project.created", p.id, ws.id, engine=state.engine)
    db.commit()
    return {"id": p.id}


@router.get("/projects/{project_id}")
def get_project(
    project: Project = Depends(owned_project), db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
) -> dict[str, Any]:
    provider = ai_provider.get_provider(settings)
    data = _summary(db, project)
    data.update(
        {
            "settings": P.project_settings(project),
            "interview": ie.view(P.interview(project), ai_provider.engine_label(provider, settings)).model_dump(mode="json"),
            "requirements": project.requirements,
            "architecture": project.architecture,
            "has_terraform": bool(project.generated_files),
            "config_revision": project.config_revision,
            "manual_edits": sorted((project.file_overrides or {}).keys()),
        }
    )
    return data


@router.delete("/projects/{project_id}", status_code=204)
def delete_project(
    project: Project = Depends(owned_project),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    ws: WorkspaceSession = Depends(current_session),
) -> Response:
    real_state = settings.workspaces_dir / project.id / "aws" / "terraform.tfstate"
    if real_state.exists() and real_state.read_text().strip() and '"resources": []' not in real_state.read_text():
        raise HTTPException(409, "This project manages real AWS resources. Tear them down before deleting the project.")
    P.audit(db, "project.deleted", project.id, ws.id, name=project.name)
    db.delete(project)
    db.commit()
    return Response(status_code=204)


# --- interview ---------------------------------------------------------------


class AnswerBody(BaseModel):
    question_id: str = Field(max_length=40)
    value: str | float | None = None
    text: str | None = Field(default=None, max_length=1000)
    accept_recommendation: bool = False


def _invalidate_downstream(project: Project, state: Any, reason: str) -> None:
    if project.requirements or project.architecture or project.generated_files:
        msg = f"{reason} The compiled requirements, architecture and generated Terraform were cleared and must be regenerated."
        if project.file_overrides:
            msg += f" Manual Terraform edits ({', '.join(sorted(project.file_overrides))}) were discarded."
        state.transcript.append(TranscriptEntry(role="system", text=msg, at=ie.now(), kind="warning"))
    project.requirements = None
    project.architecture = None
    project.generated_files = None
    project.file_overrides = {}
    project.config_revision += 1
    project.status = "interviewing"


@router.post("/projects/{project_id}/interview/answer")
def answer(
    body: AnswerBody,
    project: Project = Depends(owned_project),
    ws: WorkspaceSession = Depends(current_session),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    limiter.check(ws.id, "interview", settings.rate_limit_interview_per_minute)
    state = P.interview(project)
    qdef = ie.QUESTION_INDEX.get(body.question_id)
    if qdef is None or body.question_id not in {q.id for q in ie.applicable(state)}:
        raise HTTPException(400, "Unknown or non-applicable question.")
    qview = qdef.view(state)
    provider = ai_provider.get_provider(settings)
    before = {k: v.value for k, v in state.answers.items()}
    if body.accept_recommendation:
        if qview.recommended is None:
            raise HTTPException(400, "This question has no recommendation.")
        ie.record_answer(state, body.question_id, qview.recommended, "accepted_recommendation", None, "option")
    elif body.value is not None:
        ie.record_answer(state, body.question_id, body.value, "user", None, "option")
    elif body.text:
        state.transcript.append(TranscriptEntry(role="user", text=body.text, at=ie.now(), question_id=body.question_id))
        interp, notes = provider.interpret(qview, qdef, body.text)
        state.ai_notes += notes
        if interp.kind == "answer":
            ie.record_answer(
                state, body.question_id, interp.value, "user", body.text, "ai" if provider.live and not notes else "deterministic_parser"
            )
        elif interp.kind == "accept_recommendation" and qview.recommended is not None:
            ie.record_answer(state, body.question_id, qview.recommended, "accepted_recommendation", body.text, "deterministic_parser")
        elif interp.kind == "explain":
            ie.explain(state, body.question_id)
        else:
            opts = (
                "; ".join(o.label for o in qview.options) if qview.options else ("a number" if qview.kind == "number" else "a CIDR range")
            )
            extra = f" {interp.note}" if interp.note else ""
            state.transcript.append(
                TranscriptEntry(
                    role="assistant",
                    kind="clarification",
                    at=ie.now(),
                    question_id=body.question_id,
                    text=f"I couldn't match that to an answer, so nothing was recorded.{extra} Please choose: {opts}. Or ask “what does this mean?”.",
                )
            )
    else:
        raise HTTPException(400, "Provide value, text or accept_recommendation.")
    after = {k: v.value for k, v in state.answers.items()}
    if before != after and (project.requirements or project.architecture):
        _invalidate_downstream(project, state, "An answer changed after the requirements were compiled.")
    elif before != after and not state.complete:
        project.status = "interviewing"
    if state.complete and project.status == "interviewing":
        project.status = "interview_complete"
    project.interview = state.model_dump(mode="json")
    P.audit(db, "interview.answer", project.id, ws.id, question=body.question_id, changed=before != after)
    db.commit()
    return ie.view(state, ai_provider.engine_label(provider, settings)).model_dump(mode="json")


@router.get("/projects/{project_id}/interview/questions/{question_id}")
def question_view(question_id: str, project: Project = Depends(owned_project)) -> dict[str, Any]:
    state = P.interview(project)
    q = ie.QUESTION_INDEX.get(question_id)
    if q is None or question_id not in {x.id for x in ie.applicable(state)}:
        raise HTTPException(404, "Unknown or non-applicable question.")
    return q.view(state).model_dump(mode="json")


class ExplainBody(BaseModel):
    question_id: str = Field(max_length=40)


@router.post("/projects/{project_id}/interview/explain")
def explain(
    body: ExplainBody, project: Project = Depends(owned_project), db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
) -> dict[str, Any]:
    state = P.interview(project)
    if body.question_id not in ie.QUESTION_INDEX:
        raise HTTPException(400, "Unknown question.")
    ie.explain(state, body.question_id)
    project.interview = state.model_dump(mode="json")
    db.commit()
    return ie.view(state, ai_provider.engine_label(ai_provider.get_provider(settings), settings)).model_dump(mode="json")


# --- requirements & architecture ------------------------------------------------


@router.post("/projects/{project_id}/requirements/compile")
def compile_reqs(
    project: Project = Depends(owned_project), ws: WorkspaceSession = Depends(current_session), db: Session = Depends(get_db)
) -> dict[str, Any]:
    state = P.interview(project)
    old = P.spec(project)
    try:
        spec = compile_requirements(state, revision=(old.revision + 1) if old else 1)
    except CompileError as exc:
        raise HTTPException(409, str(exc)) from exc
    try:
        arch = build_architecture(spec)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    project.requirements = spec.model_dump(mode="json")
    project.architecture = arch.model_dump(mode="json")
    project.generated_files = None
    project.file_overrides = {}
    project.config_revision += 1
    project.status = "requirements_ready"
    P.audit(db, "requirements.compiled", project.id, ws.id, revision=spec.revision, count=len(spec.requirements))
    db.commit()
    return {"requirements": project.requirements, "architecture": project.architecture}


class SelectBody(BaseModel):
    option_id: Literal["lean", "balanced", "resilient"]
    confirm_discard_edits: bool = False


@router.post("/projects/{project_id}/architecture/select")
def select_option(
    body: SelectBody,
    project: Project = Depends(owned_project),
    ws: WorkspaceSession = Depends(current_session),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    arch = P.arch(project)
    spec = P.spec(project)
    if arch is None or spec is None:
        raise HTTPException(409, "Compile requirements first.")
    option = arch.option(body.option_id)
    if option is None:
        raise HTTPException(400, "That option is not available for this project's requirements.")
    if project.file_overrides and not body.confirm_discard_edits:
        raise HTTPException(409, "Regenerating Terraform would discard your manual edits. Confirm to continue.")
    arch.selected = option.id
    files = generate(project.id, project.name, spec, option)
    try:
        tf = Terraform(settings, settings.workspaces_dir, "simulation")
        files = format_files(files, tf.fmt_text)
    except ToolUnavailable:
        pass
    project.architecture = arch.model_dump(mode="json")
    project.generated_files = files
    project.file_overrides = {}
    project.config_revision += 1
    project.status = "generated"
    P.audit(db, "architecture.selected", project.id, ws.id, option=option.id, files=len(files))
    db.commit()
    return {"selected": option.id, "files": sorted(files)}


# --- settings ----------------------------------------------------------------


class SettingsBody(BaseModel):
    name: str | None = Field(default=None, min_length=3, max_length=60, pattern=r"^[A-Za-z0-9][A-Za-z0-9 ._-]*$")
    description: str | None = Field(default=None, max_length=500)
    deployment_mode: Literal["simulation", "aws"] | None = None
    policy_profile: Literal["standard", "strict"] | None = None
    acm_certificate_arn: str | None = Field(
        default=None, max_length=200, pattern=r"^(arn:aws[a-z-]*:acm:[a-z0-9-]+:[0-9]{12}:certificate/[A-Za-z0-9-]+)?$"
    )
    owner_email: str | None = Field(default=None, max_length=120)
    region: str | None = None
    budget: float | None = Field(default=None, gt=0, le=1_000_000)


@router.patch("/projects/{project_id}/settings")
def update_settings(
    body: SettingsBody,
    project: Project = Depends(owned_project),
    ws: WorkspaceSession = Depends(current_session),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    s = P.project_settings(project)
    changed: list[str] = []
    if body.deployment_mode and body.deployment_mode != s["deployment_mode"]:
        if body.deployment_mode == "aws" and not (settings.allow_real_deploy and settings.aws_expected_account_id):
            raise HTTPException(
                403, "Real AWS mode is disabled on this server. An operator must set IAP_ALLOW_REAL_DEPLOY and IAP_AWS_EXPECTED_ACCOUNT_ID."
            )
        s["deployment_mode"] = body.deployment_mode
        changed.append("deployment_mode")
    for key in ("policy_profile", "acm_certificate_arn", "owner_email"):
        val = getattr(body, key)
        if val is not None and val != s.get(key):
            s[key] = val or None
            changed.append(key)
    if body.name:
        project.name = body.name.strip()
        changed.append("name")
    if body.description is not None:
        project.description = body.description
        changed.append("description")
    state = P.interview(project)
    for qid, val in (("region", body.region), ("budget", body.budget)):
        if val is not None and state.value(qid) != val:
            refusal = ie.record_answer(state, qid, val, "user", None, "option")
            if refusal:
                raise HTTPException(400, refusal)
            _invalidate_downstream(project, state, f"The {qid} was changed in project settings.")
            changed.append(qid)
    project.interview = state.model_dump(mode="json")
    project.settings = s
    if changed and ("deployment_mode" in changed or "acm_certificate_arn" in changed):
        project.config_revision += 1  # plans made under other settings are no longer valid
    P.audit(db, "settings.updated", project.id, ws.id, changed=changed)
    db.commit()
    return {"settings": s, "changed": changed}
