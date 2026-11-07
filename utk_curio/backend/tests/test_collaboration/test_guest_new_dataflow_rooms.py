"""A hosted guest's own new dataflow (File > New) is a room of its own, which
only that guest's tabs join (``projects/visitor_copies.py``,
``collaboration/events.py``).

Two visitors, A and B, sign in to the shared guest account here, as two
browsers do, and an account signs in too. A's tabs join the room of A's new
dataflow as its owner and edit its doc, which a later tab, as after a reload,
opens with A's change. To B and to the account it is a dataflow that does not
exist. Each test imports what main lacks inside itself, so a checkout without
the new dataflows fails here test by test.
"""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone

import pytest
from pycrdt import Map

from ._support import NAMESPACE, connect, join, make_user

#: A's new dataflow as its File > New made it: one node.
SPEC = {
    "dataflow": {
        "name": "Mine",
        "nodes": [
            {"id": "loader", "type": "curio.builtin/code", "x": 10, "y": 20,
             "content": "x = 1\n", "out": "DATAFRAME", "in": "DEFAULT", "goal": "",
             "metadata": {"keywords": []}},
        ],
        "edges": [],
    },
}


@pytest.fixture()
def visitors(doc_app, monkeypatch):
    """A's new dataflow on a Curio started with ``--deploy``, and the
    sign-ins of A and B to the shared guest account and of an account:
    ``(application, socketio, {who: token}, the dataflow's id)``."""
    from utk_curio.backend import config
    from utk_curio.backend import extensions as _ext
    from utk_curio.backend.app.collaboration import dataflow_docs
    from utk_curio.backend.app.projects import visitor_copies
    from utk_curio.backend.app.users.models import UserSession

    application, socketio = doc_app
    monkeypatch.setattr(config, "CURIO_NO_AUTH", False)
    monkeypatch.setattr(dataflow_docs, "_today", lambda: "2026-11-06")
    guest, session_a = make_user(config.CURIO_SHARED_GUEST_USERNAME, is_guest=True)
    session_b = UserSession(
        user_id=guest.id, token=f"tok-visitor-b-{guest.id}", active=True,
        expires_at=datetime.now(timezone.utc) + timedelta(days=1), last_seen_at=datetime.now(timezone.utc),
    )
    _ext.db.session.add(session_b)
    _ext.db.session.commit()
    _account, session_c = make_user("ana")
    mine = visitor_copies.new_dataflow(guest, copy.deepcopy(SPEC), sign_in=session_a.token)
    assert mine is not None
    tokens = {"A": session_a.token, "B": session_b.token, "account": session_c.token}
    return application, socketio, tokens, mine


def _type(text: str):
    """A change that types *text* at the start of the node's code."""

    def change(doc):
        doc.get("nodes", type=Map)["loader"]["content"].insert(0, text)

    return change


def _code(dataflow: dict) -> str:
    return next(n for n in dataflow["nodes"] if n["id"] == "loader")["content"]


def _tab(application, socketio, token: str, project_id: str):
    """A tab of *project_id* for the sign-in *token*, synced with its doc."""
    from ._ydoc_client import DocClient

    socket = connect(socketio, application, token)
    ack = join(socket, project_id)
    socket.get_received(namespace=NAMESPACE)
    assert ack["ok"] is True, ack
    assert (ack["role"], ack["projectId"]) == ("owner", project_id), ack
    tab = DocClient(socket, project_id)
    started = tab.sync()
    assert started["ok"] is True, started
    return tab


def test_a_hosted_guests_new_dataflow_is_its_own_room_which_it_owns(visitors):
    from utk_curio.backend.app.collaboration import dataflow_docs
    from utk_curio.backend.app.common.user_storage import GUEST_KEY
    from utk_curio.backend.app.projects import storage

    application, socketio, tokens, mine = visitors
    tab = _tab(application, socketio, tokens["A"], mine)

    acks = tab.edit(_type("# mine\n"))

    assert acks and all(ack.get("ok") for ack in acks), acks
    dataflow_docs.flush(mine)
    assert _code(storage.read_spec(GUEST_KEY, mine)["dataflow"]) == "# mine\nx = 1\n"
    # A later tab of the same visitor, as after a reload, holds the change.
    assert _code(_tab(application, socketio, tokens["A"], mine).dataflow()) == "# mine\nx = 1\n"


def test_to_another_guest_and_to_an_account_a_guests_new_dataflow_does_not_exist(visitors):
    from utk_curio.backend.app.common.user_storage import GUEST_KEY
    from utk_curio.backend.app.projects import storage

    application, socketio, tokens, mine = visitors
    for who in ("B", "account"):
        socket = connect(socketio, application, tokens[who])

        assert join(socket, mine) == {"ok": False, "error": "unknown_project"}, who
        # Nor does any later event of the socket reach the dataflow.
        locked = socket.emit("node_lock", {"projectId": mine, "nodeId": "loader"},
                             namespace=NAMESPACE, callback=True)
        assert locked == {"ok": False, "error": "not_joined"}, who
    assert _code(storage.read_spec(GUEST_KEY, mine)["dataflow"]) == "x = 1\n"
