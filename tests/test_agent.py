from __future__ import annotations

import json
import stat

from constella.agent import (
    AgentConfig,
    AgentStatus,
    agent_heartbeat,
    agent_hello,
    agent_sample,
    reconnect_delay,
    write_state_file,
)
from constella.schema import GpuHardwareInfo, GpuInfo, NodeHardware, Snapshot


def test_agent_config_reads_env_and_token_file(tmp_path, monkeypatch) -> None:
    token_file = tmp_path / "token"
    token_file.write_text("secret\n", encoding="utf-8")
    state_file = tmp_path / "agent-state.json"
    monkeypatch.setenv("CONSTELLA_NODE_ID", "node-a")
    monkeypatch.setenv("CONSTELLA_MANAGER_URL", "ws://manager/api/agents/ws")
    monkeypatch.setenv("CONSTELLA_AGENT_TOKEN_FILE", str(token_file))
    monkeypatch.setenv("CONSTELLA_AGENT_STATE_FILE", str(state_file))

    config = AgentConfig.from_env()

    assert config.node_id == "node-a"
    assert config.manager_url == "ws://manager/api/agents/ws"
    assert config.token == "secret"
    assert config.state_file == state_file


def test_agent_protocol_messages_include_required_fields() -> None:
    config = AgentConfig(
        node_id="node-a",
        manager_url="ws://manager/api/agents/ws",
        token="secret",
        refresh_interval=1.0,
        process_interval=3.0,
    )
    snapshot = Snapshot(
        ok=True,
        source="test",
        hostname="node-a-host",
        timestamp=10.0,
        elapsed_ms=2.0,
        seq=4,
        refresh_interval=1.0,
        gpus=[GpuInfo(index=0, uuid="GPU-a", memory_total_mb=100, memory_used_mb=20)],
    )

    hardware = NodeHardware(
        gpus=[
            GpuHardwareInfo(
                index=0,
                uuid="GPU-a",
                name="NVIDIA H100 80GB HBM3",
                architecture="Hopper",
            )
        ]
    )
    hello = agent_hello(config, hardware=hardware)
    sample = agent_sample(config, 7, snapshot)
    heartbeat = agent_heartbeat(config, 8)

    assert hello["type"] == "hello"
    assert hello["node_id"] == "node-a"
    assert hello["capabilities"]["nvidia_smi_fallback"] is True
    assert hello["hardware"]["gpus"][0]["architecture"] == "Hopper"
    assert sample["type"] == "sample"
    assert sample["seq"] == 7
    assert sample["snapshot"]["gpus"][0]["uuid"] == "GPU-a"
    assert "architecture" not in sample["snapshot"]["gpus"][0]
    assert heartbeat["type"] == "heartbeat"
    assert heartbeat["seq"] == 8


def test_write_state_file_is_private_json(tmp_path) -> None:
    path = tmp_path / "run" / "agent-state.json"
    status = AgentStatus(
        node_id="node-a",
        pid=1234,
        status="online",
        last_sample_at=10.0,
        last_sent_at=11.0,
        last_error=None,
    )

    write_state_file(path, status)

    payload = json.loads(path.read_text(encoding="utf-8"))
    mode = stat.S_IMODE(path.stat().st_mode)
    assert payload["node_id"] == "node-a"
    assert payload["pid"] == 1234
    assert payload["status"] == "online"
    assert mode == 0o600


def test_reconnect_delay_caps_with_jitter() -> None:
    assert reconnect_delay(0, jitter=0.0) == 1.0
    assert reconnect_delay(3, jitter=0.5) == 15.5
    assert reconnect_delay(99, jitter=1.0) == 31.0
