# Setup

## Fastest options

- **GitHub Codespaces** — the README's *Open in GitHub Codespaces* button uses `.devcontainer/`: a Python 3.12 image with Node.js 22 and Terraform 1.17.0 (installed by `.devcontainer/Dockerfile` and checked against HashiCorp's SHA-256 sums). `setup.sh` (on creation) installs dependencies, writes `backend/.env` with a random session key, and builds the frontend; `start.sh` (on every start) launches the API on port 8000 and the production web server on port 3000, which Codespaces forwards privately to your account. Logs: `/tmp/iap-backend.log`, `/tmp/iap-frontend.log`.
- **Docker Compose** — `docker compose up --build`, then http://localhost:3000. The backend image installs Terraform from releases.hashicorp.com and checks it against HashiCorp's published SHA-256 sums; it runs as a non-root user, generates a session key on first start, and keeps the database, workspaces and provider cache in the `iap-data` volume. Only port 3000 is published; the API is reached through the frontend's `/api` proxy. Checkov and Trivy are not included in the images (their pipeline steps show as unavailable; they are advisory only).

Both run in simulation mode with real deployment disabled. `scripts/smoke-test.sh <url>` checks a running instance, and the *Try-it environments* GitHub Actions workflow runs it against both setups on every push to `main` and every pull request.

## Requirements

| Tool | Version tested | Required |
|---|---|---|
| Python | 3.13 (3.12+ supported) | yes |
| Node.js / npm | 26.12 / 11.20 (Node 20+ should work) | yes |
| Terraform | 1.17.0 (≥ 1.6) | yes, for validation and plans |
| Checkov | 3.3.30 | optional (advisory scan) |
| Trivy | 0.76.1 | optional (advisory scan) |
| Google Chrome | any recent | only for the Playwright journey |
| PostgreSQL | — | optional; SQLite is the default |

## Backend

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
python3 -c "import secrets; print(secrets.token_urlsafe(48))"   # paste into IAP_SECRET_KEY in .env
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

The SQLite database and Terraform workspaces are created under `backend/var/` (git-ignored). On first validation the AWS provider is downloaded into `backend/var/plugin-cache/` (internet access to `registry.terraform.io` required once).

### PostgreSQL

```bash
export IAP_DATABASE_URL="postgresql+psycopg://iap:<password>@localhost:5432/iap"
cd backend && .venv/bin/python -m alembic upgrade head
```

### Optional scanners

```bash
# Checkov in its own virtualenv (it pins many dependencies)
python3 -m venv .tools/checkov-venv && .tools/checkov-venv/bin/pip install checkov
# The backend auto-detects .tools/checkov-venv, or set IAP_CHECKOV_CMD="/path/python -m checkov.main"
brew install trivy   # or see https://trivy.dev
```

If a scanner is missing, the pipeline reports it as **unavailable**.

### Optional AI assistance

```bash
IAP_AI_PROVIDER=anthropic
IAP_ANTHROPIC_API_KEY=<key>          # server-side only
IAP_ANTHROPIC_MODEL=claude-opus-5-5  # default
```

Without a key the interview runs in deterministic demo mode, which is labelled in the UI.

## Frontend

```bash
cd frontend
npm install
npm run dev        # http://localhost:3000 (proxies /api to IAP_BACKEND_URL, default http://127.0.0.1:8000)
# production
npm run build && npm run start
```

## Configuration reference

All backend settings are environment variables prefixed `IAP_` (see `backend/.env.example` and `backend/app/config.py`). Important ones:

| Variable | Default | Purpose |
|---|---|---|
| `IAP_SECRET_KEY` | dev placeholder (refused in production) | signs session cookies and CSRF tokens |
| `IAP_DATABASE_URL` | SQLite in `backend/var` | database |
| `IAP_COOKIE_SECURE` | false | set true behind HTTPS |
| `IAP_AI_PROVIDER` | demo | `demo` or `anthropic` |
| `IAP_TERRAFORM_BIN` | terraform | Terraform binary |
| `IAP_TOOL_TIMEOUT_SECONDS` | 300 | default subprocess timeout |
| `IAP_ALLOW_REAL_DEPLOY` | false | operator opt-in for real AWS |
| `IAP_AWS_PROFILE` / `IAP_AWS_EXPECTED_ACCOUNT_ID` | — | required for real AWS |
| `IAP_RATE_LIMIT_PIPELINE_PER_MINUTE` | 6 | per session |
