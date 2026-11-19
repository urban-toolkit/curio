"""Every key of a data source, loaded by a run on the server.

The ``data`` documents of ``src/tests/fixtures/autk-every-key.json`` write
every key of autk-grammar 5.2.0's CSV, JSON, GeoJSON, OpenStreetMap, join,
GeoTIFF, heatmap, SQL, update and drop sources between them, and its
``workspaces``: files of the repository and tables written inline, every
geometry column, every GeoJSON geometry with its boxes, a workspace on every
kind, an OpenStreetMap table dropped, an extract read in the CRS of its
coordinates, tag sets read from Overpass with ``forceRefresh``, a join
measured from each zone's own shape (``"useCentroid": false``) with an
aggregate normalized, a heatmap's normalized aggregate, SQL tables with a
layer type and without, CSV tables updated and replaced, a layer updated by a
property, a table dropped, and two workspaces each in a CRS of its own. Each
is compiled as a run on the server compiles an Autark data node
(``utk_curio/common/autk_data_compiler.py``) and run here through
``execute_js_code``, on autk-db in the sandbox's Node, and what it hands on is
pinned: each table's name, layer type, rows and workspace, a table with no
geometry as its rows (``rows``, a CSV table's as its source wrote them;
``tables``, any table's as the load left it, sorted), the properties of a
table's rows (``properties``, each row found by a key property), the
coordinates of a table's first row in its workspace's CRS, on its precision
grid, and the CRS the table is handed on in (``coordinates``), a raster in its
envelope with its workspace, a join's aggregates on each row it joins onto.

autk-db keeps in a workspace only what lies in the box of the first table
loaded into it, and reads a GeoJSON source's ``boundingBox`` in the
workspace's CRS (World Mercator, metres), so each document loads its widest
table first, and a bounding box is written in metres.

No socket: the files a document names are served from disk by a ``fetch``
placed before the compiled code, at the address the sandbox writes for the
backend (an unreachable one here). A document whose case gives ``overpass``
is answered as the Overpass API would answer it: the query of its tag sets
with that answer, any other query with no elements, and the API's status with
a 404, which autk-db takes as a free slot. Every other request is refused.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE = REPO_ROOT / "utk_curio" / "frontend" / "urban-workflows" / "src" / "tests" / "fixtures" / "autk-every-key.json"

#: Put before the compiled code: serves the files of ``FILES`` from disk, as
#: the backend's ``/file/`` route would, answers the Overpass API with
#: ``OVERPASS`` (the tag sets' query) when the case gives an answer, says so on
#: stdout, and refuses any other request.
_FETCH_FROM_DISK = """{
  const __fs = require('fs');
  const __path = require('path');
  const __prefix = '__CURIO_BACKEND_URL__/file/';
  const __overpass = OVERPASS;
  globalThis.fetch = async (url, init) => {
    const href = typeof url === 'string' ? url : (url && url.url) || String(url);
    if (__overpass && href === 'https://overpass-api.de/api/status') {
      return new Response('', { status: 404 });
    }
    if (__overpass && href === 'https://overpass-api.de/api/interpreter') {
      const query = decodeURIComponent(String((init && init.body) || '').replace(/^data=/, '').replace(/\\+/g, ' '));
      const tagged = query.includes('->.tagHits');
      console.log('[overpass] ' + (tagged ? 'tag sets' : 'other'));
      return new Response(JSON.stringify(tagged ? __overpass : { elements: [] }),
        { status: 200, headers: { 'Content-Type': 'application/json' } });
    }
    const rel = href.startsWith(__prefix) ? decodeURIComponent(href.slice(__prefix.length)) : null;
    if (!FILES.includes(rel)) throw new Error('no socket in this test: ' + href);
    console.log('[served] ' + rel);
    return new Response(__fs.readFileSync(__path.join(ROOT, rel)), { status: 200 });
  };
}
"""


def _cases():
    if not FIXTURE.is_file():
        return [pytest.param(None, id="fixture-missing")]
    cases = json.loads(FIXTURE.read_text(encoding="utf-8")).get("data", [])
    return [pytest.param(case, id=case["name"]) for case in cases] or [pytest.param(None, id="no-data-cases")]


@pytest.mark.parametrize("case", _cases())
def test_the_server_compiled_load_runs_every_key_of_a_data_source(case, tmp_path, monkeypatch):
    assert case is not None, f"{FIXTURE} holds no data documents"
    from utk_curio.cli import dependencies
    from utk_curio.common.autk_data_compiler import compile_data_spec
    from utk_curio.sandbox.app.worker import _worker_init, execute_js_code
    from utk_curio.sandbox.util.parsers import load_from_duckdb
    from utk_curio.sandbox.util.rasters import envelope_arrays, rasters_for_python

    files = case.get("files", [])
    code = compile_data_spec(json.dumps(case["document"]))
    for name in files:
        # Named by its path in the repository, and fetched from the backend's /file/ route.
        assert f"__CURIO_BACKEND_URL__/file/{name}" in code
    serve = (_FETCH_FROM_DISK.replace("FILES", json.dumps(files)).replace("ROOT", json.dumps(str(REPO_ROOT)))
             .replace("OVERPASS", json.dumps(case.get("overpass"))))

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("FLASK_BACKEND_HOST", "curio-backend.invalid")
    monkeypatch.setenv("FLASK_BACKEND_PORT", "1")
    dependencies.seed_duckdb_extensions()
    _worker_init()
    result = execute_js_code(serve + code, "", "AUTK_GRAMMAR", "", launch_dir=str(REPO_ROOT), session_id=None)

    assert result["output"]["path"], result["stderr"]
    assert result["output"]["dataType"] == "list"
    for name in files:
        assert f"[served] {name}" in result["stdout"], result["stdout"]
    if case.get("overpass"):
        # The tag sets were read from the Overpass API, past the answer a browser keeps.
        assert "[overpass] tag sets" in result["stdout"], result["stdout"]
    loaded = load_from_duckdb(result["output"]["path"], session_id=None)

    tables = [item for item in loaded if item.get("dataType") != "raster"]
    rasters = [item for item in loaded if item.get("dataType") == "raster"]
    with_geometry = [table for table in tables if any(
        feature.get("geometry") is not None for feature in (table.get("geojson") or {}).get("features", []))]
    # What it handed on, to read a failure by: each table's name, layer type,
    # rows, workspace and whether a row has a geometry, and each raster's name.
    handed = [
        (table.get("name"), table.get("type"), len((table.get("geojson") or {}).get("features", [])),
         table.get("workspace"), table in with_geometry)
        for table in tables
    ] + [(raster.get("layerName"), "raster", None, raster.get("workspace"), None) for raster in rasters]

    # Each table it loads, with its layer type, its rows and its workspace.
    expected = sorted(tuple(row) for row in case.get("handsOn", []))
    found = sorted(
        (table["name"], table["type"], len(table["geojson"]["features"]), table.get("workspace"))
        for table in with_geometry
    )
    assert [row[:2] + row[3:] for row in found] == [row[:2] + row[3:] for row in expected], handed
    for got, want in zip(found, expected):
        if want[2] is None:
            assert got[2] > 0, handed
        else:
            assert got[2] == want[2], (got, want, handed)

    # A table with no geometry is handed on as its rows: every column of each.
    for name, count, workspace in case.get("rows", []):
        table = next((t for t in tables if t.get("name") == name and t.get("workspace") == workspace), None)
        assert table is not None, (
            f"the load handed on no table {name}: it handed on {[(t.get('name'), t.get('workspace')) for t in loaded]}"
        )
        features = table["geojson"]["features"]
        assert len(features) == count
        assert all(feature.get("geometry") is None for feature in features), features[:1]
        source = next(s for s in case["document"]["data"] if s.get("outputTableName") == name)
        header, *rows = source["csvObject"]
        assert [{key: feature["properties"].get(key) for key in header} for feature in features] == [
            dict(zip(header, row)) for row in rows
        ]

    # A table with no geometry, as the load left it: its rows' values of the
    # columns written, sorted, a SQL table's, an updated and a replaced one's.
    for name, workspace, expected in case.get("tables", []):
        table = next((t for t in tables if t.get("name") == name and t.get("workspace") == workspace), None)
        assert table is not None, (
            f"the load handed on no table {name}: it handed on {[(t.get('name'), t.get('workspace')) for t in loaded]}"
        )
        features = table["geojson"]["features"]
        assert all(feature.get("geometry") is None for feature in features), features[:1]
        columns = sorted({key for row in expected for key in row})
        got = sorted(({key: feature["properties"].get(key) for key in columns} for feature in features),
                     key=lambda row: json.dumps(row, sort_keys=True))
        assert got == sorted(expected, key=lambda row: json.dumps(row, sort_keys=True)), (name, got)

    # The properties of the rows of a table with a geometry, each row found by
    # the value of a key property: the values written, a row's own after an update.
    for name, workspace, key, by_value in case.get("properties", []):
        table = next((t for t in with_geometry if t.get("name") == name and t.get("workspace") == workspace), None)
        assert table is not None, (name, workspace, handed)
        rows = {str(feature["properties"].get(key)): feature["properties"] for feature in table["geojson"]["features"]}
        for value, expected in by_value.items():
            assert value in rows, (name, key, value, sorted(rows))
            assert {column: rows[value].get(column) for column in expected} == expected, (name, value, rows[value])

    # The first row's coordinates, in its workspace's CRS on its precision grid,
    # and the CRS the table is handed on in, which the next node loads it in.
    for name, workspace, point, grid, crs in case.get("coordinates", []):
        table = next((t for t in with_geometry if t.get("name") == name and t.get("workspace") == workspace), None)
        assert table is not None, (name, workspace, handed)
        x, y = table["geojson"]["features"][0]["geometry"]["coordinates"][:2]
        assert abs(x - point[0]) <= grid and abs(y - point[1]) <= grid, (name, workspace, (x, y), point)
        named = ((table["geojson"].get("crs") or {}).get("properties") or {}).get("name", "")
        assert named.endswith(":" + crs.split(":")[-1]), (
            f"{name} in {workspace or 'the default workspace'} is handed on as {named!r}, not in {crs}"
        )

    # Each raster in its envelope, in its workspace, on its grid, and a Python
    # node downstream reads it as a dataset that keeps the workspace.
    assert sorted((r["layerName"], r.get("workspace")) for r in rasters) == sorted(
        (name, workspace) for name, workspace, _width, _height in case.get("rasters", []))
    if rasters:
        by_name = {raster["layerName"]: raster for raster in rasters}
        envelopes = [by_name[name] for name, _workspace, _width, _height in case["rasters"]]
        handed = rasters_for_python(envelopes, tmp_path / "rasters")
        try:
            for envelope, dataset, (_name, workspace, width, height) in zip(envelopes, handed, case["rasters"]):
                grid, _bands, _values = envelope_arrays(envelope)
                assert (grid["width"], grid["height"]) == (width, height), grid
                assert (dataset.width, dataset.height) == (width, height)
                assert dataset.__dict__["metadata"].get("workspace") == workspace, dataset.__dict__["metadata"]
        finally:
            for dataset in handed:
                dataset.close()

    # A join's aggregates reach the rows of the table it joins onto, each zone's
    # by its own key path: the raw ones, and a normalized one beside its own.
    for join in [s for s in case["document"]["data"] if s.get("type") == "join"]:
        target = next(t for t in tables if t["name"] == join["dataRef"] and t.get("workspace") == join.get("workspace"))
        for zone in case.get("joined", []):
            row = next(f["properties"] for f in target["geojson"]["features"] if f["properties"].get("zone") == zone["zone"])
            for path, value in zone["values"]:
                held = row
                for key in path:
                    held = held.get(key) if isinstance(held, dict) else None
                assert held == pytest.approx(value), (zone["zone"], path, row)
