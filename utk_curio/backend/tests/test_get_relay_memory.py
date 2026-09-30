"""The backend relays an artifact without rebuilding it (#408).

``/get`` is a proxy: the sandbox serializes the artifact, and the backend only
has to pass the bytes on. On the JSON path it used to parse the whole body
(``resp.json()``) and then encode it again (``jsonify``), so for one fetch the
backend held the artifact as Python objects - several times its size in bytes -
on top of the sandbox's own copy. On a 16 GB laptop running both processes,
that is the difference between a chart rendering and the OOM killer.

The measure is ``tracemalloc``'s peak while the route relays a GeoJSON body:
a relay should need about one copy of the body (the test client joins the
stream into one ``bytes``), never the parsed tree.
"""

import json
import tracemalloc
import unittest
from unittest import mock


from utk_curio.backend.app import create_app
from utk_curio.backend.app.api import routes
from utk_curio.backend.tests._unit_fixtures import TestConfig


def _geojson_body(features: int) -> bytes:
    """A FeatureCollection shaped like the sandbox's geodataframe envelope."""
    ring = [[-87.6 + i * 1e-5, 41.8 + i * 1e-5] for i in range(9)]
    payload = {
        "dataType": "geodataframe",
        "data": {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"bldg_id": n, "stories": n % 40, "status": "ACTIVE"},
                    "geometry": {"type": "Polygon", "coordinates": [ring]},
                }
                for n in range(features)
            ],
        },
    }
    return json.dumps(payload).encode("utf-8")


class FakeSandboxResponse:
    """What ``requests`` hands back for the sandbox's ``/get`` reply."""

    status_code = 200
    ok = True

    def __init__(self, body: bytes):
        self._body = body
        self.headers = {"Content-Type": "application/json",
                        "Content-Length": str(len(body))}

    @property
    def content(self):
        return self._body

    def json(self):
        return json.loads(self._body)

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size=1, decode_unicode=False):
        for start in range(0, len(self._body), chunk_size):
            yield self._body[start:start + chunk_size]

    def close(self):
        return None


class GetRelayMemoryTest(unittest.TestCase):
    def setUp(self):
        self.body = _geojson_body(40_000)
        self.app = create_app(TestConfig)
        self.client = self.app.test_client()
        self.calls = []

        def fake_sandbox_call(method, path, *, label, timeout, **kwargs):
            self.calls.append(kwargs)
            return FakeSandboxResponse(self.body)

        patch = mock.patch.object(routes, "_sandbox_call", fake_sandbox_call)
        patch.start()
        self.addCleanup(patch.stop)
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

    def _relay_peak(self):
        """Peak Python allocation while the route relays the body.

        The body is consumed a chunk at a time and dropped, as a browser
        reading the response would: the test client's own buffering (it
        collects every chunk, then joins them) is not the backend's memory.
        """
        tracemalloc.start()
        try:
            response = self.client.get("/get", query_string={"fileName": "a1"},
                                       buffered=False)
            size = 0
            for chunk in response.response:
                size += len(chunk)
            response.close()
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        return response, size, peak

    def test_the_json_path_relays_without_parsing_the_artifact(self):
        response, size, peak = self._relay_peak()

        self.assertEqual(response.status_code, 200)
        # A relay that held even half the artifact would not be relaying it.
        self.assertLess(
            peak, len(self.body) / 2,
            f"relaying a {len(self.body) / 1e6:.0f} MB body peaked at "
            f"{peak / 1e6:.0f} MB of Python allocations",
        )
        # Byte for byte: re-encoding changed the whitespace, and so the size.
        self.assertEqual(size, len(self.body))

    def test_the_relayed_body_is_the_sandbox_body(self):
        response = self.client.get("/get", query_string={"fileName": "a1"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.get_data()), json.loads(self.body))
        self.assertTrue(response.content_type.startswith("application/json"))

    def test_a_sandbox_error_is_still_reported_as_a_load_error(self):
        failing = FakeSandboxResponse(b'{"error": "KeyError"}')
        failing.status_code = 404
        failing.ok = False

        def raise_for_status():
            raise RuntimeError("404 Client Error: NOT FOUND")

        failing.raise_for_status = raise_for_status
        with mock.patch.object(routes, "_sandbox_call", lambda *a, **k: failing):
            response = self.client.get("/get", query_string={"fileName": "a1"})

        self.assertEqual(response.status_code, 500)
        self.assertIn("Error loading artifact: 404 Client Error", response.get_data(as_text=True))
