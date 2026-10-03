"""Robustness scenes: the dashboard page, Autark without WebGPU, Run All after
a failed node, the street-vision example's first node, an Autark data step.
"""
from __future__ import annotations

import re

from playwright.sync_api import expect

from ..utils import (
    assert_autark_map_drawn,
    dismiss_toasts,
    assert_vega_canvas_rendered,
    frame_node,
    hold_node_execution,
    node_locator,
    play_node,
    release_node_execution,
    run_all_and_wait,
    run_all_button,
    run_node_and_wait,
    wait_for_held_node_execution,
    wait_for_node_done,
    wait_for_run_all_to_end,
    watch_run_all,
)
from .framework import Ctx, walkthrough
from .steps import first_node_of_type, frame_until_on_top
from .provenance import PROVENANCE_EXAMPLE


# ---------------------------------------------------------------------------
# Robustness (#192, #201)
# ---------------------------------------------------------------------------

#: The lightest curated example that actually contains Autark nodes. The
#: default (a Vega-Lite dataflow) has none, so the scene would have nothing to
#: run and would fail for a reason unrelated to the fix.
AUTARK_EXAMPLE = "07-autark-gpu-shader.json"


def save_from_the_status_icon(ctx: Ctx) -> None:
    """Save the open dataflow and wait until the indicator says it is on disk.

    The status icon rather than File > Save: it is one click, it is the control
    a user reaches for, and its ``data-curio-save-state`` is the one signal that
    the request actually finished rather than merely started.
    """
    page = ctx.page
    ctx.click(page.locator("[data-curio-save-state]").first, force=True)
    page.wait_for_function(
        "() => document.querySelector('[data-curio-save-state]')"
        "?.getAttribute('data-curio-save-state') === 'saved'",
        timeout=30000,
    )


def dataflow_id_from_url(page) -> str:
    """The project id of the dataflow open in *page*, read off its route."""
    match = re.search(r"/dataflow/([0-9a-f-]{36})", page.url)
    assert match, f"not on a saved dataflow: {page.url}"
    return match.group(1)


@walkthrough(
    slug="dashboard-page-renders-pinned-charts",
    example=PROVENANCE_EXAMPLE,
    refs=[125, 192],
    title="A dashboard is a page of its own",
    premise="Pin a chart, save, open the dashboard: the chart is there without "
            "pressing Run. Unpin it and the page says what is missing.",
    note="Dashboard Mode was a state of the canvas: no URL to share, and nothing "
         "on it after a reload, because a chart only drew when Play was pressed "
         "and its data was readable only by the session that ran it. The "
         "dashboard is now its own route, the outputs behind a pinned tile are "
         "saved to the Data Catalog, and the tile draws from them on load.",
    tests=[
        "src/tests/pages/dashboardPage.test.tsx",
        "src/tests/components/universalNodeAutoRender.test.tsx",
        "src/tests/utils/dashboardLayout.test.ts",
        "src/tests/providers/dashboardPresentation.test.tsx",
        "utk_curio/sandbox/tests/test_get_shared_file_fallback.py",
    ],
)
def dashboard_page_renders_pinned_charts(ctx: Ctx) -> None:
    page = ctx.page

    # RUN the chart, so there is an output behind it to save. `play_node` runs
    # the not-yet-successful ancestors too, so this runs the chain feeding it.
    ctx.say("Run the chart", "A dashboard shows what a run produced.")
    node_id = first_node_of_type(PROVENANCE_EXAMPLE, "vis-vega")
    node = node_locator(page, node_id)
    node.wait_for(state="visible", timeout=45000)
    # Not `run_node_and_wait`: that waits for a code node's text pane, which a
    # chart does not have. Wait on the status attribute, then on drawn marks.
    play_node(page, node_id)
    wait_for_node_done(page, node_id, node_type="vis-vega", timeout_ms=180000)
    assert_vega_canvas_rendered(page, node_id, timeout=60000)

    ctx.say("Pin it, and save", "Pinning saves the output behind the chart.")
    pin = node.get_by_role("button", name="Pin to dashboard")
    # This chart is the top node of a tall dataflow, so at fit zoom its header
    # sits under the menu bar (#493) and the click would land on the bar. The
    # capture refits the view, so framing it here changes no frame.
    frame_until_on_top(page, node_id, pin.first)
    ctx.click(pin.first)
    save_from_the_status_icon(ctx)
    project_id = dataflow_id_from_url(page)

    ctx.say("Share", "The dashboard and the dataflow each have a link.")
    # Clear the pin and save toasts BEFORE opening the menu. The capture helper
    # sweeps toasts by clicking their close buttons, and a click anywhere else
    # on the page is what closes this dropdown - so an unswept toast at capture
    # time photographs a menu that has just shut.
    dismiss_toasts(page)
    ctx.click(page.get_by_test_id("share-menu-btn"), force=True)
    page.get_by_test_id("open-dashboard-link").wait_for(state="visible", timeout=10000)
    ctx.capture("share-menu")
    # Close it again: the capture is the only thing that needed it open.
    ctx.click(page.get_by_test_id("share-menu-btn"), force=True)

    # The menu's link opens a NEW tab, which `test_dashboard_page_e2e.py` asserts.
    # A walkthrough records one page, so it navigates this one instead - a full
    # load, which is the point: nothing the canvas held in memory comes along.
    ctx.say("Open the dashboard", "A full page load: nothing is kept from the canvas.")
    page.goto(f"{ctx.frontend}/dashboard/{project_id}")
    page.get_by_test_id("open-dataflow-link").wait_for(state="visible", timeout=45000)

    # The pinned chart drew, and nothing pressed Play on this page to make it.
    # Scoped to the Vega mount (`"vega" + nodeId`): a bare `canvas` finds
    # Monaco's hidden overview ruler first.
    chart = page.locator(f"#vega{node_id} canvas").first
    chart.wait_for(state="visible", timeout=90000)
    assert chart.evaluate("c => c.width > 0 && c.height > 0"), (
        "the dashboard laid out the pinned chart but it drew nothing: the output "
        "behind it was not restored from the Data Catalog"
    )
    # A page, not the canvas: no palette, no node chrome to pin or run with.
    assert page.locator("#tools-menu").count() == 0, "the editor's palette is on the dashboard"
    assert page.get_by_role("button", name="Pin to dashboard").count() == 0, (
        "a tile is showing the canvas node header"
    )
    ctx.capture("dashboard-page")

    ctx.say("And with nothing pinned", "The page says what is missing, and where to fix it.")
    ctx.click(page.get_by_test_id("open-dataflow-link"))
    node = node_locator(page, node_id)
    node.wait_for(state="visible", timeout=45000)
    unpin = node.get_by_role("button", name="Unpin from dashboard")
    # Back on the canvas, the load fit puts the header under the menu bar again.
    frame_until_on_top(page, node_id, unpin.first)
    ctx.click(unpin.first)
    save_from_the_status_icon(ctx)

    page.goto(f"{ctx.frontend}/dashboard/{project_id}")
    empty = page.get_by_test_id("dashboard-empty")
    empty.wait_for(state="visible", timeout=45000)
    expect(empty).to_contain_text("Nothing is pinned to this dashboard yet.")
    ctx.capture("empty-state")


@walkthrough(
    slug="autark-without-webgpu-says-so",
    refs=[201, 272],
    title="An Autark node on a browser without WebGPU",
    premise="Run an Autark node where WebGPU is unavailable, and read the node.",
    note="Nothing asked whether the browser had WebGPU. The library swallows "
         "its own init failure and carries on until the layer loader reaches "
         "`this._renderer.device.createShaderModule`, throwing a TypeError - "
         "and with no error boundary anywhere, that throw unmounted the whole "
         "React root and left a blank page. The node now checks first, says "
         "what is missing and what to do about it, and the canvas survives. "
         "Since #272 the answer is not final either: the panel's Check again "
         "re-probes, because Firefox returns no adapter on the first ask while "
         "its GPU process starts, and a negative is never cached. Since #603 a "
         "run stops at the first node that cannot run: the compute pass "
         "feeding the map shows the panel, and the map says which node it "
         "waits on.",
    tests=["src/tests/adapters/node/autkGrammarWebgpuFallback.test.tsx",
           "src/tests/utils/webgpuSupport.test.ts",
           "src/tests/components/errorBoundary.test.tsx"],
    example=AUTARK_EXAMPLE,
    max_diff_ratio=0.05,
)
def autark_without_webgpu_says_so(ctx: Ctx) -> None:
    page = ctx.page

    # Take WebGPU away in the page itself. `add_init_script` would need to run
    # before navigation and the runner has already navigated, so the property is
    # redefined in place - the probe reads it at run time, not at load time.
    # The real object is stashed so the recovery half below can hand it back.
    page.evaluate(
        "() => { window.__curioRealGpu = navigator.gpu;"
        " Object.defineProperty(navigator, 'gpu',"
        " { configurable: true, value: undefined }); }"
    )
    ctx.say("A browser with no WebGPU",
            "Firefox and Safari today; Chrome on a blocklisted driver.")

    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))

    # Resolved from the spec: a node's Curio type is not on the DOM element,
    # only React Flow's data-id, so display text would be a guess.
    # Must be a node whose spec declares a map/plot/compute - those are the
    # only ones that need a GPU, and so the only ones the guard fires for.
    node_id = first_node_of_type(AUTARK_EXAMPLE, "autk-grammar", containing='"map"')
    autark = page.locator(f'.react-flow__node[data-id="{node_id}"]')
    autark.wait_for(state="visible", timeout=45000)
    autark.scroll_into_view_if_needed()
    ctx.focus(autark, hold=1000)
    # Running the map runs the compute pass that feeds it first, and that pass
    # is the first node in the chain that needs WebGPU. A run stops below a
    # node that failed (#603), so the compute pass is the node that says what
    # is missing, and the map is not run at all.
    compute_id = first_node_of_type(AUTARK_EXAMPLE, "autk-grammar", containing='"compute"')
    compute = page.locator(f'.react-flow__node[data-id="{compute_id}"]')

    ctx.say("Run it", "The old failure was a TypeError from inside the shader loader.")
    # The play control is a FontAwesome <svg>, not a named button, and React
    # Flow's transformed viewport can swallow a real click - `play_node` is the
    # helper that already deals with both.
    play_node(page, node_id)

    fallback = compute.locator('[role="alert"]')
    fallback.first.wait_for(state="visible", timeout=45000)
    ctx.focus(fallback.first, hold=1800)
    ctx.say("It says what is missing, and what to do",
            "Named cause, named remedy - and the canvas is still here.")
    ctx.capture("webgpu-fallback")

    # THE POINT: the app is alive. Before, the root had unmounted.
    assert page.locator(".react-flow__node").count() > 1, (
        "the canvas lost its nodes, so the throw was not contained"
    )
    expect(page.locator("#tools-menu")).to_be_visible()
    assert not errors, f"an uncaught page error escaped: {errors}"

    # A refusal did not wedge the runner (#271): the run-all control still
    # offers a run rather than a cancel, i.e. the guard was released.
    expect(page.get_by_role("button", name="Run all nodes")).to_be_visible()

    # The map was not run, and points back up the chain (#603).
    expect(autark).to_contain_text("The node feeding this one", timeout=45000)

    # Check again while WebGPU is still missing: the panel stays.
    check_again = fallback.first.get_by_role("button", name=re.compile("check", re.I))
    check_again.wait_for(state="visible", timeout=5000)
    ctx.focus(check_again, hold=900)
    ctx.say("Ask again", "Nothing has changed yet, so the answer is the same.")
    check_again.click()
    expect(fallback.first).to_be_visible()
    ctx.capture("webgpu-check-again")

    # Now WebGPU is back - the pref was flipped, or Firefox's GPU process came
    # up. The first version of the probe had memoised its "no" for the life of
    # the page, so this click would have changed nothing (#272).
    page.evaluate(
        "() => Object.defineProperty(navigator, 'gpu',"
        " { configurable: true, value: window.__curioRealGpu })"
    )
    ctx.say("WebGPU is back", "Check again re-probes and re-runs the node.")
    check_again.click()
    expect(fallback.first).to_be_hidden(timeout=45000)
    # The compute pass ran this time, so the map below it has rows to draw.
    # Waited on "done" itself: the node still reads "error" from the refusal
    # until the rerun settles, and a wait for any settled state returns at once.
    expect(compute.locator("[data-curio-node-status]").first).to_have_attribute(
        "data-curio-node-status", "done", timeout=180000)
    ctx.focus(compute, hold=1200)
    ctx.say("The compute pass ran", "The map below it was waiting on it.")
    run_all_and_wait(page, timeout_ms=180000)
    wait_for_node_done(page, node_id, node_type="autk-grammar", timeout_ms=180000)
    # The frame below cannot show it (a screenshot on the GPU runner has every
    # WebGPU canvas blank, #427), so the map's own pixels say it drew.
    assert_autark_map_drawn(page, node_id, timeout=45000, attach_as="webgpu-recovered map canvas")
    ctx.focus(autark, hold=1200)
    ctx.say("Run the dataflow", "With WebGPU back, the whole chain draws.")
    ctx.capture("webgpu-recovered")
    ctx.capture_node("webgpu-recovered-map", node_id)
    assert not errors, f"an uncaught page error escaped during recovery: {errors}"


@walkthrough(
    slug="run-all-survives-a-failed-node",
    refs=[271],
    title="Run All after a node fails",
    premise="Run all nodes where one Autark node cannot run, then run all again.",
    note="The runner waited for every node in a level to report success or "
         "error, and the guard that refused a second run lived in a ref. A node "
         "that never reported - an Autark node whose WebGPU init threw in a "
         "render, or whose probe hung - held the run, and every later click on "
         "Run All or a node's play silently did nothing until the dataflow was "
         "reopened. The run now always ends, the button shows a run in flight "
         "and cancels it, and a refused second click says so. Since #603 the "
         "nodes after a failed one are not run, and say which node they wait on.",
    tests=["src/tests/providers/playAllRelease.test.tsx",
           "src/tests/providers/playAllUpstreamFailed.test.tsx",
           "src/tests/components/toolsMenuRunAll.test.tsx",
           "src/tests/adapters/node/autkGrammarWebgpuFallback.test.tsx"],
    example=AUTARK_EXAMPLE,
    max_diff_ratio=0.05,
)
def run_all_survives_a_failed_node(ctx: Ctx) -> None:
    page = ctx.page
    page.evaluate(
        "() => Object.defineProperty(navigator, 'gpu',"
        " { configurable: true, value: undefined })"
    )
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))

    node_id = first_node_of_type(AUTARK_EXAMPLE, "autk-grammar", containing='"map"')
    autark = page.locator(f'.react-flow__node[data-id="{node_id}"]')
    autark.wait_for(state="visible", timeout=45000)

    # One button in two states, so the locator matches either name and the
    # assertions read the state off data-run-active.
    run_all = run_all_button(page)
    ctx.focus(run_all, hold=900)
    ctx.say("Run all nodes", "One of them cannot run here.")

    # Hold the run open on purpose. The only node here that leaves the browser
    # is the Autark DATA node in level 0; the compute pass after it needs WebGPU
    # and refuses in the tick it is triggered, and nothing after that runs. So
    # the window in which the button
    # reads "Cancel run" is exactly the length of that one request - fine on a
    # quiet machine, and nothing this scene controls on a loaded one. Held, the
    # in-flight state it photographs is a fact rather than a lucky shot.
    hold_node_execution(page)
    watch_run_all(page)
    run_all.click()

    # While the run is in flight the same button offers to cancel it.
    expect(run_all).to_have_attribute("data-run-active", "true", timeout=15000)
    expect(run_all).to_have_attribute("aria-label", "Cancel run")
    wait_for_held_node_execution(page)
    ctx.capture("run-in-flight", allow_running=True)
    release_node_execution(page)

    # The first Autark node that needs WebGPU, the compute pass, refuses and
    # reports it - which is what releases its level. The nodes after it are not
    # run (#603): the map says which node it waits on.
    compute_id = first_node_of_type(AUTARK_EXAMPLE, "autk-grammar", containing='"compute"')
    compute = page.locator(f'.react-flow__node[data-id="{compute_id}"]')
    compute.locator('[role="alert"]').first.wait_for(state="visible", timeout=45000)
    expect(autark).to_contain_text("The node feeding this one", timeout=45000)

    # The run ends on its own: the button is Run All again, not a dead control.
    wait_for_run_all_to_end(page, timeout_ms=180000)
    expect(run_all).to_have_attribute("aria-label", "Run all nodes")
    ctx.focus(run_all, hold=1200)
    ctx.say("The run ended", "A failed node no longer holds every later run hostage.")
    ctx.capture("run-ended")

    # And a second run is accepted - the guard was released, not wedged.
    #
    # Not by catching that run in flight: nothing in this dataflow can be slow
    # the second time. The data node answers from its own cache, so the second
    # run makes no request at all, the compute pass refuses at the WebGPU probe
    # and nothing after it runs. The run can be over before a locator resolves, and clicking
    # "Cancel run" then waits out its whole budget for a button that has gone
    # back to saying "Run all nodes" (CI run 35275085327). What is watched
    # instead is the guard's own transitions, which a run that starts and ends
    # within one frame still leaves behind. Cancelling a run is a click this
    # scene cannot make honestly; test_run_lock_release_e2e.py makes it with a
    # run held open, and toolsMenuRunAll / playAllRelease cover the handler.
    ctx.say("Run all again", "The second run is accepted, and it ends too.")
    second = run_all_and_wait(page, timeout_ms=180000)
    assert second["started"] >= 1, (
        "the second Run All was refused: the run guard never went active (#271)"
    )
    expect(run_all).to_have_attribute("aria-label", "Run all nodes")
    assert not errors, f"an uncaught page error escaped: {errors}"


STREET_VISION_EXAMPLE = "10-street-vision-cv-analysis.json"


@walkthrough(
    slug="street-vision-example-loads-its-boundaries",
    refs=[276],
    title="The street-vision example's first node runs on a fresh install",
    premise="Open the curated street-vision example and run its first node.",
    note="The example fetched Chicago's neighborhood boundaries from a Socrata "
         "id the portal has since retired, so a curated example failed on its "
         "very first node with a 404 - and the node after it then blamed its "
         "wiring. The layer now ships in the Data Catalog and the node reads it "
         "with curio_data_path, so the run is offline and deterministic.",
    tests=["utk_curio/backend/tests/test_frontend/test_examples.py"],
    example=STREET_VISION_EXAMPLE,
    # The scene frames the loader node itself; the harness must not re-fit.
    fit_reactflow=False,
    # The claim above is asserted in code; the PNG only documents it. The
    # Linux runner antialiases text differently from the machine that captured
    # the baseline - here a full frame, 5.4% on CI - so the pin
    # leaves room for that without waving through a real change.
    max_diff_ratio=0.08,
)
def street_vision_example_loads_its_boundaries(ctx: Ctx) -> None:
    page = ctx.page

    node_id = first_node_of_type(
        STREET_VISION_EXAMPLE, "data-loading",
        containing="data.cityofchicago.neighborhoods",
    )
    node = page.locator(f'.react-flow__node[data-id="{node_id}"]')
    node.wait_for(state="visible", timeout=45000)
    node.scroll_into_view_if_needed()
    ctx.focus(node, hold=1000)
    ctx.say("The first node of the street-vision example",
            "It used to fetch a live URL that no longer exists.")

    text = run_node_and_wait(page, node_id, node_type="data-loading", timeout_ms=180000)
    assert "Saved to file" in text, (
        f"the boundaries loader should have produced an artifact, got {text!r}"
    )
    # At fit-view this twelve-node canvas makes the loader a thumbnail; the
    # output line is the claim, so frame the node before pinning it.
    frame_node(page, node_id, zoom=1.1)
    ctx.focus(node, hold=1200)
    ctx.say("Loaded from the Data Catalog",
            "98 neighborhood polygons, no network involved.")
    ctx.capture("boundaries-loaded")


PBF_EXAMPLE = "11-autark-pbf-loading.json"


@walkthrough(
    slug="autark-data-node-says-what-it-loaded",
    refs=[282],
    title="An Autark data step reports what it produced",
    premise="Run the PBF-loading step of an Autark chain, and read its body.",
    note="An autk-grammar node whose spec has only a `data` (or `compute`) "
         "section has nothing to draw, so its body was a blank box under a "
         "green Done chip - indistinguishable from a node that never ran or "
         "silently failed. Before a run it now says what running it will do; "
         "after, it names the tables it created for the next node.",
    tests=["src/tests/adapters/node/behaviors.test.tsx"],
    example=PBF_EXAMPLE,
    # The claim above is asserted in code; the PNG only documents it.
    max_diff_ratio=0.08,
)
def autark_data_node_says_what_it_loaded(ctx: Ctx) -> None:
    page = ctx.page

    # The data-only step: the one whose spec carries a PBF source and no map.
    node_id = first_node_of_type(PBF_EXAMPLE, "autk-grammar", containing='"pbfFileUrl"')
    node = page.locator(f'.react-flow__node[data-id="{node_id}"]')
    node.wait_for(state="visible", timeout=45000)
    node.scroll_into_view_if_needed()
    ctx.focus(node, hold=1000)

    # The body lives in the editor's Output pane; before a run the grammar
    # tab is the active one, so open the pane the way a user would.
    node.locator('.nav-link[data-rr-ui-event-key="output"]').first.click()
    # The click leaves the tab hovered and focused, and its "Output" tooltip
    # would sit in every capture after it.
    page.evaluate("document.activeElement && document.activeElement.blur()")
    page.mouse.move(5, 5)
    expect(page.get_by_role("tooltip")).to_have_count(0, timeout=5000)
    # It loads its own data, so it is "not run" (not waiting on an upstream).
    before = node.locator('[data-curio-node-empty="not-run"]')
    before.first.wait_for(state="visible", timeout=15000)
    assert "loads data" in (before.first.inner_text() or ""), (
        "the pre-run body should say this step loads data"
    )
    ctx.say("Before a run, the step says what it is for",
            "Not a blank box: 'This step loads data; run it to pass tables downstream.'")
    ctx.capture("before-run")

    ctx.say("Run it", "Loads the PBF into DuckDB in the sandbox - nothing to draw here.")
    play_node(page, node_id)
    wait_for_node_done(page, node_id, node_type="autk-grammar", timeout_ms=180000)

    summary = node.locator("[data-curio-autk-summary]")
    summary.first.wait_for(state="visible", timeout=15000)
    text = summary.first.inner_text() or ""
    assert text.startswith("Loaded"), f"expected a 'Loaded N tables' line, got {text!r}"
    assert "table_osm_" in text, f"the summary should name the OSM tables, got {text!r}"
    assert before.count() == 0, "the pre-run hint should give way to the summary"
    # The map below draws on its own once these tables reach it, after this
    # node's Done; the frame shows it drawn.
    map_id = first_node_of_type(PBF_EXAMPLE, "autk-grammar", containing='"map"')
    wait_for_node_done(page, map_id, node_type="autk-grammar", timeout_ms=180000)
    assert_autark_map_drawn(page, map_id, timeout=45000)
    ctx.focus(summary.first, hold=1500)
    ctx.say("After, it names what it made",
            "The same tables the next node's map will draw.")
    ctx.capture("after-run")
    ctx.capture_node("after-run-map", map_id)
