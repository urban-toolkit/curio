"""An agent at work in a dataflow's room (``collaboration/agent_peers.py``).

The server runs the agent as a peer of the dataflow's doc: a state of its own
in the doc's awareness, the room's lock of each node it writes, its actions one
at a time, and its join and leave in the room's Activity. The tabs are the doc
tests' (``_ydoc_client.py``): alice owns the dataflow and asked the agent, bob
edits it and carol watches. The module waits only as a test sets: its waits
are recorded, and its renewals are made when a test calls for them.
"""

from __future__ import annotations

import threading
import time

import pytest

from ._support import NAMESPACE, connect, invite, join, make_project, make_user

#: alice's dataflow: a loader feeding a chart.
SPEC = {
    "dataflow": {
        "nodes": [
            {"id": "loader", "type": "curio.builtin/code", "x": 10, "y": 20, "content": "x = 1\n",
             "out": "DATAFRAME", "in": "DEFAULT", "goal": "", "metadata": {"keywords": []}},
            {"id": "chart", "type": "curio.builtin/vega-lite", "x": 300, "y": 20, "content": "{}",
             "out": "DEFAULT", "in": "DATAFRAME", "goal": "", "metadata": {"keywords": []}},
        ],
        "edges": [{"id": "e1", "source": "loader", "target": "chart", "sourceHandle": "out", "targetHandle": "in"}],
        "name": "Shared", "task": "", "timestamp": 1, "provenance_id": "Shared",
    },
}

#: The agents the tests put in the room.
DFB = "agent.curio.dataflow-builder@1"
NB = "agent.curio.node-builder@1"
#: A node dragged in from the Nodes menu, dropped at a point of the dataflow.
DRAG = {
    "kind": "add",
    "from": {"palette": "builtin", "item": "curio.builtin/code"},
    "onto": None,
    "node": {"type": "curio.builtin/code", "label": "Filter"},
    "to": {"x": 420.5, "y": 80},
}
#: How long a y-protocols tab keeps a state that is not renewed (its
#: ``outdatedTimeout``).
TAB_DROPS_AFTER_S = 30.0
#: The longest any wait here takes before the test fails: a hang is a finding.
WAIT_S = 20.0


class _Room:
    """alice's dataflow, a way into it for anyone, and its agents."""

    def __init__(self, application, socketio, users, tokens, project_id, slept):
        self.application = application
        self.socketio = socketio
        self.users = users
        self.tokens = tokens
        self.project_id = project_id
        self.owner_key = str(users["alice"].id)
        #: Who asks the agents, read once here: a run on another thread reads
        #: no account row.
        self.asked_by = self.peers.asker(users["alice"])
        #: Every wait the module made that no test set itself.
        self.slept = slept

    @property
    def docs(self):
        from utk_curio.backend.app.collaboration import dataflow_docs

        return dataflow_docs

    @property
    def peers(self):
        from utk_curio.backend.app.collaboration import agent_peers

        return agent_peers

    def tab(self, name: str):
        """A tab of *name*'s, joined to the room and synced with the doc."""
        from ._ydoc_client import synced_tab

        return synced_tab(self.application, self.tokens[name], self.project_id)

    def joined(self, name: str):
        """A socket of *name*'s in the room, synced with no doc, and its join's answer."""
        socket = connect(self.socketio, self.application, self.tokens[name])
        ack = join(socket, self.project_id)
        assert ack["ok"] is True, ack
        socket.get_received(namespace=NAMESPACE)
        return socket, ack

    def agent(self, *, attachment_id: str = "att-1", coord: str = DFB, name: str = "Dataflow Builder",
              category: str = "canvas", skills=()):
        """The agent of *attachment_id* at work, asked by alice."""
        return self.peers.at_work(self.owner_key, self.project_id, attachment_id=attachment_id, coord=coord,
                                  name=name, category=category, asked_by=self.asked_by, skills=skills)

    def writes(self, peer, change):
        """A write that makes *change* to the dataflow as *peer*'s agent does."""

        def write():
            spec = self.docs.live(self.owner_key, self.project_id)
            change(spec["dataflow"])
            actor = self.docs.by_agent(peer.user["agent"]["coord"], peer.asker_account, "test")
            return self.docs.write(self.owner_key, self.project_id, spec, actor)

        return write

    def read(self) -> dict:
        return self.docs.read(self.owner_key, self.project_id)["dataflow"]

    def locks(self) -> dict:
        from utk_curio.backend.app.collaboration import room_state

        return room_state.snapshot(room_state.room_for(self.project_id))["locks"]

    def server_doc(self):
        entry = self.docs._open_entry(self.project_id)
        assert entry is not None, "the server holds no doc of the dataflow"
        return entry


@pytest.fixture()
def room(doc_app, monkeypatch):
    application, socketio = doc_app
    assert socketio is not None, "every backend serves Socket.IO"
    from utk_curio.backend.app.collaboration import agent_peers
    from utk_curio.backend.app.projects import storage

    users, tokens = {}, {}
    for name in ("alice", "bob", "carol"):
        users[name], session = make_user(name)
        tokens[name] = session.token
    project_id = make_project(users["alice"])
    invite(project_id, users["alice"], users["bob"])
    storage.write_spec(str(users["alice"].id), project_id, SPEC)
    slept: list = []
    monkeypatch.setattr(agent_peers, "BACKGROUND", False)
    monkeypatch.setattr(agent_peers, "_sleep", slept.append)
    agent_peers.reset_for_tests()
    try:
        yield _Room(application, socketio, users, tokens, project_id, slept)
    finally:
        agent_peers.reset_for_tests()


def _add_node(node_id: str):
    def change(dataflow):
        dataflow["nodes"].append({"id": node_id, "type": "curio.builtin/code", "x": 420, "y": 80, "content": "",
                                  "out": "DATAFRAME", "in": "DEFAULT", "goal": "", "metadata": {"keywords": []}})

    return change


def _set_code(node_id: str, text: str):
    def change(dataflow):
        next(node for node in dataflow["nodes"] if node["id"] == node_id)["content"] = text

    return change


def _add_edge(edge_id: str, source: str, target: str):
    def change(dataflow):
        dataflow["edges"].append({"id": edge_id, "source": source, "target": target,
                                  "sourceHandle": "out", "targetHandle": "in"})

    return change


def _remove_chart(doc):
    from pycrdt import Map

    del doc.get("nodes", type=Map)["chart"]
    del doc.get("edges", type=Map)["e1"]


def _ids(dataflow: dict) -> set:
    return {node["id"] for node in dataflow["nodes"]}


def _code(dataflow: dict, node_id: str) -> str:
    return next(node for node in dataflow["nodes"] if node["id"] == node_id)["content"]


def _lock_as(socket, room, node_id: str) -> dict:
    """*socket*'s person takes *node_id*'s lock, as their focus in it does."""
    return socket.emit("node_lock", {"projectId": room.project_id, "nodeId": node_id},
                       namespace=NAMESPACE, callback=True)


def _room_events(socket, *names) -> list:
    return [(event["name"], event["args"][0]) for event in socket.get_received(namespace=NAMESPACE)
            if event["name"] in names]


def _wait_for(ready, message: str) -> None:
    deadline = time.monotonic() + WAIT_S
    while not ready():
        assert time.monotonic() < deadline, message
        time.sleep(0.01)


def _a_writer_lands_at_once(room) -> None:
    """Another writer of the dataflow writes it while an agent waits: the
    agent holds neither the spec lock nor the doc's lock for its pace."""
    done: list = []

    def write():
        try:
            with room.docs.writing(room.owner_key, room.project_id, room.docs.person(room.owner_key, "test")) as spec:
                spec["dataflow"]["task"] = f"written while an agent waits, at {time.monotonic()}"
            done.append(True)
        except BaseException as exc:  # noqa: BLE001 - what failed is the finding
            done.append(exc)

    writer = threading.Thread(target=write, daemon=True)
    writer.start()
    writer.join(timeout=WAIT_S)
    assert done == [True], f"another writer of the dataflow waited on an agent's pace: {done}"


def test_a_tab_sees_the_agent_join_with_its_name_asker_and_skills_and_leave(room):
    bob = room.tab("bob")

    with room.agent(skills=["catalogs"]) as peer:
        state = bob.others()[peer.client_id]
        assert state == {
            "user": {
                "participant_id": peer.participant_id,
                "user_id": None,
                "name": "Dataflow Builder",
                "agent": {"attachmentId": "att-1", "coord": DFB, "category": "canvas",
                          "askedBy": {"account": room.owner_key, "name": "Alice"}},
            },
            "skills": ["catalogs"],
            "editing": None,
            "pointer": None,
            "carrying": None,
        }
        assert peer.participant_id.startswith("agent-") and len(peer.participant_id) == len("agent-") + 32
        assert peer.client_id >= 1 << 32, "the agent's client id is one a tab could hold"

        peer.use_skills(["map-edits", "catalogs"])
        assert bob.others()[peer.client_id]["skills"] == ["catalogs", "map-edits"]

    assert peer.client_id not in bob.others(), "a tab still sees the agent once it left"
    assert peer.client_id not in room.server_doc().awareness.states


def test_a_tab_that_starts_later_sees_the_agent_and_so_does_its_doc_opened_again(room):
    with room.agent() as peer:
        assert not room.docs.is_open(room.project_id), "an agent at work opened the dataflow's doc"
        later = room.tab("bob")
        assert later.others()[peer.client_id]["user"]["participant_id"] == peer.participant_id
        clock = room.server_doc().awareness.meta[peer.client_id]["clock"]

        later.socket.disconnect(namespace=NAMESPACE)
        assert room.docs.close(room.project_id), "the doc stayed in memory with no tab"
        again = room.tab("carol")

        assert again.others()[peer.client_id]["user"]["participant_id"] == peer.participant_id
        assert room.server_doc().awareness.meta[peer.client_id]["clock"] > clock, (
            "the state put back has a clock a tab that kept the last one would not take"
        )


def test_the_agent_is_renewed_before_its_tabs_would_drop_it(room, monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(room.peers, "_clock", lambda: now[0])
    bob = room.tab("bob")

    def clock_at_bob(peer) -> int:
        bob.pump()
        return bob.awareness.meta[peer.client_id]["clock"]

    with room.agent() as peer:
        sent = clock_at_bob(peer)
        now[0] += room.peers.RENEW_EVERY_S - 1
        room.peers.renew_due()
        assert clock_at_bob(peer) == sent, "the state was sent again before it was due"
        now[0] += 1
        room.peers.renew_due()
        assert clock_at_bob(peer) == sent + 1, "the state was not renewed when it was due"
        assert bob.others()[peer.client_id]["user"]["name"] == "Dataflow Builder"

        # A change sends the state, and the next renewal is due that long after it.
        now[0] += 5
        peer.use_skills(["catalogs"])
        changed = clock_at_bob(peer)
        now[0] += room.peers.RENEW_EVERY_S - 1
        room.peers.renew_due()
        assert clock_at_bob(peer) == changed
        now[0] += 1
        room.peers.renew_due()
        assert clock_at_bob(peer) == changed + 1

    assert room.peers.RENEW_EVERY_S <= TAB_DROPS_AFTER_S / 2, (
        "a renewal comes later than half the time after which a tab drops the state"
    )


def _renewers() -> list:
    return [thread for thread in threading.enumerate() if thread.name == "agent-peers" and thread.is_alive()]


def test_one_thread_renews_every_agent_and_ends_after_the_last_leaves(room, monkeypatch):
    monkeypatch.setattr(room.peers, "BACKGROUND", True)
    monkeypatch.setattr(room.peers, "RENEW_EVERY_S", 0.05)
    bob = room.tab("bob")

    with room.agent() as first, room.agent(attachment_id="att-2", coord=NB, name="Node Builder",
                                           category="node") as second:
        bob.pump()
        starts = {peer.client_id: bob.awareness.meta[peer.client_id]["clock"] for peer in (first, second)}
        assert len(_renewers()) == 1, "not one thread renews the agents at work"

        def renewed() -> bool:
            bob.pump()
            return all(bob.awareness.meta[client]["clock"] >= start + 2 for client, start in starts.items())

        _wait_for(renewed, "the thread did not renew the agents' states")
        # Nothing renews while they leave, to a tab gone first.
        monkeypatch.setattr(room.peers, "RENEW_EVERY_S", 3600.0)
        bob.socket.disconnect(namespace=NAMESPACE)

    _wait_for(lambda: not _renewers(), "the renewing thread outlived the last agent at work")


def test_its_lock_reaches_the_room_naming_it_and_goes_a_second_after_its_write(room, monkeypatch):
    alice, _ = room.joined("alice")
    bob = room.tab("bob")
    kept: list = []

    def _sleep(seconds):
        # The second after the write: the code is in, the node is still the
        # agent's, and someone joining sees its lock.
        _carol, ack = room.joined("carol")
        kept.append((seconds, ack["snapshot"]["locks"].get("loader"), bob.others()[peer.client_id]["editing"],
                     _code(bob.dataflow(), "loader")))
        _a_writer_lands_at_once(room)

    monkeypatch.setattr(room.peers, "_sleep", _sleep)
    with room.agent() as peer:
        acted = room.peers.act(peer, room.peers.Action(
            what="write the loader's code", write=room.writes(peer, _set_code("loader", "x = 2\n")),
            holds=("loader",), writes="code", targets=("loader",), did=(("changed", "node", "loader"),),
        ))
        editing_after = bob.others()[peer.client_id]["editing"]

    assert acted.landed and acted.result.wrote, acted
    [(seconds, lock, editing, code)] = kept
    assert seconds == room.peers.KEEP_AFTER_WRITE_S
    assert lock == {"user_id": None, "username": None, "name": "Dataflow Builder",
                    "participant_id": peer.participant_id, "since": lock["since"],
                    "agent": peer.user["agent"], "writes": "code"}
    assert editing == "loader", "the agent's state did not name the node it holds"
    assert code == "x = 2\n", "the lock was kept before its write landed"
    assert editing_after is None and room.locks() == {}
    events = _room_events(alice, "node_locked", "node_unlocked")
    assert events == [("node_locked", {"nodeId": "loader", "lock": lock}), ("node_unlocked", {"nodeId": "loader"})]


def test_it_waits_while_a_person_holds_its_node_then_takes_the_lock(room, monkeypatch):
    bob, _ = room.joined("bob")
    assert _lock_as(bob, room, "loader")["ok"] is True
    bob.get_received(namespace=NAMESPACE)  # bob's own lock
    polls: list = []

    def _sleep(seconds):
        polls.append(seconds)
        _a_writer_lands_at_once(room)
        if len(polls) == 3:
            unlocked = bob.emit("node_unlock", {"projectId": room.project_id, "nodeId": "loader"},
                                namespace=NAMESPACE, callback=True)
            assert unlocked == {"ok": True}

    monkeypatch.setattr(room.peers, "_sleep", _sleep)
    with room.agent() as peer:
        acted = room.peers.act(peer, room.peers.Action(
            what="write the loader's code", write=room.writes(peer, _set_code("loader", "x = 3\n")),
            holds=("loader",), writes="code", targets=("loader",),
        ))

    assert acted.landed, acted
    assert polls == [room.peers.LOCK_POLL_S] * 3, "with no tab bound, the agent waits for nothing but the person"
    assert _code(room.read(), "loader") == "x = 3\n"
    locked = [lock for name, lock in _room_events(bob, "node_locked")]
    assert [event["lock"]["participant_id"] for event in locked] == [peer.participant_id]


def test_a_person_still_in_its_node_when_the_wait_ends_leaves_the_action_undone(room, monkeypatch):
    now = [0.0]
    monkeypatch.setattr(room.peers, "_clock", lambda: now[0])
    monkeypatch.setattr(room.peers, "_sleep", lambda seconds: now.__setitem__(0, now[0] + seconds))
    bob, _ = room.joined("bob")
    assert _lock_as(bob, room, "loader")["ok"] is True
    bob.get_received(namespace=NAMESPACE)  # bob's own lock
    wrote: list = []

    with room.agent() as peer:
        acted = room.peers.act(peer, room.peers.Action(
            what="write the loader's code", write=lambda: wrote.append(True), holds=("loader",), writes="code",
        ))

    assert acted == room.peers.Acted(False, left="write the loader's code", held_by="Bob")
    assert wrote == []
    assert room.peers.LOCK_WAIT_S <= now[0] <= room.peers.LOCK_WAIT_S + room.peers.LOCK_POLL_S, now[0]
    assert room.locks()["loader"]["user_id"] == room.users["bob"].id
    assert _room_events(bob, "node_locked") == [], "the agent's lock reached the room"


def test_the_askers_own_focus_never_holds_their_agent_back(room):
    alice, _ = room.joined("alice")
    assert _lock_as(alice, room, "loader")["ok"] is True

    with room.agent() as peer:
        acted = room.peers.act(peer, room.peers.Action(
            what="write the loader's code", write=room.writes(peer, _set_code("loader", "x = 4\n")),
            holds=("loader",), writes="code",
        ))

    assert acted.landed, acted
    assert room.slept == [], "the agent waited for the person who asked it"
    assert _code(room.read(), "loader") == "x = 4\n"
    assert room.locks()["loader"]["user_id"] == room.users["alice"].id, "the agent took its asker's lock"


def test_another_agents_lock_holds_an_agent_back_and_its_own_never_does(room):
    with room.agent() as builder, room.agent(attachment_id="att-2", coord=NB, name="Node Builder",
                                             category="node") as node_builder:
        with room.peers.holding(node_builder, ["loader"], "code") as hold:
            assert hold.held_by is None and hold.nodes == ("loader",)
            assert room.locks()["loader"]["agent"]["coord"] == NB
            asker = builder.asker_account
            assert room.peers.wait_for_people(room.project_id, ["loader"], asker, peer=builder, within=0) == (
                "Node Builder"
            )
            assert room.peers.wait_for_people(room.project_id, ["loader"], asker, peer=node_builder, within=0) is None
            hold.keep = False
    assert room.locks() == {}


def test_a_drag_shows_its_pointer_and_what_it_carries_for_its_length_before_its_write(room, monkeypatch):
    bob = room.tab("bob")
    seen: list = []

    def _sleep(seconds):
        state = bob.others()[peer.client_id]
        seen.append((seconds, state["pointer"], state["carrying"], "filter" in _ids(bob.dataflow())))
        _a_writer_lands_at_once(room)

    monkeypatch.setattr(room.peers, "_sleep", _sleep)
    with room.agent() as peer:
        before = int(time.time() * 1000)
        acted = room.peers.act(peer, room.peers.Action(
            what="add a Filter node", write=room.writes(peer, _add_node("filter")), drag=DRAG,
            did=(("added", "node", "filter"),),
        ))
        after = bob.others()[peer.client_id]
        end = int(time.time() * 1000)

    assert acted.landed, acted
    [(seconds, pointer, carrying, landed_first)] = seen
    assert seconds == room.peers.DRAG_MS / 1000 == 0.5
    assert pointer["x"] == 420.5 and pointer["y"] == 80 and before <= pointer["t"] <= end, pointer
    assert carrying == {"id": carrying["id"], "kind": "add", "from": {"palette": "builtin", "item": "curio.builtin/code"},
                        "onto": None, "node": {"type": "curio.builtin/code", "label": "Filter"}, "ms": 500}
    assert carrying["id"], "a drag has no id a tab plays it once by"
    assert landed_first is False, "the node landed before its drag ended"
    assert after["pointer"] is None and after["carrying"] is None, "the drag outlived its drop"
    assert "filter" in _ids(bob.dataflow())


def test_with_no_tab_bound_an_agent_waits_for_nothing(room):
    with room.agent() as peer:
        added = room.peers.act(peer, room.peers.Action(
            what="add a Filter node", write=room.writes(peer, _add_node("filter")), drag=DRAG,
        ))
        written = room.peers.act(peer, room.peers.Action(
            what="write its code", write=room.writes(peer, _set_code("filter", "y = 1\n")),
            holds=("filter",), writes="code", targets=("filter",),
        ))

    assert added.landed and written.landed, (added, written)
    assert room.slept == [], "an agent kept its pace with no tab to see it"
    assert _code(room.read(), "filter") == "y = 1\n"


def test_one_agents_actions_never_overlap_and_two_agents_do(room, monkeypatch):
    # Paced as for a bound tab, with no tab to send the drags to.
    monkeypatch.setattr(room.docs, "has_tabs", lambda project_id: True)
    log: list = []
    dragging = {name: threading.Event() for name in ("a1", "a2", "b1")}
    drop = threading.Event()

    def _sleep(seconds):
        name = threading.current_thread().name
        log.append(("drag", name))
        dragging[name].set()
        assert drop.wait(WAIT_S), "the test never let the drags end"

    monkeypatch.setattr(room.peers, "_sleep", _sleep)
    errors: list = []

    def play(peer, name):
        add = room.writes(peer, _add_node(f"n_{name}"))

        def write():
            log.append(("write", name))
            return add()

        try:
            assert room.peers.act(peer, room.peers.Action(what=f"add {name}", write=write, drag=DRAG)).landed
        except BaseException as exc:  # noqa: BLE001 - what failed is the finding
            errors.append(exc)

    with room.agent() as first, room.agent(attachment_id="att-2", coord=NB, name="Node Builder",
                                           category="node") as second:
        threads = {name: threading.Thread(target=play, args=(peer, name), name=name, daemon=True)
                   for name, peer in (("a1", first), ("a2", first), ("b1", second))}
        threads["a1"].start()
        assert dragging["a1"].wait(WAIT_S), "the first action's drag never began"
        threads["a2"].start()
        threads["b1"].start()
        assert dragging["b1"].wait(WAIT_S), "a second agent's drag waited for the first agent's"
        assert not dragging["a2"].wait(0.3), "an agent's second action began while its first played"
        drop.set()
        for thread in threads.values():
            thread.join(WAIT_S)
            assert not thread.is_alive(), f"{thread.name} never ended"

    assert errors == []
    assert log.index(("drag", "b1")) < log.index(("write", "a1"))
    assert log.index(("write", "a1")) < log.index(("drag", "a2")), "an agent's second drag began before its first wrote"
    assert {"n_a1", "n_a2", "n_b1"} <= _ids(room.read())


def test_a_changed_target_writes_nothing_and_says_what_was_left_undone(room, monkeypatch):
    alice = room.tab("alice")
    bob = room.tab("bob")
    wrote: list = []

    def _sleep(seconds):
        # During the drag, alice removes the node it drops onto.
        alice.edit(_remove_chart)

    monkeypatch.setattr(room.peers, "_sleep", _sleep)
    onto = {"kind": "onto", "from": {"palette": "models", "item": "model.curio.example@1"}, "onto": "chart",
            "node": {"type": "curio.builtin/vega-lite", "label": "Chart"}, "to": {"x": 300, "y": 20}}
    with room.agent() as peer:
        acted = room.peers.act(peer, room.peers.Action(
            what="drop the model onto the chart", write=lambda: wrote.append(True), drag=onto,
            targets=("loader", "chart"), did=(("changed", "node", "chart"),),
        ))
        state = bob.others()[peer.client_id]

    assert acted == room.peers.Acted(False, left="drop the model onto the chart", gone=("chart",))
    assert wrote == []
    assert state["pointer"] is None and state["carrying"] is None, "the drag outlived an action left undone"
    assert "chart" not in _ids(room.read()), "what the person did was undone"


def test_activity_has_its_join_and_what_it_did_live_and_in_a_joins_snapshot(room):
    carol, _ = room.joined("carol")

    with room.agent() as peer:
        for action in (
            room.peers.Action(what="add a Filter node", write=room.writes(peer, _add_node("filter")),
                              did=(("added", "node", "filter"),)),
            room.peers.Action(what="connect it", write=room.writes(peer, _add_edge("e2", "loader", "filter")),
                              did=(("added", "connection", "e2"),)),
            room.peers.Action(what="write its code", write=room.writes(peer, _set_code("filter", "y = 1\n")),
                              holds=("filter",), writes="code", did=(("changed", "node", "filter"),)),
            room.peers.Action(what="write it again", write=room.writes(peer, _set_code("filter", "y = 2\n")),
                              holds=("filter",), writes="code", did=(("changed", "node", "filter"),)),
        ):
            assert room.peers.act(peer, action).landed, action.what

    joined = peer.user
    left = {**peer.user, "did": {"added": {"node": 1, "connection": 1}, "changed": {"node": 1}}}
    assert _room_events(carol, "agent_joined", "agent_left") == [("agent_joined", joined), ("agent_left", left)]
    _bob, ack = room.joined("bob")
    kept = [(entry["kind"], entry["payload"]) for entry in ack["snapshot"]["activity"]
            if entry["kind"].startswith("agent_")]
    assert kept == [("agent_joined", joined), ("agent_left", left)]


def test_nested_runs_share_one_peer_which_leaves_with_the_last(room):
    carol, _ = room.joined("carol")
    bob = room.tab("bob")
    shared: list = []

    def run_beside():
        with room.agent(skills=["dashboards"]) as beside:
            shared.append(beside)

    with room.agent(skills=["catalogs"]) as outer:
        with room.agent(skills=["map-edits"]) as inner:
            assert inner is outer
            assert bob.others()[outer.client_id]["skills"] == ["catalogs", "map-edits"]
        thread = threading.Thread(target=run_beside, daemon=True)
        thread.start()
        thread.join(WAIT_S)
        assert shared == [outer], "a run on another thread got a peer of its own"
        assert outer.client_id in bob.others(), "the agent left with a nested run"
        assert bob.others()[outer.client_id]["skills"] == ["catalogs", "map-edits", "dashboards"]
        assert room.peers.peer_of(room.project_id, "att-1") is outer

    assert room.peers.peer_of(room.project_id, "att-1") is None
    assert [name for name, _ in _room_events(carol, "agent_joined", "agent_left")] == ["agent_joined", "agent_left"]


def test_an_action_never_starts_under_its_dataflows_spec_lock(room):
    from utk_curio.backend.app.projects import storage

    with room.agent() as peer:
        with storage.spec_write_lock(room.owner_key, room.project_id):
            with pytest.raises(RuntimeError, match="spec lock"):
                room.peers.act(peer, room.peers.Action(what="write the loader's code", write=lambda: None))
            with pytest.raises(RuntimeError, match="spec lock"):
                with room.peers.holding(peer, ["loader"], "code"):
                    pass
        assert room.locks() == {}


def test_its_lock_goes_with_a_run_that_fails(room):
    carol, _ = room.joined("carol")

    with pytest.raises(ValueError, match="the write failed"):
        with room.agent() as peer:
            with room.peers.holding(peer, ["loader"], "code"):
                assert room.locks()["loader"]["participant_id"] == peer.participant_id
                raise ValueError("the write failed")

    assert room.locks() == {}
    assert room.peers.peer_of(room.project_id, "att-1") is None
    names = [name for name, _ in _room_events(carol, "agent_joined", "node_locked", "node_unlocked", "agent_left")]
    assert names == ["agent_joined", "node_locked", "node_unlocked", "agent_left"]


def test_an_agent_leaves_once_an_action_another_thread_plays_for_it_ends(room):
    carol, _ = room.joined("carol")
    holding, done = threading.Event(), threading.Event()

    def hold(peer):
        with room.peers.holding(peer, ["loader"], "code") as hold:
            holding.set()
            assert done.wait(WAIT_S)
            hold.keep = False

    with room.agent() as peer:
        holder = threading.Thread(target=hold, args=(peer,), daemon=True)
        holder.start()
        assert holding.wait(WAIT_S), "the other thread's action never began"
        threading.Timer(0.2, done.set).start()

    assert done.is_set(), "the agent left while an action of its own still played"
    holder.join(WAIT_S)
    assert room.locks() == {}
    names = [name for name, _ in _room_events(carol, "node_locked", "node_unlocked", "agent_left")]
    assert names == ["node_locked", "node_unlocked", "agent_left"]


def test_a_run_that_ends_under_the_spec_lock_leaves_without_waiting_for_its_action(room):
    """An action on another thread waits for the spec lock to write, and the
    run ends under it: waiting for that action, the run would never let the
    lock go. The run and its action each have a thread of their own, so a
    deadlock fails the test rather than hanging it."""
    from utk_curio.backend.app.projects import storage

    writing, left = threading.Event(), threading.Event()
    wrote: list = []

    def write():
        writing.set()
        with storage.spec_write_lock(room.owner_key, room.project_id):
            wrote.append(True)

    def run():
        with storage.spec_write_lock(room.owner_key, room.project_id):
            with room.agent() as peer:
                actor = threading.Thread(daemon=True, target=lambda: room.peers.act(
                    peer, room.peers.Action(what="write while the run ends", write=write)))
                actor.start()
                assert writing.wait(WAIT_S), "the action never began its write"
            left.set()
        actor.join(WAIT_S)

    runner = threading.Thread(target=run, daemon=True)
    runner.start()
    runner.join(WAIT_S)

    assert left.is_set() and not runner.is_alive(), "the run waited, under the spec lock, for an action that waits for it"
    assert wrote == [True], "the action's write never landed after the run let the lock go"
    assert room.peers.peer_of(room.project_id, "att-1") is None
