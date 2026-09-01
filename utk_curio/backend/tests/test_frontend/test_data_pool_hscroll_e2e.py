"""Playwright E2E for #203: the Data Pool must scroll SIDEWAYS too.

The report: a wide frame's right-hand columns are unreachable, and the columns
that are visible are crushed together.

Commit ``0b5edea4`` ("fixes #156") gave the content area ``overflow: 'auto'``
and ``nowheel`` for the **vertical** axis; the x axis was never addressed. And
there *was* an x-overflow owner all along - MUI ``TableContainer``'s default
``{ width: '100%', overflowX: 'auto' }`` - but on the wrong element. It receives
no height or flex, so its box is content-height (up to 100 rows, ~3000px) while
the visible node body is ~250px: its horizontal scrollbar was painted at the
bottom of that 3000px box, reachable only after scrolling to the very last row.
Worse, it *absorbed* the x overflow, so the outer ``overflow: auto`` div never
got a scrollbar of its own.

Secondary, same root: nothing set a min-width on ``<Table>``. MUI's
``width: 100%`` with ``table-layout: auto``, plus ``shortenString`` truncating
cells to 15 characters, means the browser squeezes every column toward
min-content instead of overflowing - the crushed columns in the screenshot.

This is the x-axis twin of ``test_data_pool_scroll_e2e.py`` and exists for the
same reason that one does: the unit tests
(``DataPoolContent.test.tsx``, ``TabularPreviewTable.test.tsx``) pin the styles,
but only a real browser with React Flow mounted can tell "the div is
scrollable" from "the user can actually scroll it" - React Flow's ZoomPane
swallows the wheel unless the element carries ``nowheel``.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_data_pool_hscroll_e2e.py -v
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
    require_owner_view,
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

# Comfortably more columns than a 525px-wide node can show, so "the grid
# overflows horizontally" is not a marginal judgement call. Long-ish names so
# each column has real min-content width even after `shortenString`.
COLUMN_COUNT = 40
ROW_COUNT = 5


def _viewport_transform(page) -> str:
    return page.evaluate(
        "() => { const el = document.querySelector('.react-flow__viewport');"
        " return el ? getComputedStyle(el).transform : ''; }"
    )


def test_the_data_pool_scrolls_to_its_last_column(
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
        username="pool_hscroll",
        project_name="Data Pool HScroll",
    )
    require_owner_view(page)

    loading = drag_to_canvas(page, page.locator(LOADING_TILE), at=POS_UP)
    pool = drag_to_canvas(page, page.locator(POOL_TILE), at=POS_DOWN)
    connect_nodes(page, loading, pool)

    set_node_code(
        page, loading,
        "import pandas as pd\n"
        f"cols = {{f'measurement_column_{{c:02d}}': "
        f"[f'v{{r}}_{{c}}' for r in range({ROW_COUNT})] for c in range({COLUMN_COUNT})}}\n"
        "df = pd.DataFrame(cols)\n"
        "return df\n",
    )
    run_node_and_wait(page, loading, node_type=LOADING_TYPE)

    pool_el = node_locator(page, pool)
    scroller = pool_el.locator(SCROLLER).first
    scroller.wait_for(state="visible", timeout=30000)

    # The columns have to have landed before any measurement: an empty table
    # cannot overflow, so measuring early would make this vacuously pass.
    page.wait_for_function(
        "(sel) => {"
        "  const el = document.querySelector(sel);"
        "  return !!el && el.scrollWidth > el.clientWidth + 8;"
        "}",
        arg=f'.react-flow__node[data-id="{pool}"] {SCROLLER}',
        timeout=30000,
    )

    metrics = scroller.evaluate(
        "el => ({ scrollWidth: el.scrollWidth, clientWidth: el.clientWidth,"
        " overflowX: getComputedStyle(el).overflowX })"
    )
    assert metrics["overflowX"] in ("auto", "scroll"), (
        f"the Data Pool's content area does not own horizontal scroll "
        f"(overflow-x={metrics['overflowX']!r}), so the right-hand columns are "
        f"unreachable (#203)"
    )

    # The inner MUI container must NOT be the x-overflow owner. While it was,
    # the outer scroller above could never receive a scrollbar, and the one MUI
    # painted sat ~3000px down at the bottom of the rows.
    inner_overflow = pool_el.locator(".MuiTableContainer-root").first.evaluate(
        "el => getComputedStyle(el).overflowX"
    )
    assert inner_overflow not in ("auto", "scroll"), (
        f"MUI's TableContainer is still claiming the x overflow "
        f"(overflow-x={inner_overflow!r}); its scrollbar is painted at the "
        f"bottom of the full row height, not at the bottom of the node"
    )

    # The columns overflow rather than being crushed toward min-content.
    table_min_width = pool_el.locator("table").first.evaluate(
        "el => getComputedStyle(el).minWidth"
    )
    assert table_min_width == "max-content", (
        f"the table declares min-width {table_min_width!r}, so MUI's width:100% "
        f"squeezes every column instead of overflowing - the crushed columns "
        f"half of #203"
    )

    # Pin a column that starts past the right edge, so "scrollLeft moved" is
    # demonstrably revealing something the user could not previously reach.
    hidden_col_offset = scroller.evaluate(
        """el => {
            const cells = el.querySelectorAll('thead th');
            const last = cells[cells.length - 1];
            if (!last) return null;
            return last.getBoundingClientRect().right - el.getBoundingClientRect().right;
        }"""
    )
    assert hidden_col_offset is not None, "the Data Pool rendered no header cells"
    assert hidden_col_offset > 0, (
        f"the last column already fits inside the node ({hidden_col_offset}px "
        f"past the edge), so this test cannot tell a scrollable pool from a "
        f"clipped one - raise COLUMN_COUNT"
    )

    # The behavioural half. `nowheel` on the ancestor is what stops React Flow
    # eating the gesture; React Flow matches with `closest`, so shift+wheel
    # works with no new class. Without it the styles above are all present and
    # the canvas zooms instead.
    box = scroller.bounding_box()
    assert box, "the Data Pool scroll container has no layout box"
    before_transform = _viewport_transform(page)
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.keyboard.down("Shift")
    page.mouse.wheel(0, 600)
    page.keyboard.up("Shift")
    page.wait_for_function(
        "(sel) => { const el = document.querySelector(sel); return el && el.scrollLeft > 0; }",
        arg=f'.react-flow__node[data-id="{pool}"] {SCROLLER}',
        timeout=10000,
    )
    assert scroller.evaluate("el => el.scrollLeft") > 0, (
        "a shift+wheel gesture over the Data Pool did not move its columns, "
        "which is the user-visible symptom of #203"
    )
    assert _viewport_transform(page) == before_transform, (
        "the wheel reached the React Flow pane and zoomed the canvas instead of "
        "scrolling the node - the `nowheel` ancestor is missing"
    )

    # Drive it all the way right and confirm the column that was past the edge
    # is now inside the node's box.
    scroller.evaluate("el => { el.scrollLeft = el.scrollWidth; }")
    page.wait_for_timeout(300)
    revealed_offset = scroller.evaluate(
        """el => {
            const cells = el.querySelectorAll('thead th');
            const last = cells[cells.length - 1];
            return last.getBoundingClientRect().right - el.getBoundingClientRect().right;
        }"""
    )
    assert revealed_offset <= 4, (
        f"scrolling to the right of the Data Pool still leaves the last column "
        f"{revealed_offset}px outside the node - the columns are clipped, not "
        f"scrolled"
    )

    # The vertical axis still works: one declaration owns both, and #156 must
    # not regress in the course of fixing #203.
    assert scroller.evaluate("el => getComputedStyle(el).overflowY") in (
        "auto",
        "scroll",
    ), "fixing the x axis cost the y axis its scroll owner (#156)"

    dismiss_toasts(page)
    save_workflow_test_screenshot(
        page, "data-pool-hscroll",
        test_name="test_the_data_pool_scrolls_to_its_last_column",
    )
