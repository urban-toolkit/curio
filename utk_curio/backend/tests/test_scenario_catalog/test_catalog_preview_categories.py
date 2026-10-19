"""The Scenario Catalog draws a scenario's project with each node's category.

A scenario's card and its details draw its project's graph as the Projects
page does (``test_projects/test_preview_categories.py``): each box's bar is
the color of the ``category`` the node's template declares, read off the
account's manifests and the catalog's, and a node type no manifest holds gets
none. A package in the account's store counts.

Each test imports what it uses from the app inside its body, so a module that
cannot import fails these tests and nothing else.
"""
from __future__ import annotations

import io
import json
import zipfile

SCENARIO = {"id": "s1", "name": "Wet year", "color": "#2a9d8f", "nodes": ["gauge"]}
#: What each node of the project is drawn with.
CATEGORIES = {"load": "data", "gauge": "vis_simple", "gone": None}


def _headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _archive() -> bytes:
    """A ``.curio.zip`` of ``acme.hydro``, whose one template, ``gauge``,
    declares the ``vis_simple`` category."""
    manifest = {
        "id": "acme.hydro",
        "version": "1.0.0",
        "name": "Hydro",
        "publisher": "Test",
        "description": "Test package",
        "license": "MIT",
        "compatibility": {"curioRuntime": ">=0.5.0", "major": 1},
        "permissions": [],
        "dependencies": {"packages": {}, "python": {}, "js": {}},
        "createdAt": "2026-06-01T12:00:00Z",
        "templates": [{
            "id": "gauge",
            "label": "Gauge",
            "category": "vis_simple",
            "engine": "python",
            "editor": "code",
            "hasCode": True,
            "hasWidgets": False,
            "hasGrammar": False,
            "inputPorts": [{"types": ["DATAFRAME"], "cardinality": "1"}],
            "outputPorts": [{"types": ["JSON"], "cardinality": "1"}],
            "templateDir": "starters/gauge",
            "defaultTemplate": "starters/gauge/Default.py",
        }],
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest, indent=2))
        archive.writestr("starters/gauge/Default.py", "def run():\n    return {}\n")
    return buffer.getvalue()


def _create(client, token) -> str:
    """A project of a built-in loader feeding the account's gauge, beside a
    node of a package no manifest holds, with one scenario."""
    spec = {
        "dataflow": {
            "name": "Gauges",
            "nodes": [
                {"id": "load", "type": "curio.builtin/data-loading@1", "content": "return 1", "x": 0, "y": 0},
                {"id": "gauge", "type": "acme.hydro/gauge@1", "content": "return input_0", "x": 300, "y": 0},
                {"id": "gone", "type": "acme.gone/gauge@1", "content": "", "x": 600, "y": 0},
            ],
            "edges": [{"id": "e1", "source": "load", "target": "gauge"}],
            "scenarios": [SCENARIO],
        }
    }
    resp = client.post(
        "/api/projects",
        data=json.dumps({"name": "Gauges", "spec": spec, "outputs": []}),
        headers=_headers(token),
    )
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()["id"]


def _categories(preview: dict) -> dict:
    return {node["id"]: node["category"] for node in preview["nodes"]}


def test_a_scenarios_card_and_details_give_each_node_its_category(client, user_and_token):
    from utk_curio.backend.app.packages import service as packages_service

    user, token = user_and_token
    packages_service.install_package_from_archive(str(user.id), _archive())
    project_id = _create(client, token)

    resp = client.get("/api/scenarios/catalog", headers=_headers(token))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    item = next(i for i in resp.get_json()["items"] if i["key"] == f"{project_id}/s1")
    assert _categories(item["preview"]) == CATEGORIES

    resp = client.get(f"/api/scenarios/{project_id}/s1", headers=_headers(token))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert _categories(resp.get_json()["preview"]) == CATEGORIES
