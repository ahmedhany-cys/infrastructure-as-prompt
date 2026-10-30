#!/bin/sh
# Generates a per-installation session-signing key on first start (kept in the
# data volume) unless IAP_SECRET_KEY is provided.
set -eu
if [ -z "${IAP_SECRET_KEY:-}" ]; then
  key_file="var/.secret_key"
  if [ ! -s "$key_file" ]; then
    umask 077
    python -c "import secrets; print(secrets.token_urlsafe(48))" > "$key_file"
  fi
  IAP_SECRET_KEY="$(cat "$key_file")"
  export IAP_SECRET_KEY
fi
exec "$@"
