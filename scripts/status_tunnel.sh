#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PID_FILE="$ROOT_DIR/run/cloudflared.pid"
LOG_FILE="$ROOT_DIR/logs/cloudflared.log"

if [[ -f "$PID_FILE" ]]; then
  PID="$(cat "$PID_FILE")"
  if kill -0 "$PID" >/dev/null 2>&1; then
    echo "cloudflared: running pid=$PID"
  else
    echo "cloudflared: stale pid=$PID"
  fi
else
  echo "cloudflared: not running"
fi

if [[ -f "$LOG_FILE" ]]; then
  tail -n 20 "$LOG_FILE"
fi
