#!/usr/bin/env bash
# Runs once when the codespace / dev container is created.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> Backend dependencies"
python -m venv backend/.venv
backend/.venv/bin/pip install --quiet --upgrade pip
backend/.venv/bin/pip install --quiet -r backend/requirements.txt

if [ ! -f backend/.env ]; then
  echo "==> Creating backend/.env with a random session-signing key"
  secret="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
  # Codespaces serves the forwarded port over HTTPS, so cookies can be Secure there.
  secure=false
  [ "${CODESPACES:-}" = "true" ] && secure=true
  (umask 077 && sed -e "s|^IAP_SECRET_KEY=.*|IAP_SECRET_KEY=${secret}|" \
      -e "s|^IAP_COOKIE_SECURE=.*|IAP_COOKIE_SECURE=${secure}|" \
      backend/.env.example > backend/.env)
fi

echo "==> Frontend dependencies and production build"
cd frontend
npm ci --no-audit --no-fund
npm run build
