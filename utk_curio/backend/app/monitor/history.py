"""The monitor's histories: rows of numbers over time, one file for each,
shared by every backend process and kept across restarts.

THE FILE. A :class:`History` has a name and one JSON document,
``<monitor folder>/<name>.json``: ``{"name": <name>, "format": 2, "rows":
[...]}``. The monitor folder is the one ``curio.py start --monitor-dir`` names
(``CURIO_MONITOR_DIR``), else ``monitor`` in the ``.curio`` tree
``user_storage.curio_root`` resolves, read at each call (:func:`_folder`).
Every backend process of a start writes the same file, and nothing starts it
over: a restart, a deploy that keeps the folder and a start of another number
of processes go on with the rows already there. The folder is its owner's
alone (``0700``, set again at each write that finds it otherwise), so node
code, which runs as another account, neither reads nor writes it.

A ROW covers a time from ``at``, its UTC start (``YYYY-MM-DDTHH:MM:00Z``), for
its ``span``: 5 minutes (``"5m"``) or an hour (``"1h"``). Its identity fields
(:attr:`History.identity`, such as a model) say what it counts, and the rest
are its numbers. A history of 5-minute rows keeps them for the last 24 hours,
counted back from the current 5-minute slot (:data:`RECENT_SLOTS` slots), and
then joins each into its hour's row. Every history keeps the rows of the last
:data:`MAX_DAYS` days counted back from the current hour (the current hour and
the 2,159 before it): a rolling window, so the oldest hour leaves each hour
whether or not anything was written since. A row past the current hour (a
clock set back) is kept.

HOW A ROW JOINS ANOTHER. Two rows of one time and identity are one, joined by
the history's rule (``join``): by default every whole number of the two is
added and every list of whole numbers added place by place (:func:`summed`),
so rows from any number of processes add up exactly, in any order. A history
of samples names its own rule, such as the busier of two samples.

TALLIES (:meth:`History.add`) never touch the disk: under the history's lock
they join the row this process holds for their time and identity, and every
:data:`WRITE_EVERY_SECONDS` a timer thread of the process (:func:`start_writer`,
which ``server.py``'s ``serve()`` starts in every process that serves) writes
what each history holds (:func:`flush_all`). SAMPLES (:meth:`History.put`) take
the same write at once. A write (:meth:`History.flush`) takes what the history
holds, so events go on without waiting for the disk, then, under the file's
lock (``common/file_locks.exclusive_lock``: a thread lock and ``flock``, one
writer at a time across every process), reads the file, joins the held rows
into the file's rows of the same time and identity, joins the 5-minute rows
past the last 24 hours into their hours, leaves out the rows past the last 90
days, and writes the whole document to a temporary file beside it, fsynced and
moved over the file with ``os.replace``: a reader or a crash sees the old file
or the new one, never part of one. A write that fails puts what it took back,
to be written by the next, and is logged once until a write succeeds again.

A FILE THIS VERSION DOES NOT READ. A document of another ``format`` (such as
an earlier version's) is read as no rows, and the next write replaces it. A
file that does not parse is set aside by the next write, as
``<name>.json.unreadable-<UTC time>``, named in the monitor's errors, and a new
one begins.

READS (:meth:`History.rows`) take the file's lock shared, so readers never
wait on each other, and count their windows back from the time they are given,
as a write does: a route never shows a row past either window. They read the
file alone: what a process holds unwritten shows once it is written.

WHEN A PROCESS STOPS, it writes what it holds (:func:`write_on_stop`): the
launcher stops each backend with SIGTERM, whose handler writes, then ends the
process as SIGTERM would have; a process that exits on its own writes at exit.
A process killed outright loses what it held, at most its last minute.

Never raises, as the rest of the monitor never does: the monitor never fails
its subject.
"""

from __future__ import annotations

import atexit
import contextlib
import functools
import itertools
import json
import logging
import os
import re
import signal
import stat
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable, Optional, Sequence

from utk_curio.backend.app.common import file_locks

#: The version of the document a history's file holds.
FORMAT = 2
#: The days a history keeps, counted back from the current hour.
MAX_DAYS = 90
#: A row's span: 5 minutes, or an hour.
FIVE_MINUTES = "5m"
AN_HOUR = "1h"
SPANS = (FIVE_MINUTES, AN_HOUR)
#: The 5-minute slots a history keeps its 5-minute rows for: the last 24 hours.
RECENT_SLOTS = 24 * 12
#: How often each backend process writes what its histories hold.
WRITE_EVERY_SECONDS = 60
#: How an hour is written. Written this way, times sort as text.
HOUR = "%Y-%m-%dT%H:00:00Z"
#: How a row's ``at`` is written: the start of its 5 minutes or of its hour.
SLOT = "%Y-%m-%dT%H:%M:00Z"
STAMP = "%Y-%m-%dT%H:%M:%SZ"
#: The file locks' namespace for the histories, each keyed by its name.
LOCKS = "monitor-history"

_AN_HOUR = re.compile(r"\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])T(?:[01]\d|2[0-3]):00:00Z")
_A_SLOT = re.compile(r"\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])T(?:[01]\d|2[0-3]):[0-5][05]:00Z")

_histories: dict[str, "History"] = {}
_histories_lock = threading.Lock()

log = logging.getLogger(__name__)


def summed(old: dict, new: dict) -> dict:
    """The row *old* and *new* are together: each whole number both hold
    added, each list of whole numbers both hold added place by place, a field
    only *new* holds taken from it, and every other field *old*'s."""
    out = dict(old)
    for field, value in new.items():
        if field not in out:
            out[field] = list(value) if isinstance(value, list) else value
            continue
        held = out[field]
        if _whole(held) and _whole(value):
            out[field] = held + value
        elif _wholes(held) and _wholes(value):
            out[field] = [a + b for a, b in itertools.zip_longest(held, value, fillvalue=0)]
    return out


class History:
    """One named history: its file, and the rows this process holds unwritten.

    *identity* names the fields that say what a row counts. *span* is the
    span its rows start with: :data:`FIVE_MINUTES` (joined into hours after 24
    hours) or :data:`AN_HOUR`. *join* is how two rows of one time and identity
    become one (:func:`summed` by default). *admit*, when given, is how the
    file takes the rows a write holds, from the file's rows and the held rows,
    oldest first: the rows to join, each the held row or another in its place.
    *clock* is what "now" is, read at each call."""

    def __init__(self, name: str, *, identity: Sequence[str] = (), span: str = FIVE_MINUTES,
                 join: Callable[[dict, dict], dict] = summed,
                 admit: Optional[Callable[[list, list], list]] = None,
                 clock: Optional[Callable[[], datetime]] = None, max_days: int = MAX_DAYS):
        if span not in SPANS:
            raise ValueError(f"a history's rows span {' or '.join(SPANS)}, not {span!r}")
        self.name = name
        self.identity = tuple(identity)
        self.span = span
        self.max_days = max_days
        self._join = join
        self._admit = admit
        self._clock = clock
        self._lock = threading.Lock()
        #: Held from a write's take of the rows to its end, so one write of
        #: this history waits for another of this process to land: a stop's
        #: write ends after the minute's.
        self._writing = threading.Lock()
        #: The rows this process holds unwritten, by time, span and identity.
        self._pending: dict[tuple, dict] = {}
        #: Whether the last write failed: a failure is logged once until a
        #: write succeeds again.
        self._failing = False
        #: Why the last read found no rows, logged once until it changes.
        self._unread = ""
        with _histories_lock:
            _histories[name] = self

    def path(self) -> Path:
        """The history's file, in the monitor folder as it is now."""
        return _folder() / f"{self.name}.json"

    def _time(self) -> datetime:
        """Now: the history's clock, else this module's, read at each call."""
        return self._clock() if self._clock is not None else _now()

    # -- what happens -------------------------------------------------------

    def add(self, numbers: dict, *, at: Optional[datetime] = None) -> None:
        """Add *numbers*, a row's identity fields and its numbers, to the row
        this process holds for their identity and their time, *at* or now:
        its 5-minute slot, or its hour. In memory, under the history's lock;
        the next write writes it. Never raises."""
        try:
            row = {field: list(value) if isinstance(value, list) else value for field, value in numbers.items()}
            row["at"] = _slot_of(at or self._time(), self.span).strftime(SLOT)
            row["span"] = self.span
            key = self._key(row)
            with self._lock:
                held = self._pending.get(key)
                self._pending[key] = row if held is None else self._join(held, row)
        except Exception:  # noqa: BLE001 - the monitor never fails its subject
            log.debug("Could not hold a row of the monitor history %s", self.name, exc_info=True)

    def put(self, sample: dict, *, at: Optional[datetime] = None) -> bool:
        """Join *sample*, a row's identity fields and its values, into the
        file's row of its time, *at* or now, at once, by the history's rule.
        Whether it was written; one that was not is held for the next write.
        Never raises."""
        self.add(sample, at=at)
        return self.flush()

    def flush(self, *, now: Optional[datetime] = None) -> bool:
        """Write what this process holds into the file, its windows counted
        back from *now* (the history's clock by default): whether the file
        holds it now. What a write that fails took is held again, for the
        next. Never raises."""
        with self._writing:
            with self._lock:
                batch, self._pending = self._pending, {}
            if not batch:
                return True
            try:
                self._write(batch, now or self._time())
            except Exception as exc:  # noqa: BLE001 - kept for the next write, which tries again
                with self._lock:
                    for key, row in batch.items():
                        held = self._pending.get(key)
                        self._pending[key] = row if held is None else self._join(row, held)
                if not self._failing:
                    self._failing = True
                    log.warning("Could not write the monitor history %s: %s. Its rows are kept, "
                                "and the next write tries again.", self.name, exc)
                return False
        if self._failing:
            self._failing = False
            log.info("The monitor history %s is written again.", self.name)
        return True

    def drop_pending(self) -> None:
        """Forget what this process holds unwritten. For tests only."""
        with self._lock:
            self._pending.clear()

    # -- what is kept -------------------------------------------------------

    def rows(self, *, now: Optional[datetime] = None) -> list[dict]:
        """A copy of every row the file holds, in time order, its windows
        counted back from *now* (the history's clock by default): the
        5-minute rows past the last 24 hours joined into their hours, and none
        past the last 90 days. No rows while there is no file, or none this
        version reads. Never raises."""
        try:
            now = now or self._time()
            folder = _folder()
            path = folder / f"{self.name}.json"
            if not path.is_file():
                return []
            with file_locks.shared_lock(folder / f"{self.name}.lock", namespace=LOCKS, key=self.name):
                data = path.read_bytes()
        except Exception as exc:  # noqa: BLE001 - a route shows no rows rather than failing
            self._read_failed(f"could not be read: {exc}")
            return []
        held = self._parsed(data)
        if held is None:
            self._read_failed("does not hold a history this version reads; the next write sets it aside")
            return []
        self._unread = ""
        return [dict(row) for row in self._settled(held, now)]

    def stamp(self) -> Optional[tuple]:
        """What a reader caches the rows by: the file's identity, times and
        size, which each write changes, or None while there is no file."""
        try:
            status = os.stat(self.path())
        except OSError:
            return None
        return (status.st_ino, status.st_mtime_ns, status.st_ctime_ns, status.st_size)

    # -- the write ----------------------------------------------------------

    def _write(self, batch: dict, now: datetime) -> None:
        """*batch* into the file, under its lock. Raises before the file is
        replaced, never after."""
        folder = _private_folder()
        path = folder / f"{self.name}.json"
        with file_locks.exclusive_lock(folder / f"{self.name}.lock", namespace=LOCKS, key=self.name):
            rows = _read_to_write(self, path, now)
            rows = self._joined(rows, batch)
            document = {"name": self.name, "format": FORMAT, "rows": self._settled(rows, now)}
            _clear_leftovers(folder, self.name)
            _replace(path, document)

    def _joined(self, rows: list[dict], batch: dict) -> list[dict]:
        """The file's *rows* with each row of *batch* joined into the row of
        its time and identity, or added, oldest first."""
        held = sorted(batch.values(), key=_in_time)
        if self._admit is not None:
            held = self._admit(rows, held)
        index = {self._key(row): number for number, row in enumerate(rows)}
        for row in held:
            key = self._key(row)
            number = index.get(key)
            if number is None:
                index[key] = len(rows)
                rows.append(row)
            else:
                rows[number] = self._join(rows[number], row)
        return rows

    def _settled(self, rows: list[dict], now: datetime) -> list[dict]:
        """*rows* as they stand at *now*, in time order: each 5-minute row
        past the last 24 hours joined into its hour's row, and the rows past
        the last :attr:`max_days` days left out. Times are compared as the
        text they are written in, which sorts as they do."""
        recent = (_slot_of(now, FIVE_MINUTES) - timedelta(minutes=5 * (RECENT_SLOTS - 1))).strftime(SLOT)
        kept: list[dict] = []
        index: dict = {}
        older: list[dict] = []
        for row in rows:
            if row["span"] == FIVE_MINUTES and row["at"] < recent:
                older.append(row)
                continue
            index[self._key(row)] = len(kept)
            kept.append(row)
        for row in sorted(older, key=_in_time):
            hour = {**row, "at": _hour_text(row["at"]), "span": AN_HOUR}
            key = self._key(hour)
            number = index.get(key)
            if number is None:
                index[key] = len(kept)
                kept.append(hour)
            else:
                kept[number] = self._join(kept[number], hour)
        oldest = (_slot_of(now, AN_HOUR) - timedelta(hours=self.max_days * 24 - 1)).strftime(SLOT)
        return sorted((row for row in kept if row["at"] >= oldest), key=_in_time)

    def _key(self, row: dict) -> tuple:
        return (row["at"], row["span"], *(row.get(field) for field in self.identity))

    def _parsed(self, data: bytes) -> Optional[list[dict]]:
        """The rows a file's *data* holds that this version reads: none for a
        document of another format, None for one that is not a history's."""
        try:
            document = json.loads(data)
        except ValueError:
            return None
        if not isinstance(document, dict):
            return None
        if document.get("format") != FORMAT:
            return []
        rows = document.get("rows")
        if not isinstance(rows, list):
            return None
        return [row for row in (self._valid(each) for each in rows) if row is not None]

    def _valid(self, row) -> Optional[dict]:
        """*row* when it is one: a time, a span, and each identity field a
        plain value; None otherwise, and it is left out."""
        if not isinstance(row, dict) or row.get("span") not in SPANS:
            return None
        moment = at_of(row.get("at"))
        if moment is None or (row["span"] == AN_HOUR and moment.minute):
            return None
        for field in self.identity:
            value = row.get(field)
            if value is not None and not isinstance(value, (str, int, float)):
                return None
        return dict(row)

    def _set_aside(self, path: Path, now: datetime) -> None:
        """Move the file at *path*, which no version reads, out of the way,
        and name it in the monitor's errors."""
        stamp = now.strftime("%Y%m%dT%H%M%SZ")
        aside = path.with_name(f"{path.name}.unreadable-{stamp}")
        for number in itertools.count(2):
            if not aside.exists():
                break
            aside = path.with_name(f"{path.name}.unreadable-{stamp}-{number}")
        os.replace(path, aside)
        log.warning("The monitor history %s could not be read; it was set aside as %s.", self.name, aside)
        from utk_curio.backend.app.monitor import errors

        errors.record(
            "backend",
            summary=f"The monitor history {self.name} could not be read",
            detail=f"{path} did not hold a history this version reads. It was set aside as {aside.name}, "
                   "and a new one begun.",
        )

    def _read_failed(self, why: str) -> None:
        if why != self._unread:
            self._unread = why
            log.warning("The monitor history %s %s.", self.name, why)


def flush_all(*, now: Optional[datetime] = None) -> dict[str, bool]:
    """Write what every history of this process holds: whether each one's
    file holds it now, by name. Never raises."""
    with _histories_lock:
        histories = list(_histories.values())
    return {history.name: history.flush(now=now) for history in histories}


def at_of(text) -> Optional[datetime]:
    """A row's ``at`` as a UTC time: the start of its 5 minutes or of its
    hour. None when it is not one."""
    if not isinstance(text, str) or not _A_SLOT.fullmatch(text):
        return None
    return _parsed_slot(text)


@functools.lru_cache(maxsize=4096)
def _parsed_slot(text: str) -> Optional[datetime]:
    """*text*, a row's ``at``, parsed once however many rows share it."""
    try:
        return datetime.strptime(text, SLOT).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _hour_text(at: str) -> str:
    """The hour a row's ``at`` is in, written as :data:`HOUR`."""
    return f"{at[:14]}00:00Z"


def hour_of(text) -> Optional[datetime]:
    """An hour written as :data:`HOUR`, as a UTC time, or None when it is not one."""
    if not isinstance(text, str) or not _AN_HOUR.fullmatch(text):
        return None
    try:
        return datetime.strptime(text, HOUR).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def sums_by(rows: Iterable[dict], period: str, identity: Sequence[str],
            join: Callable[[dict, dict], dict] = summed) -> list[dict]:
    """*rows* as one row per *period* (``"hour"`` or ``"day"``, UTC) and
    identity, in time order, each the rows of its period joined (summed by
    default): ``at`` the period's start, ``span`` ``"1h"`` or ``"1d"``. For a
    route's hourly and daily views."""
    if period not in ("hour", "day"):
        raise ValueError(f"rows are summed by hour or by day, not {period!r}")
    out: list[dict] = []
    index: dict = {}
    for row in sorted(rows, key=_in_time):
        moment = at_of(row.get("at"))
        if moment is None:
            continue
        start = moment.replace(minute=0) if period == "hour" else moment.replace(hour=0, minute=0)
        each = {**row, "at": start.strftime(HOUR), "span": "1h" if period == "hour" else "1d"}
        key = (each["at"], *(row.get(field) for field in identity))
        number = index.get(key)
        if number is None:
            index[key] = len(out)
            out.append(each)
        else:
            out[number] = join(out[number], each)
    return out


# -- the writer and the stop ------------------------------------------------------

_timer: Optional[threading.Timer] = None
_timer_lock = threading.Lock()
#: Set once this process writes its histories when it stops (write_on_stop).
_stop_handled = threading.Event()


def start_writer() -> bool:
    """Write what every history holds every :data:`WRITE_EVERY_SECONDS`, on a
    timer thread, from now on: one a process, which ``serve()`` starts in
    every process that serves. Off under ``--testing``, whose tests write the
    histories themselves (``/api/testing/monitor-flush``), as the open-files
    sampler is. Whether it started one."""
    from utk_curio.backend.config import _is_testing

    with _timer_lock:
        if _is_testing() or _timer is not None:
            return False
        _schedule()
    return True


def _schedule() -> None:
    global _timer
    _timer = threading.Timer(WRITE_EVERY_SECONDS, _tick)
    _timer.daemon = True
    _timer.start()


def _tick() -> None:
    try:
        flush_all()
    except Exception:  # noqa: BLE001 - the next minute writes again
        log.exception("Could not write the monitor histories")
    finally:
        with _timer_lock:
            _schedule()


def write_on_stop() -> bool:
    """Write what every history holds when this process stops: at exit, and
    on SIGTERM, which is how the launcher stops a backend (``cli/services.py``,
    ``cli/lifecycle.py``). The SIGTERM handler writes, then ends the process
    as SIGTERM did before it: by the handler there was, else as the signal's
    default does. Python runs it in the main thread, the server's accept loop,
    between two of its bytecodes, and that loop holds none of the locks a write
    takes. Installed once a process, by ``serve()``; off under ``--testing``,
    as :func:`start_writer` is. Whether it handles SIGTERM, which only the
    main thread can install."""
    from utk_curio.backend.config import _is_testing

    if _is_testing() or _stop_handled.is_set():
        return False
    _stop_handled.set()
    atexit.register(_write_quietly)
    if not hasattr(signal, "SIGTERM") or threading.current_thread() is not threading.main_thread():
        return False
    before = signal.getsignal(signal.SIGTERM)

    def on_sigterm(signum, frame) -> None:
        _write_quietly()
        if callable(before):
            before(signum, frame)
            return
        signal.signal(signum, signal.SIG_DFL if before is None else before)
        os.kill(os.getpid(), signum)

    signal.signal(signal.SIGTERM, on_sigterm)
    return True


def _write_quietly() -> None:
    try:
        flush_all()
    except Exception:  # noqa: BLE001 - a process that stops never fails over the monitor
        log.debug("Could not write the monitor histories as the process stopped", exc_info=True)


# -- the folder and the file --------------------------------------------------------

def _folder() -> Path:
    """The monitor folder: ``CURIO_MONITOR_DIR`` (``--monitor-dir``), else
    ``monitor`` in the ``.curio`` tree, read at each call."""
    named = os.environ.get("CURIO_MONITOR_DIR", "").strip()
    if named:
        return Path(named)
    from utk_curio.backend.app.common import user_storage

    return user_storage.curio_root() / "monitor"


def _private_folder() -> Path:
    """The monitor folder, made when it is not there, its owner's alone."""
    folder = _folder()
    folder.mkdir(parents=True, exist_ok=True)
    if os.name == "posix" and stat.S_IMODE(folder.stat().st_mode) != 0o700:
        os.chmod(folder, 0o700)
    return folder


def _read_to_write(history: History, path: Path, now: datetime) -> list[dict]:
    """The rows of the file at *path* a write starts from: none when there is
    no file or one of another format, and none when it does not parse, which
    is set aside."""
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        return []
    held = history._parsed(data)
    if held is None:
        history._set_aside(path, now)
        return []
    return held


def _clear_leftovers(folder: Path, name: str) -> None:
    """Remove the temporary files of *name*'s writes that a process killed
    mid-write left: under the file's lock no other write is under way."""
    for leftover in folder.glob(f".{name}.*.tmp"):
        with contextlib.suppress(OSError):
            leftover.unlink()


def _replace(path: Path, document: dict) -> None:
    """*document* to the file at *path*, through a temporary file beside it,
    fsynced, and ``os.replace``."""
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.stem}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(document, handle, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise


# -- times ------------------------------------------------------------------------

def _slot_of(moment: datetime, span: str) -> datetime:
    """The start of the 5 minutes, or the hour, *moment* is in, in UTC."""
    moment = moment.astimezone(timezone.utc)
    minute = moment.minute - moment.minute % 5 if span == FIVE_MINUTES else 0
    return moment.replace(minute=minute, second=0, microsecond=0)


def _in_time(row: dict) -> tuple:
    return (str(row.get("at") or ""), str(row.get("span") or ""))


def _whole(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _wholes(value) -> bool:
    return isinstance(value, list) and all(_whole(each) for each in value)


def _now() -> datetime:
    return datetime.now(timezone.utc)
