#!/usr/bin/env bash
# Runs every time the codespace / dev container starts: launches the API and the
# web app in the background (logs in /tmp/iap-*.log) and waits until both answer.
set -euo pipefail
cd "$(dirname "$0")/.."

if ! curl -fsS http://127.0.0.1:8000/api/health >/dev/null 2>&1; then
  (cd backend && nohup .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 >/tmp/iap-backend.log 2>&1 &)
fi
if ! curl -fsS -o /dev/null http://127.0.0.1:3000/ 2>/dev/null; then
  (cd frontend && nohup npm start >/tmp/iap-frontend.log 2>&1 &)
fi

for _ in $(seq 1 60); do
  if curl -fsS http://127.0.0.1:3000/api/health >/dev/null 2>&1; then
    echo "Infrastructure as Prompt is running on port 3000 (simulation mode)."
    exit 0
  fi
  sleep 2
done
echo "The app did not start within 2 minutes. See /tmp/iap-backend.log and /tmp/iap-frontend.log." >&2
exit 1
