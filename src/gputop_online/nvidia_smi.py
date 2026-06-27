from __future__ import annotations

import csv
import socket
import subprocess
import time
from io import StringIO
from typing import Any

from .procfs import process_runtime_seconds
from .schema import GpuInfo, GpuProcess, Snapshot

GPU_QUERY_FIELDS = [
    "index",
    "uuid",
    "name",
    "pci.bus_id",
    "driver_version",
    "temperature.gpu",
    "utilization.gpu",
    "utilization.memory",
    "memory.total",
    "memory.used",
    "memory.free",
    "power.draw",
    "power.limit",
    "clocks.sm",
    "clocks.mem",
    "pstate",
    "compute_mode",
    "mig.mode.current",
]


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if not value or value.upper() in {"N/A", "[N/A]", "NOT SUPPORTED"}:
        return None
    return value


def _to_int(value: str | None, default: int = 0) -> int:
    value = _clean(value)
    if value is None:
        return default
    try:
        return int(float(value))
    except ValueError:
        return default


def _to_float(value: str | None, default: float = 0.0) -> float:
    value = _clean(value)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def parse_gpu_query_csv(output: str) -> tuple[list[GpuInfo], str | None]:
    gpus: list[GpuInfo] = []
    driver_version: str | None = None
    reader = csv.reader(StringIO(output))

    for row in reader:
        if not row or all(not cell.strip() for cell in row):
            continue
        values = {field: row[i].strip() if i < len(row) else "" for i, field in enumerate(GPU_QUERY_FIELDS)}
        driver_version = driver_version or _clean(values.get("driver_version"))
        gpus.append(
            GpuInfo(
                index=_to_int(values.get("index")),
                uuid=_clean(values.get("uuid")) or "unknown",
                name=_clean(values.get("name")) or "unknown",
                pci_bus_id=_clean(values.get("pci.bus_id")),
                utilization_gpu=_to_int(values.get("utilization.gpu")),
                utilization_mem=_to_int(values.get("utilization.memory")),
                memory_total_mb=_to_int(values.get("memory.total")),
                memory_used_mb=_to_int(values.get("memory.used")),
                memory_free_mb=_to_int(values.get("memory.free")),
                temperature_c=_to_int(values.get("temperature.gpu")),
                power_watts=round(_to_float(values.get("power.draw")), 1),
                power_limit_watts=round(_to_float(values.get("power.limit")), 1),
                clock_sm_mhz=_to_int(values.get("clocks.sm")) or None,
                clock_mem_mhz=_to_int(values.get("clocks.mem")) or None,
                pstate=_clean(values.get("pstate")),
                compute_mode=_clean(values.get("compute_mode")),
                mig_mode=_clean(values.get("mig.mode.current")),
            )
        )

    return gpus, driver_version


def parse_process_query_csv(output: str) -> dict[str, list[GpuProcess]]:
    result: dict[str, list[GpuProcess]] = {}
    reader = csv.reader(StringIO(output))
    for row in reader:
        if len(row) < 4:
            continue
        uuid, pid, name, used_memory = [cell.strip() for cell in row[:4]]
        uuid = _clean(uuid) or "unknown"
        process = GpuProcess(
            pid=_to_int(pid),
            name=_clean(name) or "?",
            gpu_memory_mb=_to_int(used_memory),
            kind="compute",
        )
        if process.pid:
            process.runtime_seconds = process_runtime_seconds(process.pid)
            result.setdefault(uuid, []).append(process)
    return result


def sample(timeout: float = 2.5) -> Snapshot:
    started = time.monotonic()
    cmd = [
        "nvidia-smi",
        f"--query-gpu={','.join(GPU_QUERY_FIELDS)}",
        "--format=csv,noheader,nounits",
    ]
    output = subprocess.check_output(cmd, stderr=subprocess.PIPE, timeout=timeout, text=True)
    gpus, driver_version = parse_gpu_query_csv(output)

    try:
        proc_output = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-compute-apps=gpu_uuid,pid,process_name,used_memory",
                "--format=csv,noheader,nounits",
            ],
            stderr=subprocess.DEVNULL,
            timeout=timeout,
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        processes_by_uuid: dict[str, list[GpuProcess]] = {}
    else:
        processes_by_uuid = parse_process_query_csv(proc_output)

    for gpu in gpus:
        gpu.processes = processes_by_uuid.get(gpu.uuid, [])

    return Snapshot(
        ok=True,
        source="nvidia-smi",
        hostname=socket.gethostname(),
        timestamp=time.time(),
        elapsed_ms=round((time.monotonic() - started) * 1000, 1),
        gpus=gpus,
        driver_version=driver_version,
    )


def error_snapshot(error: str, source: str = "nvidia-smi") -> Snapshot:
    return Snapshot(
        ok=False,
        source=source,
        hostname=socket.gethostname(),
        timestamp=time.time(),
        elapsed_ms=0.0,
        error=error,
    )


def gpu_to_plain_dict(gpu: GpuInfo) -> dict[str, Any]:
    return gpu.to_dict()
