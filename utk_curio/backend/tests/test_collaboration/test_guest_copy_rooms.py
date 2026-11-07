"""A hosted guest's canvas of an example is its own copy's room
(``projects/visitor_copies.py``, ``collaboration/events.py``).

On a Curio started with ``--deploy`` every visitor signs in to the one shared
guest account, which owns the examples. Two visitors, A and B, sign in to it
here, as two browsers do. Each one's tab of an example joins the room of its
own copy of it, keyed by the copy's id, and syncs that copy's doc: served the
example as it is until the visitor's first change makes the copy. Each test
imports what main lacks inside itself, so a checkout without the copies'
rooms fails here test by test.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

import pytest
from pycrdt import Map

from ._support import NAMESPACE, connect, join, make_project, make_user

#: The example on disk: a loader feeding a chart.
SPEC = {
    "dataflow": {
        "nodes": [
            {"id": "loader", "type": "curio.builtin/code", "x": 10, "y": 20,
             "content": "x = 1\n", "out": "DATAFRAME", "in": "DEFAULT", "goal": "",
             "metadata": {"keywords": []}},
            {"id": "chart", "type": "curio.builtin/vega-lite", "x": 300, "y": 20,
             "content": "{}", "out": "DEFAULT", "in": "DATAFRAME", "goal": "",
             "metadata": {"keywords": []}},
        ],
        "edges": [{"id": "e1", "source": "loader", "target": "chart",
                   "sourceHandle": "out", "targetHandle": "in"}],
        "name": "Example",
    },
}


class _Guests:
    """The shared guest's example, and a tab of it for visitor A or B."""

    def __init__(self, application, socketio, tokens, example):
        self.application = application
        self.socketio = socketio
        self.tokens = tokens
        self.example = example

    def join(self, who: str, project_id: str | None = None):
        """Visitor *who*'s socket, joined to *project_id*'s room (the example's
        by default), and the join's answer."""
        socket = connect(self.socketio, self.application, self.tokens[who])
        ack = join(socket, project_id or self.example)
        socket.get_received(namespace=NAMESPACE)
        return socket, ack

    def tab(self, who: str):
        """Visitor *who*'s tab of the example, synced with the doc of the room
        its join named."""
        from ._ydoc_client import DocClient

        socket, ack = self.join(who)
        assert ack["ok"] is True, ack
        tab = DocClient(socket, ack["projectId"])
        started = tab.sync()
        assert started["ok"] is True, started
        return tab

    def own(self, who: str) -> str:
        from utk_curio.backend.app.projects import visitor_copies

        return visitor_copies.copy_id(self.tokens[who], self.example)

    def example_bytes(self) -> str:
        """The example's spec on disk, by the digest of its bytes."""
        from utk_curio.backend.app.common.user_storage import GUEST_KEY
        from utk_curio.backend.app.projects import storage

        path = storage.project_dir(GUEST_KEY, self.example) / storage.SPEC_FILE
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def live(self, project_id: str):
        """The dataflow of *project_id* as it is now, or None when it has no
        spec: ``dataflow_docs.read`` gives the whole spec, whose ``dataflow``
        holds the nodes."""
        from utk_curio.backend.app.collaboration import dataflow_docs
        from utk_curio.backend.app.common.user_storage import GUEST_KEY

        spec = dataflow_docs.read(GUEST_KEY, project_id)
        return spec["dataflow"] if spec is not None else None


@pytest.fixture()
def guests(doc_app, monkeypatch):
    """The shared guest's example, on a Curio started with ``--deploy``, and
    two visitors signed in to the account."""
    from utk_curio.backend import config
    from utk_curio.backend import extensions as _ext
    from utk_curio.backend.app.collaboration import dataflow_docs
    from utk_curio.backend.app.common.user_storage import GUEST_KEY
    from utk_curio.backend.app.projects import storage
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
    example = make_project(guest)
    storage.write_spec(GUEST_KEY, example, SPEC)
    return _Guests(application, socketio, {"A": session_a.token, "B": session_b.token}, example)


def _type(text: str, node: str = "loader"):
    """A change that types *text* at the start of *node*'s code."""

    def change(doc):
        doc.get("nodes", type=Map)[node]["content"].insert(0, text)

    return change


def _code(dataflow: dict, node: str = "loader") -> str:
    return next(n for n in dataflow["nodes"] if n["id"] == node)["content"]


def test_a_hosted_guests_tab_joins_its_own_copys_room_which_it_owns(guests):
    from utk_curio.backend.app.projects import visitor_copies  # noqa: F401 - what main lacks

    socket, ack = guests.join("A")

    assert ack["ok"] is True, ack
    assert ack["role"] == "owner"
    # The room is the visitor's own copy's, named by its sign-in.
    assert ack["projectId"] == guests.own("A") != guests.example
    assert ack["projectId"] != guests.own("B")
    # Every later event names that room: one naming the example's is refused.
    locked = socket.emit("node_lock", {"projectId": guests.own("A"), "nodeId": "loader"},
                         namespace=NAMESPACE, callback=True)
    assert locked["ok"] is True, locked
    refused = socket.emit("node_lock", {"projectId": guests.example, "nodeId": "chart"},
                          namespace=NAMESPACE, callback=True)
    assert refused == {"ok": False, "error": "not_joined"}


def test_a_hosted_guest_never_joins_another_guests_copy(guests):
    from utk_curio.backend.app.collaboration.events import GUEST_OWNED_REFUSAL

    a = guests.tab("A")
    a.edit(_type("# A's\n"))
    _socket, b_own = guests.join("B")
    assert b_own["ok"] is True and b_own["projectId"] == guests.own("B")

    # B names A's copy, which A's change made: the room refuses B.
    _socket, refused = guests.join("B", guests.own("A"))

    assert refused == {"ok": False, "error": "guest_owned", "message": GUEST_OWNED_REFUSAL}


def test_a_hosted_guest_who_only_looks_makes_no_copy(guests):
    from utk_curio.backend.app.collaboration import dataflow_docs
    from utk_curio.backend.app.common.user_storage import GUEST_KEY
    from utk_curio.backend.app.projects import storage

    before = guests.example_bytes()
    tab = guests.tab("A")
    tab.set_presence({"pointer": {"x": 1, "y": 2}})

    # The tab holds the example as it is, and answered the server's step 1
    # with nothing the doc lacked, which was kept as no change.
    assert _code(tab.dataflow()) == "x = 1\n"
    assert tab.answers and all(ack == {"ok": True, "kept": {}} for _answer, ack in tab.answers), tab.answers
    dataflow_docs.flush_due(now=10 ** 9)
    dataflow_docs.close(guests.own("A"))
    # Nothing of the copy is on disk, and the example is as it was.
    assert not storage.project_dir(GUEST_KEY, guests.own("A")).exists()
    assert guests.live(guests.own("A")) is None
    assert guests.example_bytes() == before


def test_a_hosted_guests_first_change_makes_its_copy_from_the_doc_its_tab_holds(guests):
    from utk_curio.backend.app.collaboration import dataflow_docs
    from utk_curio.backend.app.common.user_storage import GUEST_KEY
    from utk_curio.backend.app.projects import storage, visitor_copies

    before = guests.example_bytes()
    tab = guests.tab("A")
    held = tab.doc_id

    acks = tab.edit(_type("# mine\n"))
    acks += tab.edit(_type("# again\n"))

    assert acks and all(ack.get("ok") for ack in acks), acks
    own = guests.own("A")
    # The copy names the example, holds both changes, and kept the doc the
    # tab held: the tab synced on, with no reload.
    assert visitor_copies.is_own_copy(guests.tokens["A"], own)
    assert _code(guests.live(own)) == "# again\n# mine\nx = 1\n"
    assert dataflow_docs.doc_id_of(own) == held
    dataflow_docs.flush(own)
    assert _code(storage.read_spec(GUEST_KEY, own)["dataflow"]) == "# again\n# mine\nx = 1\n"
    # The example is as it was, on disk and as read.
    assert guests.example_bytes() == before
    assert _code(guests.live(guests.example)) == "x = 1\n"
    # A tab of the same visitor opened later, as after a reload, holds the change.
    assert _code(guests.tab("A").dataflow()) == "# again\n# mine\nx = 1\n"


def test_two_hosted_guests_changes_never_cross(guests):
    a, b = guests.tab("A"), guests.tab("B")
    a_again = guests.tab("A")
    for tab in (a, b, a_again):
        tab.pump()
    b_heard = len(b.received)
    b.set_presence({"pointer": {"x": 5, "y": 5}})

    a.edit(_type("# A's\n"))
    a.set_presence({"pointer": {"x": 1, "y": 1}})
    for tab in (a, b, a_again):
        tab.pump()

    # B heard nothing of A: no update, no presence, and its doc is the example.
    assert len(b.received) == b_heard
    assert b.others() == {}
    assert _code(b.dataflow()) == "x = 1\n"
    # A's other tab, on the same sign-in, shares A's copy and heard the change.
    assert _code(a_again.dataflow()) == "# A's\nx = 1\n"

    b.edit(_type("# B's\n"))
    for tab in (a, b, a_again):
        tab.pump()

    assert _code(a.dataflow()) == "# A's\nx = 1\n"
    assert _code(b.dataflow()) == "# B's\nx = 1\n"
    assert _code(guests.live(guests.own("A"))) == "# A's\nx = 1\n"
    assert _code(guests.live(guests.own("B"))) == "# B's\nx = 1\n"
    assert _code(guests.live(guests.example)) == "x = 1\n"


def test_an_agents_change_to_a_copy_not_made_yet_reaches_the_tab_that_holds_its_doc(guests):
    """A guest's agent works on the guest's copy (``visitor_copies.for_request``):
    its first write makes the copy from the doc the guest's tab holds, so the
    tab syncs on and sees the agent's change land."""
    from utk_curio.backend import config
    from utk_curio.backend.app.collaboration import dataflow_docs
    from utk_curio.backend.app.common.user_storage import GUEST_KEY
    from utk_curio.backend.app.projects import visitor_copies
    from utk_curio.backend.app.users.models import User

    before = guests.example_bytes()
    tab = guests.tab("A")
    held = tab.doc_id
    guest = User.query.filter_by(username=config.CURIO_SHARED_GUEST_USERNAME).one()

    own = visitor_copies.for_request(guest, guests.example, make=True, sign_in=guests.tokens["A"])
    assert own == guests.own("A")
    with dataflow_docs.writing(GUEST_KEY, own, dataflow_docs.by_agent("agent.curio.node-builder@1", GUEST_KEY,
                                                                        "apply")) as spec:
        spec["dataflow"]["nodes"][0]["content"] = "x = 2\n"
    tab.pump()

    assert _code(tab.dataflow()) == "x = 2\n"
    assert tab.doc_id == held and dataflow_docs.doc_id_of(own) == held
    assert guests.example_bytes() == before


def test_a_guests_copy_named_by_its_own_id_is_that_copy_never_a_copy_of_it(guests):
    """An agent's tool names the guest's copy by its id, and a node output it
    adds to the dataflow lands on the dataflow that id names
    (``InstalledDatasetRepository.lands_on``): the copy itself, with no copy
    of the copy made."""
    from flask import g

    from utk_curio.backend import config
    from utk_curio.backend.app.common.user_storage import GUEST_KEY
    from utk_curio.backend.app.datasets.repositories.installed import InstalledDatasetRepository
    from utk_curio.backend.app.projects import storage, visitor_copies
    from utk_curio.backend.app.users.models import User

    guest = User.query.filter_by(username=config.CURIO_SHARED_GUEST_USERNAME).one()
    own = visitor_copies.for_request(guest, guests.example, make=True, sign_in=guests.tokens["A"])
    assert own == guests.own("A")
    nested = visitor_copies.copy_id(guests.tokens["A"], own)

    assert visitor_copies.for_request(guest, own, make=True, sign_in=guests.tokens["A"]) == own
    with guests.application.test_request_context(headers={"Authorization": f"Bearer {guests.tokens['A']}"}):
        g.user = guest
        assert InstalledDatasetRepository(guest).lands_on(own) == own
        assert InstalledDatasetRepository(guest).lands_on(guests.example) == own

    assert not storage.project_dir(GUEST_KEY, nested).exists()
