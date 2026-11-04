"""Playwright E2E: a Data Export node's code writes the file its Download button saves.

A Data Export node holds ``return curio_export(input_0, [!! file_name !!])``
on its Code tab, and opens on its Widgets tab, which shows only its File name,
then its Download button. A File name typed and not yet left is the one
Download takes. A run writes the data on its input to a file, a table as CSV, a GeoDataFrame as
GeoJSON and a raster as GeoTIFF, under the File name with its format's
extension, and the button names that file. Download saves it; with no result
of the node's code and widgets as they are, it first runs the node and the
nodes before it. An empty File name downloads under the name of what feeds the
node. Run All writes the file and never downloads it, and a Download after it
saves the file that run wrote, with no run of its own.

Each download is checked by its bytes: the table and the GeoJSON parsed, the
GeoTIFF opened.

Run::

    CURIO_E2E_USE_EXISTING=1 pytest \\
        utk_curio/backend/tests/test_frontend/test_data_export_e2e.py -v
"""
from __future__ import annotations

import json
import re
import uuid
from typing import TYPE_CHECKING

from playwright.sync_api import expect

from .utils import (
    assert_shows_only_controls,
    connect_nodes,
    dataset_widget_state,
    drag_builtin_to_canvas,
    node_locator,
    require_owner_view,
    require_user_auth,
    run_all_and_wait,
    save_node_closeup,
    set_node_code,
    stub_login_and_enter_workflow,
    wait_for_node_code,
    wait_for_node_done,
    watch_node_run,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

EXPORT_TYPE = "curio.builtin/data-export"
STARTER = "return curio_export(input_0, [!! file_name !!])\n"
WIDGETS_TAB = '.nav-link[data-rr-ui-event-key="widgets"]'
STEM = "data-export"
#: A download that first runs two Python nodes on the server.
DOWNLOAD_TIMEOUT_MS = 240000

TREES_CODE = (
    "import pandas as pd\n\n"
    "return pd.DataFrame({'tree': ['oak', 'elm'], 'height': [10, 12]})\n"
)
TREES_CSV = "tree,height\noak,10\nelm,12\n"

STATIONS_CODE = (
    "import geopandas as gpd\n"
    "from shapely.geometry import Point\n\n"
    "return gpd.GeoDataFrame(\n"
    "    {'name': ['Clark/Lake', 'Grand']},\n"
    "    geometry=[Point(447000, 4637000), Point(447500, 4637800)],\n"
    "    crs='EPSG:32616',\n"
    ")\n"
)

HEIGHTS_CODE = (
    "import numpy as np\n"
    "import rasterio\n"
    "from rasterio.transform import from_origin\n\n"
    "path = curio_output_file('heights.tif')\n"
    "with rasterio.open(\n"
    "    path, 'w', driver='GTiff', width=4, height=3, count=1, dtype='float32',\n"
    "    crs='EPSG:32616', transform=from_origin(440000, 4640000, 30, 30), nodata=-1,\n"
    ") as raster:\n"
    "    raster.write(np.arange(12, dtype='float32').reshape(3, 4), 1)\n"
    "return rasterio.open(path)\n"
)


def _enter(page, base: str, server: str, name: str) -> dict:
    page.emulate_media(reduced_motion="reduce")
    entered = stub_login_and_enter_workflow(
        page, frontend_url=base, backend_url=server,
        name=name, username=f"dx_{uuid.uuid4().hex[:8]}", project_name=name,
    )
    require_owner_view(page)
    page.locator("#tools-menu").wait_for(state="visible", timeout=45000)
    return entered


def _widgets_panel(page, export: str):
    """The export's Widgets tab, which it opens on and which shows only its
    controls: File name, then Download."""
    return node_locator(page, export).locator("[data-widget-controls]")


def _download_button(page, export: str):
    return _widgets_panel(page, export).locator('[data-node-controls] button[aria-label^="Download"]')


def _chain(page, code: str) -> tuple[str, str]:
    """A Python node holding *code*, wired into a fresh Data Export node that
    holds its starter."""
    source = drag_builtin_to_canvas(page, "#tile-computation-analysis", at=(170, 200))
    set_node_code(page, source, code)
    export = drag_builtin_to_canvas(page, "#tile-data-export", at=(760, 220))
    wait_for_node_code(page, export, STARTER)
    # It opens on its Widgets tab, where its File name and Download are, alone.
    expect(node_locator(page, export).locator(WIDGETS_TAB)).to_have_class(re.compile(r"\bactive\b"), timeout=30000)
    assert_shows_only_controls(page, export)
    connect_nodes(page, source, export)
    expect(_download_button(page, export)).to_be_enabled(timeout=30000)
    return source, export


def _name_the_file(page, export: str, name: str) -> None:
    """Type *name* in the Widgets tab's File name and leave it, as a user does."""
    field = _widgets_panel(page, export).get_by_label("File name", exact=True)
    field.fill(name)
    field.press("Tab")
    page.wait_for_function(
        """({ nodeId, name }) => {
            const node = window.__curio_reactFlow.getNodes().find((n) => n.id === nodeId);
            const widget = node && (node.data.widgets || []).find((w) => w && w.name === "file_name");
            return !!widget && widget.value === name;
        }""",
        arg={"nodeId": export, "name": name}, timeout=15000,
    )
    assert dataset_widget_state(page, export, "file_name")["value"] == name


def _download(page, export: str, tmp_path, *, timeout: int = DOWNLOAD_TIMEOUT_MS):
    """Click Download and return the saved file's name and bytes."""
    with page.expect_download(timeout=timeout) as info:
        _download_button(page, export).click()
    download = info.value
    saved = tmp_path / download.suggested_filename
    download.save_as(str(saved))
    return download.suggested_filename, saved.read_bytes()


def test_a_table_downloads_as_csv_under_its_file_name_running_the_nodes_before_it_first(
    app_frontend: "FrontendPage", current_server: str, page, tmp_path,
):
    require_user_auth()
    _enter(page, app_frontend.base_url, current_server, "Data Export table")
    source, export = _chain(page, TREES_CODE)
    # Typed and not left: Download takes it all the same.
    _widgets_panel(page, export).get_by_label("File name", exact=True).fill("trees")
    # Nothing has run yet: the button names no file.
    expect(_download_button(page, export)).to_have_attribute("aria-label", "Download")

    name, body = _download(page, export, tmp_path)

    assert name == "trees.csv"
    assert body.decode("utf-8") == TREES_CSV
    assert dataset_widget_state(page, export, "file_name")["value"] == "trees"
    # The click ran the node and the one before it, and the button names the file.
    wait_for_node_done(page, source)
    wait_for_node_done(page, export, node_type=EXPORT_TYPE)
    expect(_download_button(page, export)).to_have_text("Download trees.csv", timeout=30000)
    # The run left the node on its Widgets tab.
    expect(node_locator(page, export).locator(WIDGETS_TAB)).to_have_class(re.compile(r"\bactive\b"))
    page.mouse.move(5, 5)
    save_node_closeup(page, STEM, export, test_name=f"{STEM}_after_a_download")


def test_a_geodataframe_downloads_as_geojson_whatever_extension_its_file_name_has(
    app_frontend: "FrontendPage", current_server: str, page, tmp_path,
):
    require_user_auth()
    _enter(page, app_frontend.base_url, current_server, "Data Export geodataframe")
    _source, export = _chain(page, STATIONS_CODE)
    _name_the_file(page, export, "stations.csv")

    name, body = _download(page, export, tmp_path)

    assert name == "stations.geojson"
    document = json.loads(body.decode("utf-8"))
    assert document["type"] == "FeatureCollection"
    assert [feature["properties"]["name"] for feature in document["features"]] == ["Clark/Lake", "Grand"]
    assert [feature["geometry"]["coordinates"] for feature in document["features"]] == [
        [447000.0, 4637000.0], [447500.0, 4637800.0],
    ]
    assert "32616" in json.dumps(document.get("crs")), document.get("crs")


def test_a_raster_downloads_as_a_geotiff_named_after_the_node_feeding_it(
    app_frontend: "FrontendPage", current_server: str, page, tmp_path,
):
    import numpy as np
    from rasterio.io import MemoryFile
    from rasterio.transform import from_origin

    require_user_auth()
    _enter(page, app_frontend.base_url, current_server, "Data Export raster")
    _source, export = _chain(page, HEIGHTS_CODE)
    # File name left empty: the file is named after what feeds the node.

    name, body = _download(page, export, tmp_path)

    assert name == "Python_Computation.tif"
    with MemoryFile(body) as memory, memory.open() as raster:
        assert raster.driver == "GTiff"
        assert (raster.width, raster.height, raster.crs.to_epsg()) == (4, 3, 32616)
        assert raster.transform == from_origin(440000, 4640000, 30, 30)
        np.testing.assert_array_equal(raster.read(1), np.arange(12, dtype="float32").reshape(3, 4))


def test_run_all_writes_the_file_and_downloads_nothing_and_download_then_saves_it_without_a_run(
    app_frontend: "FrontendPage", current_server: str, page, tmp_path,
):
    require_user_auth()
    _enter(page, app_frontend.base_url, current_server, "Data Export run all")
    _source, export = _chain(page, TREES_CODE)
    _name_the_file(page, export, "trees")
    downloads = []
    page.on("download", lambda download: downloads.append(download.suggested_filename))

    run_all_and_wait(page, timeout_ms=DOWNLOAD_TIMEOUT_MS)
    wait_for_node_done(page, export, node_type=EXPORT_TYPE)
    # The run wrote the file: the button names it.
    expect(_download_button(page, export)).to_have_text("Download trees.csv", timeout=30000)
    page.wait_for_timeout(2000)
    assert downloads == [], f"Run All downloaded {downloads}"

    # Download saves the file the run wrote: the node's result is current, so
    # nothing runs again.
    watch_node_run(page, export)
    name, body = _download(page, export, tmp_path, timeout=60000)

    assert (name, body.decode("utf-8")) == ("trees.csv", TREES_CSV)
    assert downloads == ["trees.csv"]
    ran = page.evaluate("(id) => !!((window.__curioNodeRunWatch || {})[id] || {}).started", export)
    assert not ran, "Download ran the node again, though Run All had just written its file"
