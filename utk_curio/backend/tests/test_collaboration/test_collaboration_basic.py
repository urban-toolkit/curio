"""Smoke + identity-defence tests for the collaboration namespace.

Covers the contract that every other event handler relies on:
- handshake without a token is refused,
- handshake with a valid Bearer token resolves the right User,
- two clients in the same project room see each other,
- a client cannot spoof another user's identity via payload fields
  (the server-side session is the only source of truth).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from utk_curio.backend import config as _config
from utk_curio.backend import extensions as _ext
from utk_curio.backend.app import create_app

VALID_PROJECT_ID = "3fd026a7-ef31-4fb6-ac24-2d1b099ff7cf"
NAMESPACE = "/collab"


class _CollabConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = "test-secret"
    WTF_CSRF_ENABLED = False


@pytest.fixture()
def collab_app(monkeypatch):
    """Build a Flask app with ENABLE_COLLAB=True via a config monkeypatch.

    ``create_app`` re-reads ``ENABLE_COLLAB`` from the config module on
    every call (the import is inside the function body), so flipping the
    module attribute before invoking it is enough — no module reload,
    no double SQLAlchemy registration.
    """
    monkeypatch.setattr(_config, "ENABLE_COLLAB", True, raising=True)
    # Drop any singleton left behind by an earlier test invocation.
    monkeypatch.setattr(_ext, "socketio", None, raising=True)

    application = create_app(_CollabConfig)
    socketio = _ext.socketio
    assert socketio is not None, "init_socketio() was not invoked"

    from utk_curio.backend.app.collaboration import room_state

    with application.app_context():
        _ext.db.create_all()
        room_state.reset_for_tests()
        try:
            yield application, socketio, room_state
        finally:
            room_state.reset_for_tests()
            _ext.db.session.remove()
            _ext.db.drop_all()


def _make_user(username: str):
    """Create a User + active UserSession; return ``(user, session)``."""
    from utk_curio.backend.app.users.models import User, UserSession

    user = User(username=username, name=username.title(), is_guest=False)
    _ext.db.session.add(user)
    _ext.db.session.commit()
    session = UserSession(
        user_id=user.id,
        token=f"tok-{username}-{user.id}",
        expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        last_seen_at=datetime.now(timezone.utc),
        active=True,
    )
    _ext.db.session.add(session)
    _ext.db.session.commit()
    return user, session


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
        _u_a, sess_a = _make_user("alice")
        _u_b, sess_b = _make_user("bob")
        token_a, token_b = sess_a.token, sess_b.token

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


def test_spoofed_user_id_does_not_override_auth(collab_app):
    application, socketio, _ = collab_app
    with application.app_context():
        _u_a, sess_a = _make_user("carol")
        _u_b, sess_b = _make_user("dave")
        token_a, token_b = sess_a.token, sess_b.token

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
