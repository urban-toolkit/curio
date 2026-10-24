"""DuckDB's import-time default connection, and the threads it holds.

On DuckDB 1.x, ``import duckdb`` does more than load a library: it builds the
DB API ``NUMBER`` type object from type names it parses on the default
connection, which opens that in-memory connection, and with it a pool of one
thread per core. Curio's processes never query through that connection; every
query goes through one of their own (the sandbox's store in
``sandbox/util/db.py``, the writers in ``sandbox/util/codec.py``). So the pool
idles for the life of each process: 191 threads in every backend and sandbox
on a 192-core host. Six stacks in one CI container held 4006 threads against
its limit of 4096 that way, and the next thread any of them started failed.

Closing the connection joins those threads. Node code loses nothing: the
module-level API (``duckdb.sql`` and friends) opens a fresh default connection
on first use, with its full thread pool, and explicit ``duckdb.connect()``
calls were never affected.

DuckDB 2.0 opens the default connection on first use only
(duckdb/duckdb-python#680), so its import leaves nothing to close. DuckDB has
no call that tells whether the connection is open without opening it:
``default_connection()``, the module-level ``close()`` and
``connect(":default:")`` all open one when none is. So the version decides,
and on 2.x the servers' release asks for nothing, since asking would open a
pool (19 threads on CI's 4-core runners) only to close it. What that leaves
open is a default connection something in the process opened through the
module-level API before the release. Nothing in Curio's startup does, and the
server tests (``test_server_duckdb_pool.py``) fail if a default connection is
open when a server begins serving.

The zygote still asks on 2.x, and closes what that opens, before its first
fork (*before_fork*). Its children write their outputs through DuckDB, and on
2.0 a child forked from a zygote that had never opened a DuckDB database died
with signal 11 in DuckDB's ``COPY`` in ``codec._write_dataframe_parquet``
(``test_scouts_weather_routing_runs_as_the_exec_user``, the exec-user suite's
weather routing node). One forked after the open and close did not. The
allocator setting below is off by default, and closing any database turns it
off again.

Callers:

- the zygote (``sandbox/isolation/zygote.py``), before its first fork, on
  every DuckDB, since DuckDB's state is not fork-safe;
- the backend and the sandbox servers, at startup, so the pool does not idle
  in them. They fork no node code.
"""

import collections
import importlib
import os
import sys
import time

#: The kernel's PF_EXITING, in a thread's stat flags: the thread has begun to exit.
_EXITING = 0x4

#: Seconds the release waits for the threads it ended to leave /proc.
_EXIT_WAIT = 2.0

#: The first major version of DuckDB whose import opens no default connection
#: (duckdb/duckdb-python#680).
_OPENS_ON_FIRST_USE_SINCE = 2


def _opened_at_import(duckdb):
    """Whether the DuckDB module *duckdb* opened its default connection at import.

    DuckDB 1.x does; 2.0 opens it on first use only. A ``__version__`` that
    does not read as a version counts as 1.x: asking for a default connection
    that is open opens nothing, and on any other DuckDB this costs no more than
    the release always did.
    """
    try:
        major = int(str(getattr(duckdb, "__version__", "")).split(".", 1)[0])
    except ValueError:
        return True
    return major < _OPENS_ON_FIRST_USE_SINCE


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


def exiting_threads():
    """How many threads of this process are exiting, or None where /proc is absent.

    A joined thread can still be listed for a moment: the kernel wakes the
    thread joining it early in its exit, and removes it from
    ``/proc/self/task`` only when the exit ends. Its stat's flags mark it as
    exiting all along.
    """
    task_dir = "/proc/self/task"
    try:
        thread_ids = os.listdir(task_dir)
    except OSError:
        return None
    exiting = 0
    for thread_id in thread_ids:
        try:
            with open(os.path.join(task_dir, thread_id, "stat"),
                      encoding="utf-8", errors="replace") as handle:
                fields = handle.read().rsplit(")", 1)[1].split()
            if int(fields[6]) & _EXITING:
                exiting += 1
        except (OSError, IndexError, ValueError):
            # The thread is gone already, or its stat did not parse.
            continue
    return exiting


def _wait_for_exits(timeout=_EXIT_WAIT):
    """Wait, up to *timeout* seconds, until no thread of this process is exiting."""
    deadline = time.monotonic() + timeout
    while exiting_threads() and time.monotonic() < deadline:
        time.sleep(0.001)


def describe_threads(names):
    """``'17 (python3 x16, duckdb x1)'``: the count, then names by frequency."""
    counts = collections.Counter(names)
    listed = ", ".join(f"{name} x{count}" for name, count in counts.most_common())
    return f"{len(names)} ({listed})"


def release_default_connection(who, consequence, *, names=None, import_first=False,
                               before_fork=False):
    """Close the default connection DuckDB's import opened in this process.

    That is DuckDB 1.x, once it is loaded. On 2.x this returns without asking
    for the connection, which would open it, so the allocator setting it makes
    on 1.x is skipped too, since setting it needs a connection. With
    *before_fork*, it asks on 2.x as well and closes what that opens: the
    zygote's children need a process that has opened a DuckDB database (see
    the module's docstring).

    *who* prefixes the lines this writes to stderr (``"[sandbox]"``), and
    *consequence* ends the warning a failed close gives (``"so its threads stay
    idle"``). *names* lists this process's threads (:func:`thread_names` by
    default); the thread counts on either side are logged so a run can see what
    changed, the second once the threads the close ended have left /proc (up
    to two seconds). With *import_first*, DuckDB is imported first when it is
    installed, so a later import elsewhere in the process finds it loaded and,
    on 1.x, opens no pool of its own.

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
    if not before_fork and not _opened_at_import(duckdb):
        # DuckDB 2.x: the import opened nothing, and asking for the default
        # connection would open it, with its pool, only to close it.
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
            # default; this only makes sure, on 1.x, where a connection is open
            # to set it on.
            connection.execute("SET GLOBAL allocator_background_threads = false")
        except Exception:
            pass
        connection.close()
    except Exception as exc:
        print(f"{who} warning: could not close DuckDB's import-time "
              f"connection, {consequence}: {exc}",
              file=sys.stderr, flush=True)
        return
    # close() joined the pool's threads, but a joined thread stays listed
    # until its exit ends; counted now, it would look as if it were left running.
    _wait_for_exits()
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
