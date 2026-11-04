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

The tab against the server is ``test_collaboration/test_stress_tabs.py``.
Names are imported in each test, so a checkout without them fails test by test.
"""

import threading
import unittest


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


if __name__ == "__main__":
    unittest.main()
