"""Playwright E2E: what the guides say can be dragged onto the canvas gets
there when it is dragged with the mouse.

The guides promise these drags: a dataset from the Data Catalog palette or from
a card in the Data Catalog drawer (DATA-CATALOG.md), a model from the Model
Catalog dropdown or the canvas drawer (MODEL-CATALOG.md), and a saved output
from the **Saved outputs** group of the Tools panel's **Data Catalog** dropdown.
``drag_to_canvas`` fires its drop on the canvas itself, so it never meets what
lies over the canvas, and an open catalog drawer's scrim covers the whole
window. These tests press, move and release the mouse, as a person does, and
check that each drop makes the node the guides describe:

* a dataset card from the Data Catalog drawer: a Data Loading node that reads
  the dataset;
* a layer group card from that drawer: a Data Loading node that reads each of
  the group's layers, and runs;
* a model card from the Model Catalog drawer: an Image Segmentation node whose
  code names the model;
* a saved output from the Saved outputs group: a Data Loading node that reads
  it.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_drawer_mouse_drags_e2e.py -v
"""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from playwright.sync_api import expect

from utk_curio.backend.app.datasets.install.installer import computed_dataset_id

from .utils import (
    CANVAS_DROP_TARGET,
    api_json,
    canvas_node_type,
    close_tools_palette,
    drag_to_canvas_with_the_mouse,
    enable_save_output,
    node_locator,
    open_tools_palette,
    read_node_code,
    require_owner_view,
    require_project_page,
    require_user_auth,
    run_node_and_wait,
    set_canvas_zoom,
    stub_login_and_enter_workflow,
    wait_for_drawer_closed,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

BAR = "header[data-curio-menu-bar]"
DATA_DRAWER = '[data-curio-dataset-catalog-drawer="true"]'
MODEL_DRAWER = '[data-curio-model-catalog-drawer="true"]'
# The "Adding..." placeholder is an <article role="status"> with the same id.
CARD = 'article:not([role="status"])'

LOADER_TYPE = "curio.builtin/data-loading"
ANALYSIS_TYPE = "curio.builtin/computation-analysis"
SEGMENTATION = "curio.streetvision/image-segmentation"

BOUNDARY = "data.utk.chicago-boundary"
BOUNDARY_TITLE = "Chicago Boundary"
# The one layer group that ships in the catalog: SCOUT's WRF variables.
WRF_GROUP = "netcdf.scout-wrf"
WRF_LAYERS = (
    "data.scout.wrf-rain",
    "data.scout.wrf-rh2",
    "data.scout.wrf-t2",
    "data.scout.wrf-wdir10",
    "data.scout.wrf-wspd10",
)
DDRNET = "model.curio.ddrnet23-slim"
DDRNET_NAME = "DDRNet23-Slim (street scenes)"

#: Where a card from a drawer is dropped, as an offset from the canvas's
#: top-left corner: left of the 520 px drawer, so under its scrim.
UNDER_THE_SCRIM = (320.0, 220.0)
#: Where a saved output is dropped: right of the open palette, which floats
#: over the left of the canvas, and clear of the producer framed at the top left.
RIGHT_OF_THE_PALETTE = (900.0, 420.0)

PRODUCER = "producer"
PRODUCER_CODE = (
    "import pandas as pd\n"
    'return pd.DataFrame({"tree": ["oak", "elm", "ash"], "height": [12, 9, 15]})\n'
)

_WHAT_IS_AT_JS = """([[x, y], drawer]) => {
    const hit = document.elementFromPoint(x, y);
    return {
        underDrawer: !!hit && !!drawer && !!hit.closest(drawer),
        onCanvas: !!hit && !!hit.closest(".curio-canvas-drop-target") && !hit.closest(".react-flow__node"),
    };
}"""


def _enter(page, app_frontend, current_server, *, project_spec: dict | None = None) -> dict:
    require_project_page()
    require_user_auth()
    # Before navigating: the drawers slide in through useSlideDrawerPresentation,
    # which reads prefers-reduced-motion.
    page.emulate_media(reduced_motion="reduce")
    session = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Drag User",
        username=f"drags_{uuid.uuid4().hex[:10]}",
        project_name="Mouse drags",
        project_spec=project_spec,
    )
    require_owner_view(page)
    page.locator(CANVAS_DROP_TARGET).wait_for(state="visible", timeout=45000)
    page.wait_for_function("() => !!window.__curio_reactFlow", timeout=30000)
    return session


def _client_point(page, at: tuple[float, float]) -> list[float]:
    box = page.locator(CANVAS_DROP_TARGET).bounding_box()
    assert box, f"{CANVAS_DROP_TARGET} has no layout box"
    return [box["x"] + at[0], box["y"] + at[1]]


def _open_drawer(page, name: str, root: str):
    page.locator(BAR).get_by_role("button", name=name, exact=True).click()
    drawer = page.locator(root)
    expect(drawer).to_have_attribute("aria-hidden", "false", timeout=15000)
    # The drop point lies under the scrim, so the drag has to cross it.
    point = _client_point(page, UNDER_THE_SCRIM)
    assert page.evaluate(_WHAT_IS_AT_JS, [point, root])["underDrawer"], (
        f"{point} is not under the {name} drawer's scrim"
    )
    return drawer


def _toast(page, text: str):
    # Not exact: a dataset's toast also holds its "View details" button.
    return page.locator('[aria-label="Notifications"]').get_by_text(text).first


def test_a_dataset_card_dragged_from_the_data_catalog_drawer_becomes_a_data_loading_node(
    app_frontend: "FrontendPage", current_server: str, page,
):
    _enter(page, app_frontend, current_server)
    drawer = _open_drawer(page, "Data Catalog", DATA_DRAWER)
    card = drawer.locator(f'{CARD}[data-dataset-id="{BOUNDARY}"]')
    expect(card).to_have_count(1, timeout=30000)

    node = drag_to_canvas_with_the_mouse(page, card.locator("h3"), at=UNDER_THE_SCRIM)

    assert (canvas_node_type(page, node) or "").split("@")[0] == LOADER_TYPE
    code = read_node_code(page, node)
    assert f'curio_load_data("{BOUNDARY}")' in code, code
    expect(_toast(page, f"Created a Data Loading node for {BOUNDARY_TITLE}.")).to_be_visible(
        timeout=10000
    )


def test_a_layer_group_card_dragged_from_the_data_catalog_drawer_becomes_a_loader_that_runs(
    app_frontend: "FrontendPage", current_server: str, page,
):
    _enter(page, app_frontend, current_server)
    drawer = _open_drawer(page, "Data Catalog", DATA_DRAWER)
    card = drawer.locator(f'{CARD}[data-dataset-id="{WRF_GROUP}"]')
    expect(card).to_have_count(1, timeout=30000)

    node = drag_to_canvas_with_the_mouse(page, card.locator("h3"), at=UNDER_THE_SCRIM)

    assert (canvas_node_type(page, node) or "").split("@")[0] == LOADER_TYPE
    code = read_node_code(page, node)
    # One read per layer, by the layer's own id: no dataset has the group's id.
    missing = [layer for layer in WRF_LAYERS if f'curio_load_data("{layer}")' not in code]
    assert (missing, WRF_GROUP in code) == ([], False), code

    # The drawer's scrim lies over the canvas: close the drawer, then run it.
    page.keyboard.press("Escape")
    wait_for_drawer_closed(page, DATA_DRAWER)
    run_node_and_wait(page, node, node_type=LOADER_TYPE)


def test_a_model_card_dragged_from_the_model_catalog_drawer_becomes_a_node_that_runs_it(
    app_frontend: "FrontendPage", current_server: str, page,
):
    # Street Vision's Image Segmentation runs a model. The stack is started
    # --with-examples, which seeds the package (example 10).
    session = _enter(page, app_frontend, current_server, project_spec={"dataflow": {
        "name": "Mouse drags", "task": "", "nodes": [], "edges": [],
        "packages": ["curio.builtin@1", "curio.streetvision@1"],
    }})
    store = [p.get("dirName") for p in api_json(f"{current_server}/api/packages", session["token"])["packages"]]
    assert "curio.streetvision@1" in store, (
        f"curio.streetvision@1 is not in the account's store {store}: start the stack --with-examples"
    )
    # The drop picks among this dataflow's node kinds: wait until the package's
    # nodes are among them.
    open_tools_palette(page, "packages")
    expect(
        page.locator(f'#packages-palette [data-pkg-template-id^="{SEGMENTATION}"]').first
    ).to_be_attached(timeout=60000)
    close_tools_palette(page, "packages")

    drawer = _open_drawer(page, "Model Catalog", MODEL_DRAWER)
    card = drawer.locator(f'[data-model-id="{DDRNET}"]')
    expect(card).to_have_count(1, timeout=30000)

    node = drag_to_canvas_with_the_mouse(page, card.locator("h3"), at=UNDER_THE_SCRIM)

    assert (canvas_node_type(page, node) or "").startswith(SEGMENTATION), canvas_node_type(page, node)
    code = read_node_code(page, node)
    assert f'curio_load_model("{DDRNET}")' in code, code
    expect(_toast(page, f"Created an Image Segmentation node for {DDRNET_NAME}.")).to_be_visible(
        timeout=10000
    )


def test_a_saved_output_dragged_from_the_data_palette_becomes_a_data_loading_node(
    app_frontend: "FrontendPage", current_server: str, page,
):
    session = _enter(page, app_frontend, current_server, project_spec={"dataflow": {
        "name": "Mouse drags", "task": "", "edges": [], "nodes": [{
            "id": PRODUCER, "type": ANALYSIS_TYPE, "x": 0, "y": 0, "content": PRODUCER_CODE,
            "in": "DEFAULT", "out": "DEFAULT", "goal": "", "metadata": {"keywords": []},
        }],
    }})
    project_id = session["project"]["id"]
    node_locator(page, PRODUCER).wait_for(state="visible", timeout=45000)

    # Run the producer with its save-output toggle on, so its output is saved
    # to the Data Catalog as this dataflow's.
    enable_save_output(page, PRODUCER)
    with page.expect_response(
        lambda r: f"/api/projects/{project_id}" in r.url
        and r.request.method in ("PUT", "POST")
        and PRODUCER in (r.request.post_data or ""),
        timeout=180000,
    ) as saved:
        run_node_and_wait(page, PRODUCER, node_type=ANALYSIS_TYPE)
    assert saved.value.ok, f"the save of the output failed: {saved.value.status}"

    # Frame the producer small at the top left, under the palette, so the drop
    # point to the right of the palette is empty canvas.
    set_canvas_zoom(page, 0.5)
    palette = open_tools_palette(page, "datasets")
    saved_outputs = palette.locator("details").filter(
        has=page.locator("summary", has_text="Saved outputs")
    )
    row = saved_outputs.locator(f'[data-dataset-id="{computed_dataset_id(PRODUCER, project_id)}"]')
    expect(row).to_have_count(1, timeout=30000)
    point = _client_point(page, RIGHT_OF_THE_PALETTE)
    assert page.evaluate(_WHAT_IS_AT_JS, [point, None])["onCanvas"], (
        f"{point} is not on empty canvas"
    )

    node = drag_to_canvas_with_the_mouse(
        page, row.locator('[draggable="true"]'), at=RIGHT_OF_THE_PALETTE
    )

    assert (canvas_node_type(page, node) or "").split("@")[0] == LOADER_TYPE
    code = read_node_code(page, node)
    assert f'curio_load_data("{computed_dataset_id(PRODUCER, project_id)}")' in code, code
