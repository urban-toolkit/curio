"""Playwright E2E for #156: the Data Pool node must scroll its own rows.

The report: "Users should be able to scroll within the Data Pool node and
inspect all available tables without resizing" - instead the rows past the
node's height were simply unreachable.

A merge (8e98eba) swapped the inline MUI ``TableContainer`` for the shared
``TabularPreviewTable`` and dropped its ``sx={{ overflow: 'auto' }}``. The
wrapper that ``DataPoolContent`` pins to the node box is ``overflow: hidden``,
so with nothing below it owning scroll the extra rows were clipped.

``DataPoolContent.test.tsx`` pins the styles at the unit layer. This test exists
because those styles are only half the story in a live canvas: React Flow
installs a wheel handler on the pane and swallows the event before the div sees
it unless the element carries ``nowheel``. Only a real browser with React Flow
mounted can tell "the div is scrollable" from "the user can scroll it".

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_data_pool_scroll_e2e.py -v
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from .utils import (
    connect_nodes,
    dismiss_toasts,
    drag_to_canvas,
    node_locator,
    require_project_page,
    require_user_auth,
    run_node_and_wait,
    save_workflow_test_screenshot,
    set_node_code,
    skip_if_shared_view,
    stub_login_and_enter_workflow,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

LOADING_TILE = "#step-loading"
POOL_TILE = "#step-pool"
LOADING_TYPE = "curio.builtin/data-loading"

POS_UP = (150, 150)
POS_DOWN = (760, 150)

SCROLLER = '[data-curio-datapool-scroll="true"]'
TAB_STRIP = '[data-testid="data-pool-tabs"]'

# Comfortably more rows than a 525x350 node can show, so "the grid overflows"
# is not a marginal judgement call.
ROW_COUNT = 200


def _viewport_transform(page) -> str:
    return page.evaluate(
        "() => { const el = document.querySelector('.react-flow__viewport');"
        " return el ? getComputedStyle(el).transform : ''; }"
    )


def test_the_data_pool_scrolls_its_rows_without_resizing_the_node(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
):
    require_project_page()
    require_user_auth()

    page.emulate_media(reduced_motion="reduce")
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Pool User",
        username="pool_scroll",
        project_name="Data Pool Scroll",
    )
    skip_if_shared_view(page)

    loading = drag_to_canvas(page, page.locator(LOADING_TILE), at=POS_UP)
    pool = drag_to_canvas(page, page.locator(POOL_TILE), at=POS_DOWN)
    connect_nodes(page, loading, pool)

    set_node_code(
        page, loading,
        "import pandas as pd\n"
        f"df = pd.DataFrame({{'idx': list(range({ROW_COUNT})), "
        f"'label': [f'row_{{i:03d}}' for i in range({ROW_COUNT})]}})\n"
        "return df\n",
    )
    run_node_and_wait(page, loading, node_type=LOADING_TYPE)

    pool_el = node_locator(page, pool)
    pool_el.locator(TAB_STRIP).first.wait_for(state="visible", timeout=30000)

    scroller = pool_el.locator(SCROLLER).first
    scroller.wait_for(state="visible", timeout=30000)
    # Rows have to have landed before any measurement: an empty table cannot
    # overflow, so measuring early would make this test vacuously pass.
    page.wait_for_function(
        "(sel) => {"
        "  const el = document.querySelector(sel);"
        "  return !!el && el.scrollHeight > el.clientHeight + 8;"
        "}",
        arg=f'.react-flow__node[data-id="{pool}"] {SCROLLER}',
        timeout=30000,
    )

    metrics = scroller.evaluate(
        "el => ({ scrollHeight: el.scrollHeight, clientHeight: el.clientHeight,"
        " overflowY: getComputedStyle(el).overflowY })"
    )
    assert metrics["overflowY"] in ("auto", "scroll"), (
        f"the Data Pool's content area is not a scroll owner (overflow-y="
        f"{metrics['overflowY']!r}); its parent is overflow:hidden, so the rows "
        f"below the fold are clipped and only a node resize reveals them (#156)"
    )

    # Pin a row that starts below the fold. Without it "scrollTop moved" could
    # be true of an empty box; with it, the scroll demonstrably reveals a row
    # the user could previously only reach by resizing the node.
    hidden_row_offset = scroller.evaluate(
        """el => {
            const rows = el.querySelectorAll('tbody tr');
            const last = rows[rows.length - 1];
            if (!last) return null;
            return last.getBoundingClientRect().bottom - el.getBoundingClientRect().bottom;
        }"""
    )
    assert hidden_row_offset is not None, "the Data Pool rendered no table rows"
    assert hidden_row_offset > 0, (
        f"the last row already fits inside the node ({hidden_row_offset}px past "
        f"the fold), so this test cannot tell a scrollable pool from a clipped "
        f"one - raise ROW_COUNT or shrink the node"
    )

    # The behavioural half. `nowheel` is what stops React Flow eating the wheel
    # event; without it the styles above are present and the user still cannot
    # scroll - the canvas zooms instead.
    box = scroller.bounding_box()
    assert box, "the Data Pool scroll container has no layout box"
    before_transform = _viewport_transform(page)
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.mouse.wheel(0, 600)
    page.wait_for_function(
        "(sel) => { const el = document.querySelector(sel); return el && el.scrollTop > 0; }",
        arg=f'.react-flow__node[data-id="{pool}"] {SCROLLER}',
        timeout=10000,
    )
    scrolled = scroller.evaluate("el => el.scrollTop")
    assert scrolled > 0, (
        "a wheel gesture over the Data Pool did not move its rows, which is the "
        "user-visible symptom of #156"
    )
    assert _viewport_transform(page) == before_transform, (
        "the wheel reached the React Flow pane and zoomed the canvas instead of "
        "scrolling the node - the `nowheel` class is missing from the scroller"
    )

    # Drive it all the way down and confirm the row that was past the fold is
    # now inside the node's box.
    scroller.evaluate("el => { el.scrollTop = el.scrollHeight; }")
    page.wait_for_timeout(300)
    revealed_offset = scroller.evaluate(
        """el => {
            const rows = el.querySelectorAll('tbody tr');
            const last = rows[rows.length - 1];
            return last.getBoundingClientRect().bottom - el.getBoundingClientRect().bottom;
        }"""
    )
    assert revealed_offset <= 4, (
        f"scrolling to the bottom of the Data Pool still leaves the last row "
        f"{revealed_offset}px outside the node - the rows are clipped, not scrolled"
    )

    # The other half of the fix: the tab strip stays one row tall and scrolls
    # sideways, so a pool with many tables never steals height from the table.
    strip = pool_el.locator(TAB_STRIP).first
    strip_style = strip.evaluate(
        "el => ({ overflowX: getComputedStyle(el).overflowX,"
        " flexWrap: getComputedStyle(el).flexWrap,"
        " nowheel: el.classList.contains('nowheel') })"
    )
    assert strip_style["overflowX"] in ("auto", "scroll"), (
        f"the Data Pool tab strip does not scroll horizontally: {strip_style}"
    )
    assert strip_style["flexWrap"] == "nowrap", (
        f"the Data Pool tab strip wraps, so extra tables push the table below "
        f"out of the node: {strip_style}"
    )
    assert strip_style["nowheel"], (
        "the tab strip lacks `nowheel`, so React Flow swallows a scroll over it"
    )

    dismiss_toasts(page)
    save_workflow_test_screenshot(
        page, "data-pool-scroll",
        test_name="test_the_data_pool_scrolls_its_rows_without_resizing_the_node",
    )
