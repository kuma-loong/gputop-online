#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

export NO_PROXY="${NO_PROXY:-127.0.0.1,localhost}"
export no_proxy="${no_proxy:-127.0.0.1,localhost}"

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8765}"
REFRESH="${REFRESH:-1.0}"
PROCESS_REFRESH="${PROCESS_REFRESH:-3.0}"
AGENT_TOKEN_FILE="${AGENT_TOKEN_FILE:-}"
MANAGER_HOSTNAME="${MANAGER_HOSTNAME:-}"
NODES_CONFIG="${NODES_CONFIG:-nodes.yaml}"
DB_PATH="${DB_PATH:-}"
DB_QUEUE_SIZE="${DB_QUEUE_SIZE:-1024}"
RAW_SNAPSHOT_SECONDS="${RAW_SNAPSHOT_SECONDS:-0}"
LOG_DIR="$ROOT_DIR/logs"
RUN_DIR="$ROOT_DIR/run"
PID_FILE="$RUN_DIR/constella.pid"
LOG_FILE="$LOG_DIR/constella.log"

mkdir -p "$LOG_DIR" "$RUN_DIR"

if [[ -f "$PID_FILE" ]]; then
  PID="$(cat "$PID_FILE")"
  if kill -0 "$PID" >/dev/null 2>&1; then
    echo "already running: pid=$PID url=http://$HOST:$PORT"
    exit 0
  fi
  rm -f "$PID_FILE"
fi

if [[ -f uv.lock ]]; then
  uv sync --frozen
else
  uv sync
fi

if [[ ! -d frontend/dist ]]; then
  pushd frontend >/dev/null
  if [[ -f package-lock.json ]]; then
    npm ci
  else
    npm install
  fi
  npm run build
  popd >/dev/null
fi

if [[ -z "$MANAGER_HOSTNAME" && -f "$NODES_CONFIG" ]]; then
  MANAGER_HOSTNAME="$(
    PYTHONPATH="$ROOT_DIR/src" "$ROOT_DIR/.venv/bin/python" - "$NODES_CONFIG" <<'PY'
from pathlib import Path
import sys

from constella.cluster_control import load_manager_hostname

print(load_manager_hostname(Path(sys.argv[1])) or "")
PY
  )"
fi

if [[ -n "$AGENT_TOKEN_FILE" ]]; then
  export CONSTELLA_AGENT_TOKEN_FILE="$AGENT_TOKEN_FILE"
fi

if [[ -n "$MANAGER_HOSTNAME" ]]; then
  export CONSTELLA_MANAGER_HOSTNAME="$MANAGER_HOSTNAME"
fi

if [[ -n "$DB_PATH" ]]; then
  export CONSTELLA_DB_PATH="$DB_PATH"
  export CONSTELLA_DB_QUEUE_SIZE="$DB_QUEUE_SIZE"
  export CONSTELLA_RAW_SNAPSHOT_SECONDS="$RAW_SNAPSHOT_SECONDS"
fi

CMD=(
  "$ROOT_DIR/.venv/bin/constella"
  serve
  --host "$HOST"
  --port "$PORT"
  --refresh "$REFRESH"
  --process-refresh "$PROCESS_REFRESH"
)

if command -v setsid >/dev/null 2>&1; then
  nohup setsid "${CMD[@]}" >"$LOG_FILE" 2>&1 &
else
  nohup "${CMD[@]}" >"$LOG_FILE" 2>&1 &
fi

echo "$!" > "$PID_FILE"
echo "started: pid=$(cat "$PID_FILE") url=http://$HOST:$PORT log=$LOG_FILE"
