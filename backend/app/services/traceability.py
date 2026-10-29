"""Derives requirement statuses from evidence.

Rules (documented in docs/requirements-compiler.md):
- A requirement is ``passing`` only if every mapped policy produced at least one
  ``pass`` and no ``fail``/``error`` on the latest scan of the current config.
- If all mapped policies are ``not_applicable`` the requirement is ``failing``:
  nothing in the plan implements it.
- If the pipeline stopped before policies ran, it is ``blocked``.
- Cost requirements are decided by the cost estimate (level ``estimate``).
- Real AWS inspection can raise the level to ``live_inspection`` or turn a
  requirement ``failing``. Simulated inspection is recorded as evidence but
  never raises the verification level.
- No AI output is ever an input to these rules.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.domain.architecture import ArchitectureOption
from app.domain.findings import PolicyResult
from app.domain.requirements import EvidenceItem, RequirementsSpec, RequirementStatus, VerificationLevel


def apply_scan(
    spec: RequirementsSpec,
    results: list[PolicyResult] | None,
    scan_id: str | None,
    blocked_reason: str | None,
    option: ArchitectureOption | None,
) -> RequirementsSpec:
    now = datetime.now(UTC)
    by_policy: dict[str, list[PolicyResult]] = {}
    for r in results or []:
        by_policy.setdefault(r.policy_id, []).append(r)
    for req in spec.requirements:
        if req.status == RequirementStatus.not_applicable and req.status_reason.startswith("User explicitly"):
            continue
        req.evidence = [e for e in req.evidence if e.kind in ("live_check", "simulated_check")]
        if req.id == "REQ-CST-001":
            if option is None:
                req.status, req.verification_level, req.status_reason = (
                    RequirementStatus.unverified,
                    VerificationLevel.none,
                    "No architecture selected.",
                )
                continue
            cost = option.cost
            ok = bool(cost.within_budget)
            req.status = RequirementStatus.passing if ok else RequirementStatus.failing
            req.verification_level = VerificationLevel.estimate
            req.status_reason = cost.budget_note + " (approximate estimate, not a billing guarantee)"
            req.evidence.append(
                EvidenceItem(
                    kind="cost_estimate",
                    source="cost-model:static-price-table",
                    outcome="pass" if ok else "fail",
                    detail=f"${cost.total_monthly_usd:,.2f}/month estimated vs ${cost.budget_usd or 0:,.0f} budget",
                    observed_at=now,
                    data={"pricing_as_of": cost.pricing_as_of},
                )
            )
            continue
        if not req.policies:
            req.status, req.verification_level, req.status_reason = (
                RequirementStatus.unverified,
                VerificationLevel.none,
                "No automated verification is defined.",
            )
            continue
        if results is None:
            req.status = RequirementStatus.blocked if blocked_reason else RequirementStatus.unverified
            req.verification_level = VerificationLevel.none
            req.status_reason = blocked_reason or "Validation pipeline has not run for the current configuration."
            continue
        outcomes = [r for pid in req.policies for r in by_policy.get(pid, [])]
        for r in outcomes:
            req.evidence.append(
                EvidenceItem(
                    kind="policy_result",
                    source=f"policy:{r.policy_id}",
                    outcome=r.outcome,
                    detail=f"{r.resource or 'configuration'}: {r.message}",
                    observed_at=now,
                    scan_id=scan_id,
                    data={"expected": r.expected, "actual": r.actual} if r.outcome == "fail" else {},
                )
            )
        fails = [r for r in outcomes if r.outcome in ("fail", "error")]
        passes = {r.policy_id for r in outcomes if r.outcome == "pass"}
        if fails:
            req.status = RequirementStatus.failing
            req.status_reason = f"{len(fails)} policy violation(s): " + "; ".join(
                f"{r.policy_id} on {r.resource or 'config'}" for r in fails[:4]
            )
            req.verification_level = VerificationLevel.static_config
        elif not passes:
            req.status = RequirementStatus.failing
            req.status_reason = "No resources implementing this requirement were found in the plan."
            req.verification_level = VerificationLevel.static_config
        elif passes != set(req.policies) and not all(
            any(r.outcome == "not_applicable" for r in by_policy.get(p, [])) for p in set(req.policies) - passes
        ):
            req.status = RequirementStatus.unverified
            req.status_reason = "Some mapped policies were not evaluated."
            req.verification_level = VerificationLevel.none
        else:
            req.status = RequirementStatus.passing
            req.verification_level = VerificationLevel.static_config
            req.status_reason = f"All mapped policies pass on the Terraform plan ({', '.join(sorted(passes))}). Static analysis only — not verified against a live environment."
    return spec


def apply_verification(spec: RequirementsSpec, checks: list[dict[str, Any]], simulated: bool) -> RequirementsSpec:
    now = datetime.now(UTC)
    by_req: dict[str, list[dict[str, Any]]] = {}
    for c in checks:
        by_req.setdefault(c["requirement"], []).append(c)
    for req in spec.requirements:
        for c in by_req.get(req.id, []):
            req.evidence.append(
                EvidenceItem(
                    kind="simulated_check" if simulated else "live_check",
                    source=c["source"],
                    outcome=c["outcome"],
                    detail=("[SIMULATED — not evidence of real infrastructure] " if simulated else "") + c["detail"],
                    observed_at=now,
                )
            )
        if simulated or req.id not in by_req:
            continue
        outcomes = {c["outcome"] for c in by_req[req.id]}
        if "fail" in outcomes:
            req.status = RequirementStatus.failing
            req.status_reason = "Live AWS inspection found a violation: " + "; ".join(
                c["detail"] for c in by_req[req.id] if c["outcome"] == "fail"
            )
            req.verification_level = VerificationLevel.live_inspection
        elif outcomes == {"pass"} and req.status == RequirementStatus.passing:
            req.verification_level = VerificationLevel.live_inspection
            req.status_reason = "Policies pass on the plan and live AWS configuration matches."
    return spec
