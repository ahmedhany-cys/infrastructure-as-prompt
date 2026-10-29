"""Policy engine: evaluates enabled policies on a plan and decides blocking."""

from __future__ import annotations

from typing import Any

from app.domain.findings import ExternalFinding, PolicyResult, ScanSummary
from app.domain.requirements import RequirementsSpec, Severity
from app.services.policy.graph import build_graph
from app.services.policy.rules import POLICIES, PolicyContext

# Severities that block deployment per policy profile.
BLOCKING = {
    "standard": {Severity.critical},
    "strict": {Severity.critical, Severity.high},
}


def context_from_requirements(spec: RequirementsSpec | None, profile_facts: dict[str, Any] | None = None) -> PolicyContext:
    enabled = {p.id for p in POLICIES if p.baseline}
    facts: dict[str, Any] = dict(profile_facts or {})
    if spec:
        for req in spec.requirements:
            if req.status.value != "not_applicable":
                enabled.update(req.policies)
        facts = {**spec.facts, **facts}
    return PolicyContext(
        enabled=enabled,
        required_backup_days=int(facts.get("backup_days", 7)),
        min_app_instances=int(facts.get("min_app_instances", 1)),
        allowed_regions=list(facts.get("allowed_regions") or []),
        admin_cidr=facts.get("admin_cidr"),
        require_private_app=bool(facts.get("require_private_app", False)),
        log_retention_days=int(facts.get("log_retention_days") or 0),
    )


def evaluate(plan_json: dict[str, Any], ctx: PolicyContext, spec: RequirementsSpec | None = None) -> list[PolicyResult]:
    graph = build_graph(plan_json)
    req_by_policy: dict[str, list[str]] = {}
    if spec:
        for req in spec.requirements:
            for pid in req.policies:
                req_by_policy.setdefault(pid, []).append(req.id)
    results: list[PolicyResult] = []
    for policy in POLICIES:
        if policy.id not in ctx.enabled:
            results.append(
                PolicyResult(
                    policy_id=policy.id,
                    title=policy.title,
                    severity=policy.severity,
                    category=policy.category,
                    outcome="not_applicable",
                    message="Not required by this project's requirements or policy profile.",
                    requirements=req_by_policy.get(policy.id, []),
                )
            )
            continue
        try:
            found = policy.check(graph, ctx, policy)
        except Exception as exc:  # noqa: BLE001 - a policy bug must never be read as a pass
            found = [
                PolicyResult(
                    policy_id=policy.id,
                    title=policy.title,
                    severity=policy.severity,
                    category=policy.category,
                    outcome="error",
                    message=f"Policy evaluation error: {type(exc).__name__}: {exc}",
                )
            ]
        for r in found:
            r.requirements = req_by_policy.get(policy.id, [])
        results.extend(found)
    return results


def summarize(results: list[PolicyResult], external: list[ExternalFinding], profile: str = "standard") -> ScanSummary:
    s = ScanSummary()
    blocking_sev = BLOCKING.get(profile, BLOCKING["standard"])
    blockers: list[str] = []
    for r in results:
        if r.outcome == "fail":
            match r.severity:
                case Severity.critical:
                    s.critical += 1
                case Severity.high:
                    s.high += 1
                case Severity.medium:
                    s.medium += 1
                case _:
                    s.low += 1
            # Destructive changes are gated by the separate destructive-approval
            # step instead of blocking outright (otherwise teardown is impossible).
            if r.severity in blocking_sev and r.policy_id != "POL-CHG-001":
                blockers.append(f"{r.policy_id} on {r.resource or 'configuration'}")
        elif r.outcome == "error":
            blockers.append(f"{r.policy_id} could not be evaluated")
        elif r.outcome == "pass":
            s.passed += 1
        else:
            s.not_applicable += 1
    s.external_advisories = len(external)
    s.blocking = bool(blockers)
    s.blocking_reason = ("Deployment blocked by: " + "; ".join(sorted(set(blockers)))) if blockers else ""
    return s
