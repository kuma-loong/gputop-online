from __future__ import annotations

import ctypes
import ctypes.util
import os
import pwd
import socket
import subprocess
import time

from . import nvidia_smi
from .procfs import process_runtime_seconds
from .schema import GpuInfo, GpuProcess, OtherUserMemory, Snapshot

NVML_SUCCESS = 0
NVML_ERROR_INSUFFICIENT_SIZE = 4
NVML_ERROR_NO_PERMISSION = 7

NVML_TEMPERATURE_GPU = 0
NVML_CLOCK_SM = 1
NVML_CLOCK_MEM = 2

NVML_DEVICE_NAME_BUFFER_SIZE = 96
NVML_DEVICE_UUID_BUFFER_SIZE = 96
NVML_SYSTEM_BUFFER_SIZE = 96

PSTATE_MAP = {
    0: "P0",
    1: "P1",
    2: "P2",
    3: "P3",
    4: "P4",
    5: "P5",
    6: "P6",
    7: "P7",
    8: "P8",
    9: "P9",
    10: "P10",
    11: "P11",
    12: "P12",
    13: "P13",
    14: "P14",
    15: "P15",
}

COMPUTE_MODE_MAP = {
    0: "Default",
    1: "Exclusive Thread",
    2: "Prohibited",
    3: "Exclusive Process",
}

ECC_MODE_MAP = {0: "Disabled", 1: "Enabled"}
MIG_MODE_MAP = {0: "Disabled", 1: "Enabled"}


class NvmlMemory(ctypes.Structure):
    _fields_ = [
        ("total", ctypes.c_ulonglong),
        ("free", ctypes.c_ulonglong),
        ("used", ctypes.c_ulonglong),
    ]


class NvmlUtilization(ctypes.Structure):
    _fields_ = [
        ("gpu", ctypes.c_uint),
        ("memory", ctypes.c_uint),
    ]


class NvmlProcessInfo(ctypes.Structure):
    _fields_ = [
        ("pid", ctypes.c_uint),
        ("usedGpuMemory", ctypes.c_ulonglong),
    ]


class NvmlMemoryV2(ctypes.Structure):
    _fields_ = [
        ("version", ctypes.c_uint),
        ("_pad", ctypes.c_uint),
        ("total", ctypes.c_ulonglong),
        ("reserved", ctypes.c_ulonglong),
        ("free", ctypes.c_ulonglong),
        ("used", ctypes.c_ulonglong),
    ]


class NVMLUnavailable(RuntimeError):
    pass


def _load_library() -> ctypes.CDLL:
    lib_path = ctypes.util.find_library("nvidia-ml")
    candidates = [
        lib_path,
        "libnvidia-ml.so.1",
        "libnvidia-ml.so",
        "/usr/lib/x86_64-linux-gnu/libnvidia-ml.so.1",
        "/usr/lib64/libnvidia-ml.so.1",
        "/usr/lib/libnvidia-ml.so.1",
    ]
    for candidate in candidates:
        if not candidate:
            continue
        try:
            return ctypes.CDLL(candidate)
        except OSError:
            continue
    raise NVMLUnavailable("Cannot find libnvidia-ml.so")


def _setup(lib: ctypes.CDLL) -> None:
    lib.nvmlInit.restype = ctypes.c_int
    lib.nvmlShutdown.restype = ctypes.c_int

    lib.nvmlSystemGetDriverVersion.argtypes = [ctypes.c_char_p, ctypes.c_uint]
    lib.nvmlSystemGetDriverVersion.restype = ctypes.c_int
    lib.nvmlSystemGetNVMLVersion.argtypes = [ctypes.c_char_p, ctypes.c_uint]
    lib.nvmlSystemGetNVMLVersion.restype = ctypes.c_int

    if hasattr(lib, "nvmlSystemGetCudaDriverVersion_v2"):
        lib.nvmlSystemGetCudaDriverVersion_v2.argtypes = [ctypes.POINTER(ctypes.c_int)]
        lib.nvmlSystemGetCudaDriverVersion_v2.restype = ctypes.c_int
    elif hasattr(lib, "nvmlSystemGetCudaDriverVersion"):
        lib.nvmlSystemGetCudaDriverVersion.argtypes = [ctypes.POINTER(ctypes.c_int)]
        lib.nvmlSystemGetCudaDriverVersion.restype = ctypes.c_int

    lib.nvmlDeviceGetCount.argtypes = [ctypes.POINTER(ctypes.c_uint)]
    lib.nvmlDeviceGetCount.restype = ctypes.c_int
    lib.nvmlDeviceGetHandleByIndex.argtypes = [ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p)]
    lib.nvmlDeviceGetHandleByIndex.restype = ctypes.c_int
    lib.nvmlDeviceGetName.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint]
    lib.nvmlDeviceGetName.restype = ctypes.c_int
    lib.nvmlDeviceGetUUID.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint]
    lib.nvmlDeviceGetUUID.restype = ctypes.c_int
    lib.nvmlDeviceGetMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(NvmlMemory)]
    lib.nvmlDeviceGetMemoryInfo.restype = ctypes.c_int
    lib.nvmlDeviceGetUtilizationRates.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(NvmlUtilization),
    ]
    lib.nvmlDeviceGetUtilizationRates.restype = ctypes.c_int
    lib.nvmlDeviceGetTemperature.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.POINTER(ctypes.c_uint),
    ]
    lib.nvmlDeviceGetTemperature.restype = ctypes.c_int
    lib.nvmlDeviceGetPowerUsage.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint)]
    lib.nvmlDeviceGetPowerUsage.restype = ctypes.c_int
    lib.nvmlDeviceGetPowerManagementLimit.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_uint),
    ]
    lib.nvmlDeviceGetPowerManagementLimit.restype = ctypes.c_int
    lib.nvmlDeviceGetClockInfo.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.POINTER(ctypes.c_uint),
    ]
    lib.nvmlDeviceGetClockInfo.restype = ctypes.c_int
    lib.nvmlDeviceGetMaxClockInfo.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.POINTER(ctypes.c_uint),
    ]
    lib.nvmlDeviceGetMaxClockInfo.restype = ctypes.c_int
    lib.nvmlDeviceGetPerformanceState.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_uint),
    ]
    lib.nvmlDeviceGetPerformanceState.restype = ctypes.c_int
    lib.nvmlDeviceGetComputeMode.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint)]
    lib.nvmlDeviceGetComputeMode.restype = ctypes.c_int
    lib.nvmlDeviceGetEccMode.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_uint),
        ctypes.POINTER(ctypes.c_uint),
    ]
    lib.nvmlDeviceGetEccMode.restype = ctypes.c_int
    lib.nvmlDeviceGetComputeRunningProcesses.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_uint),
        ctypes.POINTER(NvmlProcessInfo),
    ]
    lib.nvmlDeviceGetComputeRunningProcesses.restype = ctypes.c_int

    if hasattr(lib, "nvmlDeviceGetGraphicsRunningProcesses"):
        lib.nvmlDeviceGetGraphicsRunningProcesses.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_uint),
            ctypes.POINTER(NvmlProcessInfo),
        ]
        lib.nvmlDeviceGetGraphicsRunningProcesses.restype = ctypes.c_int
    if hasattr(lib, "nvmlDeviceGetMigMode"):
        lib.nvmlDeviceGetMigMode.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_uint),
            ctypes.POINTER(ctypes.c_uint),
        ]
        lib.nvmlDeviceGetMigMode.restype = ctypes.c_int
    if hasattr(lib, "nvmlDeviceGetMemoryInfo_v2"):
        lib.nvmlDeviceGetMemoryInfo_v2.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(NvmlMemoryV2),
        ]
        lib.nvmlDeviceGetMemoryInfo_v2.restype = ctypes.c_int


def _decode_buffer(buf: ctypes.Array[ctypes.c_char]) -> str | None:
    value = bytes(buf.value).decode("utf-8", errors="replace").strip()
    return value or None


def _proc_uid(pid: int) -> int | None:
    try:
        with open(f"/proc/{pid}/status", "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.startswith("Uid:"):
                    return int(line.split()[1])
    except (OSError, ValueError):
        return None
    return None


def _uid_name(uid: int | None) -> str | None:
    if uid is None:
        return None
    try:
        return pwd.getpwuid(uid).pw_name
    except KeyError:
        return str(uid)


def _proc_comm(pid: int) -> str | None:
    try:
        with open(f"/proc/{pid}/comm", "r", encoding="utf-8", errors="replace") as f:
            return f.read().strip() or None
    except OSError:
        return None


def _proc_cmdline(pid: int) -> str | None:
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            raw = f.read()
    except OSError:
        return None
    if not raw:
        return None
    return raw.replace(b"\x00", b" ").decode("utf-8", errors="replace").strip() or None


def _cuda_driver_version(value: int) -> str:
    if value <= 0:
        return "unknown"
    return f"{value // 1000}.{(value % 1000) // 10}"


class NVMLSampler:
    def __init__(self, own_user: str | None = None, process_interval: float = 3.0):
        self.own_user = own_user or os.environ.get("USER")
        self.process_interval = max(1.0, process_interval)
        self._lib = _load_library()
        _setup(self._lib)
        rc = self._lib.nvmlInit()
        if rc != NVML_SUCCESS:
            raise NVMLUnavailable(f"nvmlInit failed with code {rc}")
        self._closed = False
        self._reserved_offsets: dict[int, int] | None = None
        self._next_process_at = 0.0
        self._process_snapshot: dict[str, tuple[list[GpuProcess], list[OtherUserMemory]]] = {}

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._lib.nvmlShutdown()
        except Exception:
            pass

    def sample(self) -> Snapshot:
        started = time.monotonic()
        count = ctypes.c_uint(0)
        rc = self._lib.nvmlDeviceGetCount(ctypes.byref(count))
        if rc != NVML_SUCCESS:
            raise NVMLUnavailable(f"nvmlDeviceGetCount failed with code {rc}")

        if self._reserved_offsets is None:
            self._reserved_offsets = self._calibrate_reserved(count.value)

        now = time.monotonic()
        collect_processes = now >= self._next_process_at
        gpus: list[GpuInfo] = []
        process_cache: list[dict[str, list[GpuProcess]] | None] = [None]
        for index in range(count.value):
            gpus.append(self._sample_gpu(index, process_cache, collect_processes))
        if collect_processes:
            self._next_process_at = time.monotonic() + self.process_interval

        return Snapshot(
            ok=True,
            source="nvml",
            hostname=socket.gethostname(),
            timestamp=time.time(),
            elapsed_ms=round((time.monotonic() - started) * 1000, 1),
            gpus=gpus,
            driver_version=self._system_string("nvmlSystemGetDriverVersion"),
            cuda_driver_version=self._cuda_version(),
            nvml_version=self._system_string("nvmlSystemGetNVMLVersion"),
        )

    def _sample_gpu(
        self,
        index: int,
        process_cache: list[dict[str, list[GpuProcess]] | None],
        collect_processes: bool,
    ) -> GpuInfo:
        handle = ctypes.c_void_p()
        rc = self._lib.nvmlDeviceGetHandleByIndex(index, ctypes.byref(handle))
        if rc != NVML_SUCCESS:
            return GpuInfo(index=index, error=f"nvmlDeviceGetHandleByIndex failed: {rc}")

        gpu = GpuInfo(index=index)
        gpu.name = self._device_string(handle, "nvmlDeviceGetName", NVML_DEVICE_NAME_BUFFER_SIZE)
        gpu.uuid = self._device_string(handle, "nvmlDeviceGetUUID", NVML_DEVICE_UUID_BUFFER_SIZE)
        self._fill_memory(gpu, handle)
        self._fill_utilization(gpu, handle)
        gpu.temperature_c = self._uint_device_call(handle, "nvmlDeviceGetTemperature", NVML_TEMPERATURE_GPU)
        gpu.power_watts = round(
            self._uint_device_call(handle, "nvmlDeviceGetPowerUsage") / 1000.0,
            1,
        )
        gpu.power_limit_watts = round(
            self._uint_device_call(handle, "nvmlDeviceGetPowerManagementLimit") / 1000.0,
            1,
        )
        gpu.clock_sm_mhz = self._optional_uint_device_call(
            handle,
            "nvmlDeviceGetClockInfo",
            NVML_CLOCK_SM,
        )
        gpu.clock_mem_mhz = self._optional_uint_device_call(
            handle,
            "nvmlDeviceGetClockInfo",
            NVML_CLOCK_MEM,
        )
        gpu.max_clock_sm_mhz = self._optional_uint_device_call(
            handle,
            "nvmlDeviceGetMaxClockInfo",
            NVML_CLOCK_SM,
        )
        gpu.max_clock_mem_mhz = self._optional_uint_device_call(
            handle,
            "nvmlDeviceGetMaxClockInfo",
            NVML_CLOCK_MEM,
        )
        pstate = self._optional_uint_device_call(handle, "nvmlDeviceGetPerformanceState")
        compute_mode = self._optional_uint_device_call(handle, "nvmlDeviceGetComputeMode")
        gpu.pstate = PSTATE_MAP.get(pstate) if pstate is not None else None
        gpu.compute_mode = COMPUTE_MODE_MAP.get(compute_mode) if compute_mode is not None else None
        gpu.ecc_mode = self._ecc_mode(handle)
        gpu.mig_mode = self._mig_mode(handle)
        if collect_processes:
            gpu.processes, gpu.other_users = self._processes(handle, gpu.uuid, process_cache)
            self._process_snapshot[gpu.uuid] = (gpu.processes, gpu.other_users)
        else:
            gpu.processes, gpu.other_users = self._process_snapshot.get(gpu.uuid, ([], []))
        return gpu

    def _system_string(self, func_name: str) -> str | None:
        buf = ctypes.create_string_buffer(NVML_SYSTEM_BUFFER_SIZE)
        func = getattr(self._lib, func_name)
        rc = func(buf, NVML_SYSTEM_BUFFER_SIZE)
        if rc != NVML_SUCCESS:
            return None
        return _decode_buffer(buf)

    def _cuda_version(self) -> str | None:
        version = ctypes.c_int(0)
        if hasattr(self._lib, "nvmlSystemGetCudaDriverVersion_v2"):
            rc = self._lib.nvmlSystemGetCudaDriverVersion_v2(ctypes.byref(version))
        elif hasattr(self._lib, "nvmlSystemGetCudaDriverVersion"):
            rc = self._lib.nvmlSystemGetCudaDriverVersion(ctypes.byref(version))
        else:
            return None
        if rc != NVML_SUCCESS:
            return None
        return _cuda_driver_version(version.value)

    def _device_string(self, handle: ctypes.c_void_p, func_name: str, size: int) -> str:
        buf = ctypes.create_string_buffer(size)
        func = getattr(self._lib, func_name)
        rc = func(handle, buf, size)
        if rc != NVML_SUCCESS:
            return "unknown"
        return _decode_buffer(buf) or "unknown"

    def _uint_device_call(
        self,
        handle: ctypes.c_void_p,
        func_name: str,
        arg: int | None = None,
    ) -> int:
        value = ctypes.c_uint(0)
        func = getattr(self._lib, func_name)
        if arg is None:
            rc = func(handle, ctypes.byref(value))
        else:
            rc = func(handle, arg, ctypes.byref(value))
        if rc != NVML_SUCCESS:
            return 0
        return int(value.value)

    def _optional_uint_device_call(
        self,
        handle: ctypes.c_void_p,
        func_name: str,
        arg: int | None = None,
    ) -> int | None:
        value = ctypes.c_uint(0)
        func = getattr(self._lib, func_name)
        if arg is None:
            rc = func(handle, ctypes.byref(value))
        else:
            rc = func(handle, arg, ctypes.byref(value))
        if rc != NVML_SUCCESS:
            return None
        return int(value.value)

    def _fill_memory(self, gpu: GpuInfo, handle: ctypes.c_void_p) -> None:
        mem = NvmlMemory()
        rc = self._lib.nvmlDeviceGetMemoryInfo(handle, ctypes.byref(mem))
        if rc != NVML_SUCCESS:
            return

        total_mb = int(mem.total // (1024 * 1024))
        free_mb = int(mem.free // (1024 * 1024))
        used_mb: int | None = None

        v2 = self._try_memory_v2(handle)
        if v2 is not None:
            used_mb, free_mb = v2
        elif self._reserved_offsets and gpu.index in self._reserved_offsets:
            used_mb = total_mb - free_mb - self._reserved_offsets[gpu.index]

        if used_mb is None:
            used_mb = int((mem.total - mem.free) // (1024 * 1024))

        gpu.memory_total_mb = total_mb
        gpu.memory_used_mb = max(0, int(used_mb))
        gpu.memory_free_mb = max(0, total_mb - gpu.memory_used_mb)

    def _try_memory_v2(self, handle: ctypes.c_void_p) -> tuple[int, int] | None:
        if not hasattr(self._lib, "nvmlDeviceGetMemoryInfo_v2"):
            return None
        mem = NvmlMemoryV2()
        mem.version = ctypes.sizeof(NvmlMemoryV2) | (2 << 24)
        rc = self._lib.nvmlDeviceGetMemoryInfo_v2(handle, ctypes.byref(mem))
        if rc != NVML_SUCCESS:
            return None
        used_mb = int((mem.total - mem.free - mem.reserved) // (1024 * 1024))
        free_mb = int(mem.free // (1024 * 1024))
        return max(0, used_mb), free_mb

    def _calibrate_reserved(self, count: int) -> dict[int, int]:
        if hasattr(self._lib, "nvmlDeviceGetMemoryInfo_v2"):
            handle = ctypes.c_void_p()
            if self._lib.nvmlDeviceGetHandleByIndex(0, ctypes.byref(handle)) == NVML_SUCCESS:
                if self._try_memory_v2(handle) is not None:
                    return {}

        try:
            smi_snapshot = nvidia_smi.sample(timeout=2.5)
        except Exception:
            return {}

        smi_used = {gpu.index: gpu.memory_used_mb for gpu in smi_snapshot.gpus}
        offsets: dict[int, int] = {}
        for index in range(count):
            handle = ctypes.c_void_p()
            if self._lib.nvmlDeviceGetHandleByIndex(index, ctypes.byref(handle)) != NVML_SUCCESS:
                continue
            mem = NvmlMemory()
            if self._lib.nvmlDeviceGetMemoryInfo(handle, ctypes.byref(mem)) != NVML_SUCCESS:
                continue
            raw_used = int((mem.total - mem.free) // (1024 * 1024))
            reserved = raw_used - smi_used.get(index, raw_used)
            if reserved > 0:
                offsets[index] = reserved
        return offsets

    def _fill_utilization(self, gpu: GpuInfo, handle: ctypes.c_void_p) -> None:
        util = NvmlUtilization()
        rc = self._lib.nvmlDeviceGetUtilizationRates(handle, ctypes.byref(util))
        if rc != NVML_SUCCESS:
            return
        gpu.utilization_gpu = int(util.gpu)
        gpu.utilization_mem = int(util.memory)

    def _ecc_mode(self, handle: ctypes.c_void_p) -> str | None:
        current = ctypes.c_uint(0)
        pending = ctypes.c_uint(0)
        rc = self._lib.nvmlDeviceGetEccMode(handle, ctypes.byref(current), ctypes.byref(pending))
        if rc != NVML_SUCCESS:
            return None
        return ECC_MODE_MAP.get(current.value, str(current.value))

    def _mig_mode(self, handle: ctypes.c_void_p) -> str | None:
        if not hasattr(self._lib, "nvmlDeviceGetMigMode"):
            return None
        current = ctypes.c_uint(0)
        pending = ctypes.c_uint(0)
        rc = self._lib.nvmlDeviceGetMigMode(handle, ctypes.byref(current), ctypes.byref(pending))
        if rc != NVML_SUCCESS:
            return None
        return MIG_MODE_MAP.get(current.value, str(current.value))

    def _processes(
        self,
        handle: ctypes.c_void_p,
        gpu_uuid: str,
        process_cache: list[dict[str, list[GpuProcess]] | None],
    ) -> tuple[list[GpuProcess], list[OtherUserMemory]]:
        raw = self._running_processes(handle, "nvmlDeviceGetComputeRunningProcesses", "compute")
        if raw is None:
            if process_cache[0] is None:
                try:
                    proc_output = subprocess.check_output(
                        [
                            "nvidia-smi",
                            "--query-compute-apps=gpu_uuid,pid,process_name,used_memory",
                            "--format=csv,noheader,nounits",
                        ],
                        stderr=subprocess.DEVNULL,
                        timeout=2.5,
                        text=True,
                    )
                    process_cache[0] = nvidia_smi.parse_process_query_csv(proc_output)
                except Exception:
                    process_cache[0] = {}
            raw = process_cache[0].get(gpu_uuid, [])

        graphics = self._running_processes(handle, "nvmlDeviceGetGraphicsRunningProcesses", "graphics")
        if graphics:
            raw.extend(graphics)

        own: list[GpuProcess] = []
        other: dict[str, OtherUserMemory] = {}
        for process in raw:
            uid = _proc_uid(process.pid)
            user = _uid_name(uid)
            process.user = process.user or user
            process.name = process.name or _proc_comm(process.pid) or "?"
            process.runtime_seconds = process.runtime_seconds or process_runtime_seconds(process.pid)
            if self.own_user and user == self.own_user:
                process.cmdline = _proc_cmdline(process.pid)
                own.append(process)
                continue

            key = user or "?"
            if key not in other:
                other[key] = OtherUserMemory(user=key, process_count=0, total_memory_mb=0)
            other[key].process_count += 1
            other[key].total_memory_mb += process.gpu_memory_mb
            if process.runtime_seconds is not None:
                other[key].runtime_seconds = max(
                    other[key].runtime_seconds or 0,
                    process.runtime_seconds,
                )
        return own, sorted(other.values(), key=lambda item: item.total_memory_mb, reverse=True)

    def _running_processes(
        self,
        handle: ctypes.c_void_p,
        func_name: str,
        kind: str,
    ) -> list[GpuProcess] | None:
        if not hasattr(self._lib, func_name):
            return []
        func = getattr(self._lib, func_name)
        count = ctypes.c_uint(0)
        rc = func(handle, ctypes.byref(count), None)
        if rc == NVML_ERROR_NO_PERMISSION:
            return None
        if rc == NVML_SUCCESS and count.value == 0:
            return []
        if rc not in {NVML_SUCCESS, NVML_ERROR_INSUFFICIENT_SIZE}:
            return []
        if count.value == 0:
            return []

        buffer = (NvmlProcessInfo * count.value)()
        rc = func(handle, ctypes.byref(count), buffer)
        if rc == NVML_ERROR_NO_PERMISSION:
            return None
        if rc != NVML_SUCCESS:
            return []

        result: list[GpuProcess] = []
        for i in range(count.value):
            info = buffer[i]
            used = int(info.usedGpuMemory)
            if used >= (1 << 63):
                used = 0
            result.append(
                GpuProcess(
                    pid=int(info.pid),
                    name=_proc_comm(int(info.pid)) or "?",
                    gpu_memory_mb=int(used // (1024 * 1024)),
                    kind=kind,
                    runtime_seconds=process_runtime_seconds(int(info.pid)),
                )
            )
        return result


def sample(own_user: str | None = None) -> Snapshot:
    sampler = NVMLSampler(own_user=own_user)
    try:
        return sampler.sample()
    finally:
        sampler.close()


def sample_with_fallback(own_user: str | None = None) -> Snapshot:
    try:
        sampler = NVMLSampler(own_user=own_user)
    except Exception as exc:
        try:
            snapshot = nvidia_smi.sample()
            snapshot.source = "nvidia-smi"
            return snapshot
        except Exception as fallback_exc:
            return nvidia_smi.error_snapshot(
                f"NVML failed: {exc}; nvidia-smi failed: {fallback_exc}",
                source="none",
            )

    try:
        return sampler.sample()
    except Exception as exc:
        try:
            snapshot = nvidia_smi.sample()
            snapshot.source = "nvidia-smi"
            return snapshot
        except Exception as fallback_exc:
            return nvidia_smi.error_snapshot(
                f"NVML failed: {exc}; nvidia-smi failed: {fallback_exc}",
                source="none",
            )
    finally:
        sampler.close()
