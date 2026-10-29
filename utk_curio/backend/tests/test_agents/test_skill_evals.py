"""Every skill Curio ships holds its evaluations, as agentskills.io lays them out, and their runs count as its guides say.

Each skill of ``skills/``, and each skill a package Curio ships ships, holds
``evals/evals.json`` (https://agentskills.io/skill-creation/evaluating-skills):
test cases, each with its assertions, and, for a skill a chat loads with
skill.read, about twenty trigger queries, eight to ten that should load it
and eight to ten that should not
(https://agentskills.io/skill-creation/optimizing-descriptions). The queries
run where a chat lists the skill and is not handed it, so loading it is the
chat's own choice. ``agent_eval.py skills`` runs them against a live model,
which CI never does: these tests read the files, and count runs made up here.

A skill's listing leaves the ``evals/`` at its root out, as the packager of
agentskills.io's skill-creator does: no run is offered its evaluations, no
skill.read reads one, and no export carries one.

New names are read inside each test, so this module imports on a checkout
without them and each test fails on its own.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
AGENTS = REPO_ROOT / "agents"
#: How many trigger queries of each label a skill a chat loads holds.
EACH_SIDE = range(8, 11)


def _skill_evals():
    from utk_curio.backend.app.agents.evaluation import skill_evals

    return skill_evals


def _manifests() -> dict[str, dict]:
    """Each agent Curio ships, by its coord, as its manifest is written."""
    found = {}
    for path in sorted(AGENTS.glob("*/manifest.json")):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if manifest.get("kind") != "base":
            found[path.parent.name] = manifest
    return found


def _placed(coord: str) -> frozenset[str]:
    from utk_curio.backend.app.agents.application import skill_runs
    from utk_curio.backend.app.agents.domain import builtin

    return skill_runs.placed_in(builtin.read_prompt_text(coord, "system"), skill_runs.shipped_skills())


def _packages_of(dataflow: Path | None) -> set[str]:
    if dataflow is None:
        return set()
    spec = json.loads(dataflow.read_text(encoding="utf-8"))
    return {p.get("id") if isinstance(p, dict) else p for p in (spec.get("dataflow") or {}).get("packages") or []}


def _package_of(folder: Path) -> str | None:
    """The package whose ``skills/`` holds *folder*, by its folder's name."""
    parts = folder.relative_to(REPO_ROOT).parts
    return parts[1] if parts[0] == "packages" else None


def _chat_lists(coord: str, name: str, folder: Path, dataflow: Path | None) -> str | None:
    """Why a chat of *coord* on *dataflow* does not list *name* for skill.read
    to load, or None when it does."""
    manifest = _manifests().get(coord)
    if manifest is None:
        return f"{coord} is no agent Curio ships"
    if not (manifest.get("catalog") or {}).get("listed"):
        return f"{coord} has no chat"
    package = _package_of(folder)
    if package is not None:
        if package not in _packages_of(dataflow):
            return f"its dataflow does not use {package}"
    elif manifest.get("skills") is not None and name not in manifest["skills"]:
        return f"{coord}'s manifest does not name {name}"
    instruction = (manifest.get("prompts") or {}).get("instruction") or {}
    if name in (instruction.get("skills") or ()):
        return f"{coord}'s instruction hands {name} to every chat"
    if name in _placed(coord):
        return f"{coord}'s preamble holds {name}"
    return None


def _write_skill(folder: Path, evals: dict) -> None:
    (folder / "evals" / "files").mkdir(parents=True)
    (folder / "references" / "evals").mkdir(parents=True)
    (folder / "SKILL.md").write_text(
        f"---\nname: {folder.name}\ndescription: Use this skill when counting street trees.\n---\n## Trees\n",
        encoding="utf-8",
    )
    (folder / "evals" / "evals.json").write_text(json.dumps(evals), encoding="utf-8")
    (folder / "evals" / "files" / "flow.json").write_text("{}", encoding="utf-8")
    (folder / "references" / "species.md").write_text("Oak, elm, maple.\n", encoding="utf-8")
    (folder / "references" / "evals" / "counted.md").write_text("Kept.\n", encoding="utf-8")


def _evals(name: str = "street-trees") -> dict:
    return {
        "skill_name": name,
        "agent": "agent.you.tree-counter@1",
        "evals": [{"id": 1, "prompt": "Count the oaks.", "expected_output": "A count.",
                   "assertions": ["The answer counts oaks.", "The answer names its source."]}],
        "trigger_queries": [{"query": "How many oaks are on my street?", "should_trigger": True},
                            {"query": "Rename the chart.", "should_trigger": False}],
    }


# --- The listing ----------------------------------------------------------------------


def test_a_skills_listing_leaves_its_root_evals_folder_out(tmp_path):
    """The files a skill lists, those skill.read reads and those an export
    carries leave out the ``evals/`` at its root, and keep a folder of that
    name deeper in the skill."""
    from utk_curio.backend.app.agents.application import skill_runs
    from utk_curio.backend.app.agents.domain import skills
    from utk_curio.backend.app.agents.repositories import user_skills

    folder = tmp_path / "street-trees"
    _write_skill(folder, _evals())
    skill = skills.parse(folder)
    assert skills.EVALS_DIR == "evals"
    assert skill.files == ("references/evals/counted.md", "references/species.md")
    assert skills.listed_files(folder) == skill.files
    run = skill_runs.RunSkills(catalog=(skill,))
    assert "evals.json" not in skill_runs.content(skill, readable=True)
    for path in ("evals/evals.json", "evals/files/flow.json"):
        assert skill_runs.read(run, {"name": "street-trees", "path": path})[0] == "refused", path
    assert skill_runs.read(run, {"name": "street-trees", "path": "references/evals/counted.md"})[0] == "ok"
    assert sorted(user_skills.read_files(folder)) == ["SKILL.md", "references/evals/counted.md",
                                                      "references/species.md"]


# --- The files ------------------------------------------------------------------------


def test_every_skill_curio_ships_holds_its_evaluations_in_the_format():
    """Every skill of ``skills/`` and every skill a shipped package ships holds
    ``evals/evals.json``, which reads: its name, at least two test cases of at
    least two assertions each, and the agent, dataflow and target each runs
    on, each dataflow a file and each node one its dataflow holds."""
    skill_evals = _skill_evals()
    folders = skill_evals.skill_folders()
    assert len(folders) >= 22, folders
    for folder in folders:
        assert skill_evals.evals_file(folder).is_file(), f"{folder.name} holds no evals/evals.json"
        evals = skill_evals.read(folder)
        assert evals.name == folder.name
        assert len(evals.cases) >= 2, folder.name
        for case in evals.cases:
            assert len(case.assertions) >= 2, (folder.name, case.id)
            assert case.context.agent in _manifests(), (folder.name, case.id, case.context.agent)
    assert [e.name for e in skill_evals.shipped_evals()] == [folder.name for folder in folders]


def test_a_skill_a_chat_loads_has_about_twenty_trigger_queries_and_any_other_none():
    """A skill some agent's chat lists for skill.read, and is not handed,
    holds eight to ten queries that should load it and eight to ten that
    should not. A skill no chat loads that way, one the preamble holds or an
    instruction hands to every chat, holds none: no run could measure them."""
    skill_evals = _skill_evals()
    for folder in skill_evals.skill_folders():
        evals = skill_evals.read(folder)
        loads = [coord for coord in _manifests()
                 if _chat_lists(coord, evals.name, folder, evals.context.dataflow) is None]
        should = sum(1 for query in evals.queries if query.should_trigger)
        should_not = len(evals.queries) - should
        if loads:
            assert should in EACH_SIDE and should_not in EACH_SIDE, (evals.name, should, should_not, loads)
        else:
            assert not evals.queries, (evals.name, "no chat loads it")


def test_trigger_queries_run_where_a_chat_lists_the_skill_and_is_not_handed_it():
    """A skill's trigger queries run on its file's top-level agent, attached
    to the canvas, whose chat lists the skill and is not handed it, on a
    dataflow that uses the skill's package when a package ships it."""
    skill_evals = _skill_evals()
    for folder in skill_evals.skill_folders():
        evals = skill_evals.read(folder)
        if not evals.queries:
            continue
        assert evals.context.target == skill_evals.CANVAS, evals.name
        assert _chat_lists(evals.context.agent, evals.name, folder, evals.context.dataflow) is None, (
            evals.name, _chat_lists(evals.context.agent, evals.name, folder, evals.context.dataflow))


def test_a_package_skills_test_cases_run_on_a_dataflow_that_uses_its_package():
    """A package's skill reaches the agents on a dataflow that uses the
    package, so each of its test cases runs on one."""
    skill_evals = _skill_evals()
    for folder in skill_evals.skill_folders():
        package = _package_of(folder)
        if package is None:
            continue
        evals = skill_evals.read(folder)
        for case in evals.cases:
            assert package in _packages_of(case.context.dataflow), (evals.name, case.id)


def test_a_file_that_breaks_the_format_is_refused_naming_each_problem(tmp_path):
    skill_evals = _skill_evals()
    folder = tmp_path / "street-trees"
    broken = _evals("other-name")
    broken["evals"] += [{"id": 2, "prompt": "", "assertions": []},
                        {"id": 1, "prompt": "Again.", "expected_output": "x", "assertions": ["x"]}]
    broken["trigger_queries"] += [{"query": "Rename the chart.", "should_trigger": False},
                                  {"query": "Count the elms.", "should_trigger": "no"}]
    broken["target"] = {"kind": "node"}
    _write_skill(folder, broken)
    try:
        skill_evals.read(folder)
    except skill_evals.EvalsError as exc:
        message = str(exc)
    else:
        raise AssertionError("the file was read")
    for problem in ("skill_name must be 'street-trees'", "evals[2]: prompt must be text",
                    "evals[2]: expected_output must be text", "evals[2]: assertions must be a list",
                    "evals[1]: id must be a whole number no other test case has",
                    "trigger_queries[3] repeats an earlier query", "trigger_queries[4] must be",
                    "the top level: target must be"):
        assert problem in message, (problem, message)


# --- Counting -------------------------------------------------------------------------


def test_trigger_rates_and_the_benchmark_count_as_agentskills_io_says(tmp_path):
    """A query passes on a trigger rate above one half when it should
    trigger, below it when it should not, and a run that failed counts in
    neither. A run whose chat delegated its work before it loaded the skill
    did not load it, and is counted as handed off. The benchmark holds each
    condition's mean pass rate over its
    graded runs, the difference, and the runs with the skill split by
    whether the skill reached the model."""
    skill_evals = _skill_evals()
    folder = tmp_path / "street-trees"
    _write_skill(folder, _evals())
    evals = skill_evals.read(folder)

    def trigger(query, triggered, error=None, handed_off=None):
        return {"kind": "trigger", "skill": "street-trees", "query": query, "triggered": triggered,
                **({"error": error} if error else {}), **({"handedOff": handed_off} if handed_off else {})}

    rows = skill_evals.trigger_results(evals, [
        trigger(1, True), trigger(1, True), trigger(1, False, handed_off="node.content.generate"),
        trigger(2, True), trigger(2, False), trigger(2, False, error="the run answered 502"),
    ])
    assert rows == [
        {"query": "How many oaks are on my street?", "should_trigger": True, "triggers": 2, "runs": 3,
         "errors": 0, "handed_off": 1, "trigger_rate": 0.6667, "passed": True},
        {"query": "Rename the chart.", "should_trigger": False, "triggers": 1, "runs": 2, "errors": 1,
         "handed_off": 0, "trigger_rate": 0.5, "passed": False},
    ]
    assert skill_evals.trigger_summary(rows) == {
        "queries": 2, "judged": 2, "passed": 1, "should_trigger_rate": 0.6667,
        "should_not_trigger_rate": 0.5, "errors": 1, "runs": 5, "handed_off": 1,
    }

    def task(condition, rate, used=None, error=None):
        record = {"kind": "task", "skill": "street-trees", "case": 1, "condition": condition, "run": 1,
                  "used": used, "timing": {"duration_ms": 2000, "total_tokens": 100}}
        if error:
            record["error"] = error
        else:
            record["grading"] = {"summary": {"pass_rate": rate, "passed": 0, "failed": 0, "total": 2}}
        return record

    bench = skill_evals.benchmark(evals, [
        task("with_skill", 1.0, used=True), task("with_skill", 0.5, used=False), task("with_skill", 1.0, used=True),
        task("without_skill", 0.0), task("without_skill", 0.5), task("without_skill", 0.0),
        task("without_skill", None, error="the grader failed"),
    ])
    summary = bench["run_summary"]
    assert summary["with_skill"]["pass_rate"]["mean"] == 0.8333
    assert summary["without_skill"]["pass_rate"]["mean"] == 0.1667
    assert (summary["with_skill"]["runs"], summary["without_skill"]["runs"]) == (3, 3)
    assert summary["without_skill"]["errors"] == 1
    assert summary["delta"]["pass_rate"] == 0.6667
    assert summary["with_skill"]["used"] == {"runs": 2, "pass_rate": 1.0}
    assert summary["with_skill"]["not_used"] == {"runs": 1, "pass_rate": 0.5}
    assert summary["delta"]["time_seconds"] == 0.0 and summary["with_skill"]["tokens"]["mean"] == 100.0
    assert len(bench["runs"]) == 7
    assert skill_evals.grading_summary([{"passed": True}, {"passed": False}, {"passed": True}]) == {
        "passed": 2, "failed": 1, "total": 3, "pass_rate": 0.6667,
    }


def test_each_query_and_test_case_runs_three_times_in_each_of_its_conditions(tmp_path):
    skill_evals = _skill_evals()
    folder = tmp_path / "street-trees"
    _write_skill(folder, _evals())
    tasks = skill_evals.plan([skill_evals.read(folder)])
    assert [task.key for task in tasks] == [
        "triggers/q01/run-1", "triggers/q01/run-2", "triggers/q01/run-3",
        "triggers/q02/run-1", "triggers/q02/run-2", "triggers/q02/run-3",
        "eval-1/with_skill/run-1", "eval-1/with_skill/run-2", "eval-1/with_skill/run-3",
        "eval-1/without_skill/run-1", "eval-1/without_skill/run-2", "eval-1/without_skill/run-3",
    ]
    assert {task.condition for task in tasks if task.kind == "trigger"} == {"with_skill"}
    assert all(skill_evals.Task.from_dict(task.as_dict()) == task for task in tasks)


# --- The endpoint ---------------------------------------------------------------------


def test_the_endpoint_comes_from_three_variables_and_no_output_may_hold_it(tmp_path):
    """The endpoint is read from the three variables, a missing one named by
    its name alone; its ``repr`` names the model alone; and a file under a
    run's folder that holds its key, its base URL, its host and port or its
    host is found."""
    skill_evals = _skill_evals()
    env = {"CURIO_EVAL_BASE_URL": "https://models.example.org:8443/v1/", "CURIO_EVAL_API_KEY": "not-a-real-key-0123",
           "CURIO_EVAL_MODEL": "a-model"}
    try:
        skill_evals.Endpoint.from_env({"CURIO_EVAL_MODEL": "a-model"})
    except LookupError as exc:
        assert str(exc) == "set CURIO_EVAL_BASE_URL, CURIO_EVAL_API_KEY", exc
    else:
        raise AssertionError("an endpoint was read without its URL and key")
    endpoint = skill_evals.Endpoint.from_env(env)
    assert repr(endpoint) == "Endpoint(model='a-model')"
    assert endpoint.secrets() == {
        "eval-api-key": "not-a-real-key-0123", "eval-base-url": "https://models.example.org:8443/v1/",
        "eval-base-url-bare": "https://models.example.org:8443/v1", "eval-endpoint": "models.example.org:8443",
        "eval-host": "models.example.org",
    }
    (tmp_path / "skill" / "triggers").mkdir(parents=True)
    (tmp_path / "skill" / "clean.json").write_text('{"model": "a-model"}', encoding="utf-8")
    for at, secret in enumerate(("not-a-real-key-0123", "models.example.org", "https://models.example.org:8443/v1")):
        (tmp_path / "skill" / "triggers" / f"{at}.log").write_text(f"failed at {secret} once", encoding="utf-8")
    assert skill_evals.leaks(tmp_path, endpoint) == ["skill/triggers/0.log", "skill/triggers/1.log",
                                                     "skill/triggers/2.log"]
    loopback = skill_evals.Endpoint(base_url="http://127.0.0.1:9/v1", api_key="not-a-real-key-0123", model="m")
    assert "eval-host" not in loopback.secrets() and loopback.secrets()["eval-endpoint"] == "127.0.0.1:9"


def test_the_graders_words_are_a_page_of_the_base_entry_with_a_place_for_each_value():
    from utk_curio.backend.app.agents.domain import agent_text

    assert "skill-evals.md" in agent_text.pages()
    assert agent_text.section("skill-evals.md", "grader").startswith("You grade one answer")
    values = {name: f"<{name}>" for name in
              ("prompt", "expected_output", "assertions", "reply", "proposals", "tools")}
    filled = agent_text.fill(agent_text.section("skill-evals.md", "grader-task"), values, "skill-evals.md")
    assert all(f"<{name}>" in filled for name in values)
