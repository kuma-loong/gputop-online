#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

BIN="${CLOUDFLARED_BIN:-$HOME/.local/bin/cloudflared}"
ENV_FILE="${CLOUDFLARED_ENV_FILE:-$ROOT_DIR/run/cloudflared.env}"
LOG_DIR="$ROOT_DIR/logs"
RUN_DIR="$ROOT_DIR/run"
PID_FILE="$RUN_DIR/cloudflared.pid"
LOG_FILE="$LOG_DIR/cloudflared.log"

mkdir -p "$LOG_DIR" "$RUN_DIR"

if [[ ! -x "$BIN" ]]; then
  echo "cloudflared not found or not executable: $BIN" >&2
  exit 1
fi

if [[ ! -f "$ENV_FILE" ]]; then
  echo "missing env file: $ENV_FILE" >&2
  echo "expected CLOUDFLARED_TOKEN=... in that file" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

if [[ -z "${CLOUDFLARED_TOKEN:-}" && -z "${TUNNEL_TOKEN:-}" ]]; then
  echo "CLOUDFLARED_TOKEN or TUNNEL_TOKEN is empty" >&2
  exit 1
fi

export TUNNEL_TOKEN="${TUNNEL_TOKEN:-$CLOUDFLARED_TOKEN}"

if [[ -f "$PID_FILE" ]]; then
  PID="$(cat "$PID_FILE")"
  if kill -0 "$PID" >/dev/null 2>&1; then
    echo "already running: pid=$PID log=$LOG_FILE"
    exit 0
  fi
  rm -f "$PID_FILE"
fi

CMD=("$BIN" tunnel --no-autoupdate run)

if command -v setsid >/dev/null 2>&1; then
  nohup setsid "${CMD[@]}" >"$LOG_FILE" 2>&1 &
else
  nohup "${CMD[@]}" >"$LOG_FILE" 2>&1 &
fi

echo "$!" > "$PID_FILE"
chmod 600 "$PID_FILE"
echo "started cloudflared: pid=$(cat "$PID_FILE") log=$LOG_FILE"
