"""Each server's open files over time: a sample every hour, for the running process.

A process may hold so many files, sockets and pipes open at once: its soft
limit (``RLIMIT_NOFILE``). At the limit, each file or connection it opens fails
with "[Errno 24] Too many open files". A leak climbs over hours or days, so the
backend samples both servers every :data:`INTERVAL_SECONDS`, the first time as
it starts (:func:`start_sampler`, which ``server.py``'s ``serve()`` calls in the
home process when it serves): its own count and limit (``common/open_files.py``'s
``in_use``), and the sandbox's, which its ``/monitor`` reply carries beside its
memory. ``GET /api/monitor/open-files`` publishes every sample kept
(:func:`snapshot`): timestamps and numbers only.

The samples are the monitor history ``open-files`` (``history.py``): written to
``.curio/monitor/open-files.json`` at each sample, started over when the
backend starts, and at most 90 days of hours, the oldest going first. A write
that fails is logged, and the next hour's sample writes every row again.

THE WARNING. A sample above :data:`WARN_ABOVE` of a server's limit records an
error in the monitor's errors list (``errors.py``), naming the server and its
counts: once per crossing, and again only after the server's count fell below
:data:`CLEAR_BELOW` of its limit. A sample with no count (a sandbox that did not
answer, a platform that cannot count) leaves the warning as it stands.

Never raises, as the rest of the monitor never does.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Optional

from utk_curio.backend.app.monitor import errors
from utk_curio.backend.app.monitor import history as monitor_history
from utk_curio.common import open_files

log = logging.getLogger(__name__)

#: A sample every hour, the first as the backend starts.
INTERVAL_SECONDS = 3600
#: The first sample waits up to this long for the sandbox, which the launcher
#: starts right after the backend.
FIRST_SAMPLE_WAIT_SECONDS = 60
#: Meanwhile it asks the sandbox again this often.
SANDBOX_RETRY_SECONDS = 5
#: A sample above this share of a server's limit records an error ...
WARN_ABOVE = 0.8
#: ... and the server's count falls below this share before it records another.
CLEAR_BELOW = 0.7
#: The servers a sample counts, by the keys it names them by.
SERVERS = ("backend", "sandbox")

#: Each row: ``{hour, at, backend, sandbox}``. A server's part is
#: ``{"open": n, "limit": n}``, each None where unknown; the sandbox's part is
#: None when it did not answer.
HISTORY = monitor_history.History("open-files")

_LOCK = threading.Lock()
#: The servers whose warning stands: recorded, and not yet cleared by a fall
#: below :data:`CLEAR_BELOW`.
_warned: set = set()
_timer: Optional[threading.Timer] = None
#: The wait between two asks of the sandbox; a test's own clock replaces it.
_sleep = time.sleep


def sample(*, wait_for_sandbox: float = 0) -> dict:
    """Count both servers' open files and limits now, keep the sample, and
    warn of a server above :data:`WARN_ABOVE` of its limit. Returns the
    sample's row.

    While the sandbox does not answer, it is asked again every
    :data:`SANDBOX_RETRY_SECONDS`, for up to *wait_for_sandbox* seconds. Runs
    in an app context, as the sandbox's call answers a failure through Flask.
    """
    sandbox = _sandbox_counts(wait_for_sandbox)
    backend = _counts(*open_files.in_use())
    now = _now()
    row = {
        "hour": now.strftime(monitor_history.HOUR),
        "at": now.strftime(monitor_history.STAMP),
        "backend": backend,
        "sandbox": sandbox,
    }
    HISTORY.update(lambda rows: rows.append(dict(row)))
    for server in SERVERS:
        _warn_of(server, row[server], row["at"])
    return row


def snapshot() -> dict:
    """The route's body: every sample kept, oldest first, and what the page
    reads them by."""
    return {
        "computedAt": _now().strftime(monitor_history.STAMP),
        "startedAt": HISTORY.started_at.strftime(monitor_history.STAMP),
        "maxDays": HISTORY.max_days,
        "intervalSeconds": INTERVAL_SECONDS,
        "warnAbovePercent": round(WARN_ABOVE * 100),
        "clearBelowPercent": round(CLEAR_BELOW * 100),
        "samples": [
            {"at": row.get("at"), "backend": row.get("backend"), "sandbox": row.get("sandbox")}
            for row in HISTORY.rows()
        ],
    }


def start_sampler(app) -> None:
    """Sample every :data:`INTERVAL_SECONDS` on a timer thread, the first time
    now, giving the sandbox up to :data:`FIRST_SAMPLE_WAIT_SECONDS` to answer.
    A sample that fails is logged, and the next comes an hour later. Off under
    ``--testing``, whose tests call :func:`sample` themselves."""
    from utk_curio.backend.config import _is_testing

    global _timer
    if _is_testing() or _timer is not None:
        return

    def _tick(wait: float) -> None:
        try:
            with app.app_context():
                sample(wait_for_sandbox=wait)
        except Exception:  # noqa: BLE001 - the next hour samples again
            log.exception("Could not sample the servers' open files")
        finally:
            _schedule(INTERVAL_SECONDS, 0)

    def _schedule(seconds: float, wait: float) -> None:
        global _timer
        _timer = threading.Timer(seconds, _tick, args=(wait,))
        _timer.daemon = True
        _timer.start()

    _schedule(0, FIRST_SAMPLE_WAIT_SECONDS)


def reset() -> None:
    """Drop every sample, as a backend start does, and the standing warnings.
    For tests only."""
    HISTORY.start()
    with _LOCK:
        _warned.clear()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _number(value) -> int | None:
    """A count or a limit as a server reported it; anything else is unknown."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _counts(count, limit) -> dict:
    """A server's part of a sample."""
    return {"open": _number(count), "limit": _number(limit)}


def _sandbox_counts(wait: float) -> dict | None:
    """The sandbox's part of a sample, from its ``/monitor`` reply, or None
    when it did not answer within *wait* seconds."""
    from utk_curio.backend.app.monitor import routes

    asks = 1 + max(0, int(wait // SANDBOX_RETRY_SECONDS))
    for ask in range(asks):
        if ask:
            _sleep(SANDBOX_RETRY_SECONDS)
        payload = routes._sandbox_monitor()
        if payload is not None:
            return _counts(payload.get("open_files"), payload.get("open_files_limit"))
    return None


def _warn_of(server: str, counts: dict | None, at: str) -> None:
    """Record an error when *server*'s sample is above :data:`WARN_ABOVE` of
    its limit and no warning of it stands; a count below :data:`CLEAR_BELOW`
    of its limit clears a standing one."""
    count = (counts or {}).get("open")
    limit = (counts or {}).get("limit")
    if count is None or not limit:
        return
    share = count / limit
    with _LOCK:
        if share < CLEAR_BELOW:
            _warned.discard(server)
            return
        if share <= WARN_ABOVE or server in _warned:
            return
        _warned.add(server)
    errors.record(
        server,
        summary=f"The {server} has {count:,} open files, {share:.1%} of its limit of {limit:,}",
        detail=(
            f"Sampled at {at}. At its limit, each file or connection the {server} opens fails with "
            f'"[Errno 24] Too many open files". The Open files chart under Hardware shows its count '
            "over time."
        ),
    )
