from __future__ import annotations

from constella.cluster import AgentHello, ClusterState, parse_agent_hello


def sample_message(node_id: str, seq: int, util: int = 50) -> dict[str, object]:
    return {
        "type": "sample",
        "schema_version": 1,
        "node_id": node_id,
        "seq": seq,
        "sampled_at": 100.0 + seq,
        "refresh_interval": 1.0,
        "process_interval": 3.0,
        "snapshot": {
            "ok": True,
            "source": "test",
            "hostname": f"{node_id}-host",
            "timestamp": 100.0 + seq,
            "elapsed_ms": 2.0,
            "gpus": [
                {
                    "index": 0,
                    "uuid": "GPU-abc",
                    "name": "NVIDIA Test",
                    "utilization_gpu": util,
                    "memory_total_mb": 100,
                    "memory_used_mb": 25,
                    "processes": [
                        {
                            "pid": 123,
                            "name": "python",
                            "task_name": "train.py",
                            "gpu_memory_mb": 25,
                            "kind": "compute",
                            "process_start_time": 90.0,
                        }
                    ],
                }
            ],
        },
    }


def test_cluster_state_registers_sample_and_drops_old_seq() -> None:
    state = ClusterState(local_node_id="manager")
    state.register_hello(AgentHello(node_id="node-a", hostname="host-a"), now=10.0)

    assert state.ingest_sample(sample_message("node-a", 2, util=40), received_at=12.0)
    assert not state.ingest_sample(sample_message("node-a", 1, util=99), received_at=13.0)

    cluster = state.snapshot(now=13.0)
    node = cluster.nodes[0]
    assert node.node_id == "node-a"
    assert node.seq == 2
    assert node.status == "online"
    assert node.gpus[0].gpu_id == "node-a:GPU-abc"
    assert node.gpus[0].utilization_gpu == 40


def test_cluster_state_marks_stale_offline_and_disconnect() -> None:
    state = ClusterState(local_node_id="manager", stale_after=5.0, offline_after=30.0)
    state.register_hello(AgentHello(node_id="node-a", hostname="host-a"), now=10.0)
    state.ingest_sample(sample_message("node-a", 1), received_at=10.0)

    assert state.snapshot(now=16.0).nodes[0].status == "stale"
    assert state.snapshot(now=41.0).nodes[0].status == "offline"

    state.ingest_heartbeat("node-a", seq=3, now=42.0)
    assert state.snapshot(now=42.1).nodes[0].status == "online"

    state.disconnect("node-a", now=43.0)
    assert state.snapshot(now=43.0).nodes[0].status == "offline"


def test_cluster_state_accepts_samples_after_agent_reconnect_resets_seq() -> None:
    state = ClusterState(local_node_id="manager")
    old_connection = object()
    new_connection = object()
    state.register_hello(
        AgentHello(node_id="node-a", hostname="host-a"),
        now=10.0,
        connection_id=old_connection,
    )
    assert state.ingest_sample(
        sample_message("node-a", 2508, util=40),
        received_at=11.0,
        connection_id=old_connection,
    )

    state.register_hello(
        AgentHello(node_id="node-a", hostname="host-a"),
        now=20.0,
        connection_id=new_connection,
    )
    state.disconnect("node-a", now=21.0, connection_id=old_connection)
    assert not state.ingest_sample(
        sample_message("node-a", 2509, util=99),
        received_at=22.0,
        connection_id=old_connection,
    )
    assert state.ingest_sample(
        sample_message("node-a", 1, util=55),
        received_at=23.0,
        connection_id=new_connection,
    )

    node = state.snapshot(now=23.0).nodes[0]
    assert node.status == "online"
    assert node.seq == 1
    assert node.gpus[0].utilization_gpu == 55


def test_cluster_state_keeps_static_hardware_from_hello() -> None:
    state = ClusterState(local_node_id="manager")
    hello = parse_agent_hello(
        {
            "type": "hello",
            "node_id": "node-a",
            "hostname": "host-a",
            "hardware": {
                "gpus": [
                    {
                        "index": 0,
                        "uuid": "GPU-abc",
                        "name": "NVIDIA H100 80GB HBM3",
                        "architecture": "Hopper",
                    }
                ]
            },
        }
    )

    state.register_hello(hello, now=10.0)
    state.ingest_sample(sample_message("node-a", 1), received_at=11.0)

    node = state.snapshot(now=11.0).nodes[0]
    assert node.hardware is not None
    assert node.hardware.gpus[0].architecture == "Hopper"
    assert not hasattr(node.gpus[0], "architecture")
    assert "hardware" not in node.to_dict()
    assert state.snapshot(now=11.0).to_dict()["nodes"][0]["hardware"]["gpus"][0]["architecture"] == "Hopper"
