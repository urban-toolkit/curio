"""An Autark map of rows that do not all have a geometry.

A collection's rows are the common case: in a folder of photos and a video,
the video, and any photo that carries no position, has no geometry, and a raster
that is not georeferenced has no footprint. The map draws the rows that have
one. autk-db reads a layer's kind off its first feature, so the case that
matters is a first row without one.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_autark_rows_without_geometry_e2e.py -v
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

from .utils import (
    play_node,
    require_owner_view,
    require_project_page,
    require_user_auth,
    stub_login_and_enter_workflow,
    wait_for_node_done,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

DATA_NODE_ID = "rows-without-geometry-data"
MAP_NODE_ID = "rows-without-geometry-map"
MAP_TYPE = "curio.builtin/autk-grammar"

#: Photos with a position, and first of all a video without one.
ROWS = '''import geopandas as gpd
from shapely.geometry import Point

rows = gpd.GeoDataFrame(
    {
        "name": ["clip_01.mp4", "IMG_0001.jpg", "IMG_0002.jpg", "IMG_0003.jpg"],
        "value": [0, 1, 2, 3],
        "geometry": [None, Point(-87.6278, 41.8826), Point(-87.6240, 41.8840), Point(-87.6300, 41.8790)],
    },
    crs="EPSG:4326",
)

return rows
'''

MAP_SPEC = {
    "map": {
        "layerRefs": [
            {"dataRef": "upstream", "getFnv": "value", "getFnvType": "quantitative", "defaultFnv": 0}
        ]
    }
}


def _spec() -> dict:
    return {
        "dataflow": {
            "name": "AutarkRowsWithoutGeometry",
            "task": "",
            "nodes": [
                {
                    "id": DATA_NODE_ID, "type": "curio.builtin/data-loading",
                    "x": 120, "y": 160, "content": ROWS,
                    "in": "DEFAULT", "out": "DEFAULT", "goal": "", "metadata": {"keywords": []},
                },
                {
                    "id": MAP_NODE_ID, "type": MAP_TYPE,
                    "x": 820, "y": 160, "content": json.dumps(MAP_SPEC, indent=2),
                    "in": "DEFAULT", "out": "DEFAULT", "goal": "", "metadata": {"keywords": []},
                },
            ],
            "edges": [
                {
                    "id": f"reactflow__edge-{DATA_NODE_ID}out-{MAP_NODE_ID}in",
                    "source": DATA_NODE_ID, "target": MAP_NODE_ID,
                    "sourceHandle": "out", "targetHandle": "in",
                }
            ],
        }
    }


def test_an_autark_map_draws_the_rows_that_have_a_geometry(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
):
    require_project_page()
    require_user_auth()

    errors: list[str] = []
    page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Autark Rows",
        username="autark_rows",
        project_name="Autark rows without geometry",
        project_spec=_spec(),
    )
    require_owner_view(page)

    # Plays the data node first, then the map; fails with the node's own
    # error text if the map does not load. A map node reports through its
    # map, so there is no output text to read.
    play_node(page, MAP_NODE_ID)
    wait_for_node_done(page, MAP_NODE_ID, node_type=MAP_TYPE)
    assert not [e for e in errors if "[autk-grammar] node error" in e], errors
