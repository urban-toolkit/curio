"""The sandbox gives freed memory back to the system once it is idle (#408).

Every request runs on a thread of its own (Werkzeug's threaded server), and
glibc's malloc gives threads that allocate at the same time separate arenas.
What a run frees stays in its arena for that arena's next allocation, so after
a re-run every arena that served a loader or a fetch keeps that run's pages
resident, and pyarrow's pool keeps what it cached. The re-run replay
(``tests/_rerun_memory.py``, four loaders of 200k polygons) measured it on
Linux: re-run after re-run the memory in use stayed at 30 MB and nothing in
Python grew, while the free memory the arenas kept grew from 90 MB to about
800 MB, and the sandbox settled 1.1 to 1.5 times one loader's memory above
idle.

So when the last request in flight has finished, the sandbox hands that memory
back: ``malloc_trim(0)`` returns the free pages of every glibc arena, and
pyarrow's pool releases what it keeps cached. That takes a few milliseconds,
and no running request waits for it. Without glibc (macOS, Windows, musl) only
the pyarrow part runs.
"""

from __future__ import annotations

import ctypes
import sys
import threading

from werkzeug.wsgi import ClosingIterator


def _find_malloc_trim():
    """glibc's ``malloc_trim``, or None where the C library has none."""
    if not sys.platform.startswith("linux"):
        return None
    try:
        trim = ctypes.CDLL(None).malloc_trim
    except (AttributeError, OSError):
        return None
    trim.argtypes = [ctypes.c_size_t]
    trim.restype = ctypes.c_int
    return trim


_malloc_trim = _find_malloc_trim()


def release_free_memory() -> None:
    """Return the memory the allocators keep free to the system. Never raises."""
    pyarrow = sys.modules.get("pyarrow")
    if pyarrow is not None:
        try:
            pyarrow.default_memory_pool().release_unused()
        except Exception:  # noqa: BLE001 - giving memory back is best effort
            pass
    if _malloc_trim is not None:
        try:
            _malloc_trim(0)
        except Exception:  # noqa: BLE001
            pass


class ReleaseMemoryWhenIdle:
    """WSGI middleware: :func:`release_free_memory` once no request is left.

    A request counts until its response has been sent: a streamed ``/get``
    holds memory for as long as it streams, so the count drops when the server
    closes the response, not when the view returns.
    """

    def __init__(self, wsgi_app, release=release_free_memory):
        self._app = wsgi_app
        self._release = release
        self._lock = threading.Lock()
        self._in_flight = 0

    def __call__(self, environ, start_response):
        with self._lock:
            self._in_flight += 1
        try:
            response = self._app(environ, start_response)
        except BaseException:
            self._finished()
            raise
        return ClosingIterator(response, [self._finished])

    def _finished(self) -> None:
        with self._lock:
            self._in_flight -= 1
            idle = self._in_flight == 0
        if idle:
            self._release()
