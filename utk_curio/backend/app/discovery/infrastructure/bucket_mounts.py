"""Bucket mounts: the mount service's control channel, and its self-test.

A deployment may run a mount service beside Curio
(``docker-compose.bucket-mounts.yml``): rclone's remote control daemon in a
container of its own, the only container that may mount with FUSE. It mounts
under its own :data:`SERVICE_MOUNTS`, a folder the host shares with Curio's
container, where each mount appears under the folder ``--bucket-mounts-dir``
names. The backend asks it to mount and unmount through rclone's rc API: one
HTTP POST of JSON per call, on the Unix socket ``--bucket-mount-socket``
names, in a folder only root may enter (:class:`RcClient`).

THE SELF-TEST (:func:`self_test`), which the backend runs once as it starts
(``application/bucket_mount_check.py``): mount the service's own test folder,
read-only and with ``allow_other``; read the file the service wrote there
back through ``--bucket-mounts-dir``, AS THE EXECUTION ACCOUNT, in a child
process with that account's ids; unmount it. FUSE without ``allow_other``
still lets uid 0 read, and the backend runs as root, like rclone: a read as
root would pass where node code's reads fail. The test reaches no network,
and it proves FUSE, the service's AppArmor profile, mount propagation,
``allow_other`` and the channel.

A SOURCE'S MOUNT is rclone's ``s3`` backend on a connection string
(:func:`s3_parameters`, :func:`connection_string`), mounted with
:data:`SOURCE_MOUNT_OPTIONS`; ``mount/listmounts`` names it by
:func:`listed_fs`. Which bucket a source mounts, and when, is
``application/bucket_mount_sources.py``'s.

Nothing here imports Curio or Flask: CI's ``bucket-mounts`` job loads this
file by its path in a plain Python container
(``scripts/bucket-mounts/ci_check.py``). ``socket.AF_UNIX``, ``pwd`` and
``os.geteuid`` are reached only when they are used, so the module imports on
Windows too.
"""

from __future__ import annotations

import base64
import errno
import hashlib
import http.client
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, Mapping, NamedTuple, Optional

#: The variables ``--bucket-mounts-dir`` and ``--bucket-mount-socket`` set
#: (``utk_curio/cli/environment.py``), and the one naming the account node
#: code runs as, which the launcher exports.
DIR_VARIABLE = "CURIO_BUCKET_MOUNTS_DIR"
SOCKET_VARIABLE = "CURIO_BUCKET_MOUNT_SOCKET"
EXEC_USER_VARIABLE = "CURIO_EXEC_USER"

#: The port of the backend's proxy, the mount service's one way out: its
#: ``HTTPS_PROXY`` in ``docker-compose.bucket-mounts.yml``
#: (``infrastructure/mount_proxy.py``).
PROXY_PORT = 3128

#: Where the service mounts, in its own container: the host folder it shares
#: with Curio's container (``docker-compose.bucket-mounts.yml``).
SERVICE_MOUNTS = "/mounts"
#: The service's test folder, and the file it writes there, holding this
#: line, as it starts (``scripts/bucket-mounts/service.sh``).
SELFTEST_FOLDER = "/selftest"
SELFTEST_FILE = "ok"
SELFTEST_LINE = "curio bucket mounts self-test"
#: Where the self-test mounts the test folder: under :data:`SERVICE_MOUNTS`
#: in the service, so under ``--bucket-mounts-dir`` here.
SELFTEST_MOUNT = ".selftest"
SELFTEST_MOUNT_POINT = f"{SERVICE_MOUNTS}/{SELFTEST_MOUNT}"
#: How the test folder is mounted: rclone's FUSE mount, read-only, with
#: ``allow_other`` so node code's account may read it, no cache, files 0444
#: and folders 0555. Flat parameters, by their rclone option names: rclone
#: answers a name it does not know with "unknown parameters", where one
#: inside ``mountOpt`` or ``vfsOpt`` would be dropped unread.
SELFTEST_MOUNT_OPTIONS = {
    "mountType": "mount",
    "allow_other": True,
    "read_only": True,
    "vfs_cache_mode": "off",
    "file_perms": "0444",
    "dir_perms": "0555",
}

#: Each call's deadline, in seconds.
CALL_TIMEOUT = 30
#: How long the self-test waits for the service to answer, since it may start
#: after the backend, asking again every :data:`SERVICE_RETRY_SECONDS`.
SERVICE_WAIT_SECONDS = 60
SERVICE_RETRY_SECONDS = 2
#: The deadline of the read as the execution account, in seconds.
READ_TIMEOUT = 30
#: The most of an answer, and of the test file, read.
MAX_ANSWER_BYTES = 1 << 20
MAX_READ_BYTES = 4096

#: Why the service is unavailable, as /monitor's Deployment says it: a closed
#: list of words, since that page is public. What went wrong, with paths and
#: rclone's answers, goes to the monitor's Recent errors.
PROBLEMS = {
    "no-service": "the mount service is not running, or its socket is not in this container",
    "no-answer": "the mount service did not answer in time",
    "mount-refused": "the mount service could not mount its test folder",
    "unmount-refused": "the mount service could not unmount its test folder",
    "not-propagated": "the test mount did not reach this container",
    "not-readable": "node code's account could not read the test mount",
    "wrong-file": "the test mount did not hold the test file",
    "error": "the self-test failed",
}


class RcError(Exception):
    """A call to the mount service that failed, its reason in plain words.

    ``kind`` says how: ``unreachable`` (no socket, or nothing answering on
    it), ``timeout`` (no answer by the deadline), ``refused`` (rclone answered
    with an error, whose words the reason carries) or ``malformed`` (an answer
    that is not rclone's JSON).
    """

    def __init__(self, kind: str, reason: str):
        super().__init__(reason)
        self.kind = kind
        self.reason = reason


class _UnixConnection(http.client.HTTPConnection):
    """An HTTP connection on a Unix socket, where rclone's rc server listens."""

    def __init__(self, path: str, timeout: float):
        super().__init__("localhost", timeout=timeout)
        self._path = path

    def connect(self) -> None:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        try:
            sock.connect(self._path)
        except Exception:
            sock.close()
            raise
        self.sock = sock


class RcClient:
    """rclone's rc API on the mount service's Unix socket: each call one POST
    of JSON to ``/<method>``, which rclone answers with JSON."""

    def __init__(self, socket_path, *, timeout: float = CALL_TIMEOUT):
        self.socket_path = str(socket_path)
        self.timeout = timeout

    def call(self, method: str, params: Optional[Mapping] = None, *,
             timeout: Optional[float] = None) -> dict:
        """Call *method* (``mount/mount``) with *params*; rclone's answer.

        Raises :class:`RcError` naming what went wrong.
        """
        deadline = self.timeout if timeout is None else timeout
        body = json.dumps(dict(params or {})).encode("utf-8")
        connection = _UnixConnection(self.socket_path, deadline)
        try:
            connection.request("POST", f"/{method}", body=body,
                               headers={"Content-Type": "application/json"})
            response = connection.getresponse()
            status = response.status
            raw = response.read(MAX_ANSWER_BYTES + 1)
        except TimeoutError:
            raise RcError("timeout", f"the mount service did not answer {method} within {deadline:g} s") from None
        except (FileNotFoundError, ConnectionRefusedError, PermissionError) as exc:
            raise RcError(
                "unreachable",
                f"nothing answers on the mount service's socket {self.socket_path}: {exc.strerror or exc}",
            ) from None
        except (OSError, http.client.HTTPException) as exc:
            raise RcError("unreachable", f"the call {method} to the mount service broke off: {exc}") from None
        finally:
            connection.close()
        return _answer(method, status, raw)


def _answer(method: str, status: int, raw: bytes) -> dict:
    """rclone's answer to *method*, or :class:`RcError` with its reason."""
    if len(raw) > MAX_ANSWER_BYTES:
        raise RcError("malformed", f"the mount service's answer to {method} is over {MAX_ANSWER_BYTES} bytes")
    try:
        answer = json.loads(raw.decode("utf-8")) if raw.strip() else {}
    except ValueError:
        raise RcError(
            "malformed", f"the mount service answered {method} with something other than JSON (HTTP {status})",
        ) from None
    if status != 200:
        error = answer.get("error") if isinstance(answer, dict) else None
        raise RcError("refused", f"the mount service refused {method}: {error or f'HTTP {status}'}")
    if not isinstance(answer, dict):
        raise RcError("malformed", f"the mount service answered {method} with JSON that is not an object")
    return answer


class Account(NamedTuple):
    """The account a read runs as: its name and ids."""

    name: str
    uid: int
    gid: int


class SelfTest(NamedTuple):
    """A self-test's outcome: passed, or a key of :data:`PROBLEMS`, and what
    happened, in words with paths that only the monitor's Recent errors shows."""

    passed: bool
    problem: Optional[str]
    detail: str


class SelfTestFailed(Exception):
    """A step of the self-test that failed: a key of :data:`PROBLEMS`, and
    what went wrong."""

    def __init__(self, problem: str, detail: str):
        super().__init__(detail)
        self.problem = problem
        self.detail = detail


def configured(environ: Optional[Mapping[str, str]] = None) -> Optional[tuple[Path, Path]]:
    """The folder the service's mounts appear in here, and its socket, when
    both variables are set; None when this deployment names no service."""
    environ = os.environ if environ is None else environ
    folder = (environ.get(DIR_VARIABLE) or "").strip()
    socket_path = (environ.get(SOCKET_VARIABLE) or "").strip()
    if not folder or not socket_path:
        return None
    return Path(folder), Path(socket_path)


def execution_account(environ: Optional[Mapping[str, str]] = None) -> Optional[Account]:
    """The account node code runs as, when this process may read as it: it is
    root, and ``CURIO_EXEC_USER`` names an account. None otherwise, and the
    self-test then reads as this process."""
    environ = os.environ if environ is None else environ
    name = (environ.get(EXEC_USER_VARIABLE) or "").strip()
    if not name or not hasattr(os, "geteuid") or os.geteuid() != 0:
        return None
    try:
        import pwd

        entry = pwd.getpwnam(name)
    except (ImportError, KeyError):
        return None
    return Account(name, entry.pw_uid, entry.pw_gid)


#: The problem a call that got no answer from rclone names, whatever it asked.
_CHANNEL_PROBLEMS = {"unreachable": "no-service", "timeout": "no-answer"}


def _call_failed(error: RcError, problem: str, doing: str) -> SelfTestFailed:
    return SelfTestFailed(_CHANNEL_PROBLEMS.get(error.kind, problem), f"{doing}: {error.reason}")


def mount_test_folder(client: RcClient) -> None:
    """Make the test mount's folder and mount the service's test folder
    there (:data:`SELFTEST_MOUNT_OPTIONS`). Raises :class:`SelfTestFailed`."""
    try:
        client.call("operations/mkdir", {"fs": SERVICE_MOUNTS, "remote": SELFTEST_MOUNT})
        client.call("mount/mount", {
            "fs": SELFTEST_FOLDER, "mountPoint": SELFTEST_MOUNT_POINT, **SELFTEST_MOUNT_OPTIONS,
        })
    except RcError as error:
        raise _call_failed(
            error, "mount-refused", f"mounting {SELFTEST_FOLDER} at {SELFTEST_MOUNT_POINT}",
        ) from None


def unmount_test_folder(client: RcClient, *, only_if_mounted: bool = False) -> bool:
    """Unmount the test folder; with *only_if_mounted*, only when the service
    lists the mount, as a self-test that stopped halfway leaves it. Whether
    it unmounted. Raises :class:`SelfTestFailed`."""
    try:
        if only_if_mounted:
            listed = client.call("mount/listmounts").get("mountPoints") or []
            if not any(isinstance(entry, dict) and entry.get("MountPoint") == SELFTEST_MOUNT_POINT
                       for entry in listed):
                return False
        client.call("mount/unmount", {"mountPoint": SELFTEST_MOUNT_POINT})
    except RcError as error:
        raise _call_failed(error, "unmount-refused", f"unmounting {SELFTEST_MOUNT_POINT}") from None
    return True


def _unmount_quietly(client: RcClient) -> None:
    """Unmount the test folder after a later step failed, whose failure is
    the one the self-test reports."""
    try:
        client.call("mount/unmount", {"mountPoint": SELFTEST_MOUNT_POINT})
    except RcError:
        # The step that failed is what the self-test reports; the next
        # self-test unmounts what this one leaves (unmount_test_folder).
        return


#: What the child that reads as the execution account runs: the file's first
#: bytes to its output, or 100 plus the errno that stopped it as its exit code.
_READ_CODE = (
    "import sys\n"
    "try:d=open(sys.argv[1],'rb').read(4096)\n"
    "except OSError as e:sys.exit(100+(e.errno or 0))\n"
    "sys.stdout.buffer.write(d)\n"
)
_ERRNO_EXIT = 100


def read_test_file(path, account: Optional[Account]) -> str:
    """The test file's text, read as *account*, in a child process with its
    ids; by this process when *account* is None. Raises :class:`SelfTestFailed`."""
    if account is None:
        try:
            with open(path, "rb") as handle:
                data = handle.read(MAX_READ_BYTES)
        except OSError as exc:
            raise _read_failed(path, account, exc.errno or 0) from None
        return data.decode("utf-8", "replace")
    return _read_in_child(path, account)


def _read_in_child(path, account: Optional[Account]) -> str:
    """Read *path* in a child of this Python: as *account* when given (its
    uid, its gid and no other group), with no environment, from ``/``."""
    ids = {} if account is None else {"user": account.uid, "group": account.gid, "extra_groups": []}
    try:
        done = subprocess.run(
            [sys.executable, "-I", "-S", "-c", _READ_CODE, str(path)],
            stdin=subprocess.DEVNULL, capture_output=True, env={}, cwd="/",
            timeout=READ_TIMEOUT, check=False, **ids,
        )
    except subprocess.TimeoutExpired:
        raise SelfTestFailed("no-answer", f"reading {path} as {_who(account)} took over {READ_TIMEOUT} s") from None
    except (OSError, subprocess.SubprocessError) as exc:
        raise SelfTestFailed("error", f"could not start a read of {path} as {_who(account)}: {exc}") from None
    if done.returncode == 0:
        return done.stdout[:MAX_READ_BYTES].decode("utf-8", "replace")
    if done.returncode >= _ERRNO_EXIT:
        raise _read_failed(path, account, done.returncode - _ERRNO_EXIT)
    stderr = done.stderr.decode("utf-8", "replace").strip()[-500:]
    raise SelfTestFailed(
        "error", f"the read of {path} as {_who(account)} ended with code {done.returncode}: {stderr}",
    )


def _read_failed(path, account: Optional[Account], number: int) -> SelfTestFailed:
    """A read that the system refused with errno *number*: the mount is not
    here when the file is not, and otherwise it is not readable."""
    problem = "not-propagated" if number in (errno.ENOENT, errno.ENOTDIR) else "not-readable"
    words = os.strerror(number) if number else "an unknown error"
    return SelfTestFailed(problem, f"reading {path} as {_who(account)}: {words} (errno {number})")


def _who(account: Optional[Account]) -> str:
    if account is not None:
        return f"{account.name} (uid {account.uid})"
    if hasattr(os, "geteuid"):
        return f"this process (uid {os.geteuid()})"
    return "this process"


def _wait_for_service(client: RcClient, wait_seconds: float,
                      sleep: Callable[[float], None], clock: Callable[[], float]) -> None:
    """Ask the service ``rc/noop`` until it answers, for up to *wait_seconds*."""
    deadline = clock() + wait_seconds
    while True:
        try:
            client.call("rc/noop")
            return
        except RcError as error:
            if error.kind not in _CHANNEL_PROBLEMS or clock() >= deadline:
                raise _call_failed(error, "error", "asking the mount service rc/noop") from None
        sleep(SERVICE_RETRY_SECONDS)


def self_test(client: RcClient, mounts_dir, *, account: Optional[Account] = None,
              wait_seconds: float = SERVICE_WAIT_SECONDS,
              read: Optional[Callable[[Path, Optional[Account]], str]] = None,
              sleep: Callable[[float], None] = time.sleep,
              clock: Callable[[], float] = time.monotonic) -> SelfTest:
    """Mount the service's test folder, read its file through *mounts_dir*
    as *account* (as this process when None), and unmount it.

    Waits up to *wait_seconds* for the service to answer first, and
    unmounts a test mount a self-test that stopped halfway left. A step that
    fails still unmounts what was mounted. Never raises.
    """
    path = Path(mounts_dir) / SELFTEST_MOUNT / SELFTEST_FILE
    reader = read or read_test_file
    try:
        _wait_for_service(client, wait_seconds, sleep, clock)
        unmount_test_folder(client, only_if_mounted=True)
        mount_test_folder(client)
        try:
            text = reader(path, account)
            if text.strip() != SELFTEST_LINE:
                raise SelfTestFailed(
                    "wrong-file",
                    f"{path}, read as {_who(account)}, holds {text[:80]!r}, not {SELFTEST_LINE!r}",
                )
        except Exception:
            _unmount_quietly(client)
            raise
        unmount_test_folder(client)
    except SelfTestFailed as failed:
        return SelfTest(False, failed.problem, failed.detail)
    except Exception as exc:  # noqa: BLE001 - the self-test reports a failure, it never raises
        return SelfTest(False, "error", f"the self-test raised {type(exc).__name__}: {exc}")
    return SelfTest(
        True, None,
        f"mounted {SELFTEST_FOLDER} at {SELFTEST_MOUNT_POINT}, read {path} as {_who(account)}, unmounted it",
    )


def self_test_from_env(environ: Optional[Mapping[str, str]] = None, *,
                       wait_seconds: float = SERVICE_WAIT_SECONDS) -> Optional[SelfTest]:
    """The self-test of the service the environment names, reading as the
    execution account (:func:`execution_account`); None when it names none."""
    environ = os.environ if environ is None else environ
    named = configured(environ)
    if named is None:
        return None
    folder, socket_path = named
    return self_test(RcClient(socket_path), folder, account=execution_account(environ),
                     wait_seconds=wait_seconds)


# ── A source's mount ─────────────────────────────────────────────────────────

#: How a source's bucket is mounted: as the test folder is (read-only, with
#: ``allow_other``, no cache, files 0444 and folders 0555), and with each
#: folder's listing kept 5 minutes, so a folder read again soon asks the
#: bucket nothing. Flat parameters, as :data:`SELFTEST_MOUNT_OPTIONS` says why.
SOURCE_MOUNT_OPTIONS = {**SELFTEST_MOUNT_OPTIONS, "dir_cache_time": "5m"}

#: What rclone's connection-string syntax ends or opens a value at, so a value
#: holding one is quoted.
_SPECIAL = frozenset(",:'\"=")


def s3_parameters(endpoint: str, *, path_style: bool) -> dict[str, str]:
    """The parameters of rclone's ``s3`` backend for a public bucket at
    *endpoint*: anonymous (``env_auth=false`` and no keys), the bucket in the
    URL's path or, without *path_style*, in its host; listed with
    ListObjectsV2, as Discovery's S3 provider lists, where rclone's provider
    ``Other`` would use V1; each file read with a GET alone, no HEAD first."""
    return {
        "provider": "Other",
        "endpoint": endpoint,
        "env_auth": "false",
        "no_head_object": "true",
        "force_path_style": "true" if path_style else "false",
        "list_version": "2",
    }


def remote_path(bucket: str, folder: str = "") -> str:
    """``<bucket>`` or ``<bucket>/<folder>``: what a remote's root names."""
    return f"{bucket}/{folder}" if folder else bucket


def connection_string(backend: str, parameters: Mapping[str, str], path: str) -> str:
    """``:<backend>,<name>=<value>,...:<path>``, rclone's connection string of
    a remote made on the fly. A value holding ``,``, ``:``, a quote or ``=``
    goes in single quotes, each single quote in it doubled, as rclone's
    syntax asks."""
    pairs = ",".join(f"{name}={_quoted(str(value))}" for name, value in parameters.items())
    return f":{backend},{pairs}:{path}"


def _quoted(value: str) -> str:
    if not _SPECIAL.intersection(value):
        return value
    return "'" + value.replace("'", "''") + "'"


def listed_fs(backend: str, parameters: Mapping[str, str], path: str) -> str:
    """What ``mount/listmounts`` names a mount of that remote by.

    rclone answers with ``fs.ConfigString``: the remote's name, which for a
    remote with parameters is ``:<backend>`` and a suffix, then ``:`` and its
    root. The suffix is ``{`` the first five characters of the unpadded
    URL-safe base64 of the MD5 of the parameters as rclone writes them back
    ``}``: sorted by name, ``name='value'`` each, with each single quote
    doubled, joined by commas (``configmap.Simple.String``). It grows longer
    only when two remotes' suffixes collide in one service. The root is the
    path without its outer slashes. CI's ``bucket-mounts`` job checks this
    against the service it runs (``scripts/bucket-mounts/ci_check.py``).
    """
    written = ",".join(
        "{}='{}'".format(name, str(value).replace("'", "''")) for name, value in sorted(parameters.items())
    )
    digest = hashlib.md5(written.encode("utf-8"), usedforsecurity=False).digest()
    suffix = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")[:5]
    return f":{backend}{{{suffix}}}:{path.strip('/')}"
