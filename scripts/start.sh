#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

export NO_PROXY="${NO_PROXY:-127.0.0.1,localhost}"
export no_proxy="${no_proxy:-127.0.0.1,localhost}"

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8765}"
REFRESH="${REFRESH:-1.0}"
PROCESS_REFRESH="${PROCESS_REFRESH:-3.0}"
LOG_DIR="$ROOT_DIR/logs"
RUN_DIR="$ROOT_DIR/run"
PID_FILE="$RUN_DIR/gputop-online.pid"
LOG_FILE="$LOG_DIR/gputop-online.log"

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

CMD=(
  "$ROOT_DIR/.venv/bin/gputop-online"
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
