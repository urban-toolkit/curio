"""The stress tiers' tab (``tests/stress/sockets.py``) against the server's doc.

The tiers' users each open a tab of a shared dataflow over python-socketio.
Here the same ``Tab`` runs on Flask-SocketIO's test client, as the doc tests'
tabs do (``_ydoc_client.py``), so its frames are proven against the server's
own handlers: an owner's and an editor's join and sync, keystrokes and a drag
that reach the other tab, each timed by the ledger, two tabs typing in one node
each keeping its line whole, and a watcher stopped before it types. Nothing
waits on a clock.
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
            if event["name"] == "yjs":
                self.on_yjs(event["args"][0])

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


def test_a_tab_that_joins_as_a_watcher_stops_before_it_types(shared):
    from utk_curio.backend.tests.stress.sockets import SyncLedger, TabFailed

    carol, _link, samples = _tab(shared, "carol", SyncLedger())
    with pytest.raises(TabFailed):
        carol.join()
    assert samples[0][:2] == ("socket connect", True)
    (label, ok, error, kind) = samples[1]
    assert (label, ok, kind) == ("socket join_session", False, "socket")
    assert "'watcher'" in error and len(samples) == 2
