# Testing

## How to run

```bash
# Backend (needs terraform on PATH for the integration tests; they are skipped otherwise)
cd backend
.venv/bin/python -m pytest
.venv/bin/python -m ruff check app tests && .venv/bin/python -m ruff format --check app tests
.venv/bin/python -m mypy app

# Frontend
cd frontend
npm run lint && npm run typecheck && npm test && npm run build

# End-to-end UI journey (starts/reuses both servers; uses installed Google Chrome)
npx playwright test          # IAP_E2E_CHANNEL=chromium to use Playwright's bundled browser
```

Run the backend suite on its own: concurrent Terraform-heavy jobs on the same machine can make provider plugin start-up time out (see limitations).

## Results recorded on 2026-10-29 (macOS 15.6, Apple Silicon, Terraform 1.17.0, AWS provider 6.70.0)

| Check | Result |
|---|---|
| Backend pytest | **116 passed** on the final code. Network to the Terraform registry was intermittent on the test machine: the first full run stopped at one `terraform init` that failed with `read: can't assign requested address`; the remaining tests were re-run and two more `init` calls failed the same way; those three variants then passed when re-run on their own. No assertion failed. |
| ruff check / ruff format --check / mypy | clean / clean / no issues (40 files) |
| Frontend ESLint / tsc | clean / clean |
| Vitest | 7 passed |
| `next build` | success |
| Playwright full journey | 1 passed (≈ 4.4 min), no console errors, no failed asset requests; refreshed all 13 screenshots |
| Real AWS deployment | **not performed** |
| Live Anthropic API call | **not performed** (no API key available) |
| PostgreSQL | **not tested** (Alembic migration verified on SQLite) |

## What the suites cover

**Policy engine** (`tests/test_policy_engine.py`)
- Positive: the real generated Balanced plan passes every enabled policy.
- Negative on a real plan containing a public database, SSH from `0.0.0.0/0` and a wildcard IAM policy: each is detected with resource, expected/actual values, requirement and remediation; the scan blocks.
- New policies: log retention (lifecycle and log groups, 0 = never expire), alarms that must notify a subscribed topic, alert topic encrypted with a customer-managed key (AWS-managed SNS key rejected), off-hours schedules.
- Targeted negative/positive tests for SG ingress (22/3389/5432/8080, IPv6, all ports, allowed 443 on a public LB), DB subnet routing, DB SG sources, RDS encryption/backups/deletion/secrets (with redaction assertion), IAM wildcards/NotAction/privilege escalation/admin attachments/IAM users, S3 public access and encryption, ALB TLS/redirect/headers, region residency, credentials in user data (redacted), destructive changes, strict vs standard profile, and a crashing policy turning into a blocking error.

**Domain** (`tests/test_domain.py`)
- Interview tailoring: profile hints from the request (industry, geography, runtime, traffic pattern, uploads, ops team); industry/geography-driven recommendations (healthcare → regulated/HIPAA/6-year logs; Middle East → Frankfurt); refusals below the restore-window and PCI log-retention minimums and for malformed emails; off-hours question only for business-hours non-production; email extraction from free text; per-section progress; runtime → port and instance size, spiky → scaling headroom, off-hours → < 40 % of the compute cost, log retention floor; production without alerts flagged.
- Interview: hints are never answers; adaptive applicability; refused unsafe answers; HTTP-only allowed only for public dev data; residency and budget conflicts block completion with suggestions; revisions prune non-applicable answers; declined recommendations tracked; free-text parser including "ambiguous → unclear, never guessed".
- Compiler: refuses incomplete interviews; traceable fields; compliance/availability-driven requirements; database-less specs.
- Architecture & cost: option exclusion with reasons, budget-aware recommendation, itemised totals, regional multipliers, diagram components ↔ generated Terraform addresses.
- Traceability: failing/blocked/passing rules; simulated checks never raise the verification level; live failures override.

**Infrastructure** (`tests/test_infrastructure.py`)
- AI provider: missing credentials → demo; valid output accepted; out-of-allow-list values, missing values, malformed output, refusals and API errors rejected with deterministic fallback; prompt-injection text cannot produce an action; hint allow-list.
- Generator: determinism, secure defaults, no secrets, lean variant; **real `terraform init` + `validate` on eight variants** (including uploads + alerts, a staging business-hours schedule, and JVM/spiky without alerts or database).
- Runner/workspace: filename and ID validation, simulation environment cannot use host credentials, subcommand allow-list, `apply` refused outside real mode, timeout, cancellation, output cap.
- Execution-safety gate: rejects external/http data sources, provisioners, `file()`, backends, modules, `null_resource`; accepts generated configs; bypass attempts via URLs/comments caught; provider allow-list parsing.
- Plan review on a real plan and on synthetic destructive changes; live verification mapping with a fake boto3 session (including API errors recorded as errors, not passes).

**API scenario** (`tests/test_e2e_scenario.py`, real Terraform, simulation mode)
- Full lifecycle: request → interview (incl. free text) → compile → options → generate → validate → insecure change blocked (`POL-RDS-001`, `REQ-SEC-001` failing, plan rejected, approval refused) → revert → validate → apply refused without approval → approve → simulated apply → evidence (JSON + Markdown) → re-plan shows no changes → destroy plan → approval refused without typed confirmation → teardown.
- Plan changed after approval → apply refused (409). Wrong plan hash → approval refused.
- Unauthenticated (401), other sessions (404), missing CSRF (403), real mode from UI (403), rate limiting (429).
- A malicious `data "external"` edit is stopped by the safety gate and never executed (marker file not created).

**Frontend** — Vitest: HCL tokenizer (round-trip, classification, HTML treated as text) and diagram layout (only spec components, tier placement, wrapping shared services onto a second row). Playwright: the 15-step journey through the real UI — answering the tailored interview by clicking, typing free text for the industry and the alert email, and declining a recommendation — capturing `docs/screenshots/*` and failing on any console error or failed asset request; includes a mobile-width check of the project list.

## Not covered

- Real AWS apply/teardown and live verification against real APIs.
- Live LLM behaviour.
- Load testing; multi-process deployments (rate limiter and operation lock are per process).
- Accessibility beyond semantic HTML, labels and keyboard-reachable controls (no automated a11y audit was run).
