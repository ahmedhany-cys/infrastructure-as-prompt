# Requirements interview and compiler

## Interview state

The interview's source of truth is `InterviewState` (`backend/app/domain/interview.py`), not the chat transcript:

- `answers` — confirmed answers only, each with origin (`user` or `accepted_recommendation`) and how it was interpreted (`option`, `deterministic_parser`, `ai`).
- `hints` — things detected in the initial request. **Never** treated as answers; they only inform recommendations.
- `conflicts` — `blocking` (prevents completion) or `warning`.
- `rejected` — recommendations the user declined (`rejected_by=user`) and unsafe answers the system refused (`rejected_by=system`).
- `transcript` — display only.

## Questions

27 questions in seven sections. Only the ones that apply are asked (a typical project answers 23–25). Each question's recommendation is computed from the answers already given, so the interview tailors itself to the customer: a healthcare organisation in the US is steered towards regulated data, HIPAA and six-year log retention; an online store towards high availability and a file bucket; a business-hours staging system towards switching its servers off at night.

| Section | ID | Asked when | What the answer changes |
|---|---|---|---|
| Your business | industry | always | recommendations for data class, compliance, availability, file storage, log retention |
| | user_geography | always | recommended region (e.g. Middle East & Africa → Frankfurt, the closest supported region) |
| | environment | always | availability, cost, security |
| | deployment_type | always | change safety |
| | existing_ack | deployment_type = existing | change safety (MVP creates a separate environment or stops) |
| Your application | app_runtime | always | app port (Node 3000, Python 8000, .NET 5000, JVM 8080…) and instance size (JVM/.NET one size larger) |
| | traffic | always | sizing, scaling, cost |
| | traffic_pattern | always | spiky → twice the scaling headroom and scale-out at 50 % CPU (instead of 60 %) |
| | off_hours | development/staging with business-hours traffic | scheduled scale-to-zero 19:00–07:00 and weekends (`aws_autoscaling_schedule`), ~64 % lower compute cost |
| | needs_database | always | architecture |
| | db_size | database | allocated storage (20 / 100 / 500 GB, autoscaling to 5×) and a free-storage alarm threshold |
| | file_uploads | always | private, encrypted, versioned, TLS-only S3 bucket and an IAM policy scoped to it |
| Data & compliance | data_sensitivity | always | security, compliance |
| | compliance | data is personal or regulated | controls, backups, WAF |
| | data_residency | always | allowed regions |
| | region | always (options filtered by residency) | latency, cost, compliance |
| Uptime & recovery | availability | always | Multi-AZ, instance count |
| | recovery_window | database | backup retention 1/7/14/35 days; below 7 days refused for production, below 35 for HIPAA/PCI |
| Security & access | tls | always | HTTPS (HTTP-only refused unless public data in development) |
| | admin_access | always | SSM vs SSH |
| | admin_cidr | admin_access = ssh | validated CIDR, never `0.0.0.0/0`, private or > /16 ranges |
| | audit_logging | not HIPAA/PCI (mandatory there) | CloudTrail, flow logs |
| | log_retention | always | log bucket lifecycle and log group retention (30 d – 6 years); below 1 year refused for PCI |
| Operations | ops_team | always | recommendations (alerts; prefer automatic database failover outside development) |
| | alerting | always | CloudWatch alarms → KMS-encrypted SNS topic |
| | alert_email | alerting = email | validated address written to the `alert_email` variable |
| Budget | budget | always | option selection; recommendation computed from the cheapest compliant option |

The request text is also scanned for profile hints (for example "online store", "Django", "Black Friday", "uploads", "no dedicated ops team"); like every hint, they only pre-select a recommendation and are never recorded as answers.

Revising an answer re-evaluates applicability (answers that no longer apply are removed and announced), conflicts and completion. If requirements were already compiled, they — and the architecture and generated Terraform, including manual edits — are cleared after a confirmation dialog.

## Conflict detection

- **CF-BUDGET** (blocking): budget below the cheapest option that satisfies all *must* requirements. Computed by compiling a draft spec and running the architecture engine. Suggestions include raising the budget, relaxing availability (with the recomputed minimum) or using a development environment — and explicitly state that security controls will not be removed.
- **CF-RESIDENCY** (blocking): region outside the residency restriction.
- **CF-EXISTING** (blocking): user needs to manage existing resources (import is not supported).
- **CF-REGULATED** (warning): regulated data but no framework.
- **CF-DEV-HA** (warning): high availability requested for development.
- **CF-NO-ALERTS** (warning): production without alerts.

Refused answers (recorded with `rejected_by=system`): plain HTTP for non-public or non-development data, SSH from overly broad or private ranges, a restore window below the minimum for the environment or framework, log retention below one year for PCI, switching servers off at night when the service must stay available, and malformed alert email addresses.

## Free-text interpretation

The deterministic parser matches option values/labels and per-question synonyms. If more than one option matches, the answer is **unclear** — it never guesses (e.g. "dev or prod"). Questions such as "what does that mean?" return an explanation and the recommendation. "Whatever you recommend" accepts the recommendation (recorded as such). With the Anthropic provider enabled, unclear replies are sent to the model; its output must be one of the allowed values.

## Compiled specification

`compile_requirements()` refuses to run on an incomplete interview. Each requirement has:

```json
{
  "id": "REQ-SEC-001",
  "title": "Database is not reachable from the internet",
  "category": "security", "priority": "must", "severity": "critical",
  "origin": "confirmed", "source": "Interview: data_sensitivity = Customers' personal data; needs_database = Yes, PostgreSQL",
  "decisions": ["DEC-NET-TIERS", "DEC-DB-PLACEMENT"],
  "resources": ["aws_db_instance.main", "aws_db_subnet_group.main", "aws_security_group.db", "..."],
  "policies": ["POL-RDS-001", "POL-NET-001", "POL-SG-002"],
  "verification_method": "Plan-based policies; live check of PubliclyAccessible and security group rules after a real deployment.",
  "status": "unverified", "verification_level": "none", "evidence": []
}
```

A full example from a real run: [examples/requirements-spec.json](examples/requirements-spec.json).

Requirements that are always present (security baseline, `origin: derived`): encryption at rest, no exposed admin/DB ports, app servers reachable only via the load balancer, least-privilege IAM, no secrets in configuration, IMDSv2, private log storage, tagging. Others depend on answers (database isolation, TLS, audit trail, availability, backups, deletion protection, WAF, private app tier, data residency, budget), including the customer-tailored ones:

| Requirement | From | Verified by |
|---|---|---|
| REQ-SEC-010 Uploaded files are private and encrypted | file_uploads | POL-S3-001/002/003 on every bucket, POL-IAM-001 |
| REQ-AUD-003 Logs retained for at least N days | log_retention | POL-LOG-004 (lifecycle expiration and log group retention) |
| REQ-OPS-003 Someone is alerted when the service is unhealthy | alerting, alert_email | POL-OPS-001 (LB alarm → subscribed topic), POL-OPS-002 (topic encrypted with a customer-managed key) |
| REQ-CST-002 Servers switch off outside business hours | off_hours | POL-CST-001 (scale-to-zero and restart schedules) |

Assumptions the system made without asking (e.g. PostgreSQL 16, Graviton instances, the runtime's default port, two AZs, AWS-managed keys, local state, business hours in the region's time zone, starting database storage) are listed separately, and unresolved items (ACM certificate, formal compliance assessment) are carried into the evidence report.

## Status derivation (`traceability.py`)

| Situation | Status |
|---|---|
| No scan for the current configuration | `unverified` |
| Pipeline stopped before policies ran | `blocked` (with the reason) |
| Any mapped policy `fail` or `error` | `failing` |
| All mapped policies `not_applicable` | `failing` — nothing in the plan implements it |
| All mapped policies pass | `passing`, level `static_config` |
| Cost requirement | from the estimate, level `estimate` |
| Live AWS check fails | `failing`, level `live_inspection` |
| Live AWS checks pass and policies pass | `passing`, level `live_inspection` |
| Simulated checks | evidence only; level unchanged |

These rules have no AI input.
