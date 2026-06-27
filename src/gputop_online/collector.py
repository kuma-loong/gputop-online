from __future__ import annotations

import asyncio
import logging
from collections import defaultdict, deque
from typing import Any

from . import nvidia_smi
from .nvml import NVMLSampler
from .schema import Snapshot

logger = logging.getLogger(__name__)


class SnapshotCollector:
    def __init__(
        self,
        refresh_interval: float = 1.0,
        process_interval: float = 3.0,
        history_size: int = 120,
    ):
        self.refresh_interval = max(0.25, refresh_interval)
        self.process_interval = max(self.refresh_interval, process_interval)
        self.history_size = history_size
        self._task: asyncio.Task[None] | None = None
        self._event = asyncio.Event()
        self._snapshot: Snapshot | None = None
        self._seq = 0
        self._history: dict[str, dict[str, deque[float]]] = defaultdict(
            lambda: {
                "gpu": deque(maxlen=history_size),
                "memory": deque(maxlen=history_size),
                "power": deque(maxlen=history_size),
                "temperature": deque(maxlen=history_size),
            }
        )
        self._sampler: NVMLSampler | None = None

    @property
    def snapshot(self) -> Snapshot | None:
        return self._snapshot

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._run(), name="gpu-snapshot-collector")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._sampler:
            self._sampler.close()
            self._sampler = None

    async def wait_for_update(self, last_seq: int, timeout: float = 30.0) -> Snapshot | None:
        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            if self._snapshot and self._snapshot.seq > last_seq:
                return self._snapshot
            self._event.clear()
            if self._snapshot and self._snapshot.seq > last_seq:
                return self._snapshot

            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                return self._snapshot
            try:
                await asyncio.wait_for(self._event.wait(), timeout=remaining)
            except asyncio.TimeoutError:
                return self._snapshot

    async def _run(self) -> None:
        while True:
            started = asyncio.get_running_loop().time()
            snapshot = await asyncio.to_thread(self._sample_once)
            self._publish(snapshot)
            elapsed = asyncio.get_running_loop().time() - started
            await asyncio.sleep(max(0.0, self.refresh_interval - elapsed))

    def _sample_once(self) -> Snapshot:
        try:
            if self._sampler is None:
                self._sampler = NVMLSampler(process_interval=self.process_interval)
            return self._sampler.sample()
        except Exception as exc:
            logger.warning("NVML sample failed, falling back to nvidia-smi: %s", exc)
            if self._sampler is not None:
                self._sampler.close()
                self._sampler = None
            try:
                return nvidia_smi.sample(timeout=2.5)
            except Exception as fallback_exc:
                return nvidia_smi.error_snapshot(
                    f"NVML failed: {exc}; nvidia-smi failed: {fallback_exc}",
                    source="none",
                )

    def _publish(self, snapshot: Snapshot) -> None:
        self._seq += 1
        snapshot.seq = self._seq
        snapshot.refresh_interval = self.refresh_interval
        for gpu in snapshot.gpus:
            key = str(gpu.index)
            self._history[key]["gpu"].append(float(gpu.utilization_gpu))
            self._history[key]["memory"].append(float(gpu.memory_percent))
            self._history[key]["power"].append(float(gpu.power_percent))
            self._history[key]["temperature"].append(float(gpu.temperature_c))
        snapshot.history = self._history_payload()
        self._snapshot = snapshot
        self._event.set()

    def _history_payload(self) -> dict[str, dict[str, list[float]]]:
        payload: dict[str, dict[str, list[float]]] = {}
        for gpu_index, series in self._history.items():
            payload[gpu_index] = {name: list(values) for name, values in series.items()}
        return payload


def snapshot_to_jsonable(snapshot: Snapshot | None) -> dict[str, Any]:
    if snapshot is None:
        return {
            "ok": False,
            "source": "none",
            "error": "collector has not produced a snapshot yet",
            "seq": 0,
            "gpus": [],
            "totals": {
                "gpu_count": 0,
                "avg_gpu_utilization": 0.0,
                "avg_memory_utilization": 0.0,
                "memory_used_mb": 0,
                "memory_total_mb": 0,
                "power_watts": 0.0,
                "power_limit_watts": 0.0,
                "max_temperature_c": 0,
                "active_processes": 0,
            },
            "history": {},
        }
    return snapshot.to_dict()
