from __future__ import annotations

import os
import time

_BOOT_TIME_SECONDS: int | None = None


def _boot_time_seconds() -> int | None:
    global _BOOT_TIME_SECONDS
    if _BOOT_TIME_SECONDS is not None:
        return _BOOT_TIME_SECONDS

    try:
        with open("/proc/stat", "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.startswith("btime "):
                    _BOOT_TIME_SECONDS = int(line.split()[1])
                    return _BOOT_TIME_SECONDS
    except (OSError, ValueError):
        return None
    return None


def process_runtime_seconds(pid: int) -> int | None:
    boot_time = _boot_time_seconds()
    if boot_time is None:
        return None

    try:
        ticks_per_second = os.sysconf("SC_CLK_TCK")
    except (OSError, ValueError):
        return None

    try:
        with open(f"/proc/{pid}/stat", "r", encoding="utf-8", errors="replace") as f:
            stat = f.read()
    except OSError:
        return None

    comm_end = stat.rfind(")")
    if comm_end < 0:
        return None

    fields_after_comm = stat[comm_end + 2 :].split()
    if len(fields_after_comm) <= 19:
        return None

    try:
        start_ticks = int(fields_after_comm[19])
    except ValueError:
        return None

    started_at = boot_time + (start_ticks / ticks_per_second)
    return max(0, int(time.time() - started_at))
