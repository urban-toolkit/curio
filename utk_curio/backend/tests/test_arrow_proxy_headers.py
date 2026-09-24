"""The backend passes the Arrow request through, not just part of it.

`/get` here is a proxy: the sandbox decides the format, this process forwards
the request and relays the bytes. Forwarding `Accept` but dropping the WKB
opt-in made every geodataframe come back 415, and the caller then fell back to
JSON -- which looks like success, because the data still arrives. Only the
stress harness noticed, because it treats that 415 as an error.
"""

import unittest
from unittest import mock

from utk_curio.backend.app import create_app
from utk_curio.backend.app.api import routes
from utk_curio.backend.app.api.routes import ARROW_IPC_MIME, GEOMETRY_ACCEPT_HEADER
from utk_curio.backend.tests._unit_fixtures import TestConfig


class ArrowResponse:
    status_code = 200
    content = b"ARROW1"
    headers = {"Content-Type": ARROW_IPC_MIME, "X-Curio-Kind": "geodataframe"}


class ArrowProxyHeadersTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig)
        self.client = self.app.test_client()
        self.sent = []

        def fake_sandbox_call(method, path, *, label, timeout, **kwargs):
            self.sent.append(kwargs.get("headers") or {})
            return ArrowResponse()

        patch = mock.patch.object(routes, "_sandbox_call", fake_sandbox_call)
        patch.start()
        self.addCleanup(patch.stop)
        # /get is behind require_auth, which resolves a user before the route
        # body runs. This suite is about header plumbing, so stand in a user
        # rather than signing one up.
        from utk_curio.backend.app.users import dependencies

        for module, name in ((dependencies, "get_current_user"),
                             (routes, "get_current_token")):
            patched = mock.patch.object(
                module, name,
                lambda *a, **k: ("session-1" if name == "get_current_token"
                                 else mock.Mock(id=1)),
            )
            patched.start()
            self.addCleanup(patched.stop)

    def get(self, headers):
        return self.client.get("/get", query_string={"fileName": "a1"}, headers=headers)

    def test_the_geometry_opt_in_reaches_the_sandbox(self):
        self.get({"Accept": ARROW_IPC_MIME, GEOMETRY_ACCEPT_HEADER: "wkb"})

        self.assertEqual(self.sent[-1].get("Accept"), ARROW_IPC_MIME)
        self.assertEqual(self.sent[-1].get(GEOMETRY_ACCEPT_HEADER), "wkb")

    def test_a_request_without_it_forwards_only_accept(self):
        """A client that cannot decode WKB must not be handed it by accident."""
        self.get({"Accept": ARROW_IPC_MIME})

        self.assertEqual(self.sent[-1].get("Accept"), ARROW_IPC_MIME)
        self.assertIsNone(self.sent[-1].get(GEOMETRY_ACCEPT_HEADER))

    def test_the_json_path_sends_no_arrow_headers(self):
        self.get({})

        self.assertNotIn("Accept", self.sent[-1])
        self.assertNotIn(GEOMETRY_ACCEPT_HEADER, self.sent[-1])


if __name__ == "__main__":
    unittest.main()
