#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8765}"
PID_FILE="$ROOT_DIR/run/gputop-online.pid"

export NO_PROXY="${NO_PROXY:-127.0.0.1,localhost}"
export no_proxy="${no_proxy:-127.0.0.1,localhost}"

if [[ -f "$PID_FILE" ]]; then
  PID="$(cat "$PID_FILE")"
  if kill -0 "$PID" >/dev/null 2>&1; then
    echo "process: running pid=$PID"
  else
    echo "process: stale pid=$PID"
  fi
else
  echo "process: not running"
fi

if command -v curl >/dev/null 2>&1; then
  curl -fsS "http://$HOST:$PORT/api/health" || true
  echo
fi
