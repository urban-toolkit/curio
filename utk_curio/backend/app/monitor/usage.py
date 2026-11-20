"""What this Curio did for the people using it and how long it took, over the
last 90 days, kept across restarts: the monitor page's Usage tab.

THE MEASURES (:data:`MEASURES`), each counted once as it ends (:func:`record`),
with its time and whether it failed:

- ``node.python`` and ``node.javascript``: a node's run as Play runs it
  (``execution/node_exec.py``), each step of a run on the server and of a
  dashboard viewer's run among them, from the call's start to its reply;
  failed when its output names no file, as the execution counters count it.
- ``run``: a dataflow's run on the server (``runs/service.py``: Run All, a run
  up to a node, an automatic run) or a dashboard viewer's (``runs/viewer.py``),
  from its start to its end; failed when it ends ``failed`` or stops on an
  error. A cancelled run and one that ends waiting for the canvas
  (``needs_canvas``) did not fail.
- ``turn``: an agent's chat turn (``agents/application/turns/turn_jobs.py``),
  from its start to its end; failed when it ends with an error. An ask
  withdrawn before its turn started is not counted, and a Solve is a job of
  its own, not a turn.
- ``request``: the backend's answer to a request, from before it is handled
  to its response (``requests.py``, which says which requests it leaves out);
  failed with a 5xx.

THE ROWS are the monitor history ``usage`` (``history.py``), ``usage.json`` in
the monitor folder, which every backend process writes: a measure adds to the
row its process holds for its 5 minutes and key, which the process's writer
adds to the file's within a minute. A row holds sums alone, so the rows of any
number of processes add up exactly: ``{at, span, key, count, failed, us,
buckets}``, its count, those that failed, their total time in whole
microseconds, so a request of a fraction of a millisecond counts its time, and
their count in each of the 19 duration buckets of ``durations.py``. The file
is in format :data:`FILE_FORMAT`: one of the earlier rows' shape (whole
milliseconds, buckets from 50 ms) reads as empty and the next write replaces
it.

THE SESSIONS are a sample every 5 minutes, which the home process takes
(:func:`start_sessions_sampler`) a few seconds after each 5-minute slot ends,
dated to that slot: the sign-ins seen (``UserSession.last_seen_at``, which a
request touches at most once a minute) since the slot began, since its hour
began and since its UTC day began, of accounts and of guests apart. They are
the history ``sessions``, ``sessions.json``. Two rows of one time keep the
larger of each count (:func:`_larger`), so an hour's row holds the sessions
seen in that hour, and a day's the sessions seen that day.

THE STARTS are each start of the home process with its version
(:func:`record_start`), the history ``starts``, ``starts.json``. A start whose
version is not the version of the start before it is a deploy
(:func:`deploys`), which the charts mark.

``GET /api/monitor/usage`` publishes :func:`snapshot`: the sessions seen in
the last 24 hours, read from the database, and three views, as the LLM route's
are: the last 24 hours in 5-minute steps, the last 7 days in hourly steps and
the last 90 days in daily steps. Each view gives its first and last step's
start; each measure's count, failures, milliseconds and 95th percentile time
at every step that had one; each measure's count, failures, milliseconds,
average and 95th percentile time over the whole view; the sessions of
accounts and of guests at each step sampled (in the 5 minutes, the hour or
the day); and the deploys within it.

THE CACHE. As the LLM route's: the body is held for :data:`TTL_SECONDS` and
computed again sooner once one of the three files changed.

Never raises, as ``counters.py`` never does: nothing fails over its
bookkeeping.
"""

from __future__ import annotations

import contextlib
import itertools
import logging
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from utk_curio.backend.app.monitor import durations
from utk_curio.backend.app.monitor import history as monitor_history

log = logging.getLogger(__name__)

#: What the Usage tab counts, in the order it lists them.
MEASURES = ("node.python", "node.javascript", "run", "turn", "request")
#: The page polls this route every 60 s.
TTL_SECONDS = 60
#: A sample of the sessions every 5 minutes, one per slot.
SESSIONS_EVERY_SECONDS = 300
#: How long after its slot ends a sample is taken.
SAMPLE_AFTER_SECONDS = 5
#: The format of ``usage.json``: its rows' times in microseconds, in the buckets from 1 ms.
FILE_FORMAT = 3

#: What a usage row counts: its measure.
_IDENTITY = ("key",)
#: A usage row's sums besides its duration buckets, each a whole number.
_SUMS = ("count", "failed", "us")
#: A sessions row's counts: of accounts and of guests, since its slot began,
#: since its hour began and since its UTC day began.
_SESSION_FIELDS = ("accounts5m", "guests5m", "accounts1h", "guests1h", "accountsDay", "guestsDay")
#: The views the route gives: each one's name, the time a step covers, how many
#: steps it spans (the current one among them), what its rows are summed by
#: (none: the 5-minute rows themselves), and the sessions counts it reads.
_VIEWS = (
    ("24h", timedelta(minutes=5), 24 * 12, None, ("accounts5m", "guests5m")),
    ("7d", timedelta(hours=1), 7 * 24, "hour", ("accounts1h", "guests1h")),
    ("90d", timedelta(days=1), 90, "day", ("accountsDay", "guestsDay")),
)
_STAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
#: A version as ``utk_curio.__version__`` writes one; anything else is "unknown".
_VERSION = re.compile(r"[0-9A-Za-z][0-9A-Za-z.+_-]{0,39}")

_LOCK = threading.Lock()
_cache: dict = {"value": None, "at": 0.0, "stamp": None}
#: The sessions sampler's timer, once it started.
_sampler: dict = {}
_sampler_lock = threading.Lock()


def _larger(old: dict, new: dict) -> dict:
    """Two sessions samples of one time as the row it keeps: the larger of
    each count, and every other field the first's."""
    out = dict(old)
    for field, value in new.items():
        held = out.get(field)
        if field not in out or (_whole(value) and _whole(held) and value > held):
            out[field] = value
    return out


def _kept_first(old: dict, new: dict) -> dict:
    """A start written twice is one start: the row written first, else the new one."""
    return dict(old or new)


def _history_now() -> datetime:
    """Now, read through :func:`_now` at each call, so a test's clock reaches the histories."""
    return _now()


#: Each row: ``{at, span, key, count, failed, us, buckets}``.
HISTORY = monitor_history.History("usage", identity=_IDENTITY, clock=_history_now, file_format=FILE_FORMAT)
#: Each row: ``{at, span, accounts5m, guests5m, accounts1h, guests1h, accountsDay, guestsDay}``.
SESSIONS = monitor_history.History("sessions", join=_larger, clock=_history_now)
#: Each row: ``{at, span, startedAt, version}``, one per start, in the row of its hour.
STARTS = monitor_history.History("starts", identity=("startedAt",), span=monitor_history.AN_HOUR,
                                 join=_kept_first, clock=_history_now)


def record(key: str, *, ms, failed: bool = False) -> None:
    """Count one *key*, a measure of :data:`MEASURES`, that took *ms*
    milliseconds and ended now, *failed* or not. Never raises."""
    try:
        if key not in MEASURES:
            return
        HISTORY.add({
            "key": key,
            "count": 1,
            "failed": 1 if failed else 0,
            "us": durations.whole_us(ms),
            "buckets": durations.counts(ms),
        }, at=_now())
    except Exception:  # noqa: BLE001
        # A request, a run or a turn never fails over its bookkeeping.
        return


# -- the starts -------------------------------------------------------------------

def record_start(version: Optional[str] = None) -> bool:
    """Write that the home process starts now, with *version*
    (``utk_curio.__version__`` by default): whether it was written. Never
    raises."""
    try:
        if version is None:
            import utk_curio

            version = utk_curio.__version__
        now = _now()
        return STARTS.put({"startedAt": now.strftime(monitor_history.STAMP), "version": _version_text(version)},
                          at=now)
    except Exception:  # noqa: BLE001 - a start never fails over the monitor
        log.debug("Could not write the monitor's start", exc_info=True)
        return False


def deploys(rows: Optional[list] = None) -> list[dict]:
    """Each start the history keeps whose version is not the version of the
    start before it, oldest first, ``{at, version}``: a deploy of another
    version, or the first start kept. Of *rows*, else of the file."""
    if rows is None:
        rows = STARTS.rows()
    starts = sorted((row for row in rows if _started(row)), key=_started_at)
    out: list[dict] = []
    before = None
    for row in starts:
        if row["version"] != before:
            out.append({"at": row["startedAt"], "version": row["version"]})
        before = row["version"]
    return out


# -- the sessions -------------------------------------------------------------------

def sample_sessions(*, now: Optional[datetime] = None) -> Optional[dict]:
    """Count the sessions seen in the 5-minute slot that ended last (the
    nearest slot to end before or after *now*, now by default), in its hour
    and in its UTC day, each up to now, and write them as that slot's sample.
    Runs in an app context. The sample, or None when the database could not be
    read. Never raises."""
    try:
        moment = (now or _now()).astimezone(timezone.utc)
        slot = _last_start(moment - timedelta(seconds=SESSIONS_EVERY_SECONDS / 2), timedelta(minutes=5))
        sample: dict = {}
        for suffix, since in (("5m", slot), ("1h", slot.replace(minute=0)),
                              ("Day", slot.replace(hour=0, minute=0))):
            accounts, guests = _seen_since(since)
            sample[f"accounts{suffix}"] = accounts
            sample[f"guests{suffix}"] = guests
    except Exception:  # noqa: BLE001 - the next slot samples again
        log.warning("Could not count the sessions seen", exc_info=True)
        _rolled_back()
        return None
    SESSIONS.put(sample, at=slot)
    return sample


def start_sessions_sampler(app) -> bool:
    """Sample the sessions a few seconds after each 5-minute slot ends, on a
    timer thread, from now on: in the home process, which ``serve()`` starts
    it in beside the open-files sampler. Off under ``--testing``, as that
    sampler is. Whether it started one."""
    from utk_curio.backend.config import _is_testing

    with _sampler_lock:
        if _is_testing() or "timer" in _sampler:
            return False
        _schedule_sample(app)
    return True


def _schedule_sample(app) -> None:
    timer = threading.Timer(_until_next_sample(), _sample_tick, args=(app,))
    timer.daemon = True
    _sampler["timer"] = timer
    timer.start()


def _until_next_sample(now: Optional[datetime] = None) -> float:
    """Seconds from *now* to :data:`SAMPLE_AFTER_SECONDS` past the next
    5-minute slot's start."""
    seconds = (now or _now()).timestamp()
    return SESSIONS_EVERY_SECONDS - seconds % SESSIONS_EVERY_SECONDS + SAMPLE_AFTER_SECONDS


def _sample_tick(app) -> None:
    try:
        with app.app_context():
            sample_sessions()
    except Exception:  # noqa: BLE001 - the next slot samples again
        log.exception("Could not sample the sessions seen")
    finally:
        with _sampler_lock:
            _schedule_sample(app)


def _seen_since(since: datetime) -> tuple[int, int]:
    """The sessions seen from *since* on: of accounts, and of guests. The
    bound is naive UTC, as the column is stored (``stats.py``'s timezone
    trap)."""
    from sqlalchemy import func

    from utk_curio.backend.app.users.models import User, UserSession
    from utk_curio.backend.extensions import db

    cutoff = since.astimezone(timezone.utc).replace(tzinfo=None)
    counted = (
        db.session.query(User.is_guest, func.count(UserSession.id))
        .join(User, User.id == UserSession.user_id)
        .filter(UserSession.last_seen_at >= cutoff)
        .group_by(User.is_guest)
        .all()
    )
    guests = sum(int(count) for guest, count in counted if guest)
    accounts = sum(int(count) for guest, count in counted if not guest)
    return accounts, guests


def _rolled_back() -> None:
    from utk_curio.backend.extensions import db

    with contextlib.suppress(Exception):
        db.session.rollback()


# -- the route --------------------------------------------------------------------

def snapshot() -> dict:
    """The route's body (see the module docstring), computed again once one of
    the files changed, else at most once per :data:`TTL_SECONDS`."""
    now = time.monotonic()
    with _LOCK:
        stamp = (HISTORY.stamp(), SESSIONS.stamp(), STARTS.stamp())
        cached = _cache.get("value")
        age = now - _cache.get("at", 0.0)
        if cached is not None and _cache.get("stamp") == stamp and age < TTL_SECONDS:
            return _with_age(cached, age)
        value = _summarise()
        _cache.update(value=value, at=time.monotonic(), stamp=stamp)
        return _with_age(value, 0.0)


def reset() -> None:
    """Drop what this process holds unwritten, and the cache. For tests only."""
    for each in (HISTORY, SESSIONS, STARTS):
        each.drop_pending()
    with _LOCK:
        _cache.update(value=None, at=0.0, stamp=None)


def _summarise() -> dict:
    """The body, from the files' rows and the database's sessions."""
    now = _now()
    # A row dated past the current 5 minutes (a clock set back) is in no view.
    current = _last_start(now, timedelta(minutes=5)).strftime(monitor_history.SLOT)
    rows = [row for row in HISTORY.rows(now=now) if _readable(row) and row["at"] <= current]
    samples = [row for row in SESSIONS.rows(now=now) if _sampled(row) and row["at"] <= current]
    kept = deploys(STARTS.rows(now=now))
    return {
        "computedAt": now.strftime(monitor_history.STAMP),
        "maxDays": HISTORY.max_days,
        "measures": list(MEASURES),
        "sessionsLast24h": _sessions_last_24_hours(now),
        "views": {name: _view(step, steps, period, fields, rows, samples, kept, now)
                  for name, step, steps, period, fields in _VIEWS},
    }


def _view(step: timedelta, steps: int, period: Optional[str], fields: tuple,
          rows: list[dict], samples: list[dict], kept: list[dict], now: datetime) -> dict:
    """One view: its steps from the start of the first of its *steps* to the
    start of the current one, each measure's numbers at each step and over
    the view, the sessions at each step, and the deploys within it."""
    last = _last_start(now, step)
    first = last - step * (steps - 1)
    start, end = first.strftime(monitor_history.SLOT), last.strftime(monitor_history.SLOT)
    # Up to now: the end of the current step.
    until = (last + step).strftime(monitor_history.STAMP)
    if period is None:
        series = [row for row in rows if row["span"] == monitor_history.FIVE_MINUTES]
        sampled = [row for row in samples if row["span"] == monitor_history.FIVE_MINUTES]
    else:
        series = monitor_history.sums_by(rows, period, _IDENTITY)
        sampled = monitor_history.sums_by(samples, period, (), join=_larger)
    # Times are compared as the text they are written in, which sorts as they do.
    within = sorted((row for row in series if start <= row["at"] <= end), key=_in_order)
    by_key: dict = {key: [] for key in MEASURES}
    for row in within:
        by_key[row["key"]].append(row)
    accounts, guests = fields
    return {
        "from": start,
        "to": end,
        "stepSeconds": int(step.total_seconds()),
        "rows": [{"at": row["at"], "key": row["key"], "count": row["count"], "failed": row["failed"],
                  "ms": _ms(row["us"]), "p95Ms": durations.shown(durations.percentile(row["buckets"]))}
                 for row in within],
        "measures": [{"key": key, **_stats(_sum(by_key[key]))} for key in MEASURES],
        "sessions": [{"at": row["at"], "accounts": row[accounts], "guests": row[guests]}
                     for row in sorted(sampled, key=_at) if start <= row["at"] <= end],
        "deploys": [deploy for deploy in kept if start <= deploy["at"] < until],
    }


def _sessions_last_24_hours(now: datetime) -> Optional[dict]:
    """The sessions seen in the 24 hours before *now*, of accounts and of
    guests, read from the database; None when it could not be read."""
    try:
        accounts, guests = _seen_since(now - timedelta(hours=24))
    except Exception:  # noqa: BLE001 - the tile reads n/a rather than the route failing
        log.debug("Could not count the sessions of the last 24 hours", exc_info=True)
        _rolled_back()
        return None
    return {"accounts": accounts, "guests": guests}


def _stats(total: dict) -> dict:
    """What the page shows of *total*, the sums of some rows: the count, the
    failures, the milliseconds, the average and the 95th percentile time, each
    time None when nothing was counted."""
    average_us = durations.average(total["us"], total["count"])
    return {
        "count": total["count"],
        "failed": total["failed"],
        "ms": _ms(total["us"]),
        "averageMs": None if average_us is None else durations.shown(average_us / 1000),
        "p95Ms": durations.shown(durations.percentile(total["buckets"])),
    }


def _sum(rows) -> dict:
    """The sums of *rows*, added up."""
    total: dict = {field: 0 for field in _SUMS}
    buckets = [0] * durations.BUCKETS
    for row in rows:
        for field in _SUMS:
            total[field] += row[field]
        buckets = [a + b for a, b in itertools.zip_longest(buckets, row["buckets"], fillvalue=0)]
    total["buckets"] = buckets
    return total


def _readable(row) -> bool:
    """Whether *row* is a usage row this version counts: a measure, whole
    sums, and whole bucket counts."""
    return (isinstance(row, dict) and row.get("key") in MEASURES
            and all(_whole(row.get(field)) for field in _SUMS)
            and isinstance(row.get("buckets"), list) and all(_whole(count) for count in row["buckets"]))


def _sampled(row) -> bool:
    """Whether *row* is a sessions sample this version reads: every count whole."""
    return isinstance(row, dict) and all(_whole(row.get(field)) for field in _SESSION_FIELDS)


def _started(row) -> bool:
    """Whether *row* is a start this version reads: a time and a version."""
    return (isinstance(row, dict) and isinstance(row.get("startedAt"), str) and bool(_STAMP.fullmatch(row["startedAt"]))
            and isinstance(row.get("version"), str))


def _started_at(row: dict) -> str:
    return row["startedAt"]


def _at(row: dict) -> str:
    return row["at"]


def _in_order(row: dict) -> tuple:
    return (row["at"], MEASURES.index(row["key"]))


def _version_text(version) -> str:
    """*version* as a start keeps it: the version itself when it is plainly one, else "unknown"."""
    text = version.strip() if isinstance(version, str) else ""
    return text if _VERSION.fullmatch(text) else "unknown"


def _last_start(now: datetime, step: timedelta) -> datetime:
    """The start of the 5 minutes, the hour or the UTC day *now* is in."""
    now = now.astimezone(timezone.utc).replace(second=0, microsecond=0)
    if step == timedelta(minutes=5):
        return now.replace(minute=now.minute - now.minute % 5)
    if step == timedelta(hours=1):
        return now.replace(minute=0)
    return now.replace(hour=0, minute=0)


def _ms(us: int) -> float:
    """*us* microseconds as milliseconds, to the microsecond."""
    return round(us / 1000, 3)


def _whole(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _with_age(value: dict, age: float) -> dict:
    out = dict(value)
    out["ageSeconds"] = int(age)
    out["ttlSeconds"] = TTL_SECONDS
    return out
