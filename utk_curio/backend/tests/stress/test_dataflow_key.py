"""Every call and socket of the stress harness names its dataflow.

A stack started with ``--backend-processes N`` runs N backends behind nginx,
which sends each request and socket to the process that owns its dataflow: by
the ``X-Curio-Dataflow`` header, else a socket handshake's ``dataflow`` query
argument (``cli/backend_group.py``). A run's stream (``/api/runs/<id>``),
``/processPythonCode`` and the scripted model's queues name no dataflow in
their path. So once a user has a dataflow every call it makes carries the
header; a member's agent work carries its room's, whose turns run in the
process that owns it; and a tab's socket names its room's dataflow in its
handshake, both ways.

Nothing opens a socket: the session and the socket client are stand-ins.
Names are imported in each test, so a checkout without them fails test by test.
"""

import json
import unittest
import unittest.mock as mock
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

DATAFLOW = "0f8fad5b-d9cb-469f-a165-70867728950e"
ROUTE_HEADER = "X-Curio-Dataflow"
NODE = "11111111-2222-4333-8444-555555555555"


def _event(seq: int, event: str, data: dict) -> str:
    """A line of an ask's stream: a room envelope of the turn."""
    return "data: " + json.dumps({"projectId": DATAFLOW, "attachmentId": "att-9", "askId": "a" * 32,
                                  "seq": seq, "event": event, "data": data})


#: An ask's stream whose turn writes its node and ends.
TURN_STREAM = ["event: turn", _event(4, "tool_result", {"tool": "node.content.write", "status": "applied"}),
               "event: turn", _event(6, "done", {"reply": "Done."})]


class _Response:
    def __init__(self, status: int, body=None, lines=()):
        self.status_code, self._body, self._lines = status, body, list(lines)
        self.content = b"{}" if body is not None else b""
        self.text = ""

    def json(self):
        return self._body

    def iter_lines(self, decode_unicode=False):
        return iter(self._lines)

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


class _Session:
    """A requests session that answers a member's agent work and keeps the
    headers of each call it was asked."""

    headers: list = []

    def request(self, method, url, json=None, headers=None, timeout=None, **_kwargs):
        _Session.headers.append((method, urlsplit(url).path, dict(headers or {})))
        if url.endswith("/attachments"):
            return _Response(201, {"attachmentId": "att-9"})
        if url.endswith("/agent-script"):
            return _Response(200, {"pending": 2})
        return _Response(202, {"askId": json["askId"], "attachmentId": "att-9", "state": "running"})

    def get(self, url, headers=None, stream=False, timeout=None, **_kwargs):
        _Session.headers.append(("GET", urlsplit(url).path, dict(headers or {})))
        return _Response(200, lines=TURN_STREAM)

    def post(self, url, headers=None, timeout=None, **_kwargs):
        _Session.headers.append(("POST", urlsplit(url).path, dict(headers or {})))
        return _Response(200, {})

    def close(self):
        return None


class AUsersCallsTest(unittest.TestCase):
    def test_every_call_names_the_users_dataflow_once_it_has_one(self):
        from utk_curio.backend.tests.stress.driver import VirtualUser

        user = VirtualUser("http://backend", "u1", "e.json", {}, None, {})
        user.token = "tok"
        asked: list = []

        def request(_method, url, **kwargs):
            asked.append((urlsplit(url).path, dict(kwargs.get("headers") or {})))
            return _Response(200, {})

        user.session = SimpleNamespace(request=request)
        user._call("POST", "/api/auth/signup", json_body={})
        user.project_id = DATAFLOW
        user._call("GET", "/api/runs/:id", path_url="/api/runs/r1")

        self.assertNotIn(ROUTE_HEADER, asked[0][1], "a call made before the user had a dataflow named one")
        self.assertEqual(asked[1][1].get(ROUTE_HEADER), DATAFLOW, asked[1])
        self.assertEqual(asked[1][1].get("Authorization"), "Bearer tok")


class AMembersAgentWorkTest(unittest.TestCase):
    def test_a_members_agent_work_names_its_rooms_dataflow(self):
        """A member asks its agent before its own work moves to the room's
        dataflow: each call names the room's, where the turn runs."""
        from utk_curio.backend.tests.stress import agents
        from utk_curio.backend.tests.stress.driver import VirtualUser

        user = VirtualUser("http://backend", "u1", "e.json", {}, None, {})
        user.token, user.room = "tok", SimpleNamespace(project_id=DATAFLOW)
        turn = agents.MemberTurn("u1", NODE, "# line\nreturn input_0", early=True)
        _Session.headers = []
        with mock.patch.object(agents.requests, "Session", _Session):
            turn.run(user)

        paths = [path for _method, path, _headers in _Session.headers]
        self.assertIn("/api/testing/agent-script", paths)
        self.assertGreaterEqual(len(paths), 4, paths)
        self.assertEqual({headers.get(ROUTE_HEADER) for _method, _path, headers in _Session.headers}, {DATAFLOW},
                         _Session.headers)


class ATabsSocketTest(unittest.TestCase):
    def test_a_tabs_socket_names_its_rooms_dataflow_in_its_handshake(self):
        from utk_curio.backend.tests.stress import sockets

        connected: list = []

        def connect(client, url, **kwargs):
            connected.append((url, kwargs))

        with mock.patch.object(sockets.TabClient, "connect", connect), \
                mock.patch.object(sockets.TabClient, "transport", lambda client: "websocket"):
            sockets.SocketLink("http://backend/api", "/collab", "tok", lambda *a: None, lambda *a: None,
                               dataflow=DATAFLOW)

        [(url, kwargs)] = connected
        self.assertEqual(parse_qs(urlsplit(url).query).get("dataflow"), [DATAFLOW], url)
        self.assertEqual((kwargs.get("headers") or {}).get(ROUTE_HEADER), DATAFLOW, kwargs)
        self.assertEqual(kwargs.get("socketio_path"), "/api/socket.io")

    def test_a_tab_opens_its_socket_on_its_rooms_dataflow(self):
        from utk_curio.backend.tests.stress import sockets
        from utk_curio.backend.tests.stress.driver import BURST, VirtualUser

        user = VirtualUser("http://backend", "u1", "e.json", {}, None, {})
        user.token = "tok"
        room = sockets.Room(0, ["u1"])
        room.project_id = DATAFLOW
        room.invited.set()
        made: list = []

        def link(*args, **kwargs):
            made.append(kwargs)
            raise ConnectionError("no backend in this test")

        with mock.patch.object(sockets, "SocketLink", link):
            through = sockets.run_tab(user, room, backend_url="http://backend", namespace="/collab", pacing=BURST)

        self.assertFalse(through)
        self.assertEqual([kwargs.get("dataflow") for kwargs in made], [DATAFLOW], made)


if __name__ == "__main__":
    unittest.main()
