"""Every tab of the guest account is someone of its own in the room.

Every hosted guest, and every tab of a Curio with no sign-in, signs in to the
one guest account, so the room numbers that account's tabs
(``room_state.add_user``): each takes the lowest number no other participant of
the room holds, and frees it when it leaves. The room's list, each awareness
state the server names (``dataflow_docs._user``), a lock the tab holds
(``room_state.try_lock``), and the join's and the leave's Activity records name
such a tab by its number, the records with its name too (``events.py``).
Another account's tabs carry no number, so they stay one person.

The field is named here as the server writes it, not imported, so a server
without it fails each test at its assertion.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from utk_curio.backend import extensions as _ext

from ._support import NAMESPACE, connect, drain, join, make_project, make_user, received

#: The field that numbers a tab of the guest account in its room.
NUMBER = "guest_number"

#: A dataflow of one node, for the tabs that sync its doc.
SPEC = {
    "dataflow": {
        "nodes": [{"id": "loader", "type": "curio.builtin/code", "x": 10, "y": 20,
                   "content": "x = 1\n", "out": "DATAFRAME", "in": "DEFAULT", "goal": "",
                   "metadata": {"keywords": []}}],
        "edges": [],
        "name": "Shared", "task": "", "timestamp": 1, "provenance_id": "Shared",
    },
}

SIGN_IN_KINDS = pytest.mark.parametrize("no_sign_in", [False, True], ids=["hosted-guests", "no-sign-in"])


def _sign_in(user):
    """Another sign-in of *user*'s account: a session of its own, as another
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


def _guests_dataflow(monkeypatch, *, no_sign_in: bool, sign_ins: int, with_spec: bool = False):
    """A dataflow the guest account's tabs open, and *sign_ins* tokens of that
    account, one per visitor: on a hosted Curio another account's dataflow,
    which the guests watch, and on a Curio with no sign-in one the guest
    account owns. Its id, the guest and the tokens. *with_spec* writes its spec,
    for tabs that sync its doc."""
    from utk_curio.backend import config
    from utk_curio.backend.app.projects import storage

    monkeypatch.setattr(config, "CURIO_NO_AUTH", no_sign_in)
    guest, first = make_user(config.CURIO_SHARED_GUEST_USERNAME, is_guest=True)
    tokens = [first.token] + [_sign_in(guest).token for _ in range(sign_ins - 1)]
    owner = guest if no_sign_in else make_user("alice")[0]
    project_id = make_project(owner)
    if with_spec:
        storage.write_spec(storage._GUEST_KEY if no_sign_in else str(owner.id), project_id, SPEC)
    return project_id, guest, tokens


@SIGN_IN_KINDS
def test_a_room_numbers_the_guest_accounts_tabs_and_a_later_tab_takes_the_lowest_free_number(
    collab_app, monkeypatch, no_sign_in,
):
    application, socketio, room_state = collab_app
    project_id, _guest, tokens = _guests_dataflow(monkeypatch, no_sign_in=no_sign_in, sign_ins=4)
    room = room_state.room_for(project_id)

    def numbers() -> dict:
        return {entry["participant_id"]: entry.get(NUMBER) for entry in room_state.users_in(room)}

    tabs = [connect(socketio, application, token) for token in tokens]
    first, second = join(tabs[0], project_id), join(tabs[1], project_id)
    assert first["ok"] is True and second["ok"] is True, (first, second)
    assert numbers() == {first["participant_id"]: 1, second["participant_id"]: 2}, (
        f"the room did not number the guest account's two tabs 1 and 2: {numbers()}"
    )

    tabs[0].disconnect(namespace=NAMESPACE)
    assert numbers() == {second["participant_id"]: 2}, f"the tab that stayed did not keep its number: {numbers()}"

    third, fourth = join(tabs[2], project_id), join(tabs[3], project_id)
    assert numbers() == {
        second["participant_id"]: 2, third["participant_id"]: 1, fourth["participant_id"]: 3,
    }, f"a later tab did not take the lowest number free in the room: {numbers()}"

    # Another account's two tabs are one person: neither is numbered, and the
    # guests' numbers stay.
    bob, bob_session = make_user("bob")
    for _ in range(2):
        assert join(connect(socketio, application, bob_session.token), project_id)["ok"] is True
    bobs = [entry for entry in room_state.users_in(room) if entry["user_id"] == bob.id]
    assert len(bobs) == 2 and all(NUMBER not in entry for entry in bobs), f"an account's tabs were numbered: {bobs}"
    assert {pid: number for pid, number in numbers().items() if number is not None} == {
        second["participant_id"]: 2, third["participant_id"]: 1, fourth["participant_id"]: 3,
    }


def test_a_lock_a_guest_tab_holds_names_it_by_its_number(collab_app, monkeypatch):
    """On a Curio with no sign-in every tab is the guest account's and edits
    (a hosted guest only watches, so it takes no lock): the lock one of them
    takes names it by its number, for the room and in a later tab's join."""
    application, socketio, _room_state = collab_app
    project_id, guest, tokens = _guests_dataflow(monkeypatch, no_sign_in=True, sign_ins=3)
    first, second, later = (connect(socketio, application, token) for token in tokens)
    assert join(first, project_id)["ok"] is True and join(second, project_id)["ok"] is True
    drain(first, second)

    ack = second.emit("node_lock", {"projectId": project_id, "nodeId": "loader"}, namespace=NAMESPACE, callback=True)

    assert ack["ok"] is True, ack
    assert (ack["lock"]["username"], ack["lock"].get(NUMBER)) == (guest.username, 2), (
        f"the second guest tab's lock does not name it by its number: {ack['lock']}"
    )
    assert [told["lock"].get(NUMBER) for told in received(first, "node_locked")] == [2]
    assert join(later, project_id)["snapshot"]["locks"]["loader"].get(NUMBER) == 2


@SIGN_IN_KINDS
def test_a_guest_tab_is_named_by_its_number_in_its_presence_and_in_the_activity_of_its_join_and_its_leave(
    doc_app, monkeypatch, no_sign_in,
):
    from ._ydoc_client import synced_tab

    application, socketio = doc_app
    project_id, guest, (first_token, second_token, later_token) = _guests_dataflow(
        monkeypatch, no_sign_in=no_sign_in, sign_ins=3, with_spec=True,
    )
    role = "owner" if no_sign_in else "watcher"
    first = synced_tab(application, first_token, project_id)
    second = synced_tab(application, second_token, project_id)
    assert second.set_presence({"pointer": {"x": 1, "y": 2, "t": 3}}) == {"ok": True}

    user = first.others()[second.doc.client_id]["user"]
    assert (user["username"], user.get(NUMBER)) == (guest.username, 2), (
        f"the server did not name the second guest tab's presence by its number: {user}"
    )

    second.socket.disconnect(namespace=NAMESPACE)
    first.pump()
    left = [event["args"][0] for event in first.events if event["name"] == "user_left"]
    assert [(payload.get("name"), payload.get(NUMBER)) for payload in left] == [(guest.name, 2)], (
        f"the leave of the second guest's tab does not name it by its number: {left}"
    )

    ack = join(connect(socketio, application, later_token), project_id)
    assert ack["ok"] is True, ack
    who = {"user_id": guest.id, "username": guest.username, "name": guest.name}
    assert [(entry["kind"], entry["payload"]) for entry in ack["snapshot"]["activity"]] == [
        ("user_joined", {**who, "role": role, NUMBER: 1}),
        ("user_joined", {**who, "role": role, NUMBER: 2}),
        ("user_left", {**who, NUMBER: 2}),
        ("user_joined", {**who, "role": role, NUMBER: 2}),
    ], "the room's Activity does not name each guest tab by its number"
