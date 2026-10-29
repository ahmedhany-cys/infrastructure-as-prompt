# API reference

Interactive OpenAPI docs are served at `http://localhost:8000/api/docs` while the backend runs. All routes are under `/api`. Every route except `POST /api/session`, `GET /api/health` and `GET /api/system` requires the session cookie; every non-GET route also requires the `X-CSRF-Token` header returned by `POST /api/session`. Requests for another session's project return **404**.

## Session & system

| Method | Path | Description |
|---|---|---|
| POST | `/session` | Create (or resume) a workspace session; sets cookies, returns `{csrf_token}` |
| GET | `/session` | Current session and CSRF token |
| GET | `/system` | AI mode label, tool availability (terraform/checkov/trivy), whether real deploys are enabled |
| GET | `/health` | Liveness |

## Projects, interview, requirements, architecture

| Method | Path | Description |
|---|---|---|
| GET | `/projects` | Project summaries (status, last scan, findings, deployment, cost) |
| POST | `/projects` | `{name, request}` → creates project, extracts hints, starts interview |
| GET | `/projects/{id}` | Detail incl. interview view (current question with its `section`, overall `progress`, per-section progress in `sections`, and `question_sections`), requirements spec, architecture spec, settings |
| DELETE | `/projects/{id}` | Delete (refused while real AWS resources are managed) |
| POST | `/projects/{id}/interview/answer` | `{question_id, value? \| text? \| accept_recommendation?}` |
| POST | `/projects/{id}/interview/explain` | `{question_id}` → adds an explanation to the transcript |
| GET | `/projects/{id}/interview/questions/{qid}` | Question view (for revising an answer) |
| POST | `/projects/{id}/requirements/compile` | Interview → requirements spec (new revision) + architecture options |
| POST | `/projects/{id}/architecture/select` | `{option_id, confirm_discard_edits?}` → generates Terraform |
| PATCH | `/projects/{id}/settings` | name, description, policy_profile, deployment_mode (aws only if server allows), acm_certificate_arn, region/budget (re-opens requirements) |

## Terraform

| Method | Path | Description |
|---|---|---|
| GET | `/projects/{id}/terraform` | Effective files, generated files, edited file names, lock file, revision, available insecure test scenarios |
| PUT | `/projects/{id}/terraform/files/{name}` | `{content}` save a manual edit (`.tf` only, ≤ 200 KB) |
| DELETE | `/projects/{id}/terraform/files/{name}` | Revert to the generated version |
| POST | `/projects/{id}/terraform/insecure-change` | `{scenario: public_database \| open_ssh \| wildcard_iam}` — documented deliberate misconfiguration |
| GET | `/projects/{id}/terraform/download` | ZIP of the project files (+ lock file, .gitignore) |

## Validation, operations, plans, deployments

| Method | Path | Description |
|---|---|---|
| POST | `/projects/{id}/validate` | Start the pipeline → `202 {operation_id}` (rate-limited) |
| GET | `/operations/{op}` | Status, progress, log, result, error |
| POST | `/operations/{op}/cancel` | Request cancellation |
| GET | `/projects/{id}/operations` | Recent operations |
| GET | `/projects/{id}/scans/latest` | Steps, policy results, external findings, summary, `stale` flag |
| GET | `/projects/{id}/scans` | Scan history |
| GET | `/projects/{id}/plans` | Plans with review; `latest_apply`, `latest_destroy` |
| POST | `/projects/{id}/plans/{plan}/approve` | `{plan_sha256, acknowledge_destructive?, confirmation_text?, account_confirmation?}` |
| POST | `/projects/{id}/plans/{plan}/apply` | Apply an approved plan → `202 {operation_id}` |
| POST | `/projects/{id}/teardown/plan` | Create a destroy plan → `202 {operation_id}` |
| GET | `/projects/{id}/deployments` | Deployments with resources and verification checks |
| GET | `/projects/{id}/evidence?format=json\|md\|json-download` | Evidence report |
| GET | `/projects/{id}/audit` | Audit log |

## Error semantics

| Status | Meaning |
|---|---|
| 400 | Invalid input or missing confirmation (e.g. destructive plan without typed project name) |
| 401 | No session |
| 403 | Missing/invalid CSRF token; unapproved plan; real mode disabled |
| 404 | Not found **or belongs to another session** |
| 409 | State conflict: interview incomplete, plan superseded or changed after approval, plan blocked by policy, another operation running |
| 422 | Schema validation error (field names only, no submitted values) |
| 429 | Rate limit |
