"""Parent side of isolated execution: stage, dispatch, time out, persist.

NOT VERIFIED ON ANY MACHINE. The dispatch half needs Linux (AF_UNIX, killpg)
and has never been executed; it was written on a Windows host with no container
runtime available.

This module keeps every privilege the child must not have. It owns the DuckDB
connection, resolves artifacts under session scoping, and decides what a
child's claimed output is allowed to become. The child gets a scratch directory
and nothing else.

The timeout is the part worth reading twice, and it is enforced by the *zygote*,
not here. Two reasons:

- ``proc.kill()`` on the child alone is not enough. Node code can spawn
  processes and those outlive it, so the child calls ``setsid`` and the whole
  process group is killed.
- The killer has to be the child's parent. While the zygote holds an unreaped
  child, that pid cannot be recycled, so the signal is guaranteed to reach the
  intended process. This module used to ``killpg`` a pid it did not own, which
  races pid reuse; inside a container that could have signalled the backend or
  the zygote itself. There is deliberately no kill path left in this file.
"""

import json
import os
import shutil
import signal
import socket
import sys
import tempfile

from utk_curio.sandbox.isolation import protocol
from utk_curio.sandbox.isolation.child import RESULT_FILENAME
from utk_curio.sandbox.isolation.protocol import ProtocolError

# Scratch directories sit BESIDE the shared data dir, not inside it.
#
# Same filesystem either way, which is what lets input staging use a hardlink
# and output persistence use a rename instead of a copy. But inside the store,
# the store itself had to stay traversable by the execution user for a child to
# reach its own scratch directory -- and a directory the child can traverse is
# one where an artifact whose name it can guess is one open() away. Beside the
# store, `.curio/data` can be 0700 with nothing to reach through it.
#
# That is also what makes hardlinking safe under an --exec-user. A hardlink
# shares its source's inode, so the staged copy cannot have permissions of its
# own: whatever the child may read here, it may read at the source. Access is
# denied by the *path* instead -- the store is unreachable, the scratch
# directory is the child's own -- which is a property of the directories, not
# of the file. See hardening.HARDLINK_SOURCES.
SCRATCH_SUBDIR = "exec-scratch"


def scratch_root(shared_data_dir):
    """The directory holding every execution's scratch directory."""
    return os.path.join(os.path.dirname(os.path.abspath(shared_data_dir)),
                        SCRATCH_SUBDIR)

DEFAULT_LIMITS = {
    "memory_mb": 4096,
    # Under the backend's 600s SANDBOX_EXEC_TIMEOUT so the node fails with a
    # real message rather than the browser giving up first.
    "cpu_seconds": 300,
    "nproc": 256,
    "fsize_mb": 8192,
    "nofile": 1024,
}

# Wall-clock allowance. Separate from cpu_seconds because a node that blocks on
# I/O burns no CPU and would otherwise hang until the backend's own deadline.
DEFAULT_WALL_TIMEOUT_SECONDS = 300

# How long past the child's own deadline the parent waits before deciding
# the zygote itself has stopped responding. Only a liveness backstop: the
# zygote enforces the real deadline, so this should never fire.
_BACKSTOP_GRACE_SECONDS = 30

# Windows has neither SIGKILL nor SIGXCPU. Only the POSIX paths in this module
# ever send a signal, but describe_child_death is a pure function that the
# Windows unit suite exercises, so looking these up eagerly would crash it.
# The numeric fallbacks are the Linux values, which is what a status reported
# by the zygote would carry.
SIGKILL = int(getattr(signal, "SIGKILL", 9))
SIGXCPU = int(getattr(signal, "SIGXCPU", 24))


class IsolatedExecutionError(RuntimeError):
    """The child could not be dispatched or its result could not be trusted."""


class ZygoteClient:
    """One request/response exchange with the zygote, over its own connection.

    A connection per execution is what lets several executions run at once
    without the zygote needing threads (it must stay single-threaded to fork
    safely). See ``zygote.py`` for the wire protocol.
    """

    def __init__(self, socket_path, *, connect_timeout=10.0):
        self.socket_path = socket_path
        self.connect_timeout = connect_timeout

    def _connect(self):
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        connection.settimeout(self.connect_timeout)
        try:
            connection.connect(self.socket_path)
        except OSError as exc:
            connection.close()
            raise IsolatedExecutionError(
                f"could not reach the execution zygote at {self.socket_path}: {exc}"
            ) from exc
        return connection

    def run(self, request, *, wall_timeout):
        """Dispatch *request* and wait for the zygote to report the child.

        Returns ``(exit_code, signal_number, timed_out)``.

        The deadline is enforced by the zygote, not here. The zygote is the
        child's parent, so while the child is unreaped its pid cannot be
        recycled and a kill is guaranteed to hit the right process; a kill from
        this process would race pid reuse and could signal something unrelated.
        The socket read below is therefore only a backstop for a zygote that has
        stopped responding altogether, and it deliberately kills nothing.
        """
        connection = self._connect()
        try:
            connection.sendall(protocol.encode_request(request) + b"\n")

            handshake = _read_json_line(connection, timeout=self.connect_timeout)
            if handshake is None:
                raise IsolatedExecutionError("the zygote closed the connection")
            if "error" in handshake:
                raise IsolatedExecutionError(f"zygote refused: {handshake['error']}")
            if not isinstance(handshake.get("pid"), int):
                raise IsolatedExecutionError(f"zygote sent no pid: {handshake!r}")

            try:
                status = _read_json_line(
                    connection, timeout=wall_timeout + _BACKSTOP_GRACE_SECONDS
                )
            except socket.timeout as exc:
                raise IsolatedExecutionError(
                    "the zygote did not report this execution within "
                    f"{wall_timeout + _BACKSTOP_GRACE_SECONDS}s, which means it "
                    "stopped enforcing its own deadline. The child may still be "
                    "running; check the sandbox log."
                ) from exc

            if status is None:
                raise IsolatedExecutionError(
                    "the zygote closed the connection before reporting the child"
                )
            return (
                status.get("exit"),
                status.get("signal"),
                bool(status.get("timed_out")),
            )
        finally:
            try:
                connection.close()
            except OSError:
                pass


def _read_json_line(connection, *, timeout):
    connection.settimeout(timeout)
    chunks = []
    while True:
        byte = connection.recv(1)
        if not byte:
            return None
        if byte == b"\n":
            break
        chunks.append(byte)
    return json.loads(b"".join(chunks).decode("utf-8"))


def user_work_dir(shared_data_dir, user_key):
    """The persistent, writable directory a user's isolated nodes run in.

    Beside the store rather than under ``.curio/users/<key>/``. The user's own
    folder is the more natural home, but ``.curio/users`` is 0700 root-owned so
    that a node cannot reach any *other* user's datasets and projects
    (``hardening.SENSITIVE_PATHS``). Putting a child-writable directory inside
    it means relaxing that to 0711, and then every ``<key>/datasets/`` needs its
    own 0700 -- applied as users appear at runtime, not once at boot. That trades
    a closed cross-user read for a convenience. Here the property is identical:
    per user, persistent, writable, owned by the execution user, and nothing
    else is reachable through it.
    """
    return os.path.join(
        os.path.dirname(os.path.abspath(shared_data_dir)),
        SCRATCH_SUBDIR, "users", str(user_key),
    )


def prepare_user_work_dir(path, *, exec_uid=None, launch_dir=None):
    """Create the user's work directory and make it usable by the child.

    0700 and owned by the execution user: it is the one place an isolated node
    may write, and ``confine`` chdirs into it, so relative reads and writes in
    node code both land here.

    A ``docs`` symlink is dropped in when the launch directory has one. The
    bundled examples read their data relatively
    (``gpd.read_file("docs/examples/data/x.geojson")``), and with the cwd moved
    off the launch directory those paths would resolve to nothing. The link is
    to a root-owned tree, so it reads and does not write.
    """
    os.makedirs(path, exist_ok=True)
    if sys.platform == "win32":
        return path
    try:
        os.chmod(path, 0o700)
        if exec_uid is not None and os.getuid() == 0:
            os.chown(path, exec_uid, -1)
    except OSError:
        pass

    if launch_dir:
        source = os.path.join(launch_dir, "docs")
        link = os.path.join(path, "docs")
        if os.path.isdir(source) and not os.path.lexists(link):
            try:
                os.symlink(source, link)
            except OSError:
                pass
    return path


def make_scratch_dir(shared_data_dir, *, exec_uid=None):
    """Create a private scratch directory for one execution.

    0700, and owned by the execution user when we are root and one was
    configured. Group and other get nothing: two concurrent executions may
    belong to different Curio users, and while both children run as the same
    uid (so this is not a boundary between them), there is no reason to widen
    it further.
    """
    root = scratch_root(shared_data_dir)
    os.makedirs(root, exist_ok=True)
    path = tempfile.mkdtemp(prefix="exec-", dir=root)
    os.chmod(path, 0o700)
    if exec_uid is not None and hasattr(os, "chown") and os.getuid() == 0:
        os.chown(path, exec_uid, -1)
    return path


def read_child_manifest(scratch_dir):
    """Read and validate the manifest the child left behind.

    Anything here is attacker-controlled, so it goes through
    ``protocol.parse_child_result`` with the scratch directory supplied, which
    is what makes the containment check run against real paths.
    """
    path = os.path.join(scratch_dir, RESULT_FILENAME)
    if not os.path.exists(path):
        raise IsolatedExecutionError(
            "the child produced no result manifest, which usually means it was "
            "killed before it finished"
        )
    with open(path, "rb") as handle:
        raw = handle.read(protocol.MAX_MANIFEST_BYTES + 1)
    return protocol.parse_child_result(raw, scratch_dir=scratch_dir)


def describe_child_death(exit_code, signal_number, timed_out, *, wall_timeout,
                         limits):
    """Turn an abnormal child exit into a sentence a user can act on.

    A bare "killed by signal 9" tells a data scientist nothing. Each branch
    names the limit that fired and what to do next.
    """
    if timed_out:
        return (
            f"This node was stopped after {wall_timeout}s. It is still counted "
            "as a failure rather than a partial result. If the work genuinely "
            "needs longer, raise --exec-timeout; if it is stuck, look for an "
            "unbounded loop or a wait on something that never arrives."
        )
    if signal_number == SIGKILL:
        memory_mb = limits.get("memory_mb")
        return (
            "This node was killed by the operating system. The usual cause is "
            f"exceeding the memory limit of {memory_mb} MB. Try selecting fewer "
            "columns or filtering rows before returning, or raise "
            "--exec-memory-mb."
        )
    if signal_number == SIGXCPU:
        return (
            f"This node exceeded its CPU allowance of {limits.get('cpu_seconds')}s. "
            "Note this counts CPU time, not wall-clock, so a busy loop hits it "
            "quickly. Raise --exec-timeout if the work is genuinely this heavy."
        )
    if signal_number is not None:
        return f"This node was killed by signal {signal_number}."
    if exit_code == 3:
        return (
            "The sandbox could not confine this execution, so it refused to run "
            "the node rather than run it unprotected. Check the sandbox log for "
            "the failing step."
        )
    if exit_code not in (0, None):
        return (
            f"This node's process exited with status {exit_code} without "
            "reporting a result. If it called os._exit or crashed a C "
            "extension, that would do it."
        )
    return "This node's process ended without reporting a result."


def cleanup_scratch(scratch_dir):
    """Remove an execution's scratch directory, best effort.

    Never allowed to fail an execution: a leaked temporary directory is a
    housekeeping problem, while an exception here would turn a successful node
    into a failed one.
    """
    try:
        shutil.rmtree(scratch_dir, ignore_errors=True)
    except Exception:
        pass
