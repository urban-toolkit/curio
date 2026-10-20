"""Playwright E2E: going back to a version and editing starts a branch in the provenance drawer.

Every version is made from one other: the one on the canvas when the edit
happened. So putting an earlier version back and editing makes the new version
from that one, and the versions made after it are left on a branch. The drawer
keeps the line to the newest version and folds that branch under the version
it left from; opened, the fold lists those versions in the order they were
made, on a rail of their own. A history where each version has one parent is a
tree, and the list shows any tree this way; here the branch is made through
the canvas, not written into a file.

It runs on the fixed catalog date, so the times the drawer shows read the same
in every frame.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_provenance_branches_e2e.py -v
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from playwright.sync_api import expect

from .utils import (
    connect_nodes,
    frame_nodes,
    require_owner_view,
    require_project_page,
    require_user_auth,
    save_workflow_test_screenshot,
    stub_login_and_enter_workflow,
    wait_for_drawer_closed,
)
from .walkthroughs import load_example_spec
from .walkthroughs.steps import (
    PROVENANCE_DRAWER,
    PROVENANCE_ITEM,
    PROVENANCE_PANEL,
    await_drawer_at_rest,
    await_provenance_history,
    canvas_graph,
    open_version,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

#: Loading it records the empty dataflow, then a version per node and one per
#: connection: one chain of 12 versions.
EXAMPLE = "01-vega-lite-chained-transforms.json"

TEST_NAME = "test_a_provenance_branch_folds_under_the_version_it_left_from"

#: The version put back: every node, and only the connection into the first
#: Data Transformation.
BACK_TO = 8
#: The first two Data Transformations. Connecting them on version 8 is one
#: edit, so one new version, made from version 8.
FIRST_TRANSFORM = "a0c5d21f-ce16-4318-95fe-598451859de1"
SECOND_TRANSFORM = "6475234e-0288-49cd-b03f-19852717c980"

#: Scrolls the drawer's body, the part of the panel holding *el*, to its end.
_BODY_TO_END_JS = """(el) => {
    const panel = el.closest('[role="dialog"]');
    const body = Array.from(panel.children).find((child) => child.contains(el));
    body.scrollTop = body.scrollHeight;
}"""


def _open(page):
    page.get_by_role("button", name="View menu", exact=True).click()
    page.get_by_test_id("provenance-menu-item").click()
    panel = page.locator(PROVENANCE_PANEL)
    panel.wait_for(state="visible", timeout=20000)
    await_drawer_at_rest(page)
    await_provenance_history(page)
    return panel


def _close(page) -> None:
    page.get_by_role("button", name="Close Dataflow provenance", exact=True).click()
    wait_for_drawer_closed(page, PROVENANCE_DRAWER)


def _listed(page) -> list[str]:
    """The versions the drawer lists, top to bottom, folded ones left out."""
    return page.locator(PROVENANCE_ITEM).evaluate_all("els => els.map((el) => el.dataset.provenanceItem)")


def _ids(locator) -> list[str]:
    return locator.evaluate_all("els => els.map((el) => el.dataset.provenanceItem)")


@pytest.mark.catalog_calendar
def test_a_provenance_branch_folds_under_the_version_it_left_from(
    app_frontend: "FrontendPage", current_server: str, page,
):
    require_project_page()
    require_user_auth()

    page.emulate_media(reduced_motion="reduce")
    spec = load_example_spec(EXAMPLE)
    nodes = len(spec["dataflow"]["nodes"])
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Prov User",
        username="prov_branches",
        project_name="Provenance Branches",
        project_spec=spec,
    )
    require_owner_view(page)
    page.wait_for_selector(".react-flow__node", timeout=45000)

    # A loaded dataflow's history is one chain: nothing to fold.
    panel = _open(page)
    chain = _listed(page)
    assert len(chain) == 1 + nodes + len(spec["dataflow"]["edges"]), chain
    assert panel.locator("[data-provenance-fold]").count() == 0, (
        "a loaded dataflow's history is one chain, yet the drawer folds a branch"
    )

    # Version 8 back on the canvas: every node, one connection.
    back = panel.locator(f'[data-provenance-item="{chain[BACK_TO - 1]}"]')
    open_version(page, back)
    back.get_by_role("button", name="Put this version on the canvas", exact=True).click()
    expect(back).to_have_attribute("data-provenance-current", "true")
    _close(page)
    page.wait_for_function(
        "() => document.querySelectorAll('.react-flow__edge').length === 1", timeout=15000,
    )
    assert canvas_graph(page) == {"nodes": nodes, "edges": 1}, canvas_graph(page)

    # One edit on the canvas, made from version 8.
    frame_nodes(page, [FIRST_TRANSFORM, SECOND_TRANSFORM])
    connect_nodes(page, FIRST_TRANSFORM, SECOND_TRANSFORM)

    panel = _open(page)
    listed = _listed(page)
    made = [version for version in listed if version not in chain]
    assert len(made) == 1, f"one connection should make one version, not {made}"
    newest = made[0]
    left_behind = chain[BACK_TO:]

    # The line to the newest version runs through version 8, and the versions
    # made after 8 are folded under it.
    assert listed == chain[:BACK_TO] + [newest], (
        f"the drawer should list versions 1 to {BACK_TO}, then the new one: {listed}"
    )
    item = panel.locator(f'[data-provenance-item="{newest}"]')
    expect(item).to_have_attribute("data-provenance-current", "true")
    expect(item).to_contain_text("Connection added")
    fold = panel.get_by_role("button", name=f"{len(left_behind)} versions on another branch", exact=True)
    expect(fold).to_have_count(1)
    expect(fold).to_have_attribute("aria-expanded", "false")
    under = fold.evaluate("el => el.closest('li').querySelector('[data-provenance-item]').dataset.provenanceItem")
    assert under == chain[BACK_TO - 1], f"the branch hangs under {under}, not version {BACK_TO}"

    # Opened, the fold lists them right under version 8, in the order they were
    # made, on a rail of their own.
    fold.click()
    expect(fold).to_have_attribute("aria-expanded", "true")
    assert _listed(page) == chain[:BACK_TO] + left_behind + [newest], _listed(page)
    branch = panel.locator('[data-provenance-line="1"]')
    expect(branch).to_have_count(1)
    assert _ids(branch.locator("[data-provenance-item]")) == left_behind

    item.evaluate(_BODY_TO_END_JS)
    save_workflow_test_screenshot(
        page, "provenance-branch",
        test_name=TEST_NAME,
        fit_reactflow=False,
        clip_selector=PROVENANCE_PANEL,
    )
    _close(page)
