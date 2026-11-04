"""The readers of a scenario's parts agree (#662).

* What dataflow.read tells an agent of each scenario, its set, its own nodes,
  its shared context and its shared outcomes, is what the Scenario Catalog's
  details list, for every shipped dataflow with scenarios.
* What saves its output because of example 06's scenarios is what stands for
  each one's boundary (the Data Pool its output crosses in from), its own last
  nodes and its shared outcomes, and nothing else.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_scenario_catalog/test_parts_readers.py -v
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]

#: Every shipped dataflow that holds scenarios.
SHIPPED = [
    "docs/examples/06-back-bay-road-sunlight.json",
    "docs/examples/dataflows/chicago-loop-shadow-towers.json",
    "docs/examples/dataflows/chicago-rain-wind-routing.json",
    "docs/examples/dataflows/crown-heights-1550-bedford-shadow.json",
    "docs/examples/dataflows/lower-manhattan-park-shade.json",
    "docs/examples/dataflows/quad-cities-flood-vulnerability.json",
    "docs/examples/dataflows/scenario-comparison-charts.json",
    "docs/examples/dataflows/scenarios.json",
]


def _headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _shipped(rel: str) -> dict:
    return json.loads((REPO_ROOT / rel).read_text(encoding="utf-8"))


def test_the_list_names_every_shipped_dataflow_with_scenarios():
    found = sorted(
        str(path.relative_to(REPO_ROOT))
        for folder in ("docs/examples", "docs/examples/dataflows")
        for path in (REPO_ROOT / folder).glob("*.json")
        if (json.loads(path.read_text(encoding="utf-8")).get("dataflow") or {}).get("scenarios")
    )
    assert found == sorted(SHIPPED)


@pytest.mark.parametrize("rel", SHIPPED)
def test_dataflow_read_lists_each_scenario_as_its_details_do(client, user_and_token, rel):
    """The projection dataflow.read builds of the project as saved, read
    before the tool's output bound cuts what is past it."""
    from utk_curio.backend.app.agents.application import tools
    from utk_curio.backend.app.agents.repositories import project_agents
    from utk_curio.backend.app.projects import storage
    from utk_curio.backend.app.projects.services import _user_dir_key

    user, token = user_and_token
    spec = _shipped(rel)
    resp = client.post(
        "/api/projects",
        data=json.dumps({"name": spec["dataflow"].get("name") or Path(rel).stem, "spec": spec, "outputs": []}),
        headers=_headers(token),
    )
    assert resp.status_code == 201, resp.get_data(as_text=True)
    project_id = resp.get_json()["id"]

    ukey = _user_dir_key(user)
    saved = project_agents.strip_agent_state(storage.read_spec(ukey, project_id))
    rows = tools._dataflow_projection(saved, ukey, project_id)["scenarios"]
    assert rows, f"dataflow.read lists no scenario of {rel}"
    for row in rows:
        resp = client.get(f"/api/scenarios/{project_id}/{row['id']}", headers=_headers(token))
        assert resp.status_code == 200, resp.get_data(as_text=True)
        details = resp.get_json()
        listed = {part: [entry["id"] for entry in details[part]] for part in ("levers", "context", "outcomes")}
        assert {
            "set": row["set"], "levers": row["nodes"], "context": row["context"], "outcomes": row["outcomes"],
        } == {"set": details["set"]["name"], **listed}, f"{rel}: {row['name']}"
        assert "levers" not in row


def test_example_06_saves_what_stands_for_its_boundary_last_nodes_and_shared_outcomes_and_nothing_else():
    from utk_curio.backend.app.scenario_catalog.domain.parts import scenario_source_node_ids

    spec = _shipped("docs/examples/06-back-bay-road-sunlight.json")
    by_id = {n["id"]: n for n in spec["dataflow"]["nodes"]}
    saved = scenario_source_node_ids(spec)
    # Back Bay layers stands for the Data Pool each scenario's output crosses
    # in from. Each scenario's last nodes: its Roads, which Mean sunlight, a
    # chart, reads, and its map of roads by sunlight, which draws what its
    # Shadow study makes; Two towers removed's map of its buildings draws what
    # its Map Editor node hands on. Sunlight change saves its own, and stands
    # for Roads by sunlight change, a chart.
    assert sorted(by_id[i].get("title") for i in saved) == [
        "Back Bay layers", "Roads", "Roads", "Roads", "Shadow study", "Shadow study", "Shadow study",
        "Sunlight change", "Two towers removed",
    ]
    # No other node of a scenario saves because of it.
    others = {"Buildings by height", "Roads by sunlight"}
    assert not [by_id[i].get("title") for i in saved if by_id[i].get("title") in others]
