"""The Scenario Catalog's scenario sets.

A listing tells each scenario's set. A set's details are its scenarios and
the shared context and outcomes they keep, each node with the ids of the
set's scenarios that use it: some nodes belong to every scenario, some to a
few. A project saved before sets is read with its scenarios grouped and their
lists inferred, the way its next save would keep them.
"""
from __future__ import annotations

import json

COMPUTE = "curio.builtin/computation-analysis@1"


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


def test_a_set_lists_which_scenarios_use_each_shared_node(client, user_and_token):
    _, token = user_and_token
    project_id = _create(client, token, _spec(with_sets=True))
    resp = client.get(f"/api/scenarios/sets/{project_id}/park", headers=_headers(token))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    assert body["set"] == {"id": "park", "name": "Lower Manhattan park shade"}
    assert [s["id"] for s in body["scenarios"]] == ["existing", "towers", "cap"]
    assert {n["id"]: n["scenarios"] for n in body["context"]} == {
        "load": ["existing", "towers", "cap"],
        "around": ["towers", "cap"],
    }
    assert {n["id"]: n["scenarios"] for n in body["outcomes"]} == {
        "chart": ["existing", "towers", "cap"],
        "change": ["existing", "towers"],
    }


def test_a_project_saved_before_sets_reads_grouped(client, user_and_token):
    """Written to disk as an older Curio saved it, past the save that would
    fill the sets in."""
    from utk_curio.backend.app.projects import storage

    user, token = user_and_token
    project_id = _create(client, token, _spec(with_sets=False))
    storage.write_spec(str(user.id), project_id, _spec(with_sets=False))
    items = client.get("/api/scenarios/catalog", headers=_headers(token)).get_json()["items"]
    sets = {i["set"]["id"] for i in items if i["project"]["id"] == project_id}
    assert sets == {"set-existing"}
    body = client.get(f"/api/scenarios/sets/{project_id}/set-existing", headers=_headers(token)).get_json()
    assert body["set"]["name"] == "Park shade"
    assert {n["id"]: n["scenarios"] for n in body["context"]}["around"] == ["towers", "cap"]


def test_an_unknown_set_is_404(client, user_and_token):
    _, token = user_and_token
    project_id = _create(client, token, _spec(with_sets=True))
    resp = client.get(f"/api/scenarios/sets/{project_id}/nope", headers=_headers(token))
    assert resp.status_code == 404
