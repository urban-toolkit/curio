"""In-process bookkeeping for the sandbox half of the monitor page.

The backend and the sandbox are separate processes, so the numbers a monitor
page wants about execution live on both sides of an HTTP boundary. This module
holds the sandbox side: how many executions were dispatched, how many isolated
slots are busy right now, how children died, and the last few failures with
their text. The backend reads it over the guarded ``GET /monitor`` route and
merges it into its own payload, exactly the way ``/version`` already proxies
the isolation labels.

Two rules this module never breaks:

- **Never raise.** Every public function swallows its own exceptions. This is
  the same contract ``backend.app.execution.runtime_journal`` states for the
  same reason: an execution must never fail over its bookkeeping.
- **Never grow.** Counters are ints and the error log is a bounded deque, so
  memory is O(1) no matter how long the process runs or how much traffic it
  takes. There is no history here beyond the window, by design: persistence is
  a database's job and this feature deliberately has no database.

Lives at ``sandbox/metrics.py`` rather than under ``sandbox/app/`` because
``isolation/runner.py`` imports it, and ``sandbox/app/__init__.py`` builds the
Flask app. A leaf module keeps the isolation suite importable without Flask.
"""

from __future__ import annotations

import collections
import threading
import time

# Bounded so a long-running sandbox cannot accumulate error text. 50 is enough
# to see a burst of related failures without turning the proxy response into
# something a browser has to scroll through.
ERROR_WINDOW = 50

# Identical failures inside this many seconds collapse into one entry with a
# count, so one node failing in a retry loop cannot flush the window.
_DEDUP_SECONDS = 60

# The text of a single failure. Matches the backend's cap so an entry that
# crosses the proxy is never truncated twice at two different lengths.
_DETAIL_CHARS = 8000

_LOCK = threading.Lock()

_total = 0
_isolated = 0
_in_process = 0
_slots_in_use = 0
_deaths: collections.Counter = collections.Counter()
_errors: collections.deque = collections.deque(maxlen=ERROR_WINDOW)


def record_dispatch(isolated: bool) -> None:
    """Count one execution, and whether it was confined. Never raises."""
    global _total, _isolated, _in_process
    try:
        with _LOCK:
            _total += 1
            if isolated:
                _isolated += 1
            else:
                _in_process += 1
    except Exception:
        pass


class _Slot:
    """Gauge of isolated executions in flight.

    Deliberately separate from ``IsolationConfig.slot()``, which owns the
    BoundedSemaphore that actually limits concurrency. Wrapping rather than
    extending leaves that class and its tests untouched, and a gauge that
    merely counts must never be able to affect whether work runs.
    """

    def __enter__(self):
        global _slots_in_use
        try:
            with _LOCK:
                _slots_in_use += 1
        except Exception:
            pass
        return self

    def __exit__(self, exc_type, exc, tb):
        global _slots_in_use
        try:
            with _LOCK:
                # Clamped: an underflow would render as a negative gauge and
                # send someone hunting a bug in the wrong process.
                _slots_in_use = max(0, _slots_in_use - 1)
        except Exception:
            pass
        return False


def slot() -> _Slot:
    """Context manager form, released even when the body raises."""
    return _Slot()


def record_child_death(reason: str, detail: str = "", context: dict | None = None) -> None:
    """Tally one abnormal child exit and log its sentence. Never raises.

    ``reason`` is a token from ``supervisor.DEATH_REASONS``; the caller gets it
    from ``supervisor.classify_child_death`` so the tally and the sentence a
    user reads can never disagree.
    """
    try:
        with _LOCK:
            _deaths[str(reason)] += 1
    except Exception:
        pass
    record_error(summary=str(detail or reason), detail=str(detail or ""), context=context)


def record_error(*, summary: str, detail: str = "", context: dict | None = None) -> None:
    """Append one sandbox-side failure to the window. Never raises."""
    try:
        summary_text = str(summary or "").strip() or "Sandbox error"
        detail_text = str(detail or "")[:_DETAIL_CHARS]
        now = time.time()
        with _LOCK:
            for entry in reversed(_errors):
                if (
                    entry["summary"] == summary_text
                    and entry["detail"] == detail_text
                    and now - entry["_at"] <= _DEDUP_SECONDS
                ):
                    entry["count"] += 1
                    entry["_at"] = now
                    entry["at"] = _iso(now)
                    return
            _errors.append({
                "at": _iso(now),
                "_at": now,
                "source": "sandbox",
                "summary": summary_text,
                "detail": detail_text,
                "context": dict(context or {}),
                "count": 1,
            })
    except Exception:
        pass


def errors() -> list:
    """The window, newest first, with the internal sort key stripped."""
    try:
        with _LOCK:
            snapshot = list(_errors)
    except Exception:
        return []
    return [{k: v for k, v in entry.items() if k != "_at"}
            for entry in reversed(snapshot)]


def snapshot() -> dict:
    """Counters as plain JSON. Never raises; degrades to zeros."""
    try:
        with _LOCK:
            deaths = dict(_deaths)
            return {
                "total": _total,
                "isolated": _isolated,
                "inProcess": _in_process,
                "slotsInUse": _slots_in_use,
                "errorWindow": ERROR_WINDOW,
                "childDeaths": deaths,
            }
    except Exception:
        return {"total": 0, "isolated": 0, "inProcess": 0, "slotsInUse": 0,
                "errorWindow": ERROR_WINDOW, "childDeaths": {}}


def process_rss_bytes():
    """This process's resident memory, or None where psutil cannot say.

    Deliberately implemented here rather than imported from the backend's
    ``monitor.hardware``: the sandbox is a separate process and must not depend
    on backend packages. psutil is already a dependency of both (``server.py``
    imports it), so this is a two-line duplicate rather than a shared module
    pulling a layer the wrong way round.
    """
    try:
        import psutil

        return int(psutil.Process().memory_info().rss)
    except Exception:
        return None


def reset() -> None:
    """Drop all state. For tests only."""
    global _total, _isolated, _in_process, _slots_in_use
    with _LOCK:
        _total = _isolated = _in_process = _slots_in_use = 0
        _deaths.clear()
        _errors.clear()


def _iso(epoch: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))
