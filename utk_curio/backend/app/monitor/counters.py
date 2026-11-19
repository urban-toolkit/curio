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

In a start of several backend processes each holds its own counters, and the
home process's ``/api/monitor`` adds them up (``processes.py``): each other
process sends its :func:`part`, and :func:`merged` sums the totals, counts each
node type once and keeps the newest :data:`DURATION_WINDOW` runs of them all by
the time each ran, so the backend's window is what one process's would be.
:func:`snapshot` is the merge of this process's part alone.
"""

from __future__ import annotations

import collections
import contextlib
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
#: Each run's ``(time.time(), milliseconds)``: its time orders the runs of
#: every process when the home process merges them.
_durations: collections.deque = collections.deque(maxlen=DURATION_WINDOW)
_last_at = None

#: The counts a process's part carries, which the merge sums.
_TOTALS = ("total", "ok", "error", "python", "javascript", "inFlight")


def record_execution(*, language: str, node_type=None, ok: bool,
                     duration_ms=None) -> None:
    """Count one node execution. Never raises.

    ``ok`` must come from the canonical failure predicate, a non-empty
    ``output.path``. Note that a non-empty stderr is NOT the predicate: benign
    warnings land in stderr too, and treating them as failures was the bug that
    made this distinction worth writing down.
    """
    global _total, _ok, _error, _python, _javascript, _last_at
    with contextlib.suppress(Exception):
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
                _durations.append((time.time(), float(duration_ms)))
            _last_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class _InFlight:
    def __enter__(self):
        global _in_flight
        with contextlib.suppress(Exception):
            with _LOCK:
                _in_flight += 1
        return self

    def __exit__(self, exc_type, exc, tb):
        global _in_flight
        with contextlib.suppress(Exception):
            with _LOCK:
                # Clamped: a negative gauge would send someone hunting a bug in
                # the wrong process.
                _in_flight = max(0, _in_flight - 1)
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
    """Counters as plain JSON: this process's :func:`part`, :func:`merged`
    alone."""
    return merged([part()])


def part() -> dict:
    """This process's counters as another backend process of its start sends
    them to the home process (``processes.py``): the counts, the node types
    themselves and each run's duration with its time. Not public: the node
    types are text from clients, and only their count is published.

    Takes the lock once and copies; the sorting is the merge's, after it.
    Holding the lock across it would put an O(n log n) sort on the path of
    every execution that wants to record. Empty when it cannot read them.
    """
    try:
        with _LOCK:
            counts = {
                "total": _total,
                "ok": _ok,
                "error": _error,
                "python": _python,
                "javascript": _javascript,
                "inFlight": _in_flight,
            }
            node_types = list(_node_types)
            durations = [[at, duration] for at, duration in _durations]
            last_at = _last_at
    except Exception:
        return {}
    return {**counts, "nodeTypes": sorted(node_types), "lastExecutionAt": last_at, "durations": durations}


def merged(parts) -> dict:
    """The counters of every process whose :func:`part` is one of *parts*, as
    plain JSON, as one process's :func:`snapshot`: the counts summed, each node
    type counted once up to the cap, the latest run's time, and the duration
    window the newest :data:`DURATION_WINDOW` runs of them all by the time each
    ran. Never raises."""
    try:
        counts = dict.fromkeys(_TOTALS, 0)
        node_types: set = set()
        last_at = None
        window: list = []
        for each in parts:
            if not isinstance(each, dict):
                continue
            for name in _TOTALS:
                counts[name] += _whole(each.get(name))
            node_types.update(str(node_type) for node_type in each.get("nodeTypes") or ())
            at = each.get("lastExecutionAt")
            if isinstance(at, str) and (last_at is None or at > last_at):
                last_at = at
            window.extend(_timed(entry) for entry in each.get("durations") or ())
        timed = sorted((entry for entry in window if entry is not None), key=lambda entry: entry[0])
        durations = [duration for _at, duration in timed[-DURATION_WINDOW:]]
    except Exception:
        return _empty()
    return {
        **counts,
        "distinctNodeTypes": min(len(node_types), _MAX_NODE_TYPES),
        "lastExecutionAt": last_at,
        "durations": _summarise(durations),
    }


def reset() -> None:
    """Drop all state. For tests only."""
    global _total, _ok, _error, _python, _javascript, _in_flight, _last_at, _started
    with _LOCK:
        _total = _ok = _error = _python = _javascript = _in_flight = 0
        _node_types.clear()
        _durations.clear()
        _last_at = None
        _started = time.monotonic()


def _whole(value) -> int:
    """A count a part carries; anything else counts nothing."""
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return max(0, value)


def _timed(entry):
    """A part's run, ``[time, milliseconds]``, as ``(time, milliseconds)``;
    None when it is not one."""
    if not isinstance(entry, (list, tuple)) or len(entry) != 2:
        return None
    at, duration = entry
    if isinstance(at, bool) or isinstance(duration, bool) or not all(
            isinstance(value, (int, float)) for value in (at, duration)):
        return None
    return float(at), float(duration)


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
