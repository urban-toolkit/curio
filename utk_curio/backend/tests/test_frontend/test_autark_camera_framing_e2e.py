"""Playwright E2E: the map framing check (#773) reads a map its document's
``camera`` turns at the view the node framed it at, then checks the turn.

An Autark node loads nine blocks near the Loop, 100 m squares 50 m apart, each
with its own value, and draws them on a map whose document writes
``"camera": {"zoom": 17, "pitch": 40, "bearing": 30}``: the eye 78 units from
the middle block, 40 degrees from straight down, facing 30 degrees east of
north. That close, the map shows a part of one block, so its drawing, read as
it is, is not framed on its layers: the camera's view is meant to be that way.

``autark_map_framing`` reads such a map at the view the node framed it at,
straight down on its nine blocks, before the camera turned it, and then the
turn: the map stands where the camera puts that framed view. The map shows
its camera's view again once the check is over.

The maps need WebGPU, so this test runs on CI's GPU job and fails without an
adapter.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_autark_camera_framing_e2e.py -v
"""

from __future__ import annotations

import json
import math

from .utils import (
    AUTK_MAP_MIN_FRAMED_SPAN,
    assert_autark_map_drawn,
    autark_map_framing,
    frame_nodes,
    node_locator,
    play_node,
    read_node_error_text,
    require_owner_view,
    require_project_page,
    require_user_auth,
    stub_login_and_enter_workflow,
    wait_for_node_settled,
    webgpu_adapter,
)

MAP = "camera-framing-map"
CAMERA = {"zoom": 17, "pitch": 40, "bearing": 30}


def _blocks() -> dict:
    """Nine squares of about 100 m, 50 m apart, near the Loop, valued 1 to 9."""
    features = []
    for row in range(3):
        for column in range(3):
            west, south = -87.634 + 0.0018 * column, 41.878 + 0.00135 * row
            ring = [[west, south], [west + 0.0012, south], [west + 0.0012, south + 0.0009],
                    [west, south + 0.0009], [west, south]]
            features.append({"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [ring]},
                             "properties": {"value": 3 * row + column + 1}})
    return {"type": "FeatureCollection", "features": features}


DOCUMENT = {
    "data": [{"type": "geojson", "outputTableName": "blocks", "geojsonObject": _blocks()}],
    "map": {
        "camera": CAMERA,
        "layerRefs": [{"dataRef": "blocks", "getFnv": "value", "getFnvType": "quantitative",
                       "colorMapInterpolator": "interpolateViridis"}],
    },
}

FLOW = {"dataflow": {
    "name": "Map camera framing",
    "task": "",
    "nodes": [{
        "id": MAP, "type": "curio.builtin/autk-grammar", "x": 0, "y": 0, "content": json.dumps(DOCUMENT, indent=2),
        "in": "DEFAULT", "out": "DEFAULT", "goal": "", "metadata": {"keywords": []},
    }],
    "edges": [],
}}

_VIEWS_JS = "(id) => window.__curio_mapViews(id)"


def test_a_map_its_camera_turns_is_checked_framed_then_turned_as_its_camera_says(app_frontend, current_server, page):
    require_project_page()
    require_user_auth()
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Map camera framing",
        username="autark_camera_framing",
        project_name=FLOW["dataflow"]["name"],
        project_spec=FLOW,
    )
    require_owner_view(page)
    node_locator(page, MAP).wait_for(state="visible", timeout=45000)
    adapter = webgpu_adapter(page)
    assert adapter, f"drawing an Autark map needs a WebGPU adapter, which CI's GPU job has: {adapter}"

    play_node(page, MAP)
    status = wait_for_node_settled(page, MAP, node_type="autk-grammar", timeout_ms=120000)
    detail = read_node_error_text(node_locator(page, MAP)) if status == "error" else ""
    assert status == "done", f"the map did not draw: {detail}"
    assert_autark_map_drawn(page, MAP)
    frame_nodes(page, [MAP])

    turned = page.evaluate(_VIEWS_JS, MAP)
    assert turned and len(turned) == 1 and turned[0].get("camera"), f"the map's view names no camera: {turned}"

    # Framed on its blocks before the turn, and turned as its camera says.
    framing = autark_map_framing(page, MAP, timeout=30000)
    assert framing is None, framing

    # Guard: the camera's view the check turned the map back to, read as it
    # is, is not framed on the nine blocks, so the rule alone refuses it. The
    # rule is read after the check, so a checkout whose check reads the map
    # only as it is fails on the check above.
    from .utils.node_drawings import _drawing_framing

    as_turned = _drawing_framing(page, MAP, min_span=AUTK_MAP_MIN_FRAMED_SPAN, timeout=0)
    assert as_turned is not None, (
        "the map's drawing at its camera's view passes the framing rule, so this map cannot show "
        "that the check reads a turned map at its framed view"
    )

    # The check leaves the map at its camera's view.
    after = page.evaluate(_VIEWS_JS, MAP)
    assert after and len(after) == 1, f"the map's views after the check are {after}"
    distance = math.dist(turned[0]["eye"], turned[0]["lookAt"])
    moved = max(abs(a - b) for key in ("eye", "lookAt") for a, b in zip(after[0][key], turned[0][key]))
    turned_up = max(abs(a - b) for a, b in zip(after[0]["up"], turned[0]["up"]))
    assert moved <= 1e-4 * distance and turned_up <= 1e-5, (
        f"the check left the map at {after[0]}, not at its camera's view {turned[0]}"
    )
