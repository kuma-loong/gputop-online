from __future__ import annotations

from constella.schema import (
    GpuInfo,
    GpuProcess,
    Snapshot,
    cluster_snapshot_from_nodes,
    process_session_id,
    snapshot_to_node_snapshot,
)


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


def test_snapshot_wraps_to_node_snapshot_with_stable_gpu_ids() -> None:
    snapshot = Snapshot(
        ok=True,
        source="test",
        hostname="host-a",
        timestamp=10.0,
        elapsed_ms=1.0,
        seq=7,
        refresh_interval=1.0,
        history={"0": {"gpu": [10.0], "memory": [20.0]}},
        gpus=[GpuInfo(index=0, uuid="GPU-shared", memory_total_mb=100, memory_used_mb=10)],
    )

    node = snapshot_to_node_snapshot(snapshot, node_id="node-a", received_at=11.0)

    assert node.node_id == "node-a"
    assert node.seq == 7
    assert node.gpus[0].gpu_id == "node-a:GPU-shared"
    assert set(node.history) == {"node-a:GPU-shared"}
    assert node.totals.memory_used_mb == 10


def test_manager_hostname_overrides_local_node_identity(monkeypatch) -> None:
    monkeypatch.setenv("CONSTELLA_MANAGER_HOSTNAME", "H100")
    snapshot = Snapshot(
        ok=True,
        source="test",
        hostname="default-host",
        timestamp=10.0,
        elapsed_ms=1.0,
        seq=7,
        gpus=[GpuInfo(index=0, uuid="GPU-local")],
    )

    node = snapshot_to_node_snapshot(snapshot)

    assert node.node_id == "H100"
    assert node.hostname == "H100"
    assert node.gpus[0].gpu_id == "H100:GPU-local"


def test_cluster_aggregation_keeps_same_index_gpus_distinct() -> None:
    left = snapshot_to_node_snapshot(
        Snapshot(
            ok=True,
            source="test",
            hostname="left",
            timestamp=1.0,
            elapsed_ms=1.0,
            seq=1,
            gpus=[GpuInfo(index=0, uuid="GPU-0", utilization_gpu=50, memory_total_mb=100)],
        ),
        node_id="node-left",
    )
    right = snapshot_to_node_snapshot(
        Snapshot(
            ok=True,
            source="test",
            hostname="right",
            timestamp=1.0,
            elapsed_ms=1.0,
            seq=1,
            gpus=[GpuInfo(index=0, uuid="GPU-0", utilization_gpu=100, memory_total_mb=100)],
        ),
        node_id="node-right",
    )

    cluster = cluster_snapshot_from_nodes([right, left], seq=3)

    assert cluster.totals.node_count == 2
    assert cluster.totals.gpu_count == 2
    assert cluster.totals.avg_gpu_utilization == 75.0
    assert {gpu.gpu_id for node in cluster.nodes for gpu in node.gpus} == {
        "node-left:GPU-0",
        "node-right:GPU-0",
    }


def test_process_session_id_uses_node_pid_and_start_time() -> None:
    first = GpuProcess(
        pid=123,
        name="python",
        gpu_memory_mb=1024,
        process_start_time=100.25,
    )
    second = GpuProcess(
        pid=123,
        name="python",
        gpu_memory_mb=1024,
        process_start_time=200.25,
    )

    assert process_session_id("node-a", first) == "node-a:123:100.250000"
    assert process_session_id("node-a", first) != process_session_id("node-a", second)
