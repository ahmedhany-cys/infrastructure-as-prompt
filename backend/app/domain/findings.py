"""Policy findings, pipeline steps and plan review schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.domain.requirements import Severity

PolicyOutcome = Literal["pass", "fail", "not_applicable", "error"]


class PolicyResult(BaseModel):
    """One deterministic policy evaluated against one resource (or globally)."""

    policy_id: str
    title: str
    severity: Severity
    category: str
    outcome: PolicyOutcome
    resource: str | None = None
    attribute: str | None = None
    message: str
    expected: Any = None
    actual: Any = None
    remediation: str = ""
    requirements: list[str] = Field(default_factory=list)


class ExternalFinding(BaseModel):
    tool: Literal["checkov", "trivy"]
    rule_id: str
    title: str
    severity: str
    resource: str | None = None
    file: str | None = None
    line: int | None = None
    guideline: str | None = None
    advisory: bool = True  # external scanners inform; the deterministic engine gates


StepStatus = Literal["passed", "failed", "warning", "skipped", "unavailable", "error", "cancelled"]


class PipelineStep(BaseModel):
    name: str
    status: StepStatus
    summary: str
    started_at: datetime | None = None
    finished_at: datetime | None = None
    output: str = ""  # truncated tool output, secrets never included


class ResourceChange(BaseModel):
    address: str
    type: str
    name: str
    actions: list[str]  # terraform actions, e.g. ["create"], ["delete","create"]
    action: Literal["create", "update", "delete", "replace", "no-op", "read"]
    stateful: bool = False
    risk: Literal["none", "low", "medium", "high", "critical"] = "none"
    notes: list[str] = Field(default_factory=list)
    changed_attributes: list[str] = Field(default_factory=list)


class PlanReview(BaseModel):
    counts: dict[str, int]
    changes: list[ResourceChange]
    destructive: bool
    data_loss_risks: list[str]
    downtime_risks: list[str]
    security_notes: list[str]
    cost_note: str
    headline: str


class ScanSummary(BaseModel):
    critical: int = 0
    high: int = 0
    medium: int = 0
    low: int = 0
    passed: int = 0
    not_applicable: int = 0
    external_advisories: int = 0
    blocking: bool = False
    blocking_reason: str = ""
