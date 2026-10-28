"""The server's Yjs doc of each open dataflow (``collaboration/dataflow_docs.py``).

Every test runs tabs that are each a pycrdt doc syncing over a Flask-SocketIO
test client (``_ydoc_client.py``), on an app started without ``--collab``,
since every backend serves Socket.IO. alice owns the dataflow, bob is an editor
she invited, and carol watches. Nothing here waits on a clock: the doc is
written when a test calls for it, at the times a test sets.
"""

from __future__ import annotations

import json

import pytest

from ._support import NAMESPACE, connect, invite, join, make_project, make_user

#: alice's dataflow on disk: two nodes, a widget, an edge and a scenario, and
#: sections the server keeps beside the doc.
SPEC = {
    "dataflow": {
        "nodes": [
            {
                "id": "loader", "type": "curio.builtin/code", "x": 10, "y": 20,
                "content": "x = 1\n", "out": "DATAFRAME", "in": "DEFAULT", "goal": "",
                "metadata": {
                    "keywords": [],
                    "widgets": [{"name": "rows", "type": "number", "default": 5, "value": 5,
                                 "options": {"min": 1, "step": 1}}],
                },
            },
            {
                "id": "chart", "type": "curio.builtin/vega-lite", "x": 300, "y": 20,
                "content": "{}", "out": "DEFAULT", "in": "DATAFRAME", "goal": "",
                "metadata": {"keywords": []},
            },
        ],
        "edges": [{"id": "e1", "source": "loader", "target": "chart",
                   "sourceHandle": "out", "targetHandle": "in"}],
        "name": "Shared",
        "task": "",
        "timestamp": 1,
        "provenance_id": "Shared",
        "scenarios": [{"id": "s1", "name": "Base", "color": "#4477aa", "nodes": ["loader"]}],
        "agents": [{"agentId": "agent.curio.node-builder@1"}],
    },
    "nodeProvenance": {"loader": [{"id": "v1"}]},
}


#: What a backend that serves no Socket.IO without --collab fails with.
NO_SOCKETS = "a backend started without --collab serves no Socket.IO"


class _Room:
    """alice's dataflow, with a way to open a tab of it for anyone."""

    def __init__(self, application, socketio, users, tokens, project_id):
        self.application = application
        self.socketio = socketio
        self.users = users
        self.tokens = tokens
        self.project_id = project_id
        self.owner_key = str(users["alice"].id)
        #: The day the doc's log files its changes under, which a test moves.
        self.day = "2026-10-28"

    @property
    def docs(self):
        """The doc server, imported where a test asks for it."""
        from utk_curio.backend.app.collaboration import dataflow_docs

        return dataflow_docs

    def socket(self, name: str):
        assert self.socketio is not None, NO_SOCKETS
        socket = connect(self.socketio, self.application, self.tokens[name])
        ack = join(socket, self.project_id)
        assert ack["ok"] is True, ack
        socket.get_received(namespace=NAMESPACE)
        return socket

    def tab(self, name: str):
        from ._ydoc_client import DocClient

        return DocClient(self.socket(name), self.project_id)

    def on_disk(self) -> dict:
        from utk_curio.backend.app.projects import storage

        return storage.read_spec(self.owner_key, self.project_id)

    def write_elsewhere(self, spec: dict) -> None:
        """Write the spec as a writer that is not the doc does."""
        from utk_curio.backend.app.projects import storage

        storage.write_spec(self.owner_key, self.project_id, spec)

    def revision(self) -> int:
        from utk_curio.backend.app.projects import storage

        return storage.spec_revision(self.owner_key, self.project_id)

    def folder(self):
        from utk_curio.backend.app.projects import storage

        return storage.project_dir(self.owner_key, self.project_id)

    def live(self) -> dict:
        return self.docs.read(self.owner_key, self.project_id)

    def logged(self, doc_id: str, day: str = None) -> list:
        """The updates of a day's segment of a doc's log, today's by default."""
        return self.docs.logged_updates(self.owner_key, self.project_id, doc_id, day or self.day)

    def pointer(self) -> dict:
        return json.loads((self.folder() / self.docs.POINTER_FILE).read_text(encoding="utf-8"))

    def server_doc(self):
        entry = self.docs._open_entry(self.project_id)
        assert entry is not None, "the server holds no doc of the dataflow"
        return entry


@pytest.fixture()
def room(doc_app, monkeypatch):
    application, socketio = doc_app
    from utk_curio.backend.app.projects import storage

    users, tokens = {}, {}
    for name in ("alice", "bob", "carol"):
        users[name], session = make_user(name)
        tokens[name] = session.token
    project_id = make_project(users["alice"])
    invite(project_id, users["alice"], users["bob"])
    storage.write_spec(str(users["alice"].id), project_id, SPEC)
    room = _Room(application, socketio, users, tokens, project_id)
    try:
        from utk_curio.backend.app.collaboration import dataflow_docs
    except ImportError:
        dataflow_docs = None  # each test fails at its own import or assertion
    if dataflow_docs is not None:
        monkeypatch.setattr(dataflow_docs, "_today", lambda: room.day)
    return room


def _type(text: str, *, at: int = 0, node: str = "loader"):
    """A change that types *text* into *node*'s code at *at* (-1: its end)."""

    def change(doc):
        from pycrdt import Map

        content = doc.get("nodes", type=Map)[node]["content"]
        content.insert(len(content) if at == -1 else at, text)

    return change


def _code(dataflow: dict, node: str = "loader") -> str:
    return next(n for n in dataflow["nodes"] if n["id"] == node)["content"]


def test_every_backend_serves_the_sockets_without_collab(doc_app):
    """Socket.IO starts whatever --collab says: a tab connects, joins and
    syncs on an app started without it."""
    from utk_curio.backend import config

    application, socketio = doc_app
    assert config.ENABLE_COLLAB is False
    assert socketio is not None, NO_SOCKETS
    user, session = make_user("alice")
    project_id = make_project(user)
    socket = connect(socketio, application, session.token)
    assert join(socket, project_id)["ok"] is True


def test_an_edit_a_widget_and_a_scenario_reach_the_other_tab(room):
    from utk_curio.backend.app.collaboration import doc_mapping

    alice, bob = room.tab("alice"), room.tab("bob")
    presence_only = room.socket("carol")  # joined the room, never syncs the doc
    assert alice.sync() == {"ok": True, "docId": alice.doc_id, "role": "owner"}
    assert bob.sync() == {"ok": True, "docId": alice.doc_id, "role": "editor"}

    def change(doc):
        from pycrdt import Map

        loader = doc.get("nodes", type=Map)["loader"]
        loader["content"].insert(0, "# shared\n")
        loader["widgets"]["rows"]["value"] = doc_mapping.encode(9)
        doc.get("scenarios", type=Map)["s1"]["name"] = doc_mapping.encode("Cool roofs")

    acks = alice.edit(change)
    assert len(acks) == 1 and acks[0]["ok"] is True, acks
    assert str(alice.doc.client_id) in acks[0]["kept"], "the ack names the clock the server kept"

    seen = bob.dataflow()
    loader = seen["nodes"][0]
    assert loader["content"] == "# shared\nx = 1\n"
    assert loader["metadata"]["widgets"] == [
        {"name": "rows", "type": "number", "default": 5, "options": {"min": 1, "step": 1}, "value": 9}
    ]
    assert seen["scenarios"] == [{"id": "s1", "name": "Cool roofs", "color": "#4477aa", "nodes": ["loader"]}]
    assert seen == alice.dataflow()
    assert room.live()["dataflow"] == {**seen, "agents": SPEC["dataflow"]["agents"]}, (
        "the server's doc holds what the tabs hold"
    )
    names = [event["name"] for event in presence_only.get_received(namespace=NAMESPACE)]
    assert "yjs" not in names, "a tab that never started a sync got the doc's traffic"


def test_a_late_joiner_gets_the_doc(room):
    alice = room.tab("alice")
    alice.sync()
    alice.edit(_type("# first\n"))
    alice.edit(_type("# second\n", at=-1, node="chart"))

    carol = room.tab("carol")
    assert carol.sync() == {"ok": True, "docId": alice.doc_id, "role": "watcher"}
    assert carol.dataflow() == alice.dataflow()
    assert _code(carol.dataflow()) == "# first\nx = 1\n"
    assert _code(carol.dataflow(), "chart") == "{}# second\n"


def test_a_reload_from_disk_keeps_both_tabs_in_step_with_nothing_doubled(room):
    from ._ydoc_client import raw_order

    alice, bob = room.tab("alice"), room.tab("bob")
    alice.sync()
    bob.sync()
    alice.edit(_type("# alice\n"))
    bob.pump()
    bob.edit(_type("# bob\n", at=-1))
    alice.pump()
    before = alice.dataflow()
    assert bob.dataflow() == before
    doc_id = alice.doc_id
    assert "# alice" not in _code(room.on_disk()["dataflow"]), (
        "the spec was written: the reload would not be from the doc's files"
    )

    room.docs.reset_for_tests()  # the backend stopped; what it kept is on disk
    for tab in (alice, bob):
        ack = tab.sync()
        assert ack["ok"] is True and ack["docId"] == doc_id, ack
    assert room.server_doc().doc_id == doc_id
    assert alice.dataflow() == bob.dataflow() == before

    bob.edit(_type("# again\n"))
    after = alice.dataflow()
    assert after == bob.dataflow()
    code = _code(after)
    assert code == "# again\n# alice\nx = 1\n# bob\n", code
    for doc in (alice.doc, bob.doc, room.server_doc().doc):
        assert raw_order(doc, "nodeOrder") == ["loader", "chart"]
        assert raw_order(doc, "edgeOrder") == ["e1"]
        assert raw_order(doc, "scenarioOrder") == ["s1"]


def test_a_doc_out_of_memory_opens_again_as_the_same_doc(room):
    """A minute after its last tab a doc leaves memory, written first; the tab
    that comes back gets the same doc, nothing doubled."""
    alice = room.tab("alice")
    alice.sync()
    alice.edit(_type("# kept\n"))
    doc_id = alice.doc_id
    alice.socket.disconnect(namespace=NAMESPACE)
    assert room.docs.close(room.project_id) is True
    assert not room.docs.is_open(room.project_id)
    assert _code(room.on_disk()["dataflow"]) == "# kept\nx = 1\n", "a doc leaves memory written"

    alice.socket = room.socket("alice")
    assert alice.sync()["docId"] == doc_id
    assert _code(alice.dataflow()) == "# kept\nx = 1\n"


def test_a_doc_whose_state_is_lost_is_built_anew_with_a_new_log_and_the_old_one_stays(room):
    """A doc built anew from Trill gets a new id and a new log, a tab holding
    the old doc reloads, and the old log still rebuilds the old doc."""
    from ._ydoc_client import DocClient

    alice = room.tab("alice")
    alice.sync()
    alice.edit(_type("# kept\n"))
    assert room.docs.flush(room.project_id) is True
    old, day = alice.doc_id, room.docs._today()
    (room.folder() / room.docs.POINTER_FILE).unlink()  # the doc's state is lost
    room.docs.reset_for_tests()

    refused = alice.sync()
    assert refused["ok"] is False and refused["error"] == "reload", refused
    new = refused["docId"]
    assert new != old and room.pointer()["doc"] == new

    fresh = DocClient(alice.socket, room.project_id)
    assert fresh.sync()["docId"] == new
    assert _code(fresh.dataflow()) == "# kept\nx = 1\n", "the doc built anew lost the written code"
    assert room.docs.segments(room.owner_key, room.project_id, new) == [day]
    assert room.docs.segments(room.owner_key, room.project_id, old) == [day], "the old log went"
    old_doc = room.docs.rebuilt(room.owner_key, room.project_id, old, day)
    from utk_curio.backend.app.collaboration import doc_mapping

    assert _code(doc_mapping.doc_to_dataflow(old_doc)) == "# kept\nx = 1\n", "the old log does not read"


def test_a_watchers_update_is_dropped(room):
    from pycrdt import create_sync_message, handle_sync_message

    from utk_curio.backend.app.collaboration.events import READ_ONLY_REFUSAL

    alice, carol = room.tab("alice"), room.tab("carol")
    alice.sync()
    assert carol.sync()["role"] == "watcher"
    assert carol.answers == [], "the server asked a watcher for its changes"

    acks = carol.edit(_type("# carol\n"))
    assert acks == [{"ok": False, "error": "read_only", "message": READ_ONLY_REFUSAL}]
    # Its step 2, all it holds, is dropped too.
    step2 = handle_sync_message(create_sync_message(alice.doc)[1:], carol.doc)
    assert carol.send(step2)["error"] == "read_only"

    assert "# carol" not in _code(alice.dataflow())
    assert "# carol" not in _code(room.live()["dataflow"])
    assert room.logged(alice.doc_id) == [], "a watcher's change reached the log"


def test_an_editor_taken_off_the_list_has_their_next_update_dropped(room):
    from utk_curio.backend.app.projects import access

    alice, bob = room.tab("alice"), room.tab("bob")
    alice.sync()
    bob.sync()
    assert bob.edit(_type("# one\n"))[0]["ok"] is True

    access.remove_editor(room.users["alice"], room.project_id, room.users["bob"].id)

    assert bob.edit(_type("# two\n"))[0]["error"] == "read_only"
    code = _code(alice.dataflow())
    assert "# one" in code and "# two" not in code


def test_awareness_is_named_by_the_server_and_a_watchers_carries_no_edits(room):
    alice, bob, carol = room.tab("alice"), room.tab("bob"), room.tab("carol")
    for tab in (alice, bob, carol):
        tab.sync()
    assert alice.set_presence({
        "user": {"name": "Mallory", "username": "mallory"},
        "pointer": {"x": 1, "y": 2},
        "drag": {"node": "loader", "x": 5, "y": 6},
    }) == {"ok": True}
    assert carol.set_presence({
        "pointer": {"x": 3, "y": 4},
        "selection": {"node": "loader", "anchor": 0, "head": 1},
        "drag": {"node": "chart", "x": 7, "y": 8},
    }) == {"ok": True}

    seen = bob.others()
    by_alice, by_carol = seen[alice.doc.client_id], seen[carol.doc.client_id]
    assert by_alice["user"]["username"] == "alice" and by_alice["user"]["role"] == "owner"
    assert by_alice["user"]["participant_id"], "a state names its participant"
    assert by_alice["drag"] == {"node": "loader", "x": 5, "y": 6}, "an editor's drag shows live"
    assert by_carol == {
        "pointer": {"x": 3, "y": 4},
        "selection": {"node": "loader", "anchor": 0, "head": 1},
        "user": {**by_carol["user"], "username": "carol", "role": "watcher"},
    }, "a watcher's state keeps its presence and no edit"

    # A tab that starts later gets everyone's states, whole.
    later = room.tab("bob")
    later.sync()
    assert later.others() == {client: state for client, state in seen.items()}


def test_awareness_clears_on_disconnect(room):
    alice, bob = room.tab("alice"), room.tab("bob")
    alice.sync()
    bob.sync()
    alice.set_presence({"pointer": {"x": 1, "y": 1}})
    assert alice.doc.client_id in bob.others()

    alice.socket.disconnect(namespace=NAMESPACE)

    assert alice.doc.client_id not in bob.others(), "the others still see a tab that left"
    assert alice.doc.client_id not in room.server_doc().awareness.states


def test_a_tab_cannot_set_another_accounts_awareness(room):
    from pycrdt import Encoder, create_awareness_message

    alice, bob = room.tab("alice"), room.tab("bob")
    alice.sync()
    bob.sync()
    alice.set_presence({"pointer": {"x": 1, "y": 1}})

    forged = Encoder()
    forged.write_var_uint(1)
    forged.write_var_uint(alice.doc.client_id)
    forged.write_var_uint(99)
    forged.write_var_string(json.dumps({"pointer": {"x": 9, "y": 9}}))
    assert bob.send(create_awareness_message(forged.to_bytes())) == {"ok": True}

    assert room.server_doc().awareness.states[alice.doc.client_id]["pointer"] == {"x": 1, "y": 1}
    assert alice.others() == {}, "bob's forged state reached alice"


def test_the_doc_is_written_after_a_second_with_no_change_or_every_ten_seconds(room, monkeypatch):
    now = [100.0]
    monkeypatch.setattr(room.docs, "_clock", lambda: now[0])
    alice = room.tab("alice")
    alice.sync()
    start = room.revision()

    alice.edit(_type("a"))
    now[0] = 100.5
    room.docs.flush_due()
    assert room.revision() == start, "written before a second with no change"
    now[0] = 101.0
    room.docs.flush_due()
    assert room.revision() == start + 1, "not written a second after the last change"
    logged = room.logged(alice.doc_id)
    assert len(logged) == 1, "a write of the spec emptied the log, or the change never reached it"
    folded = room.pointer()["folded"]
    assert folded["segment"] == room.docs._today() and folded["offset"] > 0, folded

    # Steady typing, a change every half second from 101.5: written once, ten
    # seconds after the first change it holds.
    written_at = []
    for step in range(1, 22):
        now[0] = 101.0 + step * 0.5
        alice.edit(_type("b", at=-1))
        before = room.revision()
        room.docs.flush_due()
        if room.revision() != before:
            written_at.append(now[0])
    assert written_at == [111.5], written_at

    on_disk = room.on_disk()
    assert _code(on_disk["dataflow"]) == "ax = 1\n" + "b" * 21
    assert on_disk["dataflow"]["agents"] == SPEC["dataflow"]["agents"], "the doc dropped the agents"
    assert on_disk["nodeProvenance"] == SPEC["nodeProvenance"], "the doc dropped the history"


def test_a_read_of_an_open_dataflow_is_its_doc(room):
    alice = room.tab("alice")
    alice.sync()
    alice.edit(_type("# live\n"))
    assert _code(room.on_disk()["dataflow"]) == "x = 1\n", "the spec was written already"

    live = room.live()
    assert _code(live["dataflow"]) == "# live\nx = 1\n"
    assert live["nodeProvenance"] == SPEC["nodeProvenance"]
    assert live["dataflow"]["agents"] == SPEC["dataflow"]["agents"]

    room.docs.reset_for_tests()  # stopped before the spec was written
    assert _code(room.live()["dataflow"]) == "# live\nx = 1\n", "a read missed what the log holds"


def _written_elsewhere(room) -> None:
    """A writer that is not the doc renames the dataflow and adds a node."""
    spec = room.on_disk()
    spec["dataflow"]["name"] = "Saved elsewhere"
    spec["dataflow"]["nodes"].append({"id": "extra", "type": "curio.builtin/code", "x": 0, "y": 0,
                                      "content": "y = 2\n", "out": "DEFAULT", "in": "DEFAULT", "goal": ""})
    room.write_elsewhere(spec)


def test_a_spec_written_outside_an_open_doc_becomes_a_transaction_on_it(room):
    """The write's changes join the doc, which keeps its own, under the same
    id; every tab gets them, and the next write of the spec holds both."""
    alice = room.tab("alice")
    alice.sync()
    doc_id = alice.doc_id
    alice.edit(_type("# doc\n"))
    _written_elsewhere(room)

    assert room.docs.flush(room.project_id) is True
    on_disk = room.on_disk()["dataflow"]
    assert on_disk["name"] == "Saved elsewhere" and _code(on_disk) == "# doc\nx = 1\n"
    assert [node["id"] for node in on_disk["nodes"]] == ["loader", "chart", "extra"]
    seen = alice.dataflow()
    assert seen["name"] == "Saved elsewhere" and _code(seen, "extra") == "y = 2\n", (
        "the tab did not get the outside write's changes"
    )
    assert room.docs.doc_id_of(room.project_id) == doc_id, "the outside write made a new doc"
    assert len(room.logged(doc_id)) == 2, "the outside write's change is not in the log"


def test_a_spec_written_while_the_doc_was_closed_is_carried_in_when_it_opens(room):
    """A doc whose spec was written outside it while it was closed opens as the
    same doc, the write's changes carried in, so a tab holding it reloads
    nothing."""
    alice = room.tab("alice")
    alice.sync()
    doc_id = alice.doc_id
    alice.edit(_type("# doc\n"))
    room.docs.reset_for_tests()  # stopped before the spec was written
    _written_elsewhere(room)

    ack = alice.sync()
    assert ack["ok"] is True and ack["docId"] == doc_id, ack
    seen = alice.dataflow()
    assert seen["name"] == "Saved elsewhere" and _code(seen) == "# doc\nx = 1\n"
    assert [node["id"] for node in seen["nodes"]] == ["loader", "chart", "extra"]
    assert room.docs.flush(room.project_id) is True
    assert _code(room.on_disk()["dataflow"]) == "# doc\nx = 1\n", "the doc's own change was lost"


def test_the_log_keeps_every_change_in_a_segment_a_day(room):
    """A write of the spec ends nothing; the first change of a new day starts a
    segment whose checkpoint is the doc's state before it, and a reload from
    disk reads every segment's day."""
    from utk_curio.backend.app.collaboration import doc_mapping

    alice = room.tab("alice")
    alice.sync()
    doc_id, first = alice.doc_id, room.day
    alice.edit(_type("# one\n"))
    assert room.docs.flush(room.project_id) is True
    alice.edit(_type("# two\n"))
    assert len(room.logged(doc_id)) == 2, "a write of the spec emptied the log"
    end_of_first_day = alice.dataflow()

    room.day = "2026-10-29"
    alice.edit(_type("# three\n"))
    assert room.docs.segments(room.owner_key, room.project_id, doc_id) == [first, room.day]
    assert len(room.logged(doc_id, first)) == 2 and len(room.logged(doc_id)) == 1
    checkpoint = room.docs.rebuilt(room.owner_key, room.project_id, doc_id, room.day, upto=0)
    assert doc_mapping.doc_to_dataflow(checkpoint) == end_of_first_day, (
        "the new day's checkpoint is not the doc as the day before ended"
    )
    assert room.pointer()["segment"] == room.day

    room.docs.reset_for_tests()
    ack = alice.sync()
    assert ack["ok"] is True and ack["docId"] == doc_id
    assert _code(room.live()["dataflow"]) == "# three\n# two\n# one\nx = 1\n"


def test_text_deleted_before_a_tab_joins_never_reaches_it_and_stays_in_the_log(room):
    """The doc keeps garbage collection on: a tab that joins gets no deleted
    text, while the log, the dataflow's history, keeps what was typed."""
    alice = room.tab("alice")
    alice.sync()
    secret = "api-key-0d9f2e"
    alice.edit(_type(secret))

    def delete(doc):
        from pycrdt import Map

        del doc.get("nodes", type=Map)["loader"]["content"][0:len(secret)]

    alice.edit(delete)
    later = room.tab("carol")
    later.sync()
    assert _code(later.dataflow()) == "x = 1\n"
    assert secret.encode() not in later.doc.get_update(), "a tab that joined got the deleted text"
    assert any(secret.encode() in update for update in room.logged(alice.doc_id)), (
        "the log does not hold what was typed"
    )


def test_a_doc_grown_too_large_is_built_anew_with_a_new_log(room, monkeypatch):
    """A doc no tab holds, grown many times a doc built anew, opens built anew:
    a new id and a new log, the old log kept."""
    from ._ydoc_client import DocClient

    monkeypatch.setattr(room.docs, "REBUILD_FLOOR_BYTES", 0)
    monkeypatch.setattr(room.docs, "GROWN_TOO_LARGE", 1.5)
    socket = room.socket("alice")
    old = None
    # Forty sessions, each a tab of its own and so a Yjs client of its own,
    # each typing a line and taking it out: the doc grows, its Trill does not.
    for session in range(40):
        tab = DocClient(socket, room.project_id)
        assert tab.sync()["ok"] is True
        old = old or tab.doc_id
        line = f"# session {session}\n"
        tab.edit(_type(line))

        def taken_out(doc, line=line):
            from pycrdt import Map

            del doc.get("nodes", type=Map)["loader"]["content"][0:len(line)]

        tab.edit(taken_out)
    socket.disconnect(namespace=NAMESPACE)
    assert room.docs.close(room.project_id) is True

    fresh = room.tab("alice")
    ack = fresh.sync()
    assert ack["ok"] is True and ack["docId"] != old, "the grown doc was not built anew"
    assert _code(fresh.dataflow()) == "x = 1\n"
    assert room.pointer()["doc"] == ack["docId"]
    assert room.docs.segments(room.owner_key, room.project_id, old) == [room.day], "the old log went"


def test_a_doc_hands_over_no_history_and_a_spec_that_held_its_history_keeps_it(room, monkeypatch):
    """A spec saved before the history moved beside it still holds the
    history. The doc writes its dataflow and leaves the history out, so every
    version stays on record, and no write of the doc reads the history."""
    from utk_curio.backend.app.projects import storage

    storage.drop_history(room.owner_key, room.project_id)
    marker = "history-entry-5c1e"
    legacy = dict(SPEC, nodeProvenance={"loader": [{"id": marker}]},
                  dataflowProvenance={"latest": marker, "versions": {marker: {"dataflow": {}}}})
    (room.folder() / storage.SPEC_FILE).write_text(json.dumps(legacy), encoding="utf-8")
    handed = []
    write_spec = storage.write_spec

    def recorded(user_key, project_id, spec):
        handed.append(sorted(spec))
        return write_spec(user_key, project_id, spec)

    monkeypatch.setattr(storage, "write_spec", recorded)
    alice, carol = room.tab("alice"), room.tab("carol")
    alice.sync()
    carol.sync()
    # The history never enters the doc, so no tab, a watcher's included, gets it.
    for tab in (alice, carol):
        assert marker.encode() not in tab.doc.get_update(), "the doc holds the dataflow's history"
    alice.edit(_type("# doc\n"))
    assert room.docs.flush(room.project_id) is True

    assert handed and not set(handed[-1]) & set(storage.HISTORY_KEYS), (
        f"the doc handed write_spec the history: {handed}"
    )
    on_disk = room.on_disk()
    assert _code(on_disk["dataflow"]) == "# doc\nx = 1\n"
    assert on_disk["nodeProvenance"] == legacy["nodeProvenance"], "the doc's write erased the history"
    assert on_disk["dataflowProvenance"] == legacy["dataflowProvenance"]


def test_a_doc_message_needs_a_join_a_started_sync_and_frames_that_read(room):
    from pycrdt import create_update_message

    from ._ydoc_client import DocClient

    assert room.socketio is not None, NO_SOCKETS
    stranger = connect(room.socketio, room.application, room.tokens["carol"])
    assert DocClient(stranger, room.project_id).sync()["error"] == "not_joined"

    alice = room.tab("alice")
    assert alice.send(create_update_message(b"\x00\x00"))["error"] == "not_synced"
    alice.sync()
    for frame in (b"\x07\x01", b"\x00", b"\x00\x02", b"\x01", create_update_message(b"\x01\x02\x03")):
        assert alice.send(frame)["error"] == "invalid_message", frame
    assert alice.edit(_type("# still fine\n"))[0]["ok"] is True
