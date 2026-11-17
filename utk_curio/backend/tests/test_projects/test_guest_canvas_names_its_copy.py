"""A hosted guest's load of an example answers with the id of the guest's own
copy of it (``copy_id``, ``projects/routes.py`` ``get_project``).

In a start of several backend processes a hosted guest's copy belongs to the
process its own id names, as any dataflow does
(``collaboration/owner_guard.py``), so the guest's canvas names the copy, not
the example, in every request and in its room's socket
(``src/utils/requestHeaders.ts``). The load of the example is the page's first
read of it, which any process answers, and its answer is where the page learns
the copy's id: the one the guest's sign-in and the example make, whether or not
the copy is made yet, and the room its tab joins. No read makes the copy. An
account's load names no copy, nor does the local guest's, nor a hosted guest's
load of its own new dataflow, whose page names its own id.

Visitors A and B sign in to the shared guest account as two browsers do, on the
example ``test_guest_copy_leaks.py`` sets up.
"""
from __future__ import annotations

import json

from utk_curio.backend import config
from utk_curio.backend.tests.test_datasets.computed_test_helpers import auth_headers
from utk_curio.backend.tests.test_projects.test_guest_copy_leaks import (  # noqa: F401 - fixtures
    VISITOR_A,
    VISITOR_B,
    _copy_of,
    _node,
    app,
    example,
)


def _answer(client, token: str, project_id: str, **query) -> dict:
    """``GET /api/projects/<id>`` as the canvas of *token*'s visitor asks it."""
    resp = client.get(f"/api/projects/{project_id}", query_string=query, headers=auth_headers(token))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return resp.get_json()


def test_a_hosted_guests_load_of_an_example_names_its_own_copy_before_the_copy_is_made(client, example):
    from utk_curio.backend.app.projects import visitor_copies

    for token in (VISITOR_A, VISITOR_B):
        # A canvas asks for the results it was left with; a dashboard that
        # loads its own data asks for the saved ones.
        for query in ({"results": "last"}, {}):
            named = _answer(client, token, example, **query).get("copy_id")
            assert named == _copy_of(token, example), (
                f"{token}'s load {query} names {named!r}, not its own copy {_copy_of(token, example)}"
            )

    mine, theirs = _copy_of(VISITOR_A, example), _copy_of(VISITOR_B, example)
    assert len({mine, theirs, example}) == 3, "two visitors' copies of the example share an id"
    assert not visitor_copies.is_copy(mine) and not visitor_copies.is_copy(theirs), "a load made a copy"


def test_the_copy_a_load_names_is_the_one_the_guests_change_made(client, example):
    """A rename is the visitor's own change, which makes its copy: the load
    after it names that copy, which holds the change, and B's load names B's."""
    from utk_curio.backend.app.common.user_storage import GUEST_KEY
    from utk_curio.backend.app.projects import storage

    renamed = client.put(f"/api/projects/{example}", data=json.dumps({"name": "Mine"}),
                         headers=auth_headers(VISITOR_A))
    assert renamed.status_code == 200, renamed.get_data(as_text=True)

    mine = _answer(client, VISITOR_A, example, results="last")
    assert mine["copy_id"] == _copy_of(VISITOR_A, example)
    assert storage.read_spec(GUEST_KEY, mine["copy_id"])["dataflow"]["name"] == "Mine"
    assert _answer(client, VISITOR_B, example)["copy_id"] == _copy_of(VISITOR_B, example)


def test_an_accounts_load_names_no_copy(client, user_and_token):
    _user, token = user_and_token
    created = client.post("/api/projects", data=json.dumps({
        "name": "Hers", "spec": {"dataflow": {"name": "Hers", "nodes": [_node("a")], "edges": []}}, "outputs": [],
    }), headers=auth_headers(token))
    assert created.status_code == 201, created.get_data(as_text=True)

    answer = _answer(client, token, created.get_json()["id"], results="last")

    assert "copy_id" in answer and answer["copy_id"] is None, answer.get("copy_id")


def test_the_local_guests_load_names_no_copy(client, example, monkeypatch):
    """Without sign-in the shared guest is the one local user, whose example
    is its own dataflow: no copy is made of it, so none is named."""
    monkeypatch.setattr(config, "CURIO_NO_AUTH", True)

    answer = _answer(client, VISITOR_A, example, results="last")

    assert "copy_id" in answer and answer["copy_id"] is None, answer.get("copy_id")


def test_a_hosted_guests_load_of_its_own_new_dataflow_names_no_copy(client, example):
    """A visitor's File > New copies no dataflow: its page names its own id."""
    created = client.post("/api/projects", data=json.dumps({
        "name": "New", "spec": {"dataflow": {"name": "New", "nodes": [_node("a")], "edges": []}}, "outputs": [],
    }), headers=auth_headers(VISITOR_A))
    assert created.status_code == 201, created.get_data(as_text=True)
    assert created.get_json()["kept_for_visit"] is True

    answer = _answer(client, VISITOR_A, created.get_json()["id"], results="last")

    assert "copy_id" in answer and answer["copy_id"] is None, answer.get("copy_id")
