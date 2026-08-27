"""Restricted ephemeral build workspaces + the bounded worker runner (memo dev/89 §3.3).

Every build gets a fresh workspace in the SYSTEM temp tree — never the
repository, never the user package store, never the launch directory — with
four separated directories::

    <root>/input/    # request files, made read-only after population
    <root>/cache/    # dependency cache mount (writable; per-build in v1)
    <root>/work/     # the worker's cwd, HOME, and TMPDIR
    <root>/output/   # what the worker hands back (collected with caps)

Isolation posture (dev/89 §3.3):

* **Scrubbed environment** — a worker sees ONLY the minimal env built here
  (a minimal system PATH, HOME/TMPDIR inside the workspace, locale pins, and the
  three ``CURIO_BUILD_*_DIR`` pointers) plus the caller's explicit
  ``extra_env``. The host environment — credentials, tokens, package-manager
  configuration — never reaches the child.
* **Read-only inputs** — after :func:`populate_inputs` the input tree is
  chmod-locked; the worker can only write under ``work/`` and ``output/``.
* **Bounded execution** — POSIX rlimits (CPU seconds, file size, open files;
  address space and process count where the platform honors them), a wall
  clock deadline, and a captured-output byte cap. Exceeding any bound kills
  the worker's WHOLE process group; cancellation does the same.
* **Sanitized diagnostics** — :func:`sanitize_diagnostic` strips workspace
  and host paths from anything that leaves this module; job events and tool
  results carry placeholders, never host paths (dev/89 §3.9).

What this module does NOT do: OS-level network isolation. Networklessness of
the compile/preview phases is enforced by the phase tooling itself (the
dev/89 commit 4 resolver fetches into ``cache/``; the commit 5 compiler runs
offline against it) — a plain subprocess cannot be network-namespaced
portably on macOS, so the boundary is per-phase policy, stated honestly.
"""

from __future__ import annotations

import logging
import os
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

log = logging.getLogger(__name__)

_IS_POSIX = os.name == "posix"

# Captured-diagnostic bounds: enough to debug a build, small enough to store
# on the job record and show in a review card.
DIAGNOSTIC_TAIL_CHARS = 4_000

# collect_outputs caps — outputs are compiled bundles + reports, not datasets.
MAX_OUTPUT_FILES = 64
MAX_OUTPUT_TOTAL_BYTES = 64 * 1024 * 1024


class WorkspaceError(ValueError):
    """Raised on workspace misuse: bad inputs, unsafe outputs, missing dirs."""


@dataclass(frozen=True)
class WorkerLimits:
    """Resource bounds for one worker process (dev/89 §3.3)."""

    wall_time_seconds: float = 120.0
    cpu_seconds: int = 60
    memory_bytes: int = 1024 * 1024 * 1024
    max_processes: int = 32
    max_open_files: int = 256
    max_file_bytes: int = 64 * 1024 * 1024  # RLIMIT_FSIZE — biggest file a worker may write
    max_output_bytes: int = 2 * 1024 * 1024  # captured stdout+stderr cap


#: Per-request timeout classes (build_models.timeout_class → limits).
LIMITS_BY_TIMEOUT_CLASS: dict[str, WorkerLimits] = {
    "quick": WorkerLimits(wall_time_seconds=30.0, cpu_seconds=15),
    "standard": WorkerLimits(),
}


@dataclass(frozen=True)
class BuildWorkspace:
    root: Path
    input_dir: Path
    cache_dir: Path
    work_dir: Path
    output_dir: Path


@dataclass(frozen=True)
class WorkerResult:
    """One worker run's outcome. ``status`` is one of ``ok`` (exit 0),
    ``failed`` (nonzero exit), ``timeout``, ``cancelled``, ``output-limit``.
    Tails are already sanitized — safe to store and show."""

    status: str
    exit_code: int | None
    stdout_tail: str
    stderr_tail: str
    duration_seconds: float
    limits_applied: tuple[str, ...] = field(default=())


def create_workspace(build_id: str) -> BuildWorkspace:
    """Allocate a fresh four-directory workspace in the system temp tree.

    *build_id* only flavors the directory prefix for operator forensics —
    the path itself stays unpredictable (``mkdtemp``) and is never returned
    to the model or UI.
    """
    prefix = f"curio-pkgbuild-{(build_id or 'anon')[:12]}-"
    root = Path(tempfile.mkdtemp(prefix=prefix))
    ws = BuildWorkspace(
        root=root,
        input_dir=root / "input",
        cache_dir=root / "cache",
        work_dir=root / "work",
        output_dir=root / "output",
    )
    for d in (ws.input_dir, ws.cache_dir, ws.work_dir, ws.output_dir):
        d.mkdir(parents=True)
    return ws


def populate_inputs(workspace: BuildWorkspace, files: Mapping[str, bytes]) -> None:
    """Write the request's files under ``input/`` and lock the tree read-only.

    Paths have already passed the build-model's installer-rule validation;
    this re-checks containment as defence in depth and refuses to run twice
    (inputs are immutable once populated — dev/89 §3.1).
    """
    if not workspace.input_dir.is_dir():
        raise WorkspaceError("workspace has no input directory (already destroyed?)")
    if any(workspace.input_dir.iterdir()):
        raise WorkspaceError("workspace inputs are already populated and immutable")
    base = workspace.input_dir.resolve()
    for rel, body in files.items():
        dest = (base / rel).resolve()
        if not str(dest).startswith(str(base) + os.sep):
            raise WorkspaceError(f"input path {rel!r} escapes the workspace input dir")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(body)
    _chmod_tree(workspace.input_dir, file_mode=0o444, dir_mode=0o555)


def _chmod_tree(root: Path, *, file_mode: int, dir_mode: int) -> None:
    """Apply a mode across a tree, deepest entry first.

    On Windows this used to return immediately, which quietly made
    :func:`populate_inputs` a no-op: the input tree was documented as
    "chmod-locked" and was in fact fully writable, so a worker could rewrite
    its own inputs mid-build and the tamper test passed with ``status == ok``.

    Windows has no mode bits, but it does honour the read-only *attribute*, and
    it honours it against the owning process - ``open(path, "a")`` on a
    read-only file raises ``PermissionError``. That is exactly the guarantee
    this function exists to provide, so derive the attribute from the POSIX
    owner-write bit and set it. Directories are left alone: the attribute is
    meaningless for containment on a directory (Windows ignores it for
    creation), and the files are what carry the content.
    """
    if not _IS_POSIX:
        # `stat.S_IWRITE` clears the attribute, `stat.S_IREAD` sets it.
        writable = bool(file_mode & 0o200)
        win_mode = (stat.S_IWRITE | stat.S_IREAD) if writable else stat.S_IREAD
        for entry in sorted(root.rglob("*"), reverse=True):
            if not entry.is_file():
                continue
            try:
                os.chmod(entry, win_mode)
            except OSError:
                pass
        return
    for entry in sorted(root.rglob("*"), reverse=True):
        try:
            entry.chmod(file_mode if entry.is_file() else dir_mode)
        except OSError:
            pass
    try:
        root.chmod(dir_mode)
    except OSError:
        pass


class BuildIsolationUnavailable(RuntimeError):
    """A build was requested on a platform that cannot bound it.

    Raised for a hosted deployment. A local single-user launch degrades with a
    warning instead, mirroring ``sandbox.isolation.mode``.
    """


def isolation_capabilities(platform=None, module_probe=None) -> dict[str, object]:
    """Report which build-isolation primitives this interpreter actually has.

    *platform* and *module_probe* are injectable for the same reason
    ``sandbox.isolation.mode.capabilities`` makes them injectable: the whole
    decision table is then exercisable from any host, including the Windows
    branch that a Linux CI can never reach and the POSIX branch a Windows
    developer can never reach.
    """
    platform = platform if platform is not None else sys.platform
    if module_probe is None:
        def module_probe(name):
            try:
                __import__(name)
                return True
            except Exception:
                return False

    posix = not platform.startswith("win")
    # Windows gets its bounds from Job Objects rather than setrlimit: memory,
    # CPU time and process count through the job, plus tree-kill via
    # TerminateJobObject. `ctypes` is stdlib, so the only way this is absent is
    # a build of Python without it.
    win_job = (not posix) and bool(module_probe("ctypes"))
    return {
        "platform": platform,
        # POSIX: setrlimit. Windows: a Job Object. Neither covers everything -
        # POSIX has no memory bound on macOS, Windows has no file-size or
        # open-file bound - so `limits_applied` on the result is the record of
        # what a given run actually got.
        "rlimit": (bool(module_probe("resource")) and posix) or win_job,
        # POSIX mode bits; on Windows the read-only file attribute, which the
        # OS does enforce against the owning process.
        "read_only_inputs": True,
        # POSIX: setsid + killpg. Windows: TerminateJobObject, which is
        # stronger - it reaches processes started after the job was assigned.
        "process_group_kill": posix or win_job,
    }


def missing_isolation(caps: Mapping[str, object]) -> list[str]:
    """Which bounds are needed but absent, most consequential first."""
    missing = []
    if not caps.get("rlimit"):
        missing.append("resource limits (CPU, memory, file size, open files)")
    if not caps.get("process_group_kill"):
        missing.append("process-group kill on timeout or cancel")
    if not caps.get("read_only_inputs"):
        missing.append("read-only build inputs")
    return missing


def check_build_isolation(*, hosted: bool, caps: Mapping[str, object] | None = None):
    """Gate a build on this platform's ability to bound it.

    Returns ``(missing, warning)``. Raises :class:`BuildIsolationUnavailable`
    when *hosted* and anything is missing.

    Why this exists: the worker runs code an **agent** authored, and
    ``limits_applied`` was only ever *recorded* into provenance - never gated
    on. So on Windows a build ran with no CPU, memory, file-size or open-file
    ceiling, with inputs that were not really read-only, and with no way to
    kill a runaway process group, and nothing in the pipeline noticed. On a
    shared instance that is the failure this whole module exists to prevent,
    and it would be invisible: every build would appear to work.

    The local-vs-hosted split is deliberate and matches
    ``sandbox.isolation.mode``: on a single-user laptop the author and the
    operator are the same person, so refusing to build would be the wrong
    trade; on a hosted instance they are not.
    """
    caps = caps if caps is not None else isolation_capabilities()
    missing = missing_isolation(caps)
    if not missing:
        return [], None
    if hosted:
        raise BuildIsolationUnavailable(
            "Package building was requested on an instance with user auth "
            "enabled, but this platform cannot bound a build: missing "
            + ", ".join(missing)
            + ". Refusing to run an agent-authored build unbounded. Run the "
            "Docker image, or build on a POSIX host."
        )
    return missing, (
        "This platform cannot bound a package build ("
        + ", ".join(missing)
        + "). The build will run anyway because this is a single-user launch, "
        "where the package author and the operator are the same person. Do not "
        "expose this instance to other users without --auth."
    )


def system_path_env() -> dict[str, str]:
    """The PATH (and, on Windows, the variables the loader needs) for a build
    child that must NOT inherit the parent environment.

    The point of a minimal env is that a build step sees nothing it was not
    given. ``PATH=/usr/bin:/bin`` expressed that on POSIX and was hardcoded at
    three call sites, which made every one of them a no-op-or-worse on Windows:
    the path does not exist, and a bare ``env`` without ``SystemRoot`` leaves
    the Windows loader unable to initialise, so a child fails before it runs.

    Returns only the variables needed to start a process, never the caller's.
    """
    if os.name == "nt":
        root = os.environ.get("SystemRoot") or r"C:\Windows"
        system32 = os.path.join(root, "System32")
        return {
            "PATH": os.pathsep.join([system32, root]),
            # Both are required for process startup on Windows; without
            # SystemRoot even a fully-qualified executable can fail to load.
            "SystemRoot": root,
            "SystemDrive": os.environ.get("SystemDrive") or "C:",
        }
    return {"PATH": "/usr/bin:/bin"}


def _minimal_env(workspace: BuildWorkspace, extra_env: Mapping[str, str] | None) -> dict[str, str]:
    env = {
        **system_path_env(),
        "HOME": str(workspace.work_dir),
        "TMPDIR": str(workspace.work_dir),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "CURIO_BUILD_INPUT_DIR": str(workspace.input_dir),
        "CURIO_BUILD_CACHE_DIR": str(workspace.cache_dir),
        "CURIO_BUILD_OUTPUT_DIR": str(workspace.output_dir),
    }
    for key, value in (extra_env or {}).items():
        if not isinstance(key, str) or not key or not isinstance(value, str):
            raise WorkspaceError(f"extra_env entries must be non-empty str: str, got {key!r}")
        env[key] = value
    return env


# ── Windows bounds: Job Objects ─────────────────────────────────────────────
#
# Windows has no setrlimit, which is why the whole bounded-worker contract used
# to evaporate there. It does have Job Objects, which bound a process tree
# rather than a process - and for this purpose that is strictly better than
# rlimits, because a build's grandchildren are inside the same bound and
# `TerminateJobObject` takes the entire tree down in one call.
#
# Mapped here:
#   memory_bytes   -> ProcessMemoryLimit        (per process in the job)
#   cpu_seconds    -> PerJobUserTimeLimit       (100ns units, whole job)
#   max_processes  -> ActiveProcessLimit
# plus KILL_ON_JOB_CLOSE, so if this backend dies the job dies with it instead
# of leaving an orphaned build running.
#
# Not mapped: file size and open-file count have no Job Object equivalent.
# `_apply_rlimits` reports exactly what it applied, so provenance stays honest
# about the difference rather than implying parity.

_JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x00000100
_JOB_OBJECT_LIMIT_JOB_TIME = 0x00000004
_JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x00000008
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9


def _win_job_structs():
    """Build the ctypes structs lazily so importing this module stays portable."""
    import ctypes
    from ctypes import wintypes

    class _IoCounters(ctypes.Structure):
        _fields_ = [(n, ctypes.c_ulonglong) for n in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class _BasicLimits(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _ExtendedLimits(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _BasicLimits),
            ("IoInfo", _IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    return ctypes, _ExtendedLimits


def _create_win_job(limits: WorkerLimits) -> tuple[list[str], object | None]:
    """Create a bounded Job Object. Returns ``(applied_names, handle)``.

    ``handle`` is None when the job could not be created or configured, in
    which case *nothing* was applied and the caller reports that honestly.
    """
    try:
        ctypes, ExtendedLimits = _win_job_structs()
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            return [], None

        info = ExtendedLimits()
        basic = info.BasicLimitInformation
        flags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        applied: list[str] = ["kill-on-close"]

        if limits.memory_bytes > 0:
            info.ProcessMemoryLimit = int(limits.memory_bytes)
            flags |= _JOB_OBJECT_LIMIT_PROCESS_MEMORY
            applied.append("as")
        if limits.cpu_seconds > 0:
            # PerJobUserTimeLimit counts in 100-nanosecond units.
            basic.PerJobUserTimeLimit = int(limits.cpu_seconds) * 10_000_000
            flags |= _JOB_OBJECT_LIMIT_JOB_TIME
            applied.append("cpu")
        if limits.max_processes > 0:
            basic.ActiveProcessLimit = int(limits.max_processes)
            flags |= _JOB_OBJECT_LIMIT_ACTIVE_PROCESS
            applied.append("nproc")

        basic.LimitFlags = flags
        info.BasicLimitInformation = basic
        ok = kernel32.SetInformationJobObject(
            handle, _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(info), ctypes.sizeof(info),
        )
        if not ok:
            kernel32.CloseHandle(handle)
            return [], None
        return applied, handle
    except Exception:  # ctypes/DLL surprises must never break a build path
        log.warning("could not create a Windows Job Object for build bounds",
                    exc_info=True)
        return [], None


def _assign_to_win_job(handle: object, pid: int) -> bool:
    """Put a started process (and everything it spawns) inside the job."""
    try:
        import ctypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        # PROCESS_SET_QUOTA | PROCESS_TERMINATE
        proc = kernel32.OpenProcess(0x0100 | 0x0001, False, int(pid))
        if not proc:
            return False
        try:
            return bool(kernel32.AssignProcessToJobObject(handle, proc))
        finally:
            kernel32.CloseHandle(proc)
    except Exception:
        return False


def _apply_rlimits(limits: WorkerLimits) -> tuple[list[str], object]:
    """Build the child-side rlimit applier. Returns ``(applied_names, preexec)``.

    On POSIX the second element is a ``preexec_fn``. On Windows it is a Job
    Object handle instead, which the caller assigns the started process to -
    there is no pre-exec hook, and a job bounds the whole process tree rather
    than one process.

    Address space and process-count limits are Linux-only *on POSIX*: macOS
    ignores RLIMIT_AS in practice and counts RLIMIT_NPROC per-user, which would
    make a low bound kill unrelated processes' forks. Windows gets both through
    the job, and loses file-size and open-file bounds, which have no Job Object
    equivalent. What actually applied is recorded on the result - never
    silently assumed, and never claimed to be parity.
    """
    if not _IS_POSIX:
        return _create_win_job(limits)
    import resource

    plan: list[tuple[str, int, int]] = [
        ("cpu", resource.RLIMIT_CPU, limits.cpu_seconds),
        ("fsize", resource.RLIMIT_FSIZE, limits.max_file_bytes),
        ("nofile", resource.RLIMIT_NOFILE, limits.max_open_files),
    ]
    if sys.platform.startswith("linux"):
        plan.append(("as", resource.RLIMIT_AS, limits.memory_bytes))
        plan.append(("nproc", resource.RLIMIT_NPROC, limits.max_processes))

    def _preexec() -> None:  # runs in the child, pre-exec
        for _, key, value in plan:
            try:
                resource.setrlimit(key, (value, value))
            except (ValueError, OSError):
                pass

    return [name for name, _, _ in plan], _preexec


class _PipeReader(threading.Thread):
    """Drain one pipe into a capped buffer; flags when the cap is crossed."""

    def __init__(self, pipe, cap: int, exceeded: threading.Event):
        super().__init__(daemon=True)
        self._pipe = pipe
        self._cap = cap
        self._exceeded = exceeded
        self.data = bytearray()

    def run(self) -> None:
        try:
            while True:
                chunk = self._pipe.read(8192)
                if not chunk:
                    return
                if len(self.data) < self._cap:
                    self.data.extend(chunk[: self._cap - len(self.data)])
                if len(self.data) >= self._cap:
                    self._exceeded.set()
        except (OSError, ValueError):
            return


def _kill_group(proc: subprocess.Popen, win_job: object | None = None) -> None:
    """Kill the worker and everything it spawned.

    ``proc.kill()`` alone leaves a runaway grandchild alive on Windows, which is
    the whole reason the POSIX side uses ``killpg``. ``TerminateJobObject``
    is the equivalent: every process in the job dies, including ones started
    after the job was assigned.
    """
    try:
        if _IS_POSIX:
            os.killpg(proc.pid, signal.SIGKILL)
            return
        if win_job is not None:
            try:
                import ctypes
                kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
                if kernel32.TerminateJobObject(win_job, 1):
                    return
            except Exception:
                pass
        proc.kill()
    except (ProcessLookupError, PermissionError, OSError):
        pass


def run_worker(
    workspace: BuildWorkspace,
    argv: list[str],
    *,
    limits: WorkerLimits,
    cancel: threading.Event | None = None,
    extra_env: Mapping[str, str] | None = None,
) -> WorkerResult:
    """Run one bounded worker process inside *workspace*.

    The child runs in its own session/process group with the scrubbed
    environment and rlimits above; the parent enforces the wall clock, the
    captured-output cap, and cancellation, killing the whole group on any of
    them. Never raises for a worker failure — the result IS the diagnosis.
    """
    if not argv or not all(isinstance(a, str) and a for a in argv):
        raise WorkspaceError("argv must be a non-empty list of strings")
    applied, preexec = _apply_rlimits(limits)
    started = time.monotonic()
    proc = subprocess.Popen(
        argv,
        cwd=str(workspace.work_dir),
        env=_minimal_env(workspace, extra_env),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=_IS_POSIX,
        preexec_fn=preexec if _IS_POSIX else None,  # noqa: PLW1509 — exec follows
        close_fds=True,
        # A new process group is what lets the whole tree be killed on Windows,
        # the same role start_new_session plays on POSIX.
        creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP if not _IS_POSIX else 0),
    )
    win_job = None if _IS_POSIX else preexec
    if win_job is not None and not _assign_to_win_job(win_job, proc.pid):
        # The bounds did not take, so do not report them as applied. The job is
        # closed in the finally below; KILL_ON_JOB_CLOSE only affects members.
        applied = []
    output_exceeded = threading.Event()
    # stdout+stderr share the cap (half each) so total capture stays bounded.
    out_reader = _PipeReader(proc.stdout, max(1, limits.max_output_bytes // 2), output_exceeded)
    err_reader = _PipeReader(proc.stderr, max(1, limits.max_output_bytes // 2), output_exceeded)
    out_reader.start()
    err_reader.start()

    deadline = started + limits.wall_time_seconds
    status: str | None = None
    while proc.poll() is None:
        if cancel is not None and cancel.is_set():
            status = "cancelled"
        elif time.monotonic() >= deadline:
            status = "timeout"
        elif output_exceeded.is_set():
            status = "output-limit"
        if status is not None:
            _kill_group(proc, win_job)
            break
        time.sleep(0.02)
    proc.wait()
    out_reader.join(timeout=2)
    err_reader.join(timeout=2)
    duration = time.monotonic() - started
    if status is None:
        status = "ok" if proc.returncode == 0 else "failed"

    def _tail(data: bytearray) -> str:
        text = bytes(data).decode("utf-8", errors="replace")
        if len(text) > DIAGNOSTIC_TAIL_CHARS:
            text = "…" + text[-DIAGNOSTIC_TAIL_CHARS:]
        return sanitize_diagnostic(text, workspace=workspace)

    if win_job is not None:
        # KILL_ON_JOB_CLOSE means this also reaps anything still running, so a
        # build can never leak a process past its own result.
        try:
            import ctypes
            ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle(win_job)
        except Exception:
            pass

    return WorkerResult(
        status=status,
        exit_code=proc.returncode,
        stdout_tail=_tail(out_reader.data),
        stderr_tail=_tail(err_reader.data),
        duration_seconds=duration,
        limits_applied=tuple(applied),
    )


def collect_outputs(
    workspace: BuildWorkspace,
    *,
    max_files: int = MAX_OUTPUT_FILES,
    max_total_bytes: int = MAX_OUTPUT_TOTAL_BYTES,
) -> dict[str, bytes]:
    """Read everything the worker left under ``output/``, bounded and safe.

    Symlinks are refused outright (dev/89 §3.6 archive rules — a link could
    smuggle bytes from outside the workspace into the artifact), as are
    file-count and total-size overruns.
    """
    base = workspace.output_dir
    if not base.is_dir():
        raise WorkspaceError("workspace has no output directory (already destroyed?)")
    out: dict[str, bytes] = {}
    total = 0
    for entry in sorted(base.rglob("*")):
        if entry.is_symlink():
            raise WorkspaceError(
                f"worker output contains a symlink ({entry.name!r}) — refused"
            )
        if not entry.is_file():
            continue
        if len(out) >= max_files:
            raise WorkspaceError(f"worker output exceeds the {max_files}-file limit")
        data = entry.read_bytes()
        total += len(data)
        if total > max_total_bytes:
            raise WorkspaceError("worker output exceeds the total size limit")
        out[entry.relative_to(base).as_posix()] = data
    return out


def destroy_workspace(workspace: BuildWorkspace) -> None:
    """Remove the whole workspace tree (read-only inputs included).

    Best-effort and idempotent — a build's cleanup can never mask its
    outcome. Only sanitized logs and content-addressed outputs survive a
    build (dev/89 §3.3); the tree itself never does.
    """
    if not workspace.root.exists():
        return
    _chmod_tree(workspace.root, file_mode=0o644, dir_mode=0o755)

    def _onerror(_func, path, _exc):
        try:
            os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
            os.unlink(path)
        except OSError:
            pass

    shutil.rmtree(workspace.root, onerror=_onerror)


def sanitize_diagnostic(text: str, *, workspace: BuildWorkspace | None = None) -> str:
    """Strip host paths from diagnostic text (dev/89 §3.9: never return host
    paths, environment values, or tokens to the model or UI)."""
    if not text:
        return text
    replacements: list[tuple[str, str]] = []
    if workspace is not None:
        replacements.append((str(workspace.root), "<workspace>"))
    launch = os.environ.get("CURIO_LAUNCH_CWD")
    if launch:
        replacements.append((launch, "<curio>"))
    home = os.path.expanduser("~")
    if home and home != "/":
        replacements.append((home, "<home>"))
    for needle, placeholder in replacements:
        text = text.replace(needle, placeholder)
    return text
