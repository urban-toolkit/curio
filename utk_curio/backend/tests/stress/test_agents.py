"""The members' agents on a shared canvas (``--agents``, ``agents.py``), with no server.

* The reply script per member: its own attachment's queue, never a reset, a
  write the server reads as the tool request, and code that keeps the node's.
* A turn's outcome as failures: a write landed is one timed sample; a refusal
  because the node changed meanwhile is its own kind, naming the node and the
  asker; an error, no end, no write or any other refusal fails the turn; a
  turn over before its follow began is read from the ask's snapshot.
* The member's whole agent work over HTTP, on a stand-in session.
* A tab's view of the agents: the asks it was told the end of, the agents in
  the room, a node's code, and the room as a joining tab is told of it.
* A room's agents: who asks when, the owner's wait before its run, the save,
  and the checks once the room's work is over.
* The turns section of the report, the new failure kinds, the scripted
  model made Curio's default for the tier and put back, and ``--agents``.

Two turns at once on the server, each on its own attachment's replies, is
``test_agents/test_stress_agent_turns.py``. Names are imported in each test,
so a checkout without them fails test by test.
"""

import json
import threading
import unittest
from types import SimpleNamespace
from unittest import mock

_NODE = "5b1d1e8a-2f4a-4c55-9d0e-1a2b3c4d5e6f"


def _envelope(seq, event, data=None):
    return {"projectId": "p", "attachmentId": "att", "askId": "a" * 32, "seq": seq, "event": event,
            "data": data or {}}


def _landed(seq=4):
    return _envelope(seq, "tool_result", {"tool": "node.content.write", "status": "applied"})


def _done(seq=6):
    return _envelope(seq, "done", {"reply": "Done."})


class _User:
    """What a member's agent work records on: its result's samples."""

    def __init__(self, name="u1"):
        from utk_curio.backend.tests.stress.driver import UserResult

        self.name = name
        self.result = UserResult(user=name, example="e.json", started_at=0.0)

    def socket_sample(self, label, seconds, ok, error=None, kind=None):
        from utk_curio.backend.tests.stress.driver import Sample

        self.result.samples.append(Sample(label, None, None, seconds, ok, error, kind))

    def _fail(self, endpoint, node_id, message, kind):
        from utk_curio.backend.tests.stress.driver import Sample

        self.result.samples.append(Sample(endpoint, node_id, 200, 0.0, False, message, kind))


def _turn(*envelopes, asked=True):
    import time

    from utk_curio.backend.tests.stress.agents import MemberTurn

    turn = MemberTurn("u1", _NODE, "# u1's Node Builder wrote this line\nreturn input_0", early=True)
    turn.asked = asked
    turn.asked_at = time.perf_counter() if asked else None
    for envelope in envelopes:
        turn.take(envelope)
    return turn


def _judged(*envelopes, asked=True):
    turn = _turn(*envelopes, asked=asked)
    user = _User()
    turn.judge(user)
    return turn, [(s.endpoint, s.node_id, s.ok, s.kind, s.error) for s in user.result.samples]


class TheReplyScriptTest(unittest.TestCase):
    def test_each_member_queues_its_own_attachments_replies_and_never_resets(self):
        """``reset`` on would drop the other 99 members' queues: it is off,
        and every reply is one the testing route takes."""
        from utk_curio.backend.app.testing.routes import _reply_entry_error
        from utk_curio.backend.tests.stress.agents import DONE_REPLY, script_body, write_reply

        body = script_body("att-1", _NODE, "return input_0")
        self.assertIs(body["reset"], False)
        self.assertEqual(body["attachmentId"], "att-1")
        self.assertEqual(body["replies"], [write_reply(_NODE, "return input_0"), DONE_REPLY])
        self.assertEqual([_reply_entry_error(reply) for reply in body["replies"]], [None, None])
        self.assertNotIn("```", DONE_REPLY, "the last reply asks for nothing")

    def test_the_write_is_the_tool_request_the_server_reads(self):
        from utk_curio.backend.app.agents.domain import content
        from utk_curio.backend.tests.stress.agents import WRITE_TOOL, agent_content, write_reply

        code = agent_content("u1", "return input_0")
        visible, parts = content.extract_content(write_reply(_NODE, code))
        self.assertEqual(visible, "")
        self.assertEqual(parts, [{"type": "toolRequest", "tool": WRITE_TOOL,
                                  "params": {"nodeId": _NODE, "content": code}}])

    def test_the_agent_puts_its_line_on_top_of_the_code_it_was_handed_as_the_server_keeps_it(self):
        """A pass-through still, and a room's typed lines stay; stripped, so
        a tab and the save hold it as it is."""
        from utk_curio.backend.app.agents.domain import content
        from utk_curio.backend.tests.stress.agents import AGENT_LINE, agent_content
        from utk_curio.backend.tests.stress.sockets import PASS_ON_CODE

        typed = "# u0 typed this line\n# u1 typed this line\n# u0 typed this line\n# u1 typed this line\n"
        code = agent_content("u0", typed + PASS_ON_CODE)
        self.assertEqual(code, AGENT_LINE.format(member="u0") + "\n" + typed + PASS_ON_CODE)
        self.assertEqual(content.extract_node_content(code), code)
        self.assertEqual(agent_content("u0", None), AGENT_LINE.format(member="u0") + "\n" + PASS_ON_CODE)
        self.assertEqual(agent_content("u0", "  \n"), agent_content("u0", None))


class ATurnsOutcomeTest(unittest.TestCase):
    def test_a_turn_that_ends_done_with_its_write_landed_is_one_timed_sample(self):
        turn, samples = _judged(_envelope(1, "execution"), _envelope(2, "tool_requested", {"tool": "node.content.write"}),
                                _envelope(3, "tool_started"), _landed(), _envelope(5, "change"), _done())
        self.assertEqual(samples, [("agent turn", _NODE, True, None, None)])
        self.assertTrue(turn.landed)
        self.assertEqual((turn.end, turn.events), ("done", 6))
        self.assertIsNotNone(turn.seconds)

    def test_a_write_refused_as_changed_meanwhile_is_its_own_kind_naming_the_node_and_the_asker(self):
        from utk_curio.backend.tests.stress.agents import changed_meanwhile

        refused = _envelope(4, "tool_result", {"tool": "node.content.write", "status": "refused",
                                               "reason": changed_meanwhile(_NODE)})
        turn, samples = _judged(refused, _done())
        [(label, node_id, ok, kind, error)] = samples
        self.assertEqual((label, node_id, ok, kind), ("agent turn", _NODE, False, "changed_meanwhile"))
        self.assertIn(_NODE, error)
        self.assertIn("asked by u1", error)
        self.assertEqual(turn.outcome()["write"], "changed_meanwhile")

    def test_any_other_refusal_or_no_write_fails_the_turn(self):
        refused = _envelope(4, "tool_result", {"tool": "node.content.write", "status": "refused",
                                               "reason": "Ana is editing a node this change touches"})
        turn, samples = _judged(refused, _done())
        [(_label, _node, ok, kind, error)] = samples
        self.assertEqual((ok, kind), (False, "agent_turn"))
        self.assertIn("did not land (refused): Ana is editing", error)
        self.assertEqual(turn.outcome()["write"], "refused")

        turn, samples = _judged(_envelope(1, "tool_result", {"tool": "dataflow.read", "status": "ok"}), _done())
        [(_label, _node, ok, kind, error)] = samples
        self.assertEqual((ok, kind), (False, "agent_turn"))
        self.assertIn("ended done without writing it", error)
        self.assertEqual(turn.outcome()["write"], "none")

    def test_a_turn_that_ends_in_an_error_or_never_ends_fails(self):
        _turn_, samples = _judged(_envelope(1, "error", {"error": "agent run failed: boom"}))
        [(_label, _node, ok, kind, error)] = samples
        self.assertEqual((ok, kind), (False, "agent_turn"))
        self.assertIn("ended error: agent run failed: boom", error)

        turn, samples = _judged(_landed())
        [(_label, _node, ok, kind, error)] = samples
        self.assertEqual((ok, kind), (False, "agent_turn"))
        self.assertIn("never ended", error)
        self.assertEqual(turn.outcome()["end"], None)

    def test_a_turn_over_before_its_follow_began_is_read_from_the_asks_snapshot(self):
        """Its kept events hold its whole turn; a follow again replays them
        and counts none twice."""
        view = {"askId": "a" * 32, "state": "ended",
                "events": [{"seq": 1, "event": "execution", "data": {}},
                           {"seq": 4, "event": "tool_result", "data": {"tool": "node.content.write",
                                                                         "status": "applied"}},
                           {"seq": 6, "event": "done", "data": {}}]}
        turn, samples = _judged(_envelope(6, "snapshot", view), _envelope(6, "snapshot", view), _done())
        self.assertEqual(samples, [("agent turn", _NODE, True, None, None)])
        self.assertEqual(turn.events, 3)

    def test_a_turn_never_asked_is_judged_where_it_failed(self):
        _turn_, samples = _judged(_done(), asked=False)
        self.assertEqual(samples, [])

    def test_a_follows_lines_are_read_as_room_envelopes(self):
        from utk_curio.backend.tests.stress.agents import turn_envelopes

        lines = ["event: turn", "data: " + json.dumps(_landed()), "", ": a comment",
                 "event: other", "data: " + json.dumps(_done()), "event: turn", "data: {not json",
                 "event: turn", "data: " + json.dumps(_done())]
        self.assertEqual(turn_envelopes(lines), [_landed(), _done()])


class _Response:
    def __init__(self, status, body=None, lines=()):
        self.status_code = status
        self._body = body
        self.lines = list(lines)
        self.text = json.dumps(body) if body is not None else ""
        self.content = self.text.encode("utf-8")
        self.encoding = None

    def json(self):
        return self._body

    def iter_lines(self, decode_unicode=False):
        return iter(self.lines)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _Session:
    """A member's agent session's stand-in: each call kept, each answered
    as the server answers a turn whose write landed."""

    calls: list = []

    def __init__(self):
        self.closed = False

    def request(self, method, url, json=None, headers=None, timeout=None):
        _Session.calls.append((method, url, json, (headers or {}).get("Authorization")))
        if url.endswith("/attachments"):
            return _Response(201, {"attachmentId": "att-9"})
        if url.endswith("/agent-script"):
            return _Response(200, {"pending": 2})
        return _Response(202, {"askId": json["askId"], "attachmentId": "att-9", "state": "running"})

    def get(self, url, headers=None, stream=False, timeout=None):
        import json as json_module

        _Session.calls.append(("GET", url, None, (headers or {}).get("Authorization")))
        return _Response(200, lines=["event: turn", "data: " + json_module.dumps(_landed()),
                                     "event: turn", "data: " + json_module.dumps(_done())])

    def post(self, url, headers=None, timeout=None):
        _Session.calls.append(("POST", url, None, None))
        return _Response(200, {})

    def close(self):
        self.closed = True


class AMembersAgentWorkTest(unittest.TestCase):
    def test_it_attaches_scripts_asks_and_follows_its_own_turn(self):
        """As the owner's editor would through its chat: the agent attached
        to the member's node, its replies queued for that attachment alone,
        the ask under the id it chose, followed to its end."""
        from utk_curio.backend.tests.stress import agents
        from utk_curio.backend.tests.stress.driver import VirtualUser

        user = VirtualUser("http://backend", "u1", "e.json", {}, None, {})
        user.token, user.room = "tok", SimpleNamespace(project_id="p1")
        turn = agents.MemberTurn("u1", _NODE, "# line\nreturn input_0", early=False)
        told = []
        _Session.calls = []
        with mock.patch.object(agents.requests, "Session", _Session):
            turn.run(user, told.append)
        base = "http://backend/api/agents/projects/p1"
        self.assertEqual([(method, url) for method, url, _body, _auth in _Session.calls], [
            ("POST", f"{base}/attachments"),
            ("POST", "http://backend/api/testing/agent-script"),
            ("POST", f"{base}/attachments/att-9/turns"),
            ("GET", f"{base}/attachments/att-9/turns/{turn.ask_id}/stream"),
        ])
        bodies = [body for _method, _url, body, _auth in _Session.calls]
        self.assertEqual(bodies[0], {"coord": agents.COORD, "target": {"kind": "node", "targetId": _NODE}})
        self.assertEqual(bodies[1], agents.script_body("att-9", _NODE, "# line\nreturn input_0"))
        self.assertEqual(bodies[2], {"message": agents.MESSAGE, "askId": turn.ask_id})
        self.assertEqual({auth for _method, _url, _body, auth in _Session.calls}, {"Bearer tok"})
        self.assertTrue(turn.asked and turn.landed and turn.over.is_set())
        self.assertEqual(told, [turn])
        self.assertEqual([(s.endpoint, s.ok) for s in user.result.samples], [
            ("/api/agents/projects/:id/attachments", True), ("/api/testing/agent-script", True),
            ("/api/agents/projects/:id/attachments/:id/turns", True),
            ("/api/agents/projects/:id/attachments/:id/turns/:id/stream", True), ("agent turn", True),
        ])

    def test_a_refused_attach_is_its_failure_and_nothing_is_asked(self):
        from utk_curio.backend.tests.stress import agents
        from utk_curio.backend.tests.stress.driver import VirtualUser

        class Refusing(_Session):
            def request(self, method, url, json=None, headers=None, timeout=None):
                _Session.calls.append((method, url, json, None))
                return _Response(400, {"error": "install the agent in this project before attaching it"})

        user = VirtualUser("http://backend", "u1", "e.json", {}, None, {})
        user.room = SimpleNamespace(project_id="p1")
        turn = agents.MemberTurn("u1", _NODE, "x", early=True)
        _Session.calls = []
        with mock.patch.object(agents.requests, "Session", Refusing):
            turn.run(user)
        self.assertEqual(len(_Session.calls), 1)
        [failure] = user.result.failures
        self.assertEqual((failure.endpoint, failure.status, failure.kind),
                         ("/api/agents/projects/:id/attachments", 400, "http_error"))
        self.assertFalse(turn.asked)
        self.assertTrue(turn.over.is_set())


#: A dataflow of two nodes, as a room's doc starts.
_FLOW = {
    "nodes": [
        {"id": "loader", "type": "curio.builtin/python-computation", "x": 10, "y": 20, "content": "x = 1\n"},
        {"id": _NODE, "type": "curio.builtin/python-computation", "x": 300, "y": 20, "content": "return input_0"},
    ],
    "edges": [{"id": "e1", "source": "loader", "target": _NODE}],
    "name": "Shared",
}


class _Link:
    def __init__(self, answers=()):
        self.calls = []
        self.answers = list(answers)

    def emit(self, event, data, callback=None):
        if callback is not None:
            callback({"ok": True})

    def call(self, event, data, _timeout):
        self.calls.append((event, data))
        return self.answers.pop(0)


def _tab(name="a", answers=()):
    """*name*'s tab holding :data:`_FLOW` as the server sent it, and the
    server's doc, on a stand-in socket."""
    from pycrdt import create_update_message

    from utk_curio.backend.app.collaboration import doc_mapping
    from utk_curio.backend.tests.stress.sockets import SyncLedger, Tab

    tab = Tab(name, "p", SyncLedger(), lambda *args, **kwargs: None)
    server = doc_mapping.new_doc()
    doc_mapping.dataflow_to_doc(_FLOW, server, doc_id="d")
    tab.receive({"projectId": "p", "message": create_update_message(server.get_update())})
    tab.link = _Link(answers)
    return tab, server


def _server_writes(tab, server, node_id, code):
    """The server's doc takes *code* in *node_id*, as an agent's write does,
    and relays the change to *tab*."""
    from pycrdt import create_update_message

    from utk_curio.backend.app.collaboration import doc_mapping
    from utk_curio.backend.tests.stress.sockets import CODE_KEY

    before = server.get_state()
    base = doc_mapping.doc_to_dataflow(server)
    target = {**base, "nodes": [{**node, CODE_KEY: code} if node["id"] == node_id else node
                                for node in base["nodes"]]}
    doc_mapping.apply_dataflow(server, base, target)
    tab.receive({"projectId": "p", "message": create_update_message(server.get_update(before))})


class ATabsViewOfTheAgentsTest(unittest.TestCase):
    def test_a_tab_keeps_the_asks_it_was_told_the_end_of(self):
        tab, _ = _tab()
        tab.room_event("agent_turn", {**_envelope(1, "started"), "askId": "a1"})
        tab.room_event("agent_turn", {**_envelope(2, "done"), "askId": "a1"})
        tab.room_event("agent_turn", {**_envelope(1, "error"), "askId": "a3"})
        tab.room_event("agent_turn", {"nodeId": "loader"})
        self.assertEqual(tab.agent_events, 3, "an event that names no ask is no ask's")
        self.assertEqual(tab.wait_told_ends(["a1", "a2", "a3"], 0.01), ["a2"])
        self.assertEqual(tab.asks_untold, ["a2"])
        self.assertEqual(tab.room_locks(), {})

    def test_a_tab_keeps_the_agents_in_the_room_from_their_join_and_leave(self):
        tab, _ = _tab()
        agent = {"participant_id": "agent-1", "user_id": None, "name": "Node Builder",
                 "agent": {"attachmentId": "att", "coord": "agent.curio.node-builder@1"}}
        tab.room_event("agent_joined", agent)
        tab.room_event("agent_joined", {"participant_id": "p2", "name": "Ana"})
        self.assertEqual(tab.wait_for_no_agents(0.01), {"agent-1": "Node Builder"})
        self.assertEqual(tab.agents_shown, ["Node Builder"])
        threading.Timer(0.05, tab.room_event, args=("agent_left", {**agent, "did": {}})).start()
        self.assertEqual(tab.wait_for_no_agents(5), {}, "the wait ends once the agent leaves")
        self.assertEqual((tab.agents_joined, tab.agents_left, tab.agents_shown), (1, 1, []))
        summary = tab.summary()
        self.assertEqual((summary["agents_joined"], summary["agents_left"], summary["agents_shown"]), (1, 1, []))

    def test_a_tab_reads_a_nodes_code_and_waits_for_a_write_to_reach_it(self):
        tab, server = _tab()
        self.assertEqual(tab.code_of("loader"), "x = 1\n")
        self.assertIsNone(tab.code_of("no-such-node"))
        self.assertEqual(tab.wait_for_code({_NODE: "# line\nreturn input_0"}, 0.01), {_NODE: "return input_0"})
        threading.Timer(0.05, _server_writes, args=(tab, server, _NODE, "# line\nreturn input_0")).start()
        self.assertEqual(tab.wait_for_code({_NODE: "# line\nreturn input_0"}, 5), {})
        self.assertEqual(tab.code_of(_NODE), "# line\nreturn input_0")

    def test_the_room_as_a_joining_tab_is_told_of_it(self):
        from utk_curio.backend.tests.stress.agents import present_in

        activity = [
            {"kind": "user_joined", "payload": {"participant_id": "p1"}},
            {"kind": "agent_joined", "payload": {"participant_id": "agent-1", "name": "Node Builder"}},
            {"kind": "agent_joined", "payload": {"participant_id": "agent-2", "name": "Node Builder"}},
            {"kind": "agent_left", "payload": {"participant_id": "agent-1", "name": "Node Builder", "did": {}}},
            "not an entry",
        ]
        tab, _ = _tab(answers=[{"ok": True, "snapshot": {"locks": {}, "activity": activity}}])
        room = tab.server_room()
        self.assertEqual(tab.link.calls, [("join_session", {"projectId": "p"})])
        self.assertEqual(present_in(room["activity"]), {"agent-2": "Node Builder"})
        self.assertEqual(present_in(None), {})


class _Member:
    """A member of a room as its agents read it: its name, its node, its
    result."""

    def __init__(self, name, node_id=None):
        from utk_curio.backend.tests.stress.driver import UserResult

        self.name = name
        self.own_node = {"id": node_id} if node_id else None
        self.result = UserResult(user=name, example="e.json", started_at=0.0)

    def socket_sample(self, label, seconds, ok, error=None, kind=None):
        from utk_curio.backend.tests.stress.driver import Sample

        self.result.samples.append(Sample(label, None, None, seconds, ok, error, kind))

    def _fail(self, endpoint, node_id, message, kind):
        from utk_curio.backend.tests.stress.driver import Sample

        self.result.samples.append(Sample(endpoint, node_id, 200, 0.0, False, message, kind))

    def failures(self):
        return [(s.endpoint, s.kind, s.error) for s in self.result.samples if not s.ok]


def _room(members, *, targets=()):
    from utk_curio.backend.tests.stress.agents import RoomAgents
    from utk_curio.backend.tests.stress.sockets import Room

    room = Room(0, list(members), shared=True)
    room.targets = list(targets)
    room.agents = RoomAgents(room)
    return room


class _Held:
    """A member's agent work's stand-in: over when the test says so, with
    the turn as it would have ended."""

    def __init__(self):
        self.go = threading.Event()
        self.started = []

    def run(self, turn, user, on_over=lambda turn: None):
        self.started.append(turn)
        self.go.wait(5)
        turn.asked, turn.end, turn.write = True, "done", "applied"
        turn.over.set()
        on_over(turn)


class TheRoomsAgentsTest(unittest.TestCase):
    def _started(self, room, *members):
        from utk_curio.backend.tests.stress import agents

        held = _Held()
        tab, _ = _tab()
        with mock.patch.object(agents.MemberTurn, "run", lambda turn, user, on_over: held.run(turn, user, on_over)):
            for member in members:
                room.agents.ask_early(member, tab)
                room.agents.ask_late(member, tab)
            for _ in range(100):
                if len(held.started) == sum(1 for m in members if m.own_node):
                    break
                threading.Event().wait(0.01)
        return held

    def test_members_ask_as_their_node_is_in_where_people_type_in_a_code_node_else_once_they_play(self):
        """Where people type in the example's code node, nobody types in a
        member's node: the agents work while people type. Elsewhere they
        type in the members' own nodes, so the members ask once the typing
        is over, as they play."""
        from utk_curio.backend.tests.stress.agents import agent_content

        coded = _room(["u0", "u1"], targets=[("loader", "# ")])
        self.assertTrue(coded.agents.early)
        member = _Member("u0", _NODE)
        held = self._started(coded, member)
        [turn] = held.started
        self.assertTrue(turn.early)
        self.assertEqual(turn.content, agent_content("u0", "return input_0"), "the code its tab holds, under its line")
        held.go.set()

        pairs = _room(["u0", "u1"])
        self.assertFalse(pairs.agents.early)
        held = self._started(pairs, _Member("u0", _NODE), _Member("u1"))
        self.assertEqual([turn.early for turn in held.started], [False])
        self.assertEqual(pairs.agents.skipped, {"u1"}, "a member with no node of its own asks nothing")
        held.go.set()

    def test_the_owner_runs_the_dataflow_only_once_every_members_turn_is_over(self):
        room = _room(["u0", "u1", "u2", "u3"])
        members = [_Member("u0", "n0"), _Member("u1", "n1"), _Member("u2")]
        held = self._started(room, *members)
        room.leave("u3")  # gone before it asked: nobody waits for it
        ran = threading.Event()
        owner = threading.Thread(target=lambda: (room.agents.before_the_run(members[0]), ran.set()))
        owner.start()
        self.assertFalse(ran.wait(0.3), "the owner ran while two turns were still going")
        held.go.set()
        self.assertTrue(ran.wait(5), "the owner never ran once every turn was over")
        owner.join(5)
        self.assertEqual(members[0].failures(), [])

    def test_a_save_must_hold_each_landed_agents_code_as_it_is(self):
        from utk_curio.backend.tests.stress.agents import MemberTurn

        room = _room(["u0", "u1", "u2"])
        for member, node_id, write in (("u0", "n0", "applied"), ("u1", "n1", "applied"), ("u2", "n2", "refused")):
            turn = MemberTurn(member, node_id, f"# {member}\nreturn input_0", early=False)
            turn.write = write
            room.agents.turns[member] = turn
        saved = {"nodes": {"n0": "# u0\nreturn input_0", "n1": "return input_0", "n2": "return input_0"}}
        self.assertEqual(room.agents.saved_lacks(saved), ["u1's agent's code in node n1"])
        self.assertEqual(room.agents.saved_lacks({"nodes": {}}),
                         ["u0's agent's code in node n0", "u1's agent's code in node n1"])

    def _at_the_end(self, room, members, tabs):
        threads = [threading.Thread(target=room.agents.at_the_end, args=(member, tab))
                   for member, tab in zip(members, tabs)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(10)

    def test_once_the_work_is_over_each_tab_holds_every_write_shows_no_agent_and_was_told_every_end(self):
        """The server's room, read once for the room by its first tab there,
        and each tab's own view; a write a tab lacks is said once, however
        often it is looked for."""
        from unittest import mock as mocking

        from utk_curio.backend.tests.stress import sockets
        from utk_curio.backend.tests.stress.agents import MemberTurn

        room = _room(["u0", "u1"])
        turn = MemberTurn("u0", _NODE, "# u0\nreturn input_0", early=False)
        turn.asked, turn.end, turn.write = True, "done", "applied"
        turn.over.set()
        room.agents.turns["u0"] = turn
        snapshot = {"ok": True, "snapshot": {"activity": [
            {"kind": "agent_joined", "payload": {"participant_id": "agent-9", "name": "Node Builder"}}]}}
        members = [_Member("u0", _NODE), _Member("u1")]
        holding, server = _tab("u0", answers=[snapshot, snapshot])
        lacking, _lacking_server = _tab("u1", answers=[snapshot, snapshot])
        _server_writes(holding, server, _NODE, "# u0\nreturn input_0")
        holding.room_event("agent_turn", {**_envelope(9, "done"), "askId": turn.ask_id})
        lacking.room_event("agent_joined", {"participant_id": "agent-9", "name": "Node Builder", "agent": {}})
        with mocking.patch.object(sockets, "SETTLE_TIMEOUT_S", 0.05):
            self._at_the_end(room, members, [holding, lacking])
            room.agents._writes_in_tab(members[1], lacking)
        self.assertEqual(len(holding.link.calls) + len(lacking.link.calls), 1,
                         "the room's first tab there reads the server's room, once")
        self.assertEqual(room.agents.present_at_end, ["Node Builder"])
        kinds = sorted(kind for member in members for _label, kind, _error in member.failures())
        self.assertEqual(kinds, ["agent_present", "agent_present", "agent_unsynced", "agent_unsynced",
                                 "diverged"])
        lacked = [error for _label, kind, error in members[1].failures() if kind == "agent_unsynced"]
        self.assertEqual(len([e for e in lacked if "write of node" in e]), 1, "a lacking write is said once")
        self.assertTrue(any(f"never told that u0's agent's turn ({turn.ask_id}) ended" in e for e in lacked))
        self.assertIn("diverged", [kind for _label, kind, _error in members[1].failures()],
                      "u1's tab differs from u0's, the room's first")
        outcome = room.agents.outcome([holding.summary(), lacking.summary()])
        self.assertEqual((outcome["unsynced"], outcome["tabs_showing_agents"], outcome["diverged"]), (2, 1, True))

    def test_a_room_whose_agents_did_their_work_is_no_failure_and_its_outcome_counts_its_turns(self):
        from unittest import mock as mocking

        from utk_curio.backend.tests.stress import sockets
        from utk_curio.backend.tests.stress.agents import MemberTurn, changed_meanwhile

        room = _room(["u0", "u1"], targets=[("loader", "# ")])
        tabs = []
        for member, node_id in (("u0", _NODE), ("u1", "loader")):
            turn = MemberTurn(member, node_id, f"# {member}", early=True)
            turn.asked, turn.end, turn.seconds = True, "done", 1.5
            turn.write = "applied" if member == "u0" else "refused"
            turn.reason = None if member == "u0" else changed_meanwhile("loader")
            turn.over.set()
            room.agents.turns[member] = turn
        for name in ("u0", "u1"):
            tab, server = _tab(name, answers=[{"ok": True, "snapshot": {"activity": []}}])
            _server_writes(tab, server, _NODE, "# u0")
            for turn in room.agents.turns.values():
                tab.room_event("agent_turn", {**_envelope(9, "done"), "askId": turn.ask_id})
            tabs.append(tab)
        members = [_Member("u0", _NODE), _Member("u1", "loader")]
        with mocking.patch.object(sockets, "SETTLE_TIMEOUT_S", 0.05):
            self._at_the_end(room, members, tabs)
        self.assertEqual([member.failures() for member in members], [[], []])
        outcome = room.agents.outcome([tab.summary() for tab in tabs])
        self.assertEqual((outcome["early"], outcome["asked"], outcome["present_at_end"]), (True, 2, []))
        self.assertEqual(outcome["ends"], {"done": 2, "error": 0, "withdrawn": 0, "never": 0})
        self.assertEqual(outcome["writes"], {"landed": 1, "changed_meanwhile": 1, "refused": 0, "none": 0})
        self.assertEqual((outcome["turn_seconds"], outcome["unsynced"], outcome["diverged"]), ([1.5, 1.5], 0, False))
        self.assertEqual(outcome["turn_events_told"], 4)
        self.assertEqual(room.outcome()["agents"]["asked"], 2, "the room's outcome carries its agents'")


def _agents(**overrides):
    agents = {
        "early": True, "members": 10, "asked": 10,
        "ends": {"done": 10, "error": 0, "withdrawn": 0, "never": 0},
        "turn_seconds": [1.0, 2.0, 3.0, 4.0], "writes": {"landed": 10, "changed_meanwhile": 0, "refused": 0, "none": 0},
        "unsynced": 0, "present_at_end": [], "tabs_showing_agents": 0, "turn_events_told": 900,
        "diverged": False, "turns": [],
    }
    agents.update(overrides)
    return {"room": 0, "agents": agents}


def _tier(**extra):
    from utk_curio.backend.tests.stress.report import tier_summary

    summary = tier_summary(100, [], 1.0, "burst")
    summary.update(extra)
    return summary


def _markdown(*tiers):
    from utk_curio.backend.tests.stress.report import markdown

    return markdown({"run_id": "x", "backend_url": "u", "profile": "burst", "tiers": list(tiers), "failed": False})


class TheTurnsSectionTest(unittest.TestCase):
    def test_the_agents_add_up_per_tier(self):
        from utk_curio.backend.tests.stress.report import agents_summary

        agents = agents_summary([
            _agents(),
            _agents(early=False, turn_seconds=[10.0], ends={"done": 9, "never": 1},
                    writes={"landed": 8, "changed_meanwhile": 1, "none": 1}, unsynced=2,
                    present_at_end=["Node Builder"], tabs_showing_agents=3, diverged=True),
            {"room": 2},
        ])
        self.assertEqual((agents["rooms"], agents["asked_at_once"], agents["asked"]), (2, 1, 20))
        self.assertEqual(agents["ends"], {"done": 19, "error": 0, "withdrawn": 0, "never": 1})
        self.assertEqual(agents["writes"], {"landed": 18, "changed_meanwhile": 1, "refused": 0, "none": 1})
        # Nearest rank, as every percentile of the report: of five, the second.
        self.assertEqual(agents["turn_s"], {"count": 5, "total": 20.0, "p50": 2.0, "p95": 10.0, "max": 10.0})
        self.assertEqual((agents["unsynced"], agents["present_at_end"], agents["rooms_read"]), (2, 1, 2))
        self.assertEqual((agents["tabs_showing_agents"], agents["diverged_rooms"]), (3, 1))
        self.assertEqual(agents["turn_events_told"], 1800)

    def test_a_tier_with_no_agents_has_no_turns_section_and_presence_not_read_says_so(self):
        from utk_curio.backend.tests.stress.report import agents_summary

        self.assertIsNone(agents_summary([{"room": 0}]))
        self.assertIsNone(agents_summary([]))
        self.assertNotIn("Agents:", _markdown(_tier()))
        self.assertNotIn("agents", _markdown(_tier()).splitlines()[0])
        agents = agents_summary([_agents(present_at_end=None, turn_seconds=[])])
        self.assertIsNone(agents["present_at_end"])
        self.assertIsNone(agents["turn_s"])
        row = next(line for line in _markdown(_tier(agents=agents)).splitlines() if line.startswith("| 100 | 1 |"))
        self.assertIn("| no turn ended | no turn ended | no turn ended |", row)
        self.assertTrue(row.endswith("| not read |"), row)

    def test_the_turns_section_shows_turn_time_and_writes_and_the_title_names_the_agents(self):
        from utk_curio.backend.tests.stress.report import agents_summary

        rendered = _markdown(_tier(agents=agents_summary([_agents(
            writes={"landed": 7, "changed_meanwhile": 1, "refused": 1, "none": 1}, tabs_showing_agents=2)])))
        self.assertIn("agents on the scripted model", rendered.splitlines()[0])
        self.assertIn("Agents: every member also asks Node Builder, on Curio's scripted model", rendered)
        row = next(line for line in rendered.splitlines() if line.startswith("| 100 | 1 |"))
        self.assertEqual(row, "| 100 | 1 | 10 | 10 | 0 | 0 | 2.0 s | 4.0 s | 4.0 s | 7 | 1 | 2 | 0 "
                              "| 0 (2 tab(s) still showed one) |")

    def test_the_agents_failure_kinds_are_counted_and_fail_the_tier(self):
        from utk_curio.backend.tests.stress.driver import FAILURE_KINDS, Sample, UserResult
        from utk_curio.backend.tests.stress.report import build_report, markdown, tier_summary

        kinds = ("agent_turn", "changed_meanwhile", "agent_unsynced", "agent_present")
        for kind in kinds:
            self.assertIn(kind, FAILURE_KINDS)
        result = UserResult(user="u1", example="11.json", started_at=0.0)
        result.samples += [Sample("agent turn", _NODE, None, 3.0, False, f"{kind} detail", kind) for kind in kinds]
        tier = tier_summary(100, [result], 1.0, "burst")
        self.assertEqual(tier["failures_by_kind"], {kind: 1 for kind in kinds})
        report = build_report("x", "u", [tier], shared_canvas=True)
        self.assertTrue(report["failed"])
        self.assertIn(f"node `{_NODE}` at `agent turn` (changed_meanwhile): changed_meanwhile detail",
                      markdown(report))


class TheScriptedModelTest(unittest.TestCase):
    def _answers(self, status, endpoints):
        response = mock.Mock(status_code=status, text=json.dumps({"endpoints": endpoints}))
        response.json.return_value = {"endpoints": endpoints}
        return response

    def test_it_is_curios_default_for_the_tier_and_the_launchs_models_come_back_whatever_the_tier_did(self):
        from utk_curio.backend.tests.stress import agents

        calls = []
        with mock.patch.object(agents.requests, "post",
                               side_effect=lambda url, json, timeout: calls.append(("POST", url, json))
                               or self._answers(200, [{"name": "Scripted", "models": ["scripted"]}])), \
                mock.patch.object(agents.requests, "delete",
                                  side_effect=lambda url, timeout: calls.append(("DELETE", url, None))):
            self.assertEqual(agents.on_the_scripted_model("http://b", lambda: "tier"), "tier")
            with self.assertRaises(RuntimeError):
                agents.on_the_scripted_model("http://b", mock.Mock(side_effect=RuntimeError("the tier broke")))
        url = "http://b/api/testing/llm-deployment"
        self.assertEqual(calls, [("POST", url, {"scripted": True}), ("DELETE", url, None)] * 2)

    def test_a_stack_without_its_testing_routes_stops_the_run_before_the_tier(self):
        from utk_curio.backend.tests.stress import agents

        tier = mock.Mock()
        with mock.patch.object(agents.requests, "post", return_value=self._answers(404, None)), \
                mock.patch.object(agents.requests, "delete") as delete:
            with self.assertRaises(SystemExit):
                agents.on_the_scripted_model("http://b", tier)
        tier.assert_not_called()
        delete.assert_not_called()

    def test_agents_need_a_shared_canvas(self):
        from utk_curio.backend.tests.stress.run import main

        with mock.patch("sys.stderr"), self.assertRaises(SystemExit) as stopped:
            main(["--agents", "--tiers", "10", "--room-size", "10"])
        self.assertEqual(stopped.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
