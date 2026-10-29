"""Helpers to load and store validated domain documents on Project rows."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.config import Settings
from app.domain.architecture import ArchitectureOption, ArchitectureSpec
from app.domain.interview import InterviewState
from app.domain.requirements import RequirementsSpec
from app.models import AuditLog, Project

DEFAULT_SETTINGS: dict[str, Any] = {
    "cloud_provider": "aws",
    "deployment_mode": "simulation",
    "policy_profile": "standard",
    "acm_certificate_arn": None,
    "owner_email": None,
}

SIM_TFVARS = {
    "aws_account_id": "000000000000",
    "acm_certificate_arn": "arn:aws:acm:us-east-1:000000000000:certificate/00000000-0000-0000-0000-000000000000",
}


def interview(p: Project) -> InterviewState:
    return InterviewState.model_validate(p.interview or {})


def spec(p: Project) -> RequirementsSpec | None:
    return RequirementsSpec.model_validate(p.requirements) if p.requirements else None


def arch(p: Project) -> ArchitectureSpec | None:
    return ArchitectureSpec.model_validate(p.architecture) if p.architecture else None


def selected_option(p: Project) -> ArchitectureOption | None:
    a = arch(p)
    return a.option(a.selected) if a else None


def project_settings(p: Project) -> dict[str, Any]:
    return {**DEFAULT_SETTINGS, **(p.settings or {})}


def tfvars(p: Project, settings: Settings, mode: str) -> dict[str, str]:
    opt = selected_option(p)
    region = opt.params.region if opt else "us-east-1"
    https = opt.params.https if opt else True
    if mode == "simulation":
        vals = {"aws_account_id": SIM_TFVARS["aws_account_id"]}
        if https:
            vals["acm_certificate_arn"] = SIM_TFVARS["acm_certificate_arn"].replace("us-east-1", region)
        return vals
    vals = {"aws_account_id": settings.aws_expected_account_id or ""}
    cert = project_settings(p).get("acm_certificate_arn")
    if https and cert:
        vals["acm_certificate_arn"] = cert
    return vals


def audit(db: Session, action: str, project_id: str | None, session_id: str | None, **detail: Any) -> None:
    db.add(AuditLog(project_id=project_id, session_id=session_id, action=action, detail=detail))
