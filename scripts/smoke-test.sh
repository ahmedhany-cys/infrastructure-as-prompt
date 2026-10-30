#!/usr/bin/env bash
# Smoke test against a running instance: the web app, the /api proxy, a
# session with CSRF protection, and the start of the tailored interview.
# Usage: scripts/smoke-test.sh [base-url]   (default http://localhost:3000)
set -euo pipefail
base="${1:-http://localhost:3000}"
jar="$(mktemp)"
trap 'rm -f "$jar"' EXIT

echo "Waiting for $base ..."
for i in $(seq 1 90); do
  curl -fsS "$base/api/health" >/dev/null 2>&1 && break
  [ "$i" = 90 ] && { echo "API not reachable through $base/api" >&2; exit 1; }
  sleep 2
done

curl -fsS "$base/" | grep -q "Describe the infrastructure" || { echo "Landing page did not render" >&2; exit 1; }

csrf="$(curl -fsS -c "$jar" -b "$jar" -X POST "$base/api/session" | python3 -c 'import json,sys; print(json.load(sys.stdin)["csrf_token"])')"
pid="$(curl -fsS -c "$jar" -b "$jar" -H "x-csrf-token: $csrf" -H 'content-type: application/json' \
  -d '{"name":"Smoke Test","request":"An online store for customers in Europe, built with Django, with image uploads."}' \
  "$base/api/projects" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')"
curl -fsS -b "$jar" "$base/api/projects/$pid" | python3 -c '
import json, sys
view = json.load(sys.stdin)["interview"]
hints = {h["key"]: h["value"] for h in view["state"]["hints"]}
assert view["question"]["id"] == "industry", view["question"]["id"]
assert hints.get("industry") == "ecommerce" and hints.get("app_runtime") == "python", hints
assert [s["id"] for s in view["sections"]][0] == "business"
print("Interview started with tailored suggestions:", ", ".join(f"{k}={v}" for k, v in sorted(hints.items())))
'
echo "Smoke test passed for $base"
