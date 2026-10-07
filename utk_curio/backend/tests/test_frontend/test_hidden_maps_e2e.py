"""Playwright E2E: an Autark map draws only while its canvas has a layout box,
and a map nobody will see again is destroyed.

autk-map draws a map on every animation frame from the moment autk-grammar
starts it, and every map of the page draws with the same GPU. A map hidden by
``display: none`` must draw nothing: one in a collapsed scenario, behind its
node's grammar tab or on a minimized node. A map merely out of the window
keeps drawing and stays drawn. A map nobody will see again, the one a re-run
replaced, a deleted node's and a closed dataflow's, must be destroyed:
autk-map's ``destroy()`` unconfigures its canvas's WebGPU context and drops
its window listeners, so a window resize configures no canvas that has left
the page.

An init script counts, for each map canvas, the animation frames in which it
asked WebGPU for a texture to draw into, at most one a frame callback, so a
resize, which asks outside any frame, is not a frame drawn; and it records each
canvas's context being configured and unconfigured. Each frame check counts
while the page draws ``RULER_FRAMES`` frames of its own: it holds over frames
the page drew, not over seconds a loaded runner may spend drawing none (#808).
The map, once it can be seen again, must draw under the same count, and after a
re-run its new map must take a window resize, so a count of none is not a
counter that sees nothing.

The checks are gathered and asserted together at the end, so a failure names
every way a hidden map still drew, a dead one was kept or a laid-out one
stopped.

It runs Autark nodes, which need WebGPU: without an adapter it skips, unless
``CURIO_REQUIRE_HARDWARE_WEBGPU=1`` (CI's GPU job), where it fails.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_hidden_maps_e2e.py -v
"""

from __future__ import annotations

import json
import os
import time
from typing import TYPE_CHECKING

import pytest
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from .utils import (
    activate_header_icon,
    assert_autark_map_drawn,
    frame_nodes,
    node_locator,
    play_node,
    read_node_error_text,
    require_owner_view,
    require_project_page,
    require_user_auth,
    run_all_and_wait,
    stub_login_and_enter_workflow,
    wait_for_node_settled,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

LOADER = "hm-load"
MAP = "hm-map"
SCENARIO = "hm-scenario"

#: The page's own frames each check counts over.
RULER_FRAMES = 60
#: Frames the page gets to take in what changed before a check counts.
GRACE_FRAMES = 10
#: The longest a check waits for the page to draw its frames.
RULER_TIMEOUT_MS = 90000

# A 10 x 10 grid of cells over Chicago, each with its own value, so the map
# draws many colours (``assert_autark_map_drawn`` wants more than 8).
LOADER_CODE = (
    "import geopandas as gpd\n"
    "from shapely.geometry import box\n"
    "\n"
    "cells, pop = [], []\n"
    "for i in range(10):\n"
    "    for j in range(10):\n"
    "        x, y = -87.70 + 0.006 * i, 41.86 + 0.006 * j\n"
    "        cells.append(box(x, y, x + 0.005, y + 0.005))\n"
    "        pop.append(i * 10 + j)\n"
    'return gpd.GeoDataFrame({"pop": pop}, geometry=cells, crs="EPSG:4326")\n'
)
MAP_CONTENT = json.dumps({"map": {"layerRefs": [{
    "dataRef": "input_0",
    "getFnv": "pop",
    "getFnvType": "quantitative",
    "colorMapInterpolator": "interpolateViridis",
}]}}, indent=2)

# Installed before the app loads. Counts, for each map canvas in the page, the
# frame callbacks in which it asked for a texture and the times its context was
# configured, the same for canvases that have left the page, which nothing can
# show again, and which canvases had their context unconfigured. A canvas can
# be kept under a name, to ask later what became of its map.
_FRAME_COUNTER_JS = """(() => {
    if (window.__curio_mapFrames) return;
    const drawn = new WeakMap();
    const configured = new WeakMap();
    const unconfigured = new WeakSet();
    const kept = new Map();
    let detachedFrames = 0;
    let detachedConfigures = 0;
    let running = null;
    const request = window.requestAnimationFrame.bind(window);
    window.requestAnimationFrame = (callback) => request((time) => {
        const outer = running;
        running = new Set();
        try {
            return callback(time);
        } finally {
            running = outer;
        }
    });
    const Context = window.GPUCanvasContext;
    const counts = !!(Context && Context.prototype.getCurrentTexture
        && Context.prototype.configure && Context.prototype.unconfigure);
    if (counts) {
        const { getCurrentTexture, configure, unconfigure } = Context.prototype;
        Context.prototype.getCurrentTexture = function (...args) {
            const canvas = this.canvas;
            if (running && canvas instanceof HTMLCanvasElement && !running.has(canvas)) {
                running.add(canvas);
                if (canvas.isConnected) drawn.set(canvas, (drawn.get(canvas) || 0) + 1);
                else detachedFrames += 1;
            }
            return getCurrentTexture.apply(this, args);
        };
        Context.prototype.configure = function (...args) {
            const canvas = this.canvas;
            if (canvas instanceof HTMLCanvasElement) {
                if (canvas.isConnected) configured.set(canvas, (configured.get(canvas) || 0) + 1);
                else detachedConfigures += 1;
            }
            return configure.apply(this, args);
        };
        Context.prototype.unconfigure = function (...args) {
            if (this.canvas instanceof HTMLCanvasElement) unconfigured.add(this.canvas);
            return unconfigure.apply(this, args);
        };
    }
    const canvasOf = (nodeId) => document.getElementById('autk-grammar-map-' + nodeId);
    window.__curio_countsMapFrames = counts;
    window.__curio_mapFrames = (nodeId) => {
        const canvas = canvasOf(nodeId);
        return canvas ? drawn.get(canvas) || 0 : null;
    };
    window.__curio_mapConfigures = (nodeId) => {
        const canvas = canvasOf(nodeId);
        return canvas ? configured.get(canvas) || 0 : null;
    };
    window.__curio_detachedMapFrames = () => detachedFrames;
    window.__curio_detachedMapConfigures = () => detachedConfigures;
    window.__curio_keepMapCanvas = (name, nodeId) => {
        const canvas = canvasOf(nodeId);
        if (canvas) kept.set(name, canvas);
        return !!canvas;
    };
    window.__curio_keptMapCanvas = (name) => {
        const canvas = kept.get(name);
        return canvas ? {inPage: canvas.isConnected, unconfigured: unconfigured.has(canvas)} : null;
    };
})();"""

# Resolves once the page has drawn *frames* frames, or *timeout* ms have gone.
_PAGE_FRAMES_JS = """([frames, timeout]) => new Promise((resolve) => {
    let drawn = 0;
    const timer = setTimeout(() => resolve(drawn), timeout);
    const tick = () => {
        drawn += 1;
        if (drawn >= frames) {
            clearTimeout(timer);
            resolve(drawn);
        } else {
            requestAnimationFrame(tick);
        }
    };
    requestAnimationFrame(tick);
})"""

# What each map in *ids*, and every canvas out of the page, drew while the page
# drew *frames* frames.
_COUNT_FRAMES_JS = """async ([ids, frames, timeout]) => {
    const counts = () => ids.map((id) => window.__curio_mapFrames(id));
    const before = counts();
    const detachedBefore = window.__curio_detachedMapFrames();
    const pageFrames = await (%s)([frames, timeout]);
    const after = counts();
    return {
        pageFrames,
        maps: Object.fromEntries(ids.map((id, k) => [
            id, after[k] === null || before[k] === null ? null : after[k] - before[k],
        ])),
        detached: window.__curio_detachedMapFrames() - detachedBefore,
    };
}""" % _PAGE_FRAMES_JS

# How many times a window resize configured the map's canvas, and canvases out
# of the page, once the page has drawn *frames* frames after it.
_RESIZE_JS = """async ([id, frames, timeout]) => {
    const map = window.__curio_mapConfigures(id);
    const detached = window.__curio_detachedMapConfigures();
    window.dispatchEvent(new Event('resize'));
    await (%s)([frames, timeout]);
    const after = window.__curio_mapConfigures(id);
    return {
        map: map === null || after === null ? null : after - map,
        detached: window.__curio_detachedMapConfigures() - detached,
    };
}""" % _PAGE_FRAMES_JS


def _spec(*, scenario: bool) -> dict:
    node = lambda node_id, node_type, x, y, content: {  # noqa: E731
        "id": node_id, "type": node_type, "x": x, "y": y, "content": content,
        "in": "DEFAULT", "out": "DEFAULT", "goal": "", "metadata": {"keywords": []},
    }
    dataflow = {
        "name": "Hidden maps",
        "task": "",
        "timestamp": 1789193389280,
        "provenance_id": "Hidden maps",
        # The map sits far below its loader: framed alone, the loader leaves it
        # out of the window.
        "nodes": [
            node(LOADER, "curio.builtin/data-loading", 0, 0, LOADER_CODE),
            node(MAP, "curio.builtin/autk-grammar", 0, 1400, MAP_CONTENT),
        ],
        "edges": [
            {"id": "e-load-map", "source": LOADER, "target": MAP,
             "sourceHandle": "out", "targetHandle": "in"},
        ],
    }
    if scenario:
        dataflow["scenarios"] = [{"id": SCENARIO, "name": "The map", "color": "#2a9d8f", "nodes": [MAP]}]
    return {"dataflow": dataflow}


def _require_webgpu(page) -> None:
    has_adapter = bool(page.evaluate(
        "async () => !!(navigator.gpu && await navigator.gpu.requestAdapter())"
    ))
    if not has_adapter:
        if os.environ.get("CURIO_REQUIRE_HARDWARE_WEBGPU") == "1":
            pytest.fail("CURIO_REQUIRE_HARDWARE_WEBGPU=1 but this browser has no WebGPU adapter")
        pytest.skip("running an Autark node needs a WebGPU adapter; this browser has none")
    assert page.evaluate("() => window.__curio_countsMapFrames"), (
        "the browser has WebGPU but no GPUCanvasContext to count a map's frames on"
    )


def _open_dataflow(page, app_frontend, current_server: str, *, username: str, scenario: bool) -> dict:
    """Open the dataflow with the frame counter installed, and run it."""
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    page.add_init_script(script=_FRAME_COUNTER_JS)
    spec = _spec(scenario=scenario)
    session = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Hidden Maps",
        username=username,
        project_name="Hidden maps",
        project_spec=spec,
    )
    require_owner_view(page)
    for node in spec["dataflow"]["nodes"]:
        node_locator(page, node["id"]).wait_for(state="visible", timeout=45000)
    _require_webgpu(page)
    run_all_and_wait(page, timeout_ms=240000)
    _assert_map_ran(page, "after Run All")
    return session


def _assert_map_ran(page, when: str) -> None:
    status = wait_for_node_settled(page, MAP, node_type="autk-grammar", timeout_ms=120000)
    detail = read_node_error_text(node_locator(page, MAP)) if status == "error" else ""
    assert status == "done", f"the map did not draw {when}: {detail}"


def _count_frames(page) -> dict:
    """What the map, and every map canvas out of the page, drew while the page
    drew ``RULER_FRAMES`` frames, once it had ``GRACE_FRAMES`` to settle."""
    page.evaluate(_PAGE_FRAMES_JS, [GRACE_FRAMES, RULER_TIMEOUT_MS])
    counted = page.evaluate(_COUNT_FRAMES_JS, [[MAP], RULER_FRAMES, RULER_TIMEOUT_MS])
    assert counted["pageFrames"] >= RULER_FRAMES, (
        f"the page drew {counted['pageFrames']} of {RULER_FRAMES} frames in {RULER_TIMEOUT_MS} ms: {counted}"
    )
    return counted


def _assert_map_draws(page, when: str) -> None:
    """The map, in the window, draws frames, and its canvas holds a map."""
    frame_nodes(page, [MAP])
    counted = _count_frames(page)
    assert counted["maps"][MAP], (
        f"the map drew no frame {when}, in the window, while the page drew {RULER_FRAMES}: {counted}"
    )
    assert_autark_map_drawn(page, MAP, timeout=60000)


def _check_hidden_map(page, why: str, problems: list[str]) -> None:
    """The map, in the page but hidden by ``display: none``, draws no frame."""
    frames = _count_frames(page)["maps"][MAP]
    assert frames is not None, f"{why}: the map has no canvas in the page"
    if frames:
        problems.append(f"{why} drew {frames} frames while the page drew {RULER_FRAMES}")


def _check_still_drawing(page, why: str, problems: list[str]) -> None:
    """The map, laid out though nobody sees it, keeps drawing, and its canvas
    reads as a drawn map, as screenshots and drawing checks read it."""
    frames = _count_frames(page)["maps"][MAP]
    assert frames is not None, f"{why}: the map has no canvas in the page"
    if not frames:
        problems.append(f"{why} stopped drawing: no frame while the page drew {RULER_FRAMES}")
    try:
        assert_autark_map_drawn(page, MAP, timeout=10000)
    except AssertionError as error:
        problems.append(f"{why} lost its picture: {error}")


def _keep_canvas(page, name: str) -> None:
    """Keep the map's canvas as *name*, to ask later what became of its map."""
    assert page.evaluate("([name, id]) => window.__curio_keepMapCanvas(name, id)", [name, MAP]), (
        f"the map has no canvas to keep as {name!r}"
    )


def _check_dead_map(page, name: str, why: str, problems: list[str]) -> None:
    """The map of the canvas kept as *name*, once that canvas has left the page,
    draws no frame and is destroyed. A node's teardown runs a moment after its
    canvas leaves, so what became of the map is read after the frames."""
    try:
        page.wait_for_function(
            "(name) => { const kept = window.__curio_keptMapCanvas(name); return !!kept && !kept.inPage; }",
            arg=name, timeout=15000,
        )
    except PlaywrightTimeoutError:
        kept = page.evaluate("(name) => window.__curio_keptMapCanvas(name)", name)
        raise AssertionError(f"{why}: its canvas is still in the page: {kept}") from None
    frames = _count_frames(page)["detached"]
    kept = page.evaluate("(name) => window.__curio_keptMapCanvas(name)", name)
    if frames:
        problems.append(f"{why} drew {frames} frames out of the page while the page drew {RULER_FRAMES}")
    if not kept["unconfigured"]:
        problems.append(f"{why} was not destroyed: its canvas's WebGPU context is still configured")


def _check_resize(page, problems: list[str], *, live_map: bool) -> None:
    """A window resize configures no canvas that has left the page, and, with
    *live_map*, does reach the map."""
    took = page.evaluate(_RESIZE_JS, [MAP, GRACE_FRAMES, RULER_TIMEOUT_MS])
    if live_map:
        assert took["map"], f"the map did not take a window resize: {took}"
    if took["detached"]:
        problems.append(
            f"a window resize configured canvases out of the page {took['detached']} times: "
            "maps nobody will see again still listen for it"
        )


def _assert_no_problems(problems: list[str]) -> None:
    assert not problems, "maps drew while hidden, were kept once dead, or stopped while laid out:\n- " + (
        "\n- ".join(problems)
    )


def _scenario_card(page):
    return page.get_by_test_id(f"scenario-card-{SCENARIO}")


def _leave_the_dataflow(page) -> None:
    """Back to the projects page through the top bar's logo, in the app: the
    dataflow's nodes leave this same page. Unsaved changes are discarded."""
    page.locator('header[data-curio-menu-bar="true"] a[href="/projects"]').first.click()
    discard = page.get_by_role("button", name="Discard and continue")
    deadline = time.monotonic() + 20
    while "/projects" not in page.url:
        assert time.monotonic() < deadline, f"leaving the dataflow did not reach the projects page: {page.url}"
        if discard.count() and discard.first.is_visible():
            discard.first.click()
        page.wait_for_timeout(200)
    page.wait_for_url("**/projects", timeout=15000)


def test_a_map_in_a_collapsed_scenario_draws_nothing_until_it_is_expanded(
    app_frontend: "FrontendPage", current_server: str, page,
):
    _open_dataflow(page, app_frontend, current_server, username="hidden_maps_scenario", scenario=True)
    _assert_map_draws(page, "shown")
    page.get_by_role("button", name="View menu").click()
    page.get_by_role("button", name="Show scenarios", exact=True).click()
    _scenario_card(page).wait_for(state="visible", timeout=10000)
    problems: list[str] = []

    # Collapsed, its map is hidden in the box: it draws nothing.
    _scenario_card(page).get_by_role("button", name="Collapse", exact=True).click()
    node_locator(page, MAP).wait_for(state="hidden", timeout=10000)
    _check_hidden_map(page, "the map of a collapsed scenario", problems)

    # Expanded, it draws again.
    _scenario_card(page).get_by_role("button", name="Expand", exact=True).click()
    node_locator(page, MAP).wait_for(state="visible", timeout=10000)
    _assert_map_draws(page, "expanded")

    # Run inside the collapsed box, the new map draws nothing and the one it
    # replaced is destroyed; expanded, the new one draws (#711).
    _scenario_card(page).get_by_role("button", name="Collapse", exact=True).click()
    node_locator(page, MAP).wait_for(state="hidden", timeout=10000)
    _keep_canvas(page, "replaced")
    run_all_and_wait(page, timeout_ms=240000)
    _assert_map_ran(page, "inside the collapsed box")
    _check_dead_map(page, "replaced", "the map Run All replaced inside the collapsed box", problems)
    _check_hidden_map(page, "a map run inside a collapsed scenario", problems)
    _scenario_card(page).get_by_role("button", name="Expand", exact=True).click()
    node_locator(page, MAP).wait_for(state="visible", timeout=10000)
    _assert_map_draws(page, "run collapsed, then expanded")

    # Leaving the dataflow, in the app, closes it: its map is destroyed.
    _keep_canvas(page, "closed")
    _leave_the_dataflow(page)
    _check_dead_map(page, "closed", "the map of a closed dataflow", problems)
    _check_resize(page, problems, live_map=False)

    _assert_no_problems(problems)


def test_a_map_hidden_in_its_node_draws_nothing_and_a_dead_one_is_destroyed(
    app_frontend: "FrontendPage", current_server: str, page,
):
    _open_dataflow(page, app_frontend, current_server, username="hidden_maps_in_node", scenario=False)
    _assert_map_draws(page, "shown")
    node = node_locator(page, MAP)
    problems: list[str] = []

    # Behind its grammar tab, the output pane that holds the map is hidden.
    node.locator('.nav-link[data-rr-ui-event-key="grammar"]').first.dispatch_event("click")
    node.locator(f"#autk-grammar-map-{MAP}").wait_for(state="hidden", timeout=10000)
    _check_hidden_map(page, "a map behind its node's grammar tab", problems)
    node.locator('.nav-link[data-rr-ui-event-key="output"]').first.dispatch_event("click")
    node.locator(f"#autk-grammar-map-{MAP}").wait_for(state="visible", timeout=10000)
    _assert_map_draws(page, "back on its output tab")

    # Minimized, the node is a chip; a click opens it again.
    activate_header_icon(page.locator(f'[id="{MAP}resizable"] .curio-node-tools [title="Minimize"]'))
    page.locator(f'[id="{MAP}resizable"]').wait_for(state="hidden", timeout=10000)
    _check_hidden_map(page, "a minimized node's map", problems)
    node.click()
    page.locator(f'[id="{MAP}resizable"]').wait_for(state="visible", timeout=10000)
    _assert_map_draws(page, "opened again from its chip")

    # Out of the window, the map is still laid out: it keeps drawing. The
    # loader framed alone leaves it far below.
    frame_nodes(page, [LOADER])
    assert not page.evaluate(
        """(id) => {
            const box = document.getElementById('autk-grammar-map-' + id).getBoundingClientRect();
            return box.bottom > 0 && box.right > 0 && box.top < innerHeight && box.left < innerWidth;
        }""",
        MAP,
    ), "framing the loader alone left the map in the window"
    _check_still_drawing(page, "a map out of the window", problems)
    _assert_map_draws(page, "framed again")

    # A re-run replaces the map's canvas: the map that drew on it is destroyed,
    # and the node keeps working: its new map draws and takes a window resize.
    # The node reads Done from its last run until the new map draws.
    _keep_canvas(page, "replaced")
    play_node(page, MAP)
    page.wait_for_function(
        """(id) => {
            const kept = window.__curio_keptMapCanvas('replaced');
            return !!kept && !kept.inPage && window.__curio_mapFrames(id) > 0;
        }""",
        arg=MAP, timeout=180000, polling=250,
    )
    _assert_map_ran(page, "on a re-run")
    _check_dead_map(page, "replaced", "the map a re-run replaced", problems)
    _assert_map_draws(page, "re-run")
    _check_resize(page, problems, live_map=True)

    # A deleted node's map is destroyed.
    _keep_canvas(page, "deleted")
    activate_header_icon(node.get_by_title("Delete node").first)
    page.wait_for_function(
        "(id) => !document.querySelector(`.react-flow__node[data-id='${id}']`)", arg=MAP, timeout=10000,
    )
    _check_dead_map(page, "deleted", "the map of a deleted node", problems)
    _check_resize(page, problems, live_map=False)

    _assert_no_problems(problems)
