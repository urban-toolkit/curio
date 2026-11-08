"""The backend's thread stacks, sampled every few seconds while a tier runs,
and where its threads spent the tier.

``--stacks-every N`` (``run.py``) takes a sample every N seconds. With
``--py-spy`` it is py-spy's dump of the backend (``py-spy dump --json
--nonblocking``): py-spy reads the process from outside, so a sample needs
no GIL, and it says which thread holds the GIL and which threads are on a
CPU. Without it, the sample is the backend's own dump on SIGUSR1
(``backend_probe.ask_for_stacks``, ``backend/thread_stacks.py``), which the
main thread writes once it gets the GIL. With ``--py-spy`` the tier also gets
py-spy's record of the thread that holds the GIL (``py-spy record --gil``),
sampled 50 times a second: where the backend's Python time went.

Each sample is saved as it comes, one JSON line in
``stack-samples-<name>.jsonl``: ``t`` (seconds since the tier began), the
source, and its threads, each ``[name, state, stack]``, the stack an index in
the frames table the file's last line holds. After the tier, :func:`profile`
counts every sample's threads by what they are (:func:`role`), the Curio frame
they are in, and what they wait on (:func:`waits_on`); :func:`markdown` writes
it to ``stack-profile-<name>.md`` and :func:`log_lines` gives its head for the
log.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
from collections import Counter, defaultdict
from pathlib import Path

#: How long one py-spy dump may take: a ``docker exec`` and a walk of every
#: thread's frames.
DUMP_TIMEOUT_S = 60.0
#: The fewest seconds between two of the backend's own dumps: each one formats
#: every thread's stack on the main thread, holding the GIL, so a dump every
#: few seconds would slow the very calls a tier measures.
SIGNAL_EVERY_MIN_S = 20.0
#: The rate of the GIL record, samples a second, and the longest it records,
#: should the stop at the tier's end miss it.
GIL_RATE = 50
GIL_MAX_S = 1200
#: Where the GIL record is written where the backend runs, then read back.
GIL_FILE = "/tmp/curio-stress-gil-{name}.txt"

#: The repository the harness runs from, whose files the backend's paths name.
REPO_ROOT = Path(__file__).resolve().parents[4]

_THREAD_LINE = re.compile(r"^Thread (\S+) \(([^)]*)\)(?:: \"(.*)\")?\s*$")
_PYSPY_FRAME = re.compile(r"^\s+(.*) \((.*):(\d+)\)\s*$")
_DUMP_GROUP = re.compile(r"^(\d+) thread\(s\): (.*)$")
_DUMP_NAME = re.compile(r"(.+?) \[(\d+)\](?:, |$)")
_DUMP_FRAME = re.compile(r'^  File "(.*)", line (\d+), in (.*)$')

#: The innermost frames of a thread that is blocked, not waiting for the GIL:
#: (file name, function) of a call that waits in C with the GIL let go.
_BLOCKING_FRAMES = {
    ("threading.py", "wait"): "lock or condition",
    ("threading.py", "_wait_for_tstate_lock"): "thread join",
    ("threading.py", "join"): "thread join",
    ("queue.py", "get"): "queue",
    ("queue.py", "put"): "queue",
    ("selectors.py", "select"): "select",
    ("socketserver.py", "serve_forever"): "select",
    ("socket.py", "readinto"): "socket read",
    ("socket.py", "accept"): "socket accept",
    ("ssl.py", "read"): "socket read",
    ("ssl.py", "recv_into"): "socket read",
    ("subprocess.py", "_wait"): "subprocess",
    ("subprocess.py", "_try_wait"): "subprocess",
    ("subprocess.py", "_communicate"): "subprocess",
    ("connection.py", "_recv"): "pipe read",
}
#: The source lines that surely wait in C with the GIL let go: a ``with`` on
#: something named a lock, an acquire, a sleep, a disk sync, a file lock.
#: Any other line of an idle thread may be a wait for the GIL or a C call.
_BLOCKING_WORDS = (
    ("lock", re.compile(r"^with\b[^:]*\b\w*(lock|Lock)\w*\b[^:]*:\s*$|\.acquire\(")),
    ("sleep", re.compile(r"\btime\.sleep\(|^\s*sleep\(")),
    ("disk sync", re.compile(r"\bos\.fsync\(|\bos\.fdatasync\(")),
    ("file lock", re.compile(r"\bfcntl\.(flock|lockf)\(|\bmsvcrt\.locking\(")),
)


# ---------------------------------------------------------------------------
# Reading a sample
# ---------------------------------------------------------------------------

def parse_pyspy_json(text: str) -> list:
    """The threads of py-spy's ``dump --json``: ``{name, state, frames}``
    each, *frames* innermost first, each ``(file, line, function)``;
    *state* ``gil`` for the thread that holds the GIL, ``active`` for one on
    a CPU, ``idle`` for one that is not."""
    threads = []
    for trace in json.loads(text):
        frames = [(frame.get("filename") or "?", int(frame.get("line") or 0), frame.get("name") or "?")
                  for frame in trace.get("frames") or []]
        state = "gil" if trace.get("owns_gil") else ("active" if trace.get("active") else "idle")
        name = trace.get("thread_name") or f"tid {trace.get('os_thread_id') or trace.get('thread_id')}"
        threads.append({"name": name, "state": state, "frames": frames})
    return threads


def parse_pyspy_text(text: str) -> list:
    """The threads of py-spy's plain ``dump``, as :func:`parse_pyspy_json`
    gives them."""
    threads, current = [], None
    for line in text.splitlines():
        head = _THREAD_LINE.match(line)
        if head:
            status = head.group(2)
            state = "gil" if "gil" in status else ("active" if "active" in status else "idle")
            current = {"name": head.group(3) or f"tid {head.group(1)}", "state": state, "frames": []}
            threads.append(current)
            continue
        frame = _PYSPY_FRAME.match(line)
        if frame and current is not None:
            current["frames"].append((frame.group(2), int(frame.group(3)), frame.group(1)))
    return threads


def parse_signal_dump(text: str) -> list:
    """The threads of the backend's own dump (``thread_stacks.dump``), as
    :func:`parse_pyspy_json` gives them, their state unknown (None) and the
    source line of each frame kept as its fourth item."""
    threads, names, frames = [], [], []

    def close():
        if names:
            ordered = list(reversed(frames))
            threads.extend({"name": name, "state": None, "frames": ordered} for name in names)

    lines = text.splitlines()
    for index, line in enumerate(lines):
        group = _DUMP_GROUP.match(line)
        if group:
            close()
            names = [match.group(1) for match in _DUMP_NAME.finditer(group.group(2))]
            frames = []
            continue
        frame = _DUMP_FRAME.match(line)
        if frame and names:
            code = lines[index + 1].strip() if index + 1 < len(lines) and lines[index + 1].startswith("    ") else ""
            frames.append((frame.group(1), int(frame.group(2)), frame.group(3), code))
    close()
    return threads


# ---------------------------------------------------------------------------
# What a thread is and what it waits on
# ---------------------------------------------------------------------------

def _base(path: str) -> str:
    return path.replace("\\", "/").rsplit("/", 1)[-1]


def curio_path(path: str) -> str | None:
    """*path* from ``utk_curio/`` on, or None for a file outside Curio."""
    path = path.replace("\\", "/")
    at = path.find("utk_curio/")
    return path[at:] if at != -1 else None


_SOURCES: dict = {}


def _source(relative: str) -> list:
    """The lines of the repository's file *relative*, read once."""
    if relative not in _SOURCES:
        try:
            with open(REPO_ROOT / relative, encoding="utf-8") as handle:
                _SOURCES[relative] = handle.read().splitlines()
        except OSError:
            _SOURCES[relative] = []
    return _SOURCES[relative]


def source_line(frame) -> str:
    """The source line of *frame*: the one its sample kept, else the
    repository's line for a Curio file; empty when neither is there."""
    if len(frame) > 3 and frame[3]:
        return frame[3]
    relative = curio_path(frame[0])
    if relative is None:
        return ""
    lines = _source(relative)
    return lines[frame[1] - 1].strip() if 0 < frame[1] <= len(lines) else ""


def role(thread: dict) -> str:
    """What *thread* is, from its frames and its name: an agent's turn, a
    Socket.IO handler, a request (by its route's function), the main
    thread's accept loop, or another thread by its outermost frame."""
    frames = thread["frames"]
    files = [frame[0].replace("\\", "/") for frame in frames]
    names = [frame[2] for frame in frames]
    name = thread.get("name") or ""
    if any(f.endswith("turns/turn_jobs.py") for f in files) or name.startswith("agent-turn-job"):
        return "agent turn"
    if name.startswith("agent-job") or any("/solve/" in f for f in files):
        return "agent job"
    if any(("engineio" in f or "socketio" in f or "simple_websocket" in f) for f in files):
        handler = next((frame[2] for frame in frames if (curio_path(frame[0]) or "").startswith(
            "utk_curio/backend/app/collaboration/")), None)
        return f"socket {handler}" if handler else "socket"
    if "dispatch_request" in names or "full_dispatch_request" in names or "wsgi_app" in names:
        # The outermost frame in a module of routes: the route's function.
        for frame in reversed(frames):
            path = curio_path(frame[0]) or ""
            if "/routes" in path or path.endswith("server.py"):
                return f"request {_base(path)}:{frame[2]}"
        return "request"
    if any(f.endswith("werkzeug/serving.py") for f in files):
        for frame in reversed(frames):
            path = curio_path(frame[0]) or ""
            if "/routes" in path:
                return f"request {_base(path)}:{frame[2]}"
        return "request (streaming or reading)"
    if name == "MainThread" or "serve_forever" in names:
        return "main"
    outer = next((frame for frame in reversed(frames) if curio_path(frame[0])), None)
    if outer is not None:
        return f"thread {_base(outer[0])}:{outer[2]}"
    stem = re.sub(r"[-_ ]?\d+.*$", "", name)
    return f"thread {stem or name or '?'}"


def innermost_curio(thread: dict):
    """The innermost frame of *thread* in a Curio file, or None."""
    return next((frame for frame in thread["frames"] if curio_path(frame[0])), None)


def waits_on(thread: dict) -> str:
    """What *thread* was doing: ``holds the GIL`` or ``on a CPU`` where
    py-spy says so; else blocked on a lock, a queue, a socket and so on, by
    its innermost frame (:data:`_BLOCKING_FRAMES`) or that frame's source
    line (:data:`_BLOCKING_WORDS`); else ``GIL wait or C call``: py-spy
    calls a thread that waits for the GIL idle, as it does one in a C call
    that let the GIL go."""
    state = thread.get("state")
    if state == "gil":
        return "holds the GIL"
    if state == "active":
        return "on a CPU without the GIL"
    frames = thread["frames"]
    if not frames:
        return "no Python frame"
    inner = frames[0]
    kind = _BLOCKING_FRAMES.get((_base(inner[0]), inner[2]))
    if kind:
        return f"blocked: {kind}"
    code = source_line(inner)
    for kind, pattern in _BLOCKING_WORDS:
        if pattern.search(code):
            return f"blocked: {kind}"
    return "GIL wait or C call" if state == "idle" else "running, a GIL wait or a C call"


def frame_label(frame) -> str:
    """``path:line function``, the path from ``utk_curio/`` on for a Curio
    file, else the file's name; with its source line when there is one."""
    path = curio_path(frame[0]) or _base(frame[0])
    code = source_line(frame)
    return f"{path}:{frame[1]} {frame[2]}" + (f"  `{code[:120]}`" if code else "")


# ---------------------------------------------------------------------------
# Sampling
# ---------------------------------------------------------------------------

class StackSampler:
    """Takes a sample of the backend's threads every *every_s* seconds on a
    thread of its own, from :meth:`start` to :meth:`stop`, each written to
    *path* as it comes. *pyspy*, the command that runs py-spy where the
    backend runs, and *pid*, the backend's pid there, make it py-spy's dump
    (and :meth:`start` starts the GIL record); else *probe* asks the
    backend for its own dump. A sample that fails is left out, and the first
    reasons kept."""

    def __init__(self, every_s: float, path: str, *, probe=None, pyspy=None, pid=None, name="tier"):
        self.every_s = every_s
        self.path = path
        self.probe = probe
        self.pyspy = list(pyspy or [])
        self.pid = pid
        self.name = name
        self.samples: list = []
        self.problems: list = []
        self.taken = 0
        self._frames: dict = {}
        self._stacks: dict = {}
        self._json = True
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="stack-sampler", daemon=True)
        self._started = time.monotonic()
        self._gil = None
        self._gil_began = time.monotonic()
        self.gil_text = ""
        self.gil_problem = None
        self.gil_seconds = 0.0
        self.gil_said = ""

    @property
    def uses_pyspy(self) -> bool:
        return bool(self.pyspy) and self.pid is not None

    def start(self) -> "StackSampler":
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        open(self.path, "w", encoding="utf-8").close()
        self._started = time.monotonic()
        if self.uses_pyspy:
            self._start_gil_record()
        self._thread.start()
        return self

    # ---- the GIL record ------------------------------------------------------

    def _gil_file(self) -> str:
        return GIL_FILE.format(name=re.sub(r"[^A-Za-z0-9_.-]", "-", self.name))

    def _start_gil_record(self) -> None:
        try:
            self._gil_began = time.monotonic()
            self._gil = subprocess.Popen(
                [*self.pyspy, "record", "--pid", str(self.pid), "--gil", "--nonblocking",
                 "--rate", str(GIL_RATE), "--format", "raw", "--full-filenames",
                 "--output", self._gil_file(), "--duration", str(GIL_MAX_S)],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            )
        except OSError as exc:
            self.gil_problem = f"py-spy record did not start: {exc}"

    def _end_gil_record(self) -> None:
        """Stop the GIL record where it runs (SIGINT, which makes py-spy
        write what it took) and read its file back through the probe."""
        if self._gil is None:
            return
        if self.probe is not None:
            stop = ("import os, signal, psutil\n"
                    "for p in psutil.process_iter(['name', 'cmdline']):\n"
                    "    if p.info['name'] == 'py-spy' or 'py-spy' in ' '.join(p.info['cmdline'] or [])[:40]:\n"
                    "        try:\n            os.kill(p.pid, signal.SIGINT)\n"
                    "        except OSError:\n            pass\n")
            self._probe_python(stop)
        try:
            said, _err = self._gil.communicate(timeout=120)
        except subprocess.TimeoutExpired:
            self._gil.kill()
            said, _err = self._gil.communicate()
            self.gil_problem = "py-spy record did not end within 120 s of its stop"
        self.gil_seconds = round(time.monotonic() - self._gil_began, 1)
        # Its last lines say how many samples it took and how many failed.
        self.gil_said = " | ".join(line.strip() for line in (said or "").splitlines()[-3:] if line.strip())
        if self._gil.returncode not in (0, None) and not self.gil_problem:
            self.gil_problem = f"py-spy record exit {self._gil.returncode}: {(said or '').strip()[-400:]}"
        read = ("import sys\n"
                "try:\n    sys.stdout.write(open(sys.argv[1], encoding='utf-8').read())\n"
                "except OSError as exc:\n    sys.stdout.write('')\n    sys.stderr.write(str(exc))\n")
        text, problem = self._probe_python(read, self._gil_file())
        self.gil_text = text or ""
        if not self.gil_text and not self.gil_problem:
            self.gil_problem = f"no GIL record came back: {problem or 'empty'}"

    def _probe_python(self, source: str, *args) -> tuple:
        """Run *source* with the probe's Python where the backend runs:
        its output and a problem, or None."""
        if self.probe is None:
            return "", "no probe"
        try:
            done = subprocess.run([*self.probe.command, "-c", source, *args],
                                  capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return "", f"{type(exc).__name__}: {exc}"
        return done.stdout, (done.stderr.strip()[-300:] or None) if done.returncode else None

    # ---- the samples -----------------------------------------------------------

    def _sample(self) -> tuple:
        """One sample: ``(source, threads)``; raises RuntimeError with the reason."""
        if self.uses_pyspy:
            args = [*self.pyspy, "dump", "--pid", str(self.pid), "--nonblocking"]
            done = subprocess.run(args + (["--json"] if self._json else []),
                                  capture_output=True, text=True, timeout=DUMP_TIMEOUT_S)
            if done.returncode != 0 and self._json and "json" in (done.stderr or "").lower():
                self._json = False
                done = subprocess.run(args, capture_output=True, text=True, timeout=DUMP_TIMEOUT_S)
            if done.returncode != 0:
                raise RuntimeError(f"py-spy dump exit {done.returncode}: {(done.stderr or '').strip()[-300:]}")
            text = done.stdout.strip()
            at = text.find("[")
            if at != -1 and not text.startswith("Process"):
                try:
                    return "py-spy", parse_pyspy_json(text[at:])
                except ValueError:
                    pass
            threads = parse_pyspy_text(text)
            if not threads:
                raise RuntimeError(f"py-spy dump printed no thread: {text[:300]!r}")
            return "py-spy", threads
        if self.probe is None:
            raise RuntimeError("no probe to ask the backend with")
        answer = self.probe.thread_stacks()
        if answer.get("problem"):
            raise RuntimeError(answer["problem"])
        return "signal", parse_signal_dump(answer.get("stacks", ""))

    def _run(self) -> None:
        failures = 0
        while not self._stop.is_set():
            began = time.monotonic()
            try:
                source, threads = self._sample()
                failures = 0
            except Exception as exc:  # noqa: BLE001 - a sample left out, the reason kept
                failures += 1
                if len(self.problems) < 5:
                    self.problems.append(f"t={began - self._started:.0f}s: {type(exc).__name__}: {exc}")
                if self.uses_pyspy and failures >= 3 and self.probe is not None:
                    self.problems.append("py-spy failed three times running: the backend's own dumps from here on, "
                                         f"one every {max(self.every_s, SIGNAL_EVERY_MIN_S):g} s at most")
                    self.pyspy = []
                self._stop.wait(self._interval())
                continue
            self.taken += 1
            entry = {"t": round(began - self._started, 2), "took_s": round(time.monotonic() - began, 2),
                     "source": source, "threads": [[t["name"], t["state"], self._stack_id(t["frames"])]
                                                   for t in threads]}
            self.samples.append({"t": entry["t"], "threads": threads})
            with open(self.path, "a", encoding="utf-8") as out:
                out.write(json.dumps(entry) + "\n")
            self._stop.wait(max(0.0, self._interval() - (time.monotonic() - began)))

    def _interval(self) -> float:
        """Seconds between samples: *every_s* for py-spy's, which cost the
        backend nothing, at least :data:`SIGNAL_EVERY_MIN_S` for its own."""
        return self.every_s if self.uses_pyspy else max(self.every_s, SIGNAL_EVERY_MIN_S)

    def _stack_id(self, frames: list) -> int:
        ids = []
        for frame in frames:
            key = tuple(frame)
            if key not in self._frames:
                self._frames[key] = len(self._frames)
            ids.append(self._frames[key])
        key = tuple(ids)
        if key not in self._stacks:
            self._stacks[key] = len(self._stacks)
        return self._stacks[key]

    def stop(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=DUMP_TIMEOUT_S + 30)
        if self.uses_pyspy or self._gil is not None:
            self._end_gil_record()
        with open(self.path, "a", encoding="utf-8") as out:
            out.write(json.dumps({
                "frames": [list(frame) for frame in sorted(self._frames, key=self._frames.get)],
                "stacks": [list(stack) for stack in sorted(self._stacks, key=self._stacks.get)],
            }) + "\n")


# ---------------------------------------------------------------------------
# The profile
# ---------------------------------------------------------------------------

def profile(samples: list, gil_text: str = "", gil_seconds: float = 0.0) -> dict:
    """Every sample's threads counted: by role, by role and what they wait
    on, and by role, what they wait on and their innermost Curio frame; and
    the GIL record's samples by their innermost Curio frame and by their
    innermost frame. How busy the GIL was, two ways: the share of py-spy's
    dumps in which a thread held it, and the GIL record's samples over the
    samples its seconds would hold at :data:`GIL_RATE` (a sample is taken
    only while a thread holds the GIL)."""
    roles = Counter()
    waits = Counter()
    places = Counter()
    threads_per_sample = []
    dumps_with_state = dumps_held = 0
    for sample in samples:
        threads_per_sample.append(len(sample["threads"]))
        states = [thread.get("state") for thread in sample["threads"]]
        if any(state is not None for state in states):
            dumps_with_state += 1
            dumps_held += "gil" in states
        for thread in sample["threads"]:
            who = role(thread)
            what = waits_on(thread)
            inner = innermost_curio(thread)
            roles[who] += 1
            waits[(who, what)] += 1
            places[(who, what, frame_label(inner) if inner else frame_label(thread["frames"][0])
                    if thread["frames"] else "-")] += 1
    gil_curio, gil_inner, gil_total = Counter(), Counter(), 0
    for line in gil_text.splitlines():
        stack, _, count = line.rpartition(" ")
        if not stack or not count.isdigit():
            continue
        count = int(count)
        gil_total += count
        frames = [_raw_frame(part) for part in stack.split(";")]
        frames = [frame for frame in frames if frame is not None]
        if not frames:
            continue
        frames.reverse()  # innermost first
        gil_inner[frame_label(frames[0])] += count
        curio = next((frame for frame in frames if curio_path(frame[0])), None)
        gil_curio[frame_label(curio) if curio else "(no Curio frame)"] += count
    return {"samples": len(samples), "threads_per_sample": threads_per_sample,
            "roles": roles, "waits": waits, "places": places,
            "gil_held_in_dumps": (dumps_held, dumps_with_state),
            "gil": {"samples": gil_total, "curio": gil_curio, "inner": gil_inner, "seconds": gil_seconds,
                    "busy": round(gil_total / (GIL_RATE * gil_seconds), 3) if gil_seconds else None}}


_RAW_FRAME = re.compile(r"^(.*) \((.*):(\d+)\)$")


def _raw_frame(text: str):
    match = _RAW_FRAME.match(text.strip())
    if not match:
        return None
    return (match.group(2), int(match.group(3)), match.group(1))


def markdown(result: dict, title: str, every_s: float, problems=(), gil_problem=None, top: int = 12) -> str:
    """The profile as a page: per role, its thread-samples (a thread seen in
    a sample stands for about *every_s* seconds of it), what they waited on,
    and where; then the GIL record."""
    lines = [f"# Where the backend's threads spent {title}", ""]
    n = result["samples"]
    counts = result["threads_per_sample"]
    lines.append(f"{n} sample(s), one every {every_s:g} s; threads per sample "
                 + (f"{min(counts)} to {max(counts)}, mean {sum(counts) / len(counts):.0f}" if counts else "none")
                 + ". A thread seen in a sample stands for about that many seconds of it.")
    for problem in problems:
        lines.append(f"- problem: {problem}")
    held, dumps = result["gil_held_in_dumps"]
    if dumps:
        lines.append(f"- a thread held the GIL in {held} of {dumps} py-spy dump(s) ({100 * held / dumps:.0f}%)")
    gil = result["gil"]
    if gil["busy"] is not None:
        lines.append(f"- the GIL record took {gil['samples']} sample(s) over {gil['seconds']:g} s at {GIL_RATE} "
                     f"a second: the GIL was held {100 * gil['busy']:.0f}% of the time")
    lines.append("")
    by_role = defaultdict(list)
    for (who, what), count in result["waits"].items():
        by_role[who].append((count, what))
    for who, total in result["roles"].most_common():
        lines.append(f"## {who}: {total} thread-sample(s), {total / max(n, 1):.1f} thread(s) a sample")
        lines.append("")
        for count, what in sorted(by_role[who], reverse=True):
            lines.append(f"- {what}: {count} ({100 * count / total:.0f}%)")
        lines.append("")
        lines.append("| Thread-samples | Waits on | Innermost Curio frame |")
        lines.append("| -------------: | -------- | --------------------- |")
        mine = sorted(((count, what, where) for (w, what, where), count in result["places"].items() if w == who),
                      reverse=True)
        for count, what, where in mine[:top]:
            lines.append(f"| {count} | {what} | {where.replace('|', '/')} |")
        lines.append("")
    lines.append(f"## The GIL's holder, {gil['samples']} sample(s) at {GIL_RATE} a second")
    lines.append("")
    if gil_problem:
        lines.append(f"- problem: {gil_problem}")
    if gil["samples"]:
        for heading, counter in (("Innermost Curio frame", gil["curio"]), ("Innermost frame", gil["inner"])):
            lines += ["", f"| Samples | Share | {heading} |", "| ------: | ----: | ------------ |"]
            for where, count in counter.most_common(top * 2):
                lines.append(f"| {count} | {100 * count / gil['samples']:.1f}% | {where.replace('|', '/')} |")
    lines.append("")
    return "\n".join(lines)


def log_lines(result: dict, top: int = 5) -> list:
    """The profile's head for the log: each of the busiest roles with its
    thread-samples and its first places, and the GIL record's first frames."""
    lines = []
    n = max(result["samples"], 1)
    held, dumps = result["gil_held_in_dumps"]
    busy = result["gil"]["busy"]
    if dumps or busy is not None:
        lines.append("GIL held in " + (f"{held} of {dumps} dump(s)" if dumps else "no dump")
                     + (f"; held {100 * busy:.0f}% of the GIL record's {result['gil']['seconds']:g} s"
                        if busy is not None else ""))
    for who, total in result["roles"].most_common(8):
        mine = sorted(((count, what, where) for (w, what, where), count in result["places"].items() if w == who),
                      reverse=True)[:top]
        lines.append(f"{who}: {total / n:.1f} thread(s) a sample; "
                     + "; ".join(f"{count} {what} at {where[:160]}" for count, what, where in mine))
    gil = result["gil"]
    if gil["samples"]:
        lines.append(f"GIL holder, {gil['samples']} sample(s): " + "; ".join(
            f"{100 * count / gil['samples']:.1f}% {where[:160]}" for where, count in gil["curio"].most_common(top * 2)))
    return lines
