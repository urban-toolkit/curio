"""Two processes at one file at once: the race a thread lock cannot stop.

A backend serves requests on threads, and ``curio start`` may run several
backend processes. A thread lock keeps two threads of one process apart; two
processes each have their own, so only a file lock keeps them apart.

:func:`race` shows whether one does. A forked child goes first and stops at a
:class:`Window`, inside its read-modify-write, after its read. The same write
then runs in the test's process, on a thread. Once that write ended (nothing
kept it out: the race) or waits for a file lock the child holds
(:func:`file_lock_waits`), the child goes on. So no step waits on a timer:
without a lock the write here ends first and the child's stale write lands
after it; with one, the write here waits until the child's has landed.

Forked, never spawned, so the child keeps the test's patches, which is where
its window is. A child must not use the test's database.
"""
from __future__ import annotations

import multiprocessing
import os
import threading
import time
import traceback
from dataclasses import dataclass
from typing import Any, Callable

_FORK = multiprocessing.get_context("fork")

#: How long one side waits for the other before the test fails as hung.
PATIENCE_S = 60.0


class Window:
    """Where the child stops: inside its read-modify-write, after the read."""

    def __init__(self) -> None:
        self._test_process = os.getpid()
        self.reached = _FORK.Event()
        self.go = _FORK.Event()

    def stop_here(self) -> None:
        """In the child, say the window is reached and wait to go on. In the
        test's own process, nothing."""
        if os.getpid() == self._test_process:
            return
        self.reached.set()
        if not self.go.wait(PATIENCE_S):
            raise TimeoutError("the test never let the child go on")


def file_lock_waits(monkeypatch, waits: threading.Event) -> None:
    """Set *waits* when this process asks for a file lock that another
    process holds, as its caller begins to wait (``common.file_locks``)."""
    import fcntl

    from utk_curio.backend.app.common import file_locks

    class _Fcntl:
        LOCK_SH, LOCK_EX, LOCK_UN, LOCK_NB = fcntl.LOCK_SH, fcntl.LOCK_EX, fcntl.LOCK_UN, fcntl.LOCK_NB

        @staticmethod
        def flock(fd, operation):
            if operation in (fcntl.LOCK_SH, fcntl.LOCK_EX):
                try:
                    return fcntl.flock(fd, operation | fcntl.LOCK_NB)
                except BlockingIOError:
                    waits.set()
            return fcntl.flock(fd, operation)

    monkeypatch.setattr(file_locks, "fcntl", _Fcntl)


@dataclass
class Raced:
    #: What the write in the test's process returned.
    here: Any
    #: The child's exit code: 0 when its write ended without raising.
    child_exit: int | None
    #: What the child raised, as its traceback, or "".
    child_error: str


def _child(write: Callable[[], Any], report) -> None:
    try:
        write()
    except Exception:  # the test fails on what is reported here
        report.send(traceback.format_exc())
        raise
    report.send("")


def _start(write: Callable[[], Any]):
    reader, writer = _FORK.Pipe(duplex=False)
    child = _FORK.Process(target=_child, args=(write, writer), daemon=True)
    child.start()
    writer.close()
    return child, reader


def _end(child, reader) -> str:
    """Wait for *child* to end; what it raised, or ""."""
    child.join(PATIENCE_S)
    if child.is_alive():
        child.kill()
        child.join()
        return f"the child did not end within {PATIENCE_S:.0f} s and was killed"
    reported = reader.recv() if reader.poll() else ""
    if not reported and child.exitcode != 0:
        reported = f"the child ended with exit code {child.exitcode}"
    return reported


def race(window: Window, child_write: Callable[[], Any], here_write: Callable[[], Any], monkeypatch) -> Raced:
    """Run *child_write* in a forked child until it stops at *window*, then
    *here_write* in this process, on a thread, and let the child go on once
    that write ended or waits for a file lock. Raises what *here_write*
    raised."""
    settled = threading.Event()
    file_lock_waits(monkeypatch, settled)
    child, reader = _start(child_write)
    outcome: dict[str, Any] = {}
    here = None
    try:
        deadline = time.monotonic() + PATIENCE_S
        while not window.reached.wait(0.05):
            assert child.is_alive(), f"the child ended before its window: {_end(child, reader)}"
            assert time.monotonic() < deadline, "the child never reached its window"

        def _write_here():
            try:
                outcome["value"] = here_write()
            except Exception as exc:  # raised again in the test, below
                outcome["error"] = exc
            finally:
                settled.set()

        here = threading.Thread(target=_write_here, daemon=True)
        here.start()
        assert settled.wait(PATIENCE_S), "the write here neither ended nor waited for a file lock"
    finally:
        window.go.set()
        child_error = _end(child, reader)
        if here is not None:
            here.join(PATIENCE_S)
    assert here is not None and not here.is_alive(), "the write here never ended"
    if "error" in outcome:
        raise outcome["error"]
    return Raced(outcome.get("value"), child.exitcode, child_error)


def in_another_process(call: Callable[[], Any]) -> str:
    """Run *call* to its end in a forked child; what it raised, as its
    traceback, or "" when it ended cleanly."""
    child, reader = _start(call)
    return _end(child, reader)
