"""Preview for computed ``dict``/``list`` outputs (autk-grammar pool wrappers).

These outputs are persisted as zlib-compressed JSON (``.json.zlib``) and carry an
autk-grammar pool wrapper — a single ``geodataframe``, a multi-layer ``outputs``
envelope, or a raw ``[{name, type, geojson}]`` layer array. Reading them as plain
UTF-8 text raised ``UnicodeDecodeError`` (a ``ValueError``), which the preview
route then mislabeled as "rowLimit, offset and part must be integers". The fix
decompresses transparently and parses the wrapper the same way the Data Pool does
(per-layer tables), so a multi-layer output previews as a bundle with one tab per
non-empty layer.
"""
from __future__ import annotations

import json
import zlib
from pathlib import Path

from utk_curio.backend.app.datasets.services.preview_service import DatasetPreviewService
from utk_curio.sandbox.util.tabular_preview import normalize_pool_layers


def _fc(rows: list[dict]) -> dict:
    """A FeatureCollection whose features carry ``rows`` as properties."""
    return {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "geometry": None, "properties": props} for props in rows
        ],
    }


def _write_zlib_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(zlib.compress(json.dumps(payload).encode("utf-8")))


def test_outputs_envelope_zlib_previews_as_bundle(tmp_path):
    """The dict/`outputs` shape from `layersToPoolWrapper`, zlib-compressed."""
    payload = {
        "dataType": "outputs",
        "data": [
            {"dataType": "geodataframe", "data": _fc([{"a": 1}, {"a": 2}]),
             "layerName": "roads", "layerType": "roads"},
            {"dataType": "geodataframe", "data": _fc([{"b": 9}]),
             "layerName": "buildings", "layerType": "buildings"},
        ],
    }
    f = tmp_path / "computed.node@1" / "data" / "out.json.zlib"
    _write_zlib_json(f, payload)

    preview = DatasetPreviewService().preview({"format": "json", "path": str(f)}, row_limit=6, offset=0)

    assert preview.get("unsupported") is not True, preview.get("message")
    assert preview["bundle"] is True
    assert [p["label"] for p in preview["parts"]] == ["roads", "buildings"]
    roads = preview["parts"][0]
    assert roads["format"] == "geojson" and roads["kind"] == "geodataframe"
    assert roads["totalRows"] == 2
    assert roads["rows"][0]["a"] == 1


def test_layer_array_zlib_previews_as_bundle(tmp_path):
    """The data-only `[{name, type, geojson}]` shape, zlib-compressed."""
    payload = [
        {"name": "surface", "type": "surface", "geojson": _fc([{"x": 1}])},
        {"name": "roads", "type": "roads", "geojson": _fc([{"y": 1}, {"y": 2}])},
    ]
    f = tmp_path / "computed.node@1" / "data" / "out.json.zlib"
    _write_zlib_json(f, payload)

    preview = DatasetPreviewService().preview({"format": "json", "path": str(f)}, row_limit=6, offset=0)

    assert preview["bundle"] is True
    assert [p["label"] for p in preview["parts"]] == ["surface", "roads"]
    assert preview["parts"][1]["totalRows"] == 2


def test_empty_layers_are_dropped(tmp_path):
    """An empty layer (no features) is dropped, mirroring the Data Pool's tabs."""
    payload = {
        "dataType": "outputs",
        "data": [
            {"dataType": "geodataframe", "data": _fc([]), "layerName": "parks"},
            {"dataType": "geodataframe", "data": _fc([{"a": 1}]), "layerName": "roads"},
        ],
    }
    f = tmp_path / "computed.node@1" / "data" / "out.json.zlib"
    _write_zlib_json(f, payload)

    preview = DatasetPreviewService().preview({"format": "json", "path": str(f)}, row_limit=6, offset=0)

    # Only one non-empty layer survives → flat table, not a bundle.
    assert preview.get("bundle") is not True
    assert preview["totalRows"] == 1
    assert preview["rows"][0]["a"] == 1


def test_single_layer_previews_as_flat_table(tmp_path):
    payload = {"dataType": "geodataframe", "data": _fc([{"a": 1}, {"a": 2}, {"a": 3}]),
               "layerName": "only"}
    f = tmp_path / "computed.node@1" / "data" / "out.json.zlib"
    _write_zlib_json(f, payload)

    preview = DatasetPreviewService().preview({"format": "json", "path": str(f)}, row_limit=2, offset=0)

    assert preview.get("bundle") is not True
    assert preview["totalRows"] == 3
    assert [r["a"] for r in preview["rows"]] == [1, 2]
    assert preview["truncated"] is True


def test_pool_bundle_part_pagination(tmp_path):
    payload = {
        "dataType": "outputs",
        "data": [
            {"dataType": "geodataframe",
             "data": _fc([{"i": n} for n in range(25)]), "layerName": "roads"},
            {"dataType": "geodataframe", "data": _fc([{"k": 1}]), "layerName": "buildings"},
        ],
    }
    f = tmp_path / "computed.node@1" / "data" / "out.json.zlib"
    _write_zlib_json(f, payload)
    svc = DatasetPreviewService()
    item = {"format": "json", "path": str(f)}

    overview = svc.preview(item, row_limit=6, offset=0)
    assert overview["parts"][0]["totalRows"] == 25
    assert len(overview["parts"][0]["rows"]) == 6

    page2 = svc.preview(item, row_limit=6, offset=6, part_index=0)
    assert page2["bundle"] is True and page2["partIndex"] == 0
    assert [r["i"] for r in page2["rows"]] == list(range(6, 12))

    oob = svc.preview(item, row_limit=6, offset=0, part_index=99)
    assert oob["unsupported"] is True and oob["partIndex"] == 99


def test_plain_json_still_previews(tmp_path):
    """A non-pool JSON document is unaffected by the pool-wrapper detection."""
    f = tmp_path / "computed.node@1" / "data" / "rows.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps([{"city": "Chicago"}, {"city": "NYC"}]), encoding="utf-8")

    preview = DatasetPreviewService().preview({"format": "json", "path": str(f)}, row_limit=6, offset=0)

    assert preview.get("bundle") is not True
    assert preview["totalRows"] == 2
    assert preview["rows"][0]["city"] == "Chicago"


def test_normalize_pool_layers_rejects_non_pool_shapes():
    assert normalize_pool_layers([{"city": "Chicago"}]) is None
    assert normalize_pool_layers({"foo": "bar"}) is None
    assert normalize_pool_layers("just a string") is None
    # A genuine pool shape is recognized.
    layers = normalize_pool_layers(
        {"dataType": "geodataframe", "data": _fc([{"a": 1}]), "layerName": "x"}
    )
    assert layers and layers[0]["dataType"] == "geodataframe"