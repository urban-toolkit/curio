"""Scenes on the Provenance window: its graph, panning it, and reverting."""
from __future__ import annotations

from .framework import Ctx, walkthrough
from .steps import (
    load_example_spec,
    open_provenance,
    show_every_version,
    canvas_graph,
    await_canvas_nodes,
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
    title="Loaded dataflows get a real provenance graph",
    premise="Open a saved dataflow, then read its version history.",
    note="loadParsedTrill now snapshots each version from the arrays it was handed, "
        "not from the React Flow store, which is one commit stale inside its own "
        "synchronous load loop.",
    tests=["src/tests/hook/useWorkflowOperations.loadProvenance.test.ts",
           "test_frontend/test_walkthrough_baselines.py"],
    clip_selector='[data-curio-modal-shell="true"]',
    fit_reactflow=False,
)
def provenance_graph_of_a_loaded_dataflow(ctx: Ctx) -> None:
    spec = load_example_spec(PROVENANCE_EXAMPLE)["dataflow"]
    node_count, edge_count = len(spec["nodes"]), len(spec["edges"])

    ctx.say("An example dataflow, opened from the gallery",
            "Every node and edge came from the saved spec.")
    dialog = open_provenance(ctx)

    versions = dialog.locator(".react-flow__node")
    assert versions.count() == 1 + node_count + edge_count, (
        f"the graph has {versions.count()} versions; one per loaded node and "
        f"edge plus the initial one would be {1 + node_count + edge_count}"
    )

    ctx.say("One version per node, then one per connection",
            "The window opens on the newest.")

    # The load-bearing check. DataflowThumbnail draws one <line> per edge and two
    # <rect> per node, and SKIPS any edge whose endpoints are missing from the
    # same preview -- so a version captured from the stale React Flow store (one
    # node, no edges) renders a background rect and nothing else. That is what
    # made the boxes read as blank and isolated.
    marks = versions.last.evaluate(
        "el => { const svg = el.querySelector('svg');"
        " return svg ? { lines: svg.querySelectorAll('line').length,"
        " rects: svg.querySelectorAll('rect').length } : null; }"
    )
    assert marks, "the newest provenance version rendered no thumbnail at all"
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
    ctx.focus(versions.last, hold=1600)


@walkthrough(
    slug="provenance-graph-navigation",
    example=PROVENANCE_EXAMPLE,
    refs=[187],
    title="The provenance graph pans and zooms",
    premise="Drag the version graph to reach a node below the fold.",
    note="ModalShell puts React Flow's own `nopan`/`nowheel` classes on the dialog, "
        "and React Flow matches them by ancestor. The inner graph now names "
        "opt-out classes nothing inside it carries.",
    tests=["src/tests/components/trillProvenanceWindowPan.test.tsx",
           "test_frontend/test_walkthrough_baselines.py"],
    clip_selector='[data-curio-modal-shell="true"]',
    fit_reactflow=False,
)
def provenance_graph_navigation(ctx: Ctx) -> None:
    page = ctx.page
    dialog = open_provenance(ctx)

    graph = dialog.locator(".react-flow__pane").first
    box = graph.bounding_box()
    assert box, "the provenance graph has no layout box"
    before = _viewport_transform(page)

    ctx.say("Drag the graph", "Reach the versions below the fold.")
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.mouse.down()
    for step in range(1, 13):
        page.mouse.move(
            box["x"] + box["width"] / 2 - step * 9,
            box["y"] + box["height"] / 2 - step * 11,
        )
        ctx.beat(40)
    page.mouse.up()
    ctx.beat(700)

    assert _viewport_transform(page) != before, (
        "the drag did not move the graph at all - the modal's own `nopan` class "
        "is an ancestor of the canvas, and React Flow matches it by ancestor, so "
        "every pan and wheel-zoom inside the dialog is refused"
    )
    ctx.say("The graph pans", "Versions past the fold are reachable.")


@walkthrough(
    slug="provenance-reverting-to-a-previous-version",
    example=PROVENANCE_EXAMPLE,
    refs=[195],
    title="Reverting a dataflow to an earlier version",
    premise="Step back through the version graph and watch the canvas follow.",
    note="onConnect resolved its target with `nodes.find(...) as Node` and never "
         "checked it, so reverting to a version whose edges named nodes it does "
         "not hold tore the canvas down. Such an edge is now dropped instead.",
    tests=["src/tests/providers/onConnectMissingEndpoint.test.tsx",
           "test_frontend/test_walkthrough_baselines.py"],
)
def provenance_reverting_to_a_previous_version(ctx: Ctx) -> None:
    page = ctx.page
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))

    saved = canvas_graph(page)
    ctx.say("The dataflow as saved",
            f"{saved['nodes']} nodes, {saved['edges']} connections.")

    dialog = open_provenance(ctx)
    versions = dialog.locator(".react-flow__node")
    count = versions.count()
    assert count > 1, f"the provenance graph offers {count} versions to revert to"

    # Newest-first, skipping the one already on the canvas, so the dataflow
    # visibly unwinds. Four is the floor: a single hop would not show that the
    # history is walkable, only that one click works.
    targets = list(range(count - 2, -1, -1))
    assert len(targets) >= 4, (
        f"only {len(targets)} earlier versions available; this walkthrough steps "
        f"back through at least four"
    )

    ctx.say("Revert by clicking a version",
            "The canvas becomes exactly what that version holds.")

    def capture_canvas(label: str, *, nodes: int, reopen: bool = True) -> None:
        # The modal covers the canvas each frame is about, so close it for the
        # shot and open it again for the next click. The chosen version stays
        # selected when it reopens. The first version is empty, and an empty
        # canvas has nothing to fit.
        ctx.click(page.get_by_role("button", name="Close").last)
        dialog.wait_for(state="hidden", timeout=20000)
        ctx.capture(label, fit_reactflow=nodes > 0)
        if reopen:
            open_provenance(ctx)

    for index in targets:
        show_every_version(ctx, dialog)
        version = versions.nth(index)
        expected = version_graph(version)
        ctx.click(version, hold=520)
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
        capture_canvas(f"reverted-to-v{index + 1:02d}", nodes=expected["nodes"])

    ctx.say(f"Stepped back through {len(targets)} versions",
            "Each one put its own graph on the canvas.")

    # Forward to the newest, so the canvas ends where it started.
    show_every_version(ctx, dialog)
    ctx.click(versions.nth(count - 1), hold=520)
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


def _viewport_transform(page) -> str:
    return page.evaluate(
        "() => { const el = document.querySelector("
        "'[data-curio-modal-shell=\"true\"] .react-flow__viewport');"
        " return el ? getComputedStyle(el).transform : ''; }"
    )
