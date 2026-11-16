"""Budgets that hold whole across the backend processes of a start.

``curio.py start --backend-processes N`` runs N backends
(``cli/backend_group.py``), and each dataflow belongs to one of them. What a
budget limits is shared by all of them: the sandbox's isolated pool, the
machine's package workers, an account, a visitor's address, a portal,
Nominatim. So it is one budget for the start, as it is for one process, not
one in each, which together would allow N times it.

With one process each budget is held in its memory, as before
(:func:`across_processes`). With several it is kept in the start's state, in a
folder only the backend reaches (:data:`FOLDER`: made 0700, and in the
isolation's ``hardening.SENSITIVE_PATHS``, since a node that could open a
holder's lock could hold it), each budget's file read and written under its
own lock (``file_locks.exclusive_lock``), as the media cache's room is
(``discovery/application/cache_collection.py``):

- :class:`Places`: places of a budget, at most a limit of them at once in a
  group (an account, or everyone). A place is an entry in the budget's file,
  and its holder holds a lock file of its own while it has it. An entry counts
  only while that lock is held (``file_locks.is_held``), and a process's locks
  go when it ends, so the places of a process that died are free again at once.
  No process id is kept.
- :class:`Semaphore`: a ``threading.BoundedSemaphore`` over such places. A
  waiter is woken at once by a place freed in its own process, and looks every
  :data:`RECHECK_S` for one another process freed.
- :class:`State`: a budget's small state, such as a token bucket's tokens and
  last refill or the next free second, read and changed in one step. It is its
  start's (:data:`BOOT_ID`): a new start reads none of it, as a new process
  holds none.

A budget is checked once as a run, a request or a step takes its place; only a
waiter at a full one looks again, every :data:`RECHECK_S` or when its own
process frees one. A file holds what is live, and stays small.
"""
from __future__ import annotations

import contextlib
import json
import os
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Iterator, Optional

from utk_curio.backend.app.common.file_locks import exclusive_lock, interprocess_lock, is_held
from utk_curio.backend.app.common.owner_only_file import ensure_private_dir
from utk_curio.backend.app.common.user_storage import curio_root
from utk_curio.common import backend_processes

#: The folder of the start's state (``user_storage.curio_root``) the budgets
#: are kept in, one folder each.
FOLDER = "budgets"
#: How often a waiter at a full budget looks for a place another process freed.
RECHECK_S = 0.25
#: The start this process belongs to: the launcher's boot id, which every
#: backend of the start shares, read once.
BOOT_ID = backend_processes.boot_id()

_NAME = re.compile(r"[a-z0-9][a-z0-9-]*")
_KEY = re.compile(r"[0-9a-f]{32}")


def across_processes() -> bool:
    """Whether this start runs several backend processes, so its budgets are
    kept here rather than in this process's memory."""
    return backend_processes.process_count() > 1


def _checked(name: str) -> str:
    if not _NAME.fullmatch(name):
        raise ValueError(f"a budget's name is lowercase words joined by dashes, not {name!r}")
    return name


def _folder(name: str, *, create: bool = True) -> Path:
    """The folder of budget *name*, made 0700 (with the budgets' own) unless
    only looked for."""
    root = curio_root() / FOLDER
    folder = root / name
    if create:
        ensure_private_dir(root)
        ensure_private_dir(folder)
    return folder


def _read(path: Path) -> dict:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):  # none yet, or not one Curio wrote
        return {}
    return doc if isinstance(doc, dict) else {}


def _write(path: Path, doc: dict) -> None:
    """Write *doc* whole: a reader sees the file before or this one."""
    part = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        part.write_text(json.dumps(doc, sort_keys=True), encoding="utf-8")
        os.replace(part, path)
    finally:
        part.unlink(missing_ok=True)


class State:
    """Budget *name*'s small state, a dict every backend process of the start
    reads and changes in one step (:meth:`held`)."""

    def __init__(self, name: str) -> None:
        self.name = _checked(name)

    @contextlib.contextmanager
    def held(self) -> Iterator[dict]:
        """The state, held: no process reads or changes it until the block
        ends, when what the block changed is written back. A state another
        start kept reads as empty."""
        folder = _folder(self.name)
        path = folder / "state.json"
        with exclusive_lock(folder / "state.lock", namespace="budget-state", key=self.name):
            doc = _read(path)
            state = doc.get("state") if doc.get("boot") == BOOT_ID else None
            state = state if isinstance(state, dict) else {}
            before = json.dumps(state, sort_keys=True)
            yield state
            if json.dumps(state, sort_keys=True) != before:
                _write(path, {"boot": BOOT_ID, "state": state})

    def clear(self) -> None:
        """Forget the state, as a test does between cases. Makes nothing where
        nothing was kept."""
        folder = _folder(self.name, create=False)
        if not folder.is_dir():
            return
        with exclusive_lock(folder / "state.lock", namespace="budget-state", key=self.name):
            (folder / "state.json").unlink(missing_ok=True)


class Place:
    """A place taken in a budget (:meth:`Places.take`), held until
    :meth:`release`: its entry in the budget's file, and its holder's lock."""

    def __init__(self, places: "Places", folder: Path, key: str, hold: contextlib.ExitStack) -> None:
        self._places = places
        #: Where it was taken, which is where it goes back to.
        self._folder = folder
        self._key = key
        self._hold = hold
        self._released = False
        self._guard = threading.Lock()

    def release(self) -> None:
        """Give the place back. Its entry goes first, then its lock, so no
        count reads a live place as one whose holder died. A second call does
        nothing."""
        with self._guard:
            if self._released:
                return
            self._released = True
        try:
            self._places._give_back(self._folder, self._key)
        finally:
            self._hold.close()
            with contextlib.suppress(OSError):
                (self._folder / f"{self._key}.lock").unlink()
            self._places._freed()


class Places:
    """Places of budget *name*, at most a limit of them at once in a group,
    counted in every backend process of the start."""

    def __init__(self, name: str) -> None:
        self.name = _checked(name)
        self._frees = threading.Condition()
        self._freed_count = 0

    def take(self, group: str, limit: int) -> Optional[Place]:
        """A place in *group*, or None when *limit* places of it are held."""
        folder = _folder(self.name)
        key = uuid.uuid4().hex
        hold = contextlib.ExitStack()
        hold.enter_context(interprocess_lock(folder / f"{key}.lock"))
        taken = False
        try:
            with self._held(folder):
                live = self._live(folder)
                if sum(1 for held in live.values() if held == group) < limit:
                    live[key] = group
                    _write(folder / "places.json", live)
                    taken = True
        finally:
            if not taken:
                hold.close()
                with contextlib.suppress(OSError):
                    (folder / f"{key}.lock").unlink()
        return Place(self, folder, key, hold) if taken else None

    def wait(self, group: str, limit: int, *, timeout: Optional[float] = None) -> Optional[Place]:
        """A place in *group* as soon as one is free, or None after *timeout*
        seconds. A place freed in this process wakes the wait at once; one
        another process freed is seen within :data:`RECHECK_S`."""
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            with self._frees:
                seen = self._freed_count
            place = self.take(group, limit)
            if place is not None:
                return place
            left = None if deadline is None else deadline - time.monotonic()
            if left is not None and left <= 0:
                return None
            with self._frees:
                if self._freed_count == seen:
                    self._frees.wait(RECHECK_S if left is None else min(RECHECK_S, left))

    def count(self, group: str) -> int:
        """How many places of *group* are held now."""
        folder = _folder(self.name, create=False)
        if not folder.is_dir():
            return 0
        with self._held(folder):
            live = self._live(folder)
        return sum(1 for held in live.values() if held == group)

    def _held(self, folder: Path):
        return exclusive_lock(folder / "places.lock", namespace="budget-places", key=self.name)

    @staticmethod
    def _live(folder: Path) -> dict[str, str]:
        """The budget's places whose holders hold their locks. One whose
        process died holds none, and goes from the file with its lock file.
        The budget is held."""
        path = folder / "places.json"
        listed = _read(path)
        live = {}
        for key, group in listed.items():
            if not _KEY.fullmatch(str(key)) or not isinstance(group, str):
                continue  # not an entry Curio wrote: it holds nothing
            if is_held(folder / f"{key}.lock"):
                live[key] = group
            else:
                with contextlib.suppress(OSError):
                    (folder / f"{key}.lock").unlink()
        if live != listed:
            _write(path, live)
        return live

    def _give_back(self, folder: Path, key: str) -> None:
        with self._held(folder):
            live = self._live(folder)
            if live.pop(key, None) is not None:
                _write(folder / "places.json", live)

    def _freed(self) -> None:
        with self._frees:
            self._freed_count += 1
            self._frees.notify_all()


class Semaphore:
    """A ``threading.BoundedSemaphore`` of *limit* places, which holds across
    the backend processes of a start when it runs several, as budget *name*
    (:class:`Places`), and is that semaphore in this process's memory when it
    runs one."""

    def __init__(self, name: str, limit: int) -> None:
        self.limit = limit
        self._places = Places(name)
        self._alone = threading.BoundedSemaphore(limit)
        #: This process's holds, latest last: a place, or None for one of ``_alone``.
        self._holds: list[Optional[Place]] = []
        self._holds_lock = threading.Lock()

    def acquire(self, blocking: bool = True, timeout: Optional[float] = None) -> bool:
        """Take a place, waiting for one while *blocking*, at most *timeout*
        seconds; whether one was taken."""
        if not blocking and timeout is not None:
            raise ValueError("can't specify timeout for non-blocking acquire")
        if not across_processes():
            if not self._alone.acquire(blocking, timeout):
                return False
            hold = None
        else:
            hold = self._places.wait("", self.limit, timeout=timeout if blocking else 0)
            if hold is None:
                return False
        with self._holds_lock:
            self._holds.append(hold)
        return True

    def release(self) -> None:
        """Give back one of this process's places."""
        with self._holds_lock:
            if not self._holds:
                raise ValueError("Semaphore released too many times")
            hold = self._holds.pop()
        if hold is None:
            self._alone.release()
        else:
            hold.release()

    def __enter__(self) -> bool:
        return self.acquire()

    def __exit__(self, *_exc) -> None:
        self.release()
