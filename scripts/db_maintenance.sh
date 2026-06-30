#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

DB_PATH="${DB_PATH:-run/constella.db}"
ROLLUP_BUCKET_SECONDS="${ROLLUP_BUCKET_SECONDS:-10}"
RAW_RETENTION_SECONDS="${RAW_RETENTION_SECONDS:-43200}"
SESSION_STALE_SECONDS="${SESSION_STALE_SECONDS:-300}"

uv run constella db rollup --path "$DB_PATH" --bucket-seconds "$ROLLUP_BUCKET_SECONDS"
uv run constella db prune-raw --path "$DB_PATH" --retention-seconds "$RAW_RETENTION_SECONDS"
uv run constella db close-sessions --path "$DB_PATH" --stale-seconds "$SESSION_STALE_SECONDS"
