"""Scenes on the provenance drawer: a loaded dataflow's history, moving
around it, and reverting."""
from __future__ import annotations

from ..utils import assert_header_shows_save, save_dataflow_and_settle_header
from .framework import Ctx, walkthrough
from .steps import (
    PROVENANCE_PANEL,
    await_canvas_nodes,
    canvas_graph,
    close_provenance,
    load_example_spec,
    open_provenance,
    open_version,
    park_pointer_off_drawer,
    put_version_on_canvas,
    version_graph,
)


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------

PROVENANCE_EXAMPLE = "01-vega-lite-chained-transforms.json"


@walkthrough(
    slug="provenance-graph-of-a-loaded-dataflow",
    example=PROVENANCE_EXAMPLE,
    refs=[186],
    title="Loaded dataflows get a real provenance history",
    premise="Open a saved dataflow, then read its version history.",
    note="loadParsedTrill now snapshots each version from the arrays it was handed, "
        "not from the React Flow store, which is one commit stale inside its own "
        "synchronous load loop.",
    tests=["src/tests/hook/useWorkflowOperations.loadProvenance.test.ts",
           "test_frontend/test_walkthrough_baselines.py"],
    clip_selector=PROVENANCE_PANEL,
    fit_reactflow=False,
    catalog_calendar=True,
)
def provenance_graph_of_a_loaded_dataflow(ctx: Ctx) -> None:
    spec = load_example_spec(PROVENANCE_EXAMPLE)["dataflow"]
    node_count, edge_count = len(spec["nodes"]), len(spec["edges"])

    ctx.say("An example dataflow, opened from the gallery",
            "Every node and edge came from the saved spec.")
    panel = open_provenance(ctx)

    versions = panel.locator("[data-provenance-item]")
    assert versions.count() == 1 + node_count + edge_count, (
        f"the history lists {versions.count()} versions; one per loaded node and "
        f"edge plus the initial one would be {1 + node_count + edge_count}"
    )
    newest = versions.last
    assert newest.get_attribute("data-provenance-current") == "true", (
        "the drawer does not mark the newest version as the one on the canvas"
    )

    ctx.say("One version per node, then one per connection",
            "The newest is the one on the canvas.")
    open_version(ctx.page, newest, click=ctx.click)

    # The load-bearing check. DataflowThumbnail draws one <line> per edge and two
    # <rect> per node, and SKIPS any edge whose endpoints are missing from the
    # same preview -- so a version captured from the stale React Flow store (one
    # node, no edges) renders a background rect and nothing else. That is what
    # made the boxes read as blank and isolated.
    marks = newest.evaluate(
        "el => { const svg = el.querySelector('svg');"
        " return svg ? { lines: svg.querySelectorAll('line').length,"
        " rects: svg.querySelectorAll('rect').length } : null; }"
    )
    assert marks, "the newest version, opened, shows no thumbnail at all"
    assert marks["lines"] == edge_count, (
        f"the newest version's thumbnail draws {marks['lines']} of the "
        f"dataflow's {edge_count} connections - its snapshot is missing the "
        f"nodes they run between, so they are dropped and the box reads as empty"
    )
    assert marks["rects"] >= 1 + 2 * node_count, (
        f"the newest version's thumbnail draws {(marks['rects'] - 1) // 2} of "
        f"the dataflow's {node_count} nodes"
    )

    ctx.say("Every version holds the whole graph",
            "The dataflow as it stood at that step, not one node from a stale "
            "snapshot.")
    newest.get_by_text("On the canvas now").scroll_into_view_if_needed()
    ctx.focus(newest, hold=1600)


#: Whether the whole of a version shows in the drawer's body, the part of the
#: panel that scrolls. Measured against that body itself, not the nearest box
#: that scrolls, so a box in it that scrolls on its own cannot pass for it.
_IN_VIEW_JS = """(el) => {
    const panel = el.closest('[role="dialog"]');
    const body = Array.from(panel.children).find((child) => child.contains(el));
    const a = el.getBoundingClientRect();
    const b = body.getBoundingClientRect();
    return a.top >= b.top - 1 && a.bottom <= b.bottom + 1;
}"""


@walkthrough(
    slug="provenance-graph-navigation",
    example=PROVENANCE_EXAMPLE,
    refs=[187],
    title="Moving around the provenance history",
    premise="Open the version in use, then scroll back to the first one.",
    note="The drawer opens on the version in use, at the bottom of the list, "
         "and scrolls back through the history.",
    tests=["src/tests/components/provenanceDrawer.test.tsx",
           "src/tests/utils/provenanceTree.test.ts",
           "test_frontend/test_provenance_branches_e2e.py",
           "test_frontend/test_walkthrough_baselines.py"],
    clip_selector=PROVENANCE_PANEL,
    fit_reactflow=False,
    catalog_calendar=True,
)
def provenance_graph_navigation(ctx: Ctx) -> None:
    page = ctx.page
    panel = open_provenance(ctx)
    versions = panel.locator("[data-provenance-item]")
    newest, first = versions.last, versions.first

    assert newest.evaluate(_IN_VIEW_JS), "the drawer did not open on the version in use"
    ctx.say("The drawer opens on the version in use", "The newest, at the bottom.")
    open_version(page, newest, click=ctx.click)
    newest.get_by_text("On the canvas now").scroll_into_view_if_needed()
    ctx.beat(500)
    assert not first.evaluate(_IN_VIEW_JS), (
        "with the newest version open, the first one still shows: the history "
        "fits the drawer, so this scene cannot show it scrolling"
    )

    ctx.say("Scroll back", "Reach the first version.")
    first.scroll_into_view_if_needed()
    ctx.beat(500)
    assert first.evaluate(_IN_VIEW_JS), "scrolling did not bring the first version into view"
    assert not newest.evaluate(_IN_VIEW_JS), (
        "the newest version still shows whole beside the first one: the drawer "
        "did not scroll"
    )

    assert newest.locator("button").first.get_attribute("aria-expanded") == "true", (
        "scrolling away closed the version opened at the bottom"
    )
    park_pointer_off_drawer(page)
    ctx.beat(600)


@walkthrough(
    slug="provenance-reverting-to-a-previous-version",
    example=PROVENANCE_EXAMPLE,
    refs=[195],
    title="Reverting a dataflow to an earlier version",
    premise="Step back through the version history, saving each version, and "
            "watch the canvas follow.",
    note="onConnect resolved its target with `nodes.find(...) as Node` and never "
         "checked it, so reverting to a version whose edges named nodes it does "
         "not hold tore the canvas down. Such an edge is now dropped instead.",
    tests=["src/tests/providers/onConnectMissingEndpoint.test.tsx",
           "test_frontend/test_provenance_revert_e2e.py",
           "test_frontend/test_walkthrough_baselines.py"],
)
def provenance_reverting_to_a_previous_version(ctx: Ctx) -> None:
    page = ctx.page
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))

    saved = canvas_graph(page)
    ctx.say("The dataflow as saved",
            f"{saved['nodes']} nodes, {saved['edges']} connections.")

    panel = open_provenance(ctx)
    versions = panel.locator("[data-provenance-item]")
    count = versions.count()
    assert count > 1, f"the provenance history offers {count} versions to revert to"

    # Newest-first, skipping the one already on the canvas, so the dataflow
    # visibly unwinds. Four is the floor: a single hop would not show that the
    # history is walkable, only that one click works.
    targets = list(range(count - 2, -1, -1))
    assert len(targets) >= 4, (
        f"only {len(targets)} earlier versions available; this walkthrough steps "
        f"back through at least four"
    )

    ctx.say("Revert from a version's own button",
            "Opening a version shows it; its button puts it on the canvas.")

    def capture_canvas(label: str, *, nodes: int, reopen: bool = True) -> None:
        # The drawer covers the right of the canvas each frame is about, so close
        # it for the shot and open it again for the next version. The first
        # version is empty, and an empty canvas has nothing to fit.
        close_provenance(ctx)
        # A revert is an edit, so the header reads "Unsaved" until the 30 s
        # autosave, which lands on whichever frame the runner's speed puts it
        # near. Save the version on the canvas so every frame shows its own
        # saved header and categories. A save adds no version to the history.
        save_dataflow_and_settle_header(page)
        assert_header_shows_save(page)
        ctx.capture(label, fit_reactflow=nodes > 0)
        if reopen:
            open_provenance(ctx)

    for index in targets:
        version = versions.nth(index)
        open_version(page, version, click=ctx.click)
        expected = version_graph(version)
        put_version_on_canvas(ctx, version)
        await_canvas_nodes(page, expected["nodes"])
        actual = canvas_graph(page)

        assert not errors, (
            f"reverting to version {index + 1} threw, and with no error boundary "
            f"in the app React tears down the whole canvas: "
            f"{errors[0].splitlines()[0]}"
        )
        assert actual == expected, (
            f"reverting to version {index + 1} of {count} left {actual['nodes']} "
            f"nodes and {actual['edges']} connections on the canvas, but that "
            f"version holds {expected['nodes']} and {expected['edges']}"
        )
        assert version.get_attribute("data-provenance-current") == "true", (
            f"version {index + 1} is on the canvas, but the drawer still marks "
            f"another one as in use"
        )
        assert versions.count() == count, (
            f"reverting changed the history: {versions.count()} versions, not {count}"
        )
        capture_canvas(f"reverted-to-v{index + 1:02d}", nodes=expected["nodes"])

    ctx.say(f"Stepped back through {len(targets)} versions",
            "Each one put its own graph on the canvas.")

    # Forward to the newest, so the canvas ends where it started.
    newest = versions.nth(count - 1)
    open_version(page, newest, click=ctx.click)
    put_version_on_canvas(ctx, newest)
    await_canvas_nodes(page, saved["nodes"])
    restored = canvas_graph(page)
    assert restored == saved, (
        f"returning to the newest version left {restored} on the canvas, not the "
        f"saved dataflow's {saved}"
    )
    assert page.locator("#webpack-dev-server-client-overlay").count() == 0, (
        "the dev-server error overlay has taken the whole screen"
    )

    capture_canvas("returned-to-newest", nodes=saved["nodes"], reopen=False)

    page.wait_for_selector(".react-flow__node", timeout=20000)
    ctx.beat(800)
    ctx.say("And forward again",
            "Back to the saved dataflow, with no runtime error anywhere in the walk.")
