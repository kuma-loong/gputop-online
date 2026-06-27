from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class GpuProcess:
    pid: int
    name: str
    gpu_memory_mb: int
    user: str | None = None
    cmdline: str | None = None
    kind: str = "compute"
    runtime_seconds: int | None = None


@dataclass(slots=True)
class OtherUserMemory:
    user: str
    process_count: int
    total_memory_mb: int
    runtime_seconds: int | None = None


@dataclass(slots=True)
class GpuInfo:
    index: int
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
