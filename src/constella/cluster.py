from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

from .schema import (
    ClusterSnapshot,
    GpuHardwareInfo,
    GpuInfo,
    GpuProcess,
    NodeHardware,
    NodeSnapshot,
    OtherUserMemory,
    cluster_snapshot_from_nodes,
    gpu_global_id,
    node_totals_from_gpus,
)

SCHEMA_VERSION = 1


@dataclass(slots=True)
class AgentHello:
    node_id: str
    hostname: str
    agent_version: str | None = None
    capabilities: dict[str, Any] | None = None
    hardware: NodeHardware | None = None


@dataclass(slots=True)
class NodeRuntime:
    node_id: str
    hostname: str
    snapshot: NodeSnapshot
    last_seq: int = 0
    connected: bool = False
    last_seen_at: float = 0.0
    agent_version: str | None = None
    connection_id: object | None = None
    hardware: NodeHardware | None = None


class ClusterState:
    def __init__(
        self,
        *,
        local_node_id: str,
        stale_after: float | None = None,
        offline_after: float | None = None,
    ):
        self.local_node_id = local_node_id
        self.stale_after = stale_after
        self.offline_after = offline_after
        self.latest_by_node: dict[str, NodeRuntime] = {}
        self._seq = 0
        self._event = asyncio.Event()

    @property
    def seq(self) -> int:
        return self._seq

    async def wait_for_update(self, last_seq: int, timeout: float = 30.0) -> int:
        if self._seq > last_seq:
            return self._seq
        self._event.clear()
        if self._seq > last_seq:
            return self._seq
        try:
            await asyncio.wait_for(self._event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            return self._seq
        return self._seq

    def register_hello(
        self,
        hello: AgentHello,
        *,
        now: float | None = None,
        connection_id: object | None = None,
    ) -> None:
        seen_at = now if now is not None else time.time()
        runtime = self.latest_by_node.get(hello.node_id)
        if runtime is None:
            snapshot = NodeSnapshot(
                node_id=hello.node_id,
                hostname=hello.hostname,
                seq=0,
                sampled_at=seen_at,
                received_at=seen_at,
                refresh_interval=1.0,
                process_interval=3.0,
                status="online",
                source="none",
                agent_version=hello.agent_version,
                hardware=hello.hardware,
            )
            runtime = NodeRuntime(
                node_id=hello.node_id,
                hostname=hello.hostname,
                snapshot=snapshot,
                connected=True,
                last_seen_at=seen_at,
                agent_version=hello.agent_version,
                connection_id=connection_id,
                hardware=hello.hardware,
            )
            self.latest_by_node[hello.node_id] = runtime
        else:
            runtime.hostname = hello.hostname
            runtime.connected = True
            runtime.last_seen_at = seen_at
            runtime.last_seq = 0
            runtime.connection_id = connection_id
            runtime.agent_version = hello.agent_version or runtime.agent_version
            runtime.hardware = hello.hardware or runtime.hardware
            runtime.snapshot.hostname = hello.hostname
            runtime.snapshot.agent_version = runtime.agent_version
            runtime.snapshot.hardware = runtime.hardware
        self._bump()

    def ingest_sample(
        self,
        message: dict[str, Any],
        *,
        received_at: float | None = None,
        connection_id: object | None = None,
    ) -> bool:
        node_id = str(message.get("node_id") or "")
        if not node_id:
            raise ValueError("agent sample is missing node_id")
        seq = int(message.get("seq") or 0)
        runtime = self.latest_by_node.get(node_id)
        if runtime and not self._connection_matches(runtime, connection_id):
            return False
        if runtime and seq <= runtime.last_seq:
            return False

        now = received_at if received_at is not None else time.time()
        snapshot = node_snapshot_from_agent_sample(
            message,
            received_at=now,
            hostname=runtime.hostname if runtime else None,
            agent_version=runtime.agent_version if runtime else None,
            hardware=runtime.hardware if runtime else None,
        )
        self.latest_by_node[node_id] = NodeRuntime(
            node_id=node_id,
            hostname=snapshot.hostname,
            snapshot=snapshot,
            last_seq=seq,
            connected=True,
            last_seen_at=now,
            agent_version=snapshot.agent_version,
            connection_id=connection_id,
            hardware=snapshot.hardware,
        )
        self._bump()
        return True

    def ingest_heartbeat(
        self,
        node_id: str,
        *,
        seq: int | None = None,
        now: float | None = None,
        connection_id: object | None = None,
    ) -> None:
        runtime = self.latest_by_node.get(node_id)
        if runtime is None:
            seen_at = now if now is not None else time.time()
            self.register_hello(
                AgentHello(node_id=node_id, hostname=node_id, agent_version=None),
                now=seen_at,
                connection_id=connection_id,
            )
            runtime = self.latest_by_node[node_id]
        if not self._connection_matches(runtime, connection_id):
            return
        runtime.connected = True
        runtime.last_seen_at = now if now is not None else time.time()
        if seq is not None:
            runtime.last_seq = max(runtime.last_seq, seq)
        self._bump()

    def disconnect(
        self,
        node_id: str,
        *,
        now: float | None = None,
        connection_id: object | None = None,
    ) -> None:
        runtime = self.latest_by_node.get(node_id)
        if runtime is None:
            return
        if not self._connection_matches(runtime, connection_id):
            return
        runtime.connected = False
        runtime.last_seen_at = now if now is not None else runtime.last_seen_at
        self._bump()

    def snapshot(self, *, now: float | None = None) -> ClusterSnapshot:
        timestamp = now if now is not None else time.time()
        nodes = [self._runtime_snapshot(runtime, timestamp) for runtime in self.latest_by_node.values()]
        return cluster_snapshot_from_nodes(nodes, seq=self._seq, timestamp=timestamp)

    def _runtime_snapshot(self, runtime: NodeRuntime, now: float) -> NodeSnapshot:
        snapshot = runtime.snapshot
        snapshot.status = self._status(runtime, now)
        snapshot.received_at = runtime.last_seen_at or snapshot.received_at
        return snapshot

    def _status(self, runtime: NodeRuntime, now: float) -> str:
        if not runtime.connected:
            return "offline"
        elapsed = now - runtime.last_seen_at
        refresh = max(runtime.snapshot.refresh_interval, 0.1)
        stale_after = self.stale_after if self.stale_after is not None else max(3 * refresh, 5.0)
        offline_after = (
            self.offline_after if self.offline_after is not None else max(10 * refresh, 30.0)
        )
        if elapsed > offline_after:
            return "offline"
        if elapsed > stale_after:
            return "stale"
        if runtime.snapshot.error:
            return "error"
        return "online"

    def _connection_matches(self, runtime: NodeRuntime, connection_id: object | None) -> bool:
        if connection_id is None or runtime.connection_id is None:
            return True
        return connection_id is runtime.connection_id

    def _bump(self) -> None:
        self._seq += 1
        self._event.set()


def parse_agent_hello(message: dict[str, Any]) -> AgentHello:
    if message.get("type") != "hello":
        raise ValueError("first agent message must be hello")
    node_id = str(message.get("node_id") or "").strip()
    if not node_id:
        raise ValueError("agent hello is missing node_id")
    hostname = str(message.get("hostname") or node_id)
    capabilities = message.get("capabilities")
    hardware = _hardware_from_dict(message.get("hardware"))
    return AgentHello(
        node_id=node_id,
        hostname=hostname,
        agent_version=message.get("agent_version"),
        capabilities=capabilities if isinstance(capabilities, dict) else None,
        hardware=hardware,
    )


def node_snapshot_from_agent_sample(
    message: dict[str, Any],
    *,
    received_at: float,
    hostname: str | None = None,
    agent_version: str | None = None,
    hardware: NodeHardware | None = None,
) -> NodeSnapshot:
    if message.get("type") != "sample":
        raise ValueError("agent message is not a sample")
    node_id = str(message.get("node_id") or "").strip()
    if not node_id:
        raise ValueError("agent sample is missing node_id")
    payload = message.get("snapshot")
    if not isinstance(payload, dict):
        raise ValueError("agent sample is missing snapshot")

    gpus = [_gpu_from_dict(node_id, item) for item in payload.get("gpus", []) if isinstance(item, dict)]
    sampled_at = float(message.get("sampled_at") or payload.get("timestamp") or received_at)
    refresh_interval = float(message.get("refresh_interval") or payload.get("refresh_interval") or 1.0)
    process_interval = float(message.get("process_interval") or payload.get("process_interval") or 3.0)
    history = _history_by_gpu_id(node_id, payload.get("history"), gpus)
    return NodeSnapshot(
        node_id=node_id,
        hostname=str(payload.get("hostname") or hostname or node_id),
        seq=int(message.get("seq") or payload.get("seq") or 0),
        sampled_at=sampled_at,
        received_at=received_at,
        refresh_interval=refresh_interval,
        process_interval=process_interval,
        status="online" if payload.get("ok", True) else "error",
        source=str(payload.get("source") or "none"),
        gpus=gpus,
        totals=node_totals_from_gpus(gpus),
        error=payload.get("error"),
        agent_version=agent_version,
        driver_version=payload.get("driver_version"),
        cuda_driver_version=payload.get("cuda_driver_version"),
        nvml_version=payload.get("nvml_version"),
        elapsed_ms=float(payload.get("elapsed_ms") or 0.0),
        history=history,
        hardware=hardware,
    )


def _hardware_from_dict(payload: Any) -> NodeHardware | None:
    if not isinstance(payload, dict):
        return None
    gpus = [
        GpuHardwareInfo(
            index=int(item.get("index") or 0),
            uuid=str(item.get("uuid") or "unknown"),
            name=str(item.get("name") or "unknown"),
            architecture=item.get("architecture") if item.get("architecture") else None,
        )
        for item in payload.get("gpus", [])
        if isinstance(item, dict)
    ]
    return NodeHardware(gpus=gpus) if gpus else None


def _gpu_from_dict(node_id: str, data: dict[str, Any]) -> GpuInfo:
    processes = [
        _process_from_dict(item) for item in data.get("processes", []) if isinstance(item, dict)
    ]
    other_users = [
        OtherUserMemory(
            user=str(item.get("user") or "?"),
            process_count=int(item.get("process_count") or 0),
            total_memory_mb=int(item.get("total_memory_mb") or 0),
            runtime_seconds=item.get("runtime_seconds"),
        )
        for item in data.get("other_users", [])
        if isinstance(item, dict)
    ]
    gpu = GpuInfo(
        index=int(data.get("index") or 0),
        node_id=node_id,
        uuid=str(data.get("uuid") or "unknown"),
        name=str(data.get("name") or "unknown"),
        pci_bus_id=data.get("pci_bus_id"),
        utilization_gpu=int(data.get("utilization_gpu") or 0),
        utilization_mem=int(data.get("utilization_mem") or 0),
        memory_total_mb=int(data.get("memory_total_mb") or 0),
        memory_used_mb=int(data.get("memory_used_mb") or 0),
        memory_free_mb=int(data.get("memory_free_mb") or 0),
        temperature_c=int(data.get("temperature_c") or 0),
        power_watts=float(data.get("power_watts") or 0.0),
        power_limit_watts=float(data.get("power_limit_watts") or 0.0),
        clock_sm_mhz=data.get("clock_sm_mhz"),
        clock_mem_mhz=data.get("clock_mem_mhz"),
        max_clock_sm_mhz=data.get("max_clock_sm_mhz"),
        max_clock_mem_mhz=data.get("max_clock_mem_mhz"),
        pstate=data.get("pstate"),
        compute_mode=data.get("compute_mode"),
        mig_mode=data.get("mig_mode"),
        ecc_mode=data.get("ecc_mode"),
        processes=processes,
        other_users=other_users,
        error=data.get("error"),
    )
    gpu.gpu_id = gpu_global_id(node_id, gpu)
    return gpu


def _process_from_dict(data: dict[str, Any]) -> GpuProcess:
    return GpuProcess(
        pid=int(data.get("pid") or 0),
        name=str(data.get("name") or "?"),
        gpu_memory_mb=int(data.get("gpu_memory_mb") or 0),
        user=data.get("user"),
        task_name=data.get("task_name"),
        exe=data.get("exe"),
        cmdline=data.get("cmdline"),
        cmdline_hash=data.get("cmdline_hash"),
        kind=str(data.get("kind") or "compute"),
        runtime_seconds=data.get("runtime_seconds"),
        process_start_time=data.get("process_start_time"),
        detail_status=str(data.get("detail_status") or "unknown"),
        detail_error=data.get("detail_error"),
    )


def _history_by_gpu_id(
    node_id: str,
    payload: Any,
    gpus: list[GpuInfo],
) -> dict[str, dict[str, list[float]]]:
    if not isinstance(payload, dict):
        return {}
    index_to_gpu_id = {str(gpu.index): gpu.gpu_id or gpu_global_id(node_id, gpu) for gpu in gpus}
    result: dict[str, dict[str, list[float]]] = {}
    for key, series in payload.items():
        if not isinstance(series, dict):
            continue
        gpu_id = index_to_gpu_id.get(str(key), str(key))
        result[gpu_id] = {
            name: [float(value) for value in values]
            for name, values in series.items()
            if isinstance(values, list)
        }
    return result
