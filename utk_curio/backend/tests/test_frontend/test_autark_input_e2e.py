"""Playwright E2E: the Autark node reads its input the way the Vega-Lite node does.

A fresh Autark node opens empty; wired to a loader it says the loader has not
run, and when the loader runs it fills with a starter document chosen from the
input (``utils/autkDefaultSpec.ts``). An input it cannot draw is refused with the
reason, in the node body and in its error, instead of an empty map under a green
Done. A DataFrame with a geometry column is drawn.

The first test needs no WebGPU. The others run the Autark node, which does: they
skip without an adapter unless ``CURIO_REQUIRE_HARDWARE_WEBGPU=1`` (CI's GPU job).

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_autark_input_e2e.py -v
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

import pytest

from .utils import (
    node_locator,
    play_node,
    read_node_error_text,
    require_owner_view,
    require_project_page,
    require_user_auth,
    run_all_and_wait,
    run_node_and_wait,
    stub_login_and_enter_workflow,
    wait_for_node_settled,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

LOADER_ID = "autk-input-loader"
AUTK_ID = "autk-input-map"
MAP_ON_UPSTREAM = json.dumps({"map": {"layerRefs": [{"dataRef": "upstream"}]}}, indent=2)

GDF_LOADER = (
    "import geopandas as gpd\n"
    "from shapely.geometry import Point\n"
    "\n"
    "return gpd.GeoDataFrame(\n"
    '    {"pop": [1, 2, 3]},\n'
    "    geometry=[Point(-87.63, 41.88), Point(-87.62, 41.89), Point(-87.61, 41.87)],\n"
    '    crs="EPSG:4326",\n'
    ")\n"
)
DF_WITHOUT_GEOMETRY = (
    "import pandas as pd\n"
    "\n"
    'return pd.DataFrame({"zone": ["n", "s"], "pop": [1, 2]})\n'
)
DF_WITH_GEOMETRY = (
    "import geopandas as gpd\n"
    "import pandas as pd\n"
    "from shapely.geometry import Point\n"
    "\n"
    "gdf = gpd.GeoDataFrame(\n"
    '    {"pop": [1, 2]},\n'
    "    geometry=[Point(-87.63, 41.88), Point(-87.62, 41.89)],\n"
    '    crs="EPSG:4326",\n'
    ")\n"
    "return pd.DataFrame(gdf)\n"
)

_GRAMMAR_EDITOR_JS = """(nodeId) => {
    const editors = (window.monaco && window.monaco.editor.getEditors()) || [];
    const ed = editors.find((e) => {
        const model = e.getModel();
        const path = model && model.uri && model.uri.path;
        return !!path && path.includes(`grammar-${nodeId}`);
    });
    return ed ? ed.getValue() : null;
}"""


def _spec(loader_code: str, autark_content: str) -> dict:
    node = lambda node_id, node_type, x, content: {  # noqa: E731
        "id": node_id, "type": node_type, "x": x, "y": 0, "content": content,
        "in": "DEFAULT", "out": "DEFAULT", "goal": "", "metadata": {"keywords": []},
    }
    return {
        "dataflow": {
            "name": "Autark input",
            "task": "",
            "timestamp": 1789193389280,
            "provenance_id": "Autark input",
            "nodes": [
                node(LOADER_ID, "curio.builtin/data-loading", 0, loader_code),
                node(AUTK_ID, "curio.builtin/autk-grammar", 645, autark_content),
            ],
            "edges": [{
                "id": f"reactflow__edge-{LOADER_ID}out-{AUTK_ID}in",
                "source": LOADER_ID,
                "target": AUTK_ID,
            }],
        }
    }


def _open(page, app_frontend, current_server, *, username: str, spec: dict) -> None:
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Autark Input",
        username=username,
        project_name="Autark input",
        project_spec=spec,
    )
    require_owner_view(page)
    for node_id in (LOADER_ID, AUTK_ID):
        node_locator(page, node_id).wait_for(state="visible", timeout=45000)


def _require_webgpu(page) -> None:
    has_adapter = bool(page.evaluate(
        "async () => !!(navigator.gpu && await navigator.gpu.requestAdapter())"
    ))
    if not has_adapter:
        if os.environ.get("CURIO_REQUIRE_HARDWARE_WEBGPU") == "1":
            pytest.fail("CURIO_REQUIRE_HARDWARE_WEBGPU=1 but this browser has no WebGPU adapter")
        pytest.skip("running an Autark node needs a WebGPU adapter; this browser has none")


def _empty_reason(page, node_id: str) -> str | None:
    return node_locator(page, node_id).locator("[data-curio-node-empty]").first.get_attribute(
        "data-curio-node-empty", timeout=15000,
    )


def _open_output(page, node_id: str) -> None:
    # A finished run already shows the Output pane, and the node's outcome
    # banner can sit over the tab, so click only when it is not the active one.
    tab = node_locator(page, node_id).locator('.nav-link[data-rr-ui-event-key="output"]').first
    tab.wait_for(state="visible", timeout=15000)
    if "active" not in (tab.get_attribute("class") or ""):
        tab.dispatch_event("click")


def test_a_fresh_autark_node_fills_from_its_input(
    app_frontend: "FrontendPage", current_server: str, page,
):
    _open(page, app_frontend, current_server, username="autark_input_starter", spec=_spec(GDF_LOADER, ""))

    # An edge alone carries no schema: nothing is written, and the body says
    # what a Vega-Lite chart says in the same place.
    before = page.evaluate(_GRAMMAR_EDITOR_JS, AUTK_ID)
    assert before is None or before.strip() in ("", "{}"), f"filled before its input ran: {before!r}"
    _open_output(page, AUTK_ID)
    assert _empty_reason(page, AUTK_ID) == "upstream-not-run"

    run_node_and_wait(page, LOADER_ID, node_type="DATA_LOADING", timeout_ms=120000)
    page.wait_for_function(
        "(nodeId) => { const v = (" + _GRAMMAR_EDITOR_JS + ")(nodeId); return !!v && v.includes('layerRefs'); }",
        arg=AUTK_ID,
        timeout=60000,
    )
    starter = json.loads(page.evaluate(_GRAMMAR_EDITOR_JS, AUTK_ID))
    assert starter == {
        "map": {"layerRefs": [{
            "dataRef": "upstream",
            "getFnv": "pop",
            "getFnvType": "quantitative",
            "colorMapInterpolator": "interpolateViridis",
        }]},
    }, starter


def test_a_dataframe_without_geometry_is_refused_with_the_reason(
    app_frontend: "FrontendPage", current_server: str, page,
):
    _open(page, app_frontend, current_server, username="autark_input_refused",
          spec=_spec(DF_WITHOUT_GEOMETRY, MAP_ON_UPSTREAM))
    _require_webgpu(page)

    run_node_and_wait(page, LOADER_ID, node_type="DATA_LOADING", timeout_ms=120000)
    play_node(page, AUTK_ID)
    status = wait_for_node_settled(page, AUTK_ID, node_type="autk-grammar", timeout_ms=120000)
    assert status == "error", "an input with no geometry must not end in Done"

    error = read_node_error_text(node_locator(page, AUTK_ID)) or ""
    assert "upstream has no geometry column" in error, error
    assert "not at fault" in error, error
    _open_output(page, AUTK_ID)
    assert _empty_reason(page, AUTK_ID) == "geometry-unresolved"


def test_a_dataframe_with_a_geometry_column_is_drawn(
    app_frontend: "FrontendPage", current_server: str, page,
):
    _open(page, app_frontend, current_server, username="autark_input_dataframe",
          spec=_spec(DF_WITH_GEOMETRY, MAP_ON_UPSTREAM))
    _require_webgpu(page)

    run_all_and_wait(page, timeout_ms=180000)
    status = wait_for_node_settled(page, AUTK_ID, node_type="autk-grammar", timeout_ms=120000)
    detail = read_node_error_text(node_locator(page, AUTK_ID)) if status == "error" else ""
    assert status == "done", f"the map did not draw: {detail}"
