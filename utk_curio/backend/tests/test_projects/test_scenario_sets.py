"""A dataflow's scenario sets, at ``dataflow.scenarioSets``.

What a spec keeps of them is one table of cases, ``scenarioSets.cases.json``,
read here and by Jest (``src/tests/utils/scenarioSets.cases.test.ts``): each
scenario's context and outcomes, inferred up and down its edges or kept as
the person finalized them, and the set it is in. A save fills them in, and a
committed spec is checked for them.
"""
from __future__ import annotations

import json
from pathlib import Path

from utk_curio.backend.app.projects import scenario_sets, scenarios
from utk_curio.backend.app.projects import services, storage
from utk_curio.backend.app.projects.schemas import ProjectCreate, ProjectUpdate

REPO_ROOT = Path(__file__).resolve().parents[4]
CASES = REPO_ROOT / "utk_curio" / "frontend" / "urban-workflows" / "src" / "utils" / "scenarios" / "scenarioSets.cases.json"


def test_the_backend_keeps_the_sets_the_canvas_keeps():
    cases = json.loads(CASES.read_text(encoding="utf-8"))["cases"]
    assert cases
    mismatches = []
    for c in cases:
        kept = scenarios.normalize_scenarios(c["scenarios"], c["nodes"])
        got, sets = scenario_sets.normalize_scenario_sets(
            kept, c.get("sets"), c["nodes"], c["edges"], c.get("dataflowName"),
        )
        if {"scenarioSets": sets, "scenarios": got} != c["expected"]:
            mismatches.append(f"{c['name']}: kept {sets!r} {got!r}, the table says {c['expected']!r}")
    assert not mismatches, "\n".join(mismatches)


def test_membership_lists_each_node_s_scenarios_in_the_set_s_order():
    case = json.loads(CASES.read_text(encoding="utf-8"))["cases"][0]
    kept = case["expected"]["scenarios"]
    member = scenario_sets.set_membership(kept, kept[0]["set"])
    assert member["scenarios"] == ["existing", "towers", "cap"]
    assert member["context"]["around"] == ["towers", "cap"]
    assert member["outcomes"]["chart"] == ["existing", "towers", "cap"]
    assert member["outcomes"]["changeT"] == ["existing", "towers"]


def _spec():
    nodes = [{"id": i, "type": "curio.builtin/computation-analysis", "content": "", "x": 0, "y": 0}
             for i in ("load", "a", "b", "chart")]
    edges = [{"source": "load", "target": "a"}, {"source": "load", "target": "b"},
             {"source": "a", "target": "chart"}, {"source": "b", "target": "chart"}]
    return {"dataflow": {"name": "Mine", "nodes": nodes, "edges": edges, "scenarios": [
        {"id": "s1", "name": "Baseline", "color": "#2a9d8f", "nodes": ["a"]},
        {"id": "s2", "name": "Taller", "color": "#e76f51", "nodes": ["b"]},
    ]}}


def test_a_spec_from_before_sets_gets_one_set_and_the_inferred_lists():
    spec = _spec()
    scenarios.normalize_spec_scenarios(spec)
    df = spec["dataflow"]
    assert df["scenarioSets"] == [{"id": "set-s1", "name": "Mine"}]
    assert [(s["set"], s["context"], s["outcomes"]) for s in df["scenarios"]] == [
        ("set-s1", ["load"], ["chart"]), ("set-s1", ["load"], ["chart"]),
    ]
    assert scenarios.scenario_problems(spec) == []


def test_a_committed_spec_without_sets_has_problems():
    problems = scenarios.scenario_problems(_spec())
    assert "Scenario Baseline is in no set of dataflow.scenarioSets." in problems
    assert "Scenario Baseline has no context list." in problems


def test_a_context_node_in_a_box_is_a_problem():
    spec = _spec()
    scenarios.normalize_spec_scenarios(spec)
    spec["dataflow"]["scenarios"][0]["context"] = ["b"]
    assert scenarios.scenario_problems(spec) == [
        "Scenario Baseline's context names node b, which is in a scenario's box."
    ]


def test_a_save_keeps_what_the_person_finalized(app, db, user_and_token):
    user, _ = user_and_token
    spec = _spec()
    spec["dataflow"]["scenarioSets"] = [{"id": "heights", "name": "Building heights"}]
    for s in spec["dataflow"]["scenarios"]:
        s.update(set="heights", context=["load"], outcomes=[])
    detail = services.save_project(user, ProjectCreate(name="Mine", spec=spec, outputs=[]))
    df = storage.read_spec(str(user.id), detail.id)["dataflow"]
    assert df["scenarioSets"] == [{"id": "heights", "name": "Building heights"}]
    assert [s["outcomes"] for s in df["scenarios"]] == [[], []]


def test_a_save_without_the_scenarios_keeps_the_sets(app, db, user_and_token):
    user, _ = user_and_token
    detail = services.save_project(user, ProjectCreate(name="Mine", spec=_spec(), outputs=[]))
    bare = _spec()
    del bare["dataflow"]["scenarios"]
    services.update_project(user, detail.id, ProjectUpdate(spec=bare))
    df = storage.read_spec(str(user.id), detail.id)["dataflow"]
    assert df["scenarioSets"] == [{"id": "set-s1", "name": "Mine"}]
    assert [s["set"] for s in df["scenarios"]] == ["set-s1", "set-s1"]
