"""Playwright E2E for #345: the Data Summary node must scroll SIDEWAYS too.

#203 fixed this for the Data Pool and left two sibling surfaces alone. This is
the node one. ``describe()`` with ``include="all"`` produces one column per
dataframe column, so the stats table is arbitrarily wide - far wider than a
525px node - and MUI ``Table``'s default ``width: 100%`` with
``table-layout: auto`` squeezes every column toward min-content instead of
overflowing. The ``TableContainer`` around it has carried ``overflow-x: auto``
all along and never had anything to scroll.

Why a browser and not only ``dataSummaryScroll.test.tsx``: that pins the three
style properties, but only a real browser with React Flow mounted can tell "the
div is scrollable" from "the user can actually scroll it" - React Flow's
ZoomPane swallows the wheel unless an ancestor carries ``nowheel``. That is the
same argument ``test_data_pool_hscroll_e2e.py`` makes, and the same reason it
exists alongside its own unit tests.

Ownership differs from the Data Pool on purpose: there one outer div owns the
scroll because the node body IS the table, while here three tables stack under
their own headings, so each scrolls in its own container and the headings stay
put.

Platform note for anyone running this locally on a Mac: the shift+wheel step
below does nothing in headless Chromium there, because the shift-to-horizontal
conversion is done by macOS rather than by Blink. ``test_data_pool_hscroll_e2e``
has the same step and fails at the same point on macOS, on untouched main - so a
failure there is the platform, not the fix. The style and geometry assertions
above it are platform-independent and are the substance of the claim.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_data_summary_hscroll_e2e.py -v
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from .utils import (
    dismiss_toasts,
    play_node,
    require_owner_view,
    require_project_page,
    require_user_auth,
    save_workflow_test_screenshot,
    stub_login_and_enter_workflow,
    wait_for_node_done,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

LOADING_ID = "summary-hscroll-loading"
SUMMARY_ID = "summary-hscroll-summary"
SUMMARY_TYPE = "curio.builtin/data-summary"
LOADING_TYPE = "curio.builtin/data-loading"

# The DESCRIBE table specifically: it is the wide one (one column per dataframe
# column) and it renders LAST, so `.first` would land on the 2-column dtypes
# table, which cannot overflow and would pass vacuously.
SCROLLER = '[data-curio-summary-scroll="describe"]'

# Comfortably more columns than a 525px node can show, so "it overflows" is not
# a marginal judgement call. Long names so each column has real min-content
# width of its own.
COLUMN_COUNT = 40
ROW_COUNT = 5

LOADING_CODE = (
    "import pandas as pd\n"
    f"cols = {{f'measurement_column_{{c:02d}}': "
    f"[float(r + c) for r in range({ROW_COUNT})] for c in range({COLUMN_COUNT})}}\n"
    "df = pd.DataFrame(cols)\n"
    "return df\n"
)

SUMMARY_CODE = (
    "summary = {\n"
    "    'shape': {'rows': arg.shape[0], 'columns': arg.shape[1]},\n"
    "    'describe': arg.describe(include='all').to_dict(),\n"
    "    'dtypes': {c: str(t) for c, t in arg.dtypes.items()},\n"
    "    'missing': {c: int(n) for c, n in arg.isna().sum().items()},\n"
    "}\n"
    "return summary\n"
)


def _spec() -> dict:
    return {
        "dataflow": {
            "name": "Data Summary HScroll",
            "task": "",
            "nodes": [
                {
                    "id": LOADING_ID,
                    "type": LOADING_TYPE,
                    "x": 150,
                    "y": 150,
                    "content": LOADING_CODE,
                    "in": "DEFAULT",
                    "out": "DEFAULT",
                    "goal": "",
                    "metadata": {"keywords": []},
                },
                {
                    "id": SUMMARY_ID,
                    "type": SUMMARY_TYPE,
                    "x": 760,
                    "y": 150,
                    "content": SUMMARY_CODE,
                    "in": "DEFAULT",
                    "out": "DEFAULT",
                    "goal": "",
                    "metadata": {"keywords": []},
                },
            ],
            "edges": [{
                "id": f"{LOADING_ID}-{SUMMARY_ID}",
                "source": LOADING_ID,
                "target": SUMMARY_ID,
            }],
        }
    }


def test_the_data_summary_scrolls_to_its_last_column(
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
        name="Summary User",
        username="summary_hscroll",
        project_name="Data Summary HScroll",
        project_spec=_spec(),
    )
    require_owner_view(page)

    # play + wait, not run_node_and_wait: that also reads the node's output
    # BOX, and a Data Summary node replaces it with the rendered summary once
    # it succeeds, so the box is never visible on a healthy run.
    for node_id, node_type in ((LOADING_ID, LOADING_TYPE), (SUMMARY_ID, SUMMARY_TYPE)):
        play_node(page, node_id)
        wait_for_node_done(page, node_id, node_type=node_type)

    summary = page.locator(f'.react-flow__node[data-id="{SUMMARY_ID}"]')
    scroller = summary.locator(SCROLLER).first
    scroller.wait_for(state="visible", timeout=60000)

    # The columns have to have landed before any measurement: an empty table
    # cannot overflow, so measuring early would make this vacuously pass.
    page.wait_for_function(
        "(sel) => {"
        "  const el = document.querySelector(sel);"
        "  return !!el && el.scrollWidth > el.clientWidth + 8;"
        "}",
        arg=f'.react-flow__node[data-id="{SUMMARY_ID}"] {SCROLLER}',
        timeout=60000,
    )

    metrics = scroller.evaluate(
        "el => ({ scrollWidth: el.scrollWidth, clientWidth: el.clientWidth,"
        " overflowX: getComputedStyle(el).overflowX,"
        " tableMinWidth: getComputedStyle(el.querySelector('table')).minWidth })"
    )
    assert metrics["tableMinWidth"] == "max-content", (
        "without min-width:max-content the browser squeezes the columns toward "
        f"min-content instead of overflowing (got {metrics['tableMinWidth']!r})"
    )

    # Scrollability is asserted by SCROLLING, not by reading overflow-x.
    # `scrollWidth > clientWidth` above is true of a merely-overflowing box too,
    # and the computed value is not a reliable stand-in: it came back "auto" on
    # macOS and "visible" on the Linux CI runner for this same element, while
    # the box scrolled in both. What the user needs is that setting scrollLeft
    # moves it, so that is what this checks - and the computed value rides along
    # in the message for whoever debugs the next difference.
    moved = scroller.evaluate(
        "el => { el.scrollLeft = 400; return el.scrollLeft; }"
    )
    assert moved > 0, (
        "the stats table's container does not scroll horizontally "
        f"(scrollLeft stayed {moved}; overflow-x={metrics['overflowX']!r}, "
        f"scrollWidth={metrics['scrollWidth']}, clientWidth={metrics['clientWidth']})"
    )
    scroller.evaluate("el => { el.scrollLeft = 0; }")

    # The behavioural half: a shift+wheel over the table must scroll IT, not pan
    # the canvas. `nowheel` on an ancestor is what makes that true.
    # The describe table renders below Shape / Data Types / Missing Values, so
    # on a ~250px node body it starts outside the visible area. Its layout box
    # exists all the same, and hovering that would put the cursor outside the
    # node entirely - the wheel would then reach the canvas, and this would
    # "fail" for a reason that has nothing to do with the fix.
    scroller.scroll_into_view_if_needed()
    box = scroller.bounding_box()
    assert box is not None
    before_transform = page.evaluate(
        "() => { const el = document.querySelector('.react-flow__viewport');"
        " return el ? getComputedStyle(el).transform : ''; }"
    )
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    # Shift+wheel, as the Data Pool test does: a bare deltaX wheel is not how a
    # trackpad or mouse produces horizontal scroll here, and the browser does
    # not turn it into one.
    page.keyboard.down("Shift")
    page.mouse.wheel(0, 600)
    page.keyboard.up("Shift")
    page.wait_for_function(
        "(sel) => { const el = document.querySelector(sel); return !!el && el.scrollLeft > 0; }",
        arg=f'.react-flow__node[data-id="{SUMMARY_ID}"] {SCROLLER}',
        timeout=10000,
    )
    assert page.evaluate(
        "() => { const el = document.querySelector('.react-flow__viewport');"
        " return el ? getComputedStyle(el).transform : ''; }"
    ) == before_transform, (
        "the wheel panned the canvas instead of scrolling the table - the "
        "`nowheel` ancestor is missing"
    )

    # And the last column is reachable, which is the user-visible claim.
    scroller.evaluate("el => { el.scrollLeft = el.scrollWidth; }")
    reached = scroller.evaluate(
        "el => el.scrollLeft + el.clientWidth >= el.scrollWidth - 4"
    )
    assert reached, "could not scroll to the right-hand edge of the stats table"

    # #156 must still hold: the node body keeps vertical scroll.
    body_overflow_y = summary.locator(".nowheel").first.evaluate(
        "el => getComputedStyle(el).overflowY"
    )
    assert body_overflow_y in ("auto", "scroll")

    dismiss_toasts(page)
    save_workflow_test_screenshot(
        page, "data-summary-hscroll",
        test_name="test_the_data_summary_scrolls_to_its_last_column",
    )
