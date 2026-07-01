#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

DB_PATH="${DB_PATH:-run/constella.db}"
RAW_RETENTION_SECONDS="${RAW_RETENTION_SECONDS:-43200}"
SESSION_STALE_SECONDS="${SESSION_STALE_SECONDS:-300}"

uv run constella db maintain \
  --path "$DB_PATH" \
  --raw-retention-seconds "$RAW_RETENTION_SECONDS" \
  --session-stale-seconds "$SESSION_STALE_SECONDS"
