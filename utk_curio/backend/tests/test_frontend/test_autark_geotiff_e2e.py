"""GeoTIFFs through Autark: a ``geotiff`` source drawn on a map and handed on.

A geotiff source loads a raster file through autk-grammar's own data adapter:
the node's run loads it in the sandbox, which loads the grammar's ``./data``
entry and fetches the file from the backend's ``/file/`` route, as it fetches
an OpenStreetMap extract. The file is Niterói's summer surface temperature,
``docs/examples/data/niteroi_lst_verao_2001_2024.tif``: 22 by 15 cells of about
1 km, one band a summer from 2001 to 2024, every cell its own value. The
document loads it beside the city's parks, from ``niteroi.osm.pbf``.

A map draws it as Autark draws any raster, from the node that loads it or
from a node it is handed on to, and a Python node receives it as a
``rasterio`` dataset, after the layers of the node that loaded it, holding
the file's own cells.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_autark_geotiff_e2e.py -v
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

AUTARK_TYPE = "curio.builtin/autk-grammar"
PYTHON_TYPE = "curio.builtin/python-computation"

#: Niterói's parks, and its summer surface temperature, each cell read as the file holds it.
DATA = [
    {"type": "osm", "pbfFileUrl": "docs/examples/data/niteroi.osm.pbf", "outputTableName": "table_osm",
     "queryArea": {"geocodeArea": "Rio de Janeiro", "areas": ["Niterói"]},
     "autoLoadLayers": {"layers": ["parks"]}},
    {"type": "geotiff", "geotiffFileUrl": "docs/examples/data/niteroi_lst_verao_2001_2024.tif",
     "outputTableName": "lst", "resampleMethod": "nearest"},
]

#: The summer of 2024, drawn under the parks.
MAP = {"layerRefs": [
    {"dataRef": "lst", "getFnv": "band_24", "colorMapInterpolator": "interpolateYlOrRd",
     "title": "Summer surface temperature, 2024 (°C)"},
    {"dataRef": "table_osm_parks", "color": "#2ca02c"},
]}

#: The Python node checks what it was handed against the file itself, so a
#: lost band, a flipped row or a changed cell fails the node.
PYTHON_READS_GEOTIFF = '''import numpy as np
import rasterio

rasters = [item for item in input_0 if isinstance(item, rasterio.io.DatasetReader)]
assert len(rasters) == 1, input_0
lst = rasters[0]
assert lst.crs.to_epsg() == 3395, lst.crs
with rasterio.open("docs/examples/data/niteroi_lst_verao_2001_2024.tif") as tif:
    assert (lst.width, lst.height, lst.count) == (tif.width, tif.height, tif.count), (lst.shape, tif.shape)
    assert np.array_equal(lst.read(), tif.read()), "the cells are not the file's"
layers = [item["name"] for item in input_0 if isinstance(item, dict)]
summary = f"geotiff {lst.width}x{lst.height}x{lst.count} EPSG:{lst.crs.to_epsg()} holds the file's cells beside {layers}"
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
        name="Autark GeoTIFF",
        username=username,
        project_name=spec["dataflow"]["name"],
        project_spec=spec,
    )
    require_owner_view(page)
    return errors


def test_a_geotiff_the_document_loads_draws_on_its_map(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
):
    drawer = "geotiff-own-map"
    errors = _enter(page, app_frontend, current_server, username="autark_geotiff_own", spec=_spec(
        "AutarkGeotiffOnItsMap",
        [_node(drawer, AUTARK_TYPE, 120, 160, json.dumps({"data": DATA, "map": MAP}, indent=2))],
        [],
    ))

    # Fails with the node's own error text if the GeoTIFF is not loaded or drawn.
    play_node(page, drawer)
    wait_for_node_done(page, drawer, node_type=AUTARK_TYPE)
    assert_autark_map_drawn(page, drawer, timeout=60000, attach_as="a GeoTIFF on its own node's map")
    assert not [e for e in errors if "[autk-grammar] node error" in e], errors


def test_a_geotiff_a_data_node_hands_on_draws_on_a_map_and_reaches_python_as_rasterio(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
):
    loader, drawer, reader = "geotiff-data", "geotiff-map", "geotiff-python"
    errors = _enter(page, app_frontend, current_server, username="autark_geotiff_handed", spec=_spec(
        "AutarkGeotiffHandedOn",
        [
            _node(loader, AUTARK_TYPE, 120, 160, json.dumps({"data": DATA}, indent=2)),
            _node(drawer, AUTARK_TYPE, 820, 40, json.dumps({"map": MAP}, indent=2)),
            _node(reader, PYTHON_TYPE, 820, 520, PYTHON_READS_GEOTIFF),
        ],
        [_edge(loader, drawer), _edge(loader, reader)],
    ))

    # Plays the data node first, then the map.
    play_node(page, drawer)
    wait_for_node_done(page, drawer, node_type=AUTARK_TYPE)
    assert_autark_map_drawn(page, drawer, timeout=60000, attach_as="a handed-on GeoTIFF on an Autark map")

    play_node(page, reader)
    wait_for_node_done(page, reader, node_type=PYTHON_TYPE)
    assert ("geotiff 22x15x24 EPSG:3395 holds the file's cells beside ['table_osm_parks']"
            in read_node_output_text(page, reader))
    assert not [e for e in errors if "[autk-grammar] node error" in e], errors
