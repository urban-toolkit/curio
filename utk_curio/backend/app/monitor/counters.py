"""Execution counters for this backend process.

Stdlib only and no Flask import, so the unit suite can exercise this without an
app context.

The contract is copied verbatim from
``backend.app.execution.runtime_journal.record_execution``: every public
function swallows its own exceptions, because an execution must never fail over
its bookkeeping. A monitor that breaks the thing it monitors is worse than no
monitor.

Memory is O(1) by construction. The duration window is a ``deque`` with a fixed
``maxlen`` and the node-type set is capped, so a process serving a million
executions holds exactly as much as one serving a hundred. That is what makes
"in-memory only, no new table" a real design rather than a deferred problem.
"""

from __future__ import annotations

import collections
import threading
import time

# The rolling window feeding the percentile and histogram fields. 200 is enough
# to characterise a distribution without making the snapshot expensive to sort.
DURATION_WINDOW = 200

# Node type ids come from client JSON, so the set they live in is unbounded by
# nature. Only its length is ever emitted, so stopping at a cap costs nothing
# but an undercount on an instance with more than 500 distinct node types.
_MAX_NODE_TYPES = 500

# Upper bounds for the duration histogram, in milliseconds. The final None bin
# is the overflow. Fixed rather than computed so the chart's x axis is stable
# between polls and two instances can be compared by eye.
DURATION_BUCKETS_MS = (100, 500, 1000, 5000, 30000, None)

_LOCK = threading.Lock()

_started = time.monotonic()
_total = 0
_ok = 0
_error = 0
_python = 0
_javascript = 0
_in_flight = 0
_node_types: set = set()
_durations: collections.deque = collections.deque(maxlen=DURATION_WINDOW)
_last_at = None


def record_execution(*, language: str, node_type=None, ok: bool,
                     duration_ms=None) -> None:
    """Count one node execution. Never raises.

    ``ok`` must come from the canonical failure predicate, a non-empty
    ``output.path``. Note that a non-empty stderr is NOT the predicate: benign
    warnings land in stderr too, and treating them as failures was the bug that
    made this distinction worth writing down.
    """
    global _total, _ok, _error, _python, _javascript, _last_at
    try:
        with _LOCK:
            _total += 1
            if ok:
                _ok += 1
            else:
                _error += 1
            if language == "javascript":
                _javascript += 1
            else:
                _python += 1
            if node_type and len(_node_types) < _MAX_NODE_TYPES:
                _node_types.add(str(node_type))
            if duration_ms is not None:
                _durations.append(float(duration_ms))
            _last_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    except Exception:
        pass


class _InFlight:
    def __enter__(self):
        global _in_flight
        try:
            with _LOCK:
                _in_flight += 1
        except Exception:
            pass
        return self

    def __exit__(self, exc_type, exc, tb):
        global _in_flight
        try:
            with _LOCK:
                # Clamped: a negative gauge would send someone hunting a bug in
                # the wrong process.
                _in_flight = max(0, _in_flight - 1)
        except Exception:
            pass
        return False


def in_flight() -> _InFlight:
    """Context manager around a sandbox round trip. Released even on raise."""
    return _InFlight()


def uptime_seconds() -> int:
    try:
        return int(time.monotonic() - _started)
    except Exception:
        return 0


def snapshot() -> dict:
    """Counters as plain JSON.

    Takes the lock once, copies the window, releases it, and only then sorts
    and buckets. Holding the lock across the percentile computation would put
    an O(n log n) sort on the path of every execution that wants to record.
    """
    try:
        with _LOCK:
            durations = list(_durations)
            payload = {
                "total": _total,
                "ok": _ok,
                "error": _error,
                "python": _python,
                "javascript": _javascript,
                "inFlight": _in_flight,
                "distinctNodeTypes": len(_node_types),
                "lastExecutionAt": _last_at,
            }
    except Exception:
        return _empty()

    payload["durations"] = _summarise(durations)
    return payload


def reset() -> None:
    """Drop all state. For tests only."""
    global _total, _ok, _error, _python, _javascript, _in_flight, _last_at, _started
    with _LOCK:
        _total = _ok = _error = _python = _javascript = _in_flight = 0
        _node_types.clear()
        _durations.clear()
        _last_at = None
        _started = time.monotonic()


def _summarise(durations: list) -> dict:
    ordered = sorted(durations)
    buckets = []
    for bound in DURATION_BUCKETS_MS:
        if bound is None:
            count = sum(1 for d in ordered if d > DURATION_BUCKETS_MS[-2])
        else:
            lower = 0 if bound == DURATION_BUCKETS_MS[0] else _previous_bound(bound)
            count = sum(1 for d in ordered if lower < d <= bound)
        buckets.append({"leMs": bound, "count": count})
    return {
        "windowSize": DURATION_WINDOW,
        "count": len(ordered),
        "p50Ms": _percentile(ordered, 0.50),
        "p90Ms": _percentile(ordered, 0.90),
        "p99Ms": _percentile(ordered, 0.99),
        "maxMs": int(ordered[-1]) if ordered else None,
        "buckets": buckets,
    }


def _previous_bound(bound):
    index = DURATION_BUCKETS_MS.index(bound)
    return DURATION_BUCKETS_MS[index - 1]


def _percentile(ordered: list, fraction: float):
    """Nearest-rank percentile, or None on an empty window."""
    if not ordered:
        return None
    rank = max(1, int(round(fraction * len(ordered))))
    return int(ordered[min(rank, len(ordered)) - 1])


def _empty() -> dict:
    return {
        "total": 0, "ok": 0, "error": 0, "python": 0, "javascript": 0,
        "inFlight": 0, "distinctNodeTypes": 0, "lastExecutionAt": None,
        "durations": _summarise([]),
    }
