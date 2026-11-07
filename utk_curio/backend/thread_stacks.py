"""Every thread's Python stack, written to a file when the backend gets SIGUSR1.

The stress jobs send the signal after a tier with failures
(``tests/stress/backend_probe.py``), so a backend that stalls shows where
each of its threads waits. The 11-07 stress run's backend stalled with 153 to
664 threads and left no stacks to read. faulthandler's own dump stops after
100 threads, so this one walks ``sys._current_frames()``, which holds them
all, and puts the threads that share a stack together, the largest group
first.

``serve()`` calls :func:`register`, which installs the handler where the
signal exists (not on Windows). Python runs the handler in the main thread,
the server's accept loop, between two of its bytecodes, so it takes no lock
(no ``threading.enumerate()``, no logging) that the code it interrupted may
hold. Each dump is appended to ``backend-thread-stacks.txt`` in the state
folder: ``CURIO_STATE_DIR``, else ``.curio`` in the launch folder, which the
probe finds from the backend's environment. A dump starts with a line naming
the process, the time and the thread count, and ends with :func:`end_line`.
"""

from __future__ import annotations

import os
import signal
import sys
import threading
import time
import traceback
from pathlib import Path

FILE_NAME = "backend-thread-stacks.txt"


def stacks_path(environ=None, cwd=None) -> Path:
    """Where the dumps go, from *environ* and *cwd* (this process's by
    default): the state folder ``user_storage.curio_root`` starts from,
    without its ``test`` folder."""
    environ = os.environ if environ is None else environ
    cwd = os.getcwd() if cwd is None else cwd
    override = environ.get("CURIO_STATE_DIR")
    root = Path(cwd, override) if override else Path(environ.get("CURIO_LAUNCH_CWD") or cwd, ".curio")
    return root / FILE_NAME


def end_line(pid: int) -> str:
    """The line that ends a whole dump of process *pid*."""
    return f"=== end of the thread stacks of pid {pid} ==="


def dump(main_frame=None) -> str:
    """Every thread's stack, the threads with the same stack together.
    *main_frame* stands for the main thread's stack: the frame a signal
    interrupted, so the handler's own frames are left out."""
    frames = sys._current_frames()
    if main_frame is not None:
        frames[threading.main_thread().ident] = main_frame
    # A plain copy of threading's table rather than threading.enumerate(),
    # which takes a lock the interrupted code may hold.
    threads = dict(getattr(threading, "_active", {}))
    groups: dict[str, list[str]] = {}
    for ident, frame in frames.items():
        thread = threads.get(ident)
        name = thread.name if thread is not None else "(not a threading.Thread)"
        groups.setdefault("".join(traceback.format_stack(frame)), []).append(f"{name} [{ident}]")
    pid = os.getpid()
    at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    lines = [f"=== thread stacks of pid {pid} at {at}: "
             f"{len(frames)} thread(s), {len(groups)} different stack(s) ==="]
    for stack, names in sorted(groups.items(), key=lambda group: -len(group[1])):
        lines += ["", f"{len(names)} thread(s): {', '.join(sorted(names))}", stack.rstrip("\n")]
    lines += ["", end_line(pid), ""]
    return "\n".join(lines)


def register() -> bool:
    """Append :func:`dump` to :func:`stacks_path` each time this process gets
    SIGUSR1; False where the signal does not exist, or off the main thread,
    where ``signal.signal`` cannot install a handler."""
    if not hasattr(signal, "SIGUSR1") or threading.current_thread() is not threading.main_thread():
        return False
    path = stacks_path()

    def on_signal(signum, frame) -> None:
        try:
            text = dump(frame)
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as out:
                out.write(text)
        except Exception:  # noqa: BLE001 - see below
            # Never raise into the code the signal interrupted, the server's
            # accept loop: the probe says no dump came instead.
            return

    signal.signal(signal.SIGUSR1, on_signal)
    return True
