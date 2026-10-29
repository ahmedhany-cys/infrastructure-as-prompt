# Security model and threat model

IaP is a tool that generates and can apply infrastructure, so it is itself a high-value target. This document describes the controls in the MVP, what they protect against, and what they do not.

## Assets

1. AWS credentials and the target account (real mode).
2. The integrity of the plan that gets applied.
3. Project data: requirements, generated Terraform, plan files and state (may contain resource identifiers).
4. The correctness of verification claims (evidence reports are used to make decisions).

## Trust boundaries

| Boundary | Treated as untrusted |
|---|---|
| Browser → API | All request bodies, file edits, free text, filenames |
| API → AI model | Model output (always schema-validated and allow-listed) |
| API → terraform/checkov/trivy | Tool output (size-capped, parsed defensively, never executed) |
| Generated / edited Terraform | Never trusted: always planned and policy-evaluated before approval |

## Controls

### AI cannot act
- The model has **no tools**. It is called only to (a) suggest hints from the first message and (b) map a free-text reply to one of the current question's options.
- Output uses structured outputs (`messages.parse` with a Pydantic schema) and is then checked again: hint keys/values must be in an allow-list; an answer value must be one of the current options (or a number for numeric questions). Anything else — malformed JSON, out-of-range values, refusals, API errors — is discarded and the deterministic parser is used; the event is recorded in `ai_notes`.
- User text is wrapped in delimiters with a system instruction that it is data. Even a successful prompt injection can only produce one of the already-allowed option values — which the user then sees as their recorded answer.
- The model never writes Terraform, never decides policy outcomes, never approves, and never sets requirement status. These paths contain no model calls (see `traceability.py`, `policy/`, `deploy/service.py`).
- API keys are read server-side only (`IAP_ANTHROPIC_API_KEY`); they are never logged or sent to the browser. Without a key the app runs in an explicitly labelled demo mode.

### Command execution
- **Configuration safety gate** (`terraform/safety.py`): before Terraform runs, configurations are rejected if they contain provisioners, `external`/`http`/`local_file` data sources, `null_resource`/`terraform_data`, modules, `backend`/`cloud` blocks, or filesystem functions (`file`, `templatefile`, `fileset`, …). After `init`, `terraform providers` must list only `registry.terraform.io/hashicorp/aws`.
- Only `terraform {version, fmt, init, validate, plan, show, apply, providers}` can run; `apply` is refused unless the workspace is in real AWS mode **and** called from the approval workflow.
- `subprocess.Popen` with argv lists; no shell; arguments are constructed by the application.
- Minimal environment. Simulation runs get placeholder credentials and `AWS_SHARED_CREDENTIALS_FILE`/`AWS_CONFIG_FILE` set to `/dev/null`, so host credentials cannot be used even if present.
- Timeouts, output caps (JSON commands fail loudly if truncated), cancellation and process-group termination.
- Workspace paths are derived from validated hex project IDs; editable file names are allow-listed (`^[a-z0-9_][a-z0-9_.-]{0,60}\.tf$`, no `..`, no `/`, no `simulation*`).
- External scanners run on a temporary copy containing only `.tf` files.

### Deployment safety
- Real deployment is **off by default** and can only be enabled by the server operator (`IAP_ALLOW_REAL_DEPLOY=true` + `IAP_AWS_EXPECTED_ACCOUNT_ID` + an AWS profile). The UI cannot enable it, and AWS keys are never accepted through the UI or API.
- Generated providers pin `allowed_account_ids = [var.aws_account_id]`; real-mode approval also requires typing the expected account ID.
- Approval binds to the plan file's SHA-256 and the configuration hash. At apply time both are recomputed; mismatch → the plan is marked `superseded` and a new review is required. Only the latest plan can be approved/applied.
- Plans with blocking policy findings cannot be approved. Destructive plans (any delete/replace) require a separate acknowledgement and the typed project name.
- Stateful resource destruction is also reported by policy `POL-CHG-001`.
- Projects that still manage real resources cannot be deleted.

### Web application
- Anonymous workspace sessions: HttpOnly, SameSite=Lax, HMAC-signed cookie. Projects are scoped to the session; other sessions receive 404 (no existence oracle).
- CSRF: every non-GET request needs `X-CSRF-Token`, an HMAC of the session ID (double-submit with server verification). Custom headers also force a CORS preflight; CORS is restricted to the configured origin.
- Rate limits per session for pipeline/apply (default 6/min) and interview calls (60/min).
- Pydantic validation on every body; validation errors echo field names, never submitted values. Unhandled errors return a generic message.
- Output encoding: React escapes all text; the HCL highlighter produces text tokens (tested with `<script>` content); there is no `dangerouslySetInnerHTML`.
- Security headers on API and frontend (`nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`, `Permissions-Policy`), `Cache-Control: no-store` on API responses.
- Secrets: `IAP_SECRET_KEY` must be set in production (startup refuses the development default). `.env` files are git-ignored; only placeholders are committed. Policy findings redact secret values (`<redacted>`), and tests assert the raw value never appears.
- Audit log entries for project creation, interview changes, compiles, architecture selection, file edits, insecure test changes, pipeline runs, approvals/refusals, deployments, cancellations and deletion.

## Threats and residual risk

| Threat | Mitigation | Residual risk |
|---|---|---|
| Prompt injection in the request or answers | Model output allow-listed; model cannot act | User could be misled by an AI-interpreted answer — it is labelled "AI-interpreted" and editable |
| Malicious Terraform edits that execute code or read server files at plan time (`data "external"`, `data "http"`, provisioners, `null_resource`, modules, backends, `file()`/`templatefile()`) | **Configuration safety gate** before `init`/`plan` rejects these constructs (generated or edited, no comment/string stripping to avoid bypasses); after `init`, a **provider allow-list** stops the run if anything other than `hashicorp/aws` is required. Tested end-to-end: an `external` data source never reaches Terraform. | Lexical gate: new Terraform features that execute code would need adding. The AWS provider itself can still make arbitrary AWS API calls in real mode — bounded by the deployment role's permissions. |
| Approving one plan, applying another | Plan + config hashes re-verified at approval and apply | Local disk tampering by someone with server access |
| Reuse of host credentials in simulation | Credential files disabled, placeholder keys | — |
| CSRF / cross-project access | CSRF token, session-scoped queries, 404s | No user accounts: anyone with the browser profile has the workspace |
| Plan/state files leaking data | Stored under `backend/var/` (git-ignored); passwords are never generated into config | Local state is plaintext; use an encrypted S3 backend for real use |
| Denial of service via expensive runs | Rate limits, one operation per project, timeouts | In-memory limiter resets on restart and is per-process |
| Template injection through interview answers (for example a crafted alert email) | Every answer is validated against an allow-list of option values or a strict pattern (CIDR, email without quotes, `$` or `{`) before it can reach a template; templates use `StrictUndefined` | The alert email is stored in the generated `variables.tf` and in project data; use a team mailbox rather than a personal address |
| Weak controls on new tailored resources | Uploads bucket gets the same public-access block, encryption, versioning and TLS-only policy as the log bucket and is checked by the same S3 policies; its IAM policy is scoped to one bucket (checked by POL-IAM-001); the alert topic uses a customer-managed KMS key with rotation (POL-OPS-002) | The KMS key policy grants the account root `kms:*` (the AWS default pattern), so key access is governed by IAM in the account |
| Supply chain (providers) | Provider version range pinned; lock file kept and exported | Lock file hashes are only for the platform that ran `init` |

## Verification claims

Static checks prove only that the **planned configuration** has certain properties. The evidence model keeps these distinct:

- *estimate* — cost model output
- *static_config* — policies pass on the Terraform plan
- *simulated* — checks against simulated state (recorded, never counted)
- *live_inspection* — read-only AWS API calls after a real deployment (implemented and unit-tested with fake clients; **not yet exercised against a real account**)

No requirement is ever marked verified because `terraform apply` succeeded.
