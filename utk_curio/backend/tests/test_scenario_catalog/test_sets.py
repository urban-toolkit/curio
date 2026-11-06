"""The Scenario Catalog's scenario sets.

A listing tells each scenario's set, and marks the shared context and shared
outcomes each scenario keeps: some nodes belong to every scenario of a set,
some to a few. A project saved before sets is read with its scenarios grouped
and their lists inferred, the way its next save would keep them.
"""
from __future__ import annotations

import json

COMPUTE = "curio.builtin/python-computation@1"


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _node(node_id: str) -> dict:
    return {"id": node_id, "type": COMPUTE, "content": "return input_0", "x": 0, "y": 0}


def _spec(with_sets: bool) -> dict:
    """Three scenarios: two of them read a node the third does not, and a
    pair feeds a change node."""
    ids = ["load", "around", "e", "t", "c", "chart", "change"]
    edges = [("load", "e"), ("load", "around"), ("around", "t"), ("around", "c"),
             ("e", "chart"), ("t", "chart"), ("c", "chart"), ("e", "change"), ("t", "change")]
    scenarios = [
        {"id": "existing", "name": "Existing", "color": "#2a9d8f", "nodes": ["e"]},
        {"id": "towers", "name": "Towers removed", "color": "#e76f51", "nodes": ["t"]},
        {"id": "cap", "name": "Height cap", "color": "#6a4c93", "nodes": ["c"]},
    ]
    dataflow = {
        "name": "Park shade",
        "nodes": [_node(i) for i in ids],
        "edges": [{"id": f"{a}-{b}", "source": a, "target": b} for a, b in edges],
        "scenarios": scenarios,
    }
    if with_sets:
        dataflow["scenarioSets"] = [{"id": "park", "name": "Lower Manhattan park shade"}]
        for s in scenarios:
            s["set"] = "park"
    return {"dataflow": dataflow}


def _create(client, token: str, spec: dict) -> str:
    resp = client.post("/api/projects", data=json.dumps({"name": "Park shade", "spec": spec}), headers=_headers(token))
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()["id"]


def test_a_listing_tells_each_scenario_s_set(client, user_and_token):
    _, token = user_and_token
    project_id = _create(client, token, _spec(with_sets=True))
    items = client.get("/api/scenarios/catalog", headers=_headers(token)).get_json()["items"]
    mine = [i for i in items if i["project"]["id"] == project_id]
    assert {i["name"]: i["set"] for i in mine} == {
        name: {"id": "park", "name": "Lower Manhattan park shade"}
        for name in ("Existing", "Towers removed", "Height cap")
    }


def _marks(client, token: str, project_id: str) -> dict:
    items = client.get("/api/scenarios/catalog", headers=_headers(token)).get_json()["items"]
    return {i["id"]: i for i in items if i["project"]["id"] == project_id}


def test_each_scenario_of_a_set_marks_the_shared_nodes_it_uses(client, user_and_token):
    """Some shared nodes belong to every scenario of the set, some to a few."""
    _, token = user_and_token
    project_id = _create(client, token, _spec(with_sets=True))
    rows = _marks(client, token, project_id)
    assert list(rows) == ["existing", "towers", "cap"]
    assert {i: (r["marks"]["context"], r["marks"]["outcomes"]) for i, r in rows.items()} == {
        "existing": (["load"], ["chart", "change"]),
        "towers": (["load", "around"], ["chart", "change"]),
        "cap": (["load", "around"], ["chart"]),
    }


def test_a_project_saved_before_sets_reads_grouped(client, user_and_token):
    """Written to disk as an older Curio saved it, past the save that would
    fill the sets in."""
    from utk_curio.backend.app.projects import storage

    user, token = user_and_token
    project_id = _create(client, token, _spec(with_sets=False))
    storage.write_spec(str(user.id), project_id, _spec(with_sets=False))
    rows = _marks(client, token, project_id)
    assert {r["set"]["id"] for r in rows.values()} == {"set-existing"}
    assert {r["set"]["name"] for r in rows.values()} == {"Park shade"}
    assert [i for i, r in rows.items() if "around" in r["marks"]["context"]] == ["towers", "cap"]
