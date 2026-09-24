"""Recent failures, in memory, for the monitor page's error log.

WHAT THIS EXPOSES, AND WHY IT IS DELIBERATE
-------------------------------------------
Entries here are **raw and unredacted**, and `GET /api/monitor/errors` is
public and unauthenticated like the rest of the monitor. On a `--deploy`
instance that means anyone who can reach the URL can read:

- absolute server paths, including the home directory of the account Curio
  runs as,
- fragments of other users' node code, and any data values their tracebacks
  interpolate,
- internal module paths and library versions from stack frames.

That was chosen on purpose so a user hitting a problem can copy the whole
picture into an issue without an operator in the loop. It is the reason this
module exists at all. An operator who does not want that exposure should put
the instance behind a network boundary; there is no redaction to turn on.

The aggregate routes (`/api/monitor`, `/api/monitor/storage`) make the opposite
promise and are tested for it. Keeping the raw text in its own route is what
lets that test be total rather than full of exceptions. Do not move an error
field into an aggregate payload.

TWO BUFFERS, NOT ONE
--------------------
`POST /api/monitor/errors/client` is an unauthenticated write. If browser
reports shared a deque with server-side failures, anyone could evict every real
error by posting junk. They get their own, smaller window instead, so the worst
a flooder can do is drown out other browser reports.
"""

from __future__ import annotations

import collections
import threading
import time

SERVER_WINDOW = 200
CLIENT_WINDOW = 50

# Identical failures inside this many seconds collapse into one entry with a
# count, so a node failing in a retry loop cannot flush the window.
_DEDUP_SECONDS = 60

# Matches the sandbox's cap, so an entry crossing the proxy is never truncated
# twice at two different lengths.
DETAIL_CHARS = 8000
SUMMARY_CHARS = 2000

SOURCES = ("node", "sandbox", "backend", "client")

_LOCK = threading.Lock()
# Timestamps are second-resolution, so two failures in the same second tie.
# A monotonic sequence breaks the tie, otherwise a stable sort silently
# returns them oldest-first inside that second.
_seq = 0
_server: collections.deque = collections.deque(maxlen=SERVER_WINDOW)
_client: collections.deque = collections.deque(maxlen=CLIENT_WINDOW)
_dropped_client = 0


def record(source: str, *, summary: str, detail: str = "",
           context: dict | None = None) -> None:
    """Append one failure. Never raises.

    Same contract as ``execution.runtime_journal.record_execution``: an
    execution must never fail over its bookkeeping.
    """
    global _seq
    try:
        target = _client if source == "client" else _server
        summary_text = str(summary or "").strip()[:SUMMARY_CHARS] or "Error"
        detail_text = str(detail or "")[:DETAIL_CHARS]
        now = time.time()
        with _LOCK:
            for entry in reversed(target):
                if (
                    entry["summary"] == summary_text
                    and entry["detail"] == detail_text
                    and now - entry["_at"] <= _DEDUP_SECONDS
                ):
                    entry["count"] += 1
                    entry["_at"] = now
                    entry["at"] = _iso(now)
                    return
            _seq += 1
            target.append({
                "at": _iso(now),
                "_at": now,
                "_seq": _seq,
                "source": str(source),
                "summary": summary_text,
                "detail": detail_text,
                "context": dict(context or {}),
                "count": 1,
            })
    except Exception:
        pass


def record_dropped_client() -> None:
    """Count one browser report refused by the rate limiter or a size cap."""
    global _dropped_client
    try:
        with _LOCK:
            _dropped_client += 1
    except Exception:
        pass


def summarise_traceback(text: str) -> str:
    """The last non-empty line of a traceback, which is the exception itself.

    A traceback's most useful single line is its last. Falls back to the first
    non-empty line for text that is not a traceback at all.
    """
    try:
        lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
        return lines[-1] if lines else ""
    except Exception:
        return ""


def snapshot(sandbox_entries=None) -> dict:
    """Everything the errors route returns, newest first.

    ``sandbox_entries`` are proxied from the sandbox process and merged here
    rather than stored, because that process owns its own window and restarts
    independently of this one.
    """
    try:
        with _LOCK:
            merged = list(_server) + list(_client)
            dropped = _dropped_client
    except Exception:
        merged, dropped = [], 0

    for entry in (sandbox_entries or []):
        if isinstance(entry, dict):
            merged.append(entry)

    # Sorted on the formatted stamp, which is fixed-width UTC and therefore
    # sorts lexicographically, then on the sequence so same-second entries do
    # not come back oldest-first. Proxied sandbox entries carry no sequence;
    # they sort by stamp alone, which is all the precision they have.
    merged.sort(key=lambda e: (str(e.get("at") or ""), e.get("_seq") or 0),
                reverse=True)
    cleaned = [{k: v for k, v in e.items() if k not in ("_at", "_seq")}
               for e in merged]
    return {
        "serverWindow": SERVER_WINDOW,
        "clientWindow": CLIENT_WINDOW,
        "droppedClient": dropped,
        "errors": cleaned,
    }


def reset() -> None:
    """Drop all state. For tests only."""
    global _dropped_client, _seq
    with _LOCK:
        _server.clear()
        _client.clear()
        _dropped_client = 0
        _seq = 0


def _iso(epoch: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))
