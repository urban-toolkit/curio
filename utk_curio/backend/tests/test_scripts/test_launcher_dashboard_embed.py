"""``run_spa_static_server``: a dashboard's data travels in its own page.

A dashboard at ``/dashboard/<id>`` is meant to stand on its own, so the page
server inlines the spec and the rows instead of letting the browser fetch them.
This process has no database, so it asks the backend once, on the server, for
the payload a browser would otherwise have assembled from a dozen requests.

Three things here are worth a test rather than a reading.

The page must not break out of its own script tag. The payload is somebody's
data, column names and all, and a dataflow that produced the text
``</script>`` would otherwise end the tag early and have the rest of itself
parsed as markup.

A dashboard the backend refuses to build carries the backend's reason instead
of its data: over the size limit (413), or with a tile that loads its own data
(409), the page says why and fetches nothing. A page that fetched its rows
instead would look standalone and not be. A backend that fails or cannot be
reached says nothing about the dashboard, so that page is the ordinary one.

And only a real navigation should pay for it. A HEAD, or a URL that cannot be a
project id, must not send the backend off to read every artifact behind a tile.
"""
from __future__ import annotations

import json
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from utk_curio.cli.static_server import run_spa_static_server

INDEX_BODY = '<!doctype html><html><head><base href="/"></head><body></body></html>'
HTML_ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"

DASHBOARD_ID = "97af666e-e32f-40a0-bc06-021fc3c22acf"


def _free_port() -> int:
    probe = ThreadingHTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
    port = probe.server_address[1]
    probe.server_close()
    return port


class _StubBackend:
    """Stands in for the Curio backend's dashboard endpoint."""

    def __init__(self, payload=None, status=200):
        self.payload = payload
        self.status = status
        self.paths = []
        self.port = _free_port()
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                outer.paths.append(self.path)
                # Whatever the status, as the backend answers: a refusal is a
                # JSON body too.
                body = b"" if outer.payload is None else json.dumps(outer.payload).encode("utf-8")
                self.send_response(outer.status)
                if body:
                    self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._server.shutdown()
        self._server.server_close()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"


def _start_spa(tmp_path, backend_url: str) -> str:
    dist = tmp_path / "dist"
    dist.mkdir(exist_ok=True)
    (dist / "index.html").write_text(INDEX_BODY, encoding="utf-8")
    port = _free_port()
    thread = threading.Thread(
        target=run_spa_static_server,
        args=(str(dist), port, "", backend_url),
        daemon=True,
    )
    thread.start()
    url = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            urllib.request.urlopen(f"{url}/index.html", timeout=1).read()
            return url
        except OSError:
            threading.Event().wait(0.05)
    pytest.fail("run_spa_static_server never came up")


def _get(base: str, path: str, method: str = "GET") -> str:
    request = urllib.request.Request(
        f"{base}{path}", headers={"Accept": HTML_ACCEPT}, method=method
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return response.read().decode("utf-8")


def _embedded(html: str):
    """The payload the page carries, or None when it carries none."""
    marker = '<script id="curio-dashboard-payload" type="application/json">'
    start = html.find(marker)
    if start < 0:
        return None
    start += len(marker)
    end = html.find("</script>", start)
    return json.loads(html[start:end])


PAYLOAD = {
    "meta": {"projectId": DASHBOARD_ID, "name": "Trips"},
    "spec": {"dataflow": {"nodes": [], "edges": []}},
    "outputs": {"a.parquet": {"dataType": "dataframe", "data": {"n": [1, 2]}, "schema": {}}},
}


def test_a_dashboard_page_carries_its_own_data(tmp_path):
    with _StubBackend(PAYLOAD) as backend:
        spa = _start_spa(tmp_path, backend.url)

        html = _get(spa, f"/dashboard/{DASHBOARD_ID}")

        assert _embedded(html) == PAYLOAD
        assert backend.paths == [f"/api/projects/{DASHBOARD_ID}/dashboard"]


def test_the_payload_survives_a_script_tag_in_the_data(tmp_path):
    # Column names and cell values are somebody's data. Without escaping, this
    # ends the tag early and the rest of the payload is parsed as markup.
    hostile = {
        "meta": {},
        "spec": {},
        "outputs": {
            "x.parquet": {
                "dataType": "dataframe",
                "data": {"label": ["</script><img src=x onerror=alert(1)>"]},
                "schema": {},
            }
        },
    }
    with _StubBackend(hostile) as backend:
        spa = _start_spa(tmp_path, backend.url)

        html = _get(spa, f"/dashboard/{DASHBOARD_ID}")

        # It round-trips unchanged...
        assert _embedded(html) == hostile
        # ...and the literal tag never appears in the markup.
        assert "<img src=x" not in html
        assert "</script><img" not in html


def test_a_dataflow_page_carries_nothing(tmp_path):
    with _StubBackend(PAYLOAD) as backend:
        spa = _start_spa(tmp_path, backend.url)

        html = _get(spa, f"/dataflow/{DASHBOARD_ID}")

        assert _embedded(html) is None
        assert backend.paths == []


def test_a_path_that_cannot_be_a_project_id_is_not_looked_up(tmp_path):
    with _StubBackend(PAYLOAD) as backend:
        spa = _start_spa(tmp_path, backend.url)

        html = _get(spa, "/dashboard/not-a-uuid")

        assert _embedded(html) is None
        assert backend.paths == []


def test_a_head_request_does_not_assemble_a_payload(tmp_path):
    # Assembling reads every artifact behind a tile. Nothing reads a HEAD body.
    with _StubBackend(PAYLOAD) as backend:
        spa = _start_spa(tmp_path, backend.url)

        _get(spa, f"/dashboard/{DASHBOARD_ID}", method="HEAD")

        assert backend.paths == []


def _too_large(name: str) -> tuple[str, dict]:
    """The size refusal as ``GET /api/projects/<id>/dashboard`` answers it: the
    limit's own words, which name the node to aggregate."""
    from utk_curio.backend.app.projects.dashboard_payload import (
        DashboardTooLargeError,
        TileWeight,
    )

    weight = TileWeight(
        node_id="trips-by-hour", filename="a.parquet", data_type="dataframe",
        bytes=31 * 1024 * 1024,
    )
    error = DashboardTooLargeError(weight.bytes, 25 * 1024 * 1024, [weight])
    reason = error.describe()
    return reason, {
        "error": reason,
        "totalBytes": error.total_bytes,
        "limitBytes": error.limit_bytes,
        "heaviest": [{"nodeId": weight.node_id, "bytes": weight.bytes, "dataType": weight.data_type}],
        "name": name,
    }


def test_a_dashboard_over_the_size_limit_says_why_and_carries_no_data(tmp_path):
    # The limit is a refusal, not a fallback. A page that fetched its rows
    # instead would look standalone and not be, so the page carries the
    # backend's reason and the dataflow's name, and no data.
    reason, body = _too_large("Trips")
    with _StubBackend(body, status=413) as backend:
        spa = _start_spa(tmp_path, backend.url)

        html = _get(spa, f"/dashboard/{DASHBOARD_ID}")

        assert _embedded(html) == {
            "meta": {"projectId": DASHBOARD_ID, "name": "Trips"},
            "refused": {"status": 413, "message": reason},
        }, "the page carries no refusal, so it is an ordinary page that fetches its data itself"
        assert "trips-by-hour" in reason


def test_a_tile_that_loads_its_own_data_says_why_and_carries_no_data(tmp_path):
    from utk_curio.backend.app.projects.dashboard_payload import (
        DashboardCannotBeStandaloneError,
    )

    reason = DashboardCannotBeStandaloneError(["city-map"]).describe()
    body = {"error": reason, "tiles": ["city-map"], "name": "Trips"}
    with _StubBackend(body, status=409) as backend:
        spa = _start_spa(tmp_path, backend.url)

        html = _get(spa, f"/dashboard/{DASHBOARD_ID}")

        assert _embedded(html) == {
            "meta": {"projectId": DASHBOARD_ID, "name": "Trips"},
            "refused": {"status": 409, "message": reason},
        }, "the page carries no refusal, so it is an ordinary page that fetches its data itself"


def test_a_refusal_survives_a_script_tag_in_the_dataflow_name(tmp_path):
    # The name is the owner's text, and travels in the same tag as a payload.
    hostile = "</script><img src=x onerror=alert(1)>"
    reason, body = _too_large(hostile)
    with _StubBackend(body, status=413) as backend:
        spa = _start_spa(tmp_path, backend.url)

        html = _get(spa, f"/dashboard/{DASHBOARD_ID}")

        assert _embedded(html) == {
            "meta": {"projectId": DASHBOARD_ID, "name": hostile},
            "refused": {"status": 413, "message": reason},
        }, "the page carries no refusal, so it is an ordinary page that fetches its data itself"
        assert "<img src=x" not in html


def test_a_backend_that_fails_still_serves_an_ordinary_page(tmp_path):
    # A failure is not a refusal: it says nothing about the dashboard.
    with _StubBackend({"error": "Internal Server Error"}, status=500) as backend:
        spa = _start_spa(tmp_path, backend.url)

        html = _get(spa, f"/dashboard/{DASHBOARD_ID}")

        assert _embedded(html) is None
        assert "<body>" in html


def test_without_a_backend_url_the_page_is_unchanged(tmp_path):
    # The dev server and any launch without --backend-url: no embedding, and
    # above all no crash on the route.
    spa = _start_spa(tmp_path, "")

    html = _get(spa, f"/dashboard/{DASHBOARD_ID}")

    assert _embedded(html) is None
    assert html == INDEX_BODY
