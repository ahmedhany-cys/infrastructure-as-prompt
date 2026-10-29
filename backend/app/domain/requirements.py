"""Structured requirements specification (output of the requirements compiler)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class Category(StrEnum):
    security = "security"
    availability = "availability"
    cost = "cost"
    networking = "networking"
    performance = "performance"
    compliance = "compliance"
    operational = "operational"


class Priority(StrEnum):
    must = "must"
    should = "should"
    could = "could"


class Severity(StrEnum):
    critical = "critical"
    high = "high"
    medium = "medium"
    low = "low"
    info = "info"


SEVERITY_RANK = {Severity.critical: 4, Severity.high: 3, Severity.medium: 2, Severity.low: 1, Severity.info: 0}


class Origin(StrEnum):
    confirmed = "confirmed"  # directly stated or explicitly accepted by the user
    derived = "derived"  # follows deterministically from confirmed answers
    assumption = "assumption"  # a default the system chose; shown for review


class RequirementStatus(StrEnum):
    unverified = "unverified"
    passing = "passing"
    failing = "failing"
    blocked = "blocked"
    not_applicable = "not_applicable"


class VerificationLevel(StrEnum):
    """How strong the evidence behind a requirement status is (weakest first)."""

    none = "none"
    estimate = "estimate"  # e.g. cost model output
    static_config = "static_config"  # policy evaluated on Terraform plan/config
    simulated_inspection = "simulated_inspection"  # checked against mock cloud — NOT real
    live_inspection = "live_inspection"  # checked against real AWS API responses


class EvidenceItem(BaseModel):
    kind: str  # policy_result | cost_estimate | live_check | simulated_check | plan_review
    source: str  # e.g. "policy:POL-RDS-001" or "aws:rds:DescribeDBInstances"
    outcome: str  # pass | fail | error | skipped | not_applicable
    detail: str
    observed_at: datetime
    scan_id: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class Requirement(BaseModel):
    id: str
    title: str
    description: str
    category: Category
    priority: Priority
    severity: Severity
    origin: Origin
    source: str  # which interview answers produced it
    rationale: str
    decisions: list[str] = Field(default_factory=list)  # architecture decision ids
    resources: list[str] = Field(default_factory=list)  # terraform resource addresses
    policies: list[str] = Field(default_factory=list)  # deterministic policy ids
    verification_method: str
    status: RequirementStatus = RequirementStatus.unverified
    verification_level: VerificationLevel = VerificationLevel.none
    status_reason: str = "Not evaluated yet."
    evidence: list[EvidenceItem] = Field(default_factory=list)


class Assumption(BaseModel):
    id: str
    statement: str
    reason: str
    can_change_in: str  # where the user can revise it


class Conflict(BaseModel):
    id: str
    severity: str  # blocking | warning
    message: str
    involved: list[str]  # question ids
    suggestions: list[str] = Field(default_factory=list)


class RejectedSuggestion(BaseModel):
    """Either a recommendation the user declined (rejected_by="user") or an
    unsafe answer the system refused to record (rejected_by="system")."""

    question_id: str
    value: Any
    reason: str
    rejected_by: str = "user"
    at: datetime


class RequirementsSpec(BaseModel):
    schema_version: str = "1.0"
    revision: int = 1
    generated_at: datetime
    facts: dict[str, Any]  # confirmed interview facts the compiler used
    requirements: list[Requirement]
    assumptions: list[Assumption] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list)
    conflicts: list[Conflict] = Field(default_factory=list)
    rejected: list[RejectedSuggestion] = Field(default_factory=list)

    def by_id(self, req_id: str) -> Requirement | None:
        return next((r for r in self.requirements if r.id == req_id), None)
