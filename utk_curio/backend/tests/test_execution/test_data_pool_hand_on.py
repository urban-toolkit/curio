"""What a Python node receives through a Data Pool, against what it receives
fed directly by the node upstream of the pool.

``hook/dataPoolHandOn.cases.json`` (frontend) names, for each kind of output a
node upstream of a pool makes, the input a Python node sends the backend fed
directly (``sent.direct``) and fed through a Data Pool (``sent.pool``). Its Jest
half (``src/tests/adapters/node/dataPoolRasters.test.tsx``) checks that the pool
hands on what makes ``sent.pool``. Here each pair goes through the backend's
reading of a run's input (``node_exec.parse_input_ref``) and the sandbox's run
of the node (``worker.execute_code``, in process), on an output of that kind in
the sandbox's store, and the node must receive the same rasters both ways:
their bands, size, transform, CRS and name.

A dataflow saved before its outputs carried their type restores each as its
path alone (``normalizeFlowInput`` of a string), and a node it feeds sends that:
such an input is read by its reference, as one that names its type is.
"""
from __future__ import annotations

import json
import shutil
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
FRONTEND_SRC = REPO_ROOT / "utk_curio" / "frontend" / "urban-workflows" / "src"
CASES_FILE = FRONTEND_SRC / "hook" / "dataPoolHandOn.cases.json"
WIRE_FILE = FRONTEND_SRC / "utils" / "raster" / "rasterWire.cases.json"
#: The GeoTIFF the sandbox's raster tests read: 40 x 30 cells in EPSG:32616.
RASTER = Path(__file__).resolve().parents[1] / "test_frontend" / "data" / "autark_raster_utm16n.tif"

#: What the node receives on input_0: its type, and each raster in it, alone or
#: in a list or a tuple, by its file's name, size, CRS, transform and bands.
CHECK = textwrap.indent(textwrap.dedent("""\
    import math
    import os
    import rasterio

    def rasters_in(value):
        if isinstance(value, rasterio.io.DatasetReader):
            return [value]
        if isinstance(value, (list, tuple)):
            return [raster for item in value for raster in rasters_in(item)]
        return []

    def described(raster):
        return {
            "name": os.path.basename(raster.name),
            "size": [raster.width, raster.height],
            "crs": raster.crs.to_string() if raster.crs else None,
            "transform": list(raster.transform)[:6],
            "bands": [
                {
                    "description": raster.descriptions[index],
                    "values": [None if math.isnan(v) else v for v in raster.read(index + 1).ravel().tolist()],
                }
                for index in range(raster.count)
            ],
        }

    return {"input": type(input_0).__name__, "rasters": [described(raster) for raster in rasters_in(input_0)]}
"""), "    ")


def _cases() -> list:
    return json.loads(CASES_FILE.read_text(encoding="utf-8"))["cases"]


def _wire_envelope(at: int) -> dict:
    return json.loads(WIRE_FILE.read_text(encoding="utf-8"))["cases"][at]["envelope"]


@pytest.fixture
def store(tmp_path, monkeypatch):
    """A sandbox store of the test's own, as the sandbox suites make one."""
    from utk_curio.sandbox.app.worker import _worker_init
    from utk_curio.sandbox.util.db import init_db, release_connection

    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))
    monkeypatch.setenv("CURIO_SHARED_DATA", str(tmp_path / "data"))
    monkeypatch.delenv("CURIO_SANDBOX_TOKEN", raising=False)
    release_connection()
    init_db()
    _worker_init()
    yield tmp_path
    release_connection()


def _stored(kind: str, folder: Path) -> str:
    """The id of an output of *kind* (the cases' ``artifact``) in the store."""
    import geopandas as gpd
    import rasterio
    from shapely.geometry import Point

    from utk_curio.sandbox.util.parsers import save_to_duckdb
    from utk_curio.sandbox.util.rasters import raster_from_envelope

    def raster(name: str):
        target = folder / name
        shutil.copyfile(RASTER, target)
        return rasterio.open(target)

    heat = {**_wire_envelope(0), "layerName": "heat"}
    parks = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-87.62, 41.88]},
            "properties": {"name": "Grant Park"},
        }],
    }
    opened = []
    if kind == "raster":
        opened = [raster("heat.tif")]
        value = opened[0]
    elif kind == "tuple":
        stations = gpd.GeoDataFrame({"name": ["Loop"]}, geometry=[Point(-87.62, 41.88)], crs="EPSG:4326")
        opened = [raster("depth.tif")]
        value = (stations, opened[0])
    elif kind == "rasters":
        opened = [raster("day.tif"), raster_from_envelope(_wire_envelope(1), folder)]
        value = list(opened)
    elif kind == "tables":
        value = [{"name": "parks", "type": "points", "geojson": parks}, heat]
    elif kind == "heatmap":
        value = [heat]
    elif kind == "envelope":
        value = heat
    elif kind == "text":
        value = "a note"
    else:
        raise AssertionError(f"no output of kind {kind!r}")
    try:
        return save_to_duckdb(value, node_id=f"upstream-{kind}")
    finally:
        for dataset in opened:
            dataset.close()


def _received(sent: dict, art_id: str, placeholder: str) -> dict:
    """What a Python node whose input is *sent*, naming *art_id* where the case
    names *placeholder*, receives, as the backend and the sandbox read it."""
    from utk_curio.backend.app.execution.node_exec import parse_input_ref
    from utk_curio.sandbox.app.worker import execute_code
    from utk_curio.sandbox.util.parsers import load_from_duckdb

    sent = json.loads(json.dumps(sent).replace(json.dumps(placeholder), json.dumps(art_id)))
    ref = parse_input_ref(sent)
    result = execute_code(
        CHECK, ref["path"], "curio.builtin/python-computation", ref["dataType"],
        save_dataset=False, input_slots=[0],
    )
    assert result["stderr"] == "", result["stderr"]
    return load_from_duckdb(result["output"]["path"])


def test_an_input_that_names_no_type_is_read_by_its_reference():
    from utk_curio.backend.app.execution.node_exec import parse_input_ref

    assert parse_input_ref({"path": "art-1"}) == {"path": "art-1", "dataType": ""}
    assert parse_input_ref({"filename": "art-1"}) == {"path": "art-1", "dataType": ""}
    # One that names its type keeps it, and a bundle's outputs read as a file.
    assert parse_input_ref({"path": "art-1", "dataType": "raster"}) == {"path": "art-1", "dataType": "raster"}
    assert parse_input_ref({"filename": "art-1", "dataType": "outputs"}) == {"path": "art-1", "dataType": "file"}


def test_a_python_node_receives_through_a_data_pool_what_it_receives_without_one(store):
    for case in _cases():
        placeholder = case["handedOn"]["path"]
        art_id = _stored(case["artifact"], store)

        direct = _received(case["sent"]["direct"], art_id, placeholder)
        pooled = _received(case["sent"]["pool"], art_id, placeholder)

        assert len(direct["rasters"]) == case["rasters"], f"{case['name']}: {direct}"
        assert pooled == direct, f"{case['name']}: through the pool {pooled}, directly {direct}"
