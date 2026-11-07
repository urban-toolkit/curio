"""The stress tiers' tab (``tests/stress/sockets.py``) against the server's doc.

The tiers' users each open a tab of a shared dataflow over python-socketio.
Here the same ``Tab`` runs on Flask-SocketIO's test client, as the doc tests'
tabs do (``_ydoc_client.py``), so its frames are proven against the server's
own handlers: an owner's and an editor's join and sync, keystrokes and a drag
that reach the other tab, each timed by the ledger, two tabs typing in one node
each keeping its line whole, a watcher stopped before it types, and two
members of a shared canvas each adding a node and its connection, one getting
the lock of the node both type in and the other typing anyway. Nothing waits
on a clock.
"""

from __future__ import annotations

import pytest

from ._support import NAMESPACE, connect, invite, make_project, make_user

#: alice's dataflow: two nodes with code, and an edge.
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
        "name": "Shared", "task": "", "timestamp": 1, "provenance_id": "Shared",
    },
}


class _TestLink:
    """A tab's socket on Flask-SocketIO's test client: an answer comes back
    with its emit, and what the server sent reaches the tab when pumped."""

    transport = "test client"

    def __init__(self, client):
        self.client = client
        self.on_yjs = None
        #: The tab's handler of the room's lock events, when a test gives it one.
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


@pytest.fixture()
def shared(doc_app):
    """alice's dataflow on disk, bob invited to edit it, carol not."""
    application, socketio = doc_app
    from utk_curio.backend.app.projects import storage

    users, tokens = {}, {}
    for name in ("alice", "bob", "carol"):
        users[name], session = make_user(name)
        tokens[name] = session.token
    project_id = make_project(users["alice"])
    invite(project_id, users["alice"], users["bob"])
    storage.write_spec(str(users["alice"].id), project_id, SPEC)
    return {"application": application, "socketio": socketio, "project_id": project_id,
            "tokens": tokens, "owner_key": str(users["alice"].id)}


def _tab(shared, name, ledger):
    """*name*'s tab, connected; its link and the samples it recorded."""
    from utk_curio.backend.tests.stress.sockets import Tab

    assert shared["socketio"] is not None, "every backend serves Socket.IO"
    link = _TestLink(connect(shared["socketio"], shared["application"], shared["tokens"][name]))
    samples = []

    def record(label, seconds, ok, error=None, kind=None):
        samples.append((label, ok, error, kind))

    tab = Tab(name, shared["project_id"], ledger, record)
    tab.connect(link.bind)
    return tab, link, samples


def _synced(shared, ledger, *names):
    tabs = []
    for name in names:
        tab, link, samples = _tab(shared, name, ledger)
        tab.join()
        tab.sync()
        ledger.synced(name)
        tabs.append((tab, link, samples))
    return tabs


def _dataflow(tab) -> dict:
    from utk_curio.backend.app.collaboration import doc_mapping

    with tab.lock:
        return doc_mapping.doc_to_dataflow(tab.doc)


def _node(dataflow: dict, node_id: str) -> dict:
    return next(node for node in dataflow["nodes"] if node["id"] == node_id)


def test_a_tabs_keystrokes_and_drag_reach_the_other_tab_each_timed(shared):
    from utk_curio.backend.app.collaboration import dataflow_docs
    from utk_curio.backend.tests.stress.sockets import DRAG_STEP, SyncLedger

    ledger = SyncLedger()
    (alice, _alice_link, alice_samples), (bob, bob_link, _) = _synced(shared, ledger, "alice", "bob")
    assert (alice.role, bob.role) == ("owner", "editor")
    assert alice.doc_id is not None and alice.doc_id == bob.doc_id
    assert alice.target([("loader", "# ")]) == ("loader", "# ")

    for char in "# hi\n":
        alice.keystroke("loader", char)
    alice.drag("loader")
    assert ledger.open == 6, "bob has not read what the server relayed"
    bob_link.pump()

    assert (ledger.updates, ledger.open, ledger.deliveries) == (6, 0, 6)
    assert len(ledger.seconds) == 6 and min(ledger.seconds) >= 0
    seen = _node(_dataflow(bob), "loader")
    assert seen["content"] == "# hi\nx = 1\n"
    assert (seen["x"], seen["y"]) == (10 + DRAG_STEP, 20 + DRAG_STEP)
    assert bob.digest() == alice.digest()
    updates = [sample for sample in alice_samples if sample[0] == "socket yjs update"]
    assert len(updates) == 6 and all(ok for _label, ok, _error, _kind in alice_samples), alice_samples
    live = dataflow_docs.read(shared["owner_key"], shared["project_id"])
    assert _node(live["dataflow"], "loader")["content"] == "# hi\nx = 1\n", "the server's doc has it too"


def test_two_tabs_typing_in_one_node_each_keep_their_line_whole(shared):
    """Each tab types after its own last keystroke, as an editor's cursor
    stays, so concurrent typing never splits a line."""
    from utk_curio.backend.tests.stress.sockets import SyncLedger

    ledger = SyncLedger()
    (alice, alice_link, _), (bob, bob_link, _) = _synced(shared, ledger, "alice", "bob")
    for mine, theirs in zip("# alice\n", "# bobby\n"):
        alice.keystroke("loader", mine)
        bob.keystroke("loader", theirs)
        alice_link.pump()
        bob_link.pump()

    code = _node(_dataflow(alice), "loader")["content"]
    assert code == _node(_dataflow(bob), "loader")["content"]
    lines = code.splitlines(keepends=True)
    assert sorted(lines[:2]) == ["# alice\n", "# bobby\n"] and lines[2:] == ["x = 1\n"], code
    assert (ledger.open, len(ledger.seconds)) == (0, 16)


def test_two_members_each_add_a_node_and_a_connection_and_leave_no_lock(shared):
    """A shared canvas's members, the owner and an editor: each adds its own
    node below the loader, with its connection, as the canvas writes them.
    alice gets the loader's lock; bob, refused, types there anyway, as the
    canvas lets him, and lets go of nothing; alice types and lets her lock go.
    With both tabs still open, both hold the same doc, the server's doc holds
    both nodes, both connections and both members' lines, and no lock is held:
    in the server's room, as a tab joining now is told, or in either tab."""
    from utk_curio.backend.app.collaboration import dataflow_docs, room_state
    from utk_curio.backend.tests.stress.driver import Pacing
    from utk_curio.backend.tests.stress.sockets import PASS_ON_CODE, SyncLedger, member_node

    ledger = SyncLedger()
    (alice, alice_link, alice_samples), (bob, bob_link, bob_samples) = _synced(shared, ledger, "alice", "bob")
    alice_link.on_room, bob_link.on_room = alice.room_event, bob.room_event
    added = {}
    for row, (name, tab) in enumerate((("alice", alice), ("bob", bob)), 1):
        node, edge = member_node({"id": "loader", "x": 10, "y": 20}, row)
        tab.add_node(node, edge)
        added[name] = (node["id"], edge["id"])
    alice_link.pump()
    bob_link.pump()
    assert (ledger.open, alice.digest()) == (0, bob.digest())

    assert alice.take_lock("loader") is True
    bob_link.pump()
    assert bob.room_locks() == {"loader": "alice"}, "bob's tab shows alice's lock, as the canvas's chip"
    no_pause = Pacing(key_gap_min=0.0, key_gap_max=0.0)
    _, bob_line = bob.work([("loader", "# ")], no_pause, lock=True)
    _, alice_line = alice.work([("loader", "# ")], no_pause)
    alice.release_lock("loader")
    alice_link.pump()
    bob_link.pump()

    assert ledger.open == 0
    assert alice.digest() == bob.digest()
    assert (alice.locks_taken, alice.locks_released, alice.locks_refused) == (1, 1, 0)
    assert (bob.locks_taken, bob.locks_released, bob.locks_refused) == (0, 0, 1)
    room = room_state.room_for(shared["project_id"])
    assert room_state.snapshot(room)["locks"] == {}
    assert alice.room_locks() == {} and bob.room_locks() == {}
    assert bob.server_locks() == {}, "a tab joining now is told of no lock"
    live = dataflow_docs.read(shared["owner_key"], shared["project_id"])["dataflow"]
    nodes = {node["id"]: node for node in live["nodes"]}
    edges = {edge["id"]: edge for edge in live["edges"]}
    for node_id, edge_id in added.values():
        assert nodes[node_id]["content"] == PASS_ON_CODE
        assert (edges[edge_id]["source"], edges[edge_id]["target"]) == ("loader", node_id)
    code = nodes["loader"]["content"]
    assert code.count(alice_line) == 2 and code.count(bob_line) == 2 and code.endswith("x = 1\n"), code
    samples = alice_samples + bob_samples
    assert all(ok for _label, ok, _error, _kind in samples), samples


def test_a_tab_that_joins_as_a_watcher_stops_before_it_types(shared):
    from utk_curio.backend.tests.stress.sockets import SyncLedger, TabFailed

    carol, _link, samples = _tab(shared, "carol", SyncLedger())
    with pytest.raises(TabFailed):
        carol.join()
    assert samples[0][:2] == ("socket connect", True)
    (label, ok, error, kind) = samples[1]
    assert (label, ok, kind) == ("socket join_session", False, "socket")
    assert "'watcher'" in error and len(samples) == 2
