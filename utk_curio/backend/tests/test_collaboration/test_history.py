"""A dataflow's history, kept by the server as points in its doc's log
(``collaboration/history.py``).

Every change of an open doc is a point of the history, a transaction and its
origin each: a node or a connection added or removed, an agent's change, a
person's typing once they pause or leave the editor, a run, a Map Editor edit,
File > Save, a version or a node's code put back. A version is the doc rebuilt
up to its point, and a node's entries are notes on points. A dataflow with no
points gets them when its doc first opens: the history it carries, imported
once, or the dataflow a node and then a connection at a time. Only the owner
and the editors the owner invited read and change it, and the owner may clear
it before a version.

alice owns the dataflow, bob is an editor she invited, and carol watches. The
tabs are pycrdt docs syncing over a Flask-SocketIO test client
(``_ydoc_client.py``). Nothing waits on a clock: typing is due when a test says
the clock moved. New names are imported inside each test, so the module imports
on a checkout without them and each test fails on its own.
"""

from __future__ import annotations

import copy
import json

import pytest

from .test_dataflow_docs import room  # noqa: F401 - room is a fixture

#: The agent the agent's change here is made as.
BUILDER = "agent.curio.node-builder@1"

#: alice's dataflow, with no history: three nodes and two connections.
FLOW = {
    "dataflow": {
        "nodes": [
            {"id": "loader", "type": "curio.builtin/code", "x": 10, "y": 20, "content": "x = 1\n",
             "out": "DATAFRAME", "in": "DEFAULT", "goal": ""},
            {"id": "shaper", "type": "curio.builtin/code", "x": 300, "y": 20, "content": "y = x\n",
             "out": "DATAFRAME", "in": "DATAFRAME", "goal": ""},
            {"id": "chart", "type": "curio.builtin/vega-lite", "x": 600, "y": 20, "content": "{}",
             "out": "DEFAULT", "in": "DATAFRAME", "goal": ""},
        ],
        "edges": [
            {"id": "e1", "source": "loader", "target": "shaper", "sourceHandle": "out", "targetHandle": "in"},
            {"id": "e2", "source": "shaper", "target": "chart", "sourceHandle": "out", "targetHandle": "in"},
        ],
        "name": "Kept",
        "task": "",
        "timestamp": 1,
        "provenance_id": "Kept",
    },
}


class _Clock:
    """The doc server's clock, which a test moves."""

    def __init__(self):
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture()
def kept(room, monkeypatch):
    """alice's dataflow as FLOW, with no history, its server's clock the
    test's."""
    from utk_curio.backend.app.collaboration import dataflow_docs
    from utk_curio.backend.app.projects import storage

    clock = _Clock()
    monkeypatch.setattr(dataflow_docs, "_clock", clock)
    storage.drop_history(room.owner_key, room.project_id)
    storage.write_spec(room.owner_key, room.project_id, copy.deepcopy(FLOW))
    room.clock = clock
    return room


def _auth(room, name: str = "alice") -> dict:
    return {"Authorization": f"Bearer {room.tokens[name]}", "Content-Type": "application/json"}


def _http(room):
    return room.application.test_client()


def _synced(room, name: str):
    tab = room.tab(name)
    ack = tab.sync()
    assert ack["ok"] is True, ack
    return tab


def _points(room) -> list:
    from utk_curio.backend.app.collaboration import history

    return history.points(room.owner_key, room.project_id)


def _dataflow_at(room, point_id: str) -> dict:
    from utk_curio.backend.app.collaboration import history

    flow = history.dataflow_at(room.owner_key, room.project_id, point_id)
    assert flow is not None, f"the version {point_id} does not rebuild"
    return flow


def _node_ids(flow: dict) -> list:
    return [node["id"] for node in flow.get("nodes") or []]


def _code_of(flow: dict, node_id: str):
    return next((node.get("content") for node in flow.get("nodes") or [] if node["id"] == node_id), None)


def _add_node(node_id: str, **fields):
    """A change that adds a node, as a tab's canvas writes one."""

    def change(doc):
        from utk_curio.backend.app.collaboration import doc_mapping

        before = doc_mapping.doc_to_dataflow(doc)
        after = copy.deepcopy(before)
        after["nodes"].append({"id": node_id, "type": "curio.builtin/code", "x": 0, "y": 400,
                               "content": "z = 3\n", **fields})
        doc_mapping.apply_dataflow(doc, before, after)

    return change


def _remove_edge(edge_id: str):
    def change(doc):
        from utk_curio.backend.app.collaboration import doc_mapping

        before = doc_mapping.doc_to_dataflow(doc)
        after = copy.deepcopy(before)
        after["edges"] = [edge for edge in after["edges"] if edge["id"] != edge_id]
        doc_mapping.apply_dataflow(doc, before, after)

    return change


def _set_fields(**fields):
    """A change to the dataflow's own fields, as a tab's canvas writes one."""

    def change(doc):
        from utk_curio.backend.app.collaboration import doc_mapping

        before = doc_mapping.doc_to_dataflow(doc)
        doc_mapping.apply_dataflow(doc, before, {**copy.deepcopy(before), **copy.deepcopy(fields)})

    return change


def _type(text: str, node: str = "loader", at: int = 0):
    def change(doc):
        from pycrdt import Map

        doc.get("nodes", type=Map)[node]["content"].insert(at, text)

    return change


def _erase(text: str, node: str = "loader"):
    """A change that deletes the first *text* in *node*'s code."""

    def change(doc):
        from pycrdt import Map

        content = doc.get("nodes", type=Map)[node]["content"]
        at = str(content).index(text)
        start = len(str(content)[:at].encode("utf-8"))
        del content[start:start + len(text.encode("utf-8"))]

    return change


# ---------------------------------------------------------------------------
# Points the server records
# ---------------------------------------------------------------------------

def test_each_transaction_of_a_batch_is_a_point_of_its_own_named_after_its_origin(kept):
    """Updates applied as one batch, as a burst of typing in a room makes them,
    are each a transaction of their own, and each is a point named after the
    tab that sent it."""
    from utk_curio.backend.app.collaboration import dataflow_docs, doc_mapping, history

    _synced(kept, "alice")
    entry = kept.server_doc()
    people = {
        "alice": {"user_id": kept.users["alice"].id, "name": "Alice", "role": "owner"},
        "bob": {"user_id": kept.users["bob"].id, "name": "Bob", "role": "editor"},
    }
    before = len(_points(kept))
    with entry.lock:
        changes = []
        for name, node_id in (("alice", "from-alice"), ("bob", "from-bob")):
            was = doc_mapping.doc_to_dataflow(entry.doc)
            now = copy.deepcopy(was)
            now["nodes"].append({"id": node_id, "type": "curio.builtin/code", "x": 0, "y": 0, "content": ""})
            with entry.doc.transaction(origin=f"sid-{name}"):
                doc_mapping.apply_dataflow(entry.doc, was, now)
            updates, entry.updates = entry.updates, []
            touched = history.take_touched(entry)
            start, end = dataflow_docs._append(entry, updates)
            changes.append(history.Change(history.Tab(f"sid-{name}", people[name]), start, end, touched))
        history.recorded(entry, changes)
    made = _points(kept)[before:]
    assert [(p["kind"], p["what"], p["by"]["name"]) for p in made] == [
        ("graph", "Node added", "Alice"), ("graph", "Node added", "Bob"),
    ], made
    assert made[1]["parent"] == made[0]["id"], "the second change is made from the first"
    assert "from-alice" in _node_ids(_dataflow_at(kept, made[0]["id"]))
    assert "from-bob" not in _node_ids(_dataflow_at(kept, made[0]["id"]))
    assert {"from-alice", "from-bob"} <= set(_node_ids(_dataflow_at(kept, made[1]["id"])))


def test_tabs_updates_applied_as_one_batch_are_a_point_per_tab_and_transaction(kept, monkeypatch):
    """Through the server's own batch (``dataflow_docs._apply_batch``):
    updates from several tabs that wait for the doc together are written to
    the log at once, and each is still a point of its own, named after the
    account of the tab that sent it, holding the dataflow up to its change."""
    from .test_doc_batches import _Burst, _sender

    names = {"from-alice": "Alice", "from-bob": "Bob", "from-ana": "Alice"}
    tabs = {"alice": _synced(kept, "alice"), "bob": _synced(kept, "bob"), "ana": _synced(kept, "alice")}
    for tab in tabs.values():
        tab.pump()
    count = len(_points(kept))
    burst = _Burst(kept, monkeypatch)
    answers: dict = {}
    burst.run(*(_sender(tab, _add_node(f"from-{name}"), answers, name) for name, tab in tabs.items()))
    for name in tabs:
        assert all(ack["ok"] for ack in answers.get(name) or [{"ok": False}]), (name, answers.get(name))
    assert max(burst.writes) >= 2, f"no write held more than one tab's update: {burst.writes}"

    made = _points(kept)[count:]
    assert [p["kind"] for p in made] == ["graph"] * 3, made
    held: set = set()
    for i, point in enumerate(made):
        now = {node for node in _node_ids(_dataflow_at(kept, point["id"])) if node in names}
        added = now - held
        assert len(added) == 1, f"point {point['id']} holds {sorted(now)} after {sorted(held)}"
        (node,) = added
        assert (point["what"], point["by"]["name"]) == ("Node added", names[node]), (node, point)
        if i:
            assert point["start"] >= made[i - 1]["end"], "two points of one write share records"
            assert point["parent"] == made[i - 1]["id"]
        held = now
    assert held == set(names)


def test_a_node_a_tab_adds_is_a_version_holding_it(kept):
    from utk_curio.backend.app.collaboration import history

    alice = _synced(kept, "alice")
    head = history.versions(kept.owner_key, kept.project_id)["head"]
    acks = alice.edit(_add_node("added"))
    assert all(ack["ok"] for ack in acks), acks
    listed = history.versions(kept.owner_key, kept.project_id)
    newest = listed["versions"][-1]
    assert (newest["kind"], newest["what"], newest["by"]["name"]) == ("graph", "Node added", "Alice"), newest
    assert newest["parent"] == head, "a version is made from the version on the canvas"
    assert listed["head"] == newest["id"]
    assert "added" in [node["id"] for node in newest["preview"]["nodes"]]


def test_two_tabs_list_the_same_versions(kept):
    """What either tab changes is one history, which both read the same."""
    alice, bob = _synced(kept, "alice"), _synced(kept, "bob")
    alice.edit(_add_node("by-alice"))
    bob.pump()
    bob.edit(_remove_edge("e2"))
    alice.pump()
    seen = {}
    for name in ("alice", "bob"):
        answer = _http(kept).get(f"/api/projects/{kept.project_id}/history", headers=_auth(kept, name))
        assert answer.status_code == 200, answer.get_json()
        seen[name] = [(v["id"], v["parent"], v["kind"], v["what"]) for v in answer.get_json()["versions"]]
    assert seen["alice"] == seen["bob"]
    assert [what for _id, _parent, _kind, what in seen["alice"][-2:]] == ["Node added", "Connection deleted"]


def test_a_dataflow_with_no_history_gets_a_point_for_no_node_then_one_a_node_then_one_a_connection(kept):
    """The 10-06 rule, kept by the server: the dataflow with no node, then a
    version per node, then a version per connection, each holding the whole
    graph as it stood, every connection's two nodes among its own (#195), each
    under an id of its own (#186)."""
    from utk_curio.backend.app.collaboration import history

    _synced(kept, "alice")
    listed = history.versions(kept.owner_key, kept.project_id)["versions"]
    flow = FLOW["dataflow"]
    assert len(listed) == 1 + len(flow["nodes"]) + len(flow["edges"]), listed
    assert len({v["id"] for v in listed}) == len(listed), "two versions share an id"
    assert [v["what"] for v in listed] == [""] + ["Node added"] * 3 + ["Connection added"] * 2
    for i, version in enumerate(listed):
        preview = version["preview"]
        held = {node["id"] for node in preview["nodes"]}
        assert len(preview["nodes"]) == min(i, len(flow["nodes"]))
        for edge in preview["edges"]:
            assert edge["source"] in held and edge["target"] in held, (version["id"], edge)
        if i:
            assert version["parent"] == listed[i - 1]["id"]
    last = _dataflow_at(kept, listed[-1]["id"])
    assert [(n["id"], n["content"]) for n in last["nodes"]] == [(n["id"], n["content"]) for n in flow["nodes"]]
    assert [e["id"] for e in last["edges"]] == ["e1", "e2"]


def _earlier_history() -> dict:
    """An earlier history as a canvas saved it: the load's versions, then a
    branch from the second one, each a whole copy of the dataflow, and runs
    and an edit of the loader."""
    flow = FLOW["dataflow"]
    rest = {k: v for k, v in flow.items() if k not in ("nodes", "edges", "timestamp")}
    stamps = [1_790_000_000_000 + step for step in range(5)]
    held = [
        ([], []),
        (flow["nodes"][:1], []),
        (flow["nodes"][:2], []),
        (flow["nodes"][:2], flow["edges"][:1]),
        (flow["nodes"][:1] + [{**flow["nodes"][2], "x": 900}], []),
    ]
    keys = [f"Kept_{stamp}" for stamp in stamps]
    versions = {key: {"dataflow": {"nodes": copy.deepcopy(nodes), "edges": copy.deepcopy(edges), **rest,
                                   "timestamp": stamp}}
                for key, stamp, (nodes, edges) in zip(keys, stamps, held)}
    graph_edges = [
        {"id": f"{keys[0]}_to_{keys[1]}", "source": keys[0], "target": keys[1], "label": "Node added"},
        {"id": f"{keys[1]}_to_{keys[2]}", "source": keys[1], "target": keys[2], "label": "Node added"},
        {"id": f"{keys[2]}_to_{keys[3]}", "source": keys[2], "target": keys[3], "label": "Connection added"},
        {"id": f"{keys[1]}_to_{keys[4]}", "source": keys[1], "target": keys[4], "label": "Node added"},
    ]
    entries = {
        "loader": [
            {"id": 1, "parentId": None, "code": "x = 1\n", "inputs": [], "outputs": ["DATAFRAME"],
             "startTime": "Oct 28 2026 10:1:0", "endTime": "Oct 28 2026 10:1:2"},
            {"id": 2, "parentId": 1, "code": "x = 2\n", "inputs": [], "outputs": [],
             "startTime": "Oct 28 2026 10:2:0", "endTime": "Oct 28 2026 10:2:0",
             "kind": "edit", "label": "Node Builder", "before": "x = 1\n"},
        ],
        "gone-node": [
            {"id": 3, "parentId": None, "code": "gone()\n", "inputs": [], "outputs": [],
             "startTime": "Oct 28 2026 10:3:0", "endTime": "Oct 28 2026 10:3:1"},
        ],
    }
    return {
        "dataflowProvenance": {
            "id": "Kept", "latest": keys[3],
            "graph": {"id": "Kept", "nodes": [{"id": key, "timestamp": stamp} for key, stamp in zip(keys, stamps)],
                      "edges": graph_edges},
            "versions": versions,
        },
        "nodeProvenance": entries,
    }


def test_the_earlier_history_is_imported_once_with_its_ids_times_and_parents(kept):
    """#1204's logs, read once on the dataflow's first open: each version a
    point with its id, time and parent, its dataflow the version's, the tree
    kept as parents along one timeline; each entry a note whose code is the
    entry's; the version on the canvas the one it was. The logs are then set
    aside, and a second open imports nothing."""
    from utk_curio.backend.app.collaboration import dataflow_docs, doc_mapping, history
    from utk_curio.backend.app.projects import storage

    earlier = _earlier_history()
    storage.write_spec(kept.owner_key, kept.project_id, {**copy.deepcopy(FLOW), **copy.deepcopy(earlier)})
    _synced(kept, "alice")
    points = _points(kept)
    versions = earlier["dataflowProvenance"]["versions"]
    imported = [p for p in points if p["kind"] == "imported"]
    assert [p["id"] for p in imported] == list(versions)
    stamps = {node["id"]: node["timestamp"] for node in earlier["dataflowProvenance"]["graph"]["nodes"]}
    parents = {edge["target"]: edge["source"] for edge in earlier["dataflowProvenance"]["graph"]["edges"]}
    for point in imported:
        assert point["at"] == stamps[point["id"]]
        assert point.get("parent") == parents.get(point["id"]), point
        want = dataflow_docs._normalized(doc_mapping.owned(versions[point["id"]]["dataflow"]))
        assert doc_mapping.same(_dataflow_at(kept, point["id"]), want), point["id"]
    assert history.head_of(points) == earlier["dataflowProvenance"]["latest"]
    listed = history.versions(kept.owner_key, kept.project_id)
    assert listed["head"] == earlier["dataflowProvenance"]["latest"]

    loader = history.entries(kept.owner_key, kept.project_id, "loader", code="x = 1\n")
    assert [(e["id"], e["parentId"], e["code"]) for e in loader["entries"]] == [(1, None, "x = 1\n"), (2, 1, "x = 2\n")]
    assert loader["entries"][1]["kind"] == "edit" and loader["entries"][1]["label"] == "Node Builder"
    assert loader["entries"][1]["before"] == "x = 1\n"
    assert loader["current"] == 1, "the entry in use holds the node's code"
    gone = history.entries(kept.owner_key, kept.project_id, "gone-node")
    assert [e["code"] for e in gone["entries"]] == ["gone()\n"], "an entry whose node is gone keeps its code"

    # Set aside, read by nothing.
    assert not any(key in storage.read_spec(kept.owner_key, kept.project_id) for key in storage.HISTORY_KEYS)
    assert storage.history_sections(kept.owner_key, kept.project_id) == {}
    aside = kept.folder() / storage.HISTORY_DIR / storage.IMPORTED_DIR
    assert sorted(path.name for path in aside.iterdir()) == ["entries.jsonl", "versions.jsonl"]

    # Opened again, nothing is imported twice.
    count = len(_points(kept))
    dataflow_docs.close_all()
    _synced(kept, "alice")
    assert len(_points(kept)) == count


def test_an_earlier_version_the_doc_has_no_place_for_is_left_out_and_its_child_takes_its_parent(kept):
    from utk_curio.backend.app.collaboration import history
    from utk_curio.backend.app.projects import storage

    earlier = _earlier_history()
    keys = list(earlier["dataflowProvenance"]["versions"])
    # A node field named like a key the doc gives a node for something else.
    broken = earlier["dataflowProvenance"]["versions"][keys[2]]["dataflow"]["nodes"][1]
    broken["widgetOrder"] = ["not", "this"]
    storage.write_spec(kept.owner_key, kept.project_id, {**copy.deepcopy(FLOW), **earlier})
    _synced(kept, "alice")
    imported = {p["id"]: p for p in _points(kept) if p["kind"] == "imported"}
    assert keys[2] not in imported, "the version with no place in the doc was imported"
    assert imported[keys[3]]["parent"] == keys[1], "its child takes its parent"
    assert history.head_of(_points(kept)) == keys[3]


def test_a_tabs_typing_is_a_point_named_after_the_typist_once_they_pause_or_leave_the_editor(kept):
    from utk_curio.backend.app.collaboration import dataflow_docs, history

    alice, bob = _synced(kept, "alice"), _synced(kept, "bob")
    count = len(_points(kept))
    bob.edit(_type("# one\n"))
    bob.edit(_type("# two\n"))
    kept.clock.now += 5
    dataflow_docs.flush_due(kept.clock.now)
    assert len(_points(kept)) == count, "typing became a point before its pause"
    kept.clock.now += history.TYPING_PAUSE_S
    dataflow_docs.flush_due(kept.clock.now)
    made = _points(kept)[count:]
    assert [(p["kind"], p["what"], p["by"]["name"]) for p in made] == [("typing", "Bob edited", "Bob")], made
    assert [(n["node"], n["kind"], n["label"]) for n in made[0]["notes"]] == [("loader", "edit", "Bob edited")]
    assert _code_of(_dataflow_at(kept, made[0]["id"]), "loader") == "# two\n# one\nx = 1\n"

    # Leaving the editor ends it at once.
    alice.set_presence({"editing": "shaper"})
    alice.edit(_type("# alice\n", node="shaper"))
    assert len(_points(kept)) == count + 1
    alice.set_presence({"editing": None})
    newest = _points(kept)[-1]
    assert (newest["kind"], newest["what"]) == ("typing", "Alice edited")
    entries = history.entries(kept.owner_key, kept.project_id, "shaper")["entries"]
    assert entries[-1]["code"] == "# alice\ny = x\n" and entries[-1]["before"] == "y = x\n"


def test_a_run_follows_the_typing_before_it_and_a_map_editor_edit_takes_its_place(kept):
    """One action, one entry: typing and then running are two, and an edit made
    in the node's body is one, under its own name."""
    alice = _synced(kept, "alice")
    count = len(_points(kept))
    alice.edit(_type("# a\n"))
    answer = _http(kept).post(
        f"/api/projects/{kept.project_id}/history/nodes/loader/runs", headers=_auth(kept),
        data=json.dumps({"code": "# a\nx = 1\n", "inputs": [], "outputs": ["DATAFRAME"],
                         "startTime": "2026-10-29T10:00:00Z", "endTime": "2026-10-29T10:00:01Z"}),
    )
    assert answer.status_code == 201, answer.get_json()
    made = _points(kept)[count:]
    assert [p["kind"] for p in made] == ["typing", "run"], made
    run = made[1]["notes"][0]
    assert (run["kind"], run["outputs"], "code" in run) == ("run", ["DATAFRAME"], False)

    alice.edit(_type("# b\n"))
    answer = _http(kept).post(
        f"/api/projects/{kept.project_id}/history/nodes/loader/edits", headers=_auth(kept),
        data=json.dumps({"label": "Remove building_id 119"}),
    )
    assert answer.status_code == 201, answer.get_json()
    made = _points(kept)[count + 2:]
    assert [(p["kind"], p["what"]) for p in made] == [("edit", "Remove building_id 119")], made
    assert made[0]["start"] < made[0]["end"], "the edit's point holds the typing it took the place of"


def test_a_read_before_any_tab_opened_the_dataflow_gives_it_its_first_points(kept):
    """The drawer can ask before any tab's sync opened the dataflow's doc: the
    read opens it, and lists the versions the open made."""
    from utk_curio.backend.app.collaboration import history

    assert not history.has_points(kept.owner_key, kept.project_id)
    listed = _http(kept).get(f"/api/projects/{kept.project_id}/history", headers=_auth(kept)).get_json()
    assert listed["kept"] is True, listed
    assert [v["kind"] for v in listed["versions"]] == ["load"] * (1 + 3 + 2), listed["versions"]
    assert listed["head"] == listed["versions"][-1]["id"]
    entries = _http(kept).get(f"/api/projects/{kept.project_id}/history/nodes/loader",
                              headers=_auth(kept)).get_json()
    assert entries == {"entries": [], "current": None}, entries


def test_an_entry_descends_from_the_one_whose_code_it_began_from_and_typing_that_changed_nothing_is_none(kept):
    """A node's next entry branches from the entry in use: after a run's code
    is put back, the typing and the run that follow descend from that run, not
    from the newest entry. Typing that leaves the code as it began is no
    entry."""
    from utk_curio.backend.app.collaboration import dataflow_docs, history

    alice = _synced(kept, "alice")
    runs = f"/api/projects/{kept.project_id}/history/nodes/loader/runs"

    def run(code: str) -> None:
        answer = _http(kept).post(runs, headers=_auth(kept), data=json.dumps(
            {"code": code, "inputs": [], "outputs": ["DATAFRAME"]}))
        assert answer.status_code == 201, answer.get_json()

    run("x = 1\n")
    alice.edit(_type("# a\n"))
    run("# a\nx = 1\n")
    put = _http(kept).post(
        f"/api/projects/{kept.project_id}/history/nodes/loader/code", headers=_auth(kept),
        data=json.dumps({"from": "# a\nx = 1\n", "code": "x = 1\n", "label": "Code put back"}),
    )
    assert put.status_code == 200, put.get_json()
    alice.pump()
    alice.edit(_type("# b\n"))
    run("# b\nx = 1\n")
    entries = history.entries(kept.owner_key, kept.project_id, "loader")
    assert [(e["id"], e["parentId"], e.get("kind", "run")) for e in entries["entries"]] == [
        (1, None, "run"), (2, 1, "edit"), (3, 2, "run"), (4, 1, "edit"), (5, 4, "run"),
    ], entries["entries"]
    assert entries["current"] == 5

    # Typed and taken out again: the code is as it began, and nothing is added.
    count = len(_points(kept))
    alice.edit(_type("# c\n"))
    alice.edit(_erase("# c\n"))
    kept.clock.now += history.TYPING_PAUSE_S + 1
    dataflow_docs.flush_due(kept.clock.now)
    assert len(_points(kept)) == count, _points(kept)[count:]
    assert _code_of(kept.live()["dataflow"], "loader") == "# b\nx = 1\n"


def test_a_run_whose_code_the_doc_no_longer_holds_keeps_it(kept):
    from utk_curio.backend.app.collaboration import history

    _synced(kept, "alice")
    answer = _http(kept).post(
        f"/api/projects/{kept.project_id}/history/nodes/loader/runs", headers=_auth(kept),
        data=json.dumps({"code": "ran = True\n", "inputs": [], "outputs": []}),
    )
    assert answer.status_code == 201, answer.get_json()
    entries = history.entries(kept.owner_key, kept.project_id, "loader")["entries"]
    assert entries[-1]["code"] == "ran = True\n"


def test_file_save_is_a_version_named_saved(kept):
    _synced(kept, "alice")
    answer = _http(kept).post(f"/api/projects/{kept.project_id}/history/saved", headers=_auth(kept))
    assert answer.status_code == 201, answer.get_json()
    newest = _points(kept)[-1]
    assert (newest["kind"], newest["what"], newest["by"]["name"]) == ("saved", "Saved", "Alice")
    listed = _http(kept).get(f"/api/projects/{kept.project_id}/history", headers=_auth(kept)).get_json()
    assert listed["versions"][-1]["what"] == "Saved" and listed["head"] == newest["id"]


def test_file_saves_answer_has_the_dataflows_categories_as_it_is(kept):
    """No tab saves the dataflow, so File > Save's version is what tells the
    canvas title its categories, as a save's answer did."""
    from utk_curio.backend.app.projects import services
    from utk_curio.backend.app.collaboration import dataflow_docs

    _synced(kept, "alice")
    answer = _http(kept).post(f"/api/projects/{kept.project_id}/history/saved", headers=_auth(kept))

    assert answer.status_code == 201, answer.get_json()
    expected = services._categories(
        kept.users["alice"], kept.project_id, dataflow_docs.read(kept.owner_key, kept.project_id),
    )
    assert answer.get_json()["categories"] == expected


def test_file_save_writes_the_dataflows_file_as_its_doc_holds_it(kept):
    """A tab's change reaches the dataflow's file a second after the doc took
    it. No tab sends the dataflow, so File > Save's version writes the file
    first: what reads the file (the Scenario Catalog among them) has the change
    once the save answers."""
    from utk_curio.backend.app.projects import storage

    alice = _synced(kept, "alice")
    alice.edit(_type("# typed just now\n"))
    before = storage.read_spec(kept.owner_key, kept.project_id)
    assert _code_of(before["dataflow"], "loader") == "x = 1\n", "the file had the change before the save"

    answer = _http(kept).post(f"/api/projects/{kept.project_id}/history/saved", headers=_auth(kept))

    assert answer.status_code == 201, answer.get_json()
    after = storage.read_spec(kept.owner_key, kept.project_id)
    assert _code_of(after["dataflow"], "loader") == "# typed just now\nx = 1\n"


def test_an_agents_change_is_a_version_named_after_it_with_an_entry_on_the_node_it_changed(kept):
    from utk_curio.backend.app.collaboration import dataflow_docs

    _synced(kept, "alice")
    spec = dataflow_docs.live(kept.owner_key, kept.project_id)
    next(n for n in spec["dataflow"]["nodes"] if n["id"] == "loader")["content"] = "x = 42\n"
    dataflow_docs.write(kept.owner_key, kept.project_id, spec,
                        dataflow_docs.by_agent(BUILDER, kept.owner_key, "apply"))
    listed = _http(kept).get(f"/api/projects/{kept.project_id}/history", headers=_auth(kept)).get_json()
    newest = listed["versions"][-1]
    assert (newest["kind"], newest["what"]) == ("agent", "Node Builder, asked by Alice"), newest
    entries = _http(kept).get(f"/api/projects/{kept.project_id}/history/nodes/loader",
                              headers=_auth(kept)).get_json()["entries"]
    assert (entries[-1]["kind"], entries[-1]["label"], entries[-1]["code"], entries[-1]["before"]) == (
        "edit", "Node Builder", "x = 42\n", "x = 1\n")


# ---------------------------------------------------------------------------
# Putting back, checked
# ---------------------------------------------------------------------------

def test_an_undo_after_another_persons_edit_is_refused_and_changes_nothing(kept):
    """The checked code write behind a put-back and the Map Editor's Undo and
    Redo: the code lands only if the node still holds what the undo began
    from, in the same transaction."""
    alice, bob = _synced(kept, "alice"), _synced(kept, "bob")
    bob.edit(_type("# bob was here\n"))
    alice.pump()
    url = f"/api/projects/{kept.project_id}/history/nodes/loader/code"
    refused = _http(kept).post(url, headers=_auth(kept),
                               data=json.dumps({"from": "x = 1\n", "code": "x = 0\n", "label": "Undo"}))
    assert refused.status_code == 409, refused.get_json()
    assert refused.get_json()["error"] == "Bob changed this node after; nothing was undone."
    assert _code_of(alice.dataflow(), "loader") == "# bob was here\nx = 1\n"
    assert _code_of(kept.live()["dataflow"], "loader") == "# bob was here\nx = 1\n"

    landed = _http(kept).post(url, headers=_auth(kept), data=json.dumps(
        {"from": "# bob was here\nx = 1\n", "code": "x = 0\n", "label": "Undo"}))
    assert landed.status_code == 200, landed.get_json()
    assert _code_of(bob.dataflow(), "loader") == "x = 0\n"
    newest = _points(kept)[-1]
    assert (newest["kind"], newest["what"], newest["by"]["name"]) == ("code", "Undo", "Alice")


def test_putting_a_version_back_makes_every_tab_hold_it(kept):
    from utk_curio.backend.app.collaboration import history

    alice, bob = _synced(kept, "alice"), _synced(kept, "bob")
    first = history.versions(kept.owner_key, kept.project_id)["head"]
    alice.edit(_add_node("extra"))
    bob.pump()
    answer = _http(kept).post(f"/api/projects/{kept.project_id}/history/{first}/put-back", headers=_auth(kept, "bob"))
    assert answer.status_code == 200, answer.get_json()
    assert answer.get_json()["refused"] == []
    for tab in (alice, bob):
        assert "extra" not in _node_ids(tab.dataflow())
    newest = _points(kept)[-1]
    assert (newest["kind"], newest["restores"], newest["parent"], newest["by"]["name"]) == (
        "putBack", first, first, "Bob")
    assert history.versions(kept.owner_key, kept.project_id)["head"] == newest["id"]


def test_a_version_put_back_keeps_the_dataflows_name_settings_and_installs(kept):
    """A version put back brings back its nodes, connections and goal, and
    leaves the dataflow its name, hand-set categories, auto-run, packages and
    datasets as they are now: a rename made after the version stays, so the
    next save, which sends the name the tab shows, renames nothing."""
    from utk_curio.backend.app.collaboration import dataflow_docs, history

    alice, bob = _synced(kept, "alice"), _synced(kept, "bob")
    first = history.versions(kept.owner_key, kept.project_id)["head"]
    now = {
        "name": "Renamed",
        "provenance_id": "Renamed",
        "categories": {"city": ["Chicago"], "topic": ["Greenery"]},
        "autoRun": True,
        "packages": ["model.curio.ddrnet23-slim@1"],
        "datasets": [{"datasetId": "data.cityofchicago.neighborhoods",
                      "dirName": "data.cityofchicago.neighborhoods@1"}],
    }
    alice.edit(_set_fields(task="A later goal", **now))
    alice.edit(_add_node("extra"))
    bob.pump()
    answer = _http(kept).post(f"/api/projects/{kept.project_id}/history/{first}/put-back", headers=_auth(kept, "bob"))
    assert answer.status_code == 200, answer.get_json()
    for tab in (alice, bob):
        flow = tab.dataflow()
        assert "extra" not in _node_ids(flow)
        assert flow.get("task") == "", "the version's goal was not put back"
        assert {name: flow.get(name) for name in now} == now, "the put-back changed the dataflow's own fields"
    held = dataflow_docs.read(kept.owner_key, kept.project_id)["dataflow"]
    assert "extra" not in _node_ids(held)
    assert {name: held.get(name) for name in now} == now, "the server's dataflow lost its own fields"


# ---------------------------------------------------------------------------
# Who reads it, and clearing it
# ---------------------------------------------------------------------------

def test_a_watcher_and_a_guest_are_refused_the_history(kept):
    """Only the owner and the editors the owner invited see the history: a
    watcher is refused every route of it, and its tab is never told the
    history changed."""
    from ._support import make_user

    alice, bob, carol = _synced(kept, "alice"), _synced(kept, "bob"), _synced(kept, "carol")
    guest, session = make_user("visitor", is_guest=True)
    kept.tokens["visitor"] = session.token
    base = f"/api/projects/{kept.project_id}/history"
    for name in ("carol", "visitor"):
        for method, url in (("get", base), ("get", f"{base}/nodes/loader"), ("post", f"{base}/saved"),
                            ("post", f"{base}/nodes/loader/runs"), ("post", f"{base}/clear")):
            answer = getattr(_http(kept), method)(url, headers=_auth(kept, name), data=json.dumps({"before": "p1"}))
            assert answer.status_code == 403, (name, url, answer.get_json())
            assert "owner and the editors" in answer.get_json()["error"]
    owner = _http(kept).get(base, headers=_auth(kept)).get_json()
    editor = _http(kept).get(base, headers=_auth(kept, "bob")).get_json()
    assert (owner["canClear"], editor["canClear"]) == (True, False)

    for tab in (alice, bob, carol):
        tab.pump()
        tab.events.clear()
    alice.edit(_add_node("told"))
    for tab in (alice, bob, carol):
        tab.pump()
    told = {name: any(e["name"] == "history_changed" for e in tab.events)
            for name, tab in (("alice", alice), ("bob", bob), ("carol", carol))}
    assert told == {"alice": True, "bob": True, "carol": False}, told


def test_the_shared_view_of_an_imported_dataflow_carries_no_history(kept):
    from utk_curio.backend.app.projects import storage

    storage.write_spec(kept.owner_key, kept.project_id, {**copy.deepcopy(FLOW), **_earlier_history()})
    _synced(kept, "alice")
    shared = _http(kept).get(f"/api/projects/{kept.project_id}/shared").get_json()
    assert not any(key in shared["spec"] for key in storage.HISTORY_KEYS), list(shared["spec"])


def test_the_owner_clears_the_history_before_a_version(kept):
    """Clearing keeps the dataflow as it is and the versions from the one named
    on, each rebuilding to what it held; what came before, text typed and
    deleted included, is in no file of the dataflow's any more. An editor may
    not clear it."""
    from utk_curio.backend.app.collaboration import history

    alice, bob = _synced(kept, "alice"), _synced(kept, "bob")
    alice.edit(_type("SECRET-KEY-123\n"))
    alice.edit(_erase("SECRET-KEY-123\n"))
    alice.set_presence({"editing": "loader"})
    alice.set_presence({"editing": None})
    alice.edit(_add_node("after"))
    keep_from = _points(kept)[-1]["id"]
    bob.edit(_type("# bob\n", node="shaper"))
    kept.clock.now += history.TYPING_PAUSE_S + 1
    from utk_curio.backend.app.collaboration import dataflow_docs

    dataflow_docs.flush_due(kept.clock.now)
    _http(kept).post(f"/api/projects/{kept.project_id}/history/saved", headers=_auth(kept, "bob"))
    points = _points(kept)
    index = [p["id"] for p in points].index(keep_from)
    remaining_before = {p["id"]: _dataflow_at(kept, p["id"]) for p in points[index:] if p["kind"] != "run"}

    refused = _http(kept).post(f"/api/projects/{kept.project_id}/history/clear", headers=_auth(kept, "bob"),
                               data=json.dumps({"before": keep_from}))
    assert refused.status_code == 403, refused.get_json()
    cleared = _http(kept).post(f"/api/projects/{kept.project_id}/history/clear", headers=_auth(kept),
                               data=json.dumps({"before": keep_from}))
    assert cleared.status_code == 200, cleared.get_json()

    after = _points(kept)
    assert after[0]["id"] == keep_from and after[0]["parent"] is None
    assert [p["id"] for p in after] == [p["id"] for p in points[index:]]
    for point_id, flow in remaining_before.items():
        assert _dataflow_at(kept, point_id) == flow, point_id
    for path in kept.folder().rglob("*"):
        if path.is_file():
            assert b"SECRET-KEY-123" not in path.read_bytes(), f"{path.name} still holds the text"

    # The doc's tabs sync on, and the history goes on from the version kept.
    alice.edit(_add_node("later"))
    bob.pump()
    assert "later" in _node_ids(bob.dataflow())
    newest = _points(kept)[-1]
    assert newest["what"] == "Node added" and "later" in _node_ids(_dataflow_at(kept, newest["id"]))


def test_dropping_the_history_starts_it_again_from_the_dataflow(kept):
    """The seeder drops it before it puts an example back: no point stays,
    and the next change starts the history from the dataflow."""
    from utk_curio.backend.app.collaboration import history

    alice = _synced(kept, "alice")
    alice.edit(_add_node("gone-soon"))
    history.drop(kept.owner_key, kept.project_id)
    assert _points(kept) == []
    alice.edit(_add_node("next"))
    listed = history.versions(kept.owner_key, kept.project_id)["versions"]
    assert [v["kind"] for v in listed] == ["load"] * len(listed)
    assert {"gone-soon", "next"} <= {node["id"] for node in listed[-1]["preview"]["nodes"]}


def test_node_history_read_reads_the_points(kept):
    """The agents read what the drawer lists: a node's entries, newest first,
    and one entry's code."""
    from utk_curio.backend.app.agents.application import tools

    _synced(kept, "alice")
    for code in ("x = 1\n", "ran = 2\n"):
        _http(kept).post(f"/api/projects/{kept.project_id}/history/nodes/loader/runs", headers=_auth(kept),
                         data=json.dumps({"code": code, "inputs": [], "outputs": ["DATAFRAME"]}))
    status, text = tools.execute_read_tool(
        "node.history.read", user_key=kept.owner_key, project_id=kept.project_id,
        target={"kind": "node", "targetId": "loader"}, params={},
    )
    assert status == "ok", text
    rows = json.loads(text)["entries"]
    assert [row["kind"] for row in rows] == ["run", "run"]
    status, text = tools.execute_read_tool(
        "node.history.read", user_key=kept.owner_key, project_id=kept.project_id,
        target={"kind": "node", "targetId": "loader"}, params={"entryId": rows[0]["id"]},
    )
    assert status == "ok" and json.loads(text)["code"] == "ran = 2\n", text


# ---------------------------------------------------------------------------
# What a load and a save carry, and copies
# ---------------------------------------------------------------------------

def test_a_load_a_shared_view_and_a_saves_answer_carry_no_history(kept):
    """The history is read from its own routes, by the owner and the editors:
    no load serves it, so a watcher's link never carries it."""
    from utk_curio.backend.app.projects import storage

    storage.write_spec(kept.owner_key, kept.project_id, {**copy.deepcopy(FLOW), **_earlier_history()})
    _synced(kept, "alice")
    base = f"/api/projects/{kept.project_id}"
    loaded = _http(kept).get(base, headers=_auth(kept)).get_json()["spec"]
    shared = _http(kept).get(f"{base}/shared").get_json()["spec"]
    answered = _http(kept).put(base, headers=_auth(kept), data=json.dumps({"name": "Renamed"})).get_json()["spec"]
    for name, spec in (("load", loaded), ("shared view", shared), ("save's answer", answered)):
        assert not set(spec) & set(storage.HISTORY_KEYS), (name, sorted(spec))
    listed = _http(kept).get(f"{base}/history", headers=_auth(kept)).get_json()
    assert [v["id"] for v in listed["versions"] if v["kind"] == "imported"] == list(
        _earlier_history()["dataflowProvenance"]["versions"]
    )


def test_a_save_carrying_history_is_imported_before_the_first_open_and_not_read_after(kept):
    """A whole save of a dataflow that has no points yet puts the history it
    carries on record, and the save's own first open imports it; once the
    dataflow has its points, what a save carries is not read, nor written
    beside the spec."""
    from utk_curio.backend.app.collaboration import history
    from utk_curio.backend.app.projects import storage

    earlier = _earlier_history()
    base = f"/api/projects/{kept.project_id}"
    saved = _http(kept).put(base, headers=_auth(kept),
                            data=json.dumps({"spec": {**copy.deepcopy(FLOW), **copy.deepcopy(earlier)}}))
    assert saved.status_code == 200, saved.get_json()
    imported = [p["id"] for p in _points(kept) if p["kind"] == "imported"]
    assert imported == list(earlier["dataflowProvenance"]["versions"])

    count = len(_points(kept))
    late = {"nodeProvenance": {"loader": [{"id": 77, "parentId": None, "code": "late()\n", "inputs": [],
                                           "outputs": [], "startTime": "", "endTime": ""}]}}
    for body in ({"history": late}, {"spec": {**copy.deepcopy(FLOW), **late}}):
        answer = _http(kept).put(base, headers=_auth(kept), data=json.dumps(body))
        assert answer.status_code == 200, answer.get_json()
    assert storage.history_sections(kept.owner_key, kept.project_id) == {}, "a late history was written beside the spec"
    assert 77 not in [e["id"] for e in history.entries(kept.owner_key, kept.project_id, "loader")["entries"]]
    assert all(p["kind"] != "imported" for p in _points(kept)[count:])


def test_a_duplicate_and_an_editors_copy_keep_the_history_and_a_watchers_copy_starts_its_own(kept):
    from utk_curio.backend.app.collaboration import history

    alice = _synced(kept, "alice")
    alice.edit(_add_node("kept-in-copies"))
    source = [v["id"] for v in history.versions(kept.owner_key, kept.project_id)["versions"]]

    def versions_of(name: str, project: dict) -> list:
        key = kept.owner_key if name == "alice" else str(kept.users[name].id)
        return [v["id"] for v in history.versions(key, project["id"])["versions"]]

    duplicate = _http(kept).post(f"/api/projects/{kept.project_id}/duplicate", headers=_auth(kept))
    assert duplicate.status_code == 201, duplicate.get_json()
    assert versions_of("alice", duplicate.get_json()) == source

    for name in ("bob", "carol"):
        made = _http(kept).post("/api/projects", headers=_auth(kept, name), data=json.dumps(
            {"name": f"{name}'s copy", "spec": copy.deepcopy(FLOW), "copy_of": kept.project_id}))
        assert made.status_code == 201, made.get_json()
        copied = made.get_json()
        if name == "bob":
            assert versions_of(name, copied) == source, "an editor's copy did not keep the history"
        else:
            own = history.versions(str(kept.users[name].id), copied["id"])["versions"]
            assert all(v["kind"] == "load" for v in own), (
                f"a watcher's copy took the history it may not read: {[(v['id'], v['kind']) for v in own]}"
            )
