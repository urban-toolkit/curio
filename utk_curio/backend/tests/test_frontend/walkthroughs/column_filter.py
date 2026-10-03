"""The scene on the Column Filter reading a real DataFrame."""
from __future__ import annotations

import re

from playwright.sync_api import expect

from ..utils import (
    close_tools_palette,
    connect_nodes,
    drag_to_canvas,
    node_locator,
    open_tools_palette,
    run_node_and_wait,
    set_node_code,
)
from .framework import Ctx, walkthrough


# ---------------------------------------------------------------------------
# The Column Filter reads a real DataFrame (#194)
# ---------------------------------------------------------------------------

#: The package the Column Filter ships in, and the node body that feeds it.
EXAMPLE_UI_PKG = "curio.example-ui@1"
COLUMN_FILTER_CODE = (
    "import pandas as pd\n"
    "df = pd.DataFrame({'population': [2746, 8804, 1200],"
    " 'name': ['Chicago', 'NYC', 'Peoria']})\n"
    "return df\n"
)


@walkthrough(
    slug="column-filter-reads-a-dataframe",
    refs=[194],
    title="A packaged node reads the frame wired into it",
    premise="Wire Data Loading into the Column Filter and watch it react.",
    note="`asFrame` required the row-map encoding pandas' bare `to_dict()` "
         "produces and explicitly rejected arrays - but Curio serialises with "
         "`to_dict(orient='list')`, so every real DataFrame arrived as arrays, "
         "`asFrame` returned null, and the node sat there asking to be "
         "connected to the thing it was already connected to. Nothing threw and "
         "nothing logged, which is why it read as 'the node does nothing'.",
    tests=["src/tests/adapters/node/exampleUiColumnFilter.test.tsx",
           "sandbox/tests/test_dataframe_wire_shape.py",
           "test_frontend/test_package_refresh_e2e.py"],
    fit_reactflow=False,
    max_diff_ratio=0.05,
)
def column_filter_reads_a_dataframe(ctx: Ctx) -> None:
    page = ctx.page

    ctx.say("Add the example package", "The Column Filter ships inside it.")
    page.get_by_text("NODE CATALOG").click()
    page.get_by_role("button", name=re.compile("Browse Node Catalog")).click()
    drawer = page.locator('[data-curio-node-catalog-drawer="true"]')
    drawer.wait_for(state="attached", timeout=15000)
    expect(drawer).to_have_attribute("aria-hidden", "false", timeout=10000)

    card = page.locator(f'article[data-pkg-dir="{EXAMPLE_UI_PKG}"]')
    if card.count() == 0:
        card = page.locator("article").filter(has_text="Example: Custom UI Node").first
    ctx.click(card.first.get_by_role("button", name=re.compile(r"^Add to project")))
    # NOT `accept_confirm_dialog`. The Node catalog is the one that asks through
    # `InstallPermissionsDialog` rather than the shared `ConfirmDialog` — it has
    # permissions and conflicts to show, which is exactly the asymmetry #196
    # documented — so there is no dialog named "Add …" to wait for here.
    page.get_by_role("dialog").last.get_by_role(
        "button", name=re.compile(r"^(Add|Install)")
    ).last.click()
    expect(
        page.locator(f'article[data-pkg-dir="{EXAMPLE_UI_PKG}"]').first.get_by_role(
            "button", name="Remove from project"
        )
    ).to_be_visible(timeout=120000)
    page.keyboard.press("Escape")

    ctx.say("A node that outputs a frame", "Three rows, one numeric column.")
    # A node is 525 px wide at zoom 1: these two drops leave room for the wire
    # between them and keep the filter inside the 1280 px viewport.
    loading = drag_to_canvas(page, page.locator("#tile-data-loading"), at=(170, 200))
    set_node_code(page, loading, COLUMN_FILTER_CODE)

    ctx.say("And the Column Filter beside it")
    open_tools_palette(page, "packages")
    row = page.locator(f'#packages-palette [data-pkg-palette-coords~="{EXAMPLE_UI_PKG}"]')
    expect(row).to_have_count(1, timeout=30000)
    filter_node = drag_to_canvas(page, row, at=(740, 220))
    close_tools_palette(page, "packages")

    node = node_locator(page, filter_node)
    ctx.focus(node, hold=1000)
    # Before the frame arrives the node is honest about what it is waiting for;
    # capturing it here is what makes the next frame mean something.
    ctx.capture("waiting-for-a-frame")

    ctx.say("Wire them together, and run the loader",
            "This is the moment the node used to ignore.")
    connect_nodes(page, loading, filter_node)
    run_node_and_wait(page, loading, node_type="curio.builtin/data-loading")

    # THE POINT: the node read the frame. It names the numeric column it found
    # and counts the rows that match, neither of which it could do from the
    # payload it used to reject.
    body = node_locator(page, filter_node)
    expect(body).to_contain_text("population", timeout=60000)
    expect(body).to_contain_text(re.compile(r"\d+ of \d+ rows match"), timeout=60000)
    text = " ".join((body.text_content() or "").split())
    assert "Connect a DataFrame upstream" not in text, (
        "the Column Filter still says it has no frame after one was wired in "
        f"and run, so `asFrame` is rejecting the payload again: {text[:200]}"
    )
    ctx.focus(body, hold=1400)
    ctx.capture("reading-the-frame")
    ctx.say("It found the column and counted the rows",
            "The same payload it used to reject.")
