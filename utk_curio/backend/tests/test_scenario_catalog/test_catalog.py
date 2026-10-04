"""The Scenario Catalog (#662): every scenario in the account's projects.

Scenarios live in projects, so the catalog stores nothing: its listing is read
off the project summaries, and a scenario's details off its project's spec and
the outputs the project saved to the Data Catalog. So:

* the listing holds every scenario of every project, keyed by project and
  scenario, with its project and a plain-box preview of its graph;
* another account's scenarios are neither listed nor readable;
* a deleted project's scenarios are gone, and an edit shows at once;
* a scenario's details name its fixed context, levers and outcomes, each with
  the output its project saved for it, and never a path on this machine.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_scenario_catalog -v
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from utk_curio.backend.app.datasets.install.installer import computed_dataset_id

BASELINE = {"id": "s1", "name": "Baseline", "color": "#2a9d8f", "description": "Today's heights", "nodes": ["a", "chart"]}
TALL = {"id": "s2", "name": "Twice as tall", "color": "#e76f51", "nodes": ["b"]}


def _headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _node(node_id, kind="computation-analysis", content="return arg", x=0):
    return {"id": node_id, "type": f"curio.builtin/{kind}@1", "content": content, "x": x, "y": 0}


def _spec(name, scenarios):
    """A loader feeding two branches: ``a`` into a chart, and ``b``."""
    return {
        "dataflow": {
            "name": name,
            "nodes": [
                _node("load", "data-loading", "return 1"),
                _node("a", x=300),
                _node("chart", "vis-vega", "{}", x=600),
                _node("b", x=300),
            ],
            "edges": [
                {"id": "e1", "source": "load", "target": "a"},
                {"id": "e2", "source": "a", "target": "chart"},
                {"id": "e3", "source": "load", "target": "b"},
            ],
            "scenarios": scenarios,
        }
    }


def _create(client, token, name, scenarios):
    resp = client.post(
        "/api/projects",
        data=json.dumps({"name": name, "spec": _spec(name, scenarios), "outputs": []}),
        headers=_headers(token),
    )
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()["id"]


def _listing(client, token, q=None):
    """The account's own scenarios: the examples Curio seeds may hold some."""
    url = "/api/scenarios/catalog" + (f"?q={q}" if q else "")
    resp = client.get(url, headers=_headers(token))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return [i for i in resp.get_json()["items"] if not i["project"]["isExample"]]


def _details(client, token, project_id, scenario_id):
    return client.get(f"/api/scenarios/{project_id}/{scenario_id}", headers=_headers(token))


def test_the_listing_holds_every_scenario_across_projects(client, user_and_token):
    _, token = user_and_token
    first = _create(client, token, "Shadows", [BASELINE, TALL])
    second = _create(client, token, "Floods", [{**TALL, "name": "No NbS"}])
    _create(client, token, "No scenarios", [])

    items = _listing(client, token)

    assert sorted((i["project"]["name"], i["name"]) for i in items) == [
        ("Floods", "No NbS"), ("Shadows", "Baseline"), ("Shadows", "Twice as tall"),
    ]
    baseline = next(i for i in items if i["key"] == f"{first}/s1")
    assert baseline["id"] == "s1"
    assert baseline["color"] == "#2a9d8f"
    assert baseline["description"] == "Today's heights"
    assert baseline["nodeCount"] == 2
    assert baseline["project"]["id"] == first
    assert baseline["project"]["isExample"] is False
    # The project's graph, for the card to draw with the scenario's nodes marked.
    assert {n["id"] for n in baseline["preview"]["nodes"]} == {"load", "a", "chart", "b"}
    assert {(e["source"], e["target"]) for e in baseline["preview"]["edges"]} == {
        ("load", "a"), ("a", "chart"), ("load", "b"),
    }
    # Two projects may hold a scenario with one id: a copy keeps its ids.
    assert {i["key"] for i in items if i["id"] == "s2"} == {f"{first}/s2", f"{second}/s2"}


def test_a_search_matches_the_name_the_description_and_the_project(client, user_and_token):
    _, token = user_and_token
    _create(client, token, "Shadows", [BASELINE, TALL])
    _create(client, token, "Floods", [{**TALL, "name": "No NbS"}])

    assert [i["name"] for i in _listing(client, token, q="tall")] == ["Twice as tall"]
    assert [i["name"] for i in _listing(client, token, q="heights")] == ["Baseline"]
    assert [i["name"] for i in _listing(client, token, q="floods")] == ["No NbS"]


def test_another_accounts_scenarios_are_neither_listed_nor_readable(
    client, user_and_token, other_user_and_token
):
    _, token = user_and_token
    _, other_token = other_user_and_token
    theirs = _create(client, other_token, "Their study", [BASELINE])

    assert _listing(client, token) == []
    resp = _details(client, token, theirs, "s1")
    assert resp.status_code == 404
    assert _details(client, other_token, theirs, "s1").status_code == 200


def test_a_deleted_projects_scenarios_are_gone(client, user_and_token):
    _, token = user_and_token
    project_id = _create(client, token, "Shadows", [BASELINE])
    assert [i["key"] for i in _listing(client, token)] == [f"{project_id}/s1"]

    resp = client.delete(f"/api/projects/{project_id}", headers=_headers(token))
    assert resp.status_code in (200, 204), resp.get_data(as_text=True)

    assert _listing(client, token) == []
    assert _details(client, token, project_id, "s1").status_code == 404


def test_an_edit_to_the_project_is_an_edit_to_its_scenario(client, user_and_token):
    _, token = user_and_token
    project_id = _create(client, token, "Shadows", [BASELINE])

    resp = client.put(
        f"/api/projects/{project_id}",
        data=json.dumps({"spec": _spec("Shadows", [{**BASELINE, "name": "Existing", "nodes": ["a"]}])}),
        headers=_headers(token),
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)

    [item] = _listing(client, token)
    assert (item["name"], item["nodeCount"]) == ("Existing", 1)
    assert [n["id"] for n in _details(client, token, project_id, "s1").get_json()["levers"]] == ["a"]


def test_an_unknown_scenario_is_not_found(client, user_and_token):
    _, token = user_and_token
    project_id = _create(client, token, "Shadows", [BASELINE])

    resp = _details(client, token, project_id, "nope")

    assert resp.status_code == 404
    assert resp.get_json()["error"] == "Shadows has no scenario nope"


def test_the_details_name_context_levers_and_outcomes_with_their_saved_outputs(client, user_and_token):
    _, token = user_and_token
    project_id = _create(client, token, "Shadows", [BASELINE])
    shared = Path(os.environ["CURIO_SHARED_DATA"])
    (shared / "load_out.csv").write_text("id,height\n1,10\n", encoding="utf-8")
    (shared / "a_out.csv").write_text("id,sunlight\n1,0.5\n", encoding="utf-8")
    resp = client.put(
        f"/api/projects/{project_id}",
        data=json.dumps({"outputs": [
            {"node_id": "load", "filename": "load_out.csv"},
            {"node_id": "a", "filename": "a_out.csv"},
        ]}),
        headers=_headers(token),
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)

    resp = _details(client, token, project_id, "s1")
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()

    assert (body["key"], body["name"], body["project"]["name"]) == (f"{project_id}/s1", "Baseline", "Shadows")
    assert [n["id"] for n in body["context"]] == ["load"]
    assert [n["id"] for n in body["levers"]] == ["a", "chart"]
    assert [n["id"] for n in body["outcomes"]] == ["chart"]
    assert body["outcomes"][0]["type"] == "curio.builtin/vis-vega@1"
    # The chart saves nothing itself: what it draws is node a's saved output.
    [outcome] = body["outcomes"][0]["results"]
    assert (outcome["datasetId"], outcome["nodeId"]) == (computed_dataset_id("a", project_id), "a")
    [context] = body["context"][0]["results"]
    assert (context["datasetId"], context["nodeId"]) == (computed_dataset_id("load", project_id), "load")
    assert "path" not in json.dumps(body["context"] + body["levers"] + body["outcomes"])


def test_a_shared_parameter_is_context_with_its_value(client, user_and_token):
    _, token = user_and_token
    spec = _spec("Shadows", [{**TALL, "nodes": ["b"]}])
    spec["dataflow"]["nodes"].append({
        "id": "season", "type": "curio.builtin/parameter@1", "content": "", "x": 0, "y": 300,
        "metadata": {"widgets": [{"name": "season", "type": "text", "default": "winter", "value": "summer"}]},
    })
    spec["dataflow"]["nodes"][3]["content"] = "return [!! @season !!]"
    resp = client.post(
        "/api/projects",
        data=json.dumps({"name": "Shadows", "spec": spec, "outputs": []}),
        headers=_headers(token),
    )
    assert resp.status_code == 201, resp.get_data(as_text=True)
    project_id = resp.get_json()["id"]

    body = _details(client, token, project_id, "s2").get_json()

    assert [n["id"] for n in body["context"]] == ["load", "season"]
    season = body["context"][1]
    assert season["parameter"] == {"name": "season", "value": "summer"}
    assert season["results"] == []


def test_the_catalog_needs_a_signed_in_account(client):
    assert client.get("/api/scenarios/catalog").status_code == 401
    assert client.get("/api/scenarios/p/s").status_code == 401
