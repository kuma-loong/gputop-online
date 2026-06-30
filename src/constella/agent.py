from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import random
import socket
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import websockets

from . import __version__
from .cluster import SCHEMA_VERSION
from .collector import SnapshotCollector, validate_refresh_interval
from .schema import Snapshot, local_node_id

logger = logging.getLogger(__name__)

RECONNECT_DELAYS = (1.0, 2.0, 5.0, 15.0, 30.0)


@dataclass(slots=True)
class AgentConfig:
    node_id: str
    manager_url: str
    token: str
    refresh_interval: float = 1.0
    process_interval: float = 3.0
    state_file: Path = Path.home() / ".constella" / "run" / "agent-state.json"
    heartbeat_seconds: float = 10.0

    @classmethod
    def from_env(
        cls,
        *,
        node_id: str | None = None,
        manager_url: str | None = None,
        token: str | None = None,
        token_file: str | Path | None = None,
        refresh_interval: float | None = None,
        process_interval: float | None = None,
        state_file: str | Path | None = None,
    ) -> AgentConfig:
        resolved_token = token or os.environ.get("CONSTELLA_AGENT_TOKEN")
        resolved_token_file = token_file or os.environ.get("CONSTELLA_AGENT_TOKEN_FILE")
        if not resolved_token and resolved_token_file:
            resolved_token = Path(resolved_token_file).read_text(encoding="utf-8").strip()
        if not resolved_token:
            raise ValueError("agent token is required via CONSTELLA_AGENT_TOKEN or token file")

        resolved_url = manager_url or os.environ.get("CONSTELLA_MANAGER_URL")
        if not resolved_url:
            raise ValueError("manager url is required via CONSTELLA_MANAGER_URL")

        refresh = (
            float(refresh_interval)
            if refresh_interval is not None
            else float(os.environ.get("CONSTELLA_REFRESH_SECONDS", "1.0"))
        )
        process = (
            float(process_interval)
            if process_interval is not None
            else float(os.environ.get("CONSTELLA_PROCESS_SECONDS", "3.0"))
        )
        resolved_state_file = Path(
            state_file
            or os.environ.get("CONSTELLA_AGENT_STATE_FILE", "")
            or Path.home() / ".constella" / "run" / "agent-state.json"
        )
        return cls(
            node_id=node_id or local_node_id(),
            manager_url=resolved_url,
            token=resolved_token,
            refresh_interval=validate_refresh_interval(refresh),
            process_interval=max(1.0, process),
            state_file=resolved_state_file,
        )


@dataclass(slots=True)
class AgentStatus:
    node_id: str
    pid: int
    status: str = "starting"
    last_sample_at: float | None = None
    last_sent_at: float | None = None
    last_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "pid": self.pid,
            "status": self.status,
            "last_sample_at": self.last_sample_at,
            "last_sent_at": self.last_sent_at,
            "last_error": self.last_error,
        }


async def run_agent(config: AgentConfig, *, collector: SnapshotCollector | None = None) -> None:
    owned_collector = collector is None
    collector = collector or SnapshotCollector(
        refresh_interval=config.refresh_interval,
        process_interval=config.process_interval,
    )
    status = AgentStatus(node_id=config.node_id, pid=os.getpid())
    writer_task = asyncio.create_task(_state_writer(config.state_file, status), name="agent-state-writer")
    await collector.start()
    try:
        await _connection_loop(config, collector, status)
    finally:
        writer_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await writer_task
        if owned_collector:
            await collector.stop()
        write_state_file(config.state_file, status)


async def _connection_loop(
    config: AgentConfig,
    collector: SnapshotCollector,
    status: AgentStatus,
) -> None:
    attempt = 0
    while True:
        try:
            await _run_connection(config, collector, status)
            attempt = 0
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            status.status = "offline"
            status.last_error = str(exc)
            delay = reconnect_delay(attempt)
            attempt += 1
            logger.warning("agent connection failed; retrying in %.1fs: %s", delay, exc)
            await asyncio.sleep(delay)


async def _run_connection(
    config: AgentConfig,
    collector: SnapshotCollector,
    status: AgentStatus,
) -> None:
    headers = {"Authorization": f"Bearer {config.token}"}
    async with websockets.connect(
        config.manager_url,
        additional_headers=headers,
        max_queue=1,
        open_timeout=10,
    ) as websocket:
        status.status = "online"
        status.last_error = None
        await websocket.send(json.dumps(agent_hello(config)))
        receiver = asyncio.create_task(_receiver_loop(websocket, collector), name="agent-ws-receiver")
        sender = asyncio.create_task(_sender_loop(websocket, collector, config, status), name="agent-ws-sender")
        done, pending = await asyncio.wait(
            {receiver, sender},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        for task in pending:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        for task in done:
            task.result()


async def _receiver_loop(websocket: Any, collector: SnapshotCollector) -> None:
    async for raw in websocket:
        try:
            message = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if message.get("type") != "config":
            continue
        if "refresh_interval" in message:
            with contextlib.suppress(ValueError, TypeError):
                collector.set_refresh_interval(float(message["refresh_interval"]))
        if "process_interval" in message:
            with contextlib.suppress(ValueError, TypeError):
                collector.set_process_interval(float(message["process_interval"]))


async def _sender_loop(
    websocket: Any,
    collector: SnapshotCollector,
    config: AgentConfig,
    status: AgentStatus,
) -> None:
    last_snapshot_seq = 0
    message_seq = 0
    while True:
        snapshot = await collector.wait_for_update(
            last_snapshot_seq,
            timeout=config.heartbeat_seconds,
        )
        if snapshot and snapshot.seq > last_snapshot_seq:
            last_snapshot_seq = snapshot.seq
            status.last_sample_at = snapshot.timestamp
            message_seq += 1
            await websocket.send(json.dumps(agent_sample(config, message_seq, snapshot)))
            status.last_sent_at = time.time()
            continue

        message_seq += 1
        await websocket.send(json.dumps(agent_heartbeat(config, message_seq)))
        status.last_sent_at = time.time()


async def _state_writer(path: Path, status: AgentStatus) -> None:
    while True:
        write_state_file(path, status)
        await asyncio.sleep(2.0)


def write_state_file(path: Path, status: AgentStatus) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(status.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(payload + "\n", encoding="utf-8")
    os.chmod(temp_path, 0o600)
    os.replace(temp_path, path)


def agent_hello(config: AgentConfig) -> dict[str, Any]:
    return {
        "type": "hello",
        "schema_version": SCHEMA_VERSION,
        "node_id": config.node_id,
        "hostname": socket.gethostname(),
        "agent_version": __version__,
        "capabilities": {
            "nvml": True,
            "nvidia_smi_fallback": True,
            "process_cmdline": True,
        },
    }


def agent_sample(config: AgentConfig, seq: int, snapshot: Snapshot) -> dict[str, Any]:
    return {
        "type": "sample",
        "schema_version": SCHEMA_VERSION,
        "node_id": config.node_id,
        "seq": seq,
        "sampled_at": snapshot.timestamp,
        "refresh_interval": snapshot.refresh_interval,
        "process_interval": config.process_interval,
        "snapshot": snapshot.to_dict(),
    }


def agent_heartbeat(config: AgentConfig, seq: int) -> dict[str, Any]:
    return {
        "type": "heartbeat",
        "schema_version": SCHEMA_VERSION,
        "node_id": config.node_id,
        "seq": seq,
        "timestamp": time.time(),
    }


def reconnect_delay(attempt: int, *, jitter: float | None = None) -> float:
    base = RECONNECT_DELAYS[min(attempt, len(RECONNECT_DELAYS) - 1)]
    random_jitter = random.uniform(0, min(1.0, base * 0.15)) if jitter is None else jitter
    return base + random_jitter
