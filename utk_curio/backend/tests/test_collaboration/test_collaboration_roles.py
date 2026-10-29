"""Who edits in a dataflow's room (``projects/access.py``).

The owner and the editors the owner invited edit, and everyone else who opens
the link watches: the server refuses each of a watcher's edits. Participants
are told apart by participant, not by account, so two tabs of one account, or
two hosted guests on the one guest account, are two people. A hosted guest
joins no room of a dataflow a guest owns, and a change to the editors reaches
the room at once. The dataflow itself is the server's Yjs doc, whose roles
``test_dataflow_docs.py`` holds; code is typed together, with no vote.
"""

from __future__ import annotations

import pytest

from ._support import NAMESPACE, connect, drain, invite, join, make_project, make_user, received

#: The events the room took before the dataflow became its doc: a node's or
#: a connection's change relayed, and the votes on a code change.
GONE_EVENTS = [
    ("node_added", {"nodeId": "n9", "node": {"id": "n9", "position": {"x": 1, "y": 2}, "data": {}}}),
    ("node_updated", {"nodeId": "n1", "patch": {"position": {"x": 1, "y": 2}}}),
    ("node_removed", {"nodeId": "n1"}),
    ("edge_added", {"edgeId": "e1", "edge": {"id": "e1", "source": "n1", "target": "n2"}}),
    ("edge_removed", {"edgeId": "e1"}),
    ("request_code_change", {"nodeId": "n1", "kind": "code", "oldValue": "a", "newValue": "b"}),
    ("approve_code_change", {"proposalId": "p1"}),
    ("reject_code_change", {"proposalId": "p1"}),
]


def _room(collab_app, *invited):
    """alice owns a dataflow, *invited* edit it, and carol watches; everyone
    has joined, in that order, so carol's join answer lists the whole room.
    Returns the dataflow's id and each one's socket and ack."""
    application, socketio, _ = collab_app
    with application.app_context():
        alice, a_tok = make_user("alice")
        tokens = {"alice": a_tok.token}
        project_id = make_project(alice)
        for name in invited:
            user, tok = make_user(name)
            tokens[name] = tok.token
            invite(project_id, alice, user)
        _carol, c_tok = make_user("carol")
        tokens["carol"] = c_tok.token
    sockets, acks = {}, {}
    for name, token in tokens.items():
        sockets[name] = connect(socketio, application, token)
        acks[name] = join(sockets[name], project_id)
        assert acks[name]["ok"] is True, acks[name]
    drain(*sockets.values())
    return project_id, sockets, acks


def test_a_watchers_edit_is_refused_and_an_invited_editors_is_relayed(collab_app):
    from utk_curio.backend.app.collaboration.events import READ_ONLY_REFUSAL

    project_id, s, _acks = _room(collab_app, "bob")
    payload = {"projectId": project_id, "nodeId": "n1"}

    refused = s["carol"].emit("node_lock", payload, namespace=NAMESPACE, callback=True)
    assert refused == {"ok": False, "error": "read_only", "message": READ_ONLY_REFUSAL}
    assert received(s["alice"], "node_locked") == [], "a watcher's lock reached the owner"

    relayed = s["bob"].emit("node_lock", payload, namespace=NAMESPACE, callback=True)
    assert relayed["ok"] is True
    got = received(s["alice"], "node_locked")
    assert [g["nodeId"] for g in got] == ["n1"]
    assert got[0]["lock"]["username"] == "bob"
    assert [g["nodeId"] for g in received(s["carol"], "node_locked")] == ["n1"], (
        "a watcher sees the editor's lock"
    )


@pytest.mark.parametrize("event,extra", [
    ("node_lock", {"nodeId": "n1"}),
    ("output_produced", {"nodeId": "n1", "output": {"code": "success", "content": "x"}}),
    ("resolve_conflict", {"choice": "mine"}),
])
def test_a_watcher_is_refused_every_change_to_the_room(collab_app, event, extra):
    project_id, s, _acks = _room(collab_app)

    ack = s["carol"].emit(event, {"projectId": project_id, **extra}, namespace=NAMESPACE, callback=True)

    assert ack["ok"] is False and ack["error"] == "read_only", (event, ack)
    assert [e["name"] for e in s["alice"].get_received(namespace=NAMESPACE)] == [], (
        f"a watcher's {event} reached the owner"
    )


@pytest.mark.parametrize("event,extra", GONE_EVENTS, ids=[event for event, _ in GONE_EVENTS])
def test_the_room_takes_no_vote_and_relays_no_node_or_connection(collab_app, event, extra):
    """Code is typed together in the dataflow's doc, with no vote, and the doc
    carries every node and connection: the room takes none of these from an
    editor, and they reach nobody."""
    project_id, s, _acks = _room(collab_app, "bob")
    if event in ("approve_code_change", "reject_code_change"):
        # A vote on a change alice asked for, as a room with votes kept one.
        asked = s["alice"].emit("request_code_change", {
            "projectId": project_id, "nodeId": "n1", "kind": "code", "oldValue": "a", "newValue": "b",
        }, namespace=NAMESPACE, callback=True)
        if isinstance(asked, dict) and isinstance(asked.get("proposal"), dict):
            extra = {"proposalId": asked["proposal"]["id"]}
        drain(*s.values())

    ack = s["bob"].emit(event, {"projectId": project_id, **extra}, namespace=NAMESPACE, callback=True)

    assert not (isinstance(ack, dict) and ack.get("ok")), (event, ack)
    for name in ("alice", "carol"):
        assert [e["name"] for e in s[name].get_received(namespace=NAMESPACE)] == [], (
            f"bob's {event} reached {name}"
        )
    snapshot = join(s["alice"], project_id)["snapshot"]
    assert "proposals" not in snapshot, "the room still keeps proposals"


def test_the_room_lists_each_participants_role(collab_app):
    project_id, s, acks = _room(collab_app, "bob")

    assert acks["alice"]["role"] == "owner"
    assert acks["bob"]["role"] == "editor"
    assert acks["carol"]["role"] == "watcher"
    users = acks["carol"]["snapshot"]["users"]
    assert {u["username"]: u["role"] for u in users} == {
        "alice": "owner", "bob": "editor", "carol": "watcher",
    }
    ids = [u["participant_id"] for u in users]
    assert len(set(ids)) == 3 and all(ids), ids
    assert {a["participant_id"] for a in acks.values()} == set(ids)
    assert all("sid" not in u for u in users), "a participant's socket id left the server"


def test_two_participants_of_one_account_are_told_apart(collab_app):
    """Two tabs of alice's: each its own participant, with a lock of its own."""
    application, socketio, _ = collab_app
    with application.app_context():
        alice, tok = make_user("alice")
        token = tok.token
        project_id = make_project(alice)
    first, second = connect(socketio, application, token), connect(socketio, application, token)
    one, two = join(first, project_id), join(second, project_id)
    assert one.get("participant_id") and two.get("participant_id"), (one, two)
    assert one["participant_id"] != two["participant_id"]
    assert one["role"] == two["role"] == "owner"

    lock = first.emit("node_lock", {"projectId": project_id, "nodeId": "n1"}, namespace=NAMESPACE, callback=True)
    assert lock["ok"] is True and lock["lock"]["participant_id"] == one["participant_id"]
    taken = second.emit("node_lock", {"projectId": project_id, "nodeId": "n1"}, namespace=NAMESPACE, callback=True)
    assert taken == {"ok": False, "error": "locked_by_other"}
    other = second.emit("node_lock", {"projectId": project_id, "nodeId": "n2"}, namespace=NAMESPACE, callback=True)
    assert other["ok"] is True and other["lock"]["participant_id"] == two["participant_id"]


def test_a_hosted_guest_joins_no_room_of_a_dataflow_a_guest_owns(collab_app, monkeypatch):
    """On a Curio started with --deploy every visitor is the shared guest,
    which owns the examples: each visitor's canvas of one stays its own. Such
    a guest watches an account's dataflow."""
    from utk_curio.backend import config
    from utk_curio.backend.app.collaboration.events import GUEST_OWNED_REFUSAL

    monkeypatch.setattr(config, "CURIO_NO_AUTH", False)
    application, socketio, _ = collab_app
    with application.app_context():
        guest, g_tok = make_user(config.CURIO_SHARED_GUEST_USERNAME, is_guest=True)
        token = g_tok.token
        alice, _a_tok = make_user("alice")
        example = make_project(guest)
        alices = make_project(alice)
    visitor = connect(socketio, application, token)

    assert join(visitor, example) == {"ok": False, "error": "guest_owned", "message": GUEST_OWNED_REFUSAL}
    watching = join(visitor, alices)
    assert watching["ok"] is True and watching["role"] == "watcher"
    ack = visitor.emit("node_lock", {"projectId": alices, "nodeId": "n1"},
                       namespace=NAMESPACE, callback=True)
    assert ack["error"] == "read_only"


def test_without_deploy_the_shared_guest_edits_its_own_dataflows(collab_app, monkeypatch):
    """A clone without --deploy signs everyone in as the shared guest, the one
    local user, who owns its dataflows and edits them in their room."""
    from utk_curio.backend import config

    monkeypatch.setattr(config, "CURIO_NO_AUTH", True)
    application, socketio, _ = collab_app
    with application.app_context():
        guest, g_tok = make_user(config.CURIO_SHARED_GUEST_USERNAME, is_guest=True)
        token = g_tok.token
        project_id = make_project(guest)
    local = connect(socketio, application, token)

    ack = join(local, project_id)
    assert ack["ok"] is True and ack.get("role") == "owner", ack


def test_a_removed_editor_watches_at_once_and_on_their_next_join(collab_app):
    from utk_curio.backend.app.projects import access
    from utk_curio.backend.app.users.models import User

    project_id, s, acks = _room(collab_app, "bob")
    application, socketio, _ = collab_app
    lock = s["bob"].emit("node_lock", {"projectId": project_id, "nodeId": "n1"}, namespace=NAMESPACE, callback=True)
    assert lock["ok"] is True
    drain(*s.values())

    with application.app_context():
        alice = User.query.filter_by(username="alice").one()
        bob = User.query.filter_by(username="bob").one()
        bob_id, bob_token = bob.id, bob.sessions[0].token
        assert access.remove_editor(alice, project_id, bob_id) == []

    events = {e["name"]: e["args"][0] for e in s["alice"].get_received(namespace=NAMESPACE)}
    assert events["node_unlocked"] == {"nodeId": "n1"}, "a removed editor's lock stayed"
    roles = {u["participant_id"]: u["role"] for u in events["roles_changed"]["users"]}
    assert roles[acks["bob"]["participant_id"]] == "watcher"
    refused = s["bob"].emit("node_lock", {"projectId": project_id, "nodeId": "n1"},
                            namespace=NAMESPACE, callback=True)
    assert refused["error"] == "read_only"

    s["bob"].disconnect(namespace=NAMESPACE)
    again = join(connect(socketio, application, bob_token), project_id)
    assert again["ok"] is True and again["role"] == "watcher"


def test_an_editor_invited_while_watching_edits_at_once(collab_app):
    from utk_curio.backend.app.projects import access
    from utk_curio.backend.app.users.models import User

    project_id, s, acks = _room(collab_app)
    application, _socketio, _ = collab_app
    with application.app_context():
        alice = User.query.filter_by(username="alice").one()
        access.add_editor(alice, project_id, "carol")

    roles = {u["participant_id"]: u["role"] for u in received(s["carol"], "roles_changed")[-1]["users"]}
    assert roles[acks["carol"]["participant_id"]] == "editor"
    ack = s["carol"].emit("node_lock", {"projectId": project_id, "nodeId": "n1"},
                          namespace=NAMESPACE, callback=True)
    assert ack["ok"] is True


def test_a_join_to_a_dataflow_that_does_not_exist_is_refused(collab_app):
    application, socketio, _ = collab_app
    with application.app_context():
        _alice, tok = make_user("alice")
        token = tok.token
    client = connect(socketio, application, token)

    assert join(client, "3fd026a7-ef31-4fb6-ac24-2d1b099ff7cf") == {"ok": False, "error": "unknown_project"}
