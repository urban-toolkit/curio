"""The endpoint that hands a dashboard everything it needs in one response.

Unauthenticated on purpose, like ``/shared``: a dashboard is opened by whoever
holds the link, and this serves what that page would otherwise have fetched a
piece at a time.

The case worth protecting is the refusal. A dashboard whose rows will not fit in
a page must fail loudly and say which tiles are heavy, because the tempting
alternative, embedding what fits and fetching the rest, produces a page that
looks standalone and is not. Nobody finds out until it is opened somewhere the
server cannot be reached, which is the one situation the whole feature exists
for.
"""
import base64
import json

import pytest

from utk_curio.backend.app.projects import services


def _auth(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _spec_with_pinned_chart():
    """A producer feeding a pinned chart, as a dataflow saved from the canvas
    holds it (``TrillGenerator``): the template id as ``type`` and
    ``dashboardPinned`` on the node, with no ``data`` block (#693)."""
    return {
        "dataflow": {
            "name": "dash-route-test",
            "task": "",
            "timestamp": 1748990000000,
            "provenance_id": "dash-route-test",
            "nodes": [
                {
                    "id": "py",
                    "type": "curio.builtin/computation-analysis",
                    "x": 0,
                    "y": 0,
                },
                {
                    "id": "chart",
                    "type": "curio.builtin/vis-vega",
                    "x": 300,
                    "y": 0,
                    "dashboardPinned": True,
                },
            ],
            "edges": [{"id": "py-chart", "source": "py", "target": "chart"}],
        }
    }


def _create(client, token, spec=None, outputs=None):
    resp = client.post(
        "/api/projects",
        data=json.dumps(
            {
                "name": "Dashboard",
                "spec": spec or _spec_with_pinned_chart(),
                "outputs": outputs or [],
            }
        ),
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()["id"]


def test_a_missing_project_is_a_404(client, tmp_curio):
    resp = client.get("/api/projects/00000000-0000-0000-0000-000000000000/dashboard")
    assert resp.status_code == 404


def test_it_serves_the_spec_without_a_token(client, user_and_token, tmp_curio):
    _, token = user_and_token
    pid = _create(client, token)

    resp = client.get(f"/api/projects/{pid}/dashboard")

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["spec"]["dataflow"]["name"] == "dash-route-test"
    assert body["meta"]["projectId"] == pid
    assert "outputs" in body


def test_it_carries_the_descriptors_a_tile_needs_to_render(client, user_and_token, tmp_curio):
    # Curio bundles node implementations but not node descriptors: the only
    # thing that registers a node type is the package loader, fed by
    # GET /api/packages, and `curio.builtin` is a real package in the owner's
    # store rather than a bundle constant. Without these a standalone page shows
    # "Loading node..." on every tile, however much data it carries.
    _, token = user_and_token
    pid = _create(client, token)

    body = client.get(f"/api/projects/{pid}/dashboard").get_json()

    registry = body["registry"]
    ids = [p.get("packageId") for p in registry["packages"]]
    assert "curio.builtin" in ids, ids
    assert isinstance(registry["starters"], list)


def test_the_payload_carries_no_rows_when_nothing_was_saved(client, user_and_token, tmp_curio):
    _, token = user_and_token
    pid = _create(client, token)

    body = client.get(f"/api/projects/{pid}/dashboard").get_json()

    # No manifest outputs, so nothing to embed. The page still builds: the tile
    # shows its own empty state rather than the whole dashboard failing.
    assert body["outputs"] == {}


def test_a_dashboard_too_large_to_embed_is_refused(
    client, user_and_token, tmp_curio, monkeypatch
):
    _, token = user_and_token
    pid = _create(client, token)

    # Shrink the budget rather than manufacture 25 MB of rows: the refusal is
    # what is under test, not the size of the number.
    from utk_curio.backend.app.projects import dashboard_payload

    monkeypatch.setattr(dashboard_payload, "DEFAULT_PAYLOAD_LIMIT_BYTES", 512)

    def fat_reader():
        def read(filename):
            return {"dataType": "dataframe", "data": {"a": list(range(500))}, "schema": {}}

        return read

    monkeypatch.setattr(services, "_dashboard_envelope_reader", fat_reader)
    monkeypatch.setattr(
        services,
        "load_shared_project",
        lambda project_id: {
            "project": type("D", (), {"name": "Dashboard"})(),
            "spec": _spec_with_pinned_chart(),
            "outputs": [
                {"node_id": "py", "filename": "py.parquet", "data_type": "dataframe"}
            ],
        },
    )

    resp = client.get(f"/api/projects/{pid}/dashboard")

    assert resp.status_code == 413
    body = resp.get_json()
    # The owner has to know which node to aggregate, not just that it was big.
    assert "py" in body["error"]
    assert body["heaviest"][0]["nodeId"] == "py"
    assert body["totalBytes"] > body["limitBytes"]


def test_only_what_a_tile_reads_is_embedded(client, user_and_token, tmp_curio, monkeypatch):
    _, token = user_and_token
    pid = _create(client, token)

    def reader():
        return lambda filename: {"dataType": "dataframe", "data": {"a": [1]}, "schema": {}}

    monkeypatch.setattr(services, "_dashboard_envelope_reader", reader)
    monkeypatch.setattr(
        services,
        "load_shared_project",
        lambda project_id: {
            "project": type("D", (), {"name": "Dashboard"})(),
            "spec": _spec_with_pinned_chart(),
            "outputs": [
                {"node_id": "py", "filename": "py.parquet", "data_type": "dataframe"},
                # Saved because the account runs with save-every-output on. No
                # pinned tile descends from it, so it must not ride along in a
                # page that gets handed out by link.
                {"node_id": "secret", "filename": "secret.parquet", "data_type": "dataframe"},
            ],
        },
    )

    body = client.get(f"/api/projects/{pid}/dashboard").get_json()

    assert set(body["outputs"]) == {"py.parquet"}


# ---------------------------------------------------------------------------
# A raster behind a pinned Autark map
# ---------------------------------------------------------------------------

RASTER_META = {
    "width": 40, "height": 30, "count": 1, "crs": "EPSG:32616", "crsWkt": None,
    "transform": [100.0, 0.0, 447000.0, 0.0, -100.0, 4637000.0],
    "nodata": None, "dtype": "float32",
}


class _SandboxReply:
    """A sandbox answer, as ``requests`` hands one to the backend."""

    def __init__(self, status, *, body=None, content=b"", headers=None):
        self.status_code = status
        self.ok = 200 <= status < 300
        self._body = body
        self.content = json.dumps(body).encode("utf-8") if body is not None else content
        self.headers = headers or {}

    def json(self):
        if self._body is None:
            raise ValueError("no JSON body")
        return self._body

    def raise_for_status(self):
        if not self.ok:
            raise RuntimeError(f"HTTP {self.status_code}")

    def close(self):
        pass


def _spec_with_pinned_raster_map():
    """A Python node's raster feeding a pinned Autark map."""
    spec = _spec_with_pinned_chart()
    spec["dataflow"]["nodes"][1] = {
        "id": "map",
        "type": "curio.builtin/autk-grammar",
        "x": 300,
        "y": 0,
        "dashboardPinned": True,
        "content": json.dumps({"map": {"layerRefs": [{"dataRef": "input_0", "getFnv": "band_1"}]}}),
    }
    spec["dataflow"]["edges"] = [{"id": "py-map", "source": "py", "target": "map"}]
    return spec


def _sandbox_serving_a_raster(monkeypatch, raster_reply):
    """The sandbox as the dashboard sees it, through the one call the backend
    asks it with; returns what it was asked."""
    from utk_curio.backend.app.api import routes as api_routes

    asked = []

    def sandbox_call(method, path, *, label, timeout, **kwargs):
        asked.append((path, dict(kwargs.get("params") or {})))
        if path == "/get":
            return _SandboxReply(200, body={"dataType": "raster", "data": "/srv/curio/data/r.tif"})
        if path == "/raster":
            return raster_reply
        raise AssertionError(f"the dashboard asked the sandbox for {path}")

    monkeypatch.setattr(api_routes, "_sandbox_call", sandbox_call)
    monkeypatch.setattr(
        services,
        "load_shared_project",
        lambda project_id: {
            "project": type("D", (), {"name": "Dashboard"})(),
            "spec": _spec_with_pinned_raster_map(),
            "outputs": [{"node_id": "py", "filename": "r_output", "data_type": "raster"}],
        },
    )
    return asked


def test_a_raster_behind_a_pinned_map_travels_as_its_geotiff(
    client, user_and_token, tmp_curio, monkeypatch
):
    # The map loads the GeoTIFF /raster serves, which a page that needs no
    # server cannot ask for, so the page carries it.
    _, token = user_and_token
    pid = _create(client, token, spec=_spec_with_pinned_raster_map())
    geotiff = b"II*\x00" + bytes(range(256)) * 4
    asked = _sandbox_serving_a_raster(monkeypatch, _SandboxReply(
        200, content=geotiff, headers={"X-Curio-Raster": json.dumps(RASTER_META)},
    ))

    resp = client.get(f"/api/projects/{pid}/dashboard")

    assert resp.status_code == 200, resp.get_data(as_text=True)
    rasters = resp.get_json().get("rasters")
    assert rasters, "the page carries no raster, so its map would ask /raster for one"
    [raster] = rasters
    assert (raster["filename"], raster["part"], raster["status"]) == ("r_output", None, 200)
    assert raster["meta"] == RASTER_META
    assert base64.b64decode(raster["geotiff"]) == geotiff
    # Asked as the editor's map asks: by name, for no more than a map loads.
    # No session: the sandbox reads the copy the shared load hydrated.
    [params] = [params for path, params in asked if path == "/raster"]
    assert params["fileName"] == "r_output"
    assert int(params["maxCells"]) == 2048 * 2048 and int(params["maxSide"]) == 8192
    assert "part" not in params and "sessionId" not in params


def test_a_raster_too_large_for_a_map_travels_as_the_editors_refusal(
    client, user_and_token, tmp_curio, monkeypatch
):
    # The page then says what the editor says, and asks no server.
    _, token = user_and_token
    pid = _create(client, token, spec=_spec_with_pinned_raster_map())
    big = {**RASTER_META, "width": 5000, "height": 5000}
    _sandbox_serving_a_raster(monkeypatch, _SandboxReply(413, body={
        "error": "too-large",
        "message": "the raster is 5000 by 5000 cells",
        "meta": big,
        "fileName": "r_output",
    }))

    resp = client.get(f"/api/projects/{pid}/dashboard")

    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert resp.get_json().get("rasters") == [{
        "filename": "r_output",
        "part": None,
        "status": 413,
        "meta": big,
        "message": "the raster is 5000 by 5000 cells",
    }]


def test_a_raster_over_the_page_limit_is_refused_in_the_limits_own_words(
    client, user_and_token, tmp_curio, monkeypatch
):
    # Its GeoTIFF is what the page would carry, so it is what counts, and the
    # refusal names the raster's node as it names any heavy tile.
    _, token = user_and_token
    pid = _create(client, token, spec=_spec_with_pinned_raster_map())
    from utk_curio.backend.app.projects import dashboard_payload

    monkeypatch.setattr(dashboard_payload, "DEFAULT_PAYLOAD_LIMIT_BYTES", 4096)
    _sandbox_serving_a_raster(monkeypatch, _SandboxReply(
        200, content=b"II*\x00" + b"\x01" * 8192, headers={"X-Curio-Raster": json.dumps(RASTER_META)},
    ))

    resp = client.get(f"/api/projects/{pid}/dashboard")

    assert resp.status_code == 413, (
        f"a page carrying an 8 KB raster under a 4 KB limit answered {resp.status_code}"
    )
    body = resp.get_json()
    assert body["heaviest"][0]["nodeId"] == "py"
    assert body["heaviest"][0]["dataType"] == "raster"
    assert body["totalBytes"] > body["limitBytes"] == 4096
    assert "over the 4 KB limit" in body["error"]
