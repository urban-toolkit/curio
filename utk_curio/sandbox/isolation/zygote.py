"""A warm, single-threaded process that forks one child per node execution.

NOT VERIFIED ON ANY MACHINE. Linux-only (fork, AF_UNIX, waitpid) and never
executed: written on a Windows host with no container runtime available.

Why a separate process rather than forking from Flask
-----------------------------------------------------
Commit ``1e189ef`` moved execution in-process to cut per-node latency from
500-2000ms to ~10ms, and almost all of that cost is importing geopandas,
pandas, shapely and duckdb. A fresh interpreter per node would put it straight
back. So the imports happen once, here, and each execution is a ``fork`` of
this already-warm process, which costs about a millisecond.

Forking from the Flask process itself would be cheaper still, and wrong:

- Flask runs ``threaded=True``. Forking a multi-threaded process gives the
  child a copy of locks held by threads that do not exist in it, and
  GDAL/PROJ hold locks. The classic symptom is a child that hangs on its
  first ``geopandas`` call.
- The Flask process owns the DuckDB read-write connection. A fork inherits
  that file descriptor, handing the child exactly the access the scratch
  directory exists to deny.

This process is started before either of those is true, starts no threads of
its own (hence the ``selectors`` loop rather than a thread per connection), and
never opens the DuckDB store. What it imports is another matter: ``import
duckdb`` opens an in-memory default connection with a thread pool, and numpy's
OpenBLAS starts one too. OpenBLAS tears its pool down before every fork;
DuckDB does not, which is why ``warm_up`` closes that connection before the
first fork. See :func:`_release_import_time_duckdb`.

Wire protocol, newline-delimited JSON over AF_UNIX, one connection per
execution:

    parent -> zygote   {"code": ..., "scratch_dir": ..., "wall_timeout": 300}
    zygote -> parent   {"pid": 1234}                        just after the fork
    zygote -> parent   {"exit": 0, "signal": null,
                        "timed_out": false}                 once reaped

This process enforces ``wall_timeout`` itself, because it is the child's parent:
while the child is unreaped its pid cannot be recycled, so a kill is guaranteed
to hit the right process. The parent's own socket read is only a liveness
backstop and kills nothing. One connection per execution is what makes
concurrent executions work without any threads on this side.
"""

import argparse
import collections
import errno
import json
import os
import signal
import socket
import sys

SOCKET_BACKLOG = 64

# How long to block in the selector while children are outstanding. Only
# affects how promptly an exited child is reaped and reported; the parent has
# its own timeout, so this is not a correctness deadline.
_REAP_POLL_SECONDS = 0.05


def build_namespace_template():
    """Import everything node code expects and return the seeded globals.

    Deliberately mirrors ``worker._worker_init`` so an isolated node sees the
    same names as an in-process one, with one intentional exception documented
    in :func:`_unavailable_under_isolation`.
    """
    import warnings

    warnings.filterwarnings("ignore")

    # pyproj bundles a proj.db that can lag the system PROJ runtime. Same fix
    # as worker._worker_init; without it EPSG lookups fail in the child.
    import pathlib as _pathlib
    import sys as _sys

    import pyproj.datadir as _pyproj_datadir

    _system_proj = _pathlib.Path(_sys.prefix) / "Library" / "share" / "proj"
    if (_system_proj / "proj.db").exists():
        _pyproj_datadir.set_data_dir(str(_system_proj))

    import ast
    import datetime
    import hashlib
    import io
    import json as _json
    import math
    import mmap
    import time
    import zlib
    from pathlib import Path

    import duckdb
    import geopandas as gpd
    import numpy as np
    import pandas as pd
    import shapely
    from shapely import wkt

    from utk_curio.sandbox.util.codec import detect_kind
    from utk_curio.sandbox.util.parsers import checkIOType

    return {
        "__builtins__": __builtins__,
        "warnings": warnings,
        "gpd": gpd,
        "pd": pd,
        "json": _json,
        "mmap": mmap,
        "zlib": zlib,
        "os": os,
        "time": time,
        "hashlib": hashlib,
        "ast": ast,
        "io": io,
        "np": np,
        "numpy": np,
        "shapely": shapely,
        "wkt": wkt,
        "math": math,
        "datetime": datetime,
        "Path": Path,
        "duckdb": duckdb,
        "detect_kind": detect_kind,
        "checkIOType": checkIOType,
        # The three store helpers the in-process path also seeds are replaced
        # by stubs. See _unavailable_under_isolation.
        "load_from_duckdb": _unavailable_under_isolation("load_from_duckdb"),
        "save_to_duckdb": _unavailable_under_isolation("save_to_duckdb"),
        "save_dataset_parquet": _unavailable_under_isolation("save_dataset_parquet"),
    }


def _unavailable_under_isolation(name):
    """A stub for a store helper the in-process path exposes to node code.

    ``worker._globals_cache`` seeds ``load_from_duckdb``, ``save_to_duckdb``
    and ``save_dataset_parquet`` straight into user scope, so node code can
    read and write any artifact in the store, including other sessions'. That
    is precisely what isolation removes, so these cannot be the real functions
    here.

    Binding the names to a stub rather than leaving them undefined is about the
    error message: a node that used them gets a sentence explaining why it
    stopped working instead of a bare ``NameError``.

    To be clear about what this is worth: it is clarity and defence in depth,
    not the control. Node code is arbitrary Python and can import the real
    module itself. What actually keeps the store out of reach is filesystem
    permissions on ``.curio/data`` for the execution user.
    """

    def _stub(*_args, **_kwargs):
        raise RuntimeError(
            f"{name}() is not available when node execution is isolated. "
            "Nodes exchange data through their inputs and return value rather "
            "than by reaching into the artifact store directly. If you need "
            "this, run with --isolation=off and accept that node code then has "
            "the sandbox's full privileges."
        )

    return _stub


def _thread_names():
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


def _describe_threads(names):
    """``'17 (python3 x16, duckdb x1)'``: the count, then names by frequency."""
    counts = collections.Counter(names)
    listed = ", ".join(f"{name} x{count}" for name, count in counts.most_common())
    return f"{len(names)} ({listed})"


def _release_import_time_duckdb():
    """Close the connection ``import duckdb`` opened, before anything forks.

    ``import duckdb`` does more than load a library: it opens an in-memory
    default connection, and with it a pool of one thread per core. DuckDB's
    state is not fork-safe (duckdb/duckdb-python#292), and a child forked
    from a process holding that pool died with signal 11 in DuckDB's
    ``close()`` inside ``codec._write_dataframe_parquet`` in one or two
    executions out of a hundred. The in-process path, which never forks,
    never did.

    Closing the connection joins those threads, so every child is forked from
    a process with no DuckDB work in flight. Node code loses nothing: the
    module-level API (``duckdb.sql`` and friends) opens a fresh default
    connection on first use -- in the child, with its full thread pool --
    and explicit ``duckdb.connect()`` calls were never affected.

    The thread counts on either side are logged so a run can see what
    changed. Warnings only: a zygote that failed to start would send the
    sandbox back to in-process execution (``sandbox/app/api.py::
    _isolated_runner``), which is far worse than a fork from a busy process.
    """
    duckdb = sys.modules.get("duckdb")
    if duckdb is None:
        return

    before = _thread_names()
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
        print(f"[zygote] warning: could not close DuckDB's import-time "
              f"connection, so children fork with its threads running: {exc}",
              file=sys.stderr, flush=True)
        return
    after = _thread_names()

    if before is None or after is None:
        return
    # What is left is expected: numpy's OpenBLAS pool, which tears itself
    # down on the first fork, and pyarrow's jemalloc background thread
    # ("jemalloc_bg_thd"), which is fork-aware. Neither crashed a child in
    # 1,200 executions of scripts/repro_zygote_fork_crash.py.
    if len(before) > 1:
        print(
            f"[zygote] released DuckDB's import-time connection: threads "
            f"{_describe_threads(before)} -> {_describe_threads(after)}",
            file=sys.stderr, flush=True,
        )


class Zygote:
    """Accept-and-fork loop. Single-threaded on purpose."""

    def __init__(self, socket_path, *, uid=None, gid=None, require_seccomp=False):
        self.socket_path = socket_path
        self.uid = uid
        self.gid = gid
        self.require_seccomp = require_seccomp
        self.namespace_template = None
        # pid -> connection, so an exited child's status reaches the right caller.
        self._pending = {}
        self._listener = None

    # -- lifecycle ---------------------------------------------------------

    def bind(self):
        if os.path.exists(self.socket_path):
            os.unlink(self.socket_path)
        parent = os.path.dirname(self.socket_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(self.socket_path)
        # Only the sandbox user may ask for an execution. Set after bind
        # because the mode of a socket file is not honoured before it exists.
        os.chmod(self.socket_path, 0o600)
        listener.listen(SOCKET_BACKLOG)
        listener.setblocking(False)
        self._listener = listener
        return listener

    def warm_up(self):
        self.namespace_template = build_namespace_template()
        _release_import_time_duckdb()

    def serve_forever(self):
        import selectors

        selector = selectors.DefaultSelector()
        selector.register(self._listener, selectors.EVENT_READ, data="listener")

        # Announce readiness on stdout so the parent does not have to poll the
        # socket to know the (slow) imports finished.
        print("ZYGOTE_READY", flush=True)

        while True:
            timeout = _REAP_POLL_SECONDS if self._pending else None
            for key, _mask in selector.select(timeout=timeout):
                if key.data == "listener":
                    self._accept(selector)
                else:
                    self._handle_request(selector, key.fileobj)
            self._enforce_deadlines()
            self._reap_children()

    def _enforce_deadlines(self):
        """Kill any child that has outlived its wall-clock allowance.

        Done here rather than in the sandbox because this process is the child's
        parent: it has not reaped the child, so the pid is still reserved and
        cannot have been recycled. A kill from anywhere else races pid reuse.

        The child called ``setsid``, so its pid is also its process group id and
        ``killpg`` reaches anything it spawned. ``kill`` as well, for the narrow
        window between ``fork`` and the child reaching ``setsid``, where no
        process group with that id exists yet.
        """
        import time as _time

        now = _time.monotonic()
        for pid, state in list(self._pending.items()):
            deadline = state.get("deadline")
            if deadline is None or now < deadline or state.get("killed"):
                continue
            state["killed"] = True
            state["timed_out"] = True
            for killer, target in ((os.killpg, pid), (os.kill, pid)):
                try:
                    killer(target, signal.SIGKILL)
                except (ProcessLookupError, OSError):
                    continue

    def _accept(self, selector):
        try:
            connection, _address = self._listener.accept()
        except OSError:
            return
        connection.setblocking(True)
        import selectors

        selector.register(connection, selectors.EVENT_READ, data="connection")

    # -- request handling --------------------------------------------------

    def _handle_request(self, selector, connection):
        selector.unregister(connection)
        try:
            line = _read_line(connection)
        except OSError:
            connection.close()
            return
        if not line:
            connection.close()
            return

        try:
            request = json.loads(line)
        except ValueError as exc:
            _send(connection, {"error": f"malformed request: {exc}"})
            connection.close()
            return

        try:
            pid = self._fork_child(request)
        except OSError as exc:
            _send(connection, {"error": f"fork failed: {exc}"})
            connection.close()
            return

        import time as _time

        wall_timeout = request.get("wall_timeout")
        deadline = None
        if isinstance(wall_timeout, (int, float)) and wall_timeout > 0:
            deadline = _time.monotonic() + wall_timeout

        _send(connection, {"pid": pid})
        self._pending[pid] = {
            "connection": connection,
            "deadline": deadline,
            "killed": False,
            "timed_out": False,
        }

    def _fork_child(self, request):
        from utk_curio.sandbox.isolation import child

        pid = os.fork()
        if pid != 0:
            return pid

        # ---- child ----
        # Nothing here may raise past child.main: it calls os._exit in every
        # path, so control never returns to the accept loop in this process.
        try:
            self._listener.close()
        except Exception:
            pass
        for state in self._pending.values():
            try:
                state["connection"].close()
            except Exception:
                pass

        template = self.namespace_template

        def namespace_factory():
            # A shallow copy per execution: user code may rebind names, and a
            # fork is one execution, but this keeps the contract identical to
            # the in-process path's `dict(_globals_cache)`.
            return dict(template)

        child.main(
            request,
            namespace_factory,
            uid=self.uid,
            gid=self.gid,
            require_seccomp=self.require_seccomp,
        )
        os._exit(70)  # unreachable; child.main always exits

    def _reap_children(self):
        """Report every child that has exited since the last pass."""
        while self._pending:
            try:
                pid, status = os.waitpid(-1, os.WNOHANG)
            except ChildProcessError:
                self._pending.clear()
                return
            except OSError as exc:
                if exc.errno == errno.EINTR:
                    continue
                return
            if pid == 0:
                return

            state = self._pending.pop(pid, None)
            if state is None:
                continue
            connection = state["connection"]
            if os.WIFSIGNALED(status):
                payload = {"exit": None, "signal": os.WTERMSIG(status)}
            else:
                payload = {"exit": os.WEXITSTATUS(status), "signal": None}
            # The parent cannot tell a deadline kill from any other SIGKILL, so
            # say which it was; the node error message differs.
            payload["timed_out"] = bool(state.get("timed_out"))
            try:
                _send(connection, payload)
            except OSError:
                pass
            finally:
                connection.close()


def _read_line(connection):
    """Read one newline-terminated frame. Returns b'' on a closed peer."""
    chunks = []
    while True:
        byte = connection.recv(1)
        if not byte:
            return b"".join(chunks)
        if byte == b"\n":
            return b"".join(chunks)
        chunks.append(byte)


def _send(connection, payload):
    connection.sendall(json.dumps(payload, separators=(",", ":")).encode("utf-8") + b"\n")


def _resolve_execution_identity(user):
    """Look up (uid, gid) for the configured execution user.

    Returns (None, None) when no user was configured, which is the normal case
    outside the Docker image: the zygote is then already unprivileged and has
    nothing to drop.
    """
    if not user:
        return None, None
    import pwd

    try:
        entry = pwd.getpwnam(user)
    except KeyError:
        raise SystemExit(
            f"[zygote] execution user {user!r} does not exist. Create it in the "
            "image, or launch without --exec-user."
        )
    return entry.pw_uid, entry.pw_gid


def main(argv=None):
    parser = argparse.ArgumentParser(description="Curio node execution zygote")
    parser.add_argument("--socket", required=True)
    parser.add_argument("--exec-user", default=None)
    parser.add_argument("--require-seccomp", action="store_true")
    args = parser.parse_args(argv)

    if not hasattr(os, "fork"):
        raise SystemExit("[zygote] this platform has no os.fork")

    uid, gid = _resolve_execution_identity(args.exec_user)

    zygote = Zygote(
        args.socket, uid=uid, gid=gid, require_seccomp=args.require_seccomp
    )
    zygote.warm_up()
    zygote.bind()
    try:
        zygote.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            os.unlink(args.socket)
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
