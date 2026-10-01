"""Playwright E2E: an Autark histogram's highlight holds steady while it is brushed (#532).

Reported on example 07 with a second histogram, of building levels, behind the
same Data Pool: brushing a histogram, its highlighted bars flickered while the
brush was dragged, instead of following it.

At the commit it was filed on, the brushed plot applied the pool's echo of its
own selection on every move. The echo comes back a few moves late, so the bars
the brush had just reached went dark until the next move lit them again, and
an echo of the empty selection a press starts with cleared the rectangle too.
Since #541 the echo names the chart it came from, and that chart skips it.

The dataflow here is the reporter's: example 07 plus their histogram. Each
histogram is brushed in one fast drag, outwards from its left edge, the way a
hand moves, so that echoes land between moves. Every bar's fill is watched
through the drag: from nothing lit, a bar may light once and must stay lit. The
other histogram, whose layer the brush does not touch, must not change at all.
Both histograms are brushed, each twice.

Every brush runs and the failures are reported together.

Example 07 runs a WebGPU shader, so this needs a WebGPU adapter: CI's GPU job.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_autark_brush_steady_e2e.py -v
"""
from __future__ import annotations

import copy
import time
from typing import TYPE_CHECKING

from .utils import (
    INTERACTION_VIEWPORT,
    _wait_for_no_node_running,
    bar_boxes,
    bar_fill_log,
    brush_area,
    brush_log,
    brush_mismatches,
    dismiss_toasts,
    drawing_selector,
    frame_nodes,
    lit_marks,
    node_locator,
    require_owner_view,
    require_project_page,
    require_user_auth,
    run_all_and_wait,
    stub_login_and_enter_workflow,
    watch_bar_fills,
    watch_brush,
)
from .walkthroughs import load_example_spec

if TYPE_CHECKING:
    from .utils import FrontendPage

EXAMPLE = "07-autark-gpu-shader.json"
POOL = "sh-pool"
ROADS_PLOT = "sh-plot"
BUILDINGS_PLOT = "c9167a00-af32-4e32-9ab8-5d2be7a10279"

#: Each histogram is brushed this many times, the other one in between.
ROUNDS = 2

#: The histogram the reporter added to example 07, as #532's attachment has it.
BUILDINGS_PLOT_NODE = {
    "id": BUILDINGS_PLOT,
    "type": "curio.builtin/autk-grammar@1",
    "x": 2921.783640336155,
    "y": 570.4695631137034,
    "width": 943,
    "height": 562,
    "saveOutputDataset": False,
    "out": "DEFAULT",
    "in": "DEFAULT",
    "goal": "",
    "metadata": {"keywords": []},
    "content": """{
  "plot": {
    "dataRef": "table_osm_buildings",
    "mark": "bar",
    "axis": [
      "building:levels",
      "@transform"
    ],
    "title": "Minutes of sunlight per Chicago Loop road segment",
    "transform": {
      "preset": "binning-1d",
      "options": {
        "bins": 13
      }
    },
    "events": [
      "brushX"
    ]
  }
}""",
}

BUILDINGS_PLOT_EDGES = [
    {
        "id": f"reactflow__edge-{POOL}out-{BUILDINGS_PLOT}in",
        "source": POOL, "target": BUILDINGS_PLOT, "sourceHandle": "out", "targetHandle": "in",
    },
    {
        "type": "Interaction",
        "id": f"reactflow__edge-{POOL}in/out-{BUILDINGS_PLOT}in/out",
        "source": POOL, "target": BUILDINGS_PLOT, "sourceHandle": "in/out", "targetHandle": "in/out",
    },
]


def _reporter_spec() -> dict:
    spec = copy.deepcopy(load_example_spec(EXAMPLE))
    spec["dataflow"]["nodes"].append(copy.deepcopy(BUILDINGS_PLOT_NODE))
    spec["dataflow"]["edges"].extend(copy.deepcopy(BUILDINGS_PLOT_EDGES))
    return spec


def _nothing_lit(page, plot: str, *, timeout_ms: int = 10000) -> bool:
    deadline = time.monotonic() + timeout_ms / 1000
    while True:
        counts = lit_marks(page, plot, at_least=0, timeout_ms=0)
        if counts and counts["total"] and counts["lit"] == 0:
            return True
        if time.monotonic() >= deadline:
            return False
        page.wait_for_timeout(300)


def _changes_after(states: list[dict], t: float) -> list[dict]:
    return [state for state in states[1:] if state["t"] >= t]


def _described(changes: list[dict], since: float) -> str:
    return ", ".join(f"{'lit' if c['lit'] else 'unlit'} at {c['t'] - since} ms" for c in changes)


def _brush_problems(page, plot_id: str, other_id: str, round_: int) -> list[str]:
    """One fast outward brush on *plot_id*; what went wrong with it, if anything."""
    where = f"brush {round_} of {plot_id}"
    frame_nodes(page, [plot_id])
    _wait_for_no_node_running(page)
    plot = drawing_selector(page, plot_id)
    other = drawing_selector(page, other_id)
    if not plot or not other:
        return [f"{where}: a histogram drew nothing ({plot_id}: {plot}, {other_id}: {other})"]
    area = brush_area(page, plot)
    bars = bar_boxes(page, plot)
    if not area or len(bars) < 4:
        return [f"{where}: the histogram has no brush overlay or too few bars ({len(bars)})"]
    y = area["y"] + area["height"] / 2

    # Nothing selected to begin with: a click away from any brush clears it,
    # and the pool sends the empty selection on.
    page.mouse.click(area["x"] + area["width"] - 3, y)
    if not _nothing_lit(page, plot):
        return [f"{where}: clearing the brush left bars lit, so the drag could not start from none"]
    page.wait_for_timeout(500)

    start_x = min(area["x"] + 2, bars[0]["left"] - 1)
    end_x = (bars[-2]["left"] + bars[-2]["right"]) / 2
    page.mouse.move(start_x, y)
    watch_brush(page, plot)
    watch_bar_fills(page, plot)
    watch_bar_fills(page, other)
    page.mouse.down()
    page.mouse.move(end_x, y, steps=40)
    page.wait_for_timeout(500)
    page.mouse.up()
    wrong = brush_mismatches(page, plot)
    # Room for a late echo to land after the release.
    page.wait_for_timeout(1500)

    log = bar_fill_log(page, plot)
    other_log = bar_fill_log(page, other)
    down = next(e["t"] for e in log["pointer"] if e["type"] == "mousedown")
    problems = []
    if not log["connected"]:
        problems.append(f"{where}: the plot replaced its bars during the brush")
    for label, states in zip(log["labels"], log["states"]):
        changes = _changes_after(states, down)
        if len(changes) > 1 or (changes and not changes[-1]["lit"]):
            problems.append(
                f"{where}: bar {label!r} flickered while it was brushed: {_described(changes, down)}")
    for label, states in zip(other_log["labels"], other_log["states"]):
        changes = _changes_after(states, down)
        if changes:
            problems.append(
                f"{where}: bar {label!r} of {other_id}, which the brush does not reach, changed: "
                f"{_described(changes, down)}")

    brush = brush_log(page)
    brush_down = next(e["t"] for e in brush if e["what"] == "mousedown")
    brush_up = next(e["t"] for e in brush if e["what"] == "mouseup")
    vanished = [e["t"] - brush_down for e in brush if brush_down < e["t"] < brush_up and not e["shown"]]
    if vanished:
        problems.append(f"{where}: the brush vanished {vanished[0]} ms into the drag")
    if wrong is None:
        problems.append(f"{where}: the brush was gone once the pointer let go")
    elif wrong:
        problems.append(f"{where}: the brush lit the wrong bars: " + ", ".join(
            f"{w['label']} {'lit outside the brush' if w['lit'] else 'unlit under it'}" for w in wrong))
    return problems


def test_a_histogram_brush_lights_its_bars_steadily(
    app_frontend: "FrontendPage", current_server: str, page
):
    require_project_page()
    require_user_auth()

    page.emulate_media(reduced_motion="reduce")
    page.set_viewport_size(INTERACTION_VIEWPORT)
    spec = _reporter_spec()
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Brush Steady User",
        username="autark_brush_steady",
        project_name="Autark brush steady",
        project_spec=spec,
    )
    require_owner_view(page)
    for node in spec["dataflow"]["nodes"]:
        node_locator(page, node["id"]).wait_for(state="visible", timeout=45000)
    assert page.evaluate("async () => !!(navigator.gpu && await navigator.gpu.requestAdapter())"), (
        "this browser has no WebGPU adapter, and example 07 runs a WebGPU shader")

    run_all_and_wait(page, timeout_ms=300000)
    dismiss_toasts(page)

    problems: list[str] = []
    for round_ in range(1, ROUNDS + 1):
        problems += _brush_problems(page, ROADS_PLOT, BUILDINGS_PLOT, round_)
        problems += _brush_problems(page, BUILDINGS_PLOT, ROADS_PLOT, round_)

    assert not problems, "a histogram's highlight did not hold steady while it was brushed (#532):\n- " + (
        "\n- ".join(problems))
