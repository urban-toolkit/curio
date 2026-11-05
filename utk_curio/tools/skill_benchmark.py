"""``agent_eval.py benchmark``: the skills benchmark (``agents/evaluation/benchmark.py``).

- ``benchmark run``: every skill whole, its trigger queries and its test
  cases, 3 runs with the skill and 3 without, as ``agent_eval.py skills``
  runs them against the endpoint of ``CURIO_EVAL_BASE_URL``,
  ``CURIO_EVAL_API_KEY`` and ``CURIO_EVAL_MODEL``, then scored.
- ``benchmark score <folder>``: a run's folder (``skills-<time>/``) scored,
  into its ``benchmark.json``, with no model call.
- ``benchmark compare <a> <b>``: two scored runs of one version and one
  model, case by case: per skill and over every case, whether ``b`` is
  better, worse or not shown different.

``CURIO_EVAL_GRADER_MODEL`` names one grader for every model a benchmark
measures, on the same endpoint; without it, each model grades its own answers.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from utk_curio.backend.app.agents.evaluation import benchmark, skill_evals

#: Where a run's folder keeps its score.
BENCHMARK_FILE = "benchmark.json"


def add_parser(sub) -> None:
    """The ``benchmark`` command of ``agent_eval.py``."""
    parser = sub.add_parser("benchmark", help="the skills benchmark: run, score and compare",
                            description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="benchmark_command", required=True)
    run = commands.add_parser("run", help="run every skill whole against the endpoint, then score it")
    run.add_argument("--jobs", type=int, default=4, help="workers running at once")
    run.add_argument("--out", type=Path, default=None, help="where the run's folder goes")
    run.set_defaults(func=cmd_run)
    scored = commands.add_parser("score", help="score a run's folder into its benchmark.json")
    scored.add_argument("folder", type=Path)
    scored.set_defaults(func=cmd_score)
    compared = commands.add_parser("compare", help="compare two scored runs of one version and one model")
    compared.add_argument("a", type=Path, help="a run's folder or its benchmark.json: the one compared with")
    compared.add_argument("b", type=Path, help="a run's folder or its benchmark.json: the one measured")
    compared.set_defaults(func=cmd_compare)


def _percent(found) -> str:
    value = (found or {}).get("value")
    if value is None:
        return "-"
    low_high = (found or {}).get("interval")
    span = f" [{low_high[0] * 100:.0f}, {low_high[1] * 100:.0f}]" if low_high else ""
    return f"{value * 100:.0f}%{span}"


def table(scored: dict) -> str:
    """A scored run as a Markdown table: over every case, then each skill."""
    lines = [f"Benchmark version {scored['version']}, model `{scored['model']}`, graded by `{scored['grader']}`.", "",
             "| | Success | All pass | Without | Lift | Reach | Should trigger | Should not | Errors |",
             "|---|---|---|---|---|---|---|---|---|"]
    rows = [("every case", scored["overall"])] + sorted(scored["skills"].items())
    for name, found in rows:
        lift = found["lift"].get("value")
        lines.append("| " + " | ".join([
            name, _percent(found["success"]), _percent(found["all_pass"]), _percent(found["without"]),
            "-" if lift is None else f"{lift * 100:+.0f}", _percent(found["reach"]),
            _percent(found["trigger_recall"]), _percent(found["false_triggers"]), _percent(found["errors"]),
        ]) + " |")
    if scored["disagreements"]:
        lines += ["", f"{len(scored['disagreements'])} checked assertion(s) where the grader said otherwise."]
    return "\n".join(lines) + "\n"


def _scored(path: Path) -> dict:
    path = Path(path)
    file = path if path.is_file() else path / BENCHMARK_FILE
    if file.is_file():
        return json.loads(file.read_text(encoding="utf-8"))
    return benchmark.score(path)


def cmd_score(args) -> int:
    folder = Path(args.folder)
    if not (folder / "run.json").is_file():
        print(f"refused: {folder} is no run's folder", file=sys.stderr)
        return 2
    scored = benchmark.score(folder)
    (folder / BENCHMARK_FILE).write_text(json.dumps(scored, indent=2) + "\n", encoding="utf-8")
    print(table(scored))
    print(f"wrote {folder / BENCHMARK_FILE}")
    return 0


def cmd_compare(args) -> int:
    try:
        found = benchmark.compare(_scored(args.a), _scored(args.b))
    except benchmark.CompareRefused as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    lines = [f"{found['b']} against {found['a']} (version {found['version']}, model `{found['model']}`)", "",
             "| | Success | Should trigger | Should not |", "|---|---|---|---|"]

    def said(item) -> str:
        if not item or item.get("value") is None:
            return "-"
        low, high = item["interval"] or (None, None)
        span = f" [{low * 100:+.0f}, {high * 100:+.0f}]" if low is not None else ""
        return f"{item['verdict']}, {item['value'] * 100:+.0f}{span}"

    lines.append(f"| every case | {said(found['overall']['success'])} | | |")
    for name, items in sorted(found["skills"].items()):
        lines.append(f"| {name} | {said(items['success'])} | {said(items['trigger_recall'])} | "
                     f"{said(items['false_triggers'])} |")
    print("\n".join(lines))
    return 0


def cmd_run(args) -> int:
    from utk_curio.tools import skill_eval_runner

    whole = skill_evals.Measure().as_dict()
    with tempfile.TemporaryDirectory(prefix="curio-benchmark-") as folder:
        scope = Path(folder) / "scope.json"
        scope.write_text(json.dumps({"version": 1, "measure": "full", "why": ["agent_eval.py benchmark run"],
                                     "measures": {s.name: whole for s in skill_evals.shipped_evals()}}),
                         encoding="utf-8")
        runner = argparse.Namespace(skills="", pilot=None, runs=skill_evals.RUNS, jobs=args.jobs, only=None,
                                    out=args.out, resume=None, full_trigger_runs=False, hand=False, scope=scope)
        return skill_eval_runner.run(runner)
