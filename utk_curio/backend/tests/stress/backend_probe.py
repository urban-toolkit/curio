"""The backend's threads and memory, and its dataflows' doc files, read where it runs.

The stress harness runs this file's own source with ``python -c``, through the
command its ``--probe`` names: ``docker exec <container> python`` in CI, where
the stack's ``.curio`` is its root's alone (the execution user hardens it), or
this machine's Python for a stack started here. So the script imports only the
standard library and psutil, which the backend itself requires, and prints one
JSON object:

* ``pid``, ``threads`` and ``rss_bytes``: the backend's process, the one that
  serves ``-m backend.server`` (``cli/services.py``), the reloader's child
  when there is one;
* ``docs``, for each dataflow id it is given: the segments of each of its
  docs' logs, ``ydoc/<doc id>/<day>.bin`` and ``<day>.updates``
  (``collaboration/dataflow_docs.py``), with their sizes, under the backend's
  state root (``common/user_storage.curio_root``);
* or ``error``, saying why it read nothing.

The rest of the file is the harness's side: :class:`BackendProbe` runs the
script, and :class:`Sampler` runs it every second or so while a tier runs.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

#: The modules the launcher starts the backend as.
BACKEND_MODULES = ("backend.server", "utk_curio.backend.server")
_PROJECT_ID = re.compile(r"^[0-9a-fA-F-]{36}$")

#: How long one reading may take: a ``docker exec`` and a Python start.
PROBE_TIMEOUT_S = 30.0


def is_backend(cmdline: list) -> bool:
    """Whether *cmdline* is the backend's."""
    for index, arg in enumerate(cmdline):
        if arg == "-m" and index + 1 < len(cmdline) and cmdline[index + 1] in BACKEND_MODULES:
            return True
        if str(arg).replace("\\", "/").endswith("backend/server.py"):
            return True
    return False


def pick_backend(processes: list, own_pid: int):
    """The backend's pid among *processes*, ``(pid, ppid, cmdline)`` each: the
    one whose parent is a backend too (Werkzeug's reloader serves from its
    child), else the first; None when there is none."""
    backends = {pid: ppid for pid, ppid, cmdline in processes
                if pid != own_pid and is_backend(cmdline or [])}
    children = sorted(pid for pid, ppid in backends.items() if ppid in backends)
    if children:
        return children[0]
    return min(backends) if backends else None


def state_roots(environ: dict, cwd: str) -> list:
    """Where the backend keeps ``.curio``, as ``user_storage.curio_root`` reads
    it from the backend's environment: ``CURIO_STATE_DIR``, else ``.curio``
    in the launch folder; and the ``test`` folder in it, which
    ``CURIO_TESTING`` uses."""
    override = environ.get("CURIO_STATE_DIR")
    if override:
        root = Path(cwd, override)
    else:
        root = Path(environ.get("CURIO_LAUNCH_CWD") or cwd, ".curio")
    return [root, root / "test"]


def doc_files(roots: list, project_ids: list) -> dict:
    """Each dataflow's log segments under *roots*, by dataflow id: a list of
    ``{doc, day, bin_bytes, updates_bytes}``, by doc and day; a size is None
    when that file is missing."""
    found = {}
    for project_id in project_ids:
        if not _PROJECT_ID.match(project_id):
            continue
        segments = {}
        for root in roots:
            for log_dir in sorted(Path(root).glob(f"users/*/projects/{project_id}/ydoc/*")):
                if not log_dir.is_dir():
                    continue
                for path in sorted(log_dir.iterdir()):
                    if path.suffix not in (".bin", ".updates"):
                        continue
                    entry = segments.setdefault((log_dir.name, path.stem), {
                        "doc": log_dir.name, "day": path.stem,
                        "bin_bytes": None, "updates_bytes": None,
                    })
                    entry["bin_bytes" if path.suffix == ".bin" else "updates_bytes"] = path.stat().st_size
        found[project_id] = [segments[key] for key in sorted(segments)]
    return found


def read(project_ids: list) -> dict:
    """One reading of the backend, here."""
    try:
        import psutil
    except ImportError:
        return {"error": "psutil is not installed where the probe runs"}
    processes = []
    for process in psutil.process_iter(["pid", "ppid", "cmdline"]):
        info = process.info
        processes.append((info.get("pid"), info.get("ppid"), info.get("cmdline") or []))
    pid = pick_backend(processes, os.getpid())
    if pid is None:
        return {"error": "no process here serves -m backend.server"}
    try:
        backend = psutil.Process(pid)
        with backend.oneshot():
            reading = {"pid": pid, "threads": backend.num_threads(),
                       "rss_bytes": backend.memory_info().rss}
            if project_ids:
                environ, cwd = backend.environ(), backend.cwd()
    except psutil.Error as exc:
        return {"error": f"the backend (pid {pid}) could not be read: {type(exc).__name__}: {exc}"}
    if project_ids:
        reading["docs"] = doc_files(state_roots(environ, cwd), project_ids)
    return reading


def main(argv: list) -> None:
    try:
        reading = read(argv)
    except Exception as exc:  # noqa: BLE001 - the harness reports it, never crashes on it
        reading = {"error": f"{type(exc).__name__}: {exc}"}
    sys.stdout.write(json.dumps(reading))
    sys.stdout.flush()


# ---------------------------------------------------------------------------
# The harness's side
# ---------------------------------------------------------------------------

class ProbeError(RuntimeError):
    """A reading the probe could not take, and why."""


class BackendProbe:
    """Runs this file's source as a script with *command*, a program that
    runs Python where the backend runs (``["docker", "exec", cid, "python"]``,
    or this Python)."""

    def __init__(self, command: list, timeout: float = PROBE_TIMEOUT_S):
        self.command = list(command)
        self.timeout = timeout
        self._source = Path(__file__).read_text(encoding="utf-8")

    def read(self, project_ids=()) -> dict:
        """A reading; raises :class:`ProbeError` with the reason when there is none."""
        try:
            done = subprocess.run(
                [*self.command, "-c", self._source, *project_ids],
                capture_output=True, text=True, timeout=self.timeout,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ProbeError(f"{type(exc).__name__}: {exc}") from exc
        if done.returncode != 0:
            raise ProbeError(f"exit {done.returncode}: {done.stderr.strip()[-500:]}")
        try:
            reading = json.loads(done.stdout)
        except ValueError as exc:
            raise ProbeError(f"printed no reading: {done.stdout[-300:]!r} {done.stderr.strip()[-300:]}") from exc
        if not isinstance(reading, dict) or "error" in reading:
            raise ProbeError(str(reading.get("error") if isinstance(reading, dict) else reading))
        return reading

    def sampler(self, every_s: float) -> "Sampler":
        return Sampler(self, every_s)


class Sampler:
    """Reads the backend every *every_s* seconds on a thread of its own, from
    :meth:`start` to :meth:`stop`: how its threads and memory moved while a
    tier ran. A reading that fails is skipped, and the first reason kept."""

    def __init__(self, probe: BackendProbe, every_s: float):
        self.probe = probe
        self.every_s = every_s
        self.samples: list = []
        self.problem = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="backend-probe", daemon=True)
        self._started = time.monotonic()

    def start(self) -> "Sampler":
        self._started = time.monotonic()
        self._thread.start()
        return self

    def _run(self) -> None:
        while not self._stop.is_set():
            began = time.monotonic()
            try:
                reading = self.probe.read()
            except ProbeError as exc:
                self.problem = self.problem or str(exc)
            else:
                self.samples.append({
                    "t": round(began - self._started, 2),
                    "threads": reading.get("threads"),
                    "rss_bytes": reading.get("rss_bytes"),
                })
            self._stop.wait(max(0.0, self.every_s - (time.monotonic() - began)))

    def stop(self) -> list:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=self.probe.timeout + 5)
        return list(self.samples)


if __name__ == "__main__":
    main(sys.argv[1:])
