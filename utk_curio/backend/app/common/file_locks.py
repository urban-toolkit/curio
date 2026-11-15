"""Locks for the on-disk stores: one implementation, two layers.

Neither layer alone is sufficient in this app:

* An in-process :class:`threading.Lock`, keyed per resource. Flask serves
  requests on threads and ``flock`` is held per *file descriptor*, so two
  threads in one process can each open the lock file and each "hold" the
  same advisory lock.
* A cross-process file lock — POSIX ``fcntl.flock``, Windows
  ``msvcrt.locking``. Werkzeug's reloader runs two processes, and
  ``curio start`` may run more.

A resource is held by one writer (:func:`exclusive_lock`) or by any number of
readers at once (:func:`shared_lock`), never both. A reader passes through
the resource's thread lock to count itself in, so it waits out a writer that
holds it; a writer takes the thread lock, which keeps new readers out, then
waits for the readers already in to leave. So a stream of reads never keeps
a writer out. Across processes, readers take the file lock shared and
writers exclusive; ``msvcrt`` has no shared lock, so there a reader takes it
whole and readers in different processes or threads take turns.

Extracted from :mod:`utk_curio.backend.app.projects.storage`, whose spec
lock was the first consumer, when the package seeder (memo dev/93) needed
the same guarantee for its atomic swap. Keeping one implementation means a
platform quirk gets fixed once rather than per store.
"""
from __future__ import annotations

import threading
from contextlib import contextmanager
from pathlib import Path

try:  # POSIX advisory file locking; unavailable on Windows.
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX fallback
    fcntl = None

try:  # Windows mandatory file locking; unavailable on POSIX.
    import msvcrt
except ImportError:  # pragma: no cover - non-Windows fallback
    msvcrt = None


_thread_locks: dict[tuple[str, str], threading.Lock] = {}
_thread_locks_guard = threading.Lock()


def keyed_thread_lock(namespace: str, key: str) -> threading.Lock:
    """The process-wide lock for one ``(namespace, key)`` resource.

    ``namespace`` separates unrelated consumers (``"spec"``,
    ``"package-seed"``, …) so two stores cannot collide on a shared key.
    """
    with _thread_locks_guard:
        return _thread_locks.setdefault((namespace, key), threading.Lock())


class _Readers:
    """The readers holding one resource in this process: how many, and the
    condition a writer waits on for them to leave."""

    def __init__(self) -> None:
        self.count = 0
        self.left = threading.Condition(threading.Lock())


#: The readers of each ``(namespace, key)`` resource a reader ever took.
_readers: dict[tuple[str, str], _Readers] = {}


def _readers_of(namespace: str, key: str) -> _Readers:
    with _thread_locks_guard:
        return _readers.setdefault((namespace, key), _Readers())


@contextmanager
def interprocess_lock(lock_path: Path, *, shared: bool = False):
    """Best-effort cross-process lock on *lock_path*: exclusive, or shared
    with other shared holders when *shared*.

    POSIX uses ``fcntl.flock``; Windows uses ``msvcrt.locking``, which has no
    shared lock, so there *shared* takes it whole. On the rare platform with
    neither, this is a no-op and the caller's in-process lock is the only
    guard.
    """
    if fcntl is not None:
        with open(lock_path, "w") as handle:
            fcntl.flock(handle, fcntl.LOCK_SH if shared else fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)
    elif msvcrt is not None:  # pragma: no cover - exercised only on Windows
        # Lock a 1-byte region at offset 0 to get a cross-process mutex like
        # flock(LOCK_EX). Unlike flock, ``LK_LOCK`` only retries internally for
        # ~10s and then raises OSError; under sustained contention (e.g. a
        # Play-All install racing a save) that uncaught OSError would propagate
        # out to an HTTP 500. Re-issue the blocking lock until it is acquired so
        # the waiter blocks indefinitely like the POSIX path instead of failing
        # the save (#144).
        with open(lock_path, "a+") as handle:
            while True:
                handle.seek(0)
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
                    break
                except OSError:
                    # The ~10s window elapsed without the region freeing; the
                    # call already blocked, so loop straight back into another
                    # blocking attempt (no busy-spin).
                    continue
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:  # pragma: no cover - neither POSIX nor Windows locking available
        yield


def is_held(lock_path: Path) -> bool:
    """Whether a hold has *lock_path*'s cross-process lock now: one in another
    process, or one in this process through another open of the file. Asks
    without waiting, and creates nothing: a lock file that is not there is held
    by no one.

    A process's file locks go when it ends, so what a process that died held
    reads as free. Where this platform has no file locks no holder can be
    seen, and every lock reads as held.
    """
    if fcntl is not None:
        try:
            handle = open(lock_path, "rb")
        except FileNotFoundError:
            return False
        with handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            fcntl.flock(handle, fcntl.LOCK_UN)
        return False
    if msvcrt is not None:  # pragma: no cover - exercised only on Windows
        try:
            handle = open(lock_path, "r+b")
        except FileNotFoundError:
            return False
        with handle:
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                return True
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return False
    return True  # pragma: no cover - neither POSIX nor Windows locking available


@contextmanager
def exclusive_lock(lock_path: Path, *, namespace: str, key: str):
    """Both layers at once: thread lock, then cross-process lock. A writer's
    hold: once it has the thread lock, it waits for the resource's readers
    (:func:`shared_lock`) to leave, and no new reader comes in.

    The lock file's parent directory must already exist.
    """
    thread_lock = keyed_thread_lock(namespace, key)
    thread_lock.acquire()
    try:
        readers = _readers.get((namespace, key))
        if readers is not None:
            with readers.left:
                while readers.count:
                    readers.left.wait()
        with interprocess_lock(lock_path):
            yield
    finally:
        thread_lock.release()


@contextmanager
def shared_lock(lock_path: Path, *, namespace: str, key: str):
    """A reader's hold of one resource: any number of readers hold it at
    once, never with a writer (:func:`exclusive_lock`). The reader passes
    through the resource's thread lock to count itself in, so it waits out a
    writer that holds it, then takes the cross-process lock shared.

    Not reentrant: a thread that takes it again while a writer waits for it
    to leave deadlocks, as a writer's second hold does.

    The lock file's parent directory must already exist.
    """
    readers = _readers_of(namespace, key)
    with keyed_thread_lock(namespace, key):
        with readers.left:
            readers.count += 1
    try:
        with interprocess_lock(lock_path, shared=True):
            yield
    finally:
        with readers.left:
            readers.count -= 1
            if not readers.count:
                readers.left.notify_all()
