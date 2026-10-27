"""``/output-file``: the backend relays a Data Export's file from the sandbox.

The canvas asks by the output's artifact id, never by a path. The backend asks
the sandbox under the session the caller reads that output in
(``_read_session``), and passes on the sandbox's answer as it is: the file
with the name it is saved under, or a refusal with its status and reason,
which the node shows. The sandbox's own checks are in
``sandbox/tests/test_data_export_files.py``.
"""

import unittest
from unittest import mock

from utk_curio.backend.app import create_app
from utk_curio.backend.app.api import routes
from utk_curio.backend.tests._unit_fixtures import TestConfig


class Reply:
    """The streamed ``requests`` reply the relay passes on (it asks with stream=True)."""

    def __init__(self, status, body, headers):
        self.status_code = status
        self.ok = status < 400
        self.body = body
        self.headers = headers

    def iter_content(self, chunk_size=1):
        yield self.body

    def close(self):
        pass


class OutputFileRelayTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig)
        self.client = self.app.test_client()
        self.asked = []
        self.reply = Reply(200, b"tree,height\noak,10\n", {
            "Content-Type": "text/csv; charset=utf-8",
            "Content-Disposition": "attachment; filename=trees.csv",
        })

        def fake_sandbox_call(method, path, *, label, timeout, **kwargs):
            self.asked.append((method, path, kwargs.get("params")))
            return self.reply

        for target, name, value in (
            (routes, "_sandbox_call", fake_sandbox_call),
            # The session the caller reads the output in, as kept.read_session
            # answers it for this sign-in.
            (routes, "_read_session", lambda file_name: f"session-reading-{file_name}"),
        ):
            patched = mock.patch.object(target, name, value)
            patched.start()
            self.addCleanup(patched.stop)
        # /output-file is behind require_auth, which resolves a user before the
        # route body runs; this suite is about the relay, so stand one in.
        from utk_curio.backend.app.users import dependencies

        patched = mock.patch.object(dependencies, "get_current_user", lambda *a, **k: mock.Mock(id=1))
        patched.start()
        self.addCleanup(patched.stop)

    def test_the_file_is_asked_by_the_outputs_id_in_the_readers_session_and_comes_through_named(self):
        response = self.client.get("/output-file", query_string={"fileName": "1792169042468_bd44c99d"})

        self.assertEqual(self.asked, [(
            "get", "/output-file",
            {"fileName": "1792169042468_bd44c99d", "sessionId": "session-reading-1792169042468_bd44c99d"},
        )])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_data(), b"tree,height\noak,10\n")
        self.assertEqual(response.headers["Content-Disposition"], "attachment; filename=trees.csv")
        self.assertEqual(response.mimetype, "text/csv")

    def test_a_refusal_keeps_its_status_and_its_reason(self):
        for status, code in ((403, "outside"), (404, "not-found"), (404, "gone")):
            self.reply = Reply(status, b'{"error": "%s", "message": "why"}' % code.encode(), {
                "Content-Type": "application/json",
            })
            response = self.client.get("/output-file", query_string={"fileName": "1792169042468_bd44c99d"})

            self.assertEqual(response.status_code, status, code)
            self.assertEqual(response.get_json(), {"error": code, "message": "why"})
            self.assertNotIn("Content-Disposition", response.headers)

    def test_no_output_named_asks_the_sandbox_nothing(self):
        response = self.client.get("/output-file")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.asked, [])


if __name__ == "__main__":
    unittest.main()
