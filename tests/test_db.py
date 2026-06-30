from __future__ import annotations

from fastapi.testclient import TestClient

from constella.app import create_app
from constella.cluster import ClusterState
from constella.collector import SnapshotCollector
from constella.db import AsyncDBSink, SQLiteSinkConfig, SQLiteStore
from constella.schema import GpuInfo, GpuProcess, NodeSnapshot, node_totals_from_gpus


def make_node_snapshot(sampled_at: float, *, gpu_util: int = 50) -> NodeSnapshot:
    process = GpuProcess(
        pid=1234,
        name="python",
        task_name="train.py",
        user="alice",
        cmdline="python train.py",
        cmdline_hash="hash",
        gpu_memory_mb=2048,
        process_start_time=90.0,
    )
    gpus = [
        GpuInfo(
            index=0,
            node_id="node-a",
            gpu_id="node-a:GPU-0",
            uuid="GPU-0",
            name="NVIDIA Test",
            utilization_gpu=gpu_util,
            utilization_mem=20,
            memory_total_mb=100,
            memory_used_mb=20,
            power_watts=100,
            power_limit_watts=200,
            temperature_c=40,
            processes=[process],
        ),
        GpuInfo(
            index=1,
            node_id="node-a",
            gpu_id="node-a:GPU-1",
            uuid="GPU-1",
            name="NVIDIA Test",
            utilization_gpu=gpu_util + 10,
            utilization_mem=30,
            memory_total_mb=100,
            memory_used_mb=30,
            power_watts=120,
            power_limit_watts=200,
            temperature_c=45,
            processes=[process],
        ),
    ]
    return NodeSnapshot(
        node_id="node-a",
        hostname="node-a-host",
        seq=int(sampled_at),
        sampled_at=sampled_at,
        received_at=sampled_at + 0.1,
        refresh_interval=1.0,
        process_interval=3.0,
        status="online",
        source="test",
        gpus=gpus,
        totals=node_totals_from_gpus(gpus),
        agent_version="0.2.0",
    )


def test_sqlite_store_writes_sessions_and_multi_gpu_usage(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "constella.db")
    store.open()
    try:
        store.write_node_snapshot(make_node_snapshot(100.0))

        con = store.connection
        assert con is not None
        assert con.execute("SELECT COUNT(*) FROM nodes").fetchone()[0] == 1
        assert con.execute("SELECT COUNT(*) FROM gpus").fetchone()[0] == 2
        assert con.execute("SELECT COUNT(*) FROM process_sessions").fetchone()[0] == 1
        assert con.execute("SELECT COUNT(*) FROM process_gpu_usages").fetchone()[0] == 2
        session = con.execute("SELECT task_name, sample_count FROM process_sessions").fetchone()
        assert dict(session) == {"task_name": "train.py", "sample_count": 1}
    finally:
        store.close()


def test_sqlite_store_rollup_and_raw_retention(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "constella.db")
    store.open()
    try:
        store.write_node_snapshot(make_node_snapshot(100.0, gpu_util=20), write_raw=True)
        store.write_node_snapshot(make_node_snapshot(105.0, gpu_util=40), write_raw=True)

        assert store.rollup_gpu_metrics(bucket_seconds=10) == 2
        rollup = store.connection.execute(
            """
            SELECT avg_gpu_utilization, max_gpu_utilization, sample_count
            FROM gpu_metric_rollups
            WHERE node_id='node-a' AND gpu_uuid='GPU-0'
            """
        ).fetchone()
        assert round(rollup["avg_gpu_utilization"], 1) == 30.0
        assert rollup["max_gpu_utilization"] == 40.0
        assert rollup["sample_count"] == 2

        assert store.prune_raw_snapshots(now=200.0, retention_seconds=50.0) == 2
    finally:
        store.close()


def test_db_history_api_returns_disabled_without_sink() -> None:
    client = TestClient(create_app(collector=SnapshotCollector(), cluster_state=ClusterState(local_node_id="local")))

    response = client.get("/api/history/gpu")

    assert response.status_code == 200
    assert response.json() == {"enabled": False, "items": []}


def test_db_history_api_reads_sink(tmp_path) -> None:
    sink = AsyncDBSink(SQLiteSinkConfig(path=tmp_path / "constella.db"))
    sink.store.open()
    sink.store.write_node_snapshot(make_node_snapshot(100.0))
    client = TestClient(
        create_app(
            collector=SnapshotCollector(),
            cluster_state=ClusterState(local_node_id="local"),
            db_sink=sink,
        )
    )

    response = client.get("/api/history/tasks?user=alice")

    assert response.status_code == 200
    payload = response.json()
    assert payload["enabled"] is True
    assert payload["items"][0]["task_name"] == "train.py"
    sink.store.close()
