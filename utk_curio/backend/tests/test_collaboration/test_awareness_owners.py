"""Whose awareness a socket sets (``dataflow_docs._accepted_awareness``).

The server names every state, and a socket sets only its own person's client
ids: one another person's socket set stays theirs while that socket is a tab of
the doc. A person is an account, and on a guest account, which every hosted
guest and every tab of a Curio with no sign-in signs in to, a sign-in. An
agent's state, which the server writes (``agent_peers.py``), is no socket's to
set or clear.

Each test runs tabs that are each a pycrdt doc syncing over a Flask-SocketIO
test client (``_ydoc_client.py``).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from utk_curio.backend import extensions as _ext

from ._support import NAMESPACE, invite, make_project, make_user

#: A dataflow of one node.
SPEC = {
    "dataflow": {
        "nodes": [{"id": "loader", "type": "curio.builtin/code", "x": 10, "y": 20,
                   "content": "x = 1\n", "out": "DATAFRAME", "in": "DEFAULT", "goal": "",
                   "metadata": {"keywords": []}}],
        "edges": [],
        "name": "Shared", "task": "", "timestamp": 1, "provenance_id": "Shared",
    },
}

#: Where a guest's tab points, and where a forged state says it points.
OWN = {"x": 1, "y": 1, "t": 1}
FORGED = {"x": 9, "y": 9, "t": 9}


def _sign_in(user):
    """Another sign-in of *user*'s account: a session of its own, as a second
    visitor's browser gets one."""
    from utk_curio.backend.app.users.models import UserSession

    session = UserSession(
        user_id=user.id,
        token=f"tok-{user.username}-{uuid4().hex}",
        expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        last_seen_at=datetime.now(timezone.utc),
        active=True,
    )
    _ext.db.session.add(session)
    _ext.db.session.commit()
    return session


def _forged(client_id: int, clock: int, state) -> bytes:
    """An awareness update setting *client_id*'s state, as any socket can send one."""
    from pycrdt import Encoder

    encoder = Encoder()
    encoder.write_var_uint(1)
    encoder.write_var_uint(client_id)
    encoder.write_var_uint(clock)
    encoder.write_var_string(json.dumps(state, separators=(",", ":")))
    return encoder.to_bytes()


def _server_states(project_id: str) -> dict:
    from utk_curio.backend.app.collaboration import dataflow_docs

    entry = dataflow_docs._open_entry(project_id)
    assert entry is not None, "the server holds no doc of the dataflow"
    return entry.awareness.states


def _guests_room(application, monkeypatch, *, no_sign_in: bool):
    """A dataflow two guests have open, each signed in on their own: on a
    hosted Curio both watch an account's dataflow, and on a Curio with no
    sign-in the shared guest owns it. Its id, the guest, the two guests'
    tokens and a third tab's, which only looks."""
    from utk_curio.backend import config
    from utk_curio.backend.app.projects import storage

    monkeypatch.setattr(config, "CURIO_NO_AUTH", no_sign_in)
    guest, first = make_user(config.CURIO_SHARED_GUEST_USERNAME, is_guest=True)
    second = _sign_in(guest)
    if no_sign_in:
        project_id = make_project(guest)
        storage.write_spec(storage._GUEST_KEY, project_id, SPEC)
        onlooker = _sign_in(guest)
    else:
        alice, onlooker = make_user("alice")
        project_id = make_project(alice)
        storage.write_spec(str(alice.id), project_id, SPEC)
    return project_id, guest, (first.token, second.token), onlooker.token


@pytest.mark.parametrize("no_sign_in", [False, True], ids=["hosted-guests", "no-sign-in"])
def test_a_guest_cannot_set_another_guests_state(doc_app, monkeypatch, no_sign_in):
    """Every guest signs in to the one guest account: comparing accounts let
    one guest's tab set another's pointer, which every tab then drew."""
    from pycrdt import create_awareness_message

    from ._ydoc_client import synced_tab

    application, _socketio = doc_app
    project_id, _guest, (ana_token, ben_token), onlooker_token = _guests_room(
        application, monkeypatch, no_sign_in=no_sign_in,
    )
    ana = synced_tab(application, ana_token, project_id)
    ben = synced_tab(application, ben_token, project_id)
    onlooker = synced_tab(application, onlooker_token, project_id)
    assert ana.set_presence({"pointer": OWN}) == {"ok": True}
    assert onlooker.others()[ana.doc.client_id]["pointer"] == OWN

    ack = ben.send(create_awareness_message(_forged(ana.doc.client_id, 99, {"pointer": FORGED})))

    assert ack == {"ok": True}
    assert _server_states(project_id)[ana.doc.client_id]["pointer"] == OWN, (
        "one guest's tab set another guest's state on the server"
    )
    assert onlooker.others()[ana.doc.client_id]["pointer"] == OWN, "another guest's forged state reached a tab"
    ana.pump()
    assert ana.awareness.get_local_state()["pointer"] == OWN, "another guest's forged state reached its owner"


def test_a_guest_tab_whose_socket_reconnected_sets_its_own_state_again(doc_app, monkeypatch):
    """A tab keeps its client id when its socket reconnects, and its new
    socket may come before the server has seen the old one go: one sign-in's
    socket sets that sign-in's client ids, as one account's does."""
    from pycrdt import create_awareness_message

    from ._ydoc_client import synced_tab

    application, _socketio = doc_app
    project_id, _guest, (token, _other), onlooker_token = _guests_room(application, monkeypatch, no_sign_in=False)
    before = synced_tab(application, token, project_id)
    onlooker = synced_tab(application, onlooker_token, project_id)
    assert before.set_presence({"pointer": OWN}) == {"ok": True}
    clock = before.awareness.meta[before.doc.client_id]["clock"]

    again = synced_tab(application, token, project_id)
    ack = again.send(create_awareness_message(_forged(before.doc.client_id, clock + 1, {"pointer": FORGED})))

    assert ack == {"ok": True}
    assert _server_states(project_id)[before.doc.client_id]["pointer"] == FORGED
    assert onlooker.others()[before.doc.client_id]["pointer"] == FORGED


def test_no_socket_sets_or_clears_an_agents_state(doc_app, monkeypatch):
    """An agent at work is in the room under a client id no tab holds, and
    its state is the server's alone: a tab's state or its removal for that
    client id is dropped, and a tab that tried and left takes nothing with it."""
    from pycrdt import create_awareness_message

    from utk_curio.backend.app.collaboration import agent_peers
    from utk_curio.backend.app.projects import storage

    from ._ydoc_client import synced_tab

    monkeypatch.setattr(agent_peers, "BACKGROUND", False)
    application, _socketio = doc_app
    alice, alice_session = make_user("alice")
    bob, bob_session = make_user("bob")
    project_id = make_project(alice)
    invite(project_id, alice, bob)
    storage.write_spec(str(alice.id), project_id, SPEC)
    alice_tab = synced_tab(application, alice_session.token, project_id)
    bob_tab = synced_tab(application, bob_session.token, project_id)
    agent_peers.reset_for_tests()
    try:
        with agent_peers.at_work(str(alice.id), project_id, attachment_id="att-1",
                                 coord="agent.curio.node-builder@1", name="Node Builder",
                                 category="node", asked_by=agent_peers.asker(alice)) as peer:
            agents_own = bob_tab.others()[peer.client_id]
            assert agents_own["user"]["participant_id"] == peer.participant_id

            for forged in ({"user": {"name": "Mallory"}, "pointer": FORGED}, None):
                ack = alice_tab.send(create_awareness_message(_forged(peer.client_id, 10 ** 6, forged)))
                assert ack == {"ok": True}
                assert _server_states(project_id)[peer.client_id] == agents_own, (
                    f"a tab's {'state' if forged else 'removal'} took the agent's client id"
                )
                assert bob_tab.others()[peer.client_id] == agents_own, "a tab's forgery reached another tab"

            alice_tab.socket.disconnect(namespace=NAMESPACE)
            assert _server_states(project_id)[peer.client_id] == agents_own, "a tab's leave took the agent's state"
            assert bob_tab.others()[peer.client_id] == agents_own
    finally:
        agent_peers.reset_for_tests()
