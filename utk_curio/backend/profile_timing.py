"""Profiling branch only (tmp/agent-turn-profile): where a turn's time goes,
and how long the dataflow docs' locks are waited for and held.

A turn's thread calls :func:`begin`, then :func:`step` around each part (the
wall seconds and this thread's CPU seconds it took) and :func:`mark` at each
point it reaches (seconds since :func:`begin`); :func:`end` logs one line,
``[turn-timing]``, with all of them.

:func:`lock_waited` keeps, per call site of a doc's lock, how many took it,
the seconds they waited and held it, and the longest of each; a thread of its
own logs them every :data:`LOCK_REPORT_S` seconds as ``[doc-lock]`` lines,
and a hold over :data:`LONG_HOLD_S` is logged at once with the CPU seconds
its thread spent holding it.
"""

from __future__ import annotations

import sys
import threading
import time
from contextlib import contextmanager

_local = threading.local()


def _say(text: str) -> None:
    """One line to stderr, which the launcher writes to messages.log."""
    try:
        print(text, file=sys.stderr, flush=True)
    except Exception:  # noqa: BLE001 - profiling never fails what it times
        pass


def begin(label: str) -> None:
    _local.label = label
    _local.items = []
    _local.wall = time.perf_counter()
    _local.cpu = time.thread_time()


def active() -> bool:
    return getattr(_local, "items", None) is not None


@contextmanager
def step(name: str):
    wall, cpu = time.perf_counter(), time.thread_time()
    try:
        yield
    finally:
        items = getattr(_local, "items", None)
        if items is not None:
            items.append(f"{name}={time.perf_counter() - wall:.2f}/{time.thread_time() - cpu:.2f}")


def mark(name: str) -> None:
    items = getattr(_local, "items", None)
    if items is not None:
        items.append(f"{name}@{time.perf_counter() - _local.wall:.2f}/{time.thread_time() - _local.cpu:.2f}")


def end(extra: str = "") -> None:
    items = getattr(_local, "items", None)
    if items is None:
        return
    _local.items = None
    _say(f"[turn-timing] {_local.label} total={time.perf_counter() - _local.wall:.2f}/"
         f"{time.thread_time() - _local.cpu:.2f} {' '.join(items)} {extra}")


# ---------------------------------------------------------------------------
# The docs' locks
# ---------------------------------------------------------------------------

LOCK_REPORT_S = 20.0
LONG_HOLD_S = 1.0

_stats_lock = threading.Lock()
_stats: dict = {}
_reporter = None


def _site(depth: int) -> str:
    import sys

    frame = sys._getframe(depth)
    names = []
    for _ in range(3):
        if frame is None:
            break
        names.append(f"{frame.f_code.co_name}:{frame.f_lineno}")
        frame = frame.f_back
    return "<".join(names)


def lock_entered(waited: float) -> tuple:
    """Called by a doc's lock once taken; the token :func:`lock_left` takes."""
    return (_site(3), waited, time.perf_counter(), time.thread_time())


def lock_left(token) -> None:
    site, waited, at, cpu = token
    held = time.perf_counter() - at
    with _stats_lock:
        entry = _stats.setdefault(site, [0, 0.0, 0.0, 0.0, 0.0])
        entry[0] += 1
        entry[1] += waited
        entry[2] += held
        entry[3] = max(entry[3], waited)
        entry[4] = max(entry[4], held)
    if held > LONG_HOLD_S:
        _say(f"[doc-lock] long hold {held:.2f} s (thread CPU {time.thread_time() - cpu:.2f} s, "
             f"waited {waited:.2f} s) at {site}")
    _start_reporter()


def _start_reporter() -> None:
    global _reporter
    if _reporter is not None:
        return
    with _stats_lock:
        if _reporter is not None:
            return
        _reporter = threading.Thread(target=_report, name="profile-doc-locks", daemon=True)
        _reporter.start()


def _report() -> None:
    while True:
        time.sleep(LOCK_REPORT_S)
        with _stats_lock:
            stats = dict(_stats)
            _stats.clear()
        for site, (count, waited, held, max_wait, max_held) in sorted(stats.items(), key=lambda kv: -kv[1][1]):
            _say(f"[doc-lock] {site}: {count} taken, waited {waited:.2f} s (max {max_wait:.2f}), "
                 f"held {held:.2f} s (max {max_held:.2f})")
