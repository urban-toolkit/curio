"""Smoke + identity-defence tests for the collaboration namespace.

Covers the contract that every other event handler relies on:
- handshake without a token is refused,
- handshake with a valid Bearer token resolves the right User,
- two clients in the same project room see each other,
- disconnecting removes a user from the room and releases their locks,
- a client cannot spoof another user's identity via payload fields
  (the server-side session is the only source of truth).

A room is a dataflow's, so each test joins one that exists, and whoever takes
a lock in it edits the dataflow: its owner, or an editor the owner invited
(``test_collaboration_roles.py`` holds a watcher to the rest).
"""

from __future__ import annotations

from ._support import NAMESPACE, make_project
from ._support import make_user as _make_user

VALID_PROJECT_ID = "3fd026a7-ef31-4fb6-ac24-2d1b099ff7cf"


def test_socket_rejects_missing_token(collab_app):
    application, socketio, _ = collab_app
    client = socketio.test_client(application, namespace=NAMESPACE)
    assert not client.is_connected(namespace=NAMESPACE), (
        "handshake should be refused without a Bearer token"
    )


def test_socket_rejects_invalid_token(collab_app):
    application, socketio, _ = collab_app
    client = socketio.test_client(
        application, namespace=NAMESPACE,
        auth={"token": "definitely-not-a-real-session-token"},
    )
    assert not client.is_connected(namespace=NAMESPACE)


def test_two_clients_see_each_other(collab_app):
    application, socketio, _ = collab_app
    with application.app_context():
        u_a, sess_a = _make_user("alice")
        _u_b, sess_b = _make_user("bob")
        token_a, token_b = sess_a.token, sess_b.token
        make_project(u_a, VALID_PROJECT_ID)

    client_a = socketio.test_client(
        application, namespace=NAMESPACE, auth={"token": token_a},
    )
    client_b = socketio.test_client(
        application, namespace=NAMESPACE, auth={"token": token_b},
    )
    assert client_a.is_connected(namespace=NAMESPACE)
    assert client_b.is_connected(namespace=NAMESPACE)

    ack_a = client_a.emit(
        "join_session", {"projectId": VALID_PROJECT_ID},
        namespace=NAMESPACE, callback=True,
    )
    assert ack_a["ok"] is True
    client_a.get_received(namespace=NAMESPACE)  # drain

    ack_b = client_b.emit(
        "join_session", {"projectId": VALID_PROJECT_ID},
        namespace=NAMESPACE, callback=True,
    )
    assert ack_b["ok"] is True
    snap_usernames = {u["username"] for u in ack_b["snapshot"]["users"]}
    assert snap_usernames == {"alice", "bob"}

    a_events = [e["name"] for e in client_a.get_received(namespace=NAMESPACE)]
    assert "user_joined" in a_events


def test_disconnect_releases_membership_and_locks(collab_app):
    """Disconnecting is the *only* way a client leaves a room.

    There is no ``leave_session`` event: the frontend switches projects by
    closing the socket and reconnecting (see ``CollaborationProvider``), so
    ``disconnect`` alone has to drop room membership, release any locks the
    sid held, and tell the remaining peers. If that regresses, a user who
    navigates away stays in the room forever holding their node locks.
    """
    application, socketio, room_state = collab_app
    with application.app_context():
        u_a, sess_a = _make_user("alice")
        _u_b, sess_b = _make_user("bob")
        token_a, token_b = sess_a.token, sess_b.token
        make_project(u_a, VALID_PROJECT_ID)

    client_a = socketio.test_client(
        application, namespace=NAMESPACE, auth={"token": token_a},
    )
    client_b = socketio.test_client(
        application, namespace=NAMESPACE, auth={"token": token_b},
    )
    for client in (client_a, client_b):
        ack = client.emit(
            "join_session", {"projectId": VALID_PROJECT_ID},
            namespace=NAMESPACE, callback=True,
        )
        assert ack["ok"] is True

    # Alice takes a lock, then drops off without any leave event.
    lock_ack = client_a.emit(
        "node_lock", {"projectId": VALID_PROJECT_ID, "nodeId": "node-1"},
        namespace=NAMESPACE, callback=True,
    )
    assert lock_ack["ok"] is True
    client_b.get_received(namespace=NAMESPACE)  # drain the lock broadcast

    client_a.disconnect(namespace=NAMESPACE)

    room = f"project:{VALID_PROJECT_ID}"
    remaining = {u["username"] for u in room_state.users_in(room)}
    assert remaining == {"bob"}, "disconnect must drop the sid from the room"

    b_events = [e["name"] for e in client_b.get_received(namespace=NAMESPACE)]
    assert "user_left" in b_events, "peers must be told the user is gone"

    # The lock is free again, so the next tab alice opens can take it: a socket
    # of its own, which a lock the departed one kept would refuse.
    client_a2 = socketio.test_client(
        application, namespace=NAMESPACE, auth={"token": token_a},
    )
    assert client_a2.emit(
        "join_session", {"projectId": VALID_PROJECT_ID},
        namespace=NAMESPACE, callback=True,
    )["ok"] is True
    relock = client_a2.emit(
        "node_lock", {"projectId": VALID_PROJECT_ID, "nodeId": "node-1"},
        namespace=NAMESPACE, callback=True,
    )
    assert relock["ok"] is True, "disconnect must release the departed sid's locks"


def test_spoofed_user_id_does_not_override_auth(collab_app):
    application, socketio, _ = collab_app
    with application.app_context():
        u_a, sess_a = _make_user("carol")
        _u_b, sess_b = _make_user("dave")
        token_a, token_b = sess_a.token, sess_b.token
        make_project(u_a, VALID_PROJECT_ID)

    client_a = socketio.test_client(
        application, namespace=NAMESPACE, auth={"token": token_a},
    )
    client_b = socketio.test_client(
        application, namespace=NAMESPACE, auth={"token": token_b},
    )
    for c in (client_a, client_b):
        c.emit("join_session", {"projectId": VALID_PROJECT_ID},
               namespace=NAMESPACE, callback=True)
        c.get_received(namespace=NAMESPACE)

    # Carol claims to be Dave in the payload; the server must ignore it
    # and record Carol as the lock owner from her saved session.
    ack = client_a.emit(
        "node_lock",
        {
            "projectId": VALID_PROJECT_ID,
            "nodeId": "n1",
            "userId": 999_999,
            "username": "dave",
        },
        namespace=NAMESPACE, callback=True,
    )
    assert ack["ok"] is True
    assert ack["lock"]["username"] == "carol", (
        "lock owner must come from the server-side session, not the client"
    )

    locked_events = [
        e for e in client_b.get_received(namespace=NAMESPACE)
        if e["name"] == "node_locked"
    ]
    assert locked_events, "Bob should have received the node_locked broadcast"
    assert locked_events[-1]["args"][0]["lock"]["username"] == "carol"
