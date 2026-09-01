"""Exclusive locks for the on-disk stores — one implementation, two layers.

Neither layer alone is sufficient in this app:

* An in-process :class:`threading.Lock`, keyed per resource. Flask serves
  requests on threads and ``flock`` is held per *file descriptor*, so two
  threads in one process can each open the lock file and each "hold" the
  same advisory lock.
* A cross-process file lock — POSIX ``fcntl.flock``, Windows
  ``msvcrt.locking``. Werkzeug's reloader runs two processes, and
  ``curio start`` may run more.

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


@contextmanager
def interprocess_lock(lock_path: Path):
    """Best-effort exclusive cross-process lock on *lock_path*.

    POSIX uses ``fcntl.flock``; Windows uses ``msvcrt.locking``. On the rare
    platform with neither, this is a no-op and the caller's in-process lock
    is the only guard.
    """
    if fcntl is not None:
        with open(lock_path, "w") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
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


@contextmanager
def exclusive_lock(lock_path: Path, *, namespace: str, key: str):
    """Both layers at once: thread lock, then cross-process lock.

    The lock file's parent directory must already exist.
    """
    thread_lock = keyed_thread_lock(namespace, key)
    thread_lock.acquire()
    try:
        with interprocess_lock(lock_path):
            yield
    finally:
        thread_lock.release()
