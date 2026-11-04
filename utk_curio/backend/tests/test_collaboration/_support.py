"""Accounts, dataflows and sockets for the collaboration tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from utk_curio.backend import extensions as _ext

NAMESPACE = "/collab"


def make_user(username: str, *, is_guest: bool = False):
    """Create a User + active UserSession; return ``(user, session)``."""
    from utk_curio.backend.app.users.models import User, UserSession

    user = User(username=username, name=username.title(), is_guest=is_guest)
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


def make_project(owner, project_id: str | None = None) -> str:
    """A dataflow *owner* owns, as its row alone; its id."""
    from utk_curio.backend.app.projects.models import Project

    project = Project(
        id=project_id or str(uuid4()), user_id=owner.id,
        name="Shared", slug=f"shared-{uuid4().hex[:8]}", folder_path="",
    )
    _ext.db.session.add(project)
    _ext.db.session.commit()
    return project.id


def invite(project_id: str, owner, editor) -> None:
    """*owner* invites *editor* to edit the dataflow, as the Share menu does."""
    from utk_curio.backend.app.projects import access

    access.add_editor(owner, project_id, editor.username)


def connect(socketio, application, token: str):
    client = socketio.test_client(application, namespace=NAMESPACE, auth={"token": token})
    assert client.is_connected(namespace=NAMESPACE)
    return client


def join(client, project_id: str) -> dict:
    return client.emit("join_session", {"projectId": project_id}, namespace=NAMESPACE, callback=True)


def drain(*clients) -> None:
    for client in clients:
        client.get_received(namespace=NAMESPACE)


def received(client, name: str) -> list:
    """The payloads of the *name* events *client* got since it last read."""
    return [e["args"][0] for e in client.get_received(namespace=NAMESPACE) if e["name"] == name]
