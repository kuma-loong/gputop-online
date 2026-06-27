#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

COUNT="${COUNT:-10}"

uv run python - <<'PY'
import statistics
import time

from gputop_online.nvml import NVMLSampler

count = int(__import__("os").environ.get("COUNT", "10"))
sampler = NVMLSampler()
elapsed = []
try:
    for _ in range(count):
        start = time.perf_counter()
        snapshot = sampler.sample()
        elapsed.append((time.perf_counter() - start) * 1000)
        time.sleep(0.05)
finally:
    sampler.close()

print(f"samples={count}")
print(f"source={snapshot.source} gpu_count={len(snapshot.gpus)}")
print(f"avg_ms={statistics.mean(elapsed):.2f} p95_ms={statistics.quantiles(elapsed, n=20)[18]:.2f}")
PY
