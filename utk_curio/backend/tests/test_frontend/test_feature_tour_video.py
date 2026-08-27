"""Record a narrated screencast of Curio's features in the e2e Chromium.

This is not a regression test. It reuses the e2e harness because that harness
already knows how to boot the whole stack (``curio_servers``), how to launch the
browser the AUTK/WebGPU nodes need (``browser_type_launch_args`` points at the
system Chrome), and how to drive the canvas without fighting React Flow. What it
produces is a video, not an assertion.

It is skipped unless ``CURIO_TOUR=1``, so a normal ``pytest test_frontend/`` run
never spends ten minutes recording.

Run::

    # from utk_curio/backend, with PYTHONPATH=<repo root>
    CURIO_TOUR=1 pytest tests/test_frontend/test_feature_tour_video.py -s --headed

Environment:

===========================  ==================================================
``CURIO_TOUR=1``             required; otherwise the module skips
``CURIO_TOUR_SCENES``        comma-separated scene ids to record (default: all)
``CURIO_TOUR_OUT``           output directory (default ``.curio/tour/``)
``CURIO_TOUR_SPEED``         pacing multiplier, >1 is faster (default 1.0)
===========================  ==================================================

Scene ids, in order: see ``SCENES`` at the bottom of this file.

A scene that raises is reported and the tour carries on to the next one, so a
single broken step still yields a usable video. The test then fails at the end
with the list of scenes that broke - the recording is a deliverable either way,
but a silently truncated tour is not.
"""
from __future__ import annotations

import os
import re
import sys
import traceback
from dataclasses import dataclass, field
from typing import Callable

import pytest
from playwright.sync_api import expect

from .tour import REPO_ROOT, VIDEO_SIZE, Tour, finalize_video, out_dir, speed
from .utils import (
    activate_header_icon,
    canvas_nodes,
    connect_nodes,
    drag_to_canvas,
    node_locator,
    open_tools_palette,
    run_node_and_wait,
    set_node_code,
    stub_db_login,
    wait_for_projects_page,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("CURIO_TOUR") != "1",
    reason="feature-tour recording only runs with CURIO_TOUR=1",
)

# ---------------------------------------------------------------------------
# Fixtures for the tour: content the scenes lean on
# ---------------------------------------------------------------------------

USER_NAME = "Ada Urbanist"
USER_LOGIN = "ada_urbanist"
USER_PASSWORD = "curio-tour-2026"

# The CSV hub dataset the authoring e2e tests use: three rows, two numeric
# columns, and a generated loader that only needs pandas - so the "run it" beat
# is a couple of seconds rather than a geopandas import.
DATASET_ID = "data.urbanlab.acs-neighborhood-profile"
DATASET_TITLE = "ACS Neighborhood Profile"

# The only package a tour may install: it declares no python dependencies, so
# nothing shells out to pip mid-recording.
PKG_DIR = "curio.example-ui@1"
PKG_NAME = "Example: Custom UI Node"

DRAWER_DATA = '[data-curio-dataset-catalog-drawer="true"]'
DRAWER_NODES = '[data-curio-node-catalog-drawer="true"]'
CARD = 'article:not([role="status"])'

TRANSFORM_TILE = "#step-transformation"
LOADER_TYPE = "curio.builtin/data-loading"
TRANSFORM_TYPE = "curio.builtin/data-transformation"

POS_LOADER = (150, 150)
POS_TRANSFORM = (760, 150)

TRANSFORM_CODE = (
    "df = arg\n"
    'df["income_per_capita"] = (df["median_income"] / df["population"]).round(2)\n'
    'print(df.sort_values("median_income", ascending=False).to_string(index=False))\n'
    "return df\n"
)

EXAMPLE_LINKED = os.path.join(
    REPO_ROOT, "docs", "examples", "03-vega-lite-linked-temporal-charts.json",
)
EXAMPLE_INTERACTION = os.path.join(
    REPO_ROOT, "docs", "examples", "dataflows", "Interaction_Vega_Simple.json",
)
EXAMPLE_AUTARK = os.path.join(
    REPO_ROOT, "docs", "examples", "11-autark-pbf-loading.json",
)


def _log(message: str) -> None:
    """Print without letting the console's codec fail the run.

    The menu labels carry ``⏷``, so a Playwright timeout message quoting one
    lands in a traceback that a cp1252 stdout cannot encode - and the resulting
    UnicodeEncodeError would replace the real failure.
    """
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    # flush: a tour run is long, and redirected stdout would otherwise hold the
    # scene log until the process exits.
    print(
        message.encode(encoding, "replace").decode(encoding, "replace"),
        flush=True,
    )


@dataclass
class Ctx:
    """Everything a scene needs, threaded through the scene registry."""

    page: object
    tour: Tour
    frontend: str
    backend: str
    state: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Shared beats
# ---------------------------------------------------------------------------


def _fit_view(page, padding: float = 0.22) -> None:
    """Frame the whole graph, the same way the screenshot helper does."""
    page.evaluate(
        """(padding) => {
            const fit = window.__curio_fitViewWithMenuOffset;
            if (typeof fit === 'function') {
                fit({ padding, duration: 600, includeHiddenNodes: true });
            }
        }""",
        padding,
    )
    page.wait_for_timeout(900)


def _reset_zoom(page) -> None:
    """Put the pane back to zoom 1 before dropping nodes.

    ``drag_to_canvas`` positions drops in screen pixels, so the canvas-space gap
    between two drops depends on the current zoom. The node geometry the offsets
    were chosen for (525x350, ~610px apart) only holds at zoom 1.
    """
    page.evaluate(
        """() => {
            const rf = window.__curio_reactFlow;
            if (!rf) return;
            const vp = rf.getViewport();
            if (Math.abs(vp.zoom - 1) < 0.01) return;
            rf.setViewport({ x: vp.x, y: vp.y, zoom: 1 }, { duration: 300 });
        }"""
    )
    page.wait_for_timeout(400)


def _menu(page, label: str):
    """Top-bar dropdown trigger (``File ⏷``, ``View ⏷``, ...)."""
    return page.get_by_role("button", name=f"{label} ⏷", exact=True)


def _load_example(ctx: Ctx, path: str, *, expected_nodes: int) -> None:
    """File > Load dataflow, on camera.

    Deliberately not ``utils.upload_workflow``: that helper hides the left tool
    rail so it cannot drift into a screenshot baseline, which is exactly the
    chrome a viewer needs to see here.
    """
    page, tour = ctx.page, ctx.tour
    tour.click(_menu(page, "File"), force=True)
    load = page.get_by_role("button", name="Load dataflow", exact=True)
    load.wait_for(state="visible", timeout=15000)
    tour.focus(load, hold=500)
    with page.expect_file_chooser() as chooser:
        page.get_by_text("Load dataflow").click()
    chooser.value.set_files(path)
    page.wait_for_function(
        "(n) => document.querySelectorAll('.react-flow__node').length >= n",
        arg=expected_nodes,
        timeout=90000,
    )
    tour.beat(900)
    _fit_view(page)


def _new_dataflow_from_menu(ctx: Ctx) -> None:
    """File > New dataflow, accepting the unsaved-changes guard."""
    page, tour = ctx.page, ctx.tour
    tour.click(_menu(page, "File"), force=True)
    tour.click(page.get_by_role("button", name="New dataflow", exact=True))
    page.wait_for_url("**/dataflow/new", timeout=20000)
    page.wait_for_timeout(1200)


def _play_all(ctx: Ctx, *, timeout_ms: int = 240000) -> None:
    """Press the rail's Run-all button and wait for every node to settle."""
    page, tour = ctx.page, ctx.tour
    button = page.locator('#tools-menu button[title="Run all nodes"]')
    tour.click(button, force=True, hold=400)
    page.wait_for_function(
        """() => {
            const nodes = [...document.querySelectorAll('.react-flow__node')];
            if (!nodes.length) return false;
            return nodes.every((n) => {
                const el = n.querySelector('[data-curio-node-status]');
                if (!el) return false;
                const s = el.getAttribute('data-curio-node-status');
                return s === 'done' || s === 'error';
            });
        }""",
        timeout=timeout_ms,
    )
    page.wait_for_timeout(1500)


def _node_ids_by_type(page, node_type: str) -> list[str]:
    fragment = node_type.rsplit("/", 1)[-1]
    return [
        n["id"] for n in canvas_nodes(page)
        if fragment in (n["nodeType"] or "")
    ]


def _center_on(page, node_id: str, *, zoom: float = 0.9) -> None:
    """Pan the canvas so one node fills the frame."""
    page.evaluate(
        """({ nodeId, zoom }) => {
            const rf = window.__curio_reactFlow;
            if (!rf) return;
            const node = rf.getNodes().find((n) => n.id === nodeId);
            if (!node) return;
            const w = node.width || node.measured?.width || 525;
            const h = node.height || node.measured?.height || 350;
            rf.setCenter(node.position.x + w / 2, node.position.y + h / 2, {
                zoom, duration: 700,
            });
        }""",
        {"nodeId": node_id, "zoom": zoom},
    )
    page.wait_for_timeout(1000)


_PALETTE_TRIGGERS = {
    "datasets": ("#datasets-palette", "Close dataset palette"),
    "packages": ("#packages-palette", "Close node package palette"),
}


def _close_tools_palette(page, kind: str) -> None:
    """Collapse a left-rail palette so it stops covering the canvas.

    The palettes open into a strip over the pane, which is right for authoring
    and wrong for filming the graph that authoring just produced.
    """
    root, title = _PALETTE_TRIGGERS[kind]
    trigger = page.locator(f'{root} button[title="{title}"]')
    if trigger.count():
        trigger.first.click(force=True)
        page.wait_for_timeout(400)


def _close_data_drawer(page) -> None:
    page.locator(DRAWER_DATA).locator("header").get_by_role(
        "button", name="Close Data Catalog drawer"
    ).click()
    expect(page.locator(DRAWER_DATA)).to_have_count(0, timeout=8000)


# ---------------------------------------------------------------------------
# Scenes
# ---------------------------------------------------------------------------


def scene_intro(ctx: Ctx) -> None:
    page, tour = ctx.page, ctx.tour
    page.goto(f"{ctx.frontend}/auth/signin")
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(1200)
    tour.chapter(
        "urban toolkit",
        "Curio",
        "A dataflow framework for collaborative urban visual analytics: "
        "code, grammars and GUI in one provenance-aware canvas.",
        hold=4200,
    )
    tour.say(
        "Everything in this tour runs locally",
        "Backend, sandbox and frontend, driven through a real browser.",
        hold=2600,
    )
    tour.hush()


def scene_signup(ctx: Ctx) -> None:
    page, tour = ctx.page, ctx.tour
    tour.chapter("01", "Accounts and projects", "Sign up, then organise your work.")
    page.goto(f"{ctx.frontend}/auth/signup")
    page.wait_for_load_state("domcontentloaded")
    page.get_by_text("Create an account").wait_for(timeout=30000)
    tour.say(
        "Curio is multi-user",
        "Every dataflow, dataset and installed package is scoped to an account.",
        hold=2400,
    )
    tour.type_into(page.get_by_label("Name", exact=True), USER_NAME)
    tour.type_into(page.get_by_label("Username"), USER_LOGIN)
    tour.type_into(page.get_by_label("Password", exact=True), USER_PASSWORD, delay=35)
    tour.type_into(page.get_by_label("Confirm Password"), USER_PASSWORD, delay=35)
    tour.hush()
    tour.click(page.get_by_role("button", name="Create account"))
    page.wait_for_url("**/projects", timeout=40000)
    wait_for_projects_page(page, timeout=15000)
    tour.beat(1200)


def scene_projects(ctx: Ctx) -> None:
    page, tour = ctx.page, ctx.tour
    tour.say(
        "The projects workspace",
        "Dataflows as cards, with search, filters and a grid or list view.",
        hold=2600,
    )
    tour.focus(page.get_by_placeholder("Search projects…"), hold=900)
    tour.focus(page.get_by_role("button", name="List", exact=True), hold=500)
    tour.click(page.get_by_role("button", name="List", exact=True))
    tour.click(page.get_by_role("button", name="Grid", exact=True))
    tour.say(
        "Bring a notebook with you",
        "Import a Jupyter notebook and Curio converts its cells into a dataflow.",
        hold=2400,
    )
    tour.focus(page.get_by_role("button", name="Import Jupyter notebook"), hold=1200)
    tour.say(
        "Per-user LLM configuration",
        "Point Curio at OpenAI, Anthropic, Gemini or your own endpoint.",
        hold=2200,
    )
    tour.click(page.get_by_role("button", name="AI Settings"))
    tour.beat(2200)
    page.keyboard.press("Escape")
    tour.beat(600)
    close = page.get_by_role("button", name=re.compile("^(Close|Cancel)$"))
    if close.count():
        try:
            close.first.click(timeout=3000)
        except Exception:
            pass
    tour.hush()


def scene_canvas(ctx: Ctx) -> None:
    page, tour = ctx.page, ctx.tour
    tour.chapter("02", "The dataflow canvas", "Where analysis is authored.")
    tour.click(page.get_by_role("button", name="+ New Dataflow"))
    page.wait_for_url("**/dataflow/**", timeout=20000)
    page.wait_for_timeout(2000)
    tour.say(
        "One canvas, several abstraction levels",
        "Python and JavaScript code, declarative grammars, and GUI widgets.",
        hold=2600,
    )
    tour.focus(page.locator("#tools-menu"), hold=1600)
    tour.say(
        "The built-in node rail",
        "Loading, transformation, computation, pooling, maps, charts, merging.",
        hold=2600,
    )
    for tile, label in (
        ("#step-loading", "Data Loading"),
        ("#step-analysis", "Python Computation"),
        ("#step-transformation", "Data Transformation"),
        ("#step-pool", "Data Pool"),
        ("#step-utk", "Autark: 2D and 3D maps, GPU compute"),
        ("#step-vega", "Vega-Lite charts"),
        ("#step-merge", "Merge Flow"),
    ):
        locator = page.locator(tile)
        if not locator.count():
            continue
        tour.say(label, hold=200)
        tour.focus(locator, hold=800)
    tour.hush()
    tour.say(
        "Menus for the rest",
        "File, View, Data catalogs, Provenance, and a built-in tutorial.",
        hold=2200,
    )
    for label in ("File", "View", "Data", "Provenance"):
        trigger = _menu(page, label)
        tour.click(trigger, force=True, hold=1100)
        page.keyboard.press("Escape")
        tour.click(trigger, force=True, hold=200)
    tour.hush()


def scene_data_catalog(ctx: Ctx) -> None:
    page, tour = ctx.page, ctx.tour
    tour.chapter(
        "03", "The Data Catalog",
        "Datasets are first-class: browse, add, import your own, publish.",
    )
    palette = open_tools_palette(page, "datasets")
    tour.say(
        "Every dataflow carries its datasets",
        "The rail lists what this dataflow can load; the catalog is the library.",
        hold=2600,
    )
    browse = palette.get_by_role("button", name="Browse Data Catalog +")
    tour.click(browse, force=True)

    root = page.locator(DRAWER_DATA)
    root.wait_for(state="attached", timeout=15000)
    expect(root).to_have_attribute("aria-hidden", "false", timeout=10000)
    drawer = page.get_by_role("dialog").filter(
        has=page.get_by_role("heading", name="Data Catalog", exact=True)
    )
    expect(drawer).to_be_visible(timeout=10000)
    tour.say(
        "CSV, GeoJSON, Parquet, GeoTIFF, Shapefile, OSM PBF",
        "Published datasets, your imports, and outputs computed by other nodes.",
        hold=3000,
    )

    card = drawer.locator(f'{CARD}[data-dataset-id="{DATASET_ID}"]')
    expect(card).to_have_count(1, timeout=20000)
    tour.focus(card, hold=1400)
    tour.hush()
    add = card.get_by_role("button", name="Add to dataflow", exact=True)
    with page.expect_response(
        lambda r: "/datasets/install" in r.url
        and r.request.method == "POST" and r.ok,
        timeout=60000,
    ):
        tour.click(add)
    expect(
        drawer.locator(f'{CARD}[data-dataset-id="{DATASET_ID}"]').get_by_role(
            "button", name="Remove from dataflow", exact=True
        )
    ).to_be_visible(timeout=25000)
    tour.say(
        "Added to this dataflow",
        "Installed into the account's store and pinned to the dataflow spec.",
        hold=2400,
    )
    tour.hush()
    _close_data_drawer(page)
    row = page.locator(f'#datasets-palette [data-dataset-id="{DATASET_ID}"]')
    expect(row).to_have_count(1, timeout=20000)
    tour.focus(row, hold=1200)
    ctx.state["dataset_row"] = row


def scene_build(ctx: Ctx) -> None:
    page, tour = ctx.page, ctx.tour
    tour.chapter("04", "Authoring a dataflow", "Drag, wire, write, run.")

    row = ctx.state.get("dataset_row")
    if row is None:
        row = open_tools_palette(page, "datasets").locator(
            f'[data-dataset-id="{DATASET_ID}"]'
        )
    tour.say(
        "Drag a dataset onto the canvas",
        "Curio writes the loader for you, in the right format for the file.",
        hold=2600,
    )
    tour.focus(row, hold=700)
    _reset_zoom(page)
    pane = page.locator(".curio-canvas-drop-target").bounding_box()
    if pane:
        tour.point_at(pane["x"] + POS_LOADER[0] + 240, pane["y"] + POS_LOADER[1] + 40)
    loader_id = drag_to_canvas(page, row, at=POS_LOADER)
    tour.beat(1400)
    tour.hush()
    # The palette strip sits over the pane; from here on the graph is the point.
    # No fitView here, deliberately: fitting a single node zooms the pane right
    # in, and the next drop - whose offset is in screen pixels - then lands on
    # top of this node instead of 610px to its right, which makes connect_nodes
    # fail with the output handle covered by the other node's editor.
    _close_tools_palette(page, "datasets")

    tour.say(
        "A Data Loading node, already coded",
        "pandas.read_csv against the installed copy, returning a DataFrame.",
        hold=3000,
    )
    tour.say(
        "Now a transformation to consume it",
        "Built-in node types drag off the same rail.",
        hold=2200,
    )
    _reset_zoom(page)
    transform_id = drag_to_canvas(page, page.locator(TRANSFORM_TILE), at=POS_TRANSFORM)
    tour.beat(900)
    _fit_view(page)

    tour.say(
        "Connect them",
        "The upstream result arrives in the next node as `arg`.",
        hold=2000,
    )
    connect_nodes(page, loader_id, transform_id)
    tour.beat(1200)
    tour.hush()

    tour.say(
        "Write the analysis",
        "Each code node is a Monaco editor running in a sandboxed process.",
        hold=2400,
    )
    _center_on(page, transform_id, zoom=0.95)
    set_node_code(page, transform_id, TRANSFORM_CODE)
    tour.beat(1600)

    tour.say("Run the loader", "", hold=1200)
    _center_on(page, loader_id, zoom=0.9)
    tour.hush()
    play = node_locator(page, loader_id).locator("svg.fa-circle-play")
    tour.focus(play, hold=400)
    run_node_and_wait(page, loader_id, node_type=LOADER_TYPE)
    tour.beat(1500)

    tour.say(
        "Play a node and its ancestors run first",
        "Results are cached as DuckDB artifacts and passed down the edges.",
        hold=2600,
    )
    _center_on(page, transform_id, zoom=0.9)
    tour.hush()
    output = run_node_and_wait(page, transform_id, node_type=TRANSFORM_TYPE)
    tour.beat(2400)
    _log(f"[tour] transformation output: {output[:200]}")
    _fit_view(page)
    ctx.state["loader_id"] = loader_id
    ctx.state["transform_id"] = transform_id

    tour.say(
        "Save it",
        "Auto-save, an unsaved-changes guard, and a save-status indicator.",
        hold=2200,
    )
    tour.click(_menu(page, "File"), force=True)
    save = page.get_by_role("button", name="Save dataflow", exact=True)
    save.wait_for(state="visible", timeout=10000)
    with page.expect_response(
        lambda r: "/api/projects" in r.url
        and r.request.method in ("POST", "PUT") and r.ok,
        timeout=40000,
    ):
        tour.click(save)
    save.wait_for(state="hidden", timeout=30000)
    tour.hush()


def scene_lineage(ctx: Ctx) -> None:
    page, tour = ctx.page, ctx.tour
    tour.chapter(
        "05", "Dataset lineage",
        "Outputs become inputs, and Curio remembers who made what.",
    )
    tour.click(_menu(page, "Data"), force=True)
    tour.click(page.get_by_role("button", name="Data Catalog", exact=True))
    root = page.locator(DRAWER_DATA)
    root.wait_for(state="attached", timeout=15000)
    expect(root).to_have_attribute("aria-hidden", "false", timeout=10000)
    drawer = page.get_by_role("dialog").filter(
        has=page.get_by_role("heading", name="Data Catalog", exact=True)
    )
    card = drawer.locator(f'{CARD}[data-dataset-id="{DATASET_ID}"]')
    expect(card).to_have_count(1, timeout=20000)
    tour.click(card.locator(f'button[aria-label^="View {DATASET_TITLE} ("]'))

    tabs = page.get_by_role("navigation", name="Dataset detail sections")
    expect(tabs).to_be_visible(timeout=20000)
    tour.say(
        "Every dataset has a detail panel",
        "Schema, preview, provenance and downstream usage.",
        hold=2600,
    )
    tour.click(tabs.get_by_role("button", name="Lineage", exact=True))
    center = page.locator('section[aria-label="Dataset content"]')
    expect(
        center.get_by_role("heading", name=re.compile(r"^Dataflows"))
    ).to_be_visible(timeout=15000)
    tour.say(
        "Consumed by the node we just wired",
        "The graph is read back from the saved dataflow, not hand-maintained.",
        hold=3200,
    )
    tour.hush()
    tour.beat(1200)
    page.locator('button[aria-label="Close"]:not([data-dismiss="toast"])').click()
    expect(tabs).to_have_count(0, timeout=10000)
    _close_data_drawer(page)


def scene_node_catalog(ctx: Ctx) -> None:
    page, tour = ctx.page, ctx.tour
    tour.chapter(
        "06", "The Node Catalog",
        "Every node lives in a versioned, shareable package.",
    )
    palette = open_tools_palette(page, "packages")
    tour.click(
        palette.get_by_role("button", name=re.compile(r"^Browse Node Catalog")),
        force=True,
    )
    drawer = page.get_by_role("dialog").filter(
        has=page.get_by_role("heading", name="Node Catalog", exact=True)
    )
    expect(drawer).to_be_visible(timeout=15000)
    tour.say(
        "Built-ins, community packages, and your own",
        "Mix them freely in one dataflow; a lockfile pins the exact set.",
        hold=3000,
    )
    search = drawer.get_by_placeholder("Search packages, publishers, tags…")
    tour.type_into(search, "example", delay=90)
    tour.beat(1200)

    card = drawer.locator(f'article[data-pkg-dir="{PKG_DIR}"]')
    expect(card).to_have_count(1, timeout=15000)
    tour.focus(card, hold=1500)
    tour.say("Add it to the dataflow", "", hold=1000)
    tour.hush()
    with page.expect_response(
        lambda r: r.url.endswith("/api/packages/resolve"), timeout=40000
    ):
        card.get_by_role("button", name="Add to dataflow", exact=True).click()
    dialog = page.get_by_role("dialog").filter(
        has=page.get_by_role("heading", name=f'Add "{PKG_NAME}"', exact=True)
    )
    expect(dialog).to_be_visible(timeout=15000)
    tour.say(
        "Dependencies are resolved before anything is installed",
        "Python and JS requirements are read from the package manifest.",
        hold=2800,
    )
    confirm = dialog.get_by_role("button", name="Add to dataflow", exact=True)
    tour.hush()
    with page.expect_response(
        lambda r: "/api/packages/projects/" in r.url
        and r.url.endswith("/install")
        and r.request.method == "POST" and r.ok,
        timeout=60000,
    ):
        tour.click(confirm)
    expect(dialog).to_have_count(0, timeout=40000)
    expect(
        card.get_by_role("button", name="Remove from dataflow", exact=True)
    ).to_be_visible(timeout=25000)
    tour.say("Installed", "No reload: the palette re-renders in place.", hold=2000)
    tour.hush()
    drawer.locator("header").get_by_role(
        "button", name="Close Node Catalog drawer"
    ).click()
    expect(page.locator(DRAWER_NODES)).to_have_count(0, timeout=8000)
    new_row = page.locator(f'#packages-palette [data-pkg-palette-coords~="{PKG_DIR}"]')
    expect(new_row).to_have_count(1, timeout=25000)
    tour.focus(new_row, hold=2000)
    tour.say(
        "Its nodes are now draggable",
        "Authoring your own works the same way: Save as package node.",
        hold=2600,
    )
    tour.hush()
    _close_tools_palette(page, "packages")


def scene_libraries(ctx: Ctx) -> None:
    page, tour = ctx.page, ctx.tour
    tour.say(
        "Python libraries, managed from the canvas",
        "Curio detects imports a dataflow needs and installs them per account.",
        hold=2600,
    )
    tour.click(_menu(page, "Data"), force=True)
    tour.click(page.get_by_role("button", name="Installed libraries", exact=True))
    expect(
        page.get_by_role("heading", name="Installed libraries")
    ).to_be_visible(timeout=20000)
    tour.beat(2600)
    tour.hush()
    page.get_by_role("button", name="Close", exact=True).first.click()
    expect(
        page.get_by_role("heading", name="Installed libraries")
    ).to_have_count(0, timeout=10000)


def scene_linked_views(ctx: Ctx) -> None:
    page, tour = ctx.page, ctx.tour
    tour.chapter(
        "07", "Visualization",
        "Vega-Lite views driven by real urban data, run end to end.",
    )
    _new_dataflow_from_menu(ctx)
    tour.say(
        "Load a published example",
        "Chicago speed-camera violations: load, aggregate, two linked views.",
        hold=2600,
    )
    _load_example(ctx, EXAMPLE_LINKED, expected_nodes=4)
    tour.say(
        "Play All runs the graph in topological order",
        "400k rows are trimmed at load, aggregated, then handed to both charts.",
        hold=3000,
    )
    tour.hush()
    _play_all(ctx)
    tour.say(
        "Two views from one computation",
        "A bar chart per camera and a total-by-year line, fed by the same node.",
        hold=3200,
    )
    tour.hush()
    _fit_view(page, padding=0.12)
    tour.beat(2000)
    ctx.state["vega_ids"] = _node_ids_by_type(page, "vis-vega")


def scene_dashboard(ctx: Ctx) -> None:
    page, tour = ctx.page, ctx.tour
    tour.say(
        "Pin the views you want to present",
        "Dashboard Mode keeps node state, edges and positions intact.",
        hold=2600,
    )
    for node_id in (ctx.state.get("vega_ids") or _node_ids_by_type(page, "vis-vega"))[:2]:
        # The header icons are FontAwesome svgs with role="button" and no
        # accessible name (the `title` prop does not survive into the DOM here),
        # so the icon class is the only stable handle: faCircle when unpinned,
        # faCircleDot once pinned. They activate on pointerdown/up so that
        # press-and-drag still moves the node, which is what
        # activate_header_icon sends.
        pin = node_locator(page, node_id).locator(
            'svg[role="button"].fa-circle, svg[role="button"].fa-circle-dot'
        ).first
        if not pin.count():
            _log(f"[tour] no dashboard pin control on {node_id}")
            continue
        tour.focus(pin, hold=450)
        activate_header_icon(pin)
        tour.beat(700)
    tour.hush()
    tour.click(_menu(page, "View"), force=True)
    tour.click(page.get_by_role("button", name="Dashboard Mode", exact=True))
    tour.beat(3200)
    tour.say(
        "The same dataflow, presented",
        "Toggle back and the canvas is exactly where you left it.",
        hold=2600,
    )
    tour.hush()
    exit_btn = page.locator('button[title="Exit Dashboard Mode"]')
    tour.click(exit_btn)
    tour.beat(1200)
    _fit_view(page)


def scene_provenance(ctx: Ctx) -> None:
    page, tour = ctx.page, ctx.tour
    tour.chapter(
        "08", "Provenance",
        "Curio tracks how a dataflow got to be the way it is.",
    )
    tour.click(_menu(page, "Provenance"), force=True)
    tour.click(page.get_by_role("button", name="Provenance", exact=True))
    tour.beat(1500)
    tour.say(
        "Versions of the dataflow, as a graph",
        "Tracked in the dataflow itself, so it travels with the file.",
        hold=3200,
    )
    tour.hush()
    page.keyboard.press("Escape")
    tour.beat(900)
    for label in ("Close", "close"):
        button = page.get_by_role("button", name=label, exact=True)
        if button.count():
            try:
                button.first.click(timeout=2500)
                break
            except Exception:
                pass


def scene_interaction(ctx: Ctx) -> None:
    page, tour = ctx.page, ctx.tour
    tour.chapter(
        "09", "Linked interactions",
        "A selection in one view is data the rest of the graph can read.",
    )
    _new_dataflow_from_menu(ctx)
    _load_example(ctx, EXAMPLE_INTERACTION, expected_nodes=3)
    tour.say(
        "Loader, Data Pool, Vega-Lite view",
        "The pool fans one result out and collects interaction state back.",
        hold=2800,
    )
    tour.hush()
    _play_all(ctx)

    vega_ids = _node_ids_by_type(page, "vis-vega")
    if not vega_ids:
        return
    _center_on(page, vega_ids[0], zoom=1.0)
    tour.say(
        "Hovering a bar writes back into the data",
        "The interaction becomes a column every downstream node can use.",
        hold=2800,
    )
    # Sweep the pointer across the plot rather than clicking marks: the Vega
    # view is one canvas, so every mark shares its bounding box and hovering
    # "each mark" would hover the same pixel five times. Walking x across the
    # plotting area is what actually fires pointerover on successive bars.
    plot = node_locator(page, vega_ids[0]).locator("canvas, svg").first
    box = plot.bounding_box()
    if box:
        y = box["y"] + box["height"] * 0.7
        left = box["x"] + box["width"] * 0.22
        right = box["x"] + box["width"] * 0.88
        for index in range(5):
            x = left + (right - left) * index / 4
            tour.point_at(x, y, hold=200)
            page.mouse.move(x, y)
            tour.beat(1100)
    tour.beat(1500)
    tour.hush()


def scene_autark(ctx: Ctx) -> None:
    page, tour = ctx.page, ctx.tour
    tour.chapter(
        "10", "Autark: maps and GPU compute",
        "One declarative UrbanSpec for data loading, WGSL compute and rendering.",
    )
    _new_dataflow_from_menu(ctx)
    _load_example(ctx, EXAMPLE_AUTARK, expected_nodes=2)
    tour.say(
        "An OSM extract, parsed in the browser",
        "DuckDB-WASM reads a local .pbf; no tile server, no Overpass call.",
        hold=3000,
    )
    tour.hush()
    _play_all(ctx)
    tour.say(
        "Rendered with WebGPU",
        "Lower Manhattan: buildings, roads and water as separate layers.",
        hold=3000,
    )
    tour.hush()
    ids = _node_ids_by_type(page, "autk-grammar")
    if ids:
        # Frame the rendering node: at fitView zoom the map is a thumbnail
        # inside a 525x350 node, which is not what this chapter is about.
        _center_on(page, ids[-1], zoom=1.25)
        tour.beat(5000)


def scene_catalog_pages(ctx: Ctx) -> None:
    page, tour = ctx.page, ctx.tour
    tour.chapter(
        "11", "Catalogs as pages",
        "The same catalogs, browsable outside any single dataflow.",
    )
    page.goto(f"{ctx.frontend}/catalog/nodes")
    page.wait_for_load_state("domcontentloaded")
    tour.beat(2600)
    tour.say(
        "Every package on this deployment",
        "Descriptions, licenses, READMEs, permissions and versions.",
        hold=2800,
    )
    tour.scroll(700, steps=7)
    tour.hush()
    page.goto(f"{ctx.frontend}/catalog/data")
    page.wait_for_load_state("domcontentloaded")
    tour.beat(2200)
    tour.say(
        "And every dataset",
        "Publish your own so the whole deployment can build on it.",
        hold=2800,
    )
    tour.scroll(700, steps=7)
    tour.hush()


def scene_outro(ctx: Ctx) -> None:
    page, tour = ctx.page, ctx.tour
    page.goto(f"{ctx.frontend}/projects")
    page.wait_for_load_state("domcontentloaded")
    wait_for_projects_page(page, timeout=20000)
    tour.beat(1800)
    tour.say(
        "Reproducible and shareable",
        "Dataflows fork, export as .curio.zip or a notebook, and share by URL.",
        hold=3000,
    )
    tour.hush()
    tour.chapter(
        "urbantk.org/curio",
        "Curio",
        "Docs, examples and hosted instances at curio.urbantk.org.",
        hold=4200,
    )
    page.evaluate("() => window.__curioTour && window.__curioTour.clearAll()")
    tour.beat(800)


#: Ordered scene registry. Ids are what ``CURIO_TOUR_SCENES`` selects.
SCENES: list[tuple[str, Callable[[Ctx], None]]] = [
    ("intro", scene_intro),
    ("signup", scene_signup),
    ("projects", scene_projects),
    ("canvas", scene_canvas),
    ("datacatalog", scene_data_catalog),
    ("build", scene_build),
    ("lineage", scene_lineage),
    ("nodecatalog", scene_node_catalog),
    ("libraries", scene_libraries),
    ("linkedviews", scene_linked_views),
    ("dashboard", scene_dashboard),
    ("provenance", scene_provenance),
    ("interaction", scene_interaction),
    ("autark", scene_autark),
    ("catalogpages", scene_catalog_pages),
    ("outro", scene_outro),
]


#: Scenes that assume a dataflow canvas is already open. Used only to decide
#: where a partial re-record has to start from.
CANVAS_SCENES = {
    "datacatalog", "build", "lineage", "nodecatalog", "libraries",
    "linkedviews", "dashboard", "provenance", "interaction", "autark",
}


def _selected_scenes() -> list[tuple[str, Callable[[Ctx], None]]]:
    wanted = os.environ.get("CURIO_TOUR_SCENES")
    if not wanted:
        return SCENES
    names = [n.strip() for n in wanted.split(",") if n.strip()]
    known = {name for name, _ in SCENES}
    unknown = [n for n in names if n not in known]
    if unknown:
        raise ValueError(
            f"unknown scene(s) {unknown}; valid ids: {[n for n, _ in SCENES]}"
        )
    return [(name, fn) for name, fn in SCENES if name in names]


def _warm_up(browser, frontend: str) -> None:
    """Pay webpack-dev-server's first-compile cost off camera.

    The very first request to the frontend can spend fifteen seconds serving a
    blank document while the bundle compiles. In a recording that is fifteen
    seconds of white, so it happens in a throwaway context before the one that
    is being recorded exists.
    """
    context = browser.new_context(viewport=VIDEO_SIZE)
    page = context.new_page()
    try:
        page.goto(f"{frontend}/auth/signin", timeout=120000)
        page.wait_for_load_state("domcontentloaded")
        try:
            page.get_by_text("Sign in", exact=False).first.wait_for(timeout=60000)
        except Exception:
            pass
    finally:
        context.close()


def test_record_feature_tour(frontend_server: str, current_server: str, browser):
    """Drive the whole feature set once, recording it as a single take."""
    scenes = _selected_scenes()
    raw_dir = os.path.join(out_dir(), "raw")
    os.makedirs(raw_dir, exist_ok=True)
    # Playwright names its recordings page@<hash>.webm and the finalizer deletes
    # the one it saved, but a killed run leaves its own behind. Clear only that
    # pattern, in a directory this test owns.
    for stale in os.listdir(raw_dir):
        if stale.startswith("page@") and stale.endswith(".webm"):
            try:
                os.remove(os.path.join(raw_dir, stale))
            except OSError:
                pass

    _warm_up(browser, frontend_server)

    context = browser.new_context(
        viewport=VIDEO_SIZE,
        record_video_dir=raw_dir,
        record_video_size=VIDEO_SIZE,
    )
    page = context.new_page()
    # The drawers slide with translate3d and the providers read
    # prefers-reduced-motion through useSyncExternalStore, so a panel is only
    # reachable once the transition is collapsed. The tour's own pacing supplies
    # the sense of movement instead.
    page.emulate_media(reduced_motion="reduce")
    # Unsaved-changes guards would otherwise block File > New dataflow with a
    # native confirm no one can answer.
    page.on("dialog", lambda d: d.accept())

    tour = Tour(page, pace=speed())
    ctx = Ctx(page=page, tour=tour, frontend=frontend_server, backend=current_server)

    # Recording a subset (CURIO_TOUR_SCENES) still has to start from a signed-in
    # browser, and re-running the signup form would collide with the account the
    # full tour creates. The DB stub gets there without spending screen time on
    # it, and is skipped when the signup scene is going to do it for real.
    selected = {name for name, _ in scenes}
    if not selected & {"intro", "signup"}:
        session = stub_db_login(
            page,
            frontend_url=frontend_server,
            backend_url=current_server,
            username=USER_LOGIN,
            name=USER_NAME,
            password=USER_PASSWORD,
            project_name="Feature Tour",
        )
        # Land where the first selected scene expects to be: the canvas scenes
        # assume a dataflow is already open, and dropping them on /projects
        # fails 30 seconds later on a menu that page does not have.
        if selected & CANVAS_SCENES and "canvas" not in selected:
            page.goto(f"{frontend_server}/dataflow/{session['project']['id']}")
            page.wait_for_load_state("domcontentloaded")
            page.locator("#tools-menu").wait_for(state="visible", timeout=45000)
        else:
            page.goto(f"{frontend_server}/projects")
            page.wait_for_load_state("domcontentloaded")
            wait_for_projects_page(page, timeout=30000)

    failures: list[tuple[str, str]] = []
    for name, scene in scenes:
        _log(f"[tour] scene: {name}")
        try:
            scene(ctx)
        except Exception:  # noqa: BLE001 - one bad scene must not lose the take
            failures.append((name, traceback.format_exc()))
            _log(f"[tour] scene {name} FAILED:\n{traceback.format_exc()}")
            # A still of the moment it broke localises the failure much faster
            # than the locator message on its own.
            try:
                page.screenshot(path=os.path.join(out_dir(), f"failed-{name}.png"))
            except Exception:
                pass
            try:
                tour.hush()
                page.keyboard.press("Escape")
            except Exception:
                pass

    page.close()
    context.close()
    written = finalize_video(page, stem="curio-feature-tour")
    for kind, path in written.items():
        _log(f"[tour] wrote {kind}: {path}")

    assert written, "no video was recorded"
    if failures:
        summary = "\n\n".join(f"--- {name} ---\n{tb}" for name, tb in failures)
        pytest.fail(
            f"{len(failures)} of {len(scenes)} scenes failed; the recording at "
            f"{written.get('mp4') or written.get('webm')} is missing them.\n\n"
            f"{summary}"
        )
