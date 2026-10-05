"""Playwright E2E: two scenarios' rasters compared in Difference, on an Autark map (#662).

Two scenarios each hold one Python node that writes a raster from the small
committed GeoTIFF of #718 (``data/autark_raster_utm16n.tif``, 40 by 30 cells
of 100 m in UTM zone 16N, nine of them nodata): "Baseline" scales it by its
factor widget, 1, and "Twice as tall", its copy, by 2. A Compare Scenarios
node, pinned to the dashboard, stands beside them. This drives the whole path
in a browser:

1. Both outcomes run, then go into the node's circles: they are two rasters,
   so the node picks Difference and writes its code for it.
2. Run All subtracts them in the sandbox's Node process, through Autark: the
   node's output is a raster envelope whose cells are comparison minus
   reference, the original raster itself, nodata kept; and the node maps it
   through the Autark node's map code.
3. Compare as switches the node to Chart and back: its code follows, and the
   choice is saved.
4. The dashboard maps the pinned difference from the saved output, with no run.
5. A reopen maps it again from the saved output, and writes nothing.

Its close-up is the frame.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_compare_difference_e2e.py -v
"""

from __future__ import annotations

import base64
import math
import struct
import time
from typing import TYPE_CHECKING

from .test_multi_input_e2e import _wait_for_circles
from .utils import (
    api_json,
    assert_autark_map_drawn,
    connect_nodes,
    frame_nodes,
    load_artifact_as_dict,
    node_locator,
    play_node,
    read_node_code,
    read_node_error_text,
    require_owner_view,
    require_project_page,
    require_user_auth,
    run_all_and_wait,
    save_dataflow,
    save_node_closeup,
    stub_login_and_enter_workflow,
    wait_for_node_done,
    wait_for_node_settled,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

COMPARE_TYPE = "curio.builtin/compare-scenarios"
PYTHON_TYPE = "curio.builtin/computation-analysis"
BASE = "cdf-base"
TALL = "cdf-tall"
COMPARE = "cdf-compare"
BASELINE = {"scenario": "s-base", "name": "Baseline", "color": "#2a9d8f"}
TWICE = {"scenario": "s-tall", "name": "Twice as tall", "color": "#e76f51"}

#: The committed raster, scaled by the node's factor and written to a file of
#: the node's own, which it returns as a rasterio dataset.
RASTER_CODE = (
    "import rasterio\n"
    "with rasterio.open('utk_curio/backend/tests/test_frontend/data/autark_raster_utm16n.tif') as source:\n"
    "    profile = source.profile\n"
    "    band = source.read(1, masked=True) * [!! factor !!]\n"
    "path = curio_output_file('compare-difference-[!! factor !!].tif')\n"
    "with rasterio.open(path, 'w', **profile) as target:\n"
    "    target.write(band.filled(profile['nodata']).astype('float32'), 1)\n"
    "return rasterio.open(path)\n"
)

# The lines the node writes in Difference and in Chart (utils/compare/compareCode.ts).
ENTRY_LINES = (
    '    ("s-base", "Baseline", [!! input 0 !!]),',
    '    ("s-tall", "Twice as tall", [!! input 1 !!]),',
)
DIFFERENCE_LINES = ("return curio_difference_scenarios([", *ENTRY_LINES)
STACK_LINES = ("return curio_stack_scenarios([", *ENTRY_LINES)


def _factor(value: int) -> dict:
    return {"widgets": [{"name": "factor", "type": "number", "default": 1, "value": value}]}


def _spec() -> dict:
    def node(node_id, node_type, x, y, content, title=None, metadata=None, **fields):
        saved = {
            "id": node_id, "type": node_type, "x": x, "y": y, "content": content,
            "in": "DEFAULT", "out": "DEFAULT", "goal": "",
            "metadata": {"keywords": [], **(metadata or {})}, **fields,
        }
        if title:
            saved["title"] = title
        return saved

    return {
        "dataflow": {
            "name": "Compare Difference",
            "task": "",
            "timestamp": 1789193389280,
            "provenance_id": "Compare Difference",
            "nodes": [
                node(BASE, PYTHON_TYPE, 0, 0, RASTER_CODE, "Raster", _factor(1)),
                node(TALL, PYTHON_TYPE, 0, 520, RASTER_CODE, "Raster", {**_factor(2), "copiedFrom": [BASE]}),
                node(COMPARE, COMPARE_TYPE, 760, 160, "", dashboardPinned=True),
            ],
            "edges": [],
            "scenarios": [
                {"id": "s-base", "name": "Baseline", "color": "#2a9d8f", "nodes": [BASE]},
                {"id": "s-tall", "name": "Twice as tall", "color": "#e76f51", "nodes": [TALL]},
            ],
        }
    }


def _wait_for_code(page, node_id: str, lines, timeout_s: float = 15.0) -> str:
    deadline = time.time() + timeout_s
    code = ""
    while time.time() < deadline:
        code = read_node_code(page, node_id)
        if all(line in code for line in lines):
            return code
        page.wait_for_timeout(250)
    raise AssertionError(f"the Compare Scenarios node did not write {lines[0]!r} for its inputs:\n{code}")


_OUTPUT_ARTIFACT_JS = """(id) => {
    const node = window.__curio_reactFlow.getNodes().find((n) => n.id === id);
    const content = node && node.data && node.data.output && node.data.output.content;
    const match = typeof content === "string" ? content.match(/Saved to file: (\\S+)/) : null;
    return match ? match[1] : null;
}"""

# The view the body shows, and where its map stands: "drawing", "drawn" or
# "problem" (components/compare/CompareMap.tsx).
_MAP_STATE_JS = """(id) => {
    const node = document.querySelector(`.react-flow__node[data-id="${id}"]`);
    const body = node && node.querySelector("[data-compare-mode]");
    const map = node && node.querySelector("[data-compare-map-state]");
    if (!body) return null;
    return [body.getAttribute("data-compare-mode"), map ? map.getAttribute("data-compare-map-state") : null];
}"""


def _assert_difference_mapped(page, node_id: str, attach_as: str) -> None:
    """The body is in Difference, its map's run settled with no problem, and the
    node's canvas holds a drawn map."""
    deadline = time.time() + 90
    state = None
    while time.time() < deadline:
        state = page.evaluate(_MAP_STATE_JS, node_id)
        if state and state[1] in ("drawn", "problem"):
            break
        page.wait_for_timeout(250)
    problem = node_locator(page, node_id).locator("[data-compare-map-problem]").all_inner_texts()
    assert state == ["difference", "drawn"], f"the difference map ended {state!r}: {problem}"
    assert_autark_map_drawn(page, node_id, timeout=60000, attach_as=attach_as)


def _band(envelope: dict) -> list[float]:
    """The envelope's one band, rows from south to north (utils/raster/rasterWire.ts)."""
    properties = envelope["data"]["features"][0]["properties"]
    raw = base64.b64decode(properties["band_1"]["float32le"])
    return list(struct.unpack(f"<{len(raw) // 4}f", raw))


def test_two_rasters_are_compared_in_difference_and_mapped(
    app_frontend: "FrontendPage", current_server: str, page,
):
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    spec = _spec()
    session = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Compare Difference",
        username="compare_difference_e2e",
        project_name="Compare Difference",
        project_spec=spec,
    )
    require_owner_view(page)
    project_id = session["project"]["id"]
    for node in spec["dataflow"]["nodes"]:
        node_locator(page, node["id"]).wait_for(state="visible", timeout=45000)

    # 1. Both outcomes run, then go into the circles: two rasters, so Difference.
    for outcome in (BASE, TALL):
        play_node(page, outcome)
        wait_for_node_done(page, outcome, node_type=PYTHON_TYPE)
    _wait_for_circles(page, COMPARE, ["in"])
    frame_nodes(page, [BASE, COMPARE])
    connect_nodes(page, BASE, COMPARE)
    _wait_for_circles(page, COMPARE, ["in", "in_1"])
    frame_nodes(page, [TALL, COMPARE])
    connect_nodes(page, TALL, COMPARE, target_handle="in_1")
    _wait_for_code(page, COMPARE, DIFFERENCE_LINES)

    # 2. Run All subtracts them through Autark, and the node maps the difference.
    run_all_and_wait(page, timeout_ms=240000)
    compare = node_locator(page, COMPARE)
    status = wait_for_node_settled(page, COMPARE, node_type=COMPARE_TYPE, timeout_ms=120000)
    assert status == "done", f"Compare Scenarios did not subtract its inputs: {read_node_error_text(compare)}"
    frame_nodes(page, [COMPARE])
    _assert_difference_mapped(page, COMPARE, "the difference of two rasters")
    artifact = page.evaluate(_OUTPUT_ARTIFACT_JS, COMPARE)
    assert artifact, "Compare Scenarios shows no saved output"
    stored = load_artifact_as_dict(artifact)
    envelope = stored.get("data") if stored.get("dataType") == "dict" else stored
    assert envelope["dataType"] == "raster", stored.get("dataType")
    assert envelope["data"]["grid"] == {
        "crs": "EPSG:32616", "width": 40, "height": 30,
        "originX": 447000, "originY": 4637000, "resX": 100, "resY": -100,
    }, envelope["data"]["grid"]
    cells = _band(envelope)
    assert len(cells) == 1200
    # Twice the raster minus the raster is the raster, sign and all: its south
    # row starts 14.5, 14.75, 15, 15.25; its north row, three nodata cells and
    # then 0.75, 1, 1.25. Nodata on either side is nodata in the difference.
    assert [round(v, 4) for v in cells[0:4]] == [14.5, 14.75, 15.0, 15.25], cells[0:4]
    assert all(math.isnan(v) for v in cells[1160:1163]), cells[1160:1163]
    assert [round(v, 4) for v in cells[1163:1166]] == [0.75, 1.0, 1.25], cells[1163:1166]
    assert sum(1 for v in cells if math.isnan(v)) == 9

    # 3. Compare as: Chart, then Difference again. The code follows the view.
    switch = compare.locator('select[aria-label="Compare as"]')
    switch.select_option("chart")
    _wait_for_code(page, COMPARE, STACK_LINES)
    compare.locator('select[aria-label="Compare as"]').select_option("difference")
    content = _wait_for_code(page, COMPARE, DIFFERENCE_LINES)
    save_dataflow(page)
    project = api_json(f"{current_server}/api/projects/{project_id}", session["token"])
    saved = {n["id"]: n for n in project["spec"]["dataflow"]["nodes"]}
    assert saved[COMPARE]["metadata"]["compareScenarios"] == {
        "inputs": [BASELINE, TWICE],
        "mode": "difference",
    }, saved[COMPARE]["metadata"]
    assert saved[COMPARE]["content"] == content
    recorded = {output["node_id"] for output in project["outputs"]}
    assert COMPARE in recorded, f"the save recorded the outputs of {sorted(recorded)}, not the pinned node's own"

    # 4. The dashboard maps the pinned difference from the saved output, no run.
    page.goto(f"{app_frontend.base_url}/dashboard/{project_id}")
    page.get_by_test_id("open-dataflow-link").wait_for(state="visible", timeout=45000)
    node_locator(page, COMPARE).wait_for(state="visible", timeout=45000)
    _assert_difference_mapped(page, COMPARE, "the difference on the dashboard")

    # 5. Reopened, it maps the saved difference with no run and writes nothing.
    page.goto(f"{app_frontend.base_url}/projects")
    page.wait_for_load_state("domcontentloaded")
    page.goto(f"{app_frontend.base_url}/dataflow/{project_id}")
    compare = node_locator(page, COMPARE)
    compare.wait_for(state="visible", timeout=45000)
    assert _wait_for_code(page, COMPARE, DIFFERENCE_LINES) == content
    frame_nodes(page, [COMPARE])
    compare.locator('.nav-link[data-rr-ui-event-key="output"]').click()
    _assert_difference_mapped(page, COMPARE, "the difference after a reopen")
    assert compare.locator('select[aria-label="Compare as"]').input_value() == "difference"
    assert page.locator("[data-curio-save-state]").first.get_attribute("data-curio-save-state") == "saved"

    save_node_closeup(
        page, "compare-difference", COMPARE,
        test_name="test_two_rasters_are_compared_in_difference_and_mapped",
        sweep_toasts=True,
    )
