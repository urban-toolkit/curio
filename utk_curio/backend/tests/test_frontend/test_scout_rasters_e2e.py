"""SCOUT's building rasterizer on the canvas, drawn by an Autark map (#662, step 17).

Example 24's chain from SCOUT's buildings to the map of their heights: Data
Loading reads SCOUT's 123 Chicago Loop buildings (the Data Catalog dataset
``data.scout.loop-buildings``), the ``scout.rasters@1`` package's
Rasterize Buildings node runs with the widgets its template declares, and an
Autark map whose document draws ``input_0``, band ``band_1``. The map is wired
straight to the package node, so it reads the node's one raster through the
Autark node's raster path (#718). The example's other nodes, Deep Umbra's
among them, are left out.

The raster the run saved is read back as the sandbox serves it to the map:
SCOUT's four zoom-16 tiles side by side, 512 by 512 cells in EPSG:3395, each
cell a height whose gray level (550 m is level 255) is within one level of the
height tiles SCOUT committed for the same buildings
(``test_packages/fixtures/scout/A_rasters``). So every building's height is
checked where it stands, and the map drawn from the raster holds more colours
than the eight ``assert_autark_map_drawn`` takes for a map: a blank map, or one
raster value spread over the canvas, holds fewer.

The packages are in every account's store and their libraries are installed
because the stack starts with ``--with-examples`` and the example declares the
packages.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_scout_rasters_e2e.py -v
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
    sandbox_auth_header,
    sandbox_base_url,
    stub_login_and_enter_workflow,
    wait_for_node_done,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

EXAMPLE = Path(REPO_ROOT) / "docs" / "examples" / "24-scout-shadow-model-chicago-loop.json"
PACKAGE_DIR = "scout.rasters@1"
LOADER_TYPE = "curio.builtin/data-loading"
RASTER_TYPE = "scout.rasters/rasterize-buildings"
MAP_TYPE = "curio.builtin/autk-grammar"
#: The height tiles SCOUT committed for its example's buildings, which the
#: Data Catalog ships as data.scout.loop-buildings (test_scout_shadow.py).
SCOUT_TILES = Path(REPO_ROOT) / "utk_curio" / "backend" / "tests" / "test_packages" / "fixtures" / "scout" / "A_rasters"
#: The zoom and the north-west tile of SCOUT's four, two by two.
ZOOM, TILE_X, TILE_Y = 16, 16814, 24355
#: The Maximum height widget's default: the height drawn as gray level 255.
MAX_HEIGHT = 550.0
#: The first run imports the rasterizer's libraries, which compile with numba.
RASTER_RUN_MS = 180000

#: The artifact a node's last run saved, from what its output pane says.
_OUTPUT_ARTIFACT_JS = """(id) => {
    const node = window.__curio_reactFlow.getNodes().find((n) => n.id === id);
    const content = node && node.data && node.data.output && node.data.output.content;
    const match = typeof content === "string" ? content.match(/Saved to file: (\\S+)/) : null;
    return match ? match[1] : null;
}"""


def _chain() -> tuple[dict, dict]:
    """Example 24 with only its loader, its Rasterize Buildings node and the
    map that node feeds, and those three nodes' ids by role. The example
    holds three maps, so the map is the one wired to the rasterizer."""
    spec = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    dataflow = spec["dataflow"]
    nodes = {node["id"]: node for node in dataflow["nodes"]}
    (raster,) = [n for n, node in nodes.items() if node["type"] == RASTER_TYPE]
    into = {edge["target"]: edge["source"] for edge in dataflow["edges"]}
    loader = into[raster]
    assert nodes[loader]["type"] == LOADER_TYPE, nodes[loader]["type"]
    maps = [n for n, node in nodes.items() if node["type"] == MAP_TYPE and into.get(n) == raster]
    assert len(maps) == 1, f"example 24 has {len(maps)} maps of Rasterize Buildings' raster"
    ids = {"loader": loader, "raster": raster, "map": maps[0]}
    kept = set(ids.values())
    dataflow["nodes"] = [node for node in dataflow["nodes"] if node["id"] in kept]
    dataflow["edges"] = [e for e in dataflow["edges"] if e["source"] in kept and e["target"] in kept]
    dataflow["name"] = "Building rasters"
    return spec, ids


def _height_raster(page, node_id: str):
    """``(meta, cells, tags)`` of the raster the node's run saved, as the
    sandbox's raster route serves it to an Autark map: its description, its one
    band and its tags."""
    import requests
    from rasterio.io import MemoryFile

    artifact = page.evaluate(_OUTPUT_ARTIFACT_JS, node_id)
    assert artifact, "Rasterize Buildings shows no saved output"
    reply = requests.get(
        f"{sandbox_base_url()}/raster", params={"fileName": artifact}, headers=sandbox_auth_header(), timeout=120,
    )
    assert reply.ok, f"/raster {artifact} -> {reply.status_code}: {reply.text[:500]}"
    meta = json.loads(reply.headers["X-Curio-Raster"])
    with MemoryFile(reply.content) as memory, memory.open() as raster:
        return meta, raster.read(1), raster.tags()


def _gray(path: Path):
    """One of SCOUT's height tiles as gray levels: 8-bit, 256 by 256."""
    import numpy as np
    from PIL import Image

    with Image.open(path) as image:
        assert image.mode == "L" and image.size == (256, 256), (path.name, image.mode, image.size)
        return np.asarray(image).astype(int)


def test_the_package_node_rasterizes_buildings_and_a_map_draws_its_mosaic(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
):
    import numpy as np

    require_project_page()
    require_user_auth()
    spec, ids = _chain()
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
    play_node(page, ids["map"])
    wait_for_node_done(page, ids["raster"], node_type=RASTER_TYPE, timeout_ms=RASTER_RUN_MS)

    # The run's raster: SCOUT's four tiles, each cell a building's height or
    # the ground's, within one gray level of SCOUT's own tile.
    meta, cells, tags = _height_raster(page, ids["raster"])
    assert (meta["crs"], meta["width"], meta["height"], meta["count"]) == ("EPSG:3395", 512, 512, 1), meta
    assert (tags.get("zoom"), tags.get("tile_x"), tags.get("tile_y"), tags.get("max_height")) == (
        str(ZOOM), str(TILE_X), str(TILE_Y), str(MAX_HEIGHT),
    ), tags
    assert not np.isnan(cells).any(), "a tile of the raster is no data, as if no building were near it"
    exact = cells.astype("float64") * (255.0 / MAX_HEIGHT)
    assert np.abs(exact - np.rint(exact)).max() < 1e-3, "the raster's heights are not whole gray levels"
    levels = np.rint(exact).astype(int)
    worst = {}
    for row in range(2):
        for column in range(2):
            name = f"{ZOOM}_{TILE_X + column}_{TILE_Y + row}.png"
            scouts = _gray(SCOUT_TILES / name)
            # Not two blank tiles agreeing: each of SCOUT's holds buildings.
            assert scouts.max() > 0, name
            block = levels[256 * row:256 * (row + 1), 256 * column:256 * (column + 1)]
            worst[name] = int(np.abs(block - scouts).max())
    assert all(level <= 1 for level in worst.values()), (
        f"the raster's heights differ from SCOUT's tiles for the same buildings by up to these gray levels: {worst}"
    )

    wait_for_node_done(page, ids["map"], node_type=MAP_TYPE)
    assert_autark_map_drawn(
        page, ids["map"], timeout=60000, attach_as="SCOUT's building height mosaic on an Autark map",
    )
    assert not [e for e in errors if "[autk-grammar] node error" in e], errors
