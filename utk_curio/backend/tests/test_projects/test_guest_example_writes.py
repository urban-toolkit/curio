"""A hosted guest's package add or removal on an example lands in its own copy
of it, and its scenario drop into an example is refused: either way the
example stays as it was.

Every hosted guest (a guest on a Curio started with ``--deploy``) signs in to
the one shared guest account, which owns the examples, so a write a guest
makes to an example reaches every other guest who opens it. A package added
to or removed from the dataflow is an edit to it, kept in the guest's own copy
(``projects/visitor_copies.py``), and it prunes nothing from the store every
guest reads. A scenario drop needs a run on the server, which a hosted guest
does not get, so it is refused, as the page refuses it before it sends one.
These tests send them as a request would, as visitor A, with visitor B reading
the example after. Each example is set up as the local guest sets one up,
with sign-in off, as ``test_guest_copy_leaks.py`` does.
"""
from __future__ import annotations

import io
import json

import pandas as pd

from utk_curio.backend import config
from utk_curio.backend.app.common.user_storage import GUEST_KEY
from utk_curio.backend.app.projects import storage
from utk_curio.backend.tests.test_datasets.computed_test_helpers import auth_headers, store_sandbox_artifact
from utk_curio.backend.tests.test_projects.test_guest_copy_leaks import (  # noqa: F401 - fixtures
    VISITOR_A,
    VISITOR_B,
    _copy_of,
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


def _remove(client, token, project_id):
    return client.delete(f"/api/packages/projects/{project_id}/{PACKAGE}", headers=auth_headers(token))


def _lockfile(client, token, project_id) -> list[str]:
    """The packages the dataflow's lockfile names, as *token*'s visitor reads it."""
    read = client.get(f"/api/packages/projects/{project_id}", headers=auth_headers(token))
    assert read.status_code == 200, read.get_data(as_text=True)
    return read.get_json()["packages"]


def _in_the_copy(token, project_id) -> list[str] | None:
    """The packages the lockfile of *token*'s visitor's own copy of the
    dataflow names, as written on disk; None while that visitor has no copy."""
    spec = storage.read_spec(GUEST_KEY, _copy_of(token, project_id))
    return None if spec is None else list(spec["dataflow"].get("packages") or [])


def _in_the_store() -> bool:
    """Whether the guest account's package store, which every guest reads,
    holds the package."""
    from utk_curio.backend.app.packages.repositories.store import package_dir

    return package_dir(GUEST_KEY, PACKAGE).is_dir()


def test_a_hosted_guests_package_install_into_an_example_lands_in_its_own_copy(
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

    installed = _install(client, VISITOR_A, example)

    assert installed.status_code == 201, installed.get_data(as_text=True)
    assert PACKAGE in installed.get_json()["packages"]
    copied = _in_the_copy(VISITOR_A, example)
    assert copied is not None and PACKAGE in copied, f"A's own copy of the example names {copied}"
    assert PACKAGE in _lockfile(client, VISITOR_A, example)
    assert PACKAGE not in _lockfile(client, VISITOR_B, example)
    assert _digests(example) == before


def test_a_hosted_guests_package_removal_from_an_example_lands_in_its_own_copy(
    client, example, monkeypatch,
):
    # The example names the package: the local guest added it.
    monkeypatch.setattr(config, "CURIO_NO_AUTH", True)
    added = _install(client, VISITOR_A, example)
    assert added.status_code == 201, added.get_data(as_text=True)
    monkeypatch.setattr(config, "CURIO_NO_AUTH", False)
    before = _digests(example)

    removed = _remove(client, VISITOR_A, example)

    assert removed.status_code == 200, removed.get_data(as_text=True)
    assert PACKAGE not in removed.get_json()["packages"]
    copied = _in_the_copy(VISITOR_A, example)
    assert copied is not None and PACKAGE not in copied, f"A's own copy of the example names {copied}"
    assert PACKAGE not in _lockfile(client, VISITOR_A, example)
    assert PACKAGE in _lockfile(client, VISITOR_B, example)
    assert _digests(example) == before
    assert _in_the_store(), "A's removal took the package out of the store every guest reads"


def test_a_hosted_guests_package_removal_prunes_nothing_from_the_store_every_guest_reads(
    client, example, monkeypatch,
):
    from utk_curio.backend.app.packages.repositories import defaults

    # The package is in the guest account's store and in its list for all
    # projects, and no dataflow names it: the local guest added it to the
    # account alone.
    monkeypatch.setattr(config, "CURIO_NO_AUTH", True)
    stored = client.post("/api/packages/catalog/install", data=json.dumps({"dirName": PACKAGE}),
                         headers=auth_headers(VISITOR_A))
    assert stored.status_code == 201, stored.get_data(as_text=True)
    monkeypatch.setattr(config, "CURIO_NO_AUTH", False)
    defaults.add_to_defaults(GUEST_KEY, PACKAGE)
    before = _digests(example)

    added = _install(client, VISITOR_A, example)
    assert added.status_code == 201, added.get_data(as_text=True)
    removed = _remove(client, VISITOR_A, example)

    assert removed.status_code == 200, removed.get_data(as_text=True)
    answer = removed.get_json()
    assert (answer["pruned"], answer["removedFromDefaults"]) == ([], []), answer
    assert _in_the_store(), "A's removal took the package out of the store every guest reads"
    assert PACKAGE in defaults.load_defaults(GUEST_KEY), "A's removal took the package out of every guest's defaults"
    assert PACKAGE not in _lockfile(client, VISITOR_B, example)
    assert _digests(example) == before


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
