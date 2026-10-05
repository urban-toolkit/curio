"""A dataflow's scenarios (#662), at ``dataflow.scenarios``.

What a spec keeps of them is one table of cases, ``scenarios.cases.json``,
read here and by Jest (``src/tests/utils/scenarioModel.test.ts``). A save
refuses a node in two scenarios, drops members that are not nodes, keeps the
on-disk scenarios when a writer omits the key and clears them on an empty
list. The project summary lists them.

The scenario module is imported inside each test, so one missing name fails
its own tests and not the whole collection.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from utk_curio.backend.app.projects import services, storage
from utk_curio.backend.app.projects.schemas import ProjectCreate, ProjectUpdate

REPO_ROOT = Path(__file__).resolve().parents[4]
CASES = REPO_ROOT / "utk_curio" / "frontend" / "urban-workflows" / "src" / "utils" / "scenarios" / "scenarios.cases.json"

BASELINE = {"id": "s1", "name": "Baseline", "color": "#2a9d8f", "nodes": ["a"]}
TALL = {"id": "s2", "name": "Twice as tall", "color": "#e76f51", "nodes": ["b"]}


def _scenarios():
    from utk_curio.backend.app.projects import scenarios

    return scenarios


def _nodes(*ids):
    return [{"id": i, "type": "curio.builtin/computation-analysis", "content": "", "x": 0, "y": 0} for i in ids]


def _spec(nodes=("a", "b"), scenarios=None):
    dataflow = {"name": "Mine", "nodes": _nodes(*nodes), "edges": []}
    if scenarios is not None:
        dataflow["scenarios"] = scenarios
    return {"dataflow": dataflow}


def _save(user, scenarios=None, nodes=("a", "b")):
    return services.save_project(
        user, ProjectCreate(name="Mine", spec=_spec(nodes, scenarios), outputs=[])
    )


def _on_disk(user, project_id):
    return storage.read_spec(str(user.id), project_id)["dataflow"].get("scenarios")


# ---------------------------------------------------------------------------
# The shared cases
# ---------------------------------------------------------------------------

def test_the_backend_keeps_what_the_canvas_keeps():
    cases = json.loads(CASES.read_text(encoding="utf-8"))["cases"]
    assert cases
    mismatches = [
        f"{c['name']}: kept {got!r}, the table says {c['expected']!r}"
        for c in cases
        if (got := _scenarios().normalize_scenarios(c["scenarios"], c["nodes"])) != c["expected"]
    ]
    assert not mismatches, "\n".join(mismatches)


# ---------------------------------------------------------------------------
# What a writer may not send
# ---------------------------------------------------------------------------

def test_new_scenarios_take_the_canvas_colors_in_turn():
    """A scenario a Dataflow Builder plan makes takes the next color the way a
    scenario made on the canvas does (``nextScenarioColor``)."""
    import re

    from utk_curio.backend.app.projects.scenarios import SCENARIO_COLORS, next_scenario_color

    source = (CASES.parent / "scenarioEdits.ts").read_text(encoding="utf-8")
    block = source.split("export const SCENARIO_COLORS = [", 1)[1].split("]", 1)[0]
    assert tuple(re.findall(r'"(#[0-9a-fA-F]{6})"', block)) == SCENARIO_COLORS
    assert next_scenario_color([]) == SCENARIO_COLORS[0]
    # A color is taken whatever its case; the first free one wins, not the next in line.
    assert next_scenario_color([SCENARIO_COLORS[0].upper(), SCENARIO_COLORS[2]]) == SCENARIO_COLORS[1]
    # Every color worn: round again by how many there are.
    worn = list(SCENARIO_COLORS) + [SCENARIO_COLORS[0]]
    assert next_scenario_color(worn) == SCENARIO_COLORS[len(worn) % len(SCENARIO_COLORS)]


def test_a_node_in_two_scenarios_is_a_conflict():
    spec = _spec(scenarios=[BASELINE, {**TALL, "nodes": ["b", "a"]}])
    assert _scenarios().scenario_conflicts(spec) == [
        "Node a is in two scenarios, Baseline and Twice as tall. A node belongs to at most one scenario."
    ]


def test_two_scenarios_with_one_id_are_a_conflict():
    spec = _spec(scenarios=[BASELINE, {**TALL, "id": "s1"}])
    assert _scenarios().scenario_conflicts(spec) == ["Two scenarios have the id s1."]


def test_a_member_that_is_not_a_node_is_a_problem_but_not_a_conflict():
    spec = _spec(scenarios=[{**BASELINE, "nodes": ["a", "gone"]}])
    assert _scenarios().scenario_conflicts(spec) == []
    assert _scenarios().scenario_problems(spec) == [
        "Scenario Baseline names node gone, which the dataflow does not have."
    ]


def test_a_request_with_a_conflict_is_refused():
    _scenarios()
    spec = _spec(scenarios=[BASELINE, {**TALL, "nodes": ["a"]}])
    with pytest.raises(ValueError, match="Node a is in two scenarios"):
        ProjectUpdate(spec=spec)
    with pytest.raises(ValueError, match="Node a is in two scenarios"):
        ProjectCreate(name="Mine", spec=spec, outputs=[])


def test_the_route_answers_400_and_writes_nothing(client, user_and_token, tmp_curio):
    _, token = user_and_token
    _scenarios()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    created = client.post(
        "/api/projects",
        data=json.dumps({"name": "Mine", "spec": _spec(scenarios=[BASELINE])}),
        headers=headers,
    )
    assert created.status_code == 201
    pid = created.get_json()["id"]

    resp = client.put(
        f"/api/projects/{pid}",
        data=json.dumps({"spec": _spec(scenarios=[BASELINE, {**TALL, "nodes": ["a"]}])}),
        headers=headers,
    )

    assert resp.status_code == 400
    assert "Node a is in two scenarios" in resp.get_json()["error"]
    stored = client.get(f"/api/projects/{pid}", headers=headers).get_json()
    assert stored["spec"]["dataflow"]["scenarios"] == [BASELINE]
    assert stored["project"]["scenarios"] == [BASELINE]


# ---------------------------------------------------------------------------
# Saving
# ---------------------------------------------------------------------------

def test_a_save_keeps_them_and_the_summary_lists_them(app, db, user_and_token):
    user, _ = user_and_token
    _scenarios()
    detail = _save(user, scenarios=[BASELINE, TALL])

    assert _on_disk(user, detail.id) == [BASELINE, TALL]
    assert detail.scenarios == [BASELINE, TALL]
    summary = next(s for s in services.list_projects(user) if s.id == detail.id)
    assert summary.scenarios == [BASELINE, TALL]


def test_a_save_drops_the_ids_of_deleted_nodes(app, db, user_and_token):
    user, _ = user_and_token
    _scenarios()
    detail = _save(user, scenarios=[BASELINE, TALL])

    spec = _spec(nodes=("a",), scenarios=[BASELINE, TALL])
    services.update_project(user, detail.id, ProjectUpdate(spec=spec))

    assert _on_disk(user, detail.id) == [BASELINE, {**TALL, "nodes": []}]


def test_a_save_without_the_key_keeps_them(app, db, user_and_token):
    """An agent's graph edit, or any writer that does not know the field."""
    user, _ = user_and_token
    _scenarios()
    detail = _save(user, scenarios=[BASELINE, TALL])

    services.update_project(user, detail.id, ProjectUpdate(spec=_spec(nodes=("a",))))

    # Carried forward, and pruned against the nodes the new spec has.
    assert _on_disk(user, detail.id) == [BASELINE, {**TALL, "nodes": []}]


def test_a_save_with_an_empty_list_clears_them(app, db, user_and_token):
    user, _ = user_and_token
    _scenarios()
    detail = _save(user, scenarios=[BASELINE])

    services.update_project(user, detail.id, ProjectUpdate(spec=_spec(scenarios=[])))

    assert _on_disk(user, detail.id) is None


def test_a_dataflow_without_scenarios_has_no_key(app, db, user_and_token):
    user, _ = user_and_token
    _scenarios()
    detail = _save(user, scenarios=[])

    assert _on_disk(user, detail.id) is None
    assert detail.scenarios == []


def test_a_duplicate_keeps_them(app, db, user_and_token):
    user, _ = user_and_token
    _scenarios()
    detail = _save(user, scenarios=[BASELINE])

    copy = services.duplicate_project(user, detail.id)

    assert copy.scenarios == [BASELINE]
