"""Two members' agents at once on one shared canvas, as the stress stage runs them.

The stress stage with agents (``tests/stress/agents.py``) has every member of
a canvas attach Node Builder to its own node and ask it a turn, all at once,
on Curio's scripted model made this Curio's default, each member's replies
queued for its own attachment with ``reset`` off. Here two of them, alice,
the owner, and bob, an editor she invited, do the same through the same
routes, while their two tabs (the stage's own ``sockets.Tab``) type and drag
in the loader.

Both turns are at the model at once, each held there on the reply it took
(``"hold"``): a call takes the replies of the attachment whose run makes it
only on the thread that runs the turn (``testing_provider.answering``), and
a call that left that thread would take the shared queue's inert reply
instead, which holds nothing, so the wait for both holds fails first. Once
let go, each turn lands its own write and its own last reply, and leaves
nothing queued; both tabs then hold both writes, the same doc as the server,
were told both turns' ends, show no agent and no lock.

The app runs on a SQLite file, as test_turn_jobs.py's does: the turns'
threads and the test's requests use the database at once.
"""

from __future__ import annotations

import time
import uuid
from types import SimpleNamespace

import pytest

from utk_curio.backend.tests._support.agent_routes import _auth
from utk_curio.backend.tests.test_agents.test_agent_changes import _project
from utk_curio.backend.tests.test_agents.test_source_grounding_routes import _install

NB = "agent.curio.node-builder@1"
CA = "curio.builtin/python-computation"
ALICE = "alice-token-stress-agents"
BOB = "bob-token-stress-agents"
#: The room's namespace, as a tab joins it.
NAMESPACE = "/collab"
#: The hold both turns' first calls wait on, at the model at once.
HOLD = "both-members-at-once"
#: How long the test waits for a turn's step before it fails.
WAIT_S = 15.0
#: The members' own nodes, each a pass-through below the loader.
ALICES_NODE = "6c0b2f4e-1d7a-4e9b-8f3c-2a1b0c9d8e7f"
BOBS_NODE = "0f9e8d7c-6b5a-4c3d-9e2f-1a0b9c8d7e6f"


def _nodes() -> list[dict]:
    return [
        {"id": "load", "type": CA, "title": "Load", "goal": "Load the parks", "content": "return 1", "x": 0, "y": 0},
        {"id": ALICES_NODE, "type": CA, "content": "return input_0", "x": 645, "y": 120},
        {"id": BOBS_NODE, "type": CA, "content": "return input_0", "x": 645, "y": 240},
    ]


def _edges() -> list[dict]:
    return [{"id": f"e-{node}", "source": "load", "target": node, "sourceHandle": "out", "targetHandle": "in"}
            for node in (ALICES_NODE, BOBS_NODE)]


def _end_turns() -> None:
    """Stop, and wait for, any turn the test left running before its tables go."""
    from utk_curio.backend.app.agents.application.turns import turn_jobs

    for job in turn_jobs.stop_all():
        if job.thread is not None:
            job.thread.join(WAIT_S)


@pytest.fixture()
def canvas(tmp_curio, tmp_path, monkeypatch):
    """alice's dataflow, a loader and a node of hers and of bob's below it,
    with Node Builder installed; bob invited to edit it. On a SQLite file,
    as on a server."""
    from utk_curio.backend import extensions
    from utk_curio.backend.app import create_app
    from utk_curio.backend.app.agents.infrastructure import testing_provider
    from utk_curio.backend.app.collaboration import agent_peers, dataflow_docs, room_state
    from utk_curio.backend.app.projects import access
    from utk_curio.backend.app.projects.services import _user_dir_key
    from utk_curio.backend.app.users.models import User, UserSession
    from utk_curio.backend.extensions import db
    from utk_curio.backend.tests._unit_fixtures import TestConfig

    class FileTestConfig(TestConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'stress-agents.db'}"

    # This app's SocketIO server, which tells the room of the agents too.
    monkeypatch.setattr(extensions, "socketio", None, raising=True)
    monkeypatch.setattr(dataflow_docs, "BACKGROUND", False, raising=True)
    application = create_app(FileTestConfig)
    with application.app_context():
        db.create_all()
        room_state.reset_for_tests()
        dataflow_docs.reset_for_tests()
        testing_provider.reset()
        people = {}
        for username, name, token in (("alice", "Alice", ALICE), ("bob", "Bob", BOB)):
            person = User(username=username, name=name, email=f"{username}@test.com")
            db.session.add(person)
            db.session.flush()
            db.session.add(UserSession(user_id=person.id, token=token))
            people[username] = person
        db.session.commit()
        client = application.test_client()
        project = _project(client, people["alice"], ALICE, _nodes(), _edges())
        _install(client, ALICE, project, NB)
        access.add_editor(people["alice"], project, "bob")
        try:
            yield SimpleNamespace(app=application, client=client, project=project,
                                  owner_key=_user_dir_key(people["alice"]), **people)
        finally:
            _end_turns()
            testing_provider.reset()
            agent_peers.reset_for_tests()
            dataflow_docs.reset_for_tests()
            room_state.reset_for_tests()
            db.session.remove()
            db.drop_all()
            db.engine.dispose()


class _TestLink:
    """A tab's socket on Flask-SocketIO's test client: an answer comes back
    with its emit, and what the server sent reaches the tab when pumped, the
    room's events and the agents' too."""

    transport = "test client"

    def __init__(self, client):
        self.client = client
        self.on_yjs = None
        self.on_room = None

    def bind(self, on_yjs, _on_close):
        self.on_yjs = on_yjs
        return self

    def emit(self, event, data, callback=None):
        ack = self.client.emit(event, data, namespace=NAMESPACE, callback=True)
        if callback is not None:
            callback(ack)

    def call(self, event, data, _timeout):
        ack = self.client.emit(event, data, namespace=NAMESPACE, callback=True)
        self.pump()
        return ack

    def pump(self):
        for event in self.client.get_received(NAMESPACE):
            if event["name"] in ("yjs", "yjs_kept"):
                self.on_yjs(event["args"][0])
            elif self.on_room is not None:
                self.on_room(event["name"], event["args"][0] if event["args"] else None)

    def close(self):
        self.client.disconnect(namespace=NAMESPACE)


def _tab(canvas, name: str, token: str, ledger):
    """*name*'s tab of the dataflow, joined and synced, as the stage opens one."""
    from utk_curio.backend.tests.stress.sockets import Tab

    socketio = canvas.app.extensions.get("socketio")
    client = socketio.test_client(canvas.app, namespace=NAMESPACE, auth={"token": token})
    assert client.is_connected(namespace=NAMESPACE)
    link = _TestLink(client)
    failures = []

    def record(label, seconds, ok, error=None, kind=None):
        if not ok:
            failures.append((label, error, kind))

    tab = Tab(name, canvas.project, ledger, record)
    tab.connect(link.bind)
    link.on_room = tab.room_event
    tab.join()
    tab.sync()
    ledger.synced(name)
    return tab, link, failures


def _pumped_until(tabs, ready, seconds: float = WAIT_S) -> None:
    """Pump every tab's socket until *ready()* holds, at most *seconds*."""
    deadline = time.monotonic() + seconds
    while True:
        for _tab_, link, _failures in tabs.values():
            link.pump()
        if ready() or time.monotonic() >= deadline:
            return
        time.sleep(0.05)


def _done_reply(envelopes: list) -> str | None:
    """The reply the ``done`` of an ask's follow carries, as it ended."""
    for envelope in envelopes:
        events = (envelope.get("data") or {}).get("events") or [] if envelope.get("event") == "snapshot" else [envelope]
        for event in events:
            if event.get("event") == "done":
                return (event.get("data") or {}).get("reply")
    return None


def test_two_members_agents_at_once_each_write_their_own_node_while_two_tabs_type_and_both_tabs_see_both(canvas):
    from utk_curio.backend.app.agents.infrastructure import testing_provider
    from utk_curio.backend.app.collaboration import dataflow_docs, room_state
    from utk_curio.backend.tests.stress.agents import (
        COORD,
        DONE_REPLY,
        MESSAGE,
        MemberTurn,
        agent_content,
        turn_envelopes,
        write_reply,
    )
    from utk_curio.backend.tests.stress.driver import Pacing
    from utk_curio.backend.tests.stress.sockets import SyncLedger

    client, base = canvas.client, f"/api/agents/projects/{canvas.project}"
    scripted = client.post("/api/testing/llm-deployment", json={"scripted": True})
    assert scripted.status_code == 200, scripted.get_data(as_text=True)
    assert [endpoint["name"] for endpoint in scripted.get_json()["endpoints"]] == ["Scripted"]
    tabs = {}
    try:
        ledger = SyncLedger()
        tabs = {name: _tab(canvas, name, token, ledger) for name, token in (("alice", ALICE), ("bob", BOB))}
        members = {"alice": (ALICE, ALICES_NODE), "bob": (BOB, BOBS_NODE)}
        asks = {}
        for name, (token, node_id) in members.items():
            attached = client.post(f"{base}/attachments", headers=_auth(token),
                                   json={"coord": COORD, "target": {"kind": "node", "targetId": node_id}})
            assert attached.status_code == 201, attached.get_data(as_text=True)
            attachment = attached.get_json()["attachmentId"]
            content = agent_content(name, tabs[name][0].code_of(node_id))
            pushed = client.post("/api/testing/agent-script", json={
                "replies": [{"text": write_reply(node_id, content), "hold": HOLD}, DONE_REPLY],
                "attachmentId": attachment, "reset": False,
            })
            assert pushed.status_code == 200, pushed.get_data(as_text=True)
            asks[name] = (token, attachment, uuid.uuid4().hex, node_id, content)
        assert testing_provider.pending() == 4, "the second member's script dropped the first's"

        for token, attachment, ask_id, _node_id, _content in asks.values():
            asked = client.post(f"{base}/attachments/{attachment}/turns", headers=_auth(token),
                                json={"message": MESSAGE, "askId": ask_id})
            assert asked.status_code == 202, asked.get_data(as_text=True)
            assert asked.get_json()["state"] == "running"
        deadline = time.monotonic() + WAIT_S
        while testing_provider.held() != {HOLD: 2} and time.monotonic() < deadline:
            time.sleep(0.05)
        assert testing_provider.held() == {HOLD: 2}, (
            "both turns were not at the model at once, each on the reply of its own attachment: "
            f"held {testing_provider.held()}, {testing_provider.pending()} reply(ies) still queued")

        # The tabs type in the loader while both agents are at work, alice
        # before they are let go and bob as they write.
        alice, bob = tabs["alice"][0], tabs["bob"][0]
        no_pause = Pacing(key_gap_min=0.0, key_gap_max=0.0)
        _, alice_line = alice.work([("load", "# ")], no_pause, lock=True)
        testing_provider.release(HOLD)
        _, bob_line = bob.work([("load", "# ")], no_pause, lock=True)

        ended = []
        for name, (token, attachment, ask_id, node_id, content) in asks.items():
            followed = client.get(f"{base}/attachments/{attachment}/turns/{ask_id}/stream", headers=_auth(token))
            assert followed.status_code == 200, followed.get_data(as_text=True)
            envelopes = turn_envelopes(followed.get_data(as_text=True).splitlines())
            turn = MemberTurn(name, node_id, content, early=True)
            turn.asked = True
            for envelope in envelopes:
                turn.take(envelope)
            assert (turn.end, turn.write) == ("done", "applied"), f"{name}'s turn: {envelopes}"
            assert _done_reply(envelopes) == DONE_REPLY, f"{name}'s turn took another reply than its own last"
            ended.append(ask_id)
        assert testing_provider.pending() == 0, "a turn left a reply of its own attachment unasked"

        expected = {node_id: content for _token, _att, _ask, node_id, content in asks.values()}

        def everywhere() -> bool:
            return all(tab.wait_for_code(expected, 0) == {} and tab.wait_told_ends(ended, 0) == []
                       and tab.wait_for_no_agents(0) == {} and tab.room_locks() == {}
                       for tab, _link, _failures in tabs.values())

        _pumped_until(tabs, everywhere)
        for name, (tab, _link, failures) in tabs.items():
            assert tab.wait_for_code(expected, 0) == {}, f"{name}'s tab lacks an agent's write"
            assert tab.wait_told_ends(ended, 0) == [], f"{name}'s tab was not told a turn's end"
            assert tab.wait_for_no_agents(0) == {}, f"{name}'s tab still shows an agent"
            assert tab.agents_joined == 2, f"{name}'s tab saw {tab.agents_joined} agent(s) join, not both"
            assert tab.room_locks() == {}, f"{name}'s tab still shows a lock"
            assert tab.wait_for_answers(WAIT_S) and failures == [], f"{name}'s tab: {failures}"
        assert alice.digest() == bob.digest(), "the two tabs hold different docs"
        live = dataflow_docs.read(canvas.owner_key, canvas.project)["dataflow"]
        nodes = {node["id"]: node.get("content") for node in live["nodes"]}
        assert {node_id: nodes[node_id] for node_id in expected} == expected, "the server's doc lacks a write"
        loader = nodes["load"]
        assert loader.count(alice_line) == 2 and loader.count(bob_line) == 2, loader
        assert loader.endswith("return 1"), loader
        assert room_state.snapshot(room_state.room_for(canvas.project))["locks"] == {}
    finally:
        client.delete("/api/testing/llm-deployment")
        for _tab_, link, _failures in tabs.values():
            link.close()
