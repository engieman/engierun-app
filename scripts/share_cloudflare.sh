#!/usr/bin/env bash
set -euo pipefail

PORT="${PORT:-5055}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if ! command -v cloudflared >/dev/null 2>&1; then
  echo "cloudflared is required: brew install cloudflared" >&2
  exit 1
fi

PYTHON="${PYTHON:-$ROOT/.venv/bin/python}"
if [[ ! -x "$PYTHON" ]]; then
  echo "Missing virtual environment. Run: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
  exit 1
fi

"$ROOT/.venv/bin/gunicorn" --workers 2 --threads 2 --timeout 60 \
  --bind "127.0.0.1:${PORT}" app:app &
SERVER_PID=$!
trap 'kill "$SERVER_PID" 2>/dev/null || true' EXIT INT TERM

for _ in {1..40}; do
  if curl -fsS "http://127.0.0.1:${PORT}/health" >/dev/null; then
    break
  fi
  sleep 0.25
done
curl -fsS "http://127.0.0.1:${PORT}/health" >/dev/null

exec cloudflared tunnel --no-autoupdate --url "http://127.0.0.1:${PORT}"
