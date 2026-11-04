"""The skills benchmark: one fixed, versioned set, scored the same way for every model.

The set is every skill's ``evals/evals.json`` (its test cases and trigger
queries) with the grader's words (``skill-evals.md``). Its **version** is a hash
of those files (:func:`version`): numbers compare only within one version.

:func:`score` reads one model's run folder (``agent_eval.py skills``) and
gives, per skill and over every case:

- **success**: the share of a case's assertions passed with the skill, as the
  mean over cases of the mean over its runs; **all_pass**, the share of its
  runs that passed every assertion; **without**, success without the skill;
- **lift**: success with the skill minus without, paired by case;
- **reach**: the share of runs with the skill that the skill reached;
- **trigger_recall** and **false_triggers**: the mean trigger rate of the
  queries that should load the skill and of those that should not;
- reliability, counted from each run's record: **errors** (runs left in an
  error, of all runs), **cut_calls** and **refused_calls** (model calls the
  output cap cut, and tool calls Curio refused, of all calls), and
  **native_turns** (agent turns on native tools, of all turns);
- cost: tokens and seconds a run, and dollars a run where a price is given.

Each rate carries how many cases (or queries) and runs it stands on, and a 95%
interval bootstrapped over the cases and, within each, over its runs
(:func:`interval`). A checked assertion's result comes from its checks
(``checks.py``), which are exact; every other one is its grader's, and where a
check and the grader differ the run is listed in ``disagreements``.

:func:`compare` pairs the cases of two runs of one version and one model and
says, per skill and overall, whether the second is better, worse or not shown
different: the verdict rests on the interval of the paired difference.
"""

from __future__ import annotations

import hashlib
import json
import random
import statistics
from collections.abc import Iterable, Mapping
from pathlib import Path

from utk_curio import shipped
from utk_curio.backend.app.agents.evaluation import checks as case_checks
from utk_curio.backend.app.agents.evaluation import skill_evals

#: The shape of ``benchmark.json``, which a later change to it moves.
FORMAT = 1
#: The grader's words, part of the set (the base entry's page).
GRADER_WORDS = ("agents", "agent.curio.builtin@1", "skill-evals.md")
#: How many characters of the set's hash its version keeps.
VERSION_CHARS = 12
#: The intervals: their confidence, how many resamples, and the seed, so a
#: number is the same each time it is scored.
CONFIDENCE = 0.95
RESAMPLES = 2000
SEED = 20261104
#: What a run writes last (``skill_eval_runner.RECORD``).
RECORD = "run.json"
#: The verdicts of a comparison.
BETTER, WORSE, SAME = "better", "worse", "not shown different"


def version(evals: Iterable[skill_evals.SkillEvals]) -> str:
    """The set's version: a hash of every skill's ``evals/evals.json`` and of
    the grader's words, the same for the same files wherever they are."""
    digest = hashlib.sha256()
    words = shipped.path(GRADER_WORDS[0]).joinpath(*GRADER_WORDS[1:])
    digest.update(words.read_bytes() if words.is_file() else b"")
    for skill in sorted(evals, key=lambda found: found.name):
        digest.update(b"\0" + skill.name.encode("utf-8") + b"\0" + skill.file.read_bytes())
    return digest.hexdigest()[:VERSION_CHARS]


# --- Intervals ------------------------------------------------------------------------


def _mean(values) -> float | None:
    values = list(values)
    return statistics.fmean(values) if values else None


def interval(groups: list[list[float]], *, seed: int = SEED) -> list[float] | None:
    """The 95% interval of the mean over *groups* (cases, each its runs' values)
    of each group's mean, resampling the groups and, within each, its runs."""
    groups = [list(group) for group in groups if group]
    if not groups:
        return None
    rng = random.Random(seed)
    means = []
    for _ in range(RESAMPLES):
        picked = [groups[rng.randrange(len(groups))] for _ in groups]
        means.append(statistics.fmean(statistics.fmean(rng.choice(group) for _ in group) for group in picked))
    return _percentiles(means)


def paired_interval(pairs: list[tuple[list[float], list[float]]], *, seed: int = SEED) -> list[float] | None:
    """The 95% interval of the mean over *pairs* (cases, each its runs' values in
    the first condition and in the second) of the second's mean minus the first's."""
    pairs = [(list(first), list(second)) for first, second in pairs if first and second]
    if not pairs:
        return None
    rng = random.Random(seed)
    means = []
    for _ in range(RESAMPLES):
        picked = [pairs[rng.randrange(len(pairs))] for _ in pairs]
        means.append(statistics.fmean(
            statistics.fmean(rng.choice(second) for _ in second) - statistics.fmean(rng.choice(first) for _ in first)
            for first, second in picked))
    return _percentiles(means)


def _percentiles(values: list[float]) -> list[float]:
    values = sorted(values)
    tail = (1 - CONFIDENCE) / 2
    low = values[int(tail * (len(values) - 1))]
    high = values[int(round((1 - tail) * (len(values) - 1)))]
    return [round(low, 4), round(high, 4)]


def _rate(groups: dict, *, seed: int) -> dict:
    """A rate over *groups* (a key each, its runs' values): its value, its
    interval, how many groups and runs it stands on."""
    found = [values for values in groups.values() if values]
    value = _mean(_mean(values) for values in found)
    return {"value": None if value is None else round(value, 4), "interval": interval(found, seed=seed),
            "n": len(found), "runs": sum(len(values) for values in found)}


def _paired(first: dict, second: dict, *, seed: int) -> dict:
    """The paired difference of two conditions' groups, keyed alike: second minus first."""
    keys = [key for key in first if first[key] and second.get(key)]
    pairs = [(first[key], second[key]) for key in keys]
    value = _mean(_mean(b) - _mean(a) for a, b in pairs)
    return {"value": None if value is None else round(value, 4), "interval": paired_interval(pairs, seed=seed),
            "n": len(pairs), "runs": sum(len(a) + len(b) for a, b in pairs)}


def _share(part: int, whole: int) -> dict:
    return {"value": round(part / whole, 4) if whole else None, "count": part, "of": whole}


# --- Reading a run folder -------------------------------------------------------------


def _json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _protocols(transcript) -> list[str]:
    found = []
    for entry in transcript or []:
        if isinstance(entry, Mapping) and entry.get("role") == "agent":
            execution = entry.get("execution") if isinstance(entry.get("execution"), Mapping) else {}
            pins = execution.get("pins") if isinstance(execution.get("pins"), Mapping) else {}
            found.append(str(pins.get("toolProtocol") or "none"))
    return found


def _final(case: skill_evals.Case | None, record: Mapping, folder: Path) -> tuple[list[bool] | None, list[dict]]:
    """A graded task run's result per assertion: its checks' where they decide
    one, its grader's otherwise; and where the two differ."""
    grading = record.get("grading") if isinstance(record.get("grading"), Mapping) else {}
    results = grading.get("assertion_results")
    if record.get("error") or not isinstance(results, list) or not results:
        return None, []
    graded = [item.get("passed") is True for item in results if isinstance(item, Mapping)]
    if case is None or not case.checks:
        return graded, []
    decided = case_checks.decided(case.checks, case_checks.RunRecord.of(folder, case.context.dataflow))
    final, differ = list(graded), []
    for place, passed in decided.items():
        if place <= len(final):
            if final[place - 1] != passed:
                differ.append({"assertion": place, "grader": final[place - 1], "check": passed})
            final[place - 1] = passed
    return final, differ


def score(folder: Path, evals: Mapping[str, skill_evals.SkillEvals] | None = None, *,
          price: Mapping | None = None, seed: int = SEED) -> dict:
    """The benchmark of one model's run folder (``skills-<time>/``), as ``benchmark.json`` holds it."""
    folder = Path(folder)
    meta = _json(folder / RECORD) or {}
    if evals is None:
        evals = {found.name: found for found in skill_evals.shipped_evals()}
    cases: dict[str, dict] = {}
    queries: dict[str, dict] = {}
    disagreements: list[dict] = []
    tally = {"runs": 0, "errors": 0, "calls": 0, "cut": 0, "tools": 0, "refused": 0, "turns": 0, "native": 0,
             "input_tokens": 0, "output_tokens": 0, "seconds": 0.0, "reached": 0, "with_runs": 0}
    per_skill_tally: dict[str, dict] = {}
    for path in sorted(folder.glob(f"*/**/{RECORD}")):
        record = _json(path)
        if not isinstance(record, Mapping) or not record.get("kind") or not record.get("skill"):
            continue
        skill = str(record["skill"])
        mine = per_skill_tally.setdefault(skill, {key: 0 for key in tally})
        run_folder = path.parent
        here = run_folder.relative_to(folder).as_posix()
        calls = [call for call in record.get("modelCalls") or [] if isinstance(call, Mapping)]
        tools = _json(run_folder / "outputs" / "calls.json") or []
        protocols = _protocols(_json(run_folder / "transcript.json"))
        timing = record.get("timing") if isinstance(record.get("timing"), Mapping) else {}
        grading = record.get("grading") if isinstance(record.get("grading"), Mapping) else {}
        grader = grading.get("grader") if isinstance(grading.get("grader"), Mapping) else {}
        counts = {
            "runs": 1, "errors": int(bool(record.get("error"))), "calls": len(calls),
            "cut": sum(1 for call in calls if call.get("cut")),
            "tools": sum(1 for call in tools if isinstance(call, Mapping)),
            "refused": sum(1 for call in tools if isinstance(call, Mapping) and call.get("status") in ("refused", "error")),
            "turns": len(protocols), "native": protocols.count("native"),
            "input_tokens": int(timing.get("input_tokens") or 0) + int(grader.get("inputTokens") or 0),
            "output_tokens": int(timing.get("output_tokens") or 0) + int(grader.get("outputTokens") or 0),
            "seconds": float(record.get("seconds") or 0),
            "reached": 0, "with_runs": 0,
        }
        if record.get("kind") == skill_evals.TRIGGER:
            if not record.get("error"):
                entry = queries.setdefault(f"{skill}/q{int(record.get('query') or 0):02d}",
                                           {"skill": skill, "should_trigger": bool(record.get("should_trigger")),
                                            "runs": []})
                entry["runs"].append(1.0 if record.get("triggered") else 0.0)
        elif record.get("kind") == skill_evals.TASK:
            skill_cases = {case.id: case for case in (evals.get(skill).cases if evals.get(skill) else ())}
            case = skill_cases.get(record.get("case"))
            final, differ = _final(case, record, run_folder)
            if final is not None:
                condition = str(record.get("condition"))
                entry = cases.setdefault(f"{skill}/{record.get('case')}", {"skill": skill, "case": record.get("case")})
                entry.setdefault(condition, []).append(round(sum(final) / len(final), 4))
                entry.setdefault(f"{condition}_all", []).append(1.0 if all(final) else 0.0)
                if condition == skill_evals.WITH_SKILL:
                    counts["with_runs"] = 1
                    counts["reached"] = int(bool(record.get("used")))
                for item in differ:
                    disagreements.append({"run": here, **item})
        for key, value in counts.items():
            tally[key] += value
            mine[key] += value
    skills = sorted({entry["skill"] for entry in cases.values()} | {entry["skill"] for entry in queries.values()})
    return {
        "benchmark": FORMAT,
        "version": meta.get("benchmarkVersion") or version(evals.values()),
        "model": meta.get("model"), "grader": meta.get("grader") or meta.get("model"),
        "commit": meta.get("commit"), "run": meta.get("run"),
        "overall": _metrics(cases.values(), queries.values(), tally, price, seed=seed),
        "skills": {name: _metrics([entry for entry in cases.values() if entry["skill"] == name],
                                  [entry for entry in queries.values() if entry["skill"] == name],
                                  per_skill_tally.get(name, {}), price, seed=seed) for name in skills},
        "cases": cases, "queries": queries, "disagreements": disagreements,
    }


def _metrics(cases: Iterable[dict], queries: Iterable[dict], tally: Mapping, price: Mapping | None,
             *, seed: int) -> dict:
    cases, queries = list(cases), list(queries)
    by = {condition: {f"{entry['skill']}/{entry['case']}": entry.get(condition) or [] for entry in cases}
          for condition in (skill_evals.WITH_SKILL, skill_evals.WITHOUT_SKILL)}
    all_pass = {f"{entry['skill']}/{entry['case']}": entry.get(f"{skill_evals.WITH_SKILL}_all") or [] for entry in cases}
    runs = int(tally.get("runs") or 0)
    found = {
        "success": _rate(by[skill_evals.WITH_SKILL], seed=seed),
        "all_pass": _rate(all_pass, seed=seed),
        "without": _rate(by[skill_evals.WITHOUT_SKILL], seed=seed),
        "lift": _paired(by[skill_evals.WITHOUT_SKILL], by[skill_evals.WITH_SKILL], seed=seed),
        "reach": _share(int(tally.get("reached") or 0), int(tally.get("with_runs") or 0)),
        "trigger_recall": _rate({i: q["runs"] for i, q in enumerate(queries) if q["should_trigger"]}, seed=seed),
        "false_triggers": _rate({i: q["runs"] for i, q in enumerate(queries) if not q["should_trigger"]}, seed=seed),
        "errors": _share(int(tally.get("errors") or 0), runs),
        "cut_calls": _share(int(tally.get("cut") or 0), int(tally.get("calls") or 0)),
        "refused_calls": _share(int(tally.get("refused") or 0), int(tally.get("tools") or 0)),
        "native_turns": _share(int(tally.get("native") or 0), int(tally.get("turns") or 0)),
        "cost": {
            "runs": runs,
            "input_tokens": int(tally.get("input_tokens") or 0), "output_tokens": int(tally.get("output_tokens") or 0),
            "seconds_a_run": round(float(tally.get("seconds") or 0) / runs, 1) if runs else None,
            "dollars": None,
        },
    }
    if price and runs:
        dollars = (found["cost"]["input_tokens"] * float(price["input"])
                   + found["cost"]["output_tokens"] * float(price["output"])) / 1e6
        found["cost"]["dollars"] = round(dollars, 4)
        found["cost"]["dollars_a_run"] = round(dollars / runs, 5)
    return found


# --- Comparing two runs ---------------------------------------------------------------


class CompareRefused(ValueError):
    """Two benchmarks that cannot be compared, saying why."""


def _verdict(found: Mapping) -> str:
    low_high = found.get("interval")
    if not low_high:
        return SAME
    low, high = low_high
    return BETTER if low > 0 else WORSE if high < 0 else SAME


def compare(a: Mapping, b: Mapping, *, seed: int = SEED) -> dict:
    """Whether *b* is better than *a*, worse or not shown different, per skill
    and over every case both measured, on the success of each case with the
    skill and on the trigger rates of each query, paired. Both must be of
    one version and one model; raises :class:`CompareRefused` otherwise."""
    if a.get("version") != b.get("version"):
        raise CompareRefused(f"the two runs measured different sets: version {a.get('version')} "
                             f"and {b.get('version')}")
    if a.get("model") != b.get("model"):
        raise CompareRefused(f"the two runs measured different models: {a.get('model')} and {b.get('model')}")

    def paired_success(keys) -> dict:
        found = _paired({key: a["cases"][key].get(skill_evals.WITH_SKILL) or [] for key in keys},
                        {key: b["cases"][key].get(skill_evals.WITH_SKILL) or [] for key in keys}, seed=seed)
        return {**found, "verdict": _verdict(found)}

    def paired_queries(keys, should: bool) -> dict:
        keys = [key for key in keys if a["queries"][key]["should_trigger"] is should]
        found = _paired({key: a["queries"][key]["runs"] for key in keys},
                        {key: b["queries"][key]["runs"] for key in keys}, seed=seed)
        # Fewer false triggers is better: their verdict is read the other way.
        verdict = _verdict(found)
        if not should and verdict != SAME:
            verdict = WORSE if verdict == BETTER else BETTER
        return {**found, "verdict": verdict}

    both_cases = sorted(set(a.get("cases") or {}) & set(b.get("cases") or {}))
    both_queries = sorted(set(a.get("queries") or {}) & set(b.get("queries") or {}))
    skills = sorted({key.split("/")[0] for key in both_cases + both_queries})
    out = {"version": a.get("version"), "model": a.get("model"), "a": a.get("run"), "b": b.get("run"),
           "overall": {"success": paired_success(both_cases)}, "skills": {}}
    for name in skills:
        mine = [key for key in both_cases if key.split("/")[0] == name]
        asked = [key for key in both_queries if key.split("/")[0] == name]
        out["skills"][name] = {"success": paired_success(mine) if mine else None,
                               "trigger_recall": paired_queries(asked, True) if asked else None,
                               "false_triggers": paired_queries(asked, False) if asked else None}
    return out
