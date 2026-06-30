from __future__ import annotations

import copy
import hashlib
import os
import socket
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class GpuProcess:
    pid: int
    name: str
    gpu_memory_mb: int
    user: str | None = None
    task_name: str | None = None
    exe: str | None = None
    cmdline: str | None = None
    cmdline_hash: str | None = None
    kind: str = "compute"
    runtime_seconds: int | None = None
    process_start_time: float | None = None
    detail_status: str = "unknown"
    detail_error: str | None = None


@dataclass(slots=True)
class OtherUserMemory:
    user: str
    process_count: int
    total_memory_mb: int
    runtime_seconds: int | None = None


@dataclass(slots=True)
class GpuInfo:
    index: int
    node_id: str | None = None
    gpu_id: str | None = None
    uuid: str = "unknown"
    name: str = "unknown"
    pci_bus_id: str | None = None
    utilization_gpu: int = 0
    utilization_mem: int = 0
    memory_total_mb: int = 0
    memory_used_mb: int = 0
    memory_free_mb: int = 0
    temperature_c: int = 0
    power_watts: float = 0.0
    power_limit_watts: float = 0.0
    clock_sm_mhz: int | None = None
    clock_mem_mhz: int | None = None
    max_clock_sm_mhz: int | None = None
    max_clock_mem_mhz: int | None = None
    pstate: str | None = None
    compute_mode: str | None = None
    mig_mode: str | None = None
    ecc_mode: str | None = None
    processes: list[GpuProcess] = field(default_factory=list)
    other_users: list[OtherUserMemory] = field(default_factory=list)
    error: str | None = None

    @property
    def memory_percent(self) -> float:
        if self.memory_total_mb <= 0:
            return 0.0
        return round((self.memory_used_mb / self.memory_total_mb) * 100.0, 1)

    @property
    def power_percent(self) -> float:
        if self.power_limit_watts <= 0:
            return 0.0
        return round((self.power_watts / self.power_limit_watts) * 100.0, 1)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["memory_percent"] = self.memory_percent
        data["power_percent"] = self.power_percent
        return data


@dataclass(slots=True)
class Snapshot:
    ok: bool
    source: str
    hostname: str
    timestamp: float
    elapsed_ms: float
    gpus: list[GpuInfo] = field(default_factory=list)
    driver_version: str | None = None
    cuda_driver_version: str | None = None
    nvml_version: str | None = None
    error: str | None = None
    seq: int = 0
    refresh_interval: float = 1.0
    history: dict[str, dict[str, list[float]]] = field(default_factory=dict)

    def totals(self) -> dict[str, Any]:
        total_memory = sum(g.memory_total_mb for g in self.gpus)
        used_memory = sum(g.memory_used_mb for g in self.gpus)
        total_power_limit = sum(g.power_limit_watts for g in self.gpus)
        total_power = sum(g.power_watts for g in self.gpus)
        active_processes = sum(len(g.processes) for g in self.gpus)
        active_processes += sum(o.process_count for g in self.gpus for o in g.other_users)
        gpu_count = len(self.gpus)

        return {
            "gpu_count": gpu_count,
            "avg_gpu_utilization": round(
                sum(g.utilization_gpu for g in self.gpus) / gpu_count, 1
            )
            if gpu_count
            else 0.0,
            "avg_memory_utilization": round((used_memory / total_memory) * 100.0, 1)
            if total_memory
            else 0.0,
            "memory_used_mb": used_memory,
            "memory_total_mb": total_memory,
            "power_watts": round(total_power, 1),
            "power_limit_watts": round(total_power_limit, 1),
            "max_temperature_c": max((g.temperature_c for g in self.gpus), default=0),
            "active_processes": active_processes,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "source": self.source,
            "hostname": self.hostname,
            "timestamp": self.timestamp,
            "elapsed_ms": self.elapsed_ms,
            "driver_version": self.driver_version,
            "cuda_driver_version": self.cuda_driver_version,
            "nvml_version": self.nvml_version,
            "error": self.error,
            "seq": self.seq,
            "refresh_interval": self.refresh_interval,
            "totals": self.totals(),
            "gpus": [g.to_dict() for g in self.gpus],
            "history": self.history,
        }


@dataclass(slots=True)
class NodeTotals:
    gpu_count: int = 0
    active_processes: int = 0
    avg_gpu_utilization: float = 0.0
    avg_memory_utilization: float = 0.0
    memory_used_mb: int = 0
    memory_total_mb: int = 0
    power_watts: float = 0.0
    power_limit_watts: float = 0.0
    max_temperature_c: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class NodeSnapshot:
    node_id: str
    hostname: str
    seq: int
    sampled_at: float
    received_at: float | None
    refresh_interval: float
    process_interval: float
    status: str
    source: str
    gpus: list[GpuInfo] = field(default_factory=list)
    totals: NodeTotals = field(default_factory=NodeTotals)
    error: str | None = None
    agent_version: str | None = None
    driver_version: str | None = None
    cuda_driver_version: str | None = None
    nvml_version: str | None = None
    elapsed_ms: float = 0.0
    history: dict[str, dict[str, list[float]]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "hostname": self.hostname,
            "seq": self.seq,
            "sampled_at": self.sampled_at,
            "received_at": self.received_at,
            "refresh_interval": self.refresh_interval,
            "process_interval": self.process_interval,
            "status": self.status,
            "source": self.source,
            "gpus": [gpu.to_dict() for gpu in self.gpus],
            "totals": self.totals.to_dict(),
            "error": self.error,
            "agent_version": self.agent_version,
            "driver_version": self.driver_version,
            "cuda_driver_version": self.cuda_driver_version,
            "nvml_version": self.nvml_version,
            "elapsed_ms": self.elapsed_ms,
            "history": self.history,
        }


@dataclass(slots=True)
class ClusterTotals(NodeTotals):
    node_count: int = 0
    online_node_count: int = 0
    stale_node_count: int = 0
    offline_node_count: int = 0


@dataclass(slots=True)
class ClusterSnapshot:
    ok: bool
    seq: int
    timestamp: float
    nodes: list[NodeSnapshot] = field(default_factory=list)
    totals: ClusterTotals = field(default_factory=ClusterTotals)
    history: dict[str, dict[str, list[float]]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "seq": self.seq,
            "timestamp": self.timestamp,
            "nodes": [node.to_dict() for node in self.nodes],
            "totals": self.totals.to_dict(),
            "history": self.history,
        }


def cmdline_fingerprint(cmdline: str | None) -> str | None:
    if not cmdline:
        return None
    return hashlib.sha256(cmdline.encode("utf-8", errors="replace")).hexdigest()[:16]


def infer_task_name(
    *,
    cmdline: str | None = None,
    exe: str | None = None,
    comm: str | None = None,
    process_name: str | None = None,
    pid: int | None = None,
) -> str:
    if cmdline:
        parts = [part for part in cmdline.split() if part]
        for part in parts:
            basename = Path(part).name
            if basename.endswith((".py", ".sh", ".pl", ".R", ".ipynb")):
                return basename
        for part in parts:
            basename = Path(part).name
            if basename in {"torchrun", "accelerate", "python", "python3", "uvicorn"}:
                return basename
        if parts:
            return Path(parts[0]).name
    if exe:
        return Path(exe).name
    if comm:
        return comm
    if process_name:
        return Path(process_name).name
    return f"unknown:{pid}" if pid is not None else "unknown"


def process_session_id(node_id: str, process: GpuProcess) -> str:
    started = (
        f"{process.process_start_time:.6f}"
        if isinstance(process.process_start_time, float)
        else "unknown"
    )
    return f"{node_id}:{process.pid}:{started}"


def gpu_global_id(node_id: str, gpu: GpuInfo) -> str:
    if gpu.uuid and gpu.uuid != "unknown":
        return f"{node_id}:{gpu.uuid}"
    return f"{node_id}:index:{gpu.index}"


def local_node_id(default: str | None = None) -> str:
    return (
        os.environ.get("CONSTELLA_NODE_ID")
        or os.environ.get("CONSTELLA_MANAGER_HOSTNAME")
        or default
        or socket.gethostname()
        or "local"
    )


def local_hostname(default: str | None = None) -> str:
    return os.environ.get("CONSTELLA_MANAGER_HOSTNAME") or default or socket.gethostname() or "local"


def node_totals_from_gpus(gpus: list[GpuInfo]) -> NodeTotals:
    gpu_count = len(gpus)
    memory_total = sum(gpu.memory_total_mb for gpu in gpus)
    memory_used = sum(gpu.memory_used_mb for gpu in gpus)
    power_limit = sum(gpu.power_limit_watts for gpu in gpus)
    power_used = sum(gpu.power_watts for gpu in gpus)
    active_processes = sum(len(gpu.processes) for gpu in gpus)
    active_processes += sum(other.process_count for gpu in gpus for other in gpu.other_users)
    return NodeTotals(
        gpu_count=gpu_count,
        active_processes=active_processes,
        avg_gpu_utilization=round(sum(gpu.utilization_gpu for gpu in gpus) / gpu_count, 1)
        if gpu_count
        else 0.0,
        avg_memory_utilization=round((memory_used / memory_total) * 100.0, 1)
        if memory_total
        else 0.0,
        memory_used_mb=memory_used,
        memory_total_mb=memory_total,
        power_watts=round(power_used, 1),
        power_limit_watts=round(power_limit, 1),
        max_temperature_c=max((gpu.temperature_c for gpu in gpus), default=0),
    )


def snapshot_to_node_snapshot(
    snapshot: Snapshot,
    *,
    node_id: str | None = None,
    hostname: str | None = None,
    received_at: float | None = None,
    process_interval: float = 3.0,
    status: str | None = None,
    agent_version: str | None = None,
) -> NodeSnapshot:
    resolved_node_id = node_id or local_node_id(snapshot.hostname)
    resolved_hostname = hostname or (
        local_hostname(snapshot.hostname) if node_id is None else snapshot.hostname
    )
    gpus = copy.deepcopy(snapshot.gpus)
    history: dict[str, dict[str, list[float]]] = {}
    for gpu in gpus:
        gpu.node_id = resolved_node_id
        gpu.gpu_id = gpu_global_id(resolved_node_id, gpu)
        if str(gpu.index) in snapshot.history:
            history[gpu.gpu_id] = snapshot.history[str(gpu.index)]

    return NodeSnapshot(
        node_id=resolved_node_id,
        hostname=resolved_hostname,
        seq=snapshot.seq,
        sampled_at=snapshot.timestamp,
        received_at=received_at,
        refresh_interval=snapshot.refresh_interval,
        process_interval=process_interval,
        status=status or ("online" if snapshot.ok else "error"),
        source=snapshot.source,
        gpus=gpus,
        totals=node_totals_from_gpus(gpus),
        error=snapshot.error,
        agent_version=agent_version,
        driver_version=snapshot.driver_version,
        cuda_driver_version=snapshot.cuda_driver_version,
        nvml_version=snapshot.nvml_version,
        elapsed_ms=snapshot.elapsed_ms,
        history=history,
    )


def cluster_totals_from_nodes(nodes: list[NodeSnapshot]) -> ClusterTotals:
    gpus = [gpu for node in nodes if node.status != "offline" for gpu in node.gpus]
    totals = node_totals_from_gpus(gpus)
    return ClusterTotals(
        gpu_count=totals.gpu_count,
        active_processes=totals.active_processes,
        avg_gpu_utilization=totals.avg_gpu_utilization,
        avg_memory_utilization=totals.avg_memory_utilization,
        memory_used_mb=totals.memory_used_mb,
        memory_total_mb=totals.memory_total_mb,
        power_watts=totals.power_watts,
        power_limit_watts=totals.power_limit_watts,
        max_temperature_c=totals.max_temperature_c,
        node_count=len(nodes),
        online_node_count=sum(1 for node in nodes if node.status == "online"),
        stale_node_count=sum(1 for node in nodes if node.status == "stale"),
        offline_node_count=sum(1 for node in nodes if node.status == "offline"),
    )


def cluster_snapshot_from_nodes(
    nodes: list[NodeSnapshot],
    *,
    seq: int,
    timestamp: float | None = None,
) -> ClusterSnapshot:
    sorted_nodes = sorted(nodes, key=lambda node: node.node_id)
    history: dict[str, dict[str, list[float]]] = {}
    for node in sorted_nodes:
        history.update(node.history)
    return ClusterSnapshot(
        ok=any(node.status == "online" for node in sorted_nodes),
        seq=seq,
        timestamp=timestamp if timestamp is not None else time.time(),
        nodes=sorted_nodes,
        totals=cluster_totals_from_nodes(sorted_nodes),
        history=history,
    )
