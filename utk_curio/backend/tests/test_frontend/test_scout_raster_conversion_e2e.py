"""SCOUT's building rasterizer on the canvas, drawn by an Autark map (#662, step 17).

The shipped test dataflow ``BuildingRasters.json``: four buildings built in
code, the ``scout.raster-conversion@1`` package's Rasterize Buildings node with
the widgets its template declares, and an Autark map whose document draws
``input_0``, band ``band_1``. The map is wired straight to the package node, so
it reads the first part of the node's ``(mosaic, tiles)``, a raster, through the
Autark node's raster path (#718); no node in between picks the raster out.

The package is in every account's store and its libraries are installed
because the stack starts with ``--with-examples`` and this dataflow declares
the package.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_scout_raster_conversion_e2e.py -v
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from .utils import (
    REPO_ROOT,
    api_json,
    assert_autark_map_drawn,
    play_node,
    require_owner_view,
    require_project_page,
    require_user_auth,
    stub_login_and_enter_workflow,
    wait_for_node_done,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

DATAFLOW = Path(REPO_ROOT) / "docs" / "examples" / "dataflows" / "BuildingRasters.json"
PACKAGE_DIR = "scout.raster-conversion@1"
RASTER_TYPE = "scout.raster-conversion/rasterize-buildings"
MAP_TYPE = "curio.builtin/autk-grammar"


def test_the_package_node_rasterizes_buildings_and_a_map_draws_its_mosaic(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
):
    require_project_page()
    require_user_auth()
    spec = json.loads(DATAFLOW.read_text(encoding="utf-8"))
    node_of = {node["type"]: node["id"] for node in spec["dataflow"]["nodes"]}
    errors: list[str] = []
    page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
    session = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Building Rasters",
        username="scout_building_rasters",
        project_name=spec["dataflow"]["name"],
        project_spec=spec,
    )
    require_owner_view(page)
    store = [p.get("dirName") for p in api_json(f"{current_server}/api/packages", session["token"])["packages"]]
    assert PACKAGE_DIR in store, (
        f"{PACKAGE_DIR} is not in the account's store {store}: start the stack --with-examples"
    )

    # Plays the loader and the package node first, then the map.
    play_node(page, node_of[MAP_TYPE])
    wait_for_node_done(page, node_of[RASTER_TYPE], node_type=RASTER_TYPE)
    wait_for_node_done(page, node_of[MAP_TYPE], node_type=MAP_TYPE)
    assert_autark_map_drawn(
        page, node_of[MAP_TYPE], timeout=60000, attach_as="SCOUT's building height mosaic on an Autark map",
    )
    assert not [e for e in errors if "[autk-grammar] node error" in e], errors
