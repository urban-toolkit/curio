"""Playwright E2E: a selection highlights linked charts; it does not rebuild them.

A chart's selection reaches a Data Pool over an interaction edge. The pool flags
the selected rows ``interacted`` and re-emits its output, and every chart it
feeds swaps the new rows into its live view (``useVega``'s hot reload), where the
spec's ``datum.interacted`` condition colours them. The chart itself did not
change, so nothing should be rebuilt.

The signal is the canvas element: vega replaces it when it builds a new view and
keeps it when rows are swapped into the view it has.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_selection_highlights_e2e.py -v
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .utils import (
    node_locator,
    require_owner_view,
    require_project_page,
    require_user_auth,
    run_all_and_wait,
    stub_login_and_enter_workflow,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

LOADER_ID = "sel-loader"
POOL_ID = "sel-pool"
BAR_ID = "sel-bar"
SCATTER_ID = "sel-scatter"

LOADER_CODE = (
    "import pandas as pd\n"
    "\n"
    "return pd.DataFrame({\n"
    '    "label": ["Alice", "Bob", "Charlie", "Dave", "Eve"],\n'
    '    "value": [30, 10, 50, 20, 40],\n'
    '    "score": [3, 9, 1, 7, 5],\n'
    "})\n"
)

# Hovering a bar selects its row; the pool marks it and both charts colour it.
BAR_SPEC = """{
  "$schema": "https://vega.github.io/schema/vega-lite/v6.json",
  "params": [{"name": "highlight", "select": {"type": "point", "on": "pointerover"}}],
  "mark": {"type": "bar", "stroke": "black"},
  "encoding": {
    "x": {"field": "label", "type": "ordinal", "sort": "y"},
    "y": {"field": "value", "type": "quantitative"},
    "color": {"condition": {"test": "datum.interacted === '1'", "value": "red"}, "value": "blue"}
  }
}"""

SCATTER_SPEC = """{
  "$schema": "https://vega.github.io/schema/vega-lite/v6.json",
  "mark": {"type": "point", "filled": true, "size": 400, "opacity": 1},
  "encoding": {
    "x": {"field": "value", "type": "quantitative"},
    "y": {"field": "score", "type": "quantitative"},
    "color": {"condition": {"test": "datum.interacted === '1'", "value": "red"}, "value": "blue"}
  }
}"""


def _node(node_id: str, node_type: str, x: int, y: int, content: str) -> dict:
    return {
        "id": node_id,
        "type": node_type,
        "x": x,
        "y": y,
        "content": content,
        "in": "DEFAULT",
        "out": "DEFAULT",
        "goal": "",
        "metadata": {"keywords": []},
    }


def _data_edge(source: str, target: str) -> dict:
    return {
        "id": f"reactflow__edge-{source}out-{target}in",
        "source": source,
        "target": target,
    }


def _spec() -> dict:
    return {
        "dataflow": {
            "name": "Selection highlights",
            "task": "",
            "timestamp": 1789193389280,
            "provenance_id": "Selection highlights",
            "nodes": [
                _node(LOADER_ID, "curio.builtin/data-loading", 0, 0, LOADER_CODE),
                _node(POOL_ID, "curio.builtin/data-pool", 600, 0, ""),
                _node(BAR_ID, "curio.builtin/vis-vega", 1200, -300, BAR_SPEC),
                _node(SCATTER_ID, "curio.builtin/vis-vega", 1200, 300, SCATTER_SPEC),
            ],
            "edges": [
                _data_edge(LOADER_ID, POOL_ID),
                _data_edge(POOL_ID, BAR_ID),
                _data_edge(POOL_ID, SCATTER_ID),
                {
                    "type": "Interaction",
                    "id": f"reactflow__edge-{BAR_ID}in/out-{POOL_ID}in/out",
                    "source": BAR_ID,
                    "target": POOL_ID,
                },
            ],
        }
    }


def _direct_spec() -> dict:
    """The same charts fed straight by the loader and joined to each other by
    a direct interaction edge: no Data Pool anywhere."""
    return {
        "dataflow": {
            "name": "Direct selection",
            "task": "",
            "timestamp": 1789193389280,
            "provenance_id": "Direct selection",
            "nodes": [
                _node(LOADER_ID, "curio.builtin/data-loading", 0, 0, LOADER_CODE),
                _node(BAR_ID, "curio.builtin/vis-vega", 700, -300, BAR_SPEC),
                _node(SCATTER_ID, "curio.builtin/vis-vega", 700, 300, SCATTER_SPEC),
            ],
            "edges": [
                _data_edge(LOADER_ID, BAR_ID),
                _data_edge(LOADER_ID, SCATTER_ID),
                {
                    "type": "Interaction",
                    "id": f"reactflow__edge-{BAR_ID}in/out-{SCATTER_ID}in/out",
                    "source": BAR_ID,
                    "target": SCATTER_ID,
                },
            ],
        }
    }


# Every canvas vega puts into a chart's container after this point, and the
# canvases each chart holds now, so a rebuild shows up as either signal.
_WATCH_CANVASES_JS = """(ids) => {
    const probe = { original: {}, added: {} };
    for (const id of ids) {
        const host = document.getElementById('vega' + id);
        probe.original[id] = host ? host.querySelector('canvas') : null;
        probe.added[id] = 0;
        if (!host) continue;
        new MutationObserver((records) => {
            for (const r of records) {
                for (const n of r.addedNodes) {
                    if (n.nodeName === 'CANVAS') probe.added[id] += 1;
                }
            }
        }).observe(host, { childList: true, subtree: true });
    }
    window.__curioSelectionProbe = probe;
    return ids.map((id) => !!probe.original[id]);
}"""

_READ_PROBE_JS = """(ids) => {
    const probe = window.__curioSelectionProbe;
    const out = {};
    for (const id of ids) {
        const c = probe.original[id];
        out[id] = { kept: !!c && c.isConnected, added: probe.added[id] };
    }
    return out;
}"""

# Opaque, saturated red pixels in the chart's current canvas: the colour the
# spec gives a row the pool marked ``interacted``.
_RED_PIXELS_JS = """(id) => {
    const c = document.querySelector('#vega' + id + ' canvas');
    if (!c || !c.width || !c.height) return -1;
    const px = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
    let red = 0;
    for (let i = 0; i < px.length; i += 4) {
        if (px[i] > 200 && px[i + 1] < 60 && px[i + 2] < 60 && px[i + 3] > 200) red += 1;
    }
    return red;
}"""


def _red_pixels(page, node_id: str) -> int:
    return page.evaluate(_RED_PIXELS_JS, node_id)


def _hover_bars_and_measure(page) -> tuple[bool, dict, int]:
    """Walk the pointer across the bars until the scatterplot shows a marked
    row; report whether it did, which canvases survived, and the red left."""
    charts = [BAR_ID, SCATTER_ID]
    assert page.evaluate(_WATCH_CANVASES_JS, charts) == [True, True]

    # The chart is one canvas, so bars are found by position, not by element.
    box = page.locator(f"#vega{BAR_ID} canvas").first.bounding_box()
    assert box, "the bar chart has no canvas box"
    saw_highlight = False
    y = box["y"] + box["height"] * 0.75
    for fraction in (0.85, 0.7, 0.55, 0.4, 0.25):
        page.mouse.move(box["x"] + box["width"] * fraction, y)
        for _ in range(20):
            page.wait_for_timeout(250)
            if _red_pixels(page, SCATTER_ID) > 0:
                saw_highlight = True
                break
        if saw_highlight:
            break

    # Give a rebuild, if one is coming, the time it takes to land.
    page.wait_for_timeout(2500)
    return saw_highlight, page.evaluate(_READ_PROBE_JS, charts), _red_pixels(page, SCATTER_ID)


def _open(page, app_frontend, current_server, *, username: str, spec: dict) -> None:
    page.emulate_media(reduced_motion="reduce")
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name=spec["dataflow"]["name"],
        username=username,
        project_name=spec["dataflow"]["name"],
        project_spec=spec,
    )
    require_owner_view(page)
    for node in spec["dataflow"]["nodes"]:
        node_locator(page, node["id"]).wait_for(state="visible", timeout=45000)

    run_all_and_wait(page, timeout_ms=180000)
    for node_id in (BAR_ID, SCATTER_ID):
        page.locator(f"#vega{node_id} canvas").first.wait_for(state="attached", timeout=60000)
    # Let the post-run renders settle before recording which canvases exist.
    page.wait_for_timeout(1500)
    assert _red_pixels(page, SCATTER_ID) == 0, "a row was marked before any selection"


def _assert_highlighted_not_rebuilt(saw_highlight: bool, probe: dict, red_now: int) -> None:
    report = f"highlight seen: {saw_highlight}; red pixels now: {red_now}; canvases: {probe}"
    assert saw_highlight, f"the selection never reached the scatterplot ({report})"
    for node_id, state in probe.items():
        assert state["kept"] and state["added"] == 0, (
            f"a selection rebuilt chart {node_id} instead of highlighting it ({report})"
        )
    assert red_now > 0, f"the highlight did not stay ({report})"


def test_a_selection_highlights_linked_charts_without_rebuilding_them(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
):
    require_project_page()
    require_user_auth()

    _open(page, app_frontend, current_server, username="selection_highlights", spec=_spec())
    _assert_highlighted_not_rebuilt(*_hover_bars_and_measure(page))


def test_a_direct_edge_between_two_charts_highlights_the_other(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
):
    """No pool: the scatterplot matches the bar chart's selection against its
    own rows (both read the loader's rows, so positions line up)."""
    require_project_page()
    require_user_auth()

    _open(page, app_frontend, current_server, username="direct_selection", spec=_direct_spec())
    _assert_highlighted_not_rebuilt(*_hover_bars_and_measure(page))
