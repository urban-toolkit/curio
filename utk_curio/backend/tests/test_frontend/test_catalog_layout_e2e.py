"""The browse pages share one layout, and it leaves room for the cards.

Two things the owner saw on the catalog pages:

* The rail's section dividers showed on some pages and not on others. Every
  page rendered the same divider; on a rail taller than the window the browser
  shrank it to 0px, because it was an empty flex item that was allowed to
  shrink. At 1280x720 that was the Data Catalog's rail and the Projects rail.
* The cards started below a crumb, a title, an intro, a search row and a chip
  row, in a grid fixed at two columns under a 1300px viewport.

So this measures, on every page, at the default 1280x720 viewport with the
details drawer open: each divider is painted, the grid lays out at least three
columns, the first card starts high enough to leave two rows in view, and no
card in view is cut short. That last one is the price of the others: a grid of
fixed height may squeeze its rows, and the first version of this layout did,
down to a strip and half a title per card, while passing the other three.

Then the owner saw two cards in a row again, in a window narrower than about
1240px: the grid fitted as many 220px cards as the rail and the drawer left
room for. So the same pages are measured again at 1150x720, where every page
must still lay out three columns, with no card cut short.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_catalog_layout_e2e.py -v
"""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from playwright.sync_api import expect

from .utils import (
    api_json,
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
    ("/catalog/skills", "Skill Catalog", "article"),
    ("/catalog/discovery", "Discovery Catalog", "article"),
    ("/catalog/models", "Model Catalog", "article"),
    ("/catalog/scenarios", "Scenario Catalog", "article"),
)

#: The details drawer is 300px wide; with it open, <main> ends at or left of
#: the window's width less this.
DRAWER_WIDTH = 300

#: Below the 65px bar, which holds the section links, a header band and the
#: grid's padding. At or above this, two rows of cards fit above the version
#: badge. It was 260 while a 48px band of tabs sat under the bar.
FIRST_CARD_MAX_TOP = 212

MIN_COLUMNS = 3

#: A window narrower than the default, where 220px cards fell to two a row.
NARROW_WIDTH = 1150

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
  // A card that clips its content (they all hide overflow) is taller inside
  // than it is drawn. Only the cards whose top is in view.
  const clipped = Array.from(document.querySelectorAll('main ' + cardSelector))
    .filter((c) => c.getBoundingClientRect().top < window.innerHeight)
    .filter((c) => c.scrollHeight > c.clientHeight + 1)
    .map((c) => c.clientHeight + '<' + c.scrollHeight);
  return {
    dividers,
    columns,
    clipped,
    firstCardTop: card ? Math.round(card.getBoundingClientRect().top) : null,
    mainRight: Math.round(document.querySelector('main').getBoundingClientRect().right),
  };
}"""


def _code_node(node_id: str, x: int) -> dict:
    return {
        "id": node_id, "type": "curio.builtin/python-computation@1",
        "content": "return 1", "x": x, "y": 0,
    }


def _save_a_scenario(page, backend: str) -> None:
    """A project with one scenario of the account's own, beside any the seeded
    examples bring (#662: the scenarios example brings two)."""
    token = next(
        c["value"] for c in page.context.cookies() if c["name"].startswith("session_token")
    )
    api_json(f"{backend}/api/projects", token, method="POST", payload={
        "name": "Layout scenarios",
        "spec": {"dataflow": {
            "name": "Layout scenarios",
            "nodes": [_code_node("a", 0), _code_node("b", 300)],
            "edges": [{"id": "e1", "source": "a", "target": "b"}],
            "scenarios": [{"id": "s1", "name": "Baseline", "color": "#2a9d8f", "nodes": ["b"]}],
        }},
        "outputs": [],
    })


def _sign_up_with_a_scenario(page, frontend_server: str, current_server: str) -> None:
    # A registered account, so /projects holds the seeded examples and has a
    # rail long enough to overflow.
    signup_e2e_user(
        page, frontend_server, name="Layout User",
        username=f"layout_{uuid.uuid4().hex[:10]}",
    )
    wait_for_projects_page(page, timeout=30000)
    _save_a_scenario(page, current_server)


def _measure_every_page(page, base_url: str, width: int) -> list[dict]:
    """Each page's measures at this window width, with its drawer open."""
    page.set_viewport_size({"width": width, "height": 720})
    measured = []
    for path, heading, card_selector in PAGES:
        page.goto(f"{base_url}{path}")
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
            arg=width - DRAWER_WIDTH,
            timeout=15000,
        )
        page.wait_for_load_state("networkidle")

        m = page.evaluate(_MEASURE, [card_selector])
        print(f"{width}px {path}: {m}")
        measured.append({"path": path, **m})
    return measured


def _columns_and_cards(m: dict, width: int) -> list[str]:
    failures: list[str] = []
    if m["columns"] < MIN_COLUMNS:
        failures.append(
            f"{m['path']} at {width}px: the grid lays out {m['columns']} columns "
            f"with the drawer open, fewer than {MIN_COLUMNS}"
        )
    if m["clipped"]:
        failures.append(
            f"{m['path']} at {width}px: {len(m['clipped'])} cards in view are cut "
            f"short (drawn < content heights: {m['clipped']})"
        )
    return failures


def test_every_browse_page_paints_its_rail_and_fits_three_columns(
    app_frontend: "FrontendPage", frontend_server: str, current_server: str, page
):
    require_user_auth()
    require_project_page()
    _sign_up_with_a_scenario(page, frontend_server, current_server)

    failures: list[str] = []
    for m in _measure_every_page(page, app_frontend.base_url, 1280):
        path = m["path"]
        if not m["dividers"]:
            failures.append(f"{path}: the rail has no section dividers")
        collapsed = [h for h in m["dividers"] if h < 1]
        if collapsed:
            failures.append(
                f"{path}: {len(collapsed)} of {len(m['dividers'])} rail dividers "
                f"are collapsed (heights {m['dividers']})"
            )
        failures += _columns_and_cards(m, 1280)
        if m["firstCardTop"] is None or m["firstCardTop"] > FIRST_CARD_MAX_TOP:
            failures.append(
                f"{path}: the first card starts at y={m['firstCardTop']}, "
                f"below y={FIRST_CARD_MAX_TOP}"
            )

    assert not failures, "\n".join(failures)


def test_every_browse_page_fits_three_columns_in_a_narrower_window(
    app_frontend: "FrontendPage", frontend_server: str, current_server: str, page
):
    require_user_auth()
    require_project_page()
    _sign_up_with_a_scenario(page, frontend_server, current_server)

    failures: list[str] = []
    for m in _measure_every_page(page, app_frontend.base_url, NARROW_WIDTH):
        failures += _columns_and_cards(m, NARROW_WIDTH)

    assert not failures, "\n".join(failures)
