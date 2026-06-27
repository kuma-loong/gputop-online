from __future__ import annotations

from gputop_online.schema import GpuInfo, Snapshot


def test_snapshot_totals() -> None:
    snapshot = Snapshot(
        ok=True,
        source="test",
        hostname="node",
        timestamp=1.0,
        elapsed_ms=2.0,
        gpus=[
            GpuInfo(
                index=0,
                utilization_gpu=50,
                memory_total_mb=100,
                memory_used_mb=25,
                power_watts=100,
                power_limit_watts=200,
                temperature_c=40,
            ),
            GpuInfo(
                index=1,
                utilization_gpu=100,
                memory_total_mb=100,
                memory_used_mb=50,
                power_watts=150,
                power_limit_watts=200,
                temperature_c=60,
            ),
        ],
    )

    totals = snapshot.totals()

    assert totals["gpu_count"] == 2
    assert totals["avg_gpu_utilization"] == 75.0
    assert totals["avg_memory_utilization"] == 37.5
    assert totals["power_watts"] == 250
    assert totals["max_temperature_c"] == 60
