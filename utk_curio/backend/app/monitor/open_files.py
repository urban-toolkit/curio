"""Each server's open files over time: a sample every hour, kept 90 days across restarts.

A process may hold so many files, sockets and pipes open at once: its soft
limit (``RLIMIT_NOFILE``). At the limit, each file or connection it opens fails
with "[Errno 24] Too many open files". A leak climbs over hours or days, so the
backend samples both servers every :data:`INTERVAL_SECONDS`, the first time as
it starts (:func:`start_sampler`, which ``server.py``'s ``serve()`` calls in the
home process when it serves): its own count and limit (``common/open_files.py``'s
``in_use``), and the sandbox's, which its ``/monitor`` reply carries beside its
memory. ``GET /api/monitor/open-files`` publishes every hour kept
(:func:`snapshot`): timestamps and numbers only.

The samples are the monitor history ``open-files`` (``history.py``), one file
every backend process writes, ``open-files.json`` in the monitor folder: each
sample is written as it is taken, into its hour's row, which holds the busiest
sample of the hour (:func:`_busier`), the last 90 days of hours. A sample whose
write fails is held, and the next write writes it.

THE WARNING. A sample above :data:`WARN_ABOVE` of a server's limit records an
error in the monitor's errors list (``errors.py``), naming the server and its
counts: once per crossing, and again only after the server's count fell below
:data:`CLEAR_BELOW` of its limit. A sample with no count (a sandbox that did not
answer, a platform that cannot count) leaves the warning as it stands.

SEVERAL BACKEND PROCESSES. In a start of several, every backend process
samples its own open files on its own timer, from when it serves, and warns of
its own, naming itself by its number; only the home process asks the sandbox,
whose files one count covers (:func:`sampler_starts_here`, :func:`sample`).
Each hour's row is then the sample of the busiest process, the one with the
largest share of its own limit, which it names (``backendProcess``), with the
sandbox's count from the home process's sample of that hour.

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
from utk_curio.common import backend_processes, open_files

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

_LOCK = threading.Lock()
#: The servers whose warning stands: recorded, and not yet cleared by a fall
#: below :data:`CLEAR_BELOW`.
_warned: set = set()
_timer: Optional[threading.Timer] = None
#: The wait between two asks of the sandbox; a test's own clock replaces it.
_sleep = time.sleep


def _busier(old: dict, new: dict) -> dict:
    """Two samples of one hour as the row the hour keeps: the busier backend
    process's part (:func:`_load`; the one written first on a tie), with its
    time and, with several processes, its number, and the busier of their
    sandbox parts, which only the home process's samples have."""
    backend = new if _load(new.get("backend")) > _load(old.get("backend")) else old
    sandbox = new if _load(new.get("sandbox")) > _load(old.get("sandbox")) else old
    row = {field: value for field, value in old.items() if field not in _SAMPLE_FIELDS}
    row["sampledAt"] = backend.get("sampledAt")
    row["backend"] = backend.get("backend")
    if backend.get("backendProcess") is not None:
        row["backendProcess"] = backend["backendProcess"]
    row["sandbox"] = sandbox.get("sandbox")
    return row


#: What a sample's row holds beside its hour: when it was taken, the backend's
#: part and, with several processes, its process, and the sandbox's part.
_SAMPLE_FIELDS = ("sampledAt", "backend", "backendProcess", "sandbox")

#: Each row: ``{at, span, sampledAt, backend, backendProcess?, sandbox}``, one
#: an hour. A server's part is ``{"open": n, "limit": n}``, each None where
#: unknown; the sandbox's part is None when it did not answer.
HISTORY = monitor_history.History("open-files", span=monitor_history.AN_HOUR, join=_busier,
                                  clock=lambda: _now())


def sample(*, wait_for_sandbox: float = 0) -> dict:
    """Count this process's open files and limit now, and in the home process
    the sandbox's, write the sample into its hour's row, and warn of a server
    above :data:`WARN_ABOVE` of its limit. Returns the sample as the route
    shows one, whose sandbox part is None in every other process.

    While the sandbox does not answer, it is asked again every
    :data:`SANDBOX_RETRY_SECONDS`, for up to *wait_for_sandbox* seconds. Runs
    in an app context, as the sandbox's call answers a failure through Flask.
    """
    sandbox = _sandbox_counts(wait_for_sandbox) if _this_process() == backend_processes.HOME else None
    backend = _counts(*open_files.in_use())
    now = _now()
    taken = {"sampledAt": now.strftime(monitor_history.STAMP), "backend": backend, "sandbox": sandbox}
    number = _numbered()
    if number is not None:
        taken["backendProcess"] = number
    HISTORY.put(taken, at=now)
    shown = _shown(taken)
    for server in SERVERS:
        _warn_of(server, shown[server], shown["at"])
    return shown


def snapshot() -> dict:
    """The route's body: each hour's sample kept, oldest first, and what the
    page reads them by. ``startedAt`` is when the oldest was taken."""
    now = _now()
    samples = [_shown(row) for row in HISTORY.rows(now=now) if isinstance(row.get("sampledAt"), str)]
    computed = now.strftime(monitor_history.STAMP)
    return {
        "computedAt": computed,
        "startedAt": samples[0]["at"] if samples else computed,
        "maxDays": HISTORY.max_days,
        "intervalSeconds": INTERVAL_SECONDS,
        "warnAbovePercent": round(WARN_ABOVE * 100),
        "clearBelowPercent": round(CLEAR_BELOW * 100),
        "samples": samples,
    }


def _shown(row: dict) -> dict:
    """A sample as the route shows it: when it was taken, both servers'
    parts, and with several processes the backend's process."""
    shown = {"at": row.get("sampledAt"), "backend": row.get("backend"), "sandbox": row.get("sandbox")}
    if row.get("backendProcess") is not None:
        shown["backendProcess"] = row["backendProcess"]
    return shown


def sampler_starts_here(does_startup_work: bool) -> bool:
    """Whether this process samples its open files: the home process when it
    does the startup work, which under Werkzeug's reloader only the process
    that serves does, and every other process of a start of several, which
    serves without the reloader (``server.py``)."""
    return bool(does_startup_work) or _this_process() != backend_processes.HOME


def start_sampler(app) -> None:
    """Sample every :data:`INTERVAL_SECONDS` on a timer thread, the first time
    now, giving the sandbox up to :data:`FIRST_SAMPLE_WAIT_SECONDS` to answer
    (in the home process, which alone asks it). A sample that fails is
    logged, and the next comes an hour later. Off under ``--testing``, whose
    tests call :func:`sample` themselves."""
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
    """Drop the samples this process holds unwritten, and the standing
    warnings. For tests only."""
    HISTORY.drop_pending()
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


def _this_process() -> int:
    """This process's number among the start's backends, home's when the
    launcher's variables cannot be read: a sample never fails over them."""
    try:
        return backend_processes.this_process()
    except ValueError:
        return backend_processes.HOME


def _numbered() -> int | None:
    """This process's number in a start of several backend processes, which
    its samples and warnings name it by; None with one."""
    try:
        several = backend_processes.process_count() > 1
    except ValueError:
        several = False
    return _this_process() if several else None


def _load(counts) -> tuple:
    """How busy a server is in a sample whose part for it is *counts*, to
    compare: the share of its limit where both are known, else its count,
    else nothing."""
    count = counts.get("open") if isinstance(counts, dict) else None
    limit = counts.get("limit") if isinstance(counts, dict) else None
    if _number(count) is not None and _number(limit):
        return 2, count / limit
    if _number(count) is not None:
        return 1, float(count)
    return 0, 0.0


def _named(server: str) -> str:
    """How a warning names *server*: the sandbox, the backend, or in a start of
    several backend processes this one, by its number."""
    number = _numbered() if server == "backend" else None
    if number is not None:
        return f"backend process {number}"
    return f"the {server}"


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
    name = _named(server)
    errors.record(
        server,
        summary=f"{name[:1].upper()}{name[1:]} has {count:,} open files, {share:.1%} of its limit of {limit:,}",
        detail=(
            f"Sampled at {at}. At its limit, each file or connection {name} opens fails with "
            f'"[Errno 24] Too many open files". The Open files chart under Hardware shows its count '
            "over time."
        ),
    )
