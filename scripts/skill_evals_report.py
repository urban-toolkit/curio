"""The Skill evaluations workflow's report: one page, ``curio-skill-evals-report.html``, of a run on every model.

``scripts/ci_skill_evals.py run`` writes one folder per model, the
``agent_eval.py skills`` run folder of that model (``results/<model>/skills-*/``),
and then calls this. It reads each folder's ``run.json`` (the model, the
commit and each skill's measure), its ``summary.json`` (each skill's pass rates
and trigger rates, as the runner counted them) and every run's own record and
transcript, and shows, per model and skill:

- the pass rate with the skill and without it, the difference, and the change
  since main's last run (``--previous``, its per-model summaries);
- the floor (``skill_eval_floors.json``), which a skill measured whole is held
  to;
- how often the skill reached the model (loaded, handed or in the preamble);
- the trigger rates;
- reliability, counted from each run's record: its turns on native tools and
  on fenced blocks, calls the output cap cut, and runs left in an error;
- tokens, time and, for a model ``skill_eval_prices.json`` prices, dollars at
  list price.

Each failed assertion is listed with the path of its run in the results
artifact.

The benchmark (``agents/evaluation/benchmark.py``) scores each model's run, its
checked assertions decided by their checks. The page shows its leaderboard,
one row a model with each rate's 95% interval, then each skill's success per
model and the models it fails on. Where main's last run of a model
measured the same set, it also shows that run against this one, case by case,
and each skill shown better or worse.

The same tables, shorter, go to ``summary.md`` for the job summary, and each
model's numbers, its benchmark among them, to ``summaries/<model>.json``, which
the next runs compare with. :func:`gate` says what fails the run: a probe that
failed, a run left in an error, a runner that failed, a skill shown worse than main's last run.

    python3 scripts/skill_evals_report.py <out folder>

It reads files only, and needs Curio's code for the benchmark, as the CI image
holds it.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import statistics
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
#: Each model's floor per skill, the lowest pass rate with the skill a skill measured whole may have.
FLOORS = HERE / "skill_eval_floors.json"
#: List prices per million tokens of the models that have one.
PRICES = HERE / "skill_eval_prices.json"
#: The page, the job summary and the summaries' folder, under the out folder.
PAGE = "curio-skill-evals-report.html"
SUMMARY = "summary.md"
SUMMARIES = "summaries"
#: The record each run writes last (``skill_eval_runner.RECORD``).
RECORD = "run.json"
#: A grade run's kind (``skill_evals.GRADE``), and the scope of a run of the
#: graders alone (``ci_skill_eval_scope.py``'s ``graders``).
GRADE = "grade"
GRADERS_SCOPE = "graders"
#: How many failed assertions the job summary lists; the page lists all.
SUMMARY_FAILURES = 15


def slug(model: str) -> str:
    """A model's name as a folder or artifact name holds it: ``openai/Qwen/Qwen3.8-27B`` is ``openai-Qwen-Qwen3.8-27B``."""
    return re.sub(r"[^A-Za-z0-9._-]+", "-", model).strip("-") or "model"


def _json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _mean(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


@dataclass
class SkillRow:
    """What one model's run measured of one skill."""

    skill: str
    measure: dict
    with_rate: float | None = None
    with_runs: int = 0
    without_rate: float | None = None
    without_runs: int = 0
    used: int = 0
    triggers: dict | None = None
    errors: int = 0
    runs: int = 0
    turns: Counter = field(default_factory=Counter)
    fallbacks: int = 0
    model_calls: int = 0
    cut_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    seconds: float = 0.0
    failures: list = field(default_factory=list)
    error_paths: list = field(default_factory=list)
    previous: dict | None = None
    floor: float | None = None

    @property
    def delta(self) -> float | None:
        if self.with_rate is None or self.without_rate is None:
            return None
        return self.with_rate - self.without_rate

    @property
    def whole(self) -> bool:
        """Measured as a floor reads it: every test case, 3 runs, both ways."""
        measure = self.measure or {}
        return ("task" in (measure.get("kinds") or []) and (measure.get("runs") or 0) >= 3
                and set(measure.get("conditions") or []) == {"with_skill", "without_skill"}
                and measure.get("cases") is None)

    @property
    def under_floor(self) -> bool:
        return self.whole and self.floor is not None and self.with_rate is not None and self.with_rate < self.floor


@dataclass
class ModelRun:
    """One model's run folder, read."""

    model: str
    folder: Path | None
    meta: dict = field(default_factory=dict)
    rows: list[SkillRow] = field(default_factory=list)
    probe: dict | None = None
    exit_code: int | None = None
    price: dict | None = None
    #: Its run scored as the skills benchmark scores it (``benchmark.json``), and
    #: its comparison with main's last run of the same model.
    scored: dict | None = None
    compared: dict | None = None

    @property
    def as_grader(self) -> dict:
        """How it graded the grader truth's answers, from its grade runs (``benchmark.agreement``)."""
        found = (self.scored or {}).get("as_grader")
        return found if isinstance(found, dict) else {}

    @property
    def runs(self) -> int:
        return sum(row.runs for row in self.rows) + int(self.as_grader.get("answers") or 0)

    @property
    def errors(self) -> int:
        return sum(row.errors for row in self.rows)

    @property
    def input_tokens(self) -> int:
        return sum(row.input_tokens for row in self.rows) + int(self.as_grader.get("input_tokens") or 0)

    @property
    def output_tokens(self) -> int:
        return sum(row.output_tokens for row in self.rows) + int(self.as_grader.get("output_tokens") or 0)

    @property
    def dollars(self) -> float | None:
        if not self.price:
            return None
        return (self.input_tokens * float(self.price["input"]) + self.output_tokens * float(self.price["output"])) / 1e6


def run_folder(model_folder: Path) -> Path | None:
    """The newest run folder (``skills-*`` holding a ``run.json``) in a model's folder."""
    found = sorted(path.parent for path in model_folder.glob(f"skills-*/{RECORD}"))
    return found[-1] if found else None


def _protocols(transcript) -> tuple[list[str], bool]:
    """The tool protocol of each agent turn of a run's transcript, and whether
    one fell back to fenced blocks after its endpoint refused native tools."""
    found, fell_back = [], False
    for entry in transcript or []:
        if not isinstance(entry, dict) or entry.get("role") != "agent":
            continue
        execution = entry.get("execution") if isinstance(entry.get("execution"), dict) else {}
        pins = execution.get("pins") if isinstance(execution.get("pins"), dict) else {}
        found.append(str(pins.get("toolProtocol") or "none"))
        fell_back = fell_back or bool(pins.get("nativeToolsRefused"))
    return found, fell_back


def _add_record(row: SkillRow, record: dict, path: str, transcript) -> None:
    row.runs += 1
    if record.get("error"):
        row.errors += 1
        row.error_paths.append(f"{path}: {str(record['error'])[:200]}")
    protocols, fell_back = _protocols(transcript)
    row.turns.update(protocols)
    row.fallbacks += fell_back
    calls = [call for call in record.get("modelCalls") or [] if isinstance(call, dict)]
    row.model_calls += len(calls)
    row.cut_calls += sum(1 for call in calls if call.get("cut"))
    timing = record.get("timing") if isinstance(record.get("timing"), dict) else {}
    grading = record.get("grading") if isinstance(record.get("grading"), dict) else {}
    grader = grading.get("grader") if isinstance(grading.get("grader"), dict) else {}
    row.input_tokens += int(timing.get("input_tokens") or 0) + int(grader.get("inputTokens") or 0)
    row.output_tokens += int(timing.get("output_tokens") or 0) + int(grader.get("outputTokens") or 0)
    row.seconds += float(record.get("seconds") or 0)
    for result in grading.get("assertion_results") or []:
        if isinstance(result, dict) and result.get("passed") is not True:
            row.failures.append({
                "case": record.get("case"), "condition": record.get("condition"), "run": record.get("run"),
                "assertion": str(result.get("text") or ""), "evidence": str(result.get("evidence") or "")[:400],
                "path": path,
            })


def read_model(model: str, folder: Path | None, *, floors: dict, previous: dict | None,
               price: dict | None) -> ModelRun:
    """*model*'s run folder, read: each skill its run measured, as a :class:`SkillRow`."""
    found = ModelRun(model=model, folder=folder, price=price)
    if folder is None:
        return found
    summary = _json(folder / "summary.json") or {}
    found.meta = {**(_json(folder / RECORD) or {}), "finished": summary.get("finished")}
    measures = found.meta.get("measures") or {}
    rows: dict[str, SkillRow] = {}
    for entry in summary.get("skills") or []:
        name = entry.get("skill")
        if not name:
            continue
        default = {"kinds": found.meta.get("kinds") or [], "runs": found.meta.get("runs"),
                   "conditions": ["with_skill", "without_skill"], "cases": None}
        row = SkillRow(skill=name, measure=measures.get(name) or default)
        kinds = set(row.measure.get("kinds") or [])
        if kinds and not {"trigger", "task"} & kinds:
            # Only its grader truth was graded: the graders' table holds that.
            continue
        bench = entry.get("benchmark") or {}
        with_skill, without = bench.get("with_skill") or {}, bench.get("without_skill") or {}
        row.with_rate = (with_skill.get("pass_rate") or {}).get("mean")
        row.with_runs = int(with_skill.get("runs") or 0)
        row.without_rate = (without.get("pass_rate") or {}).get("mean")
        row.without_runs = int(without.get("runs") or 0)
        row.used = int((with_skill.get("used") or {}).get("runs") or 0)
        triggers = entry.get("triggers")
        row.triggers = triggers if triggers and triggers.get("runs") else None
        row.floor = (floors.get(model) or {}).get(name)
        row.previous = ((previous or {}).get("skills") or {}).get(name)
        rows[name] = row
    for path in sorted(folder.glob(f"*/**/{RECORD}")):
        record = _json(path)
        if not isinstance(record, dict) or not record.get("kind") or record.get("skill") not in rows:
            continue
        if record.get("kind") == GRADE:
            # A grade of a prepared answer, no run of the skill: the graders' table counts it.
            continue
        relative = path.parent.relative_to(folder.parent.parent).as_posix()
        _add_record(rows[record["skill"]], record, relative, _json(path.with_name("transcript.json")))
    found.rows = [rows[name] for name in sorted(rows)]
    return found


#: What a comparison with main's last run says of each skill: its key, its label.
COMPARED = (("success", "success"), ("trigger_recall", "should trigger"), ("false_triggers", "should not"))


def gate(models: list[ModelRun]) -> list[str]:
    """What fails the run, one line each: a model that did not answer its
    probe, a runner that failed, runs left in an error after the runner's
    retries, and a skill shown worse than main's last run, by the 95%
    interval of the paired difference (``benchmark.compare``). A floor only
    informs: a skill's share passed with the skill swings by more than 15
    points between two runs of a few cases, where the paired interval
    tells noise from a change (the owner's call, 11-05)."""
    problems = []
    for run in models:
        if run.probe is not None and not run.probe.get("ok"):
            problems.append(f"{run.model} did not answer its probe: {run.probe.get('error') or 'no answer'}")
            continue
        if run.folder is None:
            problems.append(f"{run.model} wrote no run folder")
            continue
        if run.exit_code not in (None, 0):
            problems.append(f"{run.model}'s runner ended with {run.exit_code}: see its lines in the job's log")
        if run.errors:
            paths = [path for row in run.rows for path in row.error_paths]
            problems.append(f"{run.model}: {run.errors} run(s) left in an error after the runner's retries, "
                            f"such as {'; '.join(paths[:3])}")
        compared = run.compared or {}
        for name, items in sorted((compared.get("skills") or {}).items()):
            worse = [f"{label} {_signed(items[key])}" for key, label in COMPARED
                     if (items.get(key) or {}).get("verdict") == "worse"]
            if worse:
                problems.append(f"{run.model}: {name} is shown worse than main's last run: "
                                + "; ".join(worse) + " points")
    return problems


def summary_of(run: ModelRun) -> dict:
    """*run*'s numbers, as the next runs compare with them (``--previous``)."""
    return {
        "model": run.model, "run": run.meta.get("run"), "commit": run.meta.get("commit"),
        "finished": run.meta.get("finished"),
        "skills": {row.skill: {
            "with_skill": row.with_rate, "without_skill": row.without_rate, "whole": row.whole,
            "should_trigger": (row.triggers or {}).get("should_trigger_rate"),
            "should_not_trigger": (row.triggers or {}).get("should_not_trigger_rate"),
        } for row in run.rows},
        "benchmark": run.scored,
    }


# --- The benchmark --------------------------------------------------------------------


def scored_of(run: ModelRun) -> dict | None:
    """*run*'s benchmark: the ``benchmark.json`` its runner wrote, or its
    records scored now (``agents/evaluation/benchmark.py``)."""
    if run.folder is None:
        return None
    found = _json(run.folder / "benchmark.json")
    if isinstance(found, dict) and found.get("cases") is not None:
        return found
    from utk_curio.backend.app.agents.evaluation import benchmark

    return benchmark.score(run.folder)


def compared_of(run: ModelRun, before: dict | None) -> dict | None:
    """*run*'s benchmark against main's last one of its model, case by
    case; ``refused`` says why they do not compare (another set, another model)."""
    if not run.scored or not isinstance(before, dict) or not isinstance(before.get("benchmark"), dict):
        return None
    from utk_curio.backend.app.agents.evaluation import benchmark

    try:
        return benchmark.compare(before["benchmark"], run.scored)
    except benchmark.CompareRefused as exc:
        return {"refused": str(exc)}


#: Below this share of a skill's assertions passed with it, a model fails the skill.
FAILS_UNDER = 0.5


def _with_interval(found: dict | None) -> str:
    if not found or found.get("value") is None:
        return ""
    low_high = found.get("interval")
    span = f" [{low_high[0] * 100:.0f}, {low_high[1] * 100:.0f}]" if low_high else ""
    return f"{found['value'] * 100:.0f}%{span}"


def _signed(found: dict | None) -> str:
    if not found or found.get("value") is None:
        return ""
    low_high = found.get("interval")
    span = f" [{low_high[0] * 100:+.0f}, {low_high[1] * 100:+.0f}]" if low_high else ""
    return f"{found['value'] * 100:+.0f}{span}"


def _per_run_cost(run: ModelRun) -> str:
    if run.dollars is None or not run.runs:
        return ""
    return f"${run.dollars / run.runs:.4f}"


#: The leaderboard's columns: heading, value.
LEADERBOARD = (
    ("Model", lambda run: run.model),
    ("Success", lambda run: _with_interval(run.scored["overall"]["success"])),
    ("All pass", lambda run: _with_interval(run.scored["overall"]["all_pass"])),
    ("Lift", lambda run: _signed(run.scored["overall"]["lift"])),
    ("Reach", lambda run: _with_interval(run.scored["overall"]["reach"])),
    ("Should trigger", lambda run: _with_interval(run.scored["overall"]["trigger_recall"])),
    ("Should not", lambda run: _with_interval(run.scored["overall"]["false_triggers"])),
    ("Errors", lambda run: _with_interval(run.scored["overall"]["errors"])),
    ("Cut calls", lambda run: _with_interval(run.scored["overall"]["cut_calls"])),
    ("Refused calls", lambda run: _with_interval(run.scored["overall"]["refused_calls"])),
    ("Native turns", lambda run: _with_interval(run.scored["overall"]["native_turns"])),
    ("Cost a run", _per_run_cost),
    ("Grader vs checks", lambda run: str(len(run.scored.get("disagreements") or []))),
)


def leaderboard(models: list[ModelRun]) -> list[ModelRun]:
    """The models a benchmark scored a case or a query of, the best success with the skill first."""
    scored = [run for run in models if run.scored and (run.scored.get("cases") or run.scored.get("queries"))]
    return sorted(scored, key=lambda run: -(run.scored["overall"]["success"].get("value") or 0))


#: The graders' table's columns: heading, value. A grader's agreement is
#: counted apart on the assertions checks decide, where no grade reaches a score.
GRADERS = (
    ("Grader", lambda run: run.model),
    ("Answers", lambda run: str(run.as_grader.get("answers") or 0)),
    ("Errors", lambda run: str(run.as_grader.get("errors") or 0)),
    ("Agreement, unchecked", lambda run: _share_of(run.as_grader["unchecked"]["agreement"])),
    ("False passes, unchecked", lambda run: _share_of(run.as_grader["unchecked"]["false_passes"])),
    ("False fails, unchecked", lambda run: _share_of(run.as_grader["unchecked"]["false_fails"])),
    ("Agreement, checked", lambda run: _share_of(run.as_grader["checked"]["agreement"])),
    ("Usable", lambda run: "yes" if run.as_grader.get("usable") else f"no, under {run.as_grader['floor']:.0%}"),
)


def _share_of(found: dict | None) -> str:
    if not found or found.get("value") is None:
        return ""
    return f"{found['value']:.0%} ({found.get('count', 0)} of {found.get('of', 0)})"


def graders(models: list[ModelRun]) -> list[ModelRun]:
    """The models that graded the grader truth, the best agreement on unchecked assertions first."""
    found = [run for run in models if run.as_grader.get("answers")]
    return sorted(found, key=lambda run: -((run.as_grader.get("unchecked") or {}).get("agreement") or {}).get(
        "value", 0) or 0)


def _graders_lines(models: list[ModelRun]) -> list[str]:
    """The graders' table in the job summary, and the grader the benchmark would use."""
    board = graders(models)
    if not board:
        return []
    lines = ["", "### Graders", "",
             f"Each model graded the grader truth's prepared answers. One whose verdicts on the assertions no "
             f"check decides agree with the truth at least {board[0].as_grader['floor']:.0%} of the time can be "
             "the benchmark's grader.", "",
             "| " + " | ".join(name for name, _ in GRADERS) + " |", "|" + "---|" * len(GRADERS)]
    lines += ["| " + " | ".join(value(run) for _, value in GRADERS) + " |" for run in board]
    usable = [run.model for run in board if run.as_grader.get("usable")]
    lines += ["", f"Best usable grader: `{usable[0]}`." if usable else "No model is a usable grader."]
    return lines


def per_skill(models: list[ModelRun]) -> list[tuple[str, dict[str, dict], list[str]]]:
    """Each skill any model measured: its success per model, and the models it fails on."""
    names = sorted({name for run in models if run.scored for name in run.scored["skills"]})
    rows = []
    for name in names:
        found = {run.model: run.scored["skills"][name] for run in models if run.scored and name in run.scored["skills"]}
        fails = [model for model, metrics in found.items()
                 if metrics["success"].get("value") is not None and metrics["success"]["value"] < FAILS_UNDER]
        rows.append((name, found, fails))
    return rows


def _compare_lines(run: ModelRun) -> list[str]:
    """What *run*'s comparison with main's last run says, a line each."""
    found = run.compared
    if not found:
        return []
    if found.get("refused"):
        return [f"No comparison with main's last run: {found['refused']}."]
    lines = [f"Against main's last run ({found.get('a')}), every case both measured: "
             f"{found['overall']['success']['verdict']}, {_signed(found['overall']['success'])} points."]
    for name, items in sorted((found.get("skills") or {}).items()):
        moved = [f"{label} {items[key]['verdict']} ({_signed(items[key])})" for key, label in COMPARED
                 if items.get(key) and items[key]["verdict"] != "not shown different"]
        if moved:
            lines.append(f"{name}: " + "; ".join(moved) + ".")
    if len(lines) == 1:
        lines.append("No skill is shown different.")
    return lines


# --- Writing --------------------------------------------------------------------------


def _pct(value) -> str:
    return "" if value is None else f"{value * 100:.0f}%"


def _points(value) -> str:
    return "" if value is None else f"{value * 100:+.0f}"


def _change(row: SkillRow) -> str:
    before = (row.previous or {}).get("with_skill")
    if before is None or row.with_rate is None:
        return ""
    return _points(row.with_rate - before)


def _turns(row: SkillRow) -> str:
    total = sum(row.turns.values())
    if not total:
        return ""
    return f"{row.turns.get('native', 0)} of {total}" + (f", {row.fallbacks} fell back" if row.fallbacks else "")


def _measured(row: SkillRow) -> str:
    measure = row.measure or {}
    kinds = measure.get("kinds") or []
    parts = []
    if "trigger" in kinds:
        parts.append("triggers")
    if "task" in kinds:
        cases = "first case" if measure.get("cases") == 1 else (
            f"{measure['cases']} cases" if measure.get("cases") else "cases")
        ways = "both ways" if len(measure.get("conditions") or []) == 2 else "with the skill"
        parts.append(f"{cases} x{measure.get('runs')} {ways}")
    return ", ".join(parts)


def _cost(run: ModelRun) -> str:
    return "" if run.dollars is None else f"${run.dollars:.2f}"


#: The per-skill table's columns: heading, value.
COLUMNS = (
    ("Skill", lambda row: row.skill),
    ("Measured", _measured),
    ("With skill", lambda row: _pct(row.with_rate)),
    ("Without", lambda row: _pct(row.without_rate)),
    ("Delta", lambda row: _points(row.delta)),
    ("Since main", _change),
    ("Floor", lambda row: _pct(row.floor) + (" (under)" if row.under_floor else "")),
    ("Reached", lambda row: f"{row.used} of {row.with_runs}" if row.with_runs else ""),
    ("Should trigger", lambda row: _pct((row.triggers or {}).get("should_trigger_rate"))),
    ("Should not", lambda row: _pct((row.triggers or {}).get("should_not_trigger_rate"))),
    ("Native turns", _turns),
    ("Cut calls", lambda row: f"{row.cut_calls} of {row.model_calls}" if row.model_calls else ""),
    ("Errors", lambda row: str(row.errors)),
    ("Tokens", lambda row: f"{(row.input_tokens + row.output_tokens) / 1000:,.0f}k"),
    ("Minutes", lambda row: f"{row.seconds / 60:.1f}"),
)


def _probe(run: ModelRun) -> str:
    if run.probe is None:
        return ""
    if run.probe.get("ok"):
        return f"answered in {run.probe.get('seconds', 0):.1f} s"
    return f"failed: {run.probe.get('error') or 'no answer'}"


def markdown(models: list[ModelRun], problems: list[str], *, scope: dict, page_url: str | None) -> str:
    """The job summary: the verdict, then per model its totals and its skills."""
    lines = ["## Skill evaluations", ""]
    lines.append(f"What this run measured: **{scope.get('measure', '?')}**. " + " ".join(
        f"{line}." for line in (scope.get("why") or [])[:6]))
    lines.append("")
    if page_url:
        lines += [f"[Open {PAGE}]({page_url}): every model, skill and failed assertion.", ""]
    if problems:
        lines += ["**Failed:**", ""] + [f"- {problem}" for problem in problems] + [""]
    else:
        lines += [("**Passed:** every model answered, no run was left in an error, and no skill is shown worse "
                   "than main's last run."), ""]
    lines += ["| Model | Probe | Runs | Errors | Tokens | Cost |", "|---|---|---|---|---|---|"]
    for run in models:
        lines.append(f"| `{run.model}` | {_probe(run)} | {run.runs} | {run.errors} | "
                     f"{(run.input_tokens + run.output_tokens) / 1e6:.2f}M | {_cost(run)} |")
    board = leaderboard(models)
    if board:
        version = board[0].scored.get("version")
        lines += ["", f"### Benchmark, version {version}", "",
                  "| " + " | ".join(name for name, _ in LEADERBOARD) + " |", "|" + "---|" * len(LEADERBOARD)]
        lines += ["| " + " | ".join(value(run) for _, value in LEADERBOARD) + " |" for run in board]
        for run in board:
            said = _compare_lines(run)
            if said:
                lines += ["", f"`{run.model}`: " + " ".join(said)]
    lines += _graders_lines(models)
    for run in models:
        if not run.rows:
            continue
        lines += ["", f"### `{run.model}`", "", "| " + " | ".join(name for name, _ in COLUMNS) + " |",
                  "|" + "---|" * len(COLUMNS)]
        for row in run.rows:
            lines.append("| " + " | ".join(value(row) for _, value in COLUMNS) + " |")
    failures = [(run.model, row.skill, failure) for run in models for row in run.rows for failure in row.failures]
    if failures:
        lines += ["", f"### Failed assertions ({len(failures)})", ""]
        for model, skill, failure in failures[:SUMMARY_FAILURES]:
            lines.append(f"- `{model}` {skill} case {failure['case']}, {failure['condition']} run "
                         f"{failure['run']}: {failure['assertion']}")
        if len(failures) > SUMMARY_FAILURES:
            lines.append(f"- and {len(failures) - SUMMARY_FAILURES} more on the page")
    return "\n".join(lines) + "\n"


_STYLE = """
:root { --ink: #1d232b; --muted: #5d6875; --line: #d9dee4; --bad: #a3261b; --good: #1f6b3a; --bg: #ffffff;
        --head: #f3f5f7; }
@media (prefers-color-scheme: dark) {
  :root { --ink: #e6e9ed; --muted: #a2adb9; --line: #38414b; --bad: #f0857a; --good: #7fd19b; --bg: #161a1f;
          --head: #20262d; }
}
body { font: 14px/1.45 system-ui, sans-serif; color: var(--ink); background: var(--bg); margin: 0; padding: 16px;
       max-width: 1400px; }
h1 { font-size: 20px; } h2 { font-size: 17px; margin-top: 28px; } h3 { font-size: 15px; }
.muted { color: var(--muted); } .bad { color: var(--bad); } .good { color: var(--good); }
.wrap { overflow-x: auto; }
table { border-collapse: collapse; margin: 8px 0 16px; }
th, td { border-bottom: 1px solid var(--line); padding: 4px 8px; text-align: left; white-space: nowrap; }
th { background: var(--head); font-weight: 600; }
td.num { text-align: right; font-variant-numeric: tabular-nums; }
details { margin: 4px 0; } summary { cursor: pointer; }
code { font-size: 13px; }
li { margin: 3px 0; }
"""


def _cell(text: str, numeric: bool) -> str:
    return f'<td class="num">{html.escape(text)}</td>' if numeric else f"<td>{html.escape(text)}</td>"


def _benchmark_html(models: list[ModelRun]) -> list[str]:
    """The benchmark's part of the page: the leaderboard, the comparisons with
    main's last run, and each skill's success per model."""
    escape = html.escape
    board = leaderboard(models)
    if not board:
        return []
    parts = [f"<h2>Benchmark, version {escape(str(board[0].scored.get('version')))}</h2>",
             '<p class="muted">Success: the share of a case\'s assertions passed with the skill, averaged over its '
             "runs, then over the cases; a checked assertion's result comes from its checks, every other one from "
             "its grader. Each rate shows its 95% interval, bootstrapped over cases and runs.</p>",
             '<div class="wrap"><table><tr>' + "".join(f"<th>{escape(name)}</th>" for name, _ in LEADERBOARD)
             + "</tr>"]
    parts += ["<tr>" + "".join(_cell(value(run), name != "Model") for name, value in LEADERBOARD) + "</tr>"
              for run in board]
    parts.append("</table></div>")
    for run in board:
        said = _compare_lines(run)
        if said:
            parts.append(f"<p><code>{escape(run.model)}</code>: " + " ".join(escape(line) for line in said) + "</p>")
    rows = per_skill(models)
    if rows:
        heads = [run.model for run in board]
        parts.append("<h3>Each skill's success per model</h3>"
                     '<div class="wrap"><table><tr><th>Skill</th>' + "".join(f"<th>{escape(model)}</th>" for model in heads)
                     + f"<th>Fails on (under {FAILS_UNDER:.0%})</th></tr>")
        for name, found, fails in rows:
            cells = [_cell(name, False)]
            for model in heads:
                metrics = found.get(model)
                text = "" if metrics is None else _with_interval(metrics["success"])
                lift = _signed((metrics or {}).get("lift"))
                cells.append(_cell(f"{text} (lift {lift})" if lift else text, True))
            cells.append(_cell(", ".join(fails), False))
            parts.append("<tr>" + "".join(cells) + "</tr>")
        parts.append("</table></div>")
    return parts


def page(models: list[ModelRun], problems: list[str], *, scope: dict, run_url: str | None,
         results_name: str) -> str:
    """The report page, self-contained."""
    escape = html.escape
    commit = next((run.meta.get("commit") for run in models if run.meta.get("commit")), None)
    parts = ["<!doctype html>", '<html lang="en"><head><meta charset="utf-8">',
             '<meta name="viewport" content="width=device-width, initial-scale=1">',
             "<title>Skill evaluations</title>", f"<style>{_STYLE}</style></head><body>",
             "<h1>Skill evaluations</h1>",
             f'<p class="muted">Commit {escape(commit or "unknown")}. '
             + (f'<a href="{escape(run_url)}">The CI run</a>. ' if run_url else "")
             + f"Each run's transcript and grade are in the run's <code>{escape(results_name)}</code> artifact, "
               "at the path each failed assertion names.</p>",
             f"<p>What this run measured: <b>{escape(str(scope.get('measure', '?')))}</b>.</p><ul>"]
    parts += [f"<li>{escape(line)}</li>" for line in scope.get("why") or []]
    parts.append("</ul>")
    if problems:
        parts.append('<h2 class="bad">Failed</h2><ul>')
        parts += [f'<li class="bad">{escape(problem)}</li>' for problem in problems]
        parts.append("</ul>")
    else:
        parts.append('<p class="good">Passed: every model answered, no run was left in an error, '
                     "and no skill is shown worse than main's last run.</p>")
    parts.append('<h2>Models</h2><div class="wrap"><table><tr><th>Model</th><th>Probe</th><th>Skills</th>'
                 "<th>Runs</th><th>Errors</th><th>Input tokens</th><th>Output tokens</th><th>Cost at list price</th>"
                 "</tr>")
    for run in models:
        parts.append("<tr>" + "".join([
            _cell(run.model, False), _cell(_probe(run), False), _cell(str(len(run.rows)), True),
            _cell(str(run.runs), True), _cell(str(run.errors), True), _cell(f"{run.input_tokens:,}", True),
            _cell(f"{run.output_tokens:,}", True), _cell(_cost(run) or "not priced", True),
        ]) + "</tr>")
    parts.append("</table></div>")
    parts += _benchmark_html(models)
    board = graders(models)
    if board:
        parts.append("<h2>Graders</h2>"
                     f'<p class="muted">Each model graded the grader truth\'s prepared answers: a golden answer '
                     "meets every assertion of its case, and a mutant fails exactly the ones it names. One whose "
                     "verdicts on the assertions no check decides agree with the truth at least "
                     f"{board[0].as_grader['floor']:.0%} of the time can be the benchmark's grader.</p>"
                     '<div class="wrap"><table><tr>' + "".join(f"<th>{escape(name)}</th>" for name, _ in GRADERS)
                     + "</tr>")
        parts += ["<tr>" + "".join(_cell(value(run), name != "Grader") for name, value in GRADERS) + "</tr>"
                  for run in board]
        parts.append("</table></div>")
    numeric = {name for name, _ in COLUMNS} - {"Skill", "Measured", "Floor", "Reached", "Native turns", "Cut calls"}
    for run in models:
        parts.append(f"<h2><code>{escape(run.model)}</code></h2>")
        if not run.rows:
            said = ("It graded the grader truth's answers, in Graders above" if run.as_grader.get("answers")
                    else f"Nothing measured: {_probe(run) or 'no run folder'}")
            parts.append(f'<p class="muted">{escape(said)}.</p>')
            continue
        parts.append('<div class="wrap"><table><tr>' + "".join(f"<th>{escape(name)}</th>" for name, _ in COLUMNS)
                     + "</tr>")
        for row in run.rows:
            parts.append("<tr>" + "".join(_cell(value(row), name in numeric) for name, value in COLUMNS) + "</tr>")
        parts.append("</table></div>")
        for row in run.rows:
            if not row.failures and not row.error_paths:
                continue
            parts.append(f"<details><summary>{escape(row.skill)}: {len(row.failures)} failed assertion(s), "
                         f"{len(row.error_paths)} error(s)</summary><ul>")
            for failure in row.failures:
                parts.append(f"<li>Case {escape(str(failure['case']))}, {escape(str(failure['condition']))} run "
                             f"{escape(str(failure['run']))}: {escape(failure['assertion'])}"
                             f'<br><span class="muted">{escape(failure["evidence"])}</span>'
                             f"<br><code>{escape(failure['path'])}/transcript.json</code></li>")
            for error in row.error_paths:
                parts.append(f'<li class="bad"><code>{escape(error)}</code></li>')
            parts.append("</ul></details>")
    parts.append('<p class="muted">Pass rates are the share of a test case\'s assertions its grader passed, '
                 "averaged over the runs. Native turns: agent turns that called tools natively, of all turns. "
                 "Cut calls: model calls the output cap cut, of all calls. Cost: tokens at the list prices of "
                 "scripts/skill_eval_prices.json, the grader's among them.</p></body></html>")
    return "\n".join(parts) + "\n"


def load_config(path: Path, key: str) -> dict:
    data = _json(path) or {}
    value = data.get(key)
    return value if isinstance(value, dict) else {}


def build(out: Path, models: list[str], *, scope: dict, probes: dict | None = None, exits: dict | None = None,
          previous: Path | None = None, floors: Path = FLOORS, prices: Path = PRICES,
          run_url: str | None = None, page_url: str | None = None, results_name: str = "skill-evals-results",
          ) -> tuple[list[ModelRun], list[str]]:
    """Read every model's folder under ``out/results/``, write the page, the
    summary and the summaries under *out*, and return the models read and
    what fails the run."""
    floor_table, price_table = load_config(floors, "floors"), load_config(prices, "prices")
    runs = []
    for model in models:
        before = _json(previous / f"{slug(model)}.json") if previous else None
        run = read_model(model, run_folder(out / "results" / slug(model)), floors=floor_table,
                         previous=before if isinstance(before, dict) else None, price=price_table.get(model))
        run.probe = (probes or {}).get(model)
        run.exit_code = (exits or {}).get(model)
        run.scored = scored_of(run)
        run.compared = compared_of(run, before if isinstance(before, dict) else None)
        runs.append(run)
    problems = gate(runs)
    (out / PAGE).write_text(page(runs, problems, scope=scope, run_url=run_url, results_name=results_name),
                            encoding="utf-8")
    (out / SUMMARY).write_text(markdown(runs, problems, scope=scope, page_url=page_url), encoding="utf-8")
    (out / SUMMARIES).mkdir(parents=True, exist_ok=True)
    for run in runs:
        # A run of the graders measured no skill, so later runs do not compare with it.
        if run.folder is not None and scope.get("measure") != GRADERS_SCOPE:
            (out / SUMMARIES / f"{slug(run.model)}.json").write_text(
                json.dumps(summary_of(run), indent=2) + "\n", encoding="utf-8")
    return runs, problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("out", type=Path, help="the out folder ci_skill_evals.py run wrote")
    parser.add_argument("--models", default="", help="comma-separated; default: every folder under results/")
    parser.add_argument("--previous", type=Path, default=None)
    args = parser.parse_args(argv)
    names = [name for name in args.models.split(",") if name] or [
        (_json(folder / RECORD) or {}).get("model") or path.name
        for path in sorted((args.out / "results").iterdir()) if path.is_dir()
        for folder in [run_folder(path) or path]]
    scope = _json(args.out / "scope.json") or {}
    _, problems = build(args.out, names, scope=scope, previous=args.previous)
    print((args.out / SUMMARY).read_text(encoding="utf-8"))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
