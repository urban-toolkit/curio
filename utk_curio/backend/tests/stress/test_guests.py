"""Hosted guests on one example (``--guests``, ``guests.py``), with no server.

* The stage's pure parts: the node a guest types in, the example found in a
  gallery by its name, a node's changes, a copy's problems by kind, the rooms
  two guests shared.
* A tab's events after its join name the id the join answered, a hosted
  guest's own copy's, while its joins name the dataflow it opened.
* A guest's whole visit on stand-ins for the server, its socket and its
  agent's calls: every HTTP call names the example, never the copy, and its
  socket's events after the join name the copy; its copy read back holds its
  own work, and work that is not its own is a failure; a join to the
  example's own room stops it before it types.
* The report: each copy's process by the one rule (``report.copy_process``),
  each process's copies, the guests' summary and table, and the reader's
  checks failing the tier while being no user of it.
* Every backend process's thread stacks, read once a while after a guests
  tier's first agent turn was asked, while the turns run, into the report's
  folder, which the report names.
* ``--guests`` refuses ``--shared-canvas`` and ``--agents``.

Names are imported in each test, so a checkout without them fails test by test.
"""

import contextlib
import io
import json
import os
import tempfile
import threading
import time
import unittest
import unittest.mock as mock
from pathlib import Path
from urllib.parse import urlsplit

#: The example, and a guest's copy of it whose id falls on another of eight
#: processes: 0x3c is process 4 of 8, 0xa1 process 1.
EXAMPLE = "3c000000-0000-4000-8000-000000000001"
COPY = "a1000000-0000-5000-8000-000000000002"
OTHER_COPY = "b2000000-0000-5000-8000-000000000003"
LOADER = "6f0c1d2e-3a4b-4c5d-8e6f-7a8b9c0d1e2f"
NODE = "5b1d1e8a-2f4a-4c55-9d0e-1a2b3c4d5e6f"
ROUTE_HEADER = "X-Curio-Dataflow"

#: The example's dataflow: a loader, then the Python node the guests type in.
FLOW = {
    "nodes": [
        {"id": LOADER, "type": "curio.builtin/data-loading", "x": 10, "y": 20, "content": "x = 1"},
        {"id": NODE, "type": "curio.builtin/python-computation", "x": 300, "y": 20, "content": "return input_0"},
    ],
    "edges": [{"id": "e1", "source": LOADER, "target": NODE, "sourceHandle": "out", "targetHandle": "in"}],
    "name": "Guests' example",
}
CODES = {LOADER: "x = 1", NODE: "return input_0"}


def _job():
    return {"example": "e.json", "name": FLOW["name"], "id": EXAMPLE, "node_id": NODE, "codes": dict(CODES)}


def _no_pause():
    from utk_curio.backend.tests.stress.driver import Pacing

    return Pacing(key_gap_min=0.0, key_gap_max=0.0)


class ThePurePartsTest(unittest.TestCase):
    def test_a_guest_types_in_the_examples_first_python_node(self):
        from utk_curio.backend.tests.stress.guests import guest_node

        self.assertEqual(guest_node({"dataflow": FLOW}), NODE, "the loader comes first, but is no Python node")
        self.assertIsNone(guest_node({"dataflow": {"nodes": [FLOW["nodes"][0]], "edges": []}}))
        self.assertIsNone(guest_node(None))

    def test_the_example_is_the_one_dataflow_of_its_name_in_the_gallery(self):
        from utk_curio.backend.tests.stress.guests import find_example

        listing = [{"id": EXAMPLE, "name": FLOW["name"]}, {"id": OTHER_COPY, "name": "Another"}]
        self.assertEqual(find_example(listing, FLOW["name"]), (EXAMPLE, None))
        none, why = find_example(listing, "Missing")
        self.assertIsNone(none)
        self.assertIn("no dataflow named 'Missing'", why)
        twice, why = find_example([*listing, {"id": COPY, "name": FLOW["name"]}], FLOW["name"])
        self.assertIsNone(twice)
        self.assertIn("2 dataflows", why)
        self.assertIsNone(find_example({"error": "x"}, FLOW["name"])[0], "an answer that is no listing names none")

    def test_a_nodes_change_names_the_lines_it_gained(self):
        from utk_curio.backend.tests.stress.guests import changed_nodes

        self.assertEqual(changed_nodes(CODES, dict(CODES)), [])
        changed = changed_nodes(CODES, {LOADER: "x = 1", NODE: "# g typed this line\nreturn input_0", "n3": ""})
        self.assertEqual(len(changed), 2, changed)
        self.assertIn("# g typed this line", changed[0])
        self.assertIn("n3 was added", changed[1])
        self.assertEqual(changed_nodes(CODES, {NODE: "return input_0"}), [f"node {LOADER} is gone"])

    def test_a_copy_holding_its_guests_work_alone_has_no_problem(self):
        from utk_curio.backend.tests.stress.guests import copy_problems

        mine = "# g's Node Builder wrote this line\n# g typed this line\n# g typed this line\nreturn input_0"
        self.assertEqual(copy_problems({LOADER: "x = 1", NODE: mine}, CODES, NODE, mine), [])

    def test_work_that_is_not_the_guests_own_in_its_copy_is_leaked(self):
        from utk_curio.backend.tests.stress.guests import copy_problems

        mine = "# g's Node Builder wrote this line\nreturn input_0"
        theirs = "# h's Node Builder wrote this line\n" + mine
        problems = copy_problems({LOADER: "# h typed this line\nx = 1", NODE: theirs}, CODES, NODE, mine)
        self.assertEqual([kind for _message, kind in problems], ["leaked", "leaked"], problems)
        self.assertTrue(any("# h typed this line" in message for message, _kind in problems))
        self.assertTrue(any("# h's Node Builder wrote this line" in message for message, _kind in problems))
        added = copy_problems({LOADER: "x = 1", NODE: mine, "n3": ""}, CODES, NODE, mine)
        self.assertEqual(added, [("its copy has a node n3 the example has not", "leaked")])

    def test_its_own_work_missing_from_its_copy_is_not_in_copy(self):
        from utk_curio.backend.tests.stress.guests import copy_problems

        mine = "# g's Node Builder wrote this line\nreturn input_0"
        [(message, kind)] = copy_problems({LOADER: "x = 1", NODE: "return input_0"}, CODES, NODE, mine)
        self.assertEqual(kind, "not_in_copy")
        self.assertIn(NODE, message)
        self.assertEqual(copy_problems({LOADER: "x = 1"}, CODES, NODE, mine),
                         [(f"its copy has no node {NODE}", "not_in_copy")])
        self.assertEqual([kind for _message, kind in copy_problems({NODE: mine}, CODES, NODE, mine)], ["leaked"],
                         "another node gone from its copy is no work of its own")

    def test_two_guests_in_one_room_are_named(self):
        from utk_curio.backend.tests.stress.guests import shared_rooms

        outcomes = [{"guest": "g0", "project_id": COPY}, {"guest": "g1", "project_id": OTHER_COPY},
                    {"guest": "g2", "project_id": COPY}, {"guest": "g3", "project_id": None}]
        self.assertEqual(shared_rooms(outcomes), [f"g0, g2 joined one room, {COPY}"])
        self.assertEqual(shared_rooms(outcomes[:2]), [])


class _Link:
    """A tab's socket stand-in: it keeps the payload of each update the tab
    sends and of each call, and answers each call with the next of *answers*."""

    def __init__(self, answers=()):
        self.emitted = []
        self.calls = []
        self.answers = list(answers)

    def emit(self, event, data, callback=None):
        self.emitted.append(data)
        if callback is not None:
            callback({"ok": True})

    def call(self, event, data, _timeout):
        self.calls.append((event, data))
        return self.answers.pop(0)


class ATabNamesItsRoomTest(unittest.TestCase):
    def _tab(self, answers):
        from pycrdt import create_update_message

        from utk_curio.backend.app.collaboration import doc_mapping
        from utk_curio.backend.tests.stress.sockets import SyncLedger, Tab

        samples = []
        tab = Tab("g", EXAMPLE, SyncLedger(),
                  lambda label, seconds, ok, error=None, kind=None: samples.append((label, ok, error, kind)))
        server = doc_mapping.new_doc()
        doc_mapping.dataflow_to_doc(FLOW, server, doc_id="d")
        tab.receive({"projectId": COPY, "message": create_update_message(server.get_update())})
        tab.link = _Link(answers)
        return tab, samples

    def test_after_its_join_a_tab_names_the_room_its_join_answered(self):
        """As the page's provider does: a hosted guest's join to an example
        answers with its own copy's id, which the room's events name; a join
        again names the dataflow the tab opened."""
        tab, samples = self._tab([
            {"ok": True, "role": "owner", "participant_id": "pg", "projectId": COPY, "snapshot": {}},
            {"ok": True, "lock": {}}, {"ok": True},
            {"ok": True, "role": "owner", "projectId": COPY, "snapshot": {"locks": {}, "activity": []}},
        ])
        tab.join()
        self.assertEqual((tab.project_id, tab.room_id), (EXAMPLE, COPY))
        tab.work([(NODE, "# ")], _no_pause(), lock=True)
        tab.server_room()

        joins = [data for event, data in tab.link.calls if event == "join_session"]
        locks = [data for event, data in tab.link.calls if event in ("node_lock", "node_unlock")]
        self.assertEqual([data["projectId"] for data in joins], [EXAMPLE, EXAMPLE])
        self.assertEqual({data["projectId"] for data in locks}, {COPY})
        self.assertTrue(tab.link.emitted)
        self.assertEqual({data["projectId"] for data in tab.link.emitted}, {COPY})
        self.assertEqual(tab.summary()["room_id"], COPY)
        self.assertTrue(all(ok for _label, ok, _error, _kind in samples), samples)

    def test_a_join_that_names_no_room_keeps_the_dataflow_the_tab_opened(self):
        tab, _ = self._tab([{"ok": True, "role": "owner", "participant_id": "p1", "snapshot": {}}])
        tab.join()
        self.assertEqual(tab.room_id, EXAMPLE)
        tab.keystroke(NODE, "#")
        self.assertEqual([data["projectId"] for data in tab.link.emitted], [EXAMPLE])


class _Response:
    def __init__(self, status: int, body=None, lines=()):
        self.status_code, self._body, self._lines = status, body, list(lines)
        self.content = json.dumps(body).encode() if body is not None else b""
        self.text = self.content.decode()

    def json(self):
        return self._body

    def iter_lines(self, decode_unicode=False):
        return iter(self._lines)

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


class _Server:
    """What a guest's visit reaches, standing in for the backend: the
    example's own dataflow, the guest's copy's doc its tab syncs and writes,
    and the agent's write landing there. It keeps every HTTP call's path and
    dataflow header, and every socket payload."""

    def __init__(self, join_room=COPY, read_back_adds=None):
        from utk_curio.backend.app.collaboration import doc_mapping

        self.doc = doc_mapping.new_doc()
        doc_mapping.dataflow_to_doc(FLOW, self.doc, doc_id="d")
        self.join_room = join_room
        #: Lines another guest's work put at the top of the guest's node, which
        #: its read back then holds.
        self.read_back_adds = read_back_adds
        self.http: list = []
        self.handshakes: list = []
        self.socket: list = []
        self.opened = 0
        self.link = None
        self.content = None
        self.ask_id = None

    # -- HTTP ---------------------------------------------------------------

    def answer(self, method, url, json_body=None, headers=None, params=None):
        from utk_curio.backend.app.collaboration import doc_mapping

        path = urlsplit(url).path
        self.http.append((method, path, (headers or {}).get(ROUTE_HEADER), params))
        if path == "/api/auth/signin/guest":
            return _Response(200, {"token": "guest-token"})
        if path == "/api/projects":
            return _Response(200, [{"id": EXAMPLE, "name": FLOW["name"]}, {"id": OTHER_COPY, "name": "Other"}])
        if path == f"/api/projects/{EXAMPLE}":
            self.opened += 1
            if self.opened == 1:
                return _Response(200, {"project": {}, "spec": {"dataflow": FLOW}, "outputs": []})
            flow = doc_mapping.doc_to_dataflow(self.doc)
            if self.read_back_adds:
                flow = {**flow, "nodes": [{**node, "content": self.read_back_adds + node["content"]}
                                          if node["id"] == NODE else node for node in flow["nodes"]]}
            return _Response(200, {"project": {}, "spec": {"dataflow": flow}, "outputs": []})
        if path.endswith("/attachments"):
            return _Response(201, {"attachmentId": "att-9"})
        if path == "/api/testing/agent-script":
            request = json.loads(json_body["replies"][0].split("\n")[1])["toolRequest"]
            self.content = request["params"]["content"]
            return _Response(200, {"pending": 2})
        if path.endswith("/turns"):
            self.ask_id = json_body["askId"]
            return _Response(202, {"askId": self.ask_id, "attachmentId": "att-9", "state": "running"})
        if path.endswith("/stream"):
            self._agent_writes()
            envelope = {"projectId": COPY, "attachmentId": "att-9", "askId": self.ask_id}
            return _Response(200, lines=[
                "event: turn", "data: " + json.dumps({**envelope, "seq": 4, "event": "tool_result",
                                                      "data": {"tool": "node.content.write", "status": "applied"}}),
                "event: turn", "data: " + json.dumps({**envelope, "seq": 6, "event": "done", "data": {}}),
            ])
        return _Response(404, {"error": f"no stand-in for {method} {path}"})

    def _agent_writes(self):
        """The agent writes the node in the copy's doc, which its room relays
        to the guest's tab, then tells the room its turn ended."""
        from pycrdt import create_update_message

        from utk_curio.backend.app.collaboration import doc_mapping
        from utk_curio.backend.tests.stress.sockets import CODE_KEY

        before = self.doc.get_state()
        base = doc_mapping.doc_to_dataflow(self.doc)
        target = {**base, "nodes": [{**node, CODE_KEY: self.content} if node["id"] == NODE else node
                                    for node in base["nodes"]]}
        doc_mapping.apply_dataflow(self.doc, base, target)
        self.link.on_yjs({"projectId": COPY, "message": create_update_message(self.doc.get_update(before))})
        self.link.on_room("agent_turn", {"projectId": COPY, "askId": self.ask_id, "seq": 6, "event": "done"})

    # -- the socket -----------------------------------------------------------

    def link_class(self):
        server = self

        class Link:
            def __init__(self, backend_url, namespace, token, on_yjs, on_close, on_room=None, dataflow=None):
                server.handshakes.append(dataflow)
                server.link = self
                self.on_yjs, self.on_room = on_yjs, on_room
                self.transport = "websocket"

            def emit(self, event, data, callback=None):
                from pycrdt import handle_sync_message

                server.socket.append((event, data["projectId"]))
                handle_sync_message(data["message"][1:], server.doc)
                if callback is not None:
                    callback({"ok": True})

            def call(self, event, data, _timeout):
                from pycrdt import handle_sync_message

                server.socket.append((event, data["projectId"]))
                if event == "join_session":
                    return {"ok": True, "role": "owner", "participant_id": "pg", "projectId": server.join_room,
                            "snapshot": {"locks": {}, "activity": []}}
                if event in ("node_lock", "node_unlock"):
                    return {"ok": True, "lock": {}}
                self.on_yjs({"projectId": server.join_room,
                             "message": handle_sync_message(data["message"][1:], server.doc)})
                return {"ok": True, "docId": "d"}

            def close(self):
                return None

        return Link

    def session_class(self):
        server = self

        class Session:
            def request(self, method, url, json=None, headers=None, timeout=None, params=None, **_kwargs):
                return server.answer(method, url, json, headers, params)

            def get(self, url, headers=None, stream=False, timeout=None, **_kwargs):
                return server.answer("GET", url, None, headers)

            def post(self, url, headers=None, timeout=None, **_kwargs):
                return server.answer("POST", url, None, headers)

            def close(self):
                return None

        return Session


class AGuestsVisitTest(unittest.TestCase):
    def _visit(self, server):
        from utk_curio.backend.tests.stress import agents, sockets
        from utk_curio.backend.tests.stress.guests import GuestVisit

        visit = GuestVisit("http://backend", "g0", 0, _job(), pacing=_no_pause(), namespace="/collab",
                           first_ask=threading.Event())
        visit.session = server.session_class()()
        with mock.patch.object(sockets, "SocketLink", server.link_class()), \
                mock.patch.object(agents.requests, "Session", server.session_class()), \
                mock.patch.object(sockets, "SETTLE_TIMEOUT_S", 2.0), \
                mock.patch.object(sockets, "CALL_TIMEOUT_S", 2.0):
            result = visit.run()
        return visit, result

    def test_a_guest_works_on_its_own_copy_and_names_the_example_in_every_call(self):
        """Sign in, the gallery, the example opened; its tab on its copy's
        room, its lines typed; its agent attached, scripted, asked and
        followed, writing its copy; its copy read back. Every HTTP call that
        names a dataflow names the example, as the page does today, and
        never the copy; the socket's events after its join name the copy."""
        server = _Server()
        visit, result = self._visit(server)

        self.assertEqual([(s.endpoint, s.error) for s in result.failures], [])
        self.assertTrue(result.completed)
        paths = [path for _method, path, _header, _params in server.http]
        self.assertEqual(paths[:3], ["/api/auth/signin/guest", "/api/projects", f"/api/projects/{EXAMPLE}"])
        self.assertEqual(paths[-1], f"/api/projects/{EXAMPLE}", "its copy is read back as a reload does")
        self.assertIn("/api/testing/agent-script", paths)
        self.assertFalse([path for path in paths if COPY in path], paths)
        self.assertEqual({header for _method, _path, header, _params in server.http[2:]}, {EXAMPLE})
        self.assertEqual({header for _method, _path, header, _params in server.http[:2]}, {None},
                         "no dataflow is named before the guest opens one")
        self.assertEqual([params for _m, path, _h, params in server.http if path == f"/api/projects/{EXAMPLE}"],
                         [{"results": "last"}] * 2)
        self.assertEqual(server.handshakes, [EXAMPLE])
        self.assertEqual({room for event, room in server.socket if event == "join_session"}, {EXAMPLE})
        self.assertEqual({room for event, room in server.socket if event != "join_session"}, {COPY})

        outcome = visit.outcome()
        self.assertEqual((outcome["project_id"], outcome["example_id"], outcome["room"]), (COPY, EXAMPLE, 0))
        self.assertEqual(outcome["copy"], {"read": True, "not_in_copy": [], "leaked": []})
        self.assertEqual(outcome["turn"]["write"], "landed")
        self.assertEqual(len(outcome["agents"]["turn_seconds"]), 1)
        self.assertTrue(outcome["sync_seconds"], "each answered keystroke is a sync time")
        self.assertEqual(len(outcome["sync_seconds"]), outcome["updates"])
        self.assertEqual((outcome["present_at_end"], outcome["locks_at_end"]), ([], []))
        code = server.content
        self.assertTrue(code.startswith("# g0's Node Builder wrote this line\n# g0 typed this line\n"), code)
        self.assertTrue(code.endswith("return input_0"), code)
        self.assertTrue(visit.first_ask.is_set(), "its ask tells the tier its turns are under way")

    def test_another_guests_work_in_its_copy_fails_it(self):
        server = _Server(read_back_adds="# g1 typed this line\n")
        visit, result = self._visit(server)

        self.assertFalse(result.completed)
        self.assertEqual([(s.endpoint, s.kind) for s in result.failures], [("its copy", "leaked")])
        self.assertIn("# g1 typed this line", result.failures[0].error)
        self.assertEqual(len(visit.outcome()["copy"]["leaked"]), 1)

    def test_a_join_to_the_examples_own_room_stops_it_before_it_types(self):
        server = _Server(join_room=EXAMPLE)
        visit, result = self._visit(server)

        self.assertFalse(result.completed)
        self.assertEqual([(s.endpoint, s.kind) for s in result.failures], [("socket join_session", "leaked")])
        self.assertEqual([event for event, _room in server.socket], ["join_session"], "it typed nothing")
        self.assertIsNone(visit.outcome()["project_id"], "the example's room is no copy")
        self.assertFalse(visit.first_ask.is_set(), "it asked nothing")


class TheExampleReaderTest(unittest.TestCase):
    def _reader(self, server, name=FLOW["name"]):
        from utk_curio.backend.tests.stress.guests import ExampleReader

        reader = ExampleReader("http://backend", "e.json", name)
        reader.session = server.session_class()()
        return reader

    def test_the_reader_finds_the_example_and_the_node_its_guests_type_in(self):
        server = _Server()
        job = self._reader(server).open_example()

        self.assertEqual(job, {"example": "e.json", "name": FLOW["name"], "id": EXAMPLE, "node_id": NODE,
                               "codes": CODES})
        self.assertEqual([(path, header) for _method, path, header, _params in server.http], [
            ("/api/auth/signin/guest", None), ("/api/projects", None), (f"/api/projects/{EXAMPLE}", EXAMPLE),
        ])

    def test_an_example_the_gallery_does_not_list_stops_the_stage(self):
        from utk_curio.backend.tests.stress.guests import GuestsError

        with self.assertRaisesRegex(GuestsError, "no dataflow named 'Missing'"):
            self._reader(_Server(), "Missing").open_example()

    def test_after_a_tier_the_example_must_be_as_it_was_and_no_room_shared(self):
        server = _Server()
        reader = self._reader(server)
        reader.open_example()
        self.assertEqual(reader.check([{"guest": "g0", "project_id": COPY}]).failures, [])

        shared = reader.check([{"guest": "g0", "project_id": COPY}, {"guest": "g1", "project_id": COPY}])
        self.assertEqual([(s.endpoint, s.kind) for s in shared.failures], [("guests' rooms", "leaked")])
        self.assertIn("g0, g1 joined one room", shared.failures[0].error)

        server.read_back_adds = "# g3's Node Builder wrote this line\n"
        changed = reader.check([])
        self.assertEqual([(s.endpoint, s.kind) for s in changed.failures], [("the example", "leaked")])
        self.assertIn("# g3's Node Builder wrote this line", changed.failures[0].error)
        self.assertEqual((changed.user, changed.completed), ("the example's reader", False))
        signed_in = [header for _method, path, header, _params in server.http if path == "/api/auth/signin/guest"]
        self.assertEqual(signed_in, [None] * 4, "each check signs in anew, naming no dataflow")


def _outcome(index: int, copy_id: str | None, sync: list, turn: float | None, **changes) -> dict:
    """A guest's outcome (``guests.GuestVisit.outcome``) whose tab joined
    *copy_id*'s room; *changes* replace its fields, its ``copy`` among them."""
    outcome = {
        "room": index, "guest": f"g{index}", "example": "e.json", "example_id": EXAMPLE, "project_id": copy_id,
        "node_id": NODE, "tab": {"transport": "websocket", "role": "owner", "room_id": copy_id},
        "updates": len(sync), "sync_seconds": list(sync),
        "agents": {"turn_seconds": [turn] if turn is not None else [],
                   "phases": {"prepared": [turn / 2]} if turn is not None else {}},
        "turn": {"asked": turn is not None, "end": "done" if turn is not None else None, "seconds": turn,
                 "write": "landed" if turn is not None else "none",
                 "phases": {"prepared": turn / 2} if turn is not None else {}},
        "copy": {"read": True, "not_in_copy": [], "leaked": []},
        "present_at_end": [], "locks_at_end": [],
    }
    outcome.update(changes)
    return outcome


class TheReportTest(unittest.TestCase):
    def test_a_copy_is_on_its_examples_process_today_whatever_its_own_id(self):
        """The one rule: a guest's copy is owned with the example it copies
        (``owner_guard.room_key``), where its page names it. The copy's own id
        falls on process 1 of 8, the example's on 4."""
        from utk_curio.backend.tests.stress.report import copy_process, guests_summary, process_summary

        guests = [_outcome(0, COPY, [0.01], 2.0), _outcome(1, OTHER_COPY, [0.02], 4.0)]
        self.assertEqual([copy_process(guest, 8) for guest in guests], [4, 4])
        self.assertEqual(copy_process(guests[0], 1), 0)
        per_guest = guests_summary(guests, 8)["per_guest"]
        self.assertEqual([(entry["copy_id"], entry["process"]) for entry in per_guest], [(COPY, 4), (OTHER_COPY, 4)])
        block = process_summary(guests, 8, None, process_of=copy_process)
        self.assertEqual([(entry["process"], entry["rooms"]) for entry in block if entry["rooms"]], [(4, [0, 1])])
        self.assertEqual(block[4]["turn_s"]["count"], 2)
        self.assertEqual(block[4]["sync_ms"]["max"], 20.0)
        self.assertEqual(block[4]["phases_s"]["prepared"]["max"], 2.0)
        self.assertEqual(block[1]["rooms"], [], "the copy's own id names no process today")

    def test_the_guests_summary_says_what_they_did_and_what_was_wrong(self):
        from utk_curio.backend.tests.stress.report import guests_summary

        guests = [
            _outcome(0, COPY, [0.010, 0.030], 2.0),
            _outcome(1, OTHER_COPY, [0.020], 6.0, copy={"read": True, "not_in_copy": [], "leaked": ["x"]},
                        present_at_end=["Node Builder"], locks_at_end=[f"{NODE} by Node Builder for g1"]),
            _outcome(2, None, [], None, tab={}, copy=None, present_at_end=None, locks_at_end=None),
        ]
        summary = guests_summary(guests, 8)

        self.assertEqual((summary["guests"], summary["joined"], summary["rooms"]), (3, 2, 2))
        self.assertEqual(summary["examples"], ["e.json"])
        self.assertEqual(summary["transports"], ["websocket"])
        self.assertEqual(summary["updates"], 3)
        self.assertEqual((summary["sync_ms"]["count"], summary["sync_ms"]["max"]), (3, 30.0))
        self.assertEqual(summary["asked"], 2)
        self.assertEqual(summary["ends"], {"done": 2, "error": 0, "withdrawn": 0, "never": 0})
        self.assertEqual((summary["turn_s"]["p50"], summary["turn_s"]["max"]), (2.0, 6.0))
        self.assertEqual(summary["phases_s"]["prepared"]["max"], 3.0)
        self.assertIsNone(summary["phases_s"]["written"])
        self.assertEqual(summary["writes"]["landed"], 2)
        self.assertEqual(summary["copies"], {"read": 2, "not_in_copy": 0, "leaked": 1})
        self.assertEqual((summary["present_at_end"], summary["locks_at_end"], summary["rooms_read"]), (1, 1, 2))
        self.assertIsNone(summary["per_guest"][2]["process"], "a guest that joined no room has no copy")
        self.assertIsNone(guests_summary([], 8))

    def test_the_readers_checks_fail_the_tier_and_are_no_user_of_it(self):
        from utk_curio.backend.tests.stress.driver import Sample, UserResult
        from utk_curio.backend.tests.stress.report import tier_summary

        guest = UserResult(user="g0", example="e.json", started_at=0.0, completed=True)
        reader = UserResult(user="the example's reader", example="e.json", started_at=0.0)
        reader.samples.append(Sample("the example", None, 200, 0.0, False, "the example held work", "leaked"))
        tier = tier_summary(1, [guest], 1.0, "burst", checks=[reader])

        self.assertEqual((tier["users"], tier["completed"]), (1, 1))
        self.assertEqual(tier["failure_count"], 1)
        self.assertEqual(tier["failures_by_kind"], {"leaked": 1})
        self.assertEqual(tier["failures"][0]["user"], "the example's reader")
        self.assertEqual(tier_summary(1, [guest], 1.0)["failure_count"], 0)

    def test_the_summary_has_the_guests_table_their_turns_and_each_copys_process(self):
        from utk_curio.backend.tests.stress.report import (
            copy_process, guests_summary, markdown, process_summary, tier_summary,
        )

        guests = [_outcome(0, COPY, [0.01], 2.0), _outcome(1, OTHER_COPY, [0.02], 4.0)]
        tier = tier_summary(2, [], 1.0, "burst")
        tier["guests"] = guests_summary(guests, 8)
        tier["processes"] = process_summary(guests, 8, None, process_of=copy_process)
        text = markdown({"run_id": "x", "backend_url": "u", "profile": "burst", "tiers": [tier], "failed": False,
                         "backend_processes": 8})

        self.assertIn("hosted guests on one example", text)
        self.assertIn("| Tier | Guests | Rooms | Updates | Sync p50 |", text)
        self.assertIn("| 2 | 2 | 2 | 2 | 10.0 ms | 20.0 ms | 20.0 ms | 2 | 2 | 2.0 s | 4.0 s | 4.0 s | 2 | 2 of 2 "
                      "| 0 | 0 | 0 agent(s), 0 lock(s) |", text)
        self.assertIn("| Tier | Prepared p50 |", text, "the turns phase by phase")
        self.assertIn(f"- `g0`: copy `{COPY}` on process 4", text)
        self.assertIn(f"- `g1`: copy `{OTHER_COPY}` on process 4", text)
        self.assertIn("| 2 | 4 | 2 |", text, "process 4 holds both copies")
        self.assertIn("each hosted guest's copy is a room of its own", text)


class _StacksProbe:
    """The probe, standing in for a stack of one backend process that dumps
    its threads' stacks when asked."""

    command = ["python"]
    timeout = 1.0
    DUMP = "=== thread stacks of pid 7 at 2026-11-16T23:30:00Z: 2 thread(s) ===\n"

    def __init__(self):
        self.stacks_asked = 0

    def read(self, project_ids=()):
        return {"pid": 7, "threads": 2, "rss_bytes": 1, "cpu_seconds": 0.0, "count": 1}

    def thread_stacks(self):
        self.stacks_asked += 1
        return {"pid": 7, "path": "/app/.curio/backend-thread-stacks.txt", "stacks": self.DUMP}


class TheStacksDuringTheTurnsTest(unittest.TestCase):
    """A guests tier asks every backend process for its thread stacks once,
    a while after its first agent turn was asked, while the turns run: the
    stacks a failed tier saves come once its work is over."""

    def test_they_are_read_once_a_while_after_the_first_ask(self):
        from utk_curio.backend.tests.stress.run import watch_turns

        first_ask, over, called = threading.Event(), threading.Event(), []
        started = time.monotonic()
        threading.Timer(0.05, first_ask.set).start()
        watch_turns(first_ask, over, 0.2, lambda: called.append(time.monotonic() - started))
        self.assertEqual(len(called), 1)
        self.assertGreaterEqual(called[0], 0.2, "not before its while after the first ask")

    def test_a_tier_over_before_then_or_never_asked_reads_none(self):
        from utk_curio.backend.tests.stress.run import watch_turns

        called = []
        first_ask, over = threading.Event(), threading.Event()
        first_ask.set()
        threading.Timer(0.05, over.set).start()
        watch_turns(first_ask, over, 30.0, lambda: called.append("over first"))
        never, done = threading.Event(), threading.Event()
        done.set()
        watch_turns(never, done, 0.0, lambda: called.append("never asked"))
        self.assertEqual(called, [])

    def _main(self, out_dir: str, probe) -> int:
        """``run.main`` on one guests tier of 5, the stack and the tier stood
        in for: the tier calls what it is to call during its turns, as
        ``run_tier`` does once its first ask is a while old."""
        from types import SimpleNamespace

        from utk_curio.backend.tests.stress import run
        from utk_curio.backend.tests.stress.driver import UserResult
        from utk_curio.backend.tests.stress.guests import READER

        class Reader:
            def __init__(self, backend_url, example, name):
                self.example = example

            def open_example(self):
                return _job()

            def check(self, outcomes):
                return UserResult(user=READER, example=self.example, started_at=0.0, completed=True)

        def run_tier(*_args, during_turns=None, **_kwargs):
            if during_turns is not None:
                during_turns()
            guest = UserResult(user="g0", example="e.json", started_at=0.0, seconds=1.0, completed=True)
            return [guest], 1.0, [_outcome(0, COPY, [0.01], 2.0)]

        example = SimpleNamespace(relpath="e.json", spec_json={"dataflow": {"name": FLOW["name"]}})
        environ = {key: value for key, value in os.environ.items() if key != "GITHUB_STEP_SUMMARY"}
        with contextlib.ExitStack() as stack:
            for patch in (
                mock.patch.object(run, "make_probe", lambda args: probe),
                mock.patch.object(run, "wait_for_backend", lambda *args, **kwargs: None),
                mock.patch.object(run, "read_namespace", lambda url: "/collab"),
                mock.patch.object(run.sockets, "require_websocket_client", lambda: None),
                mock.patch.object(run, "load_mix", lambda names: [example]),
                mock.patch.object(run, "ExampleReader", Reader),
                mock.patch.object(run, "on_the_scripted_model", lambda url, tier: tier()),
                mock.patch.object(run, "read_exec_lock", lambda url: None),
                mock.patch.object(run, "run_tier", run_tier),
                mock.patch.object(run, "PROBE_END_WAIT_S", 0.0),
                mock.patch.dict(os.environ, environ, clear=True),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                stack.enter_context(patch)
            return run.main(["--tiers", "5", "--guests", "--out", out_dir])

    def test_a_guests_tier_saves_them_in_its_report_folder_and_names_them(self):
        probe = _StacksProbe()
        with tempfile.TemporaryDirectory() as out_dir:
            self.assertEqual(self._main(out_dir, probe), 0)

            self.assertEqual(probe.stacks_asked, 1, "once, during the turns; a clean tier saves none after it")
            saved = Path(out_dir, "thread-stacks-tier-1-5-during-turns.txt")
            self.assertTrue(saved.read_text(encoding="utf-8").endswith(_StacksProbe.DUMP))
            report = json.loads(Path(out_dir, "report.json").read_text(encoding="utf-8"))
            stacks = report["tiers"][0]["stacks_during_turns"]
            self.assertEqual((stacks["file"], stacks["after_s"]), (saved.name, 30.0))
            self.assertIn(f"`{saved.name}`", Path(out_dir, "summary.md").read_text(encoding="utf-8"))

    def test_with_the_probe_off_the_report_says_none_were_saved(self):
        with tempfile.TemporaryDirectory() as out_dir:
            self.assertEqual(self._main(out_dir, None), 0)

            self.assertEqual(list(Path(out_dir).glob("thread-stacks-*")), [])
            report = json.loads(Path(out_dir, "report.json").read_text(encoding="utf-8"))
            stacks = report["tiers"][0]["stacks_during_turns"]
            self.assertIsNone(stacks["file"])
            self.assertIn("the probe is off (--no-probe)", stacks["line"])


class TheCommandLineTest(unittest.TestCase):
    def test_guests_takes_no_shared_canvas_or_agents(self):
        import contextlib
        import io

        from utk_curio.backend.tests.stress.run import main

        for extra in (["--shared-canvas"], ["--agents"], ["--shared-canvas", "--agents"]):
            with self.subTest(extra=extra), contextlib.redirect_stderr(io.StringIO()) as said:
                with self.assertRaises(SystemExit):
                    main(["--tiers", "1", "--guests", *extra])
                self.assertIn("so it takes no --shared-canvas or --agents", said.getvalue())

    def test_guests_with_no_example_opens_the_mixs_first(self):
        import argparse

        from utk_curio.backend.tests.stress import run

        seen = {}

        def stop(args_self, argv=None, namespace=None):
            seen["args"] = original(args_self, argv, namespace)
            raise SystemExit(0)

        original = argparse.ArgumentParser.parse_args
        with mock.patch.object(argparse.ArgumentParser, "parse_args", stop):
            for argv, example in ((["--guests"], run.DEFAULT_MIX[0]), (["--guests", "x.json"], "x.json"), ([], None)):
                with self.subTest(argv=argv):
                    with self.assertRaises(SystemExit):
                        run.main(argv)
                    self.assertEqual(seen["args"].guests, example)


if __name__ == "__main__":
    unittest.main()
