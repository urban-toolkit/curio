"""The parts a Data Export node's input holds, labelled as its zip names them.

Both sides run the cases in ``dataExportParts.cases.json`` beside
``utils/dataExportParts.ts`` (``src/tests/utils/dataExportPartsCases.test.ts``
is the other half: the node's Part dropdown labels the parts from the input's
envelope). Here each case's value is built and labelled by the sandbox's
``bundle_zip.parts_of``, which names the zip's files, and ``parseOutput`` of
it, reduced to what the dropdown reads, is the case's envelope: so the
dropdown and the zip never disagree. An inline case, the layers an Autark node
hands on, is read as a node's input reads it (``stored_inputs.read_stored``).

The sandbox modules are read inside each test.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

CASES_FILE = (
    Path(__file__).resolve().parents[3]
    / "frontend" / "urban-workflows" / "src" / "utils" / "dataExportParts.cases.json"
)


def _cases():
    if not CASES_FILE.is_file():
        return [pytest.param(None, id="cases-file-missing")]
    cases = json.loads(CASES_FILE.read_text(encoding="utf-8"))["cases"]
    return [pytest.param(case, id=case["name"]) for case in cases]


def _value(part: dict, folder: Path):
    """The Python value *part* describes: a frame with the metadata it names,
    a raster, or a value."""
    import geopandas as gpd
    import pandas as pd
    from shapely.geometry import Point

    kind = part["kind"]
    if kind in ("dataframe", "geodataframe"):
        frame = (
            pd.DataFrame({"a": [1]}) if kind == "dataframe"
            else gpd.GeoDataFrame({"a": [1]}, geometry=[Point(0, 0)], crs="EPSG:4326")
        )
        metadata = {key: part[key] for key in ("name", "layerType", "partLabel") if key in part}
        if metadata:
            frame.__dict__["metadata"] = metadata
        return frame
    if kind == "raster":
        import numpy as np
        import rasterio
        from rasterio.transform import from_origin

        path = folder / "heights.tif"
        with rasterio.open(
            path, "w", driver="GTiff", width=2, height=2, count=1, dtype="float32",
            crs="EPSG:4326", transform=from_origin(0, 2, 1, 1),
        ) as raster:
            raster.write(np.zeros((2, 2), dtype="float32"), 1)
        return rasterio.open(path)
    return part.get("value")


def _built(case: dict, folder: Path):
    values = [_value(part, folder) for part in case["parts"]]
    container = case["container"]
    if container == "single":
        return values[0]
    if container == "dict":
        return {part["key"]: value for part, value in zip(case["parts"], values)}
    return tuple(values) if container == "tuple" else values


def _reduced(envelope):
    """*envelope*, as ``/get`` answers it, reduced to what the dropdown reads."""
    if not isinstance(envelope, dict) or "dataType" not in envelope:
        return envelope
    kind = envelope["dataType"]
    if kind in ("outputs", "list"):
        reduced = {"dataType": kind, "data": [_reduced(item) for item in envelope["data"]]}
    elif kind == "dict":
        reduced = {"dataType": kind, "data": {key: _reduced(item) for key, item in envelope["data"].items()}}
    elif kind == "geodataframe":
        metadata = envelope["data"].get("metadata")
        reduced = {"dataType": kind, "data": {"metadata": metadata} if metadata else {}}
    elif kind == "dataframe":
        reduced = {"dataType": kind, **({"metadata": envelope["metadata"]} if envelope.get("metadata") else {})}
    elif kind == "raster":
        reduced = {"dataType": kind}
    else:
        reduced = {"dataType": kind, "data": envelope.get("data")}
    if "layerName" in envelope:
        reduced["layerName"] = envelope["layerName"]
    return reduced


def _labels(value):
    from utk_curio.sandbox.util.bundle_zip import holds_parts, parts_of

    if not holds_parts(value):
        return None
    return [part.label for part in parts_of(value)[1]]


@pytest.mark.parametrize("case", _cases())
def test_the_zip_labels_each_part_as_the_dropdown_reads_it_from_the_envelope(case, tmp_path):
    from utk_curio.sandbox.util.parsers import parseOutput
    from utk_curio.sandbox.util.stored_inputs import read_stored

    assert case is not None, f"{CASES_FILE} is missing"
    if case.get("inline"):
        assert _labels(read_stored(case["envelope"])) == case["labels"]
        return
    value = _built(case, tmp_path)
    assert _labels(value) == case["labels"]
    # Through JSON, as the canvas gets it.
    assert _reduced(json.loads(json.dumps(parseOutput(value), default=str))) == case["envelope"]
