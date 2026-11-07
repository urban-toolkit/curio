"""``agent_eval.py skills``: evaluate Curio's skills as agentskills.io describes, against a live model.

Every skill Curio ships may hold ``evals/evals.json``
(``agents/evaluation/skill_evals.py`` says what it holds). This runs each
trigger query and each test case :data:`skill_evals.RUNS` times, the test
cases with the skill and without it, on ``--jobs`` workers
(``skill_eval_worker.py``), each a backend of its own with no web stack, and
writes, under ``--out``, one folder per run of the tool:

- ``run.json``: the model, the runs and the skills, each by the digest of its
  ``SKILL.md``;
- ``<skill>/triggers/q<NN>/run-<k>/``: each trigger run's record and
  transcript, and ``<skill>/triggers.json``, each query's trigger rate;
- ``<skill>/eval-<id>/with_skill/run-<k>/`` and ``without_skill/``:
  ``outputs/`` (the reply, and ``changes.json``: what the run changed in its
  dataflow and the installs it asked for), ``transcript.json``,
  ``timing.json``, ``grading.json`` and ``run.json``, and
  ``<skill>/benchmark.json``;
- ``summary.json`` and ``summary.md``; ``benchmark.json``, the run scored as
  the skills benchmark scores it (``agents/evaluation/benchmark.py``);
  ``logs/``, each worker's warnings.

The endpoint is read from ``CURIO_EVAL_BASE_URL``, ``CURIO_EVAL_API_KEY`` and
``CURIO_EVAL_MODEL``, and handed to the workers in their environment, never
on a command line. Nothing written holds the key, the base URL or its host:
the workers scrub every file and log line, and the runner reads every file
again at the end and fails if one does. ``--pilot`` runs one skill and says
how long the whole run would take. ``--resume`` goes on with a run's folder,
running only what has no record yet. ``--scope`` runs each skill a scope
names as its measure says (``skill_evals.Measure``): the skill-evals CI job
runs this so, on each model of ``CURIO_EVAL_MODELS``
(``scripts/ci_skill_evals.py``).
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from utk_curio import shipped
from utk_curio.backend.app.agents.domain import skills as skill_format
from utk_curio.backend.app.agents.evaluation import benchmark, skill_evals
from utk_curio.tools import skill_benchmark as benchmark_command
from utk_curio.backend.app.agents.evaluation.report import scrub

#: The worker each job runs.
WORKER = Path(__file__).with_name("skill_eval_worker.py")
#: Variables a worker never inherits: they change what the backend is.
_NOT_INHERITED = ("CURIO_TESTING", "CURIO_DEV", "CURIO_NO_AUTH", "CURIO_STATE_DIR", "CURIO_LAUNCH_CWD",
                  "CURIO_PACKAGES_ROOT", "CURIO_SHARED_DATA")
#: The record each run writes last, which marks it done.
RECORD = "run.json"
#: The variable naming one grader for every model (``skill_eval_worker.ENV_GRADER``).
GRADER_VARIABLE = "CURIO_EVAL_GRADER_MODEL"


def add_parser(sub) -> None:
    """The ``skills`` command of ``agent_eval.py``."""
    parser = sub.add_parser(
        "skills", help="evaluate the skills against a live model (agentskills.io's way)",
        description="Run each skill's evals/evals.json: its trigger queries, and its test cases with the skill "
                    "and without it, against the endpoint of CURIO_EVAL_BASE_URL, CURIO_EVAL_API_KEY and "
                    "CURIO_EVAL_MODEL. Writes reports, which the skill-evals CI job reads "
                    "(scripts/ci_skill_evals.py).",
    )
    parser.add_argument("--skills", default="", help="comma-separated skill names (default: every skill with evals)")
    parser.add_argument("--pilot", nargs="?", const="", default=None, metavar="SKILL",
                        help="run one skill only (the first, or SKILL) and project the whole run's time")
    parser.add_argument("--runs", type=int, default=skill_evals.RUNS, help="runs of each query and test case")
    parser.add_argument("--jobs", type=int, default=4, help="workers running at once")
    parser.add_argument("--only", choices=skill_evals.KINDS, default=None,
                        help="run only the trigger queries, only the test cases, or only the grade runs, which "
                             "grade the grader truth's prepared answers with the model measured")
    parser.add_argument("--out", type=Path, default=None, help="where the run's folder goes (default: eval/ "
                                                                    "in Curio's state folder)")
    parser.add_argument("--resume", type=Path, default=None,
                        help="a run's folder to go on with: runs that have a record are kept")
    parser.add_argument("--full-trigger-runs", action="store_true",
                        help="let a trigger run finish after it loads the skill")
    parser.add_argument("--hand", action="store_true",
                        help="hand a test case's skill over as /<name> in its runs with the skill, "
                             "instead of leaving the loading to the agent")
    parser.add_argument("--scope", type=Path, default=None,
                        help="a scope's JSON (scripts/ci_skill_eval_scope.py): run each skill it measures as its "
                             "measure says, instead of --skills, --runs and --only")
    parser.set_defaults(func=run)


def _say(text: str) -> None:
    print(text, flush=True)


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _commit() -> str | None:
    """The commit this checkout is at: ``CURIO_EVAL_COMMIT`` when set (an
    image holds no ``.git``), else git's answer."""
    if os.environ.get("CURIO_EVAL_COMMIT", "").strip():
        return os.environ["CURIO_EVAL_COMMIT"].strip()
    try:
        done = subprocess.run(["git", "-C", str(shipped.root()), "rev-parse", "HEAD"],
                              capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() or None


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = data if isinstance(data, str) else json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def _answers() -> dict[str, list[dict]]:
    """Each skill's prepared answers in the grader truth, as a grade run's task holds them."""
    from utk_curio.backend.app.agents.evaluation import grader_truth

    return {name: [{"case": answer.case, "name": answer.name, "kind": answer.kind, "fails": list(answer.fails),
                    "reply": answer.reply, "changes": answer.changes, "calls": answer.calls}
                   for answer in truth.answers]
            for name, truth in grader_truth.shipped().items()}


def _selected(args, evals) -> list:
    by_name = {skill.name: skill for skill in evals}
    names = [name.strip() for name in args.skills.split(",") if name.strip()]
    unknown = [name for name in names if name not in by_name]
    if unknown:
        raise SystemExit(f"no evals/evals.json for: {', '.join(unknown)}")
    chosen = [by_name[name] for name in names] if names else list(evals)
    if args.pilot is not None:
        if args.pilot and args.pilot not in by_name:
            raise SystemExit(f"no evals/evals.json for: {args.pilot}")
        chosen = [by_name[args.pilot]] if args.pilot else chosen[:1]
    return chosen


class _Workers:
    """The workers, each a process with its own state folder, fed from one queue."""

    def __init__(self, jobs: int, folder: Path, endpoint: skill_evals.Endpoint, args):
        self.folder = folder
        self.secrets = endpoint.secrets()
        self.args = args
        self.queue: queue.Queue = queue.Queue()
        self.lock = threading.Lock()
        self.done = 0
        self.failed = 0
        self.total = 0
        self.states = [Path(tempfile.mkdtemp(prefix="curio-skill-eval-")) for _ in range(max(1, jobs))]
        self.processes: list[subprocess.Popen] = []

    def _env(self, state: Path) -> dict:
        env = {key: value for key, value in os.environ.items() if key not in _NOT_INHERITED}
        packages = state / "packages"
        shutil.copytree(shipped.path("packages"), packages, symlinks=True)
        env.update({
            "CURIO_LAUNCH_CWD": str(state), "CURIO_STATE_DIR": str(state / ".curio"),
            "CURIO_PACKAGES_ROOT": str(packages), "CURIO_SHARED_DATA": str(state / "data"),
            "CURIO_EVAL_RESULTS": str(self.folder), "PYTHONUNBUFFERED": "1",
            "CURIO_EVAL_FULL_TRIGGER_RUNS": "1" if self.args.full_trigger_runs else "0",
            "CURIO_EVAL_HAND": "1" if self.args.hand else "0",
            "PYTHONPATH": os.pathsep.join(p for p in (str(shipped.CODE_ROOT), env.get("PYTHONPATH")) if p),
        })
        return env

    def _log(self, process: subprocess.Popen, number: int) -> None:
        log = self.folder / "logs" / f"worker-{number}.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as sink:
            for line in process.stderr:
                sink.write(scrub(line, values=self.secrets))
                sink.flush()

    def _feed(self, process: subprocess.Popen, number: int) -> None:
        def answer() -> dict | None:
            for line in process.stdout:
                try:
                    value = json.loads(line)
                except ValueError:
                    continue
                if isinstance(value, dict):
                    return value
            return None

        if not (answer() or {}).get("ready"):
            _say(f"worker {number} did not start: see logs/worker-{number}.log")
            return
        while True:
            try:
                task = self.queue.get_nowait()
            except queue.Empty:
                break
            process.stdin.write(json.dumps({"task": task.as_dict()}) + "\n")
            process.stdin.flush()
            reply = answer()
            if reply is None:
                _say(f"worker {number} stopped during {task.path}: see logs/worker-{number}.log")
                return
            with self.lock:
                self.done += 1
                self.failed += bool(reply.get("error"))
                seconds = reply.get("seconds")
                took = f"{seconds:.1f}s" if isinstance(seconds, (int, float)) else "?"
                mark = " error" if reply.get("error") else ""
                _say(f"[{self.done}/{self.total}] {task.path} {took}{mark}")
        process.stdin.write(json.dumps({"stop": True}) + "\n")
        process.stdin.flush()

    def run(self, tasks: list) -> None:
        self.total = len(tasks)
        for task in tasks:
            self.queue.put(task)
        threads = []
        try:
            for number, state in enumerate(self.states[:max(1, min(len(self.states), len(tasks)))], start=1):
                process = subprocess.Popen(
                    [sys.executable, "-u", str(WORKER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE, text=True, encoding="utf-8", cwd=state, env=self._env(state),
                )
                self.processes.append(process)
                for target in (self._log, self._feed):
                    thread = threading.Thread(target=target, args=(process, number), daemon=True)
                    thread.start()
                    threads.append(thread)
            for thread in threads:
                thread.join()
        finally:
            self.close()

    def close(self) -> None:
        for process in self.processes:
            with contextlib.suppress(OSError):
                process.stdin.close()
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                process.kill()
        for state in self.states:
            shutil.rmtree(state, ignore_errors=True)


def _records(folder: Path) -> list[dict]:
    found = []
    for path in sorted(folder.glob(f"*/**/{RECORD}")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(record, dict) and record.get("kind"):
            found.append(record)
    return found


def _percent(value) -> str:
    return "" if value is None else f"{value * 100:.0f}%"


def _report(folder: Path, chosen: list, meta: dict) -> dict:
    """Write each skill's ``triggers.json`` and ``benchmark.json``, and the
    run's ``summary.json`` and ``summary.md``. A skill a scope measured only
    some kinds of run of is reported for those alone."""
    records = _records(folder)
    kinds_of = {name: set(measure.get("kinds") or ()) for name, measure in (meta.get("measures") or {}).items()}
    rows = []
    for skill in chosen:
        mine = [r for r in records if r.get("skill") == skill.name]
        kinds = kinds_of.get(skill.name, set(meta.get("kinds") or (skill_evals.TRIGGER, skill_evals.TASK)))
        triggers = skill_evals.trigger_results(skill, mine) if skill_evals.TRIGGER in kinds else []
        if triggers:
            _write(folder / skill.name / "triggers.json", triggers)
        bench = skill_evals.benchmark(skill, mine) if skill.cases and skill_evals.TASK in kinds else None
        if bench:
            _write(folder / skill.name / "benchmark.json", bench)
        rows.append({"skill": skill.name, "triggers": skill_evals.trigger_summary(triggers),
                     "benchmark": bench["run_summary"] if bench else None,
                     "errors": sum(1 for r in mine if r.get("error"))})
    summary = {**meta, "finished": datetime.now(timezone.utc).isoformat(timespec="seconds"), "skills": rows}
    _write(folder / "summary.json", summary)
    lines = [
        f"# Skill evaluation {meta['run']}",
        "",
        f"Model `{meta['model']}`. Runs of each query, and of each test case in each condition: {meta['runs']}. "
        "An evaluation report, not a gate.",
        "",
        ("| Skill | Triggers passed | Should trigger | Should not | Handed off | With skill | Without | Delta | Used "
         "| Errors |"),
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        t, b = row["triggers"] or {}, row["benchmark"] or {}
        with_skill, without = b.get(skill_evals.WITH_SKILL) or {}, b.get(skill_evals.WITHOUT_SKILL) or {}
        used = with_skill.get("used") or {}
        delta = (b.get("delta") or {}).get("pass_rate")
        lines.append("| " + " | ".join([
            row["skill"],
            f"{t['passed']} of {t['judged']}" if t else "",
            _percent(t.get("should_trigger_rate")), _percent(t.get("should_not_trigger_rate")),
            f"{t['handed_off']} of {t['runs']}" if t else "",
            _percent((with_skill.get("pass_rate") or {}).get("mean")),
            _percent((without.get("pass_rate") or {}).get("mean")),
            "" if delta is None else f"{delta * 100:+.0f} points",
            f"{used.get('runs')} of {with_skill.get('runs')}" if with_skill.get("runs") else "",
            str(row["errors"]),
        ]) + " |")
    _write(folder / "summary.md", "\n".join(lines) + "\n")
    return summary


def run(args) -> int:
    try:
        endpoint = skill_evals.Endpoint.from_env()
    except LookupError as exc:
        print(f"refused: {exc}; the endpoint is read from them, and never written", file=sys.stderr)
        return 2
    try:
        evals = skill_evals.shipped_evals()
    except skill_evals.EvalsError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    kinds = (args.only,) if args.only else (skill_evals.TRIGGER, skill_evals.TASK)
    measured: dict = {}
    if args.scope:
        try:
            measured = skill_evals.measures(json.loads(args.scope.read_text(encoding="utf-8")))
        except (OSError, ValueError, skill_evals.EvalsError) as exc:
            print(f"refused: the scope {args.scope} cannot be read: {exc}", file=sys.stderr)
            return 2
        chosen = [skill for skill in evals if skill.name in measured]
        unmeasurable = sorted(set(measured) - {skill.name for skill in chosen})
        if unmeasurable:
            _say(f"no evals/evals.json, so not measured: {', '.join(unmeasurable)}")
    else:
        chosen = _selected(args, evals)
    answers = None
    if skill_evals.GRADE in {*kinds, *(kind for measure in measured.values() for kind in measure.kinds)}:
        try:
            answers = _answers()
        except ValueError as exc:
            print(f"refused: the grader truth cannot be read: {exc}", file=sys.stderr)
            return 2
    if measured:
        planned = skill_evals.plan_measured(chosen, measured, answers)
    else:
        planned = skill_evals.plan(chosen, runs=max(1, args.runs), kinds=kinds, answers=answers)
    if args.resume:
        folder = args.resume.resolve()
        if not (folder / RECORD).is_file():
            print(f"refused: {folder} is no run's folder", file=sys.stderr)
            return 2
        meta = json.loads((folder / RECORD).read_text(encoding="utf-8"))
    else:
        from utk_curio.backend.app.common.user_storage import curio_root

        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        folder = ((args.out or curio_root() / "eval") / f"skills-{stamp}").resolve()
        meta = {
            "run": folder.name, "model": endpoint.model, "runs": max(1, args.runs), "jobs": args.jobs,
            "kinds": list(kinds), "pilot": args.pilot is not None, "hand": args.hand,
            "fullTriggerRuns": args.full_trigger_runs, "commit": _commit(),
            "started": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "skills": {s.name: _digest(s.folder / skill_format.SKILL_FILE) for s in chosen},
            "isReleaseGate": False,
            # The benchmark's set this run measured, and who graded it (benchmark.py).
            "benchmarkVersion": benchmark.version(evals),
            "grader": os.environ.get(GRADER_VARIABLE, "").strip() or endpoint.model,
        }
        if measured:
            meta["measures"] = {s.name: measured[s.name].as_dict() for s in chosen}
        _write(folder / RECORD, meta)
    left = [task for task in planned if not (folder / task.path / RECORD).is_file()]
    _say(f"{len(chosen)} skill(s), {len(planned)} runs, {len(left)} to go, {args.jobs} jobs: {folder}")
    workers = _Workers(args.jobs, folder, endpoint, args)
    started = time.monotonic()
    interrupted = False
    try:
        if left:
            workers.run(left)
    except KeyboardInterrupt:
        interrupted = True
        workers.close()
    hours = (time.monotonic() - started) / 3600
    _report(folder, chosen, meta)
    _write(folder / benchmark_command.BENCHMARK_FILE, benchmark.score(folder, {s.name: s for s in evals}))
    _say(f"wrote {folder / 'summary.md'} after {hours * 60:.1f} minutes")
    if args.pilot is not None:
        whole = skill_evals.plan(_selected(argparse.Namespace(**{**vars(args), "pilot": None}), evals),
                                 runs=max(1, args.runs), kinds=kinds)
        guess = skill_evals.projection(_records(folder), whole, args.jobs)
        _say(f"the whole run: {guess['runs']} runs, about {guess['hours']} hours on {args.jobs} jobs "
             f"(mean seconds a run: {guess['mean_seconds']})")
    leaked = skill_evals.leaks(folder, endpoint)
    if leaked:
        print(f"FAILED: {len(leaked)} file(s) hold the key, the base URL or its host:", file=sys.stderr)
        for path in leaked:
            print(f"  {path}", file=sys.stderr)
        return 1
    _say("checked: no file holds the key, the base URL or its host")
    missing = sum(1 for task in planned if not (folder / task.path / RECORD).is_file())
    if missing:
        print(f"{missing} run(s) have no record (see {folder / 'logs'}); go on with --resume {folder}",
              file=sys.stderr)
        return 130 if interrupted else 1
    return 0
