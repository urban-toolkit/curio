"""The monitor's histories: hourly rows kept on disk for the running process.

A :class:`History` has a name, and its rows are plain dicts, each carrying its
UTC hour as ``"hour"`` (``YYYY-MM-DDTHH:00:00Z``, :data:`HOUR`). The process
holds the rows, and every change rewrites ``<state>/monitor/<name>.json``
whole, through a temporary file and a rename, so a reader of the file sees the
old rows or the new ones, never part of them. ``<state>`` is the ``.curio``
tree ``user_storage.curio_root`` resolves, at each write.

A history covers the running process only, as the monitor's counters do: the
start of the home backend, which does the startup work (``create_app``,
``common/backend_processes.py``), writes every history anew, empty, over
whatever an earlier process left (:func:`start`). Nothing carries over a
restart.

A history holds at most :attr:`History.max_days` days of hours, counted back
from its newest row's hour (:data:`MAX_DAYS` by default): once it spans more,
its oldest hours go first. A row whose hour is not one is left out.

Never raises, as the rest of the monitor never does. A write that fails is
logged and keeps the change in the process, and the next change writes every
row again.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

#: The days of hours a history holds, by default.
MAX_DAYS = 90
#: How a row's hour is written. Written this way, hours sort as text.
HOUR = "%Y-%m-%dT%H:00:00Z"
STAMP = "%Y-%m-%dT%H:%M:%SZ"
_AN_HOUR = re.compile(r"\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])T(?:[01]\d|2[0-3]):00:00Z")

_histories: dict[str, "History"] = {}
_histories_lock = threading.Lock()

log = logging.getLogger(__name__)


class History:
    """One named history: its rows in this process, its file beside them."""

    def __init__(self, name: str, *, max_days: int = MAX_DAYS):
        self.name = name
        self.max_days = max_days
        #: When this process started the history: its rows are all since then.
        self.started_at = _now()
        #: One more at every change and start: what a reader caches by.
        self.version = 0
        self._lock = threading.Lock()
        self._rows: list[dict] = []
        with _histories_lock:
            _histories[name] = self

    def path(self) -> Path:
        """The history's file."""
        return _folder() / f"{self.name}.json"

    def rows(self) -> list[dict]:
        """A copy of every row, in the order the rows were added."""
        with self._lock:
            return [dict(row) for row in self._rows]

    def update(self, change: Callable[[list[dict]], None]) -> None:
        """Let *change* edit the rows it is handed, in place, under the
        history's lock; then drop the hours past :attr:`max_days` and write
        the file. Never raises."""
        try:
            with self._lock:
                try:
                    change(self._rows)
                    self._rows = _within(self._rows, self.max_days)
                finally:
                    self.version += 1
                self._write_or_log()
        except Exception:  # noqa: BLE001 - the monitor never fails its subject
            pass

    def start(self) -> None:
        """Empty the history and write its file anew. Never raises."""
        try:
            with self._lock:
                self._rows = []
                self.started_at = _now()
                self.version += 1
                self._write_or_log()
        except Exception:  # noqa: BLE001 - a start never stops over the monitor
            pass

    def _write_or_log(self) -> None:
        """:meth:`_write`, logging a failure: the rows stay in the process,
        and the next change writes them all again."""
        try:
            self._write()
        except Exception as exc:  # noqa: BLE001 - the next change tries again
            log.warning("Could not write the monitor history %s: %s. The next change writes it again.",
                        self.name, exc)

    def _write(self) -> None:
        """The rows to the file, through a temporary file beside it and
        ``os.replace``. Not fsynced: every change writes."""
        path = self.path()
        path.parent.mkdir(parents=True, exist_ok=True)
        doc = {"name": self.name, "startedAt": self.started_at.strftime(STAMP), "rows": self._rows}
        fd, temporary = tempfile.mkstemp(prefix=f".{self.name}.", suffix=".tmp", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(doc, handle, separators=(",", ":"))
            os.replace(temporary, path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(temporary)
            raise


def start() -> None:
    """Write every history anew, empty: the home backend started (``create_app``)."""
    with _histories_lock:
        histories = list(_histories.values())
    for history in histories:
        history.start()


def hour_of(text) -> datetime | None:
    """A row's hour as a UTC datetime, or None when it is not one."""
    if not isinstance(text, str) or not _AN_HOUR.fullmatch(text):
        return None
    try:
        return datetime.strptime(text, HOUR).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _within(rows: list[dict], max_days: int) -> list[dict]:
    """*rows* without the hours more than *max_days* days before the newest
    row's hour, nor a row with no hour: the same list when none goes."""
    kept = [(row, row.get("hour")) for row in rows if isinstance(row, dict)]
    kept = [(row, hour) for row, hour in kept if isinstance(hour, str) and _AN_HOUR.fullmatch(hour)]
    newest = hour_of(max(hour for _row, hour in kept)) if kept else None
    if newest is not None:
        oldest = (newest - timedelta(hours=max_days * 24 - 1)).strftime(HOUR)
        kept = [(row, hour) for row, hour in kept if hour >= oldest]
    if len(kept) == len(rows):
        return rows
    return [row for row, _hour in kept]


def _folder() -> Path:
    """Where the histories' files are: the monitor's folder in ``.curio``."""
    from utk_curio.backend.app.common import user_storage

    return user_storage.curio_root() / "monitor"


def _now() -> datetime:
    return datetime.now(timezone.utc)
