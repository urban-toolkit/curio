"""The skills benchmark: its checks, its version, its scores and their intervals, and its paired compare.

``agents/evaluation/checks.py`` decides an assertion from a run's own record,
and ``agents/evaluation/benchmark.py`` scores a model's run folder with them
and compares two scored runs. These build run records and run folders shaped
as ``skill_eval_worker.py`` writes them: each kind of check on a record that
meets it and one that does not, the metrics of a folder whose numbers are
worked out by hand, intervals, and a compare that finds a difference planted
in its samples and none between two halves of one run's samples. No model is
called.

New names are read inside each test, so this module imports on a checkout
without them and each test fails on its own.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def _checks():
    from utk_curio.backend.app.agents.evaluation import checks

    return checks


def _benchmark():
    from utk_curio.backend.app.agents.evaluation import benchmark

    return benchmark


def _skill_evals():
    from utk_curio.backend.app.agents.evaluation import skill_evals

    return skill_evals


def _check(kind: str, assertion: int = 1, **holds):
    return _checks().Check(assertion=assertion, kind=kind, holds=holds)


# --- The checks -----------------------------------------------------------------------


def test_each_kind_of_check_decides_its_assertion_from_the_run_s_record():
    checks = _checks()
    run = checks.RunRecord(
        calls=[
            {"tool": "node.read", "status": "ok"},
            {"tool": "node.settings.write", "status": "applied",
             "arguments": {"nodeId": "mult", "widgets": {"factor": 25}}},
            {"tool": "node.content.write", "status": "refused"},
            {"tool": "delegate", "capability": "node.content.generate", "status": "ok", "inputs": {"nodeId": "chart"}},
        ],
        changed={
            "nodes": {
                "added": [{"id": "chart", "type": "curio.builtin/vis-vega",
                           "content": json.dumps({"encoding": {"color": {"field": "scenario_name"}}})}],
                "changed": [{"id": "rows", "type": "curio.builtin/computation-analysis",
                             "changes": {"content": {"before": "x = 1", "after": "threshold = [!! threshold !!]"}}}],
            },
            "edges": {"added": [{"id": "e", "source": "pool", "target": "chart", "type": "Interaction"}]},
        },
        reply="The AirNow host, www.airnowapi.org, needs a key.",
        types={"pool": "curio.builtin/data-pool", "rows": "curio.builtin/computation-analysis"},
    )
    meets = {
        "a call that landed": _check("tool", tool="node.settings.write"),
        "on its node with its arguments": _check("tool", tool="node.settings.write", node="mult",
                                                 args={"widgets.factor": 25}),
        "a refused call, when asked for": _check("tool", tool="node.content.write", status="refused"),
        "no call of a tool": _check("tool", tool="node.create", absent=True),
        "a delegation on its node": _check("delegate", capability="node.content.generate", node="chart"),
        "a node of a type": _check("node-added", type="curio.builtin/vis-vega", count=1),
        "an interaction edge between two types": _check("edge-added", **{
            "from": "curio.builtin/data-pool", "to": "curio.builtin/vis-vega", "interaction": True}),
        "code that holds a pattern": _check("code", node="rows", pattern=r"\[!! threshold !!\]"),
        "code that lacks one": _check("code", type="curio.builtin/computation-analysis", pattern=r"= 25", absent=True),
        "a spec's field and value": _check("spec", type="curio.builtin/vis-vega", path="encoding.color.field",
                                           equals="scenario_name"),
        "a spec without a field": _check("spec", node="chart", path="encoding.x", absent=True),
        "a reply that names a host": _check("reply", pattern=r"airnowapi\.org"),
    }
    for what, check in meets.items():
        assert checks.passes(check, run), what
    misses = {
        "a call on another node": _check("tool", tool="node.settings.write", node="chart"),
        "other arguments": _check("tool", tool="node.settings.write", args={"widgets.factor": 3}),
        "a refused call counts as no call": _check("tool", tool="node.content.write"),
        "a call that was made": _check("tool", tool="node.read", absent=True),
        "a delegation on another node": _check("delegate", capability="node.content.generate", node="rows"),
        "two nodes of a type": _check("node-added", type="curio.builtin/vis-vega", count=2),
        "a data edge": _check("edge-added", **{"from": "curio.builtin/data-pool", "to": "curio.builtin/vis-vega",
                                               "interaction": False}),
        "code that does not hold it": _check("code", node="rows", pattern=r"input_1"),
        "a spec with another value": _check("spec", path="encoding.color.field", equals="name"),
        "a run that changed something": _check("unchanged"),
        "a reply that does not name it": _check("reply", pattern=r"openweathermap"),
    }
    for what, check in misses.items():
        assert not checks.passes(check, run), what
    assert checks.passes(_check("unchanged"), checks.RunRecord())
    # "The code lacks it" needs code written at all.
    assert not checks.passes(_check("code", pattern="anything", absent=True), checks.RunRecord())
    # An assertion several checks name holds when all of them do.
    assert checks.decided([_check("reply", 2, pattern="airnow"), _check("unchanged", 2)], run) == {2: False}
    assert checks.decided([_check("reply", 2, pattern="airnow"), _check("unchanged", 3, absent=True)], run) == {
        2: True, 3: True}


def test_a_run_s_record_is_read_from_its_folder_and_its_case_s_dataflow(tmp_path):
    checks = _checks()
    folder = tmp_path / "run-1"
    (folder / "outputs").mkdir(parents=True)
    (folder / "outputs" / "calls.json").write_text(json.dumps([{"tool": "node.read", "status": "ok"}]),
                                                   encoding="utf-8")
    (folder / "outputs" / "changes.json").write_text(json.dumps({"changed": {"edges": {"added": [
        {"id": "e", "source": "loader", "target": "chart"}]}}, "cards": []}), encoding="utf-8")
    (folder / "outputs" / "reply.md").write_text("Done.\n", encoding="utf-8")
    dataflow = tmp_path / "flow.json"
    dataflow.write_text(json.dumps({"dataflow": {"nodes": [
        {"id": "loader", "type": "curio.builtin/data-loading"}, {"id": "chart", "type": "curio.builtin/vis-vega"}]}}),
        encoding="utf-8")
    run = checks.RunRecord.of(folder, dataflow)
    assert run.types == {"loader": "curio.builtin/data-loading", "chart": "curio.builtin/vis-vega"}
    assert run.reply == "Done.\n" and run.calls == [{"tool": "node.read", "status": "ok"}]
    assert checks.passes(_check("edge-added", **{"from": "curio.builtin/data-loading",
                                                 "to": "curio.builtin/vis-vega"}), run)
    # A run that wrote no outputs reads as one that did nothing.
    empty = checks.RunRecord.of(tmp_path / "missing")
    assert empty.calls == [] and empty.changed == {} and empty.reply == ""


def test_a_call_that_names_no_node_is_on_the_node_the_agent_is_attached_to():
    checks = _checks()
    calls = [
        {"tool": "node.settings.write", "status": "applied", "arguments": {"dataPool": {"betweenCharts": "MERGE_AND"}}},
        {"tool": "node.content.write", "status": "refused"},
        {"tool": "delegate", "capability": "node.content.generate", "status": "ok", "inputs": {"instruction": "A map."}},
    ]
    on_pool, on_canvas = checks.RunRecord(calls=calls, attached="pool"), checks.RunRecord(calls=calls)
    write = _check("tool", tool="node.settings.write", node="pool")
    assert checks.passes(write, on_pool)
    assert not checks.passes(_check("tool", tool="node.settings.write", node="pool", absent=True), on_pool)
    assert not checks.passes(write, on_canvas)
    # The record holds no arguments of a call that landed nothing, so no node it was on.
    assert not checks.passes(_check("tool", tool="node.content.write", status="refused", node="pool"), on_pool)
    delegated = _check("delegate", capability="node.content.generate", node="pool")
    assert checks.passes(delegated, on_pool)
    assert not checks.passes(delegated, on_canvas)
    # A delegation that names a nodeType writes the template of a new node.
    new_node = checks.RunRecord(calls=[{"tool": "delegate", "capability": "node.content.generate", "status": "ok",
                                        "inputs": {"nodeType": "curio.builtin/vis-vega"}}], attached="pool")
    assert not checks.passes(delegated, new_node)


def test_a_spec_check_reads_a_chip_outside_a_string_as_a_string():
    checks = _checks()
    content = ('{"data": {"values": [1]}, "encoding": {"color": '
               '{"field": "scenario_name", "scale": [!! scenario colors !!]}}}')
    run = checks.RunRecord(changed={"nodes": {"added": [
        {"id": "chart", "type": "curio.builtin/vis-vega", "content": content}]}})
    assert checks.passes(_check("spec", path="data"), run)
    assert not checks.passes(_check("spec", path="data", absent=True), run)
    assert checks.passes(_check("spec", path="encoding.color.scale", equals="[!! scenario colors !!]"), run)


def _write_skill(folder: Path, cases: list[dict], queries: list[dict] | None = None) -> None:
    (folder / "evals").mkdir(parents=True)
    (folder / "SKILL.md").write_text(
        f"---\nname: {folder.name}\ndescription: Use this skill when counting street trees.\n---\n## Trees\n",
        encoding="utf-8")
    (folder / "evals" / "evals.json").write_text(json.dumps({
        "skill_name": folder.name, "agent": "agent.you.tree-counter@1", "evals": cases,
        "trigger_queries": queries if queries is not None else [
            {"query": "How many oaks are on my street?", "should_trigger": True},
            {"query": "Rename the chart.", "should_trigger": False}],
    }), encoding="utf-8")


def _case(case_id: int, assertions: list[str], checks: list | None = None) -> dict:
    case = {"id": case_id, "prompt": "Count the oaks.", "expected_output": "A count.", "assertions": assertions}
    if checks is not None:
        case["checks"] = checks
    return case


def test_a_check_that_breaks_the_format_is_refused_naming_each_problem(tmp_path):
    skill_evals = _skill_evals()
    folder = tmp_path / "street-trees"
    _write_skill(folder, [_case(1, ["It counts oaks.", "It names its source."], [
        {"assertion": 1, "kind": "guess"},
        {"assertion": 0, "kind": "reply", "pattern": "oak"},
        {"assertion": 3, "kind": "reply", "pattern": "oak"},
        {"assertion": 1, "kind": "tool"},
        {"assertion": 2, "kind": "reply", "pattern": "oak", "case": "insensitive"},
        {"assertion": 2, "kind": "reply", "pattern": "(oak"},
        {"assertion": 1, "kind": "tool", "tool": "node.create", "args": ["nodeId"]},
        {"assertion": 1, "kind": "node-added", "type": "curio.builtin/vis-vega", "count": 0},
    ])])
    with pytest.raises(skill_evals.EvalsError) as refused:
        skill_evals.read(folder)
    message = str(refused.value)
    for problem in ("kind must be one of", "assertion must be the place of one of its 2 assertions, from 1, not 0",
                    "from 1, not 3", "a tool check needs tool", "a reply check takes no case",
                    "its pattern is no regular expression", "args must be an object", "count must be a whole number"):
        assert problem in message, message

    good = tmp_path / "street-oaks"
    _write_skill(good, [_case(1, ["It counts oaks.", "It creates no node."], [
        {"assertion": 2, "kind": "tool", "tool": "node.create", "absent": True}])])
    read = skill_evals.read(good)
    assert read.cases[0].checks == (_check("tool", 2, tool="node.create", absent=True),)


# --- The version ----------------------------------------------------------------------


def test_the_version_is_the_same_for_the_same_files_and_moves_with_any_of_them(tmp_path):
    benchmark, skill_evals = _benchmark(), _skill_evals()
    trees, oaks = tmp_path / "street-trees", tmp_path / "street-oaks"
    _write_skill(trees, [_case(1, ["It counts oaks."])])
    _write_skill(oaks, [_case(1, ["It counts oaks."])])
    both = [skill_evals.read(trees), skill_evals.read(oaks)]
    version = benchmark.version(both)
    assert len(version) == benchmark.VERSION_CHARS and int(version, 16) >= 0
    assert benchmark.version(list(reversed(both))) == version
    assert benchmark.version(both[:1]) != version
    file = trees / "evals" / "evals.json"
    data = json.loads(file.read_text(encoding="utf-8"))
    data["evals"][0]["assertions"].append("It names its source.")
    file.write_text(json.dumps(data), encoding="utf-8")
    assert benchmark.version([skill_evals.read(trees), both[1]]) != version


# --- Scoring a run folder -------------------------------------------------------------


def _record(folder: Path, record: dict, *, calls=None, reply: str = "", transcript=None) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "run.json").write_text(json.dumps(record), encoding="utf-8")
    if record.get("kind") == "task":
        (folder / "outputs").mkdir()
        (folder / "outputs" / "calls.json").write_text(json.dumps(calls or []), encoding="utf-8")
        (folder / "outputs" / "changes.json").write_text(json.dumps({"changed": {}, "cards": []}), encoding="utf-8")
        (folder / "outputs" / "reply.md").write_text(reply, encoding="utf-8")
    if transcript is not None:
        (folder / "transcript.json").write_text(json.dumps(transcript), encoding="utf-8")


def _task(skill: str, case: int, condition: str, run: int, passed: list[bool], *, used: bool = True) -> dict:
    results = [{"text": f"assertion {at}", "passed": value} for at, value in enumerate(passed, start=1)]
    return {
        "kind": "task", "skill": skill, "case": case, "condition": condition, "run": run, "used": used,
        "seconds": 10.0, "modelCalls": [{"outputTokens": 10}],
        "timing": {"input_tokens": 100, "output_tokens": 10},
        "grading": {"assertion_results": results,
                    "grader": {"model": "grader-model", "attempts": 1, "inputTokens": 10, "outputTokens": 1}},
    }


def _scored_folder(tmp_path: Path):
    """A run folder of one skill, street-trees, whose numbers are worked out by hand.

    Case 1 has two assertions; its second is checked, passing when the reply
    names an oak. With the skill its grader passes the first and fails the
    second in each run, and the replies of runs 1 and 2 name an oak: so they
    pass both (1.0), and run 3 passes one (0.5). Without the skill every
    assertion fails (0.0). Case 2 passes with the skill in every run (1.0), and
    without it in runs 1 and 3 (2 of 3). The query that should trigger loaded
    the skill in 2 of 3 runs, and the one that should not in none, its third
    run left in an error.
    """
    skill_evals = _skill_evals()
    source = tmp_path / "skills" / "street-trees"
    _write_skill(source, [_case(1, ["It counts oaks.", "It names an oak."],
                                [{"assertion": 2, "kind": "reply", "pattern": "oak"}]),
                          _case(2, ["It counts trees."])])
    evals = {"street-trees": skill_evals.read(source)}
    folder = tmp_path / "skills-20261104-000000"
    folder.mkdir()
    (folder / "run.json").write_text(json.dumps({"run": folder.name, "model": "measured-model", "commit": "abc",
                                                 "benchmarkVersion": "v1", "grader": "grader-model"}),
                                     encoding="utf-8")
    base = folder / "street-trees"
    for run, reply in ((1, "Two oaks."), (2, "An oak."), (3, "Two elms.")):
        here = base / "eval-1" / "with_skill" / f"run-{run}"
        record = _task("street-trees", 1, "with_skill", run, [True, False], used=run != 3)
        calls, transcript = None, None
        if run == 1:
            record["modelCalls"] = [{"outputTokens": 10, "cut": True}, {"outputTokens": 5}]
            calls = [{"tool": "node.read", "status": "ok"}, {"tool": "node.content.write", "status": "refused"}]
            transcript = [{"role": "user"}, {"role": "agent", "execution": {"pins": {"toolProtocol": "native"}}},
                          {"role": "agent", "execution": {"pins": {"toolProtocol": "fenced"}}}]
        _record(here, record, calls=calls, reply=reply, transcript=transcript)
        _record(base / "eval-1" / "without_skill" / f"run-{run}",
                _task("street-trees", 1, "without_skill", run, [False, False]), reply="No idea.")
        _record(base / "eval-2" / "with_skill" / f"run-{run}", _task("street-trees", 2, "with_skill", run, [True]))
        _record(base / "eval-2" / "without_skill" / f"run-{run}",
                _task("street-trees", 2, "without_skill", run, [run != 2]))
        _record(base / "triggers" / "q01" / f"run-{run}",
                {"kind": "trigger", "skill": "street-trees", "query": 1, "should_trigger": True, "run": run,
                 "triggered": run != 3, "seconds": 2.0})
        trigger = {"kind": "trigger", "skill": "street-trees", "query": 2, "should_trigger": False, "run": run,
                   "triggered": False, "seconds": 2.0}
        if run == 3:
            trigger["error"] = "the run answered 502: Connection error."
        _record(base / "triggers" / "q02" / f"run-{run}", trigger)
    return folder, evals


def test_a_case_s_checks_read_the_node_its_agent_is_attached_to(tmp_path):
    benchmark, skill_evals = _benchmark(), _skill_evals()
    source = tmp_path / "skills" / "pool-joins"
    _write_skill(source, [{**_case(1, ["It joins the charts' selections on the pool."],
                                   [{"assertion": 1, "kind": "tool", "tool": "node.settings.write", "node": "pool"}]),
                           "target": {"kind": "node", "node": "pool"}}])
    evals = {"pool-joins": skill_evals.read(source)}
    folder = tmp_path / "skills-20261104-000000"
    folder.mkdir()
    (folder / "run.json").write_text(json.dumps({"run": folder.name, "model": "measured-model"}), encoding="utf-8")
    _record(folder / "pool-joins" / "eval-1" / "with_skill" / "run-1",
            _task("pool-joins", 1, "with_skill", 1, [False]),
            calls=[{"tool": "node.settings.write", "status": "applied",
                    "arguments": {"dataPool": {"betweenCharts": "MERGE_AND"}}}])
    scored = benchmark.score(folder, evals)
    assert [(item["assertion"], item["grader"], item["check"]) for item in scored["disagreements"]] == [
        (1, False, True)]
    assert scored["cases"]["pool-joins/1"]["with_skill"] == [1.0]


def test_a_run_folder_is_scored_per_skill_and_over_every_case(tmp_path):
    benchmark = _benchmark()
    folder, evals = _scored_folder(tmp_path)
    scored = benchmark.score(folder, evals)
    assert (scored["version"], scored["model"], scored["grader"], scored["commit"]) == (
        "v1", "measured-model", "grader-model", "abc")
    overall = scored["overall"]
    assert overall == scored["skills"]["street-trees"]
    assert overall["success"]["value"] == round(((1.0 + 1.0 + 0.5) / 3 + 1.0) / 2, 4)
    assert (overall["success"]["n"], overall["success"]["runs"]) == (2, 6)
    assert overall["all_pass"]["value"] == round((2 / 3 + 1.0) / 2, 4)
    assert overall["without"]["value"] == round((0.0 + 2 / 3) / 2, 4)
    assert overall["lift"]["value"] == round(((2.5 / 3 - 0.0) + (1.0 - 2 / 3)) / 2, 4)
    assert overall["reach"] == {"value": round(5 / 6, 4), "count": 5, "of": 6}
    assert overall["trigger_recall"]["value"] == round(2 / 3, 4)
    assert (overall["false_triggers"]["value"], overall["false_triggers"]["runs"]) == (0.0, 2)
    assert overall["errors"] == {"value": round(1 / 18, 4), "count": 1, "of": 18}
    assert overall["cut_calls"] == {"value": round(1 / 13, 4), "count": 1, "of": 13}
    assert overall["refused_calls"] == {"value": 0.5, "count": 1, "of": 2}
    assert overall["native_turns"] == {"value": 0.5, "count": 1, "of": 2}
    # The grader's tokens count too.
    assert (overall["cost"]["input_tokens"], overall["cost"]["output_tokens"]) == (12 * 110, 12 * 11)
    priced = benchmark.score(folder, evals, price={"input": 0.10, "output": 0.50})
    assert priced["overall"]["cost"]["dollars"] == round((1320 * 0.10 + 132 * 0.50) / 1e6, 4)
    # The check passed runs 1 and 2's second assertion, which their grader failed.
    assert sorted((item["run"], item["assertion"], item["grader"], item["check"])
                  for item in scored["disagreements"]) == [
        ("street-trees/eval-1/with_skill/run-1", 2, False, True),
        ("street-trees/eval-1/with_skill/run-2", 2, False, True)]
    assert scored["cases"]["street-trees/1"]["with_skill"] == [1.0, 1.0, 0.5]
    assert scored["queries"]["street-trees/q02"] == {"skill": "street-trees", "should_trigger": False,
                                                    "runs": [0.0, 0.0]}
    for name in ("success", "all_pass", "without", "trigger_recall"):
        low, high = overall[name]["interval"]
        assert 0 <= low <= overall[name]["value"] <= high <= 1, name
    low, high = overall["lift"]["interval"]
    assert -1 <= low <= overall["lift"]["value"] <= high <= 1
    # The same folder scores the same each time.
    assert benchmark.score(folder, evals) == scored


def test_intervals_resample_cases_and_their_runs():
    benchmark = _benchmark()
    assert benchmark.interval([[1.0, 1.0], [1.0]]) == [1.0, 1.0]
    assert benchmark.interval([]) is None
    assert benchmark.paired_interval([([0.0, 0.0], [1.0])]) == [1.0, 1.0]
    low, high = benchmark.interval([[0.0, 1.0]] * 10)
    assert low < 0.5 < high
    # More cases narrow it.
    wide = benchmark.interval([[0.0, 1.0]] * 3)
    narrow = benchmark.interval([[0.0, 1.0]] * 40)
    assert narrow[1] - narrow[0] < wide[1] - wide[0]


# --- Comparing two runs ---------------------------------------------------------------


def _scored(cases: dict, queries: dict | None = None, *, version: str = "v1", model: str = "measured-model",
            grader: str = "measured-model") -> dict:
    return {"version": version, "model": model, "grader": grader, "run": "skills-x", "cases": cases,
            "queries": queries or {}}


def test_a_compare_finds_a_difference_planted_in_its_samples():
    benchmark = _benchmark()
    half = {f"street-trees/{at}": {"skill": "street-trees", "case": at, "with_skill": [0.5, 0.5, 0.5]}
            for at in range(1, 13)}
    whole = {key: {**entry, "with_skill": [1.0, 1.0, 1.0]} for key, entry in half.items()}
    queries_a = {"street-trees/q01": {"skill": "street-trees", "should_trigger": True, "runs": [0.0, 0.0, 0.0]},
                 "street-trees/q02": {"skill": "street-trees", "should_trigger": False, "runs": [1.0, 1.0, 1.0]}}
    queries_b = {"street-trees/q01": {**queries_a["street-trees/q01"], "runs": [1.0, 1.0, 1.0]},
                 "street-trees/q02": {**queries_a["street-trees/q02"], "runs": [0.0, 0.0, 0.0]}}
    found = benchmark.compare(_scored(half, queries_a), _scored(whole, queries_b))
    assert found["overall"]["success"]["verdict"] == benchmark.BETTER
    assert found["overall"]["success"]["value"] == 0.5
    skill = found["skills"]["street-trees"]
    assert skill["success"]["verdict"] == benchmark.BETTER
    assert skill["trigger_recall"]["verdict"] == benchmark.BETTER
    # Fewer false triggers is better.
    assert skill["false_triggers"]["verdict"] == benchmark.BETTER
    backwards = benchmark.compare(_scored(whole, queries_b), _scored(half, queries_a))
    assert backwards["overall"]["success"]["verdict"] == benchmark.WORSE
    assert backwards["skills"]["street-trees"]["false_triggers"]["verdict"] == benchmark.WORSE


def test_two_halves_of_one_run_are_not_shown_different():
    benchmark = _benchmark()
    first, second = {}, {}
    for at in range(1, 13):
        runs = [((at * 7) % 10) / 10, ((at * 3) % 10) / 10, ((at * 5) % 10) / 10]
        # Each half holds the same runs, in another order.
        first[f"street-trees/{at}"] = {"skill": "street-trees", "case": at, "with_skill": runs}
        second[f"street-trees/{at}"] = {"skill": "street-trees", "case": at, "with_skill": list(reversed(runs))}
    found = benchmark.compare(_scored(first), _scored(second))
    assert found["overall"]["success"]["verdict"] == benchmark.SAME
    assert found["overall"]["success"]["value"] == 0.0
    assert found["skills"]["street-trees"]["success"]["verdict"] == benchmark.SAME


def test_only_two_runs_of_one_set_one_model_and_one_grader_compare():
    benchmark = _benchmark()
    cases = {"street-trees/1": {"skill": "street-trees", "case": 1, "with_skill": [1.0]}}
    with pytest.raises(benchmark.CompareRefused, match="different sets"):
        benchmark.compare(_scored(cases), _scored(cases, version="v2"))
    with pytest.raises(benchmark.CompareRefused, match="different models"):
        benchmark.compare(_scored(cases), _scored(cases, model="another-model"))
    # A run its model graded and one the benchmark's fixed grader graded.
    with pytest.raises(benchmark.CompareRefused, match="graded by different models"):
        benchmark.compare(_scored(cases), _scored(cases, grader="grader-model"))
