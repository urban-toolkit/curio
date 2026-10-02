"""The five browse pages share one layout, and it leaves room for the cards.

Two things the owner saw on the catalog pages:

* The rail's section dividers showed on some pages and not on others. Every
  page rendered the same divider; on a rail taller than the window the browser
  shrank it to 0px, because it was an empty flex item that was allowed to
  shrink. At 1280x720 that was the Data Catalog's rail and the Projects rail.
* The cards started below a crumb, a title, an intro, a search row and a chip
  row, in a grid fixed at two columns under a 1300px viewport.

So this measures, on every page, at the default 1280x720 viewport with the
details drawer open: each divider is painted, the grid lays out at least three
columns, and the first card starts high enough to leave two rows in view.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_catalog_layout_e2e.py -v
"""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from playwright.sync_api import expect

from .utils import (
    require_project_page,
    require_user_auth,
    signup_e2e_user,
    wait_for_projects_page,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

#: (path, h1, card selector inside <main>)
PAGES = (
    ("/projects", "Projects", "[data-project-id]"),
    ("/catalog/nodes", "Node Catalog", "article"),
    ("/catalog/data", "Data Catalog", "article"),
    ("/catalog/agents", "Agent Catalog", "article"),
    ("/catalog/lakes", "Data Lake Catalog", "article"),
)

#: The details drawer is 320px wide; with it open, <main> ends left of this.
DRAWER_OPEN_MAIN_RIGHT = 1280 - 300

#: Below the 65px header and the 47px tabs, a header band and the grid's
#: padding. At or above this, two rows of cards fit above the version badge.
FIRST_CARD_MAX_TOP = 260

MIN_COLUMNS = 3

_MEASURE = """([cardSelector]) => {
  const rail = document.querySelector('aside');
  const dividers = rail
    ? Array.from(rail.querySelectorAll(':scope > div:empty'))
        .map((d) => d.getBoundingClientRect().height)
    : [];
  const card = document.querySelector('main ' + cardSelector);
  const grid = card ? card.parentElement : null;
  const columns = grid
    ? getComputedStyle(grid).gridTemplateColumns.split(' ').filter(Boolean).length
    : 0;
  return {
    dividers,
    columns,
    firstCardTop: card ? Math.round(card.getBoundingClientRect().top) : null,
    mainRight: Math.round(document.querySelector('main').getBoundingClientRect().right),
  };
}"""


def test_every_browse_page_paints_its_rail_and_fits_three_columns(
    app_frontend: "FrontendPage", frontend_server: str, page
):
    require_user_auth()
    require_project_page()

    # A registered account, so /projects holds the seeded examples and has a
    # rail long enough to overflow.
    signup_e2e_user(
        page, frontend_server, name="Layout User",
        username=f"layout_{uuid.uuid4().hex[:10]}",
    )
    wait_for_projects_page(page, timeout=30000)

    failures: list[str] = []
    for path, heading, card_selector in PAGES:
        page.goto(f"{app_frontend.base_url}{path}")
        expect(page.get_by_role("heading", name=heading, level=1)).to_be_visible(
            timeout=30000
        )
        page.locator(f"main {card_selector}").first.wait_for(
            state="visible", timeout=30000
        )
        # The drawer opens on the first card on arrival; wait until the grid
        # has given it its column.
        page.wait_for_function(
            "(limit) => document.querySelector('main')"
            ".getBoundingClientRect().right <= limit",
            arg=DRAWER_OPEN_MAIN_RIGHT,
            timeout=15000,
        )
        page.wait_for_load_state("networkidle")

        m = page.evaluate(_MEASURE, [card_selector])
        if not m["dividers"]:
            failures.append(f"{path}: the rail has no section dividers")
        collapsed = [h for h in m["dividers"] if h < 1]
        if collapsed:
            failures.append(
                f"{path}: {len(collapsed)} of {len(m['dividers'])} rail dividers "
                f"are collapsed (heights {m['dividers']})"
            )
        if m["columns"] < MIN_COLUMNS:
            failures.append(
                f"{path}: the grid lays out {m['columns']} columns with the "
                f"drawer open, fewer than {MIN_COLUMNS}"
            )
        if m["firstCardTop"] is None or m["firstCardTop"] > FIRST_CARD_MAX_TOP:
            failures.append(
                f"{path}: the first card starts at y={m['firstCardTop']}, "
                f"below y={FIRST_CARD_MAX_TOP}"
            )
        print(f"{path}: {m}")

    assert not failures, "\n".join(failures)
