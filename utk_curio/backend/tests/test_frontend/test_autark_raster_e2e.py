"""Rasters through Autark, as it is (#662, step 8).

A Python node's raster is drawn on an Autark map: the node returns a rasterio
dataset of a small committed GeoTIFF (``data/autark_raster_utm16n.tif``, 40 by
30 cells of 100 m in UTM zone 16N, so a raster read as EPSG:4326 would not
place), the map node asks the sandbox for its bytes and loads them with
autk-db's ``loadGeoTiff``, and autk-map draws them as a raster layer. A flat
Autark map does not zoom to its layers, so both rasters here are a few
kilometres across, enough to fill a good part of the map.

A raster an Autark node hands on travels as autk-db's ``getRaster`` collection
in an envelope. A JavaScript node stands in for that node here, building one by
hand: an Autark map draws it (written back to GeoTIFF bytes for autk-db), and
a Python node receives it as a rasterio dataset on the same grid.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_autark_raster_e2e.py -v
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

from .utils import (
    assert_autark_map_drawn,
    play_node,
    read_node_output_text,
    require_owner_view,
    require_project_page,
    require_user_auth,
    stub_login_and_enter_workflow,
    wait_for_node_done,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

MAP_TYPE = "curio.builtin/autk-grammar"
PYTHON_TYPE = "curio.builtin/computation-analysis"

MAP_SPEC = {"map": {"layerRefs": [{"dataRef": "input_0", "getFnv": "band_1"}]}}

PYTHON_RASTER = '''import rasterio

return rasterio.open("utk_curio/backend/tests/test_frontend/data/autark_raster_utm16n.tif")
'''

#: What an Autark node hands on for a 64 by 48 raster of 60 m cells: the
#: getRaster collection, its band as base64 of little-endian float32 with rows
#: from south to north, and the grid it lies on (utils/raster/rasterWire.ts).
JS_ENVELOPE = '''const width = 64;
const height = 48;
const values = new Float32Array(width * height);
for (let row = 0; row < height; row++) {
    for (let col = 0; col < width; col++) values[row * width + col] = row * 2 + col;
}
values[0] = NaN;
return {
    dataType: 'raster',
    layerName: 'ramp',
    data: {
        type: 'FeatureCollection',
        bbox: [0, 0, 0, 0],
        grid: { crs: 'EPSG:32616', width, height, originX: 447000, originY: 4637000, resX: 60, resY: -60 },
        features: [{
            type: 'Feature',
            geometry: null,
            properties: {
                rasterResX: width,
                rasterResY: height,
                bands: [{ id: 'band_1', label: 'band_1' }],
                band_1: { float32le: Buffer.from(values.buffer).toString('base64') },
            },
        }],
    },
};
'''

#: The Python node checks what it was handed, so a wrong grid fails the node.
PYTHON_READS_RASTER = '''import math
import rasterio

assert isinstance(input_0, rasterio.io.DatasetReader), type(input_0)
assert input_0.crs.to_epsg() == 32616, input_0.crs
assert (input_0.width, input_0.height) == (64, 48), (input_0.width, input_0.height)
assert tuple(input_0.transform)[:6] == (60.0, 0.0, 447000.0, 0.0, -60.0, 4637000.0), input_0.transform
band = input_0.read(1)
# Row 0 of the collection is the south edge, the last row a GeoTIFF reads.
assert math.isnan(band[47, 0]), band[47, 0]
assert band[47, 1] == 1.0 and band[0, 63] == 157.0, (band[47, 1], band[0, 63])
summary = f"rasterio {input_0.width}x{input_0.height} EPSG:{input_0.crs.to_epsg()}"
print(summary)
return summary
'''


def _node(node_id: str, node_type: str, x: int, y: int, content: str) -> dict:
    return {
        "id": node_id, "type": node_type, "x": x, "y": y, "content": content,
        "in": "DEFAULT", "out": "DEFAULT", "goal": "", "metadata": {"keywords": []},
    }


def _edge(source: str, target: str) -> dict:
    return {
        "id": f"reactflow__edge-{source}out-{target}in",
        "source": source, "target": target, "sourceHandle": "out", "targetHandle": "in",
    }


def _spec(name: str, nodes: list[dict], edges: list[dict]) -> dict:
    return {"dataflow": {"name": name, "task": "", "nodes": nodes, "edges": edges}}


def _enter(page, app_frontend, current_server, *, username: str, spec: dict) -> list[str]:
    require_project_page()
    require_user_auth()
    errors: list[str] = []
    page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Autark Raster",
        username=username,
        project_name=spec["dataflow"]["name"],
        project_spec=spec,
    )
    require_owner_view(page)
    return errors


def test_a_python_raster_draws_on_an_autark_map(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
):
    raster, drawer = "raster-python", "raster-map"
    errors = _enter(page, app_frontend, current_server, username="autark_raster_py", spec=_spec(
        "AutarkRasterFromPython",
        [
            _node(raster, PYTHON_TYPE, 120, 160, PYTHON_RASTER),
            _node(drawer, MAP_TYPE, 820, 160, json.dumps(MAP_SPEC, indent=2)),
        ],
        [_edge(raster, drawer)],
    ))

    # Plays the Python node first, then the map; fails with the node's own
    # error text (a refused raster names why) if the map does not load it.
    play_node(page, drawer)
    wait_for_node_done(page, drawer, node_type=MAP_TYPE)
    assert_autark_map_drawn(page, drawer, timeout=60000, attach_as="a Python raster on an Autark map")
    assert not [e for e in errors if "[autk-grammar] node error" in e], errors


def test_a_raster_an_autark_node_hands_on_draws_and_reaches_python_as_rasterio(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
):
    handed, drawer, reader = "raster-envelope", "raster-envelope-map", "raster-envelope-python"
    errors = _enter(page, app_frontend, current_server, username="autark_raster_env", spec=_spec(
        "AutarkRasterHandedOn",
        [
            _node(handed, "curio.builtin/js-computation", 120, 160, JS_ENVELOPE),
            _node(drawer, MAP_TYPE, 820, 40, json.dumps(MAP_SPEC, indent=2)),
            _node(reader, PYTHON_TYPE, 820, 520, PYTHON_READS_RASTER),
        ],
        [_edge(handed, drawer), _edge(handed, reader)],
    ))

    play_node(page, drawer)
    wait_for_node_done(page, drawer, node_type=MAP_TYPE)
    assert_autark_map_drawn(page, drawer, timeout=60000, attach_as="a handed-on raster on an Autark map")

    play_node(page, reader)
    wait_for_node_done(page, reader, node_type=PYTHON_TYPE)
    assert "rasterio 64x48 EPSG:32616" in read_node_output_text(page, reader)
    assert not [e for e in errors if "[autk-grammar] node error" in e], errors
