"""ORM models. Structured specs are stored as validated JSON documents; every
write goes through the Pydantic domain models first."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, ForeignKey, Integer, String, Text
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import DateTime as _DateTime
from sqlalchemy.types import TypeDecorator

from app.db import Base


class DateTime(TypeDecorator[datetime]):
    """Timezone-aware UTC datetimes on every backend (SQLite drops tzinfo)."""

    impl = _DateTime(timezone=True)
    cache_ok = True

    def __init__(self, timezone: bool = True) -> None:  # signature-compatible with sqlalchemy.DateTime
        super().__init__()

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC) if value is not None else None

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value


def _uuid() -> str:
    return uuid.uuid4().hex


def utcnow() -> datetime:
    return datetime.now(UTC)


class WorkspaceSession(Base):
    """An anonymous browser workspace. Projects are isolated per workspace."""

    __tablename__ = "workspace_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("workspace_sessions.id"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="interviewing")
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    interview: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    requirements: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    architecture: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    # Generated files and user edits are kept separately so the generator can
    # be re-run without silently discarding a reviewer's manual changes.
    generated_files: Mapped[dict[str, str] | None] = mapped_column(JSON, nullable=True)
    file_overrides: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    config_revision: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    scans: Mapped[list[ScanRun]] = relationship(back_populates="project", cascade="all, delete-orphan")


class Operation(Base):
    """A long-running backend operation (pipeline, apply, teardown)."""

    __tablename__ = "operations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), default="queued")  # queued|running|succeeded|failed|cancelled|interrupted
    progress: Mapped[str] = mapped_column(String(200), default="")
    log: Mapped[str] = mapped_column(Text, default="")
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ScanRun(Base):
    """Result of the validation pipeline for one exact configuration."""

    __tablename__ = "scan_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    config_revision: Mapped[int] = mapped_column(Integer)
    config_sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))  # passed|blocked|failed
    steps: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    policy_results: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    external_findings: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    project: Mapped[Project] = relationship(back_populates="scans")


class Plan(Base):
    """A saved Terraform plan. Approval binds to the plan file hash and the
    configuration hash; any change requires a new plan and a new review."""

    __tablename__ = "plans"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    scan_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    kind: Mapped[str] = mapped_column(String(16), default="apply")  # apply|destroy
    mode: Mapped[str] = mapped_column(String(16))  # simulation|aws
    config_sha256: Mapped[str] = mapped_column(String(64))
    plan_sha256: Mapped[str] = mapped_column(String(64))
    plan_path: Mapped[str] = mapped_column(Text)
    review: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="pending_review")  # pending_review|approved|applied|superseded|rejected|failed
    blocked_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approval: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Deployment(Base):
    __tablename__ = "deployments"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    plan_id: Mapped[str] = mapped_column(String(32))
    kind: Mapped[str] = mapped_column(String(16), default="apply")  # apply|destroy
    mode: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16))  # running|succeeded|failed|interrupted
    resources: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    verification: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    log: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    action: Mapped[str] = mapped_column(String(64))
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
