"""Playwright E2E: the Projects rail, and categories set on the canvas.

The unit tests cover the pieces: ``test_projects/test_categories.py`` the
server's derivation and the approved placement of the 45 shipped dataflows,
``projectsPageChrome.test.tsx`` the rail's arithmetic. What only a browser on a
seeded stack shows is the whole trip: the fixtures seeded as tests, the
categories the server computes reaching the canvas title, and a category added
there saved with the dataflow and listed on the rail.
"""
from __future__ import annotations

import re
import uuid
from typing import TYPE_CHECKING

import pytest
from playwright.sync_api import expect

from .utils import (
    project_card,
    require_project_page,
    require_user_auth,
    save_dataflow,
    signup_e2e_user,
    wait_for_projects_page,
)

if TYPE_CHECKING:
    from .utils import FrontendPage


#: Needs the shipped dataflows, which ``--with-examples`` seeds.
pytestmark = pytest.mark.examples

FIXTURE = "Interaction_Vega_Autark"


def _rail(page):
    return page.get_by_role("complementary", name="Filter dataflows")


def _rail_entry(page, label: str, count: int):
    """A rail button by its label and count, which its accessible name joins."""
    return _rail(page).get_by_role(
        "button", name=re.compile(rf"^{re.escape(label)}\s*{count}$")
    )


def _sign_up(page, frontend_server: str) -> None:
    require_user_auth()
    require_project_page()
    username = f"categories_{uuid.uuid4().hex[:10]}"
    signup_e2e_user(page, frontend_server, name="Categories User", username=username)
    wait_for_projects_page(page, timeout=30000)
    project_card(page, "Vega-Lite chained transforms").first.wait_for(
        state="visible", timeout=30000
    )


def test_the_rail_lists_the_tests(app_frontend: "FrontendPage", frontend_server: str, page):
    """The deploy question that started this: the fixtures were never seeded."""
    _sign_up(page, frontend_server)

    # #662: 23 with the Scenarios and FloodScenarios test dataflows.
    _rail_entry(page, "Tests", 23).click()

    expect(project_card(page, FIXTURE)).to_have_count(1, timeout=10000)
    expect(page.locator("[data-curio-projects-scroll] [data-project-id]")).to_have_count(23)

    # One entry per section: picking the use case replaces the tests.
    _rail_entry(page, "Use cases", 1).click()
    expect(project_card(page, "Heterogeneous data + linked views")).to_have_count(1)
    expect(project_card(page, FIXTURE)).to_have_count(0)

    # And sections combine: Seattle's three are all tests.
    _rail_entry(page, "Use cases", 1).click()
    _rail_entry(page, "Seattle", 3).click()
    _rail_entry(page, "Tests", 3).click()
    expect(page.locator("[data-curio-projects-scroll] [data-project-id]")).to_have_count(3)


def test_a_category_set_on_the_canvas_reaches_the_rail(
    app_frontend: "FrontendPage", frontend_server: str, page
):
    _sign_up(page, frontend_server)

    project_card(page, FIXTURE).first.dblclick()
    page.wait_for_url("**/dataflow/**", timeout=15000)

    chips = page.locator("[data-curio-category-chips]").first
    # Computed by the server from the nodes, and not removable.
    expect(chips.get_by_text("Autark", exact=True)).to_be_visible(timeout=30000)
    expect(chips.get_by_text("Tests", exact=True)).to_be_visible()
    expect(chips.get_by_role("button", name="Remove Autark")).to_have_count(0)
    # Set in the shipped file.
    expect(chips.get_by_text("Seattle", exact=True)).to_be_visible()

    topic = f"Topic {uuid.uuid4().hex[:6]}"
    chips.get_by_role("button", name="+ Category").click()
    form = page.get_by_role("group", name="Add a category")
    form.get_by_role("combobox", name="Category section").select_option("topic")
    form.get_by_role("combobox", name="Category name").fill(topic)
    form.get_by_role("button", name="Add", exact=True).click()
    expect(chips.get_by_text(topic, exact=True)).to_be_visible()
    save_dataflow(page)

    page.goto(f"{frontend_server}/projects")
    wait_for_projects_page(page, timeout=30000)
    _rail_entry(page, topic, 1).click()
    expect(page.locator("[data-curio-projects-scroll] [data-project-id]")).to_have_count(1)
    expect(project_card(page, FIXTURE)).to_have_count(1)
