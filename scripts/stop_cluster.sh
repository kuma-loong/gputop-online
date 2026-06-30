#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

NODES="${NODES:-nodes.yaml}"

uv run constella cluster stop --nodes "$NODES"
