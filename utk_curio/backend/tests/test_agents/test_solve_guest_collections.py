"""A hosted guest's Solve loads the collection that guest added, as their Play does, and no other guest's does.

Every hosted guest (a guest on a Curio started with ``--deploy``) signs in to
the one shared guest account. A collection a guest adds to the Data Catalog, as
a download from the Discovery Catalog adds one, is named after their visit and
lists only where their sign-in is served (``projects/visitor_copies.py``), and
their agents work on a copy of the example of their own. Solve runs each
attempt it checks on a thread of its own (``VerifiedRounds._validate_with``),
which serves no sign-in, and the collections an attempt's slice loads were
looked up there, so the guest's own collection was not found and the sandbox
was sent none.

Here guest A adds a collection, the example's Data Loading node loads it, and
A's agent on the node after it solves that node from its chat: the attempt
runs the loader first. B, another guest, solves the same node in B's own copy.
These tests sign the two visitors in as ``test_guest_copy_leaks.py`` does.

Every test imports what it tests inside itself, so a checkout without it fails
test by test.
"""
from __future__ import annotations

from utk_curio.backend.tests._support.agent_routes import _auth
from utk_curio.backend.tests.test_projects.test_guest_copy_leaks import (  # noqa: F401  (fixtures)
    VISITOR_A,
    VISITOR_B,
    app,
    example,
)

NB = "agent.curio.node-builder@1"


def _solve_the_node_after_the_loader(client, token: str, example: str, monkeypatch) -> list[dict]:
    """The visitor signed in as *token* adds the Node Builder to the
    example, which makes their copy of it, and solves the node after the
    loader from its agent's chat, the sandbox stood in for: what each node of
    each attempt sent the sandbox, in order."""
    from utk_curio.backend.tests.test_agents.test_routes_solve import TestStreamedSolve
    from utk_curio.backend.tests.test_agents.test_run_node_datasets import ATTACHMENT

    sent: list[dict] = []

    def _exec(_endpoint, payload):
        sent.append(payload)
        return {"stdout": [], "stderr": "", "output": {"path": f"art-{len(sent)}", "dataType": "dataframe"}}

    monkeypatch.setattr("utk_curio.backend.app.execution.runner._http_exec", _exec)
    installed = client.post(f"/api/agents/projects/{example}/install", json={"coord": NB}, headers=_auth(token))
    assert installed.status_code == 201, installed.get_data(as_text=True)
    solved = client.post(
        f"/api/agents/projects/{example}/attachments/{ATTACHMENT}/solve-node",
        json={"nodeId": "after"}, headers=_auth(token),
    )
    assert solved.status_code == 200, solved.get_data(as_text=True)
    events = TestStreamedSolve()._sse_events(solved)
    assert sent, f"the Solve never reached the sandbox: {events[-1]}"
    return sent


def test_a_hosted_guests_solve_loads_the_collection_they_added_alone(
    client, example, tmp_path, monkeypatch,
):
    from utk_curio.backend import config
    from utk_curio.backend.app.agents.application.turns import titles
    from utk_curio.backend.app.common.user_storage import GUEST_KEY
    from utk_curio.backend.app.discovery.infrastructure import storage
    from utk_curio.backend.app.projects import visitor_copies
    from utk_curio.backend.app.users.models import User
    from utk_curio.backend.tests.test_agents.test_routes_proposals import TestNodeCreate
    from utk_curio.backend.tests.test_agents.test_verified_rounds import TEMPLATES
    from utk_curio.backend.tests.test_datasets.test_editor_datasets import REPO, _a_collection
    from utk_curio.backend.tests.test_projects.test_guest_own_imports import _with_a_loader

    monkeypatch.setenv(storage.ENV_ROOT, str(REPO / "discovery"))
    guest = User.query.filter_by(username=config.CURIO_SHARED_GUEST_USERNAME).one()
    # Recordings in a folder of the shipped storage source, added as A's
    # download adds them: on a thread that serves A's sign-in.
    with visitor_copies.serving(VISITOR_A):
        collection = _a_collection(guest, tmp_path)
    _with_a_loader(example, collection)
    TestNodeCreate()._write_builtin_package(GUEST_KEY, templates=TEMPLATES)

    def _model(config_, messages, **kwargs):
        if messages and messages[0].get("content") == titles.title_prompt():
            return "Title"
        return "return input_0"

    monkeypatch.setattr("utk_curio.backend.app.agents.infrastructure.providers.run_chat_turn", _model)

    loading = _solve_the_node_after_the_loader(client, VISITOR_A, example, monkeypatch)[0]
    # The loader is sent the path of the collection's index, as for A's run
    # from the agent's chat ...
    assert collection in (loading.get("dataset_paths") or {}), loading.get("dataset_paths")
    # ... and where its files are.
    assert set(loading.get("collections") or {}) == {collection}, (
        f"A's Solve sent the loader of {collection} the collections {loading.get('collections')}"
    )

    others = _solve_the_node_after_the_loader(client, VISITOR_B, example, monkeypatch)[0]
    assert collection not in (others.get("dataset_paths") or {}), others.get("dataset_paths")
    assert not others.get("collections"), others.get("collections")
