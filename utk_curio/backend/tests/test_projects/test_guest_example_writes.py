"""What would write an example every hosted guest opens is refused to a hosted
guest, and leaves the example as it was.

Every hosted guest (a guest on a Curio started with ``--deploy``) signs in to
the one shared guest account, which owns the examples, so a write a guest
makes to an example reaches every other guest who opens it. The page refuses
a guest's package add and scenario drop before it sends one; these tests send
them as a request would, as visitor A, with visitor B reading the example
after. Each example is set up as the local guest sets one up, with sign-in
off, as ``test_guest_copy_leaks.py`` does.
"""
from __future__ import annotations

import io
import json

import pandas as pd

from utk_curio.backend import config
from utk_curio.backend.tests.test_datasets.computed_test_helpers import auth_headers, store_sandbox_artifact
from utk_curio.backend.tests.test_projects.test_guest_copy_leaks import (  # noqa: F401 - fixtures
    VISITOR_A,
    VISITOR_B,
    _digests,
    app,
    example,
)

#: A package of the Node Catalog with no library of its own, so an install
#: copies it into the account's store and runs no pip.
PACKAGE = "curio.vega-lite@1"


def _create(client, token, name, spec) -> str:
    created = client.post("/api/projects", data=json.dumps({"name": name, "spec": spec, "outputs": []}),
                          headers=auth_headers(token))
    assert created.status_code == 201, created.get_data(as_text=True)
    return created.get_json()["id"]


def _install(client, token, project_id):
    return client.post(f"/api/packages/projects/{project_id}/install", data=json.dumps({"dirName": PACKAGE}),
                       headers=auth_headers(token))


def _lockfile(client, token, project_id) -> list[str]:
    """The packages the dataflow's lockfile names, as *token*'s visitor reads it."""
    read = client.get(f"/api/packages/projects/{project_id}", headers=auth_headers(token))
    assert read.status_code == 200, read.get_data(as_text=True)
    return read.get_json()["packages"]


def test_a_hosted_guests_package_install_into_an_example_is_refused_and_changes_nothing(
    client, example, monkeypatch,
):
    # The package is in the guest account's store: the local guest added it
    # to a dataflow of its own, which copied it there.
    monkeypatch.setattr(config, "CURIO_NO_AUTH", True)
    scratch = _create(client, VISITOR_A, "Scratch", {"dataflow": {"name": "Scratch", "nodes": [], "edges": []}})
    added = _install(client, VISITOR_A, scratch)
    assert added.status_code == 201, added.get_data(as_text=True)
    monkeypatch.setattr(config, "CURIO_NO_AUTH", False)
    before = _digests(example)

    refused = _install(client, VISITOR_A, example)

    assert refused.status_code == 403, refused.get_data(as_text=True)
    assert _digests(example) == before
    assert PACKAGE not in _lockfile(client, VISITOR_B, example)


def test_a_hosted_guests_package_removal_from_an_example_is_refused_and_changes_nothing(
    client, example, monkeypatch,
):
    # The example names the package: the local guest added it.
    monkeypatch.setattr(config, "CURIO_NO_AUTH", True)
    added = _install(client, VISITOR_A, example)
    assert added.status_code == 201, added.get_data(as_text=True)
    monkeypatch.setattr(config, "CURIO_NO_AUTH", False)
    before = _digests(example)

    refused = client.delete(f"/api/packages/projects/{example}/{PACKAGE}", headers=auth_headers(VISITOR_A))

    assert refused.status_code == 403, refused.get_data(as_text=True)
    assert _digests(example) == before
    assert PACKAGE in _lockfile(client, VISITOR_B, example)


def _node(node_id, kind="python-computation", content="return input_0", x=0):
    return {"id": node_id, "type": f"curio.builtin/{kind}@1", "content": content, "x": x, "y": 0}


def test_a_hosted_guests_scenario_drop_into_an_example_is_refused_and_changes_nothing(
    client, example, monkeypatch,
):
    # A dataflow of the guest account with a scenario whose context and own
    # last node have saved outputs, so a drop of it needs no run: the local
    # guest made it and saved them.
    monkeypatch.setattr(config, "CURIO_NO_AUTH", True)
    source = _create(client, VISITOR_A, "Shadows", {"dataflow": {
        "name": "Shadows",
        "nodes": [_node("load", "data-loading", "return 1"), _node("a", x=300), _node("chart", "vis-vega", "{}", x=600)],
        "edges": [
            {"id": "e1", "source": "load", "target": "a", "sourceHandle": "out", "targetHandle": "in"},
            {"id": "e2", "source": "a", "target": "chart", "sourceHandle": "out", "targetHandle": "in"},
        ],
        "scenarios": [{"id": "s1", "name": "Baseline", "color": "#2a9d8f", "nodes": ["a"]}],
    }})
    outputs = [
        {"node_id": node, "filename": store_sandbox_artifact(pd.read_csv(io.StringIO(text)), node_id=node)}
        for node, text in (("load", "id,height\n1,10\n"), ("a", "id,sunlight\n1,0.5\n"))
    ]
    saved = client.put(f"/api/projects/{source}", data=json.dumps({"outputs": outputs}),
                       headers=auth_headers(VISITOR_A))
    assert saved.status_code == 200, saved.get_data(as_text=True)
    monkeypatch.setattr(config, "CURIO_NO_AUTH", False)
    before = _digests(example)

    refused = client.post(f"/api/scenarios/{source}/s1/copy", data=json.dumps({
        "targetProjectId": example,
        "outputs": [{"source": "load", "node": "loader-1"}, {"source": "a", "node": "a-copy"}],
    }), headers=auth_headers(VISITOR_A))

    assert refused.status_code == 403, refused.get_data(as_text=True)
    assert _digests(example) == before
    opened = client.get(f"/api/projects/{example}", headers=auth_headers(VISITOR_B))
    assert opened.status_code == 200, opened.get_data(as_text=True)
    assert opened.get_json()["outputs"] == []
