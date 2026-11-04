"""A hosted guest's agents work on a copy of their own (``projects/visitor_copies.py``).

Every hosted guest signs in to the one shared guest account, which owns the
shared examples, and an agent's work lives in the dataflow it works on: its
attachment, its chat, the changes it makes. These tests sign two visitors in to
that account, as two browsers do, and give one of them an agent that adds a
node to an example. Each test imports what main lacks inside itself, so a
checkout without the copies fails here test by test."""

from __future__ import annotations

import pytest

from utk_curio.backend import config
from utk_curio.backend.app.common.user_storage import GUEST_KEY
from utk_curio.backend.app.projects import storage
from utk_curio.backend.tests._support.agent_routes import _auth
from utk_curio.backend.tests.test_agents import test_routes_proposals

#: Two visitors' sign-ins to the shared guest account.
VISITOR_A = "hosted-guest-visitor-a"
VISITOR_B = "hosted-guest-visitor-b"
COORD = "agent.curio.node-builder@1"
CREATE = (
    '```curio.v1\n{"toolRequest": {"tool": "node.create", "params": '
    '{"nodeType": "curio.builtin/computation-analysis", "content": "print(\'mine\')"}}}\n```'
)
WRITE = (
    '```curio.v1\n{"toolRequest": {"tool": "node.content.write", "params": '
    '{"nodeId": "%s", "content": "print(\'mine, again\')"}}}\n```'
)


@pytest.fixture()
def shared_example(client, db, tmp_curio, monkeypatch):
    """An example the shared guest owns, and two hosted guests, VISITOR_A and
    VISITOR_B, signed in to that account. The example is saved as the local
    guest saves one, with sign-in off; the visitors come with it on, as on a
    Curio started with ``--deploy``, on the guests' LLM configuration."""
    from utk_curio.backend.app.users.models import User, UserSession

    guest = User(username=config.CURIO_SHARED_GUEST_USERNAME, name="Guest",
                 email="guest@test.com", is_guest=True)
    db.session.add(guest)
    db.session.flush()
    db.session.add(UserSession(user_id=guest.id, token=VISITOR_A))
    db.session.add(UserSession(user_id=guest.id, token=VISITOR_B))
    db.session.commit()
    monkeypatch.setattr(config, "CURIO_NO_AUTH", True)
    created = client.post(
        "/api/projects",
        json={"name": "Example", "spec": {"dataflow": {
            "nodes": [{"id": "n1", "type": "curio.builtin/computation-analysis",
                       "content": "print(1)", "x": 100, "y": 60}],
            "edges": [], "packages": []}}, "outputs": []},
        headers=_auth(VISITOR_A),
    )
    assert created.status_code == 201, created.get_data(as_text=True)
    monkeypatch.setattr(config, "CURIO_NO_AUTH", False)
    monkeypatch.setattr(config, "GUEST_LLM_API_TYPE", "openai_compatible")
    monkeypatch.setattr(config, "GUEST_LLM_BASE_URL", "http://127.0.0.1:9/v1")
    monkeypatch.setattr(config, "GUEST_LLM_MODEL", "test-model")
    monkeypatch.setattr(config, "GUEST_LLM_API_KEY", "test-key")
    test_routes_proposals.TestNodeCreate()._write_builtin_package(GUEST_KEY)
    return created.get_json()["id"]


def _script(monkeypatch, replies: list[str]) -> None:
    """The provider answers with *replies*, one per call, the last one again
    after them; a conversation title is answered apart."""
    calls: list = []

    def _fake_run(config_, messages, **kwargs):
        from utk_curio.backend.app.agents.application.turns import titles

        if messages and messages[0].get("content") == titles.title_prompt():
            return "Title"
        calls.append(messages)
        return replies[min(len(calls) - 1, len(replies) - 1)]

    monkeypatch.setattr("utk_curio.backend.app.agents.infrastructure.providers.run_chat_turn", _fake_run)


def _agent_adds_a_node(client, token: str, project_id: str, monkeypatch) -> tuple[str, str]:
    """The visitor signed in as *token* attaches the Node Builder to the
    canvas and asks it for a node, which lands at once: the attachment's id
    and the new node's. A guest's tab joins no room, so no doc binds it: the
    reply carries the node for it, as the stream's change event does."""
    installed = client.post(f"/api/agents/projects/{project_id}/install",
                            json={"coord": COORD}, headers=_auth(token))
    assert installed.status_code == 201, installed.get_data(as_text=True)
    attached = client.post(f"/api/agents/projects/{project_id}/attachments",
                           json={"coord": COORD, "target": {"kind": "canvas"}}, headers=_auth(token))
    assert attached.status_code == 201, attached.get_data(as_text=True)
    att_id = attached.get_json()["attachmentId"]
    _script(monkeypatch, [CREATE, "Added."])
    run = client.post(f"/api/agents/projects/{project_id}/attachments/{att_id}/run",
                      json={"message": "add a node"}, headers=_auth(token))
    assert run.status_code == 200, run.get_data(as_text=True)
    body = run.get_json()
    assert not [p for p in body["content"] if p["type"] == "proposal"]
    [landed] = body["changes"]
    assert landed["canvas"]["kind"] == "node-created"
    return att_id, landed["canvas"]["node"]["id"]


def _canvas_nodes(client, token: str, project_id: str) -> dict:
    opened = client.get(f"/api/projects/{project_id}", headers=_auth(token))
    assert opened.status_code == 200, opened.get_data(as_text=True)
    return {n["id"]: n for n in opened.get_json()["spec"]["dataflow"]["nodes"]}


def _attachments(client, token: str, project_id: str) -> list:
    listed = client.get(f"/api/agents/projects/{project_id}/attachments", headers=_auth(token))
    assert listed.status_code == 200, listed.get_data(as_text=True)
    return listed.get_json()["attachments"]


def test_one_hosted_guests_agent_work_never_reaches_the_next_guest(client, shared_example, monkeypatch):
    from utk_curio.backend.app.projects import visitor_copies  # noqa: F401 - what main lacks

    att_id, node_id = _agent_adds_a_node(client, VISITOR_A, shared_example, monkeypatch)

    # The visitor whose agent worked sees its work: the canvas opens with the
    # new node, and the agent is attached.
    assert node_id in _canvas_nodes(client, VISITOR_A, shared_example)
    assert [a["attachmentId"] for a in _attachments(client, VISITOR_A, shared_example)] == [att_id]
    # The next visitor opens the example as it ships: neither the node nor the
    # agent, and so does the example on disk.
    assert set(_canvas_nodes(client, VISITOR_B, shared_example)) == {"n1"}
    assert _attachments(client, VISITOR_B, shared_example) == []
    on_disk = storage.read_spec(GUEST_KEY, shared_example)
    assert [n["id"] for n in on_disk["dataflow"]["nodes"]] == ["n1"]
    assert not on_disk["dataflow"].get("agentAttachments")

    # A later turn of the same visitor's agent reads its copy: it finds the
    # node its own earlier turn added, and changes it there alone, at once.
    _script(monkeypatch, [WRITE % node_id, "Changed."])
    run = client.post(f"/api/agents/projects/{shared_example}/attachments/{att_id}/run",
                      json={"message": "change it"}, headers=_auth(VISITOR_A))
    assert run.status_code == 200, run.get_data(as_text=True)
    [change] = [p for p in run.get_json()["content"] if p["type"] == "change"]
    assert change["kind"] == "content"
    assert _canvas_nodes(client, VISITOR_A, shared_example)[node_id]["content"] == "print('mine, again')"
    assert set(_canvas_nodes(client, VISITOR_B, shared_example)) == {"n1"}


def test_two_hosted_guests_agents_each_keep_their_own_work(client, shared_example, monkeypatch):
    from utk_curio.backend.app.projects import visitor_copies  # noqa: F401 - what main lacks

    a_att, a_node = _agent_adds_a_node(client, VISITOR_A, shared_example, monkeypatch)
    b_att, b_node = _agent_adds_a_node(client, VISITOR_B, shared_example, monkeypatch)

    assert set(_canvas_nodes(client, VISITOR_A, shared_example)) == {"n1", a_node}
    assert set(_canvas_nodes(client, VISITOR_B, shared_example)) == {"n1", b_node}
    assert [a["attachmentId"] for a in _attachments(client, VISITOR_A, shared_example)] == [a_att]
    assert [a["attachmentId"] for a in _attachments(client, VISITOR_B, shared_example)] == [b_att]


def test_a_hosted_guests_undo_takes_the_node_off_their_copy_alone(client, shared_example, monkeypatch):
    from utk_curio.backend.app.projects import visitor_copies  # noqa: F401 - what main lacks

    att_id, node_id = _agent_adds_a_node(client, VISITOR_A, shared_example, monkeypatch)
    _b_att, b_node = _agent_adds_a_node(client, VISITOR_B, shared_example, monkeypatch)
    turns = client.get(f"/api/agents/projects/{shared_example}/attachments/{att_id}/session",
                       headers=_auth(VISITOR_A)).get_json()["turns"]
    change_id = next(p["changeId"] for t in turns for p in t.get("content") or [] if p.get("type") == "change")
    undone = client.post(f"/api/agents/projects/{shared_example}/attachments/{att_id}/changes/{change_id}/undo",
                         headers=_auth(VISITOR_A))
    assert undone.status_code == 200, undone.get_data(as_text=True)
    # The guest's tab, which no doc binds, takes the removal from the answer.
    assert undone.get_json()["canvas"] == [{
        "kind": "plan-removals", "planId": f"undo:{change_id}", "removedNodeIds": [node_id], "removedEdgeIds": [],
    }]
    assert set(_canvas_nodes(client, VISITOR_A, shared_example)) == {"n1"}
    # The other guest's node, on their own copy, stays.
    assert set(_canvas_nodes(client, VISITOR_B, shared_example)) == {"n1", b_node}


def test_the_copies_go_when_the_server_starts(client, shared_example, monkeypatch):
    from utk_curio.backend.app.projects import visitor_copies

    _agent_adds_a_node(client, VISITOR_A, shared_example, monkeypatch)

    assert visitor_copies.drop_all() == 1

    # Back to the example as it ships, as the shared examples are put back.
    assert set(_canvas_nodes(client, VISITOR_A, shared_example)) == {"n1"}
    assert _attachments(client, VISITOR_A, shared_example) == []
    assert storage.read_spec(GUEST_KEY, shared_example) is not None
