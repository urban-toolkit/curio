"""What this instance is running on: CPU, memory, load and process footprint.

The first question asked of a slow or failing deployment is almost always
"what is it running on, and is it out of something". Until now that needed
shell access to the host. This module answers it from the same public payload
as everything else.

PRIVACY. Machine specs are not user data, so this section is compatible with
the aggregate-only rule the rest of `/api/monitor` follows. One thing is
deliberately NOT reported: the hostname. It frequently encodes a person, a
team or an internal network name, and it tells an operator nothing they do not
already know. Do not add it. IP addresses and MAC addresses are excluded for
the same reason, and there is no field here that would carry one.

psutil is already a hard dependency (`pyproject.toml`, and
`sandbox/server.py` imports it), so nothing new is required. Every lookup is
still wrapped: psutil degrades differently across platforms, and a monitor must
not fail because one counter is unavailable on someone's kernel.
"""

from __future__ import annotations

import os
import platform
import subprocess

try:  # pragma: no cover - import guard, exercised only where psutil is absent
    import psutil
except Exception:  # noqa: BLE001
    psutil = None


def _cpu_model() -> str:
    """A human-readable CPU name.

    ``platform.processor()`` returns something useful on macOS and Windows but
    is routinely empty or just ``x86_64`` on Linux, so each platform gets the
    source that actually knows.
    """
    try:
        if platform.system() == "Linux":
            with open("/proc/cpuinfo", "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    if line.lower().startswith("model name"):
                        return line.split(":", 1)[1].strip()
        elif platform.system() == "Darwin":
            out = subprocess.run(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                capture_output=True, text=True, timeout=2, check=False,
            )
            if out.returncode == 0 and out.stdout.strip():
                return out.stdout.strip()
    except Exception:  # noqa: BLE001
        pass
    return (platform.processor() or platform.machine() or "unknown").strip()


def _cpu() -> dict:
    logical = None
    physical = None
    usage = None
    frequency = None
    try:
        logical = os.cpu_count()
    except Exception:  # noqa: BLE001
        pass
    if psutil is not None:
        try:
            physical = psutil.cpu_count(logical=False)
        except Exception:  # noqa: BLE001
            pass
        try:
            # interval=None is non-blocking: it reports the average since the
            # PREVIOUS call, which a page polling every 5s is exactly right
            # for. An interval here would block the request for that long.
            usage = round(float(psutil.cpu_percent(interval=None)), 1)
        except Exception:  # noqa: BLE001
            pass
        try:
            freq = psutil.cpu_freq()
            if freq is not None and freq.max:
                frequency = int(freq.max)
            elif freq is not None and freq.current:
                frequency = int(freq.current)
        except Exception:  # noqa: BLE001
            pass
    return {
        "model": _cpu_model(),
        "arch": platform.machine() or "unknown",
        "logicalCores": logical,
        "physicalCores": physical,
        "maxFrequencyMhz": frequency,
        "usagePercent": usage,
    }


def _memory() -> dict:
    if psutil is None:
        return {"totalBytes": None, "availableBytes": None, "usedPercent": None,
                "swapTotalBytes": None, "swapUsedBytes": None}
    out = {}
    try:
        vm = psutil.virtual_memory()
        out["totalBytes"] = int(vm.total)
        out["availableBytes"] = int(vm.available)
        out["usedPercent"] = round(float(vm.percent), 1)
    except Exception:  # noqa: BLE001
        out.update({"totalBytes": None, "availableBytes": None, "usedPercent": None})
    try:
        swap = psutil.swap_memory()
        out["swapTotalBytes"] = int(swap.total)
        out["swapUsedBytes"] = int(swap.used)
    except Exception:  # noqa: BLE001
        out.update({"swapTotalBytes": None, "swapUsedBytes": None})
    return out


def _load() -> dict:
    """Load averages, plus the per-core figure that makes them comparable.

    A load of 8 means nothing on its own; on 16 cores it is half idle and on 2
    it is badly oversubscribed. Reporting both saves the reader the division.
    """
    try:
        one, five, fifteen = os.getloadavg()
    except (OSError, AttributeError):
        # Windows has no load average at all.
        return {"avg1m": None, "avg5m": None, "avg15m": None, "perCore": None}
    cores = os.cpu_count() or 1
    return {
        "avg1m": round(one, 2),
        "avg5m": round(five, 2),
        "avg15m": round(fifteen, 2),
        "perCore": round(one / cores, 2),
    }


def process_rss_bytes() -> int | None:
    """Resident memory of the calling process. Used by both processes."""
    if psutil is None:
        return None
    try:
        return int(psutil.Process().memory_info().rss)
    except Exception:  # noqa: BLE001
        return None


def snapshot(sandbox_rss=None) -> dict:
    """The hardware section. Never raises; unavailable fields are null.

    ``sandbox_rss`` is proxied from the sandbox process, which runs node code
    and is therefore the one whose memory an operator actually wants to watch.
    """
    return {
        "cpu": _section(_cpu, _EMPTY_CPU),
        "memory": _section(_memory, _EMPTY_MEMORY),
        "load": _section(_load, _EMPTY_LOAD),
        "processes": {
            "backendRssBytes": process_rss_bytes(),
            "sandboxRssBytes": sandbox_rss,
        },
    }


# Each section is independently fenced. The helpers above already guard the
# individual psutil calls, so reaching one of these means something structural
# broke; the page must still render the other three sections and the rest of
# the payload rather than 500 over the part describing the host.
_EMPTY_CPU = {"model": "unknown", "arch": "unknown", "logicalCores": None,
              "physicalCores": None, "maxFrequencyMhz": None,
              "usagePercent": None}
_EMPTY_MEMORY = {"totalBytes": None, "availableBytes": None,
                 "usedPercent": None, "swapTotalBytes": None,
                 "swapUsedBytes": None}
_EMPTY_LOAD = {"avg1m": None, "avg5m": None, "avg15m": None, "perCore": None}


def _section(fn, fallback):
    try:
        return fn()
    except Exception:  # noqa: BLE001
        return dict(fallback)
