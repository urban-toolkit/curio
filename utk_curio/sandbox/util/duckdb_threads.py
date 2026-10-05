"""DuckDB's import-time default connection, and the threads it holds.

``import duckdb`` does more than load a library: it opens an in-memory default
connection, and with it a pool of one thread per core. Curio's processes never
query through that connection; every query goes through one of their own (the
sandbox's store in ``sandbox/util/db.py``, the writers in
``sandbox/util/codec.py``). So the pool idles for the life of each process:
191 threads in every backend and sandbox on a 192-core host. Six stacks in one
CI container held 4006 threads against its limit of 4096 that way, and the
next thread any of them started failed.

Closing the connection joins those threads. Node code loses nothing: the
module-level API (``duckdb.sql`` and friends) opens a fresh default connection
on first use, with its full thread pool, and explicit ``duckdb.connect()``
calls were never affected.

Callers:

- the zygote (``sandbox/isolation/zygote.py``), before its first fork, since
  DuckDB's state is not fork-safe;
- the backend and the sandbox servers, at startup, so the pool does not idle
  in them.
"""

import collections
import importlib
import os
import sys


def thread_names():
    """The name of every thread in this process, or None where /proc is absent.

    Only Linux has ``/proc/self/task``. Everywhere else the answer is None
    rather than a guess, and the callers skip what they would have reported.
    """
    task_dir = "/proc/self/task"
    try:
        thread_ids = os.listdir(task_dir)
    except OSError:
        return None
    names = []
    for thread_id in thread_ids:
        try:
            with open(os.path.join(task_dir, thread_id, "comm"),
                      encoding="utf-8", errors="replace") as handle:
                names.append(handle.read().strip() or "?")
        except OSError:
            # The thread exited between the listing and the read.
            continue
    return names


def describe_threads(names):
    """``'17 (python3 x16, duckdb x1)'``: the count, then names by frequency."""
    counts = collections.Counter(names)
    listed = ", ".join(f"{name} x{count}" for name, count in counts.most_common())
    return f"{len(names)} ({listed})"


def release_default_connection(who, consequence, *, names=None, import_first=False):
    """Close DuckDB's default connection in this process, if DuckDB is loaded.

    *who* prefixes the lines this writes to stderr (``"[sandbox]"``), and
    *consequence* ends the warning a failed close gives (``"so its threads stay
    idle"``). *names* lists this process's threads (:func:`thread_names` by
    default); the thread counts on either side are logged so a run can see what
    changed. With *import_first*, DuckDB is imported first when it is installed,
    so a later import elsewhere in the process finds it loaded and opens no
    pool of its own.

    Never raises: a process that kept the pool is better than one that did not
    start.
    """
    if import_first and "duckdb" not in sys.modules:
        try:
            importlib.import_module("duckdb")
        except ImportError:
            return
    duckdb = sys.modules.get("duckdb")
    if duckdb is None:
        return
    names = names or thread_names

    before = names()
    try:
        connection = duckdb.default_connection
        if callable(connection):  # a function in current DuckDB, an attribute before
            connection = connection()
        try:
            # DuckDB can run a jemalloc background thread of its own, which
            # is process-wide and would outlive the connection. It is off by
            # default; this only makes sure.
            connection.execute("SET GLOBAL allocator_background_threads = false")
        except Exception:
            pass
        connection.close()
    except Exception as exc:
        print(f"{who} warning: could not close DuckDB's import-time "
              f"connection, {consequence}: {exc}",
              file=sys.stderr, flush=True)
        return
    after = names()

    if before is None or after is None:
        return
    # What is left is expected: numpy's OpenBLAS pool, and pyarrow's jemalloc
    # background thread ("jemalloc_bg_thd").
    if len(before) > 1:
        print(
            f"{who} released DuckDB's import-time connection: threads "
            f"{describe_threads(before)} -> {describe_threads(after)}",
            file=sys.stderr, flush=True,
        )
