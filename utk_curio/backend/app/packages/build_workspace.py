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
  (PATH=/usr/bin:/bin, HOME/TMPDIR inside the workspace, locale pins, and the
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
    if not _IS_POSIX:
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


def _minimal_env(workspace: BuildWorkspace, extra_env: Mapping[str, str] | None) -> dict[str, str]:
    env = {
        "PATH": "/usr/bin:/bin",
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


def _apply_rlimits(limits: WorkerLimits) -> tuple[list[str], object]:
    """Build the child-side rlimit applier. Returns ``(applied_names, preexec)``.

    Address space and process-count limits are Linux-only: macOS ignores
    RLIMIT_AS in practice and counts RLIMIT_NPROC per-user, which would make
    a low bound kill unrelated processes' forks. What actually applied is
    recorded on the result — never silently assumed.
    """
    if not _IS_POSIX:
        return [], None
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


def _kill_group(proc: subprocess.Popen) -> None:
    try:
        if _IS_POSIX:
            os.killpg(proc.pid, signal.SIGKILL)
        else:
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
        preexec_fn=preexec,  # noqa: PLW1509 — bounded, exec follows immediately
        close_fds=True,
    )
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
            _kill_group(proc)
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
