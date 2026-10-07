"""Playwright E2E: catalog ages read the same on every day.

The catalogs show how long ago each item was made ("2d ago", "Updated 141d
ago"), measured against the browser's clock. Shipped items carry fixed dates,
so on the real clock each such age, and each frame showing one, grew by a day
every day. A test marked ``catalog_calendar`` runs its browser on
``CATALOG_CALENDAR`` (utils/catalog_clock.py), and the backend stamps what the
test makes on the same date.

``test_catalog_cards_read_their_age_on_the_calendar`` pins that as the frames
show it: a shipped dataset's card and a shipped package's card read the ages
they have on the calendar date and on no other, and a dataset the test makes
reads "1m ago" with the fresh dot beside them, which it does only when the
backend stamps it on the calendar too.
``test_every_shipped_date_is_days_before_the_calendar`` keeps the calendar
after every date the catalogs ship.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_catalog_calendar_e2e.py -v
"""
from __future__ import annotations

import json
import math
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from playwright.sync_api import expect

from .utils import (
    REPO_ROOT,
    drag_to_canvas,
    enable_save_output,
    require_owner_view,
    require_project_page,
    require_user_auth,
    run_node_and_wait,
    set_node_code,
    stub_login_and_enter_workflow,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

LOADING_TILE = "#tile-data-loading"
LOADING_TYPE = "curio.builtin/data-loading"
#: A frame, so running the node with save-output on leaves a ``computed.``
#: dataset: something the backend stamps while the test runs.
OWN_DATASET_CODE = (
    "import pandas as pd\n"
    "df = pd.DataFrame({'a': [1, 2, 3], 'b': ['x', 'y', 'z']})\n"
    "return df\n"
)

#: SCOUT's buildings and its shadow package both shipped dated 2026-10-05 00:00
#: UTC, 54 hours before the calendar date: "2d ago" there, "3d ago" by noon of
#: that day on the real clock, and more every day after.
SHIPPED_DATASET = "data.scout.loop-buildings"
SHIPPED_PACKAGE = "scout.shadow@1"
SHIPPED_AGE = "2d ago"

#: The text the catalogs give an age (``catalogTimeFormat.ts``).
AGE = re.compile(r"^\d+[mhd] ago$")
#: The fill of the fresh dot: changed within the last day (``.liveDotGreen``,
#: CatalogBrowseLayout.module.css).
FRESH_FILL = "--curio-role-installed-fg"

_HAS_FILL_JS = """(dot, token) => {
    const probe = document.createElement('span');
    probe.style.background = `var(${token})`;
    dot.parentElement.appendChild(probe);
    const want = getComputedStyle(probe).backgroundColor;
    probe.remove();
    return getComputedStyle(dot).backgroundColor === want;
}"""


def _age(card):
    """The age on a catalog card: the innermost span that reads "<n>m|h|d ago"."""
    return card.locator("xpath=.//span[not(*)]").filter(has_text=AGE)


def _fresh(age) -> bool:
    """Whether the dot before a Data Catalog card's age has the fresh fill."""
    dot = age.locator("xpath=preceding-sibling::span[1]")
    return dot.evaluate(_HAS_FILL_JS, FRESH_FILL)


@pytest.mark.catalog_calendar
def test_catalog_cards_read_their_age_on_the_calendar(
    app_frontend: "FrontendPage", current_server: str, page
):
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Calendar User",
        username="catalog_calendar",
        project_name="Catalog calendar",
    )
    require_owner_view(page)
    page.locator("#tools-menu").wait_for(state="visible", timeout=45000)

    # A dataset of the user's own, which the backend stamps as it is saved.
    loading = drag_to_canvas(page, page.locator(LOADING_TILE), at=(220, 200))
    set_node_code(page, loading, OWN_DATASET_CODE)
    enable_save_output(page, loading)
    run_node_and_wait(page, loading, node_type=LOADING_TYPE)

    page.goto(f"{app_frontend.base_url}/catalog/data")
    page.wait_for_load_state("domcontentloaded")

    shipped = page.locator(f'article[data-dataset-id="{SHIPPED_DATASET}"]')
    shipped.wait_for(state="visible", timeout=60000)
    expect(_age(shipped)).to_have_text(SHIPPED_AGE)
    assert not _fresh(_age(shipped)), (
        f"{SHIPPED_DATASET} is {SHIPPED_AGE} old on the calendar, yet its card "
        f"marks it as changed within the last day"
    )

    own = page.locator('article[data-dataset-id^="computed."]').first
    own.wait_for(state="visible", timeout=60000)
    expect(_age(own)).to_have_text("1m ago")
    assert _fresh(_age(own)), (
        "the dataset this test just made reads 1m ago but without the fresh dot, "
        "so the backend stamped it after the page's own date: the record clock "
        "is not on the calendar"
    )

    page.goto(f"{app_frontend.base_url}/catalog/nodes")
    page.wait_for_load_state("domcontentloaded")
    package = page.locator(f'article[data-pkg-dir="{SHIPPED_PACKAGE}"]')
    package.wait_for(state="visible", timeout=60000)
    expect(_age(package)).to_have_text(SHIPPED_AGE)


def _age_text(age: timedelta) -> str:
    """What ``catalogRelativeTime`` (catalogTimeFormat.ts) shows for *age*.

    JavaScript's ``Math.round`` rounds a half up, Python's ``round`` to even.
    """
    minutes = max(1, math.floor(age.total_seconds() / 60 + 0.5))
    if minutes < 60:
        return f"{minutes}m ago"
    hours = math.floor(minutes / 60 + 0.5)
    if hours < 48:
        return f"{hours}h ago"
    return f"{math.floor(hours / 24 + 0.5)}d ago"


def _shipped_dates():
    """``(item, field, date)`` for every shipped date a catalog shows as an age."""
    root = Path(REPO_ROOT)
    for path in sorted(root.glob("datasets/*/manifest.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        # The record date the catalog lists (catalog_item.item_from_manifest),
        # and the source file's, which the details panel shows.
        yield path.parent.name, "updatedAt", raw.get("updatedAt") or raw.get("createdAt")
        yield path.parent.name, "sourceUpdatedAt", raw.get("sourceUpdatedAt")
    for kind in ("packages", "models"):
        for path in sorted(root.glob(f"{kind}/*/manifest.json")):
            raw = json.loads(path.read_text(encoding="utf-8"))
            yield path.parent.name, "createdAt", raw.get("createdAt")


def test_every_shipped_date_is_days_before_the_calendar():
    """Every shipped date reads in whole days on the calendar, and still does two hours on.

    An item dated after the calendar would read "1m ago" beside what a test
    makes; one dated less than two days before it reads in hours, which a long
    test moves; and one whose days round up within two hours of the calendar
    reads one day more in a slow test.
    """
    from .utils.catalog_clock import CATALOG_CALENDAR  # main has no calendar yet

    unstable = []
    for item, field, value in _shipped_dates():
        if not value:
            continue
        age = CATALOG_CALENDAR - datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        later = _age_text(age + timedelta(hours=2))
        if age < timedelta(hours=48) or _age_text(age) != later:
            unstable.append(f"{item} {field} {value}: {_age_text(age)}, then {later}")
    assert not unstable, (
        f"these shipped dates do not read a steady age on the catalog calendar "
        f"({CATALOG_CALENDAR.isoformat()}): {unstable}. Move CATALOG_CALENDAR in "
        f"utils/catalog_clock.py to two days or more after the newest of them, "
        f"then re-mint the frames of the tests marked catalog_calendar."
    )
