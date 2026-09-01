"""Playwright E2E: save a project and verify it loads in executed state."""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

from playwright.sync_api import expect

from .utils import (
    _post_json,
    api_json,
    require_project_page,
    require_user_auth,
    signup_and_enter_new_workflow,
    signup_e2e_user,
    stub_db_login,
    wait_for_projects_page,
)

if TYPE_CHECKING:
    from .utils import FrontendPage


def test_project_save_via_menu(app_frontend: "FrontendPage", page):
    """Save via File > Save dataflow and verify the project appears on /projects.

    Previous incarnation of this test looked for a `Saved dataflows` submenu
    inside the File menu; that submenu was removed in
    a9c3f66 ("Standardizing interface elements, tweaks to the file menu")
    when the in-canvas list was superseded by the dedicated `/projects`
    page. The save round-trip itself is the same — `handleSave` POSTs to
    `/api/projects` and `refreshSavedProjects()` invalidates the cache —
    so we verify the save by navigating to `/projects` and asserting the
    new entry renders, which is the user-facing path that replaced the
    submenu.
    """
    require_project_page()
    signup_and_enter_new_workflow(
        page,
        app_frontend.base_url,
        name="Project Tester",
        username="prjtester",
    )

    file_btn = page.get_by_role("button", name=re.compile("File"))
    file_btn.wait_for(state="visible", timeout=15000)
    file_btn.click(force=True)

    save_btn = page.get_by_role("button", name="Save dataflow", exact=True)
    save_btn.wait_for(state="visible", timeout=5000)
    save_btn.click()
    # `handleSave` closes the File menu once the save + refreshSavedProjects
    # round-trip completes, so the Save button being hidden is our signal that
    # the save is fully done.
    save_btn.wait_for(state="hidden", timeout=10000)
    # wait for the save to be completed
    page.wait_for_timeout(2000)

    # Navigate to /projects (the current home for saved dataflows after
    # the file-menu simplification). `FlowProvider` seeds `workflowName` to
    # "DefaultDataflow" and `handleSave` defaults to that name, so a project
    # row with that title must be present.
    page.goto(f"{app_frontend.base_url}/projects")
    page.wait_for_load_state("domcontentloaded")
    wait_for_projects_page(page, timeout=15000)
    expected = page.get_by_text("DefaultDataflow", exact=True)
    expected.first.wait_for(state="visible", timeout=10000)


def test_project_list_page(app_frontend: "FrontendPage", page):
    """Verify the projects page shows saved projects."""
    require_project_page()
    base = app_frontend.base_url

    signup_e2e_user(
        page, base, name="Project Lister", username="prjlister",
    )
    page.goto(f"{base}/projects")
    page.wait_for_load_state("domcontentloaded")
    wait_for_projects_page(page, timeout=10000)


def _empty_spec(name: str) -> dict:
    return {"dataflow": {"name": name, "nodes": [], "edges": []}}


def test_projects_search_ignores_surrounding_whitespace(
    app_frontend: "FrontendPage", current_server: str, page,
):
    """#231: a project name pasted with a trailing space found nothing.

    The predicate used the raw input value as the needle
    (``p.name.toLowerCase().includes(search.toLowerCase())``), so every space the
    user did not mean to type became part of the string being searched for. The
    reporter hit it by pasting a name; the Node Catalog beside it already trimmed,
    which is what made the inconsistency visible.

    Projects are seeded over the testing seam rather than through the UI: this is
    a search test, not a project-creation one.
    """
    require_project_page()
    require_user_auth()

    stub_db_login(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Search User",
        username="search_user",
    )
    for title in ("Street-level computer vision", "Weather analysis"):
        _post_json(
            f"{current_server}/api/testing/stub-project",
            {"username": "search_user", "name": title, "spec": _empty_spec(title)},
        )

    page.goto(f"{app_frontend.base_url}/projects")
    wait_for_projects_page(page, timeout=20000)
    page.get_by_text("Street-level computer vision").first.wait_for(
        state="visible", timeout=20000
    )

    box = page.get_by_placeholder("Search projects…")

    # The reported case: the exact name plus one trailing space.
    box.fill("Street-level computer vision ")
    page.get_by_text("Street-level computer vision").first.wait_for(
        state="visible", timeout=10000
    )
    assert page.get_by_text("Weather analysis").count() == 0, (
        "the other project should have been filtered out"
    )
    assert page.get_by_text("No projects match the current filters.").count() == 0, (
        "a padded query must not empty the list - this is #231"
    )

    # A leading space too, which no amount of haystack padding could ever absorb.
    box.fill("  Street-level computer vision  ")
    page.get_by_text("Street-level computer vision").first.wait_for(
        state="visible", timeout=10000
    )

    # Whitespace alone is no query at all, so both projects come back - and the
    # empty-state copy must not claim they were filtered out.
    box.fill("   ")
    page.get_by_text("Weather analysis").first.wait_for(state="visible", timeout=10000)
    page.get_by_text("Street-level computer vision").first.wait_for(
        state="visible", timeout=10000
    )
    assert page.get_by_text("No projects match the current filters.").count() == 0


def test_rename_then_save_updates_the_projects_card(
    app_frontend: "FrontendPage", current_server: str, page,
):
    """#230: renaming on the canvas and saving left the Projects card unchanged.

    The name is stored twice - the project row (Projects list) and
    ``spec.dataflow.name`` (canvas title). The canvas rename wrote only the
    second, and ``saveCurrentProject`` sent ``projectName``, which only
    ``loadProject`` ever set. So the save faithfully re-sent the load-time name.

    Both halves of the reported symptom are asserted: the card moves, AND no
    second project appears - the reporter noted the rename neither renamed nor
    forked, and a fix that forked would be just as wrong.
    """
    require_project_page()
    require_user_auth()

    session = stub_db_login(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Rename User",
        username="rename_user",
    )
    token = session["token"]
    created = _post_json(
        f"{current_server}/api/testing/stub-project",
        {
            "username": "rename_user",
            "name": "Before Rename",
            "spec": _empty_spec("Before Rename"),
        },
    )
    pid = created["id"]

    page.goto(f"{app_frontend.base_url}/dataflow/{pid}")
    page.wait_for_load_state("domcontentloaded")

    title = page.locator("h1").filter(has_text="Before Rename")
    title.wait_for(state="visible", timeout=30000)
    title.click()

    box = page.locator("input[type='text']").last
    box.wait_for(state="visible", timeout=10000)
    box.fill("After Rename")
    box.press("Enter")

    # The rename diverges from disk, so the indicator must say so. Nothing said
    # it before; that was invisible only while #229's phantom dirty flag was on.
    disk = page.locator("[data-curio-save-state]")
    expect(disk).to_have_attribute("data-curio-save-state", "unsaved", timeout=10000)

    disk.click()
    expect(disk).to_have_attribute("data-curio-save-state", "saved", timeout=20000)

    page.goto(f"{app_frontend.base_url}/projects")
    wait_for_projects_page(page, timeout=20000)
    page.get_by_text("After Rename").first.wait_for(state="visible", timeout=20000)
    assert page.get_by_text("Before Rename").count() == 0, (
        "the Projects card still shows the old name - this is #230"
    )

    listed = api_json(f"{current_server}/api/projects", token)
    assert len(listed) == 1, (
        f"renaming must move the dataflow, not fork it; got {len(listed)} projects: "
        f"{[p['name'] for p in listed]}"
    )


def test_renaming_from_the_projects_list_reaches_the_canvas_title(
    app_frontend: "FrontendPage", current_server: str, page,
):
    """The mirror image of #230, closed by the backend half of the fix.

    A name-only PUT - what the Projects list's rename sends - never entered the
    spec block at all, so the canvas title kept rendering the old
    ``spec.dataflow.name`` until some later canvas save happened to overwrite it.
    """
    require_project_page()
    require_user_auth()

    session = stub_db_login(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="List Rename User",
        username="listrename_user",
    )
    token = session["token"]
    created = _post_json(
        f"{current_server}/api/testing/stub-project",
        {
            "username": "listrename_user",
            "name": "Old List Name",
            "spec": _empty_spec("Old List Name"),
        },
    )
    pid = created["id"]

    # Renamed over the API rather than through the context menu: the subject is
    # what the canvas reads back, not the menu interaction.
    api_json(
        f"{current_server}/api/projects/{pid}",
        token,
        method="PUT",
        payload={"name": "New List Name"},
    )

    page.goto(f"{app_frontend.base_url}/dataflow/{pid}")
    page.wait_for_load_state("domcontentloaded")
    heading = page.locator("h1").filter(has_text="New List Name")
    heading.wait_for(state="visible", timeout=30000)
    assert page.locator("h1").filter(has_text="Old List Name").count() == 0, (
        "the canvas title still shows the pre-rename name from the spec"
    )
