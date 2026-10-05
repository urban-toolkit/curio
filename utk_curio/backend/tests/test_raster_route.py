"""``GET /raster``: a raster artifact's GeoTIFF bytes, for an Autark node (#662).

The backend is a proxy here, as it is for ``/get``: the sandbox reads the
artifact under the caller's session and decides what to answer; this process
forwards the request and relays the reply. What the node needs from the relay
is the bytes, the ``X-Curio-Raster`` header that describes them, and the
sandbox's own status and words when it refuses (a raster too large to load is
a 413 with its size), so the node can say why it drew nothing.
"""

import json
import unittest
from unittest import mock

from utk_curio.backend.app import CORS_HEADERS, create_app
from utk_curio.backend.app.api import routes
from utk_curio.backend.tests._unit_fixtures import TestConfig

META = {"width": 40, "height": 30, "count": 1, "crs": "EPSG:32616"}


class SandboxReply:
    """The streamed ``requests`` reply the proxy relays."""

    def __init__(self, status, body, headers):
        self.status_code = status
        self.ok = 200 <= status < 300
        self.content = body
        self.headers = headers

    def iter_content(self, chunk_size=1):
        yield self.content

    def raise_for_status(self):
        if not self.ok:
            raise RuntimeError(f"HTTP {self.status_code}")

    def close(self):
        pass


class RasterRouteTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig)
        self.client = self.app.test_client()
        self.calls = []
        self.reply = SandboxReply(
            200, b"II*\x00tiff", {"Content-Type": "image/tiff", "X-Curio-Raster": json.dumps(META)},
        )

        def fake_sandbox_call(method, path, *, label, timeout, **kwargs):
            self.calls.append({"method": method, "path": path, **kwargs})
            return self.reply

        patch = mock.patch.object(routes, "_sandbox_call", fake_sandbox_call)
        patch.start()
        self.addCleanup(patch.stop)

    def sign_in(self):
        from utk_curio.backend.app.users import dependencies

        for module, name, value in ((dependencies, "get_current_user", mock.Mock(id=1)),
                                    (routes, "get_current_token", "session-1")):
            patched = mock.patch.object(module, name, lambda *a, _v=value, **k: _v)
            patched.start()
            self.addCleanup(patched.stop)

    def test_the_bytes_and_their_description_reach_the_browser(self):
        self.sign_in()
        response = self.client.get(
            "/raster", query_string={"fileName": "art-1", "part": "1", "maxCells": "4194304", "maxSide": "8192"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b"II*\x00tiff")
        self.assertEqual(response.mimetype, "image/tiff")
        self.assertEqual(json.loads(response.headers["X-Curio-Raster"]), META)
        # Asked of the sandbox by artifact id, under the caller's session.
        self.assertEqual(self.calls[-1]["path"], "/raster")
        self.assertEqual(self.calls[-1]["params"], {
            "fileName": "art-1", "sessionId": "session-1", "part": "1", "maxCells": "4194304", "maxSide": "8192",
        })

    def test_a_refusal_passes_through_with_its_status_and_words(self):
        self.sign_in()
        body = json.dumps({"error": "too-large", "message": "the raster is 5000 by 5000 cells",
                           "meta": {**META, "width": 5000, "height": 5000}}).encode()
        self.reply = SandboxReply(413, body, {"Content-Type": "application/json"})
        response = self.client.get("/raster", query_string={"fileName": "art-1", "maxCells": "100"})
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.get_json()["error"], "too-large")
        self.assertEqual(response.get_json()["meta"]["width"], 5000)

    def test_it_asks_who_is_asking(self):
        response = self.client.get("/raster", query_string={"fileName": "art-1"})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(self.calls, [])

    def test_it_names_an_artifact_never_a_path(self):
        self.sign_in()
        self.assertEqual(self.client.get("/raster").status_code, 400)
        self.assertEqual(self.calls, [])

    def test_the_browser_may_read_the_description(self):
        """The canvas is on another origin, so a header it may not read reads as
        null and every raster would be refused as having no description."""
        exposed = {
            name.strip().lower()
            for name in CORS_HEADERS["Access-Control-Expose-Headers"].split(",")
        }
        self.assertIn("x-curio-raster", exposed)


if __name__ == "__main__":
    unittest.main()
