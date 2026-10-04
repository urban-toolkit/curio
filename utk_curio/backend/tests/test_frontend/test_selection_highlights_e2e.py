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
    assert_in_view,
    at_fraction,
    brush_area,
    frame_nodes,
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


# The scatterplot with a brush of its own. No grid, so the light grey a Vega
# brush paints is the only grey in its canvas.
SCATTER_BRUSH_SPEC = """{
  "$schema": "https://vega.github.io/schema/vega-lite/v6.json",
  "params": [{"name": "brush", "select": {"type": "interval"}}],
  "mark": {"type": "point", "filled": true, "size": 400, "opacity": 1},
  "encoding": {
    "x": {"field": "value", "type": "quantitative"},
    "y": {"field": "score", "type": "quantitative"},
    "color": {"condition": {"test": "datum.interacted === '1'", "value": "red"}, "value": "blue"}
  },
  "config": {"axis": {"grid": false}}
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


def _merge_spec() -> dict:
    """The same pool, fed back by both charts: the scatterplot's brush reaches
    it over an interaction edge of its own, beside the bar chart's hover."""
    spec = _spec()
    flow = spec["dataflow"]
    flow["name"] = flow["provenance_id"] = "Merged selections"
    for node in flow["nodes"]:
        if node["id"] == SCATTER_ID:
            node["content"] = SCATTER_BRUSH_SPEC
    flow["edges"].append({
        "type": "Interaction",
        "id": f"reactflow__edge-{SCATTER_ID}in/out-{POOL_ID}in/out",
        "source": SCATTER_ID,
        "target": POOL_ID,
    })
    return spec


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


# The bars of a bar chart, left to right, read along the lowest canvas row that
# crosses all five: whether each is red, and a point inside it in the page.
_BARS_JS = """(id) => {
    const c = document.querySelector('#vega' + id + ' canvas');
    if (!c || !c.width || !c.height) return null;
    const w = c.width, h = c.height;
    const px = c.getContext('2d').getImageData(0, 0, w, h).data;
    const kind = (x, y) => {
        const i = (y * w + x) * 4;
        if (px[i + 3] < 200) return null;
        if (px[i] > 200 && px[i + 1] < 60 && px[i + 2] < 60) return 'red';
        if (px[i + 2] > 200 && px[i] < 60 && px[i + 1] < 60) return 'blue';
        return null;
    };
    const box = c.getBoundingClientRect();
    for (let y = h - 1; y >= 4; y--) {
        const runs = [];
        let run = null;
        for (let x = 0; x < w; x++) {
            const k = kind(x, y);
            if (k && run && run.kind === k) { run.x1 = x; continue; }
            run = k ? { kind: k, x0: x, x1: x } : null;
            if (run) runs.push(run);
        }
        const bars = runs.filter((r) => r.x1 - r.x0 >= 3);
        if (bars.length === 5) {
            return bars.map((r) => ({
                red: r.kind === 'red',
                x: box.left + ((r.x0 + r.x1 + 1) / 2) * (box.width / w),
                y: box.top + (y - 3) * (box.height / h),
            }));
        }
    }
    return null;
}"""

# Red points in the scatterplot, counted by where they sit across: every row
# has its own `value`, so each point takes its own band of columns. A brush
# edge drawn over a point splits its pixels, never its columns, and a gap of a
# few columns (a vertical edge) is bridged.
_RED_POINTS_JS = """(id) => {
    const c = document.querySelector('#vega' + id + ' canvas');
    if (!c || !c.width || !c.height) return -1;
    const w = c.width, h = c.height;
    const px = c.getContext('2d').getImageData(0, 0, w, h).data;
    const redInColumn = new Array(w).fill(0);
    for (let y = 0; y < h; y++) {
        for (let x = 0; x < w; x++) {
            const i = (y * w + x) * 4;
            if (px[i] > 200 && px[i + 1] < 60 && px[i + 2] < 60 && px[i + 3] > 200) redInColumn[x] += 1;
        }
    }
    let points = 0, last = -100;
    for (let x = 0; x < w; x++) {
        if (redInColumn[x] < 2) continue;
        if (x - last > 4) points += 1;
        last = x;
    }
    return points;
}"""

# The light grey of a Vega brush (#333 at 12.5% over white) in a chart's canvas.
_BRUSH_GREY_JS = """(id) => {
    const c = document.querySelector('#vega' + id + ' canvas');
    if (!c || !c.width || !c.height) return -1;
    const px = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
    let grey = 0;
    for (let i = 0; i < px.length; i += 4) {
        const r = px[i], g = px[i + 1], b = px[i + 2];
        if (px[i + 3] > 200 && r >= 215 && r <= 240 && Math.abs(r - g) < 4 && Math.abs(g - b) < 4) grey += 1;
    }
    return grey;
}"""


def _red_bars_once(page, count: int, *, timeout_ms: int = 15000) -> list[dict]:
    """The bar chart's bars, once exactly *count* of them are red."""
    bars = None
    for _ in range(timeout_ms // 250):
        bars = page.evaluate(_BARS_JS, BAR_ID)
        if bars and sum(b["red"] for b in bars) == count:
            return bars
        page.wait_for_timeout(250)
    raise AssertionError(f"expected {count} red bars, the bar chart shows {bars}")


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
        page.mouse.move(*assert_in_view(
            page, box["x"] + box["width"] * fraction, y, f"the bar chart at {fraction:.0%} across"))
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
    # Frame the two charts. The canvas fits itself when the dataflow loads, and
    # that fit can see the nodes before they reach their full size, so a chart
    # may end past the window's edge, where a hover reaches nothing.
    frame_nodes(page, [BAR_ID, SCATTER_ID])
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


def test_merge_or_in_the_pool_keeps_both_charts_selections(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
):
    """Merge (OR) between charts (#581): the pool keeps each chart's latest
    selection and flags the rows any of them picked. The brushed scatterplot
    keeps its brush while the bar chart's hover adds a row."""
    require_project_page()
    require_user_auth()

    _open(page, app_frontend, current_server, username="merged_selections", spec=_merge_spec())

    between = node_locator(page, POOL_ID).get_by_label("Conflict between visualizations")
    between.select_option("MERGE_OR")
    assert between.input_value() == "MERGE_OR"

    # First the scatterplot: a brush over its two leftmost points, Bob (10, 9)
    # and Dave (20, 7). It starts between the points and runs up and left to
    # the canvas's corner, past the plot's edge, where the brush stops. The
    # corner is inside the canvas, where the node corrects the pointer's
    # position for the canvas zoom; outside it, Vega would misplace the brush.
    grey_before = page.evaluate(_BRUSH_GREY_JS, SCATTER_ID)
    area = brush_area(page, f"#vega{SCATTER_ID} canvas")
    assert area, "the scatterplot drew no points to brush"
    canvas = page.locator(f"#vega{SCATTER_ID} canvas").first.bounding_box()
    assert canvas, "the scatterplot has no canvas box"
    page.mouse.move(*assert_in_view(page, *at_fraction(area, (0.35, 0.5)), "the brush's start"))
    page.mouse.down()
    page.mouse.move(*assert_in_view(
        page, canvas["x"] + 3, canvas["y"] + 3, "the scatterplot's corner"), steps=8)
    page.mouse.up()
    bars = _red_bars_once(page, 2)
    grey_brushed = page.evaluate(_BRUSH_GREY_JS, SCATTER_ID)
    assert grey_brushed > grey_before + 500, (
        f"no brush on the scatterplot ({grey_before} grey pixels before, {grey_brushed} after)"
    )

    # Then the bar chart: the rightmost bar is Charlie (50), outside the brush.
    page.mouse.move(*assert_in_view(page, bars[-1]["x"], bars[-1]["y"], "Charlie's bar"))
    bars = _red_bars_once(page, 3)
    assert [b["red"] for b in bars] == [True, True, False, False, True], (
        f"the bar chart lit the wrong bars: {bars}"
    )
    # Let any late echo land before reading the scatterplot.
    page.wait_for_timeout(1500)
    assert page.evaluate(_RED_POINTS_JS, SCATTER_ID) == 3, (
        "the scatterplot does not show the rows of both selections"
    )
    grey_now = page.evaluate(_BRUSH_GREY_JS, SCATTER_ID)
    assert grey_now >= 0.8 * grey_brushed, (
        f"the scatterplot's brush went away ({grey_brushed} grey pixels, now {grey_now})"
    )
