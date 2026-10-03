"""Scenes on layout and data shape: tag chips, a multi-view chart, a wide table."""
from __future__ import annotations

from playwright.sync_api import expect

from ..utils import frame_node, play_node
from .framework import Ctx, walkthrough
from .steps import first_node_of_type
from .agent_catalog import TAG_ROW_FIRST_CARD


# ---------------------------------------------------------------------------
# Layout and data shape (#193, #202, #203)
# ---------------------------------------------------------------------------

MULTI_VIEW_EXAMPLE = "05-vega-lite-multi-view-drilldown.json"

#: A Data Pool without Autark alongside it, so the scene needs no WebGPU.
DATA_POOL_EXAMPLE = "02-vega-lite-spatial-density.json"


@walkthrough(
    slug="catalog-tag-chips-are-plain",
    refs=[193],
    title="Tag chips read the same everywhere",
    premise="Compare the tag chips on a catalog card and in its detail drawer.",
    note="Four policies at once: the Data card tinted the LAST chip by file "
         "format - positional, not semantic, so a `2023` chip turned green "
         "because the file was GeoJSON; the Agent card tinted the last chip by "
         "category; the Package card tinted every chip; the detail drawer "
         "tinted none. All chips are plain now. Nothing is lost - the coloured "
         "card strip and the tinted avatar already carry format and category.",
    tests=["src/tests/catalog/tagChipsArePlain.test.ts",
           "src/tests/catalog/datasetFormatStyles.test.ts"],
    fit_reactflow=False,
    # The claim is that the chips in one card share a background, so the capture
    # is that chip row rather than a 1280x720 page (#333). Full page, 5% was
    # ~46,000 pixels of slack: more than the entire chip row, so a chip going
    # coloured again passed with room to spare. The row is 301x26, so 4% is
    # ~313 pixels and one re-tinted chip is thousands. It also stops the
    # baseline being hostage to the rest of the page: the footer version string
    # and the "15h ago" freshness labels drift on their own and forced
    # re-captures that had nothing to do with chips.
    #
    # 4% rather than the sibling's 8% because this frame was measured against
    # the render CI actually produced (recovered from the full-page baseline at
    # c906947b) and scored 0.88%, so 4% is still ~4.5x the observed
    # cross-machine cost. The same crop taken on macOS scores 6.11% against that
    # render: three quarters of an 8% budget spent on platform alone, which is
    # what makes minting these on Linux load-bearing rather than tidy.
    clip_selector=TAG_ROW_FIRST_CARD,
    max_diff_ratio=0.04,
)
def catalog_tag_chips_are_plain(ctx: Ctx) -> None:
    """The tints lived on the BROWSE PAGE cards, not the canvas drawer cards.

    `/catalog/data`, `/catalog/agents` and `/catalog/nodes` render
    `DataCatalogBrowseCard` / `AgentCatalogBrowseCard` / `PackageBrowseCard`,
    and those three were the ones with three different tinting policies. The
    canvas drawer uses `DatasetCard`, which never tinted - so a scene that
    opened the drawer was looking at the one surface the bug was not on.
    """
    page = ctx.page

    for kind, route, card_sel in (
        ("Data", "/catalog/data", "article[data-dataset-id]"),
        ("Agent", "/catalog/agents", "article[data-agent-coord]"),
        ("Node", "/catalog/nodes", "article[data-pkg-dir]"),
    ):
        ctx.say(f"The {kind} catalog",
                "Chips here used to take a colour from the format or category.")
        page.goto(f"{ctx.frontend}{route}")
        page.wait_for_load_state("domcontentloaded")
        if kind == "Node":
            # The page lists the newest package first, and the capture is the
            # first card's chips, so a newly shipped package would change the
            # frame. One named package keeps it the same card every time.
            page.locator(card_sel).first.wait_for(state="visible", timeout=30000)
            page.get_by_placeholder("Search packages…").fill("Custom UI")
            expect(page.locator(card_sel)).to_have_count(1, timeout=10000)

        card = page.locator(card_sel).first
        card.wait_for(state="visible", timeout=30000)
        card.scroll_into_view_if_needed()
        ctx.focus(card, hold=1200)

        # Every chip on one card resolves to the same background, so none of
        # them is carrying a colour the others are not.
        backgrounds = card.locator("[data-curio-tag-chip]").evaluate_all(
            "els => els.map(e => getComputedStyle(e).backgroundColor)"
        )
        assert backgrounds, f"the {kind} card rendered no tag chips"
        assert len(set(backgrounds)) == 1, (
            f"the chips on one {kind} card still differ in colour: "
            f"{sorted(set(backgrounds))}"
        )
        ctx.capture(f"plain-chips-{kind.lower()}")

    ctx.say("Every chip the same grey, on all three",
            "The coloured strip and the avatar are what carry the category.")


@walkthrough(
    slug="multi-view-vega-chart-is-reachable",
    refs=[202],
    title="A multi-view chart is not cut off",
    premise="Open a Vega-Lite chart with stacked sub-views and scroll to the bottom one.",
    note="Two independent defects, either alone enough to clip. The output "
         "container could not scroll - the pane is overflow:hidden and the "
         "mount div was height:100% with default overflow and no `nowheel`. "
         "And `width`/`height: \"container\"` was injected unconditionally, "
         "which vega-lite discards for vconcat/hconcat/facet/repeat, leaving "
         "`autosize: pad` - so ~750px of chart was authoritative inside a "
         "~292px pane and the ResizeObserver could not help.",
    tests=["src/tests/hook/vegaSpecSizing.test.ts",
           "src/tests/components/nodeEditorOutputScroll.test.tsx"],
    example=MULTI_VIEW_EXAMPLE,
    # The scene frames the chart node itself (see `frame_node` below); leaving
    # this True would have the capture helper fitView the whole 28-node
    # dataflow again immediately before each screenshot and undo it.
    fit_reactflow=False,
    max_diff_ratio=0.05,
)
def multi_view_vega_chart_is_reachable(ctx: Ctx) -> None:
    page = ctx.page

    ctx.say("A chart with stacked views",
            "Two sub-views, 650x400 and 650x300, in a ~292px pane.")

    # Resolved from the spec rather than `[id^=vega].first`: that picked
    # whichever mount happened to be first in DOM order, which is not
    # necessarily a node whose editor has mounted its output pane.
    # The example has nine vis-vega nodes and only some are the stacked ones;
    # the first is a single small view, which fits its pane and demonstrates
    # nothing. Pick the node whose spec is actually a vconcat.
    node_id = first_node_of_type(
        MULTI_VIEW_EXAMPLE, "vis-vega", containing="vconcat",
    )
    node = page.locator(f'.react-flow__node[data-id="{node_id}"]')
    node.wait_for(state="visible", timeout=45000)
    node.scroll_into_view_if_needed()

    # RUN it. The mount div exists from first render, so the scene could scroll
    # an EMPTY container and still pass every assertion below - which is what it
    # did: the recording showed a scrollbar moving over blank space and no
    # chart. A clipped chart is the whole subject, so there has to be one.
    ctx.say("Run it", "The chart is drawn from the node's own output.")
    play_node(page, node_id)

    mount = page.locator(f'#vega{node_id}')
    mount.wait_for(state="attached", timeout=45000)

    # Vega renders to a <canvas> inside the mount; wait for it, and for it to
    # be taller than the pane, or there is nothing to demonstrate.
    page.wait_for_function(
        "(id) => { const el = document.getElementById(id);"
        " const c = el && el.querySelector('canvas');"
        " return !!c && c.getBoundingClientRect().height > 0; }",
        arg=f"vega{node_id}",
        timeout=180000,
    )
    # Frame the node before capturing. The subject is a chart inside a 525x350
    # node; at the harness's fit zoom this example's 28 nodes make it a ~90x60
    # thumbnail, and both captures came out as the same canvas wallpaper.
    frame_node(page, node_id, zoom=1.1)
    ctx.focus(node, hold=1400)

    metrics = mount.evaluate(
        "el => ({ id: el.id, scrollH: el.scrollHeight, clientH: el.clientHeight,"
        " overflow: getComputedStyle(el).overflow,"
        " inlineStyle: el.getAttribute('style'),"
        " cls: el.getAttribute('class'),"
        " nowheel: el.classList.contains('nowheel') })"
    )
    # Report the whole measurement on failure: if this ever disagrees with
    # `nodeEditorOutputScroll.test.tsx` - which pins the same div at the unit
    # layer - the difference is what tells you which of the two is wrong.
    assert metrics["overflow"] == "auto", (
        f"the chart container does not scroll: {metrics}"
    )
    # `nowheel` is what stops React Flow zooming the canvas instead.
    assert metrics["nowheel"], "the container scrolls but the wheel zooms the canvas"

    # The claim only means something if the chart is actually taller than its
    # pane - otherwise there is nothing being clipped and nothing to scroll to.
    assert metrics["scrollH"] > metrics["clientH"] + 8, (
        f"the chart fits inside its pane ({metrics['scrollH']}px of content in "
        f"{metrics['clientH']}px), so this scene cannot show #202 - the node "
        f"probably rendered a single small view instead of the stacked ones"
    )
    ctx.capture("chart-clipped-at-the-fold")

    ctx.say("Scroll down to the second view",
            "It was there all along; there was simply no way to reach it.")
    mount.evaluate("el => el.scrollTo({ top: el.scrollHeight })")
    page.wait_for_timeout(900)
    assert mount.evaluate("el => el.scrollTop") > 0, (
        "the container reports overflow but would not scroll"
    )
    ctx.capture("scrolled-to-bottom-view")


@walkthrough(
    slug="data-pool-scrolls-sideways",
    refs=[203],
    title="A wide table can be read to its last column",
    premise="Open a Data Pool on a wide frame and scroll it right.",
    note="There WAS an x-overflow owner - MUI TableContainer's default "
         "`overflowX: auto` - but on the wrong element: it takes no height, so "
         "its box was as tall as the rows (~3000px) and its scrollbar was "
         "painted at the bottom of that, reachable only after scrolling to the "
         "last row. It also absorbed the overflow, so the node's own scroller "
         "never got one. Nothing set a min-width on the table either, so the "
         "browser crushed the columns instead of overflowing.",
    tests=["src/tests/components/tables/TabularPreviewTable.test.tsx",
           "src/tests/adapters/node/components/DataPoolContent.test.tsx"],
    example=DATA_POOL_EXAMPLE,
    # The claim above is asserted in code; the PNG only documents it. The
    # Linux runner antialiases text differently from the machine that captured
    # the baseline (6.4% of pixels on CI, run to run stable), so the pin
    # must leave room for that without waving through a real change.
    max_diff_ratio=0.10,
)
def data_pool_scrolls_sideways(ctx: Ctx) -> None:
    page = ctx.page

    # The scroller only exists once the pool has rendered a table, so the node
    # has to have RUN. Locating by the scroller attribute alone therefore found
    # nothing and looked like "no Data Pool in this dataflow".
    node_id = first_node_of_type(DATA_POOL_EXAMPLE, "data-pool")
    pool = page.locator(f'.react-flow__node[data-id="{node_id}"]')
    pool.wait_for(state="visible", timeout=45000)
    pool.scroll_into_view_if_needed()

    ctx.say("Run the pool", "It needs a table before there is anything to scroll.")
    play_node(page, node_id)

    scroller = pool.locator('[data-curio-datapool-scroll="true"]').first
    scroller.wait_for(state="visible", timeout=120000)
    ctx.focus(pool, hold=1200)
    metrics = scroller.evaluate(
        "el => ({ scrollW: el.scrollWidth, clientW: el.clientWidth,"
        " overflow: getComputedStyle(el).overflow })"
    )
    assert metrics["overflow"] == "auto", (
        f"the content area does not own both axes: overflow is {metrics['overflow']!r}"
    )

    ctx.say("Scroll right", "The last column used to be unreachable.")
    scroller.evaluate("el => el.scrollTo({ left: el.scrollWidth })")
    page.wait_for_timeout(900)

    moved = scroller.evaluate("el => el.scrollLeft")
    assert moved > 0 or metrics["scrollW"] <= metrics["clientW"], (
        "the table overflows but the content area would not scroll to it"
    )
    ctx.say("The right-hand columns, in place",
            "One scroller owns both axes now.")
    ctx.capture("scrolled-right")
