"""A warm, single-threaded process that forks one child per node execution.

Linux-only (fork, AF_UNIX, waitpid). Exercised on every CI run by
docker-compose.ci-isolated.yml and docker-compose.ci-exec-user.yml, the second
with an unprivileged execution account; the workflow asserts the mode the
sandbox reports on /version. This docstring used to say the file had never
executed anywhere, which is what mode.py's OFF default rested on.

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
never opens the DuckDB store. What it imports is another matter: on DuckDB
1.x, ``import duckdb`` opens an in-memory default connection with a thread
pool (2.0 opens it on first use only), and numpy's OpenBLAS starts one too.
OpenBLAS tears its pool down before every fork; DuckDB does not, which is why
``warm_up`` closes that connection before the first fork. See
:func:`_release_import_time_duckdb`. ``warm_up`` also imports pyseccomp, which
every child installs its seccomp filter with, and ``ctypes.util``, which a
child had once it imported pyseccomp itself: libc and libseccomp loaded
through ctypes, and no thread, open file or process left behind. See
:func:`_import_pyseccomp`.

Wire protocol, newline-delimited JSON over AF_UNIX, one connection per
execution:

    parent -> zygote   {"code": ..., "scratch_dir": ..., "wall_timeout": 300}
    zygote -> parent   {"pid": 1234}                        just after the fork
    zygote -> parent   {"exit": 0, "signal": null,
                        "timed_out": false}                 once reaped

This process enforces ``wall_timeout`` itself, because it is the child's parent:
while the child is unreaped its pid cannot be recycled, so a kill is guaranteed
to hit the right process. For the same reason it kills a child's process group
once the child has exited, before it reaps it, so nothing a node started
outlives the node (``_reap_children``). The parent's own socket read is only a
liveness backstop. The parent kills only when this process died mid-run, and
then only that run's process group (``ZygoteClient.run``). One connection per
execution is what makes concurrent executions work without any threads on this
side.

It learns that a child has exited from a pidfd of the child, which its select
watches beside the connections: the select returns as the child exits, and the
child is reaped and reported then (``Zygote._watch``). Without a pidfd the loop
finds the child at its next poll, every ``_REAP_POLL_SECONDS``, as it found
every child before; deadlines are checked on that poll too.

A caller can hang up before its answer comes: ``ZygoteClient`` gives up on the
pid after ``connect_timeout``. The answer that fails then closes that one
connection, and the loop serves the others; a child whose caller never learned
its pid is stopped, since nothing will read its result.
"""

import argparse
import contextlib
import errno
import json
import os
import signal
import socket
import sys

from utk_curio.sandbox.util.duckdb_threads import (  # noqa: F401  (_describe_threads: tests)
    describe_threads as _describe_threads,
    release_default_connection,
    thread_names as _thread_names,
)

SOCKET_BACKLOG = 64

# How long to block in the selector while children are outstanding: how often
# deadlines are checked, and how soon an exited child that has no pidfd
# (``Zygote._watch``) is reaped and reported. A child with one wakes the select
# as it exits. The parent has its own timeout, so this is not a correctness
# deadline.
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

    import duckdb
    import geopandas as gpd
    import numpy as np
    import pandas as pd
    import shapely
    from shapely import wkt

    from utk_curio.sandbox.util.codec import detect_kind
    from utk_curio.sandbox.util.input_layers import curio_layer
    from utk_curio.sandbox.util.parsers import checkIOType
    from utk_curio.sandbox.util.feature_edits import edit_features

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
        "Path": _pathlib.Path,
        "duckdb": duckdb,
        "detect_kind": detect_kind,
        "checkIOType": checkIOType,
        # The Edit Features node's code applies its edit list with it (#662).
        "curio_edit_features": edit_features,
        # A layer chip, [!! input_0:roads !!], reads one layer of an input with it.
        "curio_layer": curio_layer,
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
            "this, run with CURIO_ISOLATION=off and accept that node code then has "
            "the sandbox's full privileges."
        )

    return _stub


def _release_import_time_duckdb():
    """Close the connection ``import duckdb`` opened, before anything forks.

    On DuckDB 1.x, ``import duckdb`` does more than load a library: it opens
    an in-memory default connection, and with it a pool of one thread per
    core. DuckDB's state is not fork-safe (duckdb/duckdb-python#292), and a
    child forked from a process holding that pool died with signal 11 in
    DuckDB's ``close()`` inside ``codec._write_dataframe_parquet`` in one or
    two executions out of a hundred. The in-process path, which never forks,
    never did.

    Closing the connection joins those threads, so every child is forked from
    a process with no DuckDB work in flight. Node code loses nothing: the
    module-level API (``duckdb.sql`` and friends) opens a fresh default
    connection on first use -- in the child, with its full thread pool --
    and explicit ``duckdb.connect()`` calls were never affected.

    DuckDB 2.0 opens the default connection on first use only, so its import
    leaves the zygote no pool. This still asks for it, which opens it, and
    closes it before the first fork. On 2.0, a child forked from a zygote that
    had never opened a DuckDB database died with signal 11 in DuckDB's
    ``COPY`` in ``codec._write_dataframe_parquet``
    (``test_scouts_weather_routing_runs_as_the_exec_user``, the exec-user
    suite's weather routing node), and one forked after the open and close
    did not. The servers, which fork no node code, skip it on 2.0.

    The thread counts on either side are logged so a run can see what
    changed. What is left is expected: numpy's OpenBLAS pool, which tears
    itself down on the first fork, and pyarrow's jemalloc background thread
    ("jemalloc_bg_thd"), which is fork-aware. Neither crashed a child in 1,200
    executions of scripts/repro_zygote_fork_crash.py.

    Warnings only: a zygote that failed to start would send the sandbox back
    to in-process execution (``sandbox/app/api.py::_isolated_runner``), which
    is far worse than a fork from a busy process. The servers close the same
    connection at startup (``sandbox/util/duckdb_threads.py``).
    """
    release_default_connection(
        "[zygote]",
        "so children fork with its threads running",
        # Looked up on each call, so a test can stand in for it.
        names=lambda: _thread_names(),
        before_fork=True,
    )


def _import_pyseccomp():
    """Import pyseccomp before the first fork, so that no child imports it.

    Every child installs its seccomp filter with pyseccomp
    (``child._install_seccomp_filter``), and one that imported it after its
    fork spent milliseconds of every run on the import. The import loads libc
    and libseccomp through ctypes, finding them by soname with no process
    started (``seccomp_filter.import_pyseccomp``), and leaves no thread or
    open file behind, so a child forked after it inherits nothing in flight.

    ``ctypes.util`` is imported first, for real. A child's own import of
    pyseccomp imported it, so node code that calls ``ctypes.util`` after a
    bare ``import ctypes`` found it there; this keeps it so. The modules it
    imports are this process's already, and pyseccomp's import then puts it
    back as it found it.

    Where pyseccomp or libseccomp is missing, the import fails here and each
    child tries it again and fails as it would have without this: the zygote
    starts as it did.
    """
    try:
        import ctypes.util  # noqa: F401 - for the children, as they had it

        from utk_curio.sandbox.isolation import seccomp_filter

        seccomp_filter.import_pyseccomp()
    except Exception:  # noqa: BLE001 - each child tries again and says why
        pass


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
        self._selector = None
        # Whether a child got no pidfd yet; said once (_watch).
        self._told_no_pidfd = False

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
        _import_pyseccomp()
        _release_import_time_duckdb()

    def serve_forever(self):
        import selectors

        selector = selectors.DefaultSelector()
        selector.register(self._listener, selectors.EVENT_READ, data="listener")
        self._selector = selector

        # Announce readiness on stdout so the parent does not have to poll the
        # socket to know the (slow) imports finished.
        print("ZYGOTE_READY", flush=True)

        while True:
            timeout = _REAP_POLL_SECONDS if self._pending else None
            exited = []
            for key, _mask in selector.select(timeout=timeout):
                if key.data == "listener":
                    self._accept(selector)
                elif key.data == "connection":
                    self._handle_request(selector, key.fileobj)
                else:
                    # A child's pidfd: the child has exited. It is reaped
                    # below, with every other child that has.
                    exited.append(key.data[1])
            self._enforce_deadlines()
            self._reap_children()
            # A pidfd stays readable, so one whose child is still unreaped
            # would wake the select at once, forever. The poll finds that
            # child instead.
            for pid in exited:
                state = self._pending.get(pid)
                if state is not None:
                    self._unwatch(state)

    def _enforce_deadlines(self):
        """Kill any child that has outlived its wall-clock allowance.

        Done here rather than in the sandbox because this process is the child's
        parent: it has not reaped the child, so the pid is still reserved and
        cannot have been recycled. A kill from anywhere else races pid reuse.
        """
        import time as _time

        now = _time.monotonic()
        for pid, state in list(self._pending.items()):
            deadline = state.get("deadline")
            if deadline is None or now < deadline or state.get("killed"):
                continue
            state["killed"] = True
            state["timed_out"] = True
            _kill_group(pid)

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
            _reply(connection, {"error": f"malformed request: {exc}"})
            connection.close()
            return

        try:
            pid = self._fork_child(request, selector, connection)
        except OSError as exc:
            _reply(connection, {"error": f"fork failed: {exc}"})
            connection.close()
            return

        import time as _time

        wall_timeout = request.get("wall_timeout")
        deadline = None
        if isinstance(wall_timeout, (int, float)) and wall_timeout > 0:
            deadline = _time.monotonic() + wall_timeout

        # Pending before the answer, so the child is reaped whatever it does.
        state = {
            "connection": connection,
            "deadline": deadline,
            "killed": False,
            "timed_out": False,
        }
        self._pending[pid] = state
        self._watch(pid, state)
        if not _reply(connection, {"pid": pid}):
            # The caller hung up before it learned the pid, so nothing will
            # read this child's result: stop it now.
            connection.close()
            state["killed"] = True
            _kill_group(pid)
            print(
                f"[zygote] the caller of child {pid} hung up before its pid "
                "came; the child was stopped",
                file=sys.stderr, flush=True,
            )

    def _watch(self, pid, state):
        """Have child *pid*'s exit wake the select, through a pidfd of it.

        A pidfd is readable once its process has exited, so the select returns
        as the child exits and ``_reap_children`` reaps and reports it then.
        Without one the loop learned of an exit only at its next poll, and
        every isolated run waited for it.

        ``pidfd_open`` needs Linux 5.3, and a seccomp profile may refuse it.
        Where it fails, for any reason, the child is left to the poll, as
        every child was before, and that is said once.
        """
        import selectors

        pidfd_open = getattr(os, "pidfd_open", None)
        try:
            if pidfd_open is None:
                raise OSError(errno.ENOSYS, "this Python has no os.pidfd_open")
            pidfd = pidfd_open(pid)
        except OSError as exc:
            if not self._told_no_pidfd:
                self._told_no_pidfd = True
                print(
                    f"[zygote] no pidfd for child {pid} ({exc}); exited "
                    f"children are found every {_REAP_POLL_SECONDS} s instead",
                    file=sys.stderr, flush=True,
                )
            return
        try:
            self._selector.register(pidfd, selectors.EVENT_READ, data=("child", pid))
        except (OSError, ValueError, KeyError):
            os.close(pidfd)
            return
        state["pidfd"] = pidfd

    def _unwatch(self, state):
        """Stop watching a child through its pidfd, if it had one, and close it.

        Unregistered before it is closed: a descriptor number the next accept
        reuses must not still be in the selector.
        """
        pidfd = state.pop("pidfd", None)
        if pidfd is None:
            return
        with contextlib.suppress(KeyError, ValueError):
            self._selector.unregister(pidfd)
        with contextlib.suppress(OSError):
            os.close(pidfd)

    def _fork_child(self, request, selector, connection):
        from utk_curio.sandbox.isolation import child

        # Read before the fork: the child, once its life is tied to this
        # process's, checks that this is still its parent.
        zygote_pid = os.getpid()
        pid = os.fork()
        if pid != 0:
            return pid

        # ---- child ----
        # Nothing here may raise past child.main: it calls os._exit in every
        # path, so control never returns to the accept loop in this process.
        #
        # The listener and the zygote's end of every caller's connection are
        # closed first, by name: this child's own caller's (*connection*),
        # those accepted and not read yet (in the selector), and those of the
        # children still running. Node code must never write to a caller, and
        # a caller must read end-of-file once the zygote is gone, not once
        # this child is.
        try:
            waiting = [key.fileobj for key in selector.get_map().values()
                       if key.data == "connection"]
        except Exception:
            waiting = []
        running = [state["connection"] for state in self._pending.values()]
        for sock in (self._listener, connection, *waiting, *running):
            with contextlib.suppress(Exception):
                sock.close()
        # Then the pidfds the zygote watches the running children through,
        # and last the selector, whose epoll this child shares with the
        # zygote: node code could wait on another run's child through its
        # pidfd, and add descriptors of its own to the zygote's select, which
        # would then never sleep.
        for state in self._pending.values():
            if "pidfd" in state:
                with contextlib.suppress(OSError):
                    os.close(state["pidfd"])
        with contextlib.suppress(Exception):
            selector.close()

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
            zygote_pid=zygote_pid,
        )
        os._exit(70)  # unreachable; child.main always exits
        return None

    def _reap_children(self):
        """Report every child that has exited since the last pass.

        A child's pidfd wakes the loop as the child exits (``_watch``), and is
        closed once the child is reaped.

        Every process a node starts ends when the node does, whichever way it
        ended: it returned, it raised, or its deadline killed it. So a child's
        process group is killed before the child is reaped. ``WNOWAIT`` finds
        an exited child without reaping it, and until the reap after the kill
        its pid, which is its group's id, can go to no other process, so the
        kill reaches that run alone. The owner's rule (11-07), with no way to
        turn it off; ``test_every_process_a_node_starts_ends_when_the_node_*``
        in ``sandbox/tests/test_isolation_linux.py`` guard it.
        """
        while self._pending:
            try:
                exited = os.waitid(os.P_ALL, 0, os.WEXITED | os.WNOHANG | os.WNOWAIT)
            except ChildProcessError:
                for state in self._pending.values():
                    self._unwatch(state)
                self._pending.clear()
                return
            except OSError as exc:
                if exc.errno == errno.EINTR:
                    continue
                return
            if exited is None:
                return

            _kill_group(exited.si_pid)
            try:
                pid, status = os.waitpid(exited.si_pid, 0)
            except ChildProcessError:
                continue

            state = self._pending.pop(pid, None)
            if state is None:
                continue
            self._unwatch(state)
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
                pass  # the caller hung up; the child is reaped all the same
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


def _reply(connection, payload):
    """Send *payload* to a caller; False when the caller has hung up.

    A send to a closed connection fails (a broken pipe, or a reset). That ends
    this one exchange and nothing else: raised, it left the accept loop, the
    zygote exited, and every isolated run after it failed with "could not
    reach the execution zygote" until the stack restarted.
    """
    try:
        _send(connection, payload)
    except OSError:
        return False
    return True


def _kill_group(pid):
    """SIGKILL the child *pid* and anything it spawned.

    The child calls ``setsid``, so its pid is also its process group id and
    ``killpg`` reaches anything it spawned, which the seccomp filter, where it
    is installed, keeps in that group. ``kill`` as well, for the narrow
    window between ``fork`` and the child reaching ``setsid``, where no
    process group with that id exists yet.

    Called at the child's deadline, when its caller hung up before its pid,
    and once it has exited, before it is reaped (``_reap_children``). The
    child is unreaped each time, so its pid can be no other process's.
    """
    for killer, target in ((os.killpg, pid), (os.kill, pid)):
        try:
            killer(target, signal.SIGKILL)
        except (ProcessLookupError, OSError):
            continue


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
            "image, or launch with CURIO_EXEC_USER empty."
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
        pass  # Ctrl-C stops the zygote as a normal exit; its socket goes below
    finally:
        with contextlib.suppress(OSError):
            os.unlink(args.socket)
    return 0


if __name__ == "__main__":
    sys.exit(main())
