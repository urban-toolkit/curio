"""Playwright E2E: the tutorial describes controls the product actually has.

#240: the Data Loading step told users they could "import data from a file"
there. The uploader that claim was written against lived in ``WidgetsEditor``,
was commented out after ``export default``, and is now deleted. Someone
following the tour opened the node and found a code editor.

This walks the real intro.js tour, reading the tooltip the user reads, rather
than the source. The source read (``tutorialCopy.test.ts``) covers step order
cheaply; this one covers the claim that the tour is reachable and says what we
think it says.

Run::

    CURIO_TESTING=1 pytest \
        utk_curio/backend/tests/test_frontend/test_tutorial_copy_e2e.py -v
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest
from playwright.sync_api import expect

from .utils import (
    require_owner_view,
    require_project_page,
    require_user_auth,
    stub_login_and_enter_workflow,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

TOOLTIP = ".introjs-tooltiptext"
NEXT = ".introjs-nextbutton"

# The tour is long, and the two steps under test sit near the front. Bounded so
# a tour that never advances costs a few seconds rather than hanging.
MAX_STEPS = 14


@pytest.fixture()
def tutorial(app_frontend: "FrontendPage", current_server: str, page):
    """Open Help > Tutorial on a fresh dataflow and return the page."""
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Tutorial Copy User",
        username="tutorialcopy",
        project_name="TutorialCopy",
    )
    require_owner_view(page)

    page.get_by_role("button", name=re.compile(r"^Help")).click(force=True)
    page.get_by_role("button", name="Tutorial", exact=True).first.click()
    expect(page.locator(TOOLTIP)).to_be_visible(timeout=15000)
    return page


def _walk(page) -> list[str]:
    """Every tooltip the tour shows, in order."""
    seen: list[str] = []
    for _ in range(MAX_STEPS):
        tip = page.locator(TOOLTIP).first
        if not tip.count():
            break
        text = tip.inner_text().strip()
        if text and (not seen or seen[-1] != text):
            seen.append(text)
        nxt = page.locator(NEXT)
        if not nxt.count() or not nxt.first.is_visible():
            break
        nxt.first.click()
        page.wait_for_timeout(250)
    return seen


def _step_about_data_loading(steps: list[str]) -> str:
    for text in steps:
        if "Data Loading Node" in text:
            return text
    raise AssertionError(f"no Data Loading step in the tour: {steps}")


def test_the_data_loading_step_does_not_promise_a_file_picker(tutorial):
    steps = _walk(tutorial)
    step = _step_about_data_loading(steps)

    assert not re.search(r"import data from a file", step, re.I), (
        f"the tour still promises a control the node lacks: {step!r}"
    )
    assert re.search(r"not a file picker", step, re.I), (
        f"the tour does not say where the file does go: {step!r}"
    )


def test_the_data_loading_step_names_the_routes_that_exist(tutorial):
    step = _step_about_data_loading(_walk(tutorial))
    assert "Data Catalog" in step, f"the Data Catalog is not named: {step!r}"
    # The `[!! var$FILE !!]` marker is the only thing that renders a file input
    # inside a node.
    assert "$FILE" in step, f"the file widget marker is not named: {step!r}"


def test_the_tour_explains_the_data_catalog_next(tutorial):
    steps = _walk(tutorial)
    loading = next(i for i, t in enumerate(steps) if "Data Loading Node" in t)
    catalog = next(
        (i for i, t in enumerate(steps) if "Files live in the Data Catalog" in t),
        None,
    )
    assert catalog is not None, f"no Data Catalog step in the tour: {steps}"
    assert catalog == loading + 1, (
        "the Data Loading step says 'next step', so the Catalog step has to be "
        f"the next one: loading={loading}, catalog={catalog}"
    )
    assert re.search(r"drag the dataset onto the canvas", steps[catalog], re.I)


def test_the_palette_anchor_the_step_points_at_still_exists(tutorial):
    # Several suites locate the Data Loading tile through #step-loading, and an
    # intro.js step whose element is missing renders centred with no highlight,
    # which is a silent way for this step to rot.
    expect(tutorial.locator("#step-loading")).to_have_count(1)
