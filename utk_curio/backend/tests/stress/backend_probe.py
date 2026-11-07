"""The backend's threads and memory, and its dataflows' doc files, read where it runs.

The stress harness runs this file's own source with ``python -c``, through the
command its ``--probe`` names: ``docker exec <container> python`` in CI, where
the stack's ``.curio`` is its root's alone (the execution user hardens it), or
this machine's Python for a stack started here. So the script imports only the
standard library and psutil, which the backend itself requires, and prints one
JSON object:

* ``pid``, ``threads``, ``rss_bytes`` and ``cpu_seconds`` (user plus system,
  which psutil reads from ``/proc/<pid>/stat`` on Linux): the backend's
  process, the one that serves ``-m backend.server`` (``cli/services.py``),
  the reloader's child when there is one;
* ``docs``, for each dataflow id it is given: the segments of each of its
  docs' logs, ``ydoc/<doc id>/<day>.bin`` and ``<day>.updates``
  (``collaboration/dataflow_docs.py``), with their sizes, under the backend's
  state root (``common/user_storage.curio_root``);
* or ``error``, saying why it read nothing.

Given ``--thread-stacks``, it asks the backend for every thread's stack
instead (:func:`ask_for_stacks`): it sends SIGUSR1, which the backend answers
by appending a dump to a file in its state folder (``backend/thread_stacks.py``),
and prints ``pid``, ``path`` and ``stacks``, the dump, with ``problem`` when no
whole dump came in time.

The rest of the file is the harness's side: :class:`BackendProbe` runs the
script, :func:`reading_now` stamps a reading with when it was taken and the
harness's CPU seconds (``resource.getrusage``, its worker processes counted),
:class:`Sampler` takes one every second or so while a tier runs, and
:func:`save_thread_stacks` writes the backend's thread stacks into the report
folder.
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

#: The backend's file of thread stacks, in its state folder, and how long the
#: probe waits for a dump to end there (``backend/thread_stacks.py``).
STACKS_FILE = "backend-thread-stacks.txt"
STACKS_WAIT_S = 20.0


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


def process_reading(process) -> dict:
    """A psutil process's pid, threads, resident bytes, and CPU seconds, user
    plus system, of all its threads."""
    with process.oneshot():
        times = process.cpu_times()
        return {"pid": process.pid, "threads": process.num_threads(),
                "rss_bytes": process.memory_info().rss,
                "cpu_seconds": round(times.user + times.system, 3)}


def stacks_file(environ: dict, cwd: str) -> Path:
    """The backend's file of thread stacks, as ``thread_stacks.stacks_path``
    finds it from the backend's environment."""
    return state_roots(environ, cwd)[0] / STACKS_FILE


def stacks_end_line(pid: int) -> str:
    """The line that ends a whole dump of process *pid* (``thread_stacks.end_line``)."""
    return f"=== end of the thread stacks of pid {pid} ==="


def catches(pid: int, signum: int, status: str | None = None):
    """Whether process *pid* handles signal *signum*, from the caught mask in
    *status*, the text of ``/proc/<pid>/status`` (read when not given); None
    where there is no such file."""
    if status is None:
        try:
            status = Path(f"/proc/{pid}/status").read_text(encoding="utf-8")
        except OSError:
            return None
    for line in status.splitlines():
        if line.startswith("SigCgt:"):
            return bool(int(line.split()[1], 16) >> (signum - 1) & 1)
    return None


def ask_for_stacks(pid: int, path, wait_s: float = STACKS_WAIT_S) -> dict:
    """Send process *pid* SIGUSR1 and wait for the dump of its thread stacks
    it appends to *path* (``backend/thread_stacks.py``): ``pid``, ``path``
    and ``stacks``, and ``problem`` when no whole dump came in *wait_s*
    seconds; or ``error`` when it was not asked."""
    import signal

    path = Path(path)
    signum = getattr(signal, "SIGUSR1", None)
    if signum is None:
        return {"error": "this system has no SIGUSR1 to ask with"}
    if catches(pid, signum) is False:
        # Not sent: SIGUSR1 ends a process that does not handle it.
        return {"error": f"process {pid} does not handle SIGUSR1: a backend without thread stacks"}
    start = path.stat().st_size if path.exists() else 0
    try:
        os.kill(pid, signum)
    except OSError as exc:
        return {"error": f"could not signal process {pid}: {exc}"}
    end, text = stacks_end_line(pid), ""
    deadline = time.monotonic() + wait_s
    while True:
        if path.exists():
            with open(path, "rb") as dumped:
                dumped.seek(start)
                text = dumped.read().decode("utf-8", "replace")
        if end in text:
            return {"pid": pid, "path": str(path), "stacks": text[:text.index(end) + len(end)] + "\n"}
        if time.monotonic() >= deadline:
            return {"pid": pid, "path": str(path), "stacks": text,
                    "problem": (f"no whole dump in {wait_s:g} s: the backend's main thread "
                                "ran no Python in that time")}
        time.sleep(0.1)


def find_backend(psutil):
    """The backend's pid here, or None."""
    processes = []
    for process in psutil.process_iter(["pid", "ppid", "cmdline"]):
        info = process.info
        processes.append((info.get("pid"), info.get("ppid"), info.get("cmdline") or []))
    return pick_backend(processes, os.getpid())


def thread_stacks_here() -> dict:
    """The backend's thread stacks, asked for here (:func:`ask_for_stacks`)."""
    try:
        import psutil
    except ImportError:
        return {"error": "psutil is not installed where the probe runs"}
    pid = find_backend(psutil)
    if pid is None:
        return {"error": "no process here serves -m backend.server"}
    try:
        backend = psutil.Process(pid)
        environ, cwd = backend.environ(), backend.cwd()
    except psutil.Error as exc:
        return {"error": f"the backend (pid {pid}) could not be read: {type(exc).__name__}: {exc}"}
    return ask_for_stacks(pid, stacks_file(environ, cwd))


def read(project_ids: list) -> dict:
    """One reading of the backend, here."""
    try:
        import psutil
    except ImportError:
        return {"error": "psutil is not installed where the probe runs"}
    pid = find_backend(psutil)
    if pid is None:
        return {"error": "no process here serves -m backend.server"}
    try:
        backend = psutil.Process(pid)
        reading = process_reading(backend)
        if project_ids:
            environ, cwd = backend.environ(), backend.cwd()
    except psutil.Error as exc:
        return {"error": f"the backend (pid {pid}) could not be read: {type(exc).__name__}: {exc}"}
    if project_ids:
        reading["docs"] = doc_files(state_roots(environ, cwd), project_ids)
    return reading


def main(argv: list) -> None:
    try:
        reading = thread_stacks_here() if argv[:1] == ["--thread-stacks"] else read(argv)
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
        return self._run(list(project_ids), self.timeout)

    def thread_stacks(self) -> dict:
        """The backend's dump of every thread's stack (:func:`ask_for_stacks`);
        raises :class:`ProbeError` when it could not be asked."""
        return self._run(["--thread-stacks"], self.timeout + STACKS_WAIT_S)

    def _run(self, args: list, timeout: float) -> dict:
        try:
            done = subprocess.run(
                [*self.command, "-c", self._source, *args],
                capture_output=True, text=True, timeout=timeout,
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

#: The harness's worker processes, each running some of a tier's users: pid ->
#: its own CPU seconds once it reported them at its end, None while it runs.
_workers: dict = {}
_workers_lock = threading.Lock()


def process_cpu_seconds() -> float:
    """This process's CPU seconds, user plus system, of all its threads."""
    import resource

    usage = resource.getrusage(resource.RUSAGE_SELF)
    return usage.ru_utime + usage.ru_stime


def track_worker(pid: int) -> None:
    """Count the worker process *pid* in the harness's CPU from now on."""
    with _workers_lock:
        _workers[pid] = None


def worker_finished(pid: int, cpu_seconds: float) -> None:
    """The worker *pid* ended having run *cpu_seconds*, which it read itself."""
    with _workers_lock:
        _workers[pid] = cpu_seconds


def forget_worker(pid: int) -> None:
    with _workers_lock:
        _workers.pop(pid, None)


def harness_cpu_seconds() -> float:
    """The harness's CPU seconds, user plus system: this process's and its
    worker processes', every user's dataflow calls and tab among them. A
    running worker is read through psutil, an ended one by what it reported;
    the probe's own commands are not counted."""
    total = process_cpu_seconds()
    with _workers_lock:
        workers = dict(_workers)
    for pid, final in workers.items():
        if final is not None:
            total += final
            continue
        try:
            import psutil

            times = psutil.Process(pid).cpu_times()
            total += times.user + times.system
        except Exception:  # noqa: BLE001 - ended before it reported: counted once it does
            pass
    return total


def reading_now(probe, project_ids=(), started=None) -> tuple:
    """A reading of the backend through *probe*, or none without one, stamped
    with the moment it was taken (``at``, the middle of the call, on this
    process's monotonic clock) and with this process's own CPU seconds
    (``harness_cpu_seconds``, at ``harness_at``); and why the backend could
    not be read, or None. *started* adds ``t``, seconds since then."""
    began = time.monotonic()
    reading, problem = {}, None
    if probe is not None:
        try:
            reading = dict(probe.read(project_ids))
        except ProbeError as exc:
            problem = str(exc)
    ended = time.monotonic()
    if reading:
        reading["at"] = (began + ended) / 2
    reading["harness_at"] = ended
    reading["harness_cpu_seconds"] = harness_cpu_seconds()
    if started is not None:
        reading["t"] = round(began - started, 2)
    return reading, problem


class Sampler:
    """Takes a reading every *every_s* seconds on a thread of its own, from
    :meth:`start` to :meth:`stop`: how the backend's threads, memory and CPU,
    and the harness's own CPU, moved while a tier ran. Without a probe it
    reads the harness alone. A backend reading that fails is left out, and
    the first reason kept."""

    def __init__(self, probe, every_s: float):
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
            reading, problem = reading_now(self.probe, started=self._started)
            if problem:
                self.problem = self.problem or problem
            self.samples.append(reading)
            self._stop.wait(max(0.0, self.every_s - (time.monotonic() - began)))

    def stop(self) -> list:
        self._stop.set()
        if self._thread.is_alive():
            timeout = self.probe.timeout if self.probe is not None else PROBE_TIMEOUT_S
            self._thread.join(timeout=timeout + 5)
        return list(self.samples)


def save_thread_stacks(probe, out_dir: str, name: str) -> tuple:
    """Ask the backend through *probe* for every thread's stack and write
    what came, or why nothing did, to ``<out_dir>/thread-stacks-<name>.txt``:
    that path and a line for the log."""
    asked = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    try:
        answer = probe.thread_stacks()
    except ProbeError as exc:
        answer = {"problem": f"the probe could not ask: {exc}"}
    problem = answer.get("problem")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"thread-stacks-{name}.txt")
    with open(path, "w", encoding="utf-8") as out:
        out.write(f"The stress harness asked the backend for its thread stacks at {asked}"
                  + (f" (pid {answer['pid']}, its file {answer['path']})" if "pid" in answer else "")
                  + ".\n")
        if problem:
            out.write(f"Problem: {problem}\n")
        out.write("\n" + answer.get("stacks", ""))
    head = (answer.get("stacks") or "").partition("\n")[0].strip("= ")
    line = f"asked the backend for its thread stacks, saved in {path}" + (f": {head}" if head else "")
    return path, line + (f"; {problem}" if problem else "")


if __name__ == "__main__":
    main(sys.argv[1:])
