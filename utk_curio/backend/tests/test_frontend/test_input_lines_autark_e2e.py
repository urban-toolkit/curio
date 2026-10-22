"""Playwright E2E: Inputs in the header of nodes fed a tuple or Autark layers (#662).

Each input is a line in the header above a node's code or spec: its expander,
its tag, and what it holds. Two shipped examples, checked where jsdom has no
layout to read:

1. Example 26, Several inputs: its Python join reads three inputs, and the
   second, Summarize's, is a tuple of two tables. With the nodes that feed the
   join run, Inputs on the join's Code tab says ``input_1`` holds 2 values, a
   tuple. A close-up with ``input_0``'s columns open.
2. Example 11, Autark PBF loading: the map's input is the OSM load's layers.
   With the load run alone, ``input_0``'s list holds a line per layer. Every
   layer tag starts at one left edge, which is read with the hooks the header
   had before its lines (``[data-layer-tag]`` in ``input_0``'s list), so on the
   header the owner reviewed the test fails where the layers ran together.
   Then each layer's line is below the one before, the header lies inside the
   map's card, and every line and tag stays within the card's width. A
   close-up with the layers open.

Both examples hold Autark nodes, and the map draws only with WebGPU, so this
module runs on the GPU runner. Without a WebGPU adapter the map's test skips,
unless ``CURIO_REQUIRE_HARDWARE_WEBGPU=1`` (CI's GPU job), where it fails. The
chart's case, which needs no GPU, is ``test_input_lines_e2e.py``.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_input_lines_autark_e2e.py -v
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING

from .test_input_lines_e2e import EDGE_PX, _inside, _open_list, _ready_for_closeup, _wait_for_counts
from .test_widget_tags_e2e import _open_tab
from .utils import (
    REPO_ROOT,
    _wait_for_no_node_running,
    assert_autark_map_drawn,
    frame_nodes,
    node_locator,
    open_strip_category,
    require_owner_view,
    require_project_page,
    require_user_auth,
    require_webgpu,
    run_node_and_wait,
    save_node_closeup,
    stub_login_and_enter_workflow,
    wait_for_node_done,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

EXAMPLES = Path(REPO_ROOT) / "docs" / "examples"
SEVERAL_INPUTS = EXAMPLES / "26-several-inputs.json"
PBF_LOADING = EXAMPLES / "11-autark-pbf-loading.json"
JOIN_TEST = "test_the_join_says_its_tuple_input_holds_2_values"
MAP_TEST = "test_each_layer_of_the_map_input_is_a_line_of_its_own"
#: Example 26's join, and the nodes that feed it, in an order they can run in:
#: Summarize reads the readings.
JOIN = "several-join"
JOIN_FEEDERS = ("several-readings", "several-stations", "several-zips", "several-summary")
#: Example 11's OSM load, and the map and the plot it feeds.
LOAD, MAP, PLOT = "pbf-load", "pbf-map", "pbf-plot"
#: How long a node of these examples may take to run, in ms.
RUN_MS = 120000

# Each layer tag in input_0's open list, in the page's order: its layer and
# where it sits. Found by the hook the header had before its lines. Null while
# the list is closed.
_LAYER_TAGS_JS = r"""(nodeId) => {
    const strip = Array.from(document.querySelectorAll(`.react-flow__node[data-id="${nodeId}"] [data-widget-strip]`))
        .find((el) => el.getClientRects().length > 0);
    const list = strip && strip.querySelector('[data-strip-chips="inputs"] [data-input-columns="0"]');
    if (!list) return null;
    return Array.from(list.querySelectorAll("[data-layer-tag]")).map((tag) => {
        const box = tag.getBoundingClientRect();
        return { layer: tag.textContent, left: box.left, right: box.right, top: box.top, bottom: box.bottom };
    });
}"""

# The map's card and header, and each layer's line in input_0's open list, in
# order: its layer, where the line sits, and its layer tag's text and box.
_LAYER_LINES_JS = r"""(nodeId) => {
    const card = document.querySelector(`.react-flow__node[data-id="${nodeId}"]`);
    const strip = card && Array.from(card.querySelectorAll("[data-widget-strip]"))
        .find((el) => el.getClientRects().length > 0);
    const list = strip && strip.querySelector('[data-strip-chips="inputs"] [data-input-columns="0"]');
    if (!list) return null;
    const box = (el) => {
        if (!el) return null;
        const r = el.getBoundingClientRect();
        return { left: r.left, right: r.right, top: r.top, bottom: r.bottom };
    };
    return {
        card: box(card),
        strip: box(strip),
        lines: Array.from(list.querySelectorAll("[data-layer-line]")).map((line) => {
            const tag = line.querySelector("[data-layer-tag]");
            return { layer: line.getAttribute("data-layer-line"), box: box(line), tag: tag ? tag.textContent : null, tagBox: box(tag) };
        }),
    };
}"""


def _open(page, app_frontend, current_server, example: Path, *, username: str) -> dict:
    """Open *example* as a new dataflow, wait for its nodes, and return them by id."""
    page.emulate_media(reduced_motion="reduce")
    spec = json.loads(example.read_text(encoding="utf-8"))
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Input Lines",
        username=username,
        project_name=spec["dataflow"]["name"],
        project_spec=spec,
    )
    require_owner_view(page)
    nodes = {node["id"]: node for node in spec["dataflow"]["nodes"]}
    for node_id in nodes:
        node_locator(page, node_id).wait_for(state="attached", timeout=45000)
    return nodes


def _wait_for_layer_tags(page, node_id: str, layers: list[str], *, timeout: float = 30000) -> list:
    """Wait until input_0's open list has a tag for each of *layers*, and
    return its layer tags."""
    deadline = time.time() + timeout / 1000
    shown = page.evaluate(_LAYER_TAGS_JS, node_id) or []
    while not set(layers) <= {tag["layer"] for tag in shown} and time.time() < deadline:
        page.wait_for_timeout(250)
        shown = page.evaluate(_LAYER_TAGS_JS, node_id) or []
    assert set(layers) <= {tag["layer"] for tag in shown}, (
        f"input_0's list under {node_id}'s Inputs has no tag for each layer the map draws, {layers}: {shown}"
    )
    return shown


def test_the_join_says_its_tuple_input_holds_2_values(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
):
    require_project_page()
    require_user_auth()
    nodes = _open(page, app_frontend, current_server, SEVERAL_INPUTS, username="input_lines_join")
    assert nodes[JOIN]["type"] == "curio.builtin/computation-analysis", nodes[JOIN]["type"]
    assert "return means, peaks" in nodes["several-summary"]["content"]

    # The join's inputs hold their values; the join itself does not run.
    for node_id in JOIN_FEEDERS:
        run_node_and_wait(page, node_id, node_type=nodes[node_id]["type"], timeout_ms=RUN_MS)
    _wait_for_no_node_running(page)

    frame_nodes(page, [JOIN])
    _open_tab(page, JOIN, "code")
    open_strip_category(page, JOIN, "inputs")
    lines = _wait_for_counts(page, JOIN)
    assert [key for key, _ in lines] == ["input_0", "input_1", "input_2"], lines
    assert lines[1][1] == "from Python Computation: 2 values, a tuple", lines

    # The join with input_0's columns open.
    _open_list(page, JOIN, 0)
    node_locator(page, JOIN).locator(
        '[data-widget-strip]:visible [data-input-columns="0"] [data-column-tag]'
    ).first.wait_for(state="visible", timeout=15000)
    _ready_for_closeup(page, JOIN, "code", "[!! input_1 !!]")
    save_node_closeup(page, "26-several-inputs-join-header", JOIN, test_name=JOIN_TEST, sweep_toasts=True)


def test_each_layer_of_the_map_input_is_a_line_of_its_own(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
):
    require_project_page()
    require_user_auth()
    nodes = _open(page, app_frontend, current_server, PBF_LOADING, username="input_lines_map")
    require_webgpu(page)
    drawn = [layer["dataRef"] for layer in json.loads(nodes[MAP]["content"])["map"]["layerRefs"]]
    assert len(drawn) >= 2, drawn

    # The load runs alone. The map and the plot draw from its layers on their
    # own, and a draw shows a node's output pane, so the map's Grammar tab
    # opens only once both have drawn and nothing runs.
    run_node_and_wait(page, LOAD, node_type=nodes[LOAD]["type"], timeout_ms=RUN_MS)
    for node_id in (MAP, PLOT):
        wait_for_node_done(page, node_id, node_type=nodes[node_id]["type"], timeout_ms=RUN_MS)
    assert_autark_map_drawn(page, MAP, timeout=90000, attach_as="the map, drawn from the load's layers")
    _wait_for_no_node_running(page)

    # The owner's case one level down: each layer's tag starts a line of its
    # own, so the tags share one left edge.
    frame_nodes(page, [MAP])
    _open_tab(page, MAP, "grammar")
    open_strip_category(page, MAP, "inputs")
    _open_list(page, MAP, 0)
    tags = _wait_for_layer_tags(page, MAP, drawn)
    lefts = [tag["left"] for tag in tags]
    assert max(lefts) - min(lefts) <= EDGE_PX, f"the layer tags do not start at one left edge: {tags}"

    # A line per layer, each below the one before, each with its own tag.
    shown = page.evaluate(_LAYER_LINES_JS, MAP)
    assert shown and set(drawn) <= {line["layer"] for line in shown["lines"]}, (
        f"input_0's list has no line for each layer the map draws, {drawn}: {shown}"
    )
    lines = shown["lines"]
    assert all(line["tag"] == line["layer"] for line in lines), lines
    for upper, lower in zip(lines, lines[1:]):
        assert lower["box"]["top"] >= upper["box"]["bottom"] - EDGE_PX, (
            f"{lower['layer']}'s line (top {lower['box']['top']:.1f}) does not start below "
            f"{upper['layer']}'s (bottom {upper['box']['bottom']:.1f})"
        )

    # The header lies inside the card, and every layer's line and tag stays
    # within the card's width. The lines may run below the header's bottom,
    # where its chips scroll.
    assert _inside(shown["card"], shown["strip"]), f"the header {shown['strip']} runs out of its card {shown['card']}"
    for line in lines:
        for what in ("box", "tagBox"):
            assert _inside(shown["card"], line[what], across_only=True), (
                f"{line['layer']}'s {'line' if what == 'box' else 'tag'} {line[what]} runs out of "
                f"the card {shown['card']}"
            )

    # The line: from the load, with its count.
    counted = _wait_for_counts(page, MAP)
    assert [key for key, _ in counted] == ["input_0"], counted
    assert re.fullmatch(r"from Autark: \d+ layers", counted[0][1]), counted

    # The map with input_0's layers open.
    _ready_for_closeup(page, MAP, "grammar", '"table_osm_buildings"')
    save_node_closeup(page, "11-autark-pbf-loading-map-header", MAP, test_name=MAP_TEST, sweep_toasts=True)
