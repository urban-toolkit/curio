"""The parts of a user's tab that need no server (``sockets.py``).

* The ledger: an update is synced when the last other tab of its room holds
  its sender's clock, and only the tabs synced when it was sent wait for it.
* The room: a phase waits for every member still in it.
* The socket: python-socketio's client puts a binary event together on the
  thread that read it, in order; every doc message is a binary event.
* A tab's answers: an update's ack, or, when the ack says the server queued
  it, the kept message that answers it once its batch is applied.
* Where a tab connects, and where it types and drags: the canvas's socket
  target, and the layout's places for a node's code and its place.
* A shared canvas (``--shared-canvas``): a member's own node and connection
  as the canvas writes them, the digest that compares nodes and connections,
  the room's locks as a tab keeps them, a lock asked for around typing, the
  locks read at the end, the node each room's members add theirs below, the
  example of each room, and how the owner's run and save are judged.

The tab against the server is ``test_collaboration/test_stress_tabs.py``.
Names are imported in each test, so a checkout without them fails test by test.
"""

import os
import threading
import unittest
import uuid


class LedgerTest(unittest.TestCase):
    def _ledger(self, *tabs):
        from utk_curio.backend.tests.stress.sockets import SyncLedger

        ledger = SyncLedger()
        for tab in tabs:
            ledger.synced(tab)
        return ledger

    def test_an_update_is_synced_when_the_last_other_tab_holds_its_clock(self):
        ledger = self._ledger("a", "b", "c")
        ledger.sent("a", 11, 1, 10.0)
        ledger.applied("b", {11: 1}, 10.2)
        self.assertEqual((ledger.open, ledger.seconds), (1, []), "c does not hold it yet")
        ledger.applied("c", {11: 0}, 10.3)
        self.assertEqual(ledger.open, 1, "a clock below the update's is not the update")
        ledger.applied("c", {11: 1, 99: 4}, 10.5)
        self.assertEqual(ledger.open, 0)
        self.assertEqual([round(s, 3) for s in ledger.seconds], [0.5])
        self.assertEqual((ledger.updates, ledger.deliveries), (1, 2))

    def test_one_reading_holds_every_update_up_to_its_clock(self):
        ledger = self._ledger("a", "b")
        for clock, at in ((1, 1.0), (2, 2.0), (3, 3.0)):
            ledger.sent("a", 11, clock, at)
        ledger.applied("b", {11: 2}, 4.0)
        self.assertEqual(ledger.open, 1)
        ledger.applied("b", {11: 3}, 5.0)
        self.assertEqual(sorted(ledger.seconds), [2.0, 2.0, 3.0])

    def test_a_tab_that_synced_after_an_update_is_not_waited_for(self):
        ledger = self._ledger("a", "b")
        ledger.sent("a", 11, 1, 1.0)
        ledger.synced("late")
        ledger.applied("b", {11: 1}, 1.5)
        self.assertEqual(ledger.open, 0)
        ledger.applied("late", {11: 1}, 9.0)
        self.assertEqual(ledger.seconds, [0.5], "a late tab's sync step 2 is not a sync time")

    def test_a_tab_alone_waits_for_no_one(self):
        ledger = self._ledger("a")
        ledger.sent("a", 11, 1, 1.0)
        self.assertEqual((ledger.open, ledger.seconds, ledger.updates), (0, [], 1))
        self.assertTrue(ledger.wait_settled(0))

    def test_a_tab_that_left_no_longer_holds_the_others_updates_open(self):
        ledger = self._ledger("a", "b", "c")
        ledger.sent("a", 11, 1, 1.0)
        ledger.applied("b", {11: 1}, 1.25)
        ledger.left("c")
        self.assertEqual(ledger.open, 0)
        self.assertEqual(ledger.seconds, [0.25], "the time to the tabs that stayed")
        ledger.sent("b", 22, 1, 2.0)
        ledger.left("a")
        self.assertEqual((ledger.open, ledger.seconds), (0, [0.25]),
                         "an update nobody received has no sync time")

    def test_settling_waits_for_every_update_and_says_who_lacks_what(self):
        ledger = self._ledger("a", "b")
        ledger.sent("a", 11, 1, 1.0)
        self.assertFalse(ledger.wait_settled(0.05))
        self.assertEqual(ledger.still_waiting("a"), (1, ["b"]))
        self.assertEqual(ledger.still_waiting("b"), (0, []))
        threading.Timer(0.05, ledger.applied, args=("b", {11: 1}, 1.1)).start()
        self.assertTrue(ledger.wait_settled(5))


class RoomTest(unittest.TestCase):
    def test_a_phase_waits_for_every_member_still_in_the_room(self):
        from utk_curio.backend.tests.stress.sockets import Room

        room = Room(0, ["owner", "ed1", "ed2"])
        room.arrive("synced", "owner")
        room.arrive("synced", "ed1")
        self.assertFalse(room.wait_all("synced", 0.05))
        room.leave("ed2")
        self.assertTrue(room.wait_all("synced", 0.05))
        self.assertFalse(room.present("ed2"))

    def test_the_owner_invites_only_the_editors_that_signed_up_and_are_still_in(self):
        from utk_curio.backend.tests.stress.sockets import Room

        room = Room(0, ["owner", "ed1", "ed2", "ed3"])
        for member in ("owner", "ed1", "ed3"):
            room.arrive("registered", member)
        room.leave("ed3")
        self.assertEqual(room.registered_editors(), ["ed1"])

    def test_the_tabs_of_a_room_spread_over_its_code_nodes(self):
        from utk_curio.backend.tests.stress.sockets import Room

        room = Room(0, ["u0", "u1", "u2"])
        room.targets = [("n1", "# "), ("n2", "// ")]
        self.assertEqual([room.targets_for(m)[0][0] for m in ("u0", "u1", "u2")], ["n1", "n2", "n1"])

    def test_the_room_takes_one_verdict_on_settling_for_all_its_tabs(self):
        """So the tabs that go on to compare their docs are the same for all:
        an update landing between two tabs' looks would split them."""
        from utk_curio.backend.tests.stress.sockets import Room

        room = Room(0, ["a", "b"])
        room.ledger.synced("a")
        room.ledger.synced("b")
        room.ledger.sent("a", 11, 1, 1.0)
        room.arrive("settled", "b")
        self.assertFalse(room.settle("a", 1), "b lacks a's update")
        room.ledger.applied("b", {11: 1}, 1.5)
        self.assertFalse(room.settle("b", 1))

    def _check_both(self, first: str, second: str) -> tuple:
        from utk_curio.backend.tests.stress.sockets import Room

        room = Room(0, ["a", "b"])
        found = {}
        a = threading.Thread(target=lambda: found.setdefault("a", room.check("a", first, 5)))
        a.start()
        found["b"] = room.check("b", second, 5)
        a.join(5)
        return found, room.diverged

    def test_a_doc_that_differs_from_the_rooms_first_names_that_tab(self):
        self.assertEqual(self._check_both("doc-1", "doc-2"), ({"a": None, "b": "a"}, True))

    def test_tabs_holding_the_same_doc_agree(self):
        self.assertEqual(self._check_both("doc-1", "doc-1"), ({"a": None, "b": None}, False))


class TheSocketReadsInOrderTest(unittest.TestCase):
    def test_a_binary_event_is_put_together_on_the_thread_that_read_it(self):
        """engineio's client would hand each message to a thread of its own,
        and python-socketio's client puts a binary event together across
        them; the tab's client takes each message where it was read."""
        from engineio import packet as eio_packet
        from socketio import packet

        from utk_curio.backend.tests.stress.sockets import EVENT, TabClient

        client = TabClient(reconnection=False, handle_sigint=False)
        got = []
        client.on(EVENT, lambda data: got.append((threading.get_ident(), data)), namespace="/collab")
        sent = [{"projectId": "p", "message": b"\x00\x02\x03abc"},
                {"projectId": "p", "message": b"\x00\x02\x01z"}]
        for payload in sent:
            parts = packet.Packet(packet.EVENT, namespace="/collab", data=[EVENT, payload]).encode()
            self.assertIsInstance(parts, list, "a doc message is a binary event")
            for part in parts:
                client.eio._receive_packet(eio_packet.Packet(eio_packet.MESSAGE, data=part))
        self.assertEqual(got, [(threading.get_ident(), payload) for payload in sent])


class ATabsAnswersTest(unittest.TestCase):
    """An update is answered by its ack, or, when the ack says ``queued``, by
    the kept message that answers it once its batch is applied; a tab's
    answers come in the order it sent its updates."""

    QUEUED = {"ok": True, "queued": True}

    def _tab(self):
        """A tab holding a doc of one code node, its socket a stand-in that
        keeps each update's answer callback; the samples it records."""
        from pycrdt import create_update_message

        from utk_curio.backend.app.collaboration import doc_mapping
        from utk_curio.backend.tests.stress.sockets import SyncLedger, Tab

        samples = []
        tab = Tab("t", "p", SyncLedger(),
                  lambda label, seconds, ok, error=None, kind=None: samples.append((label, ok, error)))
        server = doc_mapping.new_doc()
        doc_mapping.dataflow_to_doc({"nodes": [{"id": "n", "type": "curio.builtin/code", "x": 0, "y": 0,
                                                "content": ""}], "edges": []}, server, doc_id="d")
        tab.receive({"projectId": "p", "message": create_update_message(server.get_update())})
        answers = []

        class Link:
            def emit(self, event, data, callback=None):
                answers.append(callback)

        tab.link = Link()
        return tab, answers, samples

    def test_a_queued_update_is_answered_by_its_kept_message_even_before_its_queued_ack(self):
        tab, answers, samples = self._tab()
        tab.keystroke("n", "a")
        answers[0]({"ok": True, "kept": {}})
        self.assertEqual(samples, [("socket yjs update", True, None)], "an ack did not answer its update")

        tab.keystroke("n", "b")
        tab.keystroke("n", "c")
        answers[1](self.QUEUED)
        self.assertEqual(len(samples), 1, "a queued update was taken as answered")
        tab.receive({"projectId": "p", "answered": 2, "kept": {}})
        self.assertEqual(samples, [("socket yjs update", True, None)] * 3)
        answers[2](self.QUEUED)
        self.assertEqual(len(samples), 3, "the queued ack of an update answered already counted again")
        self.assertTrue(tab.wait_for_answers(0.1))

    def test_what_a_kept_message_refused_is_a_failure(self):
        tab, answers, samples = self._tab()
        tab.keystroke("n", "a")
        answers[0](self.QUEUED)
        self.assertEqual(samples, [], "a queued update was taken as answered")
        tab.receive({"projectId": "p", "answered": 1, "kept": {}, "refused": {"invalid_message": 1}})
        [(label, ok, error)] = samples
        self.assertEqual((label, ok), ("socket yjs update", False))
        self.assertIn("invalid_message", error)
        self.assertTrue(tab.wait_for_answers(0.1))


class WhereATabConnectsAndWorksTest(unittest.TestCase):
    def test_the_socket_target_is_the_canvas_one(self):
        """collabSocketTarget.ts: a backend under a path puts its prefix in the path."""
        from utk_curio.backend.tests.stress.sockets import socket_target

        self.assertEqual(socket_target("http://localhost:5072"),
                         ("http://localhost:5072", "/socket.io"))
        self.assertEqual(socket_target("https://flow.example.org/api/"),
                         ("https://flow.example.org", "/api/socket.io"))

    def test_a_tab_types_and_drags_where_the_layout_puts_code_and_place(self):
        from utk_curio.backend.tests.stress import sockets
        from utk_curio.common import shared_constants

        layout = shared_constants.read("dataflowDoc")
        self.assertEqual(sockets.EVENT, layout["event"])
        self.assertEqual(layout["node"][sockets.CODE_KEY], "@text")
        self.assertEqual(layout["node"]["x"], f"{sockets.PLACE_KEY}.{sockets.X_MEMBER}")
        self.assertEqual(layout["node"]["y"], f"{sockets.PLACE_KEY}.{sockets.Y_MEMBER}")
        self.assertEqual(layout["roots"][sockets.NODES], "map")

    def test_a_tab_types_whole_comment_lines(self):
        from utk_curio.backend.tests.stress import sockets

        line = sockets.TYPED_LINE.format(prefix="# ", user="stress_x_t5x0_u1")
        self.assertTrue(line.startswith("# ") and line.endswith("\n") and line.count("\n") == 1)

    def test_a_session_types_at_a_persons_pace_and_a_burst_without_pauses(self):
        from utk_curio.backend.tests.stress.driver import BURST
        from utk_curio.backend.tests.stress.run import build_pacing
        from utk_curio.backend.tests.stress.sockets import BURST_KEY_GAP_S
        import random

        self.assertEqual((BURST.key_gap(), BURST.pause()), (BURST_KEY_GAP_S, 0.0))
        session = build_pacing("session", 3, random.Random(1))
        for pacing in session:
            self.assertGreater(pacing.key_gap(), 0)
            self.assertGreater(pacing.pause(), 0)

    def test_a_tier_runs_in_processes_of_whole_rooms_ten_users_at_most(self):
        """One process carrying every tab of a 50-user burst measured itself;
        a room's tabs share their ledger and phases, so a room stays whole."""
        from utk_curio.backend.tests.stress.run import USERS_PER_PROCESS, tier_slices

        self.assertEqual(USERS_PER_PROCESS, 10)
        slices = tier_slices(100, 5)
        self.assertEqual(len(slices), 10)
        self.assertEqual(sorted(i for part in slices for i in part), list(range(100)))
        for part in slices:
            self.assertLessEqual(len(part), 10)
            self.assertEqual(part, list(range(part[0], part[0] + len(part))))
            for room in {i // 5 for i in part}:
                self.assertLessEqual(set(range(room * 5, room * 5 + 5)), set(part), f"room {room} is split")
        self.assertEqual(tier_slices(12, 5), [list(range(10)), [10, 11]])
        self.assertEqual(tier_slices(1, 5), [[0]])
        self.assertEqual(tier_slices(25, 0), [list(range(10)), list(range(10, 20)), list(range(20, 25))])
        self.assertEqual(tier_slices(7, 12), [list(range(7))], "a room larger than a process stays whole")

    def test_a_tier_is_put_in_rooms_of_the_room_size(self):
        from utk_curio.backend.tests.stress.run import build_rooms

        rooms = build_rooms([f"u{i}" for i in range(12)], 5)
        self.assertEqual([room.members for room in rooms],
                         [["u0", "u1", "u2", "u3", "u4"], ["u5", "u6", "u7", "u8", "u9"], ["u10", "u11"]])
        self.assertEqual([room.owner for room in rooms], ["u0", "u5", "u10"])
        self.assertEqual(build_rooms(["u0"], 5)[0].members, ["u0"])
        self.assertEqual(build_rooms(["u0", "u1"], 0), [])


#: A dataflow of two nodes and their connection, as a room's doc starts.
_FLOW = {
    "nodes": [
        {"id": "loader", "type": "curio.builtin/python-computation", "x": 10, "y": 20, "content": "x = 1\n"},
        {"id": "chart", "type": "curio.builtin/vis-vega", "x": 300, "y": 20, "content": "{}"},
    ],
    "edges": [{"id": "e1", "source": "loader", "target": "chart"}],
    "name": "Shared",
}


class _Link:
    """A tab's socket stand-in: it keeps what the tab sends, answers each
    update, and answers each call with the next of *answers*."""

    def __init__(self, answers=()):
        self.sent = []
        self.calls = []
        self.answers = list(answers)

    def emit(self, event, data, callback=None):
        self.sent.append(data["message"])
        if callback is not None:
            callback({"ok": True})

    def call(self, event, data, _timeout):
        self.calls.append((event, data))
        return self.answers.pop(0)


def _tab(name, answers=(), flow=None):
    """*name*'s tab holding *flow* (:data:`_FLOW`) as the server sent it,
    on a stand-in socket; the samples it records."""
    from pycrdt import create_update_message

    from utk_curio.backend.app.collaboration import doc_mapping
    from utk_curio.backend.tests.stress.sockets import SyncLedger, Tab

    samples = []
    tab = Tab(name, "p", SyncLedger(),
              lambda label, seconds, ok, error=None, kind=None: samples.append((label, ok, error, kind)))
    server = doc_mapping.new_doc()
    doc_mapping.dataflow_to_doc(flow or _FLOW, server, doc_id="d")
    tab.receive({"projectId": "p", "message": create_update_message(server.get_update())})
    tab.link = _Link(answers)
    return tab, samples


def _no_pause():
    from utk_curio.backend.tests.stress.driver import Pacing

    return Pacing(key_gap_min=0.0, key_gap_max=0.0)


class AMembersNodeTest(unittest.TestCase):
    def test_a_members_node_and_connection_land_as_the_canvas_writes_them(self):
        """One transaction of the doc's own mapping (``apply_dataflow``): a
        Python node that passes its input on, below its parent, and the
        connection from the parent's output to its input."""
        from utk_curio.backend.tests.stress.sockets import MEMBER_NODE_TYPE, PASS_ON_CODE, member_node

        tab, samples = _tab("a")
        node, edge = member_node({"id": "loader", "x": 10, "y": 20}, 2)
        self.assertEqual(uuid.UUID(node["id"]).version, 4)
        tab.add_node(node, edge)
        self.assertEqual(len(tab.link.sent), 1, "a node and its connection are one update")
        flow = tab.dataflow()
        mine = next(n for n in flow["nodes"] if n["id"] == node["id"])
        self.assertEqual((mine["type"], mine["content"]), (MEMBER_NODE_TYPE, PASS_ON_CODE))
        self.assertGreater(mine["x"], 10)
        self.assertGreater(mine["y"], 20)
        self.assertIn({"id": edge["id"], "source": "loader", "target": node["id"],
                       "sourceHandle": "out", "targetHandle": "in"}, flow["edges"])
        self.assertEqual([n["id"] for n in flow["nodes"]][:2], ["loader", "chart"])
        self.assertEqual((tab.nodes_added, tab.edges_added), (1, 1))
        self.assertTrue(all(ok for _label, ok, _error, _kind in samples), samples)

    def test_two_members_adding_at_once_end_with_the_same_doc(self):
        """Each tab writes the nodes' order again, as the canvas does: the
        order the docs agree on holds both nodes once."""
        from utk_curio.backend.tests.stress.sockets import member_node

        a, _ = _tab("a")
        b, _ = _tab("b")
        node_a, edge_a = member_node({"id": "loader", "x": 10, "y": 20}, 1)
        node_b, edge_b = member_node({"id": "loader", "x": 10, "y": 20}, 2)
        a.add_node(node_a, edge_a)
        b.add_node(node_b, edge_b)
        self.assertNotEqual(a.digest(), b.digest())
        for sender, receiver in ((a, b), (b, a)):
            for message in sender.link.sent:
                receiver.receive({"projectId": "p", "message": message})
        self.assertEqual(a.digest(), b.digest())
        ids = [n["id"] for n in a.dataflow()["nodes"]]
        self.assertEqual(sorted(ids[2:]), sorted([node_a["id"], node_b["id"]]))
        self.assertEqual(len(ids), len(set(ids)))


class TheDigestTest(unittest.TestCase):
    def _digest(self, **changes):
        flow = {**_FLOW, **changes}
        return _tab("t", flow=flow)[0].digest()

    def test_tabs_holding_the_same_nodes_and_connections_agree(self):
        self.assertEqual(self._digest(), self._digest())

    def test_a_connection_more_or_another_handle_is_another_doc(self):
        plain = self._digest()
        more = self._digest(edges=[*_FLOW["edges"], {"id": "e2", "source": "chart", "target": "loader"}])
        handle = self._digest(edges=[{**_FLOW["edges"][0], "targetHandle": "in_1"}])
        self.assertEqual(len({plain, more, handle}), 3)

    def test_a_node_more_or_another_type_is_another_doc(self):
        plain = self._digest()
        more = self._digest(nodes=[*_FLOW["nodes"], {"id": "n3", "type": "curio.builtin/python-computation",
                                                   "x": 0, "y": 0, "content": ""}])
        retyped = self._digest(nodes=[{**_FLOW["nodes"][0], "type": "curio.builtin/data-loading"}, _FLOW["nodes"][1]])
        self.assertEqual(len({plain, more, retyped}), 3)


class TheRoomsLocksTest(unittest.TestCase):
    """A tab keeps the room's locks as the canvas keeps them
    (``CollaborationProvider.tsx``), and asks for the lock of the node it
    types in, as the canvas does when the node takes focus."""

    def test_a_tab_keeps_the_rooms_locks_from_their_events(self):
        tab, _ = _tab("a")
        tab.room_event("node_locked", {"nodeId": "loader", "lock": {"participant_id": "pb", "username": "b"}})
        tab.room_event("node_locked", {"nodeId": "chart", "lock": {"participant_id": "pc", "username": "c"}})
        self.assertEqual(tab.room_locks(), {"loader": "b", "chart": "c"})
        tab.room_event("node_unlocked", {"nodeId": "chart"})
        self.assertEqual(tab.room_locks(), {"loader": "b"})
        tab.room_event("user_left", {"participant_id": "pc", "released_locks": ["loader"]})
        self.assertEqual(tab.room_locks(), {"loader": "b"}, "a leave lets go only of its own locks")
        tab.room_event("user_left", {"participant_id": "pb", "released_locks": ["loader"]})
        self.assertEqual(tab.room_locks(), {})
        tab.room_event("agent_turn", {"nodeId": "loader"})
        self.assertEqual(tab.wait_for_no_locks(0.01), {})
        self.assertEqual(tab.locks_left, [])

    def test_a_lock_still_shown_after_the_wait_is_kept(self):
        tab, _ = _tab("a")
        tab.room_event("node_locked", {"nodeId": "loader", "lock": {"participant_id": "pb", "username": "b"}})
        threading.Timer(0.05, tab.room_event, args=("node_unlocked", {"nodeId": "loader"})).start()
        self.assertEqual(tab.wait_for_no_locks(5), {}, "the wait ends once the lock is let go")
        tab.room_event("node_locked", {"nodeId": "chart", "lock": {"participant_id": "pb", "username": "b",
                                                                   "agent": "Node Builder"}})
        self.assertEqual(tab.wait_for_no_locks(0.01), {"chart": "Node Builder for b"})
        self.assertEqual(tab.locks_left, ["chart by Node Builder for b"])

    def test_a_tab_that_gets_the_lock_types_then_lets_it_go(self):
        tab, samples = _tab("a", answers=[{"ok": True, "lock": {}}, {"ok": True}])
        node_id, line = tab.work([("loader", "# ")], _no_pause(), lock=True)
        self.assertEqual((node_id, line), ("loader", "# a typed this line\n"))
        self.assertEqual([event for event, _data in tab.link.calls], ["node_lock", "node_unlock"])
        self.assertEqual(tab.link.calls[0][1], {"projectId": "p", "nodeId": "loader"})
        self.assertTrue(tab.dataflow()["nodes"][0]["content"].startswith(line * 2))
        self.assertEqual((tab.locks_taken, tab.locks_refused, tab.locks_released), (1, 0, 1))
        self.assertTrue(all(ok for _label, ok, _error, _kind in samples), samples)

    def test_a_lock_another_holds_is_no_failure_and_the_tab_types_anyway(self):
        """Locks are soft: the canvas only shows a chip. The tab lets go of
        nothing it did not get."""
        tab, samples = _tab("a", answers=[{"ok": False, "error": "locked_by_other"}])
        tab.work([("loader", "# ")], _no_pause(), lock=True)
        self.assertEqual([event for event, _data in tab.link.calls], ["node_lock"])
        self.assertIn("# a typed this line\n", tab.dataflow()["nodes"][0]["content"])
        self.assertEqual((tab.locks_taken, tab.locks_refused, tab.locks_released), (0, 1, 0))
        self.assertTrue(all(ok for _label, ok, _error, _kind in samples), samples)

    def test_any_other_refusal_of_a_lock_or_its_release_is_a_failure(self):
        tab, samples = _tab("a", answers=[{"ok": False, "error": "read_only"},
                                          {"ok": False, "error": "not_lock_owner"}])
        self.assertFalse(tab.take_lock("loader"))
        tab.release_lock("loader")
        failed = [(label, kind) for label, ok, _error, kind in samples if not ok]
        self.assertEqual(failed, [("socket node_lock", "socket"), ("socket node_unlock", "socket")])
        self.assertEqual(tab.locks_released, 0)


class _RoomUser:
    def __init__(self, name):
        self.name = name
        self.samples = []

    def socket_sample(self, label, seconds, ok, error=None, kind=None):
        self.samples.append((label, ok, error, kind))


class TheLocksAtTheEndTest(unittest.TestCase):
    """Once every member's work is over and before any tab closes: the
    server's locks, read once for the room, and each tab's must be none."""

    def _read(self, server_locks, shown=None):
        from utk_curio.backend.tests.stress.sockets import Room, _locks_at_the_end

        room = Room(0, ["a", "b"], shared=True)
        users, tabs = {}, {}
        for name in ("a", "b"):
            tab, _ = _tab(name, answers=[{"ok": True, "snapshot": {"locks": server_locks}}])
            for node_id, lock in (shown or {}).items():
                tab.room_event("node_locked", {"nodeId": node_id, "lock": lock})
            users[name], tabs[name] = _RoomUser(name), tab
            _locks_at_the_end(users[name], room, tab)
        return room, users, tabs

    def test_no_lock_anywhere_is_no_failure(self):
        room, users, tabs = self._read({})
        self.assertEqual(room.locks_at_end, {})
        self.assertEqual([users[name].samples for name in users], [[], []])
        self.assertEqual(len(tabs["a"].link.calls) + len(tabs["b"].link.calls), 1,
                         "the room's first tab there reads the server's locks, once")

    def test_a_lock_the_server_still_holds_is_one_failure(self):
        room, users, _ = self._read({"loader": {"participant_id": "pb", "username": "b"}})
        self.assertEqual(room.locks_at_end, {"loader": "b"})
        failures = [s for name in users for s in users[name].samples if not s[1]]
        self.assertEqual([(label, kind) for label, _ok, _error, kind in failures], [("socket locks", "locked")])
        self.assertIn("node loader by b", failures[0][2])

    def test_a_tab_still_showing_a_lock_is_a_failure_of_its_own(self):
        from unittest import mock

        from utk_curio.backend.tests.stress import sockets

        with mock.patch.object(sockets, "SETTLE_TIMEOUT_S", 0.01):
            _, users, tabs = self._read({}, shown={"chart": {"participant_id": "pa", "username": "a"}})
        for name in ("a", "b"):
            [(label, ok, error, kind)] = users[name].samples
            self.assertEqual((label, ok, kind), ("socket locks", False, "locked"))
            self.assertIn("node chart by a", error)
            self.assertEqual(tabs[name].locks_left, ["chart by a"])


class ASharedRoomTest(unittest.TestCase):
    def test_a_canvas_with_no_code_node_has_its_members_type_two_to_a_node(self):
        """Its dataflow holds only Autark documents, which a typed line would
        break: the members type in their own nodes, two to each, so a lock
        is refused there too."""
        from utk_curio.backend.tests.stress.sockets import Room

        room = Room(0, [f"u{i}" for i in range(5)], shared=True)
        for index, member in enumerate(room.members):
            if member != "u2":
                room.add(member, f"n{index}", f"e{index}", "load")
        first = {member: room.targets_for(member)[0] for member in room.members}
        self.assertEqual(first, {"u0": ("n0", "# "), "u1": ("n0", "# "), "u2": ("n0", "# "),
                                 "u3": ("n0", "# "), "u4": ("n4", "# ")})
        self.assertEqual(Room(1, ["u0"]).targets_for("u0"), [], "a room of copies has no such fallback")

    def test_a_canvas_with_code_nodes_spreads_over_them_as_rooms_do(self):
        from utk_curio.backend.tests.stress.sockets import Room

        room = Room(0, ["u0", "u1", "u2"], shared=True)
        room.targets = [("n1", "# "), ("n2", "// ")]
        room.add("u0", "own0", "e0", "n1")
        self.assertEqual([room.targets_for(m)[0][0] for m in room.members], ["n1", "n2", "n1"])

    def test_a_shared_rooms_outcome_says_what_its_members_did_on_the_canvas(self):
        from utk_curio.backend.tests.stress.sockets import Room

        room = Room(3, ["a", "b"], shared=True)
        room.example = "11.json"
        room.closed_tab("a", {"synced": True, "nodes_added": 1, "edges_added": 1, "locks_taken": 1,
                              "locks_released": 1, "locks_left": []})
        room.closed_tab("b", {"synced": True, "nodes_added": 1, "edges_added": 1, "locks_refused": 1,
                              "locks_left": ["x by a"]})
        room.locks_at_end = {"x": "a"}
        canvas = room.outcome()["canvas"]
        self.assertEqual((canvas["example"], canvas["nodes_added"], canvas["edges_added"]), ("11.json", 2, 2))
        self.assertEqual(canvas["locks"], {"taken": 1, "refused": 1, "released": 1,
                                           "held_at_end": ["x by a"], "tabs_showing_locks": 1})
        self.assertNotIn("canvas", Room(0, ["a"]).outcome())


class WhichNodeAndExampleTest(unittest.TestCase):
    def test_room_k_works_on_example_k_of_the_mix(self):
        """Ten rooms of ten make every example of a mix of six a shared canvas;
        without shared canvases each user has its own, round-robin."""
        from utk_curio.backend.tests.stress.run import example_of

        mix = ["e0", "e1", "e2", "e3", "e4", "e5"]
        self.assertEqual([example_of(index, 10, mix, True) for index in range(0, 100, 10)],
                         mix + mix[:4])
        self.assertEqual({example_of(index, 10, mix, True) for index in range(30, 40)}, {"e3"})
        self.assertEqual([example_of(index, 10, mix) for index in range(7)], mix + ["e0"])

    def test_each_example_of_the_mix_has_a_node_a_python_node_reads(self):
        """Python first, then JavaScript, then an Autark data load, in the
        order the dataflow runs."""
        import json

        from utk_curio.backend.app.execution.autk_spec_kind import is_autk_data_node
        from utk_curio.backend.tests.stress.run import DEFAULT_MIX, EXAMPLES_DIR, canvas_parent
        from utk_curio.backend.tests.test_frontend.workflow_spec import parse_workflow

        picked = {}
        for name in DEFAULT_MIX:
            path = os.path.join(EXAMPLES_DIR, name)
            with open(path, encoding="utf-8") as handle:
                nodes = json.load(handle)["dataflow"]["nodes"]
            autk = {node["id"]: "compiled" for node in nodes if is_autk_data_node(node)}
            parent = canvas_parent(parse_workflow(path), autk)
            picked[name] = (parent["id"], parent["engine"])
        self.assertEqual(picked["08-autark-spatial-join-regression.json"], ("niteroi-raster", "python"))
        self.assertEqual(picked["11-autark-pbf-loading.json"], ("pbf-load", "autark"))
        self.assertEqual(picked["dataflows/regression.json"], ("reg-data", "autark"))
        self.assertEqual(picked["dataflows/js-computation.json"], ("js-node-1", "javascript"))
        self.assertEqual(picked["01-vega-lite-chained-transforms.json"][1], "python")
        self.assertEqual(picked["02-vega-lite-spatial-density.json"][1], "python")

    def test_a_dataflow_with_no_such_node_has_none(self):
        from utk_curio.backend.tests.stress.run import canvas_parent
        from utk_curio.backend.tests.test_frontend.workflow_spec import parse_workflow_dict

        flow = parse_workflow_dict({"dataflow": {"nodes": [
            {"id": "v", "type": "curio.builtin/vis-vega", "content": "{}"},
            {"id": "m", "type": "curio.builtin/autk-grammar", "content": "{}"},
        ], "edges": []}})
        self.assertIsNone(canvas_parent(flow, {}))


class TheOwnersRunAndSaveTest(unittest.TestCase):
    def test_a_step_is_done_as_its_role_says_and_a_members_node_runs(self):
        from utk_curio.backend.tests.stress.driver import steps_not_done

        steps = [
            {"nodeId": "load", "role": "run", "status": "ok"},
            {"nodeId": "chart", "role": "forward", "status": "forwarded"},
            {"nodeId": "map", "role": "browser", "status": "browser"},
            {"nodeId": "plot", "role": "browser", "status": "waiting"},
            {"nodeId": "join", "role": "run", "status": "error", "stderrTail": "Traceback\nValueError: no"},
            {"nodeId": "late", "role": "run", "status": "running"},
            {"nodeId": "type", "role": "missing", "status": "error"},
            {"nodeId": "mine", "role": "run", "status": "waiting", "skipReason": "Waits for the canvas"},
        ]
        self.assertEqual(steps_not_done(steps, must_run={"mine"}), [
            "join (run) ended error: Traceback ValueError: no",
            "late (run) ended running",
            "type (missing) ended error",
            "mine (run) ended waiting: Waits for the canvas",
        ])

    def test_a_save_must_hold_each_members_node_connection_and_lines(self):
        from utk_curio.backend.tests.stress.driver import saved_lacks

        saved = {"nodes": {"na": "return input_0", "nb": "", "load": "# b typed\n# b typed\nx = 1"},
                 "edges": {"ea": ["load", "na"], "eb": ["chart", "nb"]}}
        added = {"a": ("na", "ea", "load"), "b": ("nb", "eb", "load"), "c": ("nc", "ec", "load")}
        typed = {"a": ("load", "# a typed\n"), "b": ("load", "# b typed\n")}
        self.assertEqual(saved_lacks(saved, added, typed), [
            "b's node nb's code", "b's connection eb", "c's node nc", "c's connection ec",
            "a's lines in node load",
        ])
        whole = {"nodes": {"na": "return input_0", "load": "# a typed\n# a typed\nx"},
                 "edges": {"ea": ["load", "na"]}}
        self.assertEqual(saved_lacks(whole, {"a": ("na", "ea", "load")}, {"a": ("load", "# a typed\n")}), [])

    def _reads(self, *answers):
        """A user whose node ``n`` made a list, and the Accept header of each
        read of it, the backend answering with *answers* (status, body)."""
        import requests

        from utk_curio.backend.tests.stress.driver import VirtualUser

        user = VirtualUser("http://backend", "u", "e.json", {}, None, {})
        user.project_id = "p"
        user.result.outputs["n"] = {"path": "art1", "dataType": "list"}
        replies, accepts = [], []
        for status, body in answers:
            reply = requests.Response()
            reply.status_code, reply._content, reply.encoding = status, body, "utf-8"
            replies.append(reply)

        class Session:
            def request(self, _method, _url, **kwargs):
                accepts.append((kwargs.get("headers") or {}).get("Accept"))
                return replies[len(accepts) - 1]

        user.session = Session()
        return user, accepts

    def test_an_output_that_is_no_table_is_read_as_json_as_the_canvas_does(self):
        from types import SimpleNamespace

        from utk_curio.backend.tests.stress.driver import ARROW_IPC_MIME, json_artifact_hash

        body = b'{"data": [{"name": "roads"}], "dataType": "list", "filename": "art1"}'
        user, accepts = self._reads(
            (415, b'{"error": "not_acceptable", "message": "Arrow IPC only supports tabular kinds; '
                  b"got 'list'; re-request without the Arrow Accept header.\"}"),
            (200, body),
        )
        user._compare_to_baseline(SimpleNamespace(id="n"))
        self.assertEqual(accepts, [ARROW_IPC_MIME, None])
        self.assertEqual(user.result.hashes["n"], json_artifact_hash(body))
        self.assertEqual(user.result.failures, [])

    def test_a_geodataframe_refused_for_its_geometry_is_still_a_failure(self):
        """That 415 is how the backend's dropped WKB opt-in was caught: no
        JSON read hides it."""
        from types import SimpleNamespace

        from utk_curio.backend.tests.stress.driver import UserFailed

        user, accepts = self._reads(
            (415, b'{"error": "not_acceptable", "message": "Arrow IPC serves geodataframe geometry as WKB; '
                  b'send X-Curio-Accept-Geometry: wkb to accept it"}'),
        )
        with self.assertRaises(UserFailed):
            user._compare_to_baseline(SimpleNamespace(id="n"))
        self.assertEqual(len(accepts), 1)
        [failure] = user.result.failures
        self.assertEqual((failure.status, failure.kind), (415, "http_error"))

    def test_a_json_output_is_compared_without_its_per_run_name(self):
        """What the Arrow route answers 415 (a list, a dict) is read as JSON,
        as the canvas reads it: two runs' outputs differ by their name only."""
        from utk_curio.backend.tests.stress.driver import json_artifact_hash

        one = json_artifact_hash(b'{"data": [{"name": "roads"}], "dataType": "list", "filename": "a1"}')
        two = json_artifact_hash(b'{"filename": "b2", "dataType": "list", "data": [{"name": "roads"}]}')
        other = json_artifact_hash(b'{"data": [{"name": "parks"}], "dataType": "list", "filename": "a1"}')
        self.assertEqual(one, two)
        self.assertNotEqual(one, other)


if __name__ == "__main__":
    unittest.main()
