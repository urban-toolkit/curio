"""Playwright E2E: a dataflow loaded from a file is a dataflow of its own (#751).

The report: open a dataflow, choose File > Load dataflow, pick a dataflow saved
as JSON, save it, and the projects page does not list it. The load kept the
open dataflow's project, so the save wrote the file's nodes into that project
under that project's name. Nothing was listed under the file's name, and the
dataflow that had been open lost its own nodes.

Both halves are checked here: the file's dataflow is listed under its own name
and opens with its own nodes, and the dataflow that was open keeps its nodes and
its name. Loading over unsaved changes asks first, as every other way out of a
dataflow does.

Run::

    CURIO_TESTING=1 pytest \
        utk_curio/backend/tests/test_frontend/test_loaded_dataflow_saves_e2e.py -v
"""
from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

from playwright.sync_api import expect

from .utils import (
    accept_confirm_dialog,
    api_json,
    node_locator,
    project_card,
    require_owner_view,
    require_project_page,
    require_user_auth,
    save_dataflow,
    stub_login_and_enter_workflow,
    upload_workflow,
    wait_for_projects_page,
)

if TYPE_CHECKING:
    from .utils import FrontendPage


OPEN_NAME = "Rainfall by district"
OPEN_IDS = ["rainfall-1"]
FILE_NAME = "Tree canopy by block"
FILE_IDS = ["canopy-1", "canopy-2"]
SECOND_FILE_NAME = "Bus stops by route"
SECOND_FILE_IDS = ["stops-1"]

DISCARD_TITLE = "Discard unsaved changes?"
TITLE = "[data-curio-canvas-title] h1"
SAVE_STATE = "[data-curio-save-state]"


def _spec(name: str, node_ids: list[str]) -> dict:
    """A dataflow of computation nodes, one per id, side by side."""
    return {
        "dataflow": {
            "name": name,
            "task": "",
            "nodes": [
                {
                    "id": node_id,
                    "type": "curio.builtin/computation-analysis",
                    "x": 420 * index,
                    "y": 200,
                    "content": f"return {index + 1}",
                    "in": "DEFAULT",
                    "out": "DEFAULT",
                    "goal": "",
                    "metadata": {"keywords": []},
                }
                for index, node_id in enumerate(node_ids)
            ],
            "edges": [],
        }
    }


def _write(tmp_path, filename: str, spec: dict) -> str:
    path = tmp_path / filename
    path.write_text(json.dumps(spec), encoding="utf-8")
    return str(path)


def _enter_open_dataflow(page, app_frontend, current_server, *, username: str) -> dict:
    """Sign in and open a saved dataflow with its own node, as the report starts."""
    page.emulate_media(reduced_motion="reduce")
    session = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Load Dataflow User",
        username=username,
        project_name=OPEN_NAME,
        project_spec=_spec(OPEN_NAME, OPEN_IDS),
    )
    require_owner_view(page)
    _expect_canvas(page, OPEN_IDS, OPEN_NAME)
    return session


def _expect_canvas(page, node_ids: list[str], title: str) -> None:
    """The canvas shows exactly *node_ids*, under *title*."""
    for node_id in node_ids:
        node_locator(page, node_id).wait_for(state="visible", timeout=60000)
    expect(page.locator(".react-flow__node")).to_have_count(len(node_ids), timeout=30000)
    expect(page.locator(TITLE)).to_have_text(title, timeout=30000)


def _pick_file(page, path: str) -> None:
    """Choose File > Load dataflow and hand the chooser *path*."""
    file_menu = page.get_by_role("button", name=re.compile(r"^File"))
    file_menu.wait_for(state="visible", timeout=30000)
    file_menu.click(force=True)
    load_row = page.get_by_role("button", name="Load dataflow", exact=True)
    load_row.wait_for(state="visible", timeout=15000)
    with page.expect_file_chooser() as chooser:
        load_row.click()
    chooser.value.set_files(path)


def _open_from_projects(page, base_url: str, name: str) -> str:
    """Open *name* from the projects page: select its card, then Open dataflow."""
    page.goto(f"{base_url}/projects")
    wait_for_projects_page(page, timeout=30000)
    card = project_card(page, name).first
    card.wait_for(state="visible", timeout=30000)
    project_id = card.get_attribute("data-project-id")
    card.click()
    expect(page.locator("h2", has_text=name).first).to_be_visible(timeout=15000)
    page.get_by_role("button", name="Open dataflow", exact=True).click()
    page.wait_for_url(f"**/dataflow/{project_id}", timeout=30000)
    return project_id


def _saved_dataflow(server: str, token: str, project_id: str) -> tuple[str, str, list[str]]:
    """The project's name, its spec's name and its sorted node ids, as the server has them."""
    detail = api_json(f"{server}/api/projects/{project_id}", token)
    dataflow = detail["spec"]["dataflow"]
    return (
        detail["project"]["name"],
        dataflow["name"],
        sorted(node["id"] for node in dataflow["nodes"]),
    )


def test_a_loaded_dataflow_is_saved_as_its_own_and_the_open_one_keeps_its_nodes(
    app_frontend: "FrontendPage", current_server: str, page, tmp_path,
):
    """The reporter's four steps, then both dataflows opened from the projects page."""
    require_project_page()
    require_user_auth()
    session = _enter_open_dataflow(
        page, app_frontend, current_server, username="load_then_save_751",
    )
    token, open_id = session["token"], session["project"]["id"]

    # 1 and 2: File > Load dataflow over the open dataflow, with nothing unsaved.
    upload_workflow(
        page, app_frontend,
        _write(tmp_path, "tree-canopy-by-block.json", _spec(FILE_NAME, FILE_IDS)),
        len(FILE_IDS),
    )
    _expect_canvas(page, FILE_IDS, FILE_NAME)

    # 3: save it.
    saved = save_dataflow(page)

    # 4: the projects page lists it, under the name it has in the file.
    page.goto(f"{app_frontend.base_url}/projects")
    wait_for_projects_page(page, timeout=30000)
    project_card(page, OPEN_NAME).first.wait_for(state="visible", timeout=30000)
    listed = project_card(page, FILE_NAME).count()
    assert listed == 1, (
        f"#751: the projects page lists {listed} dataflow(s) named {FILE_NAME!r} "
        f"after it was loaded from a file and saved; the save went to "
        f"{saved.get('name')!r} ({saved.get('id')}), the dataflow open before the load "
        f"is {open_id}"
    )
    assert saved.get("name") == FILE_NAME and saved.get("id") != open_id, saved

    # Opened from there, it is the file's dataflow.
    file_id = _open_from_projects(page, app_frontend.base_url, FILE_NAME)
    assert file_id != open_id
    _expect_canvas(page, FILE_IDS, FILE_NAME)
    assert _saved_dataflow(current_server, token, file_id) == (
        FILE_NAME, FILE_NAME, sorted(FILE_IDS),
    )

    # And the dataflow that was open keeps its own nodes and its name.
    assert _open_from_projects(page, app_frontend.base_url, OPEN_NAME) == open_id
    _expect_canvas(page, OPEN_IDS, OPEN_NAME)
    assert _saved_dataflow(current_server, token, open_id) == (
        OPEN_NAME, OPEN_NAME, sorted(OPEN_IDS),
    ), "the dataflow open before the load no longer holds its own nodes and name"


def test_loading_over_unsaved_changes_asks_before_leaving_them(
    app_frontend: "FrontendPage", current_server: str, page, tmp_path,
):
    """Load dataflow leaves the open dataflow, so it asks first, like File > New."""
    require_project_page()
    require_user_auth()
    session = _enter_open_dataflow(
        page, app_frontend, current_server, username="load_over_unsaved_751",
    )
    token, open_id = session["token"], session["project"]["id"]
    file_path = _write(tmp_path, "tree-canopy-by-block.json", _spec(FILE_NAME, FILE_IDS))

    # An unsaved change: a rename on the canvas.
    renamed = f"{OPEN_NAME}, renamed"
    page.locator(TITLE).click()
    box = page.locator("[data-curio-canvas-title] input[type='text']").first
    box.wait_for(state="visible", timeout=10000)
    box.fill(renamed)
    box.press("Enter")
    save_state = page.locator(SAVE_STATE)
    expect(save_state).to_have_attribute("data-curio-save-state", "unsaved", timeout=10000)

    # Loading asks before it leaves them; Stay here keeps everything as it was.
    _pick_file(page, file_path)
    dialog = page.get_by_role("dialog", name=DISCARD_TITLE)
    expect(dialog).to_be_visible(timeout=15000)
    expect(dialog).to_contain_text("Loading a dataflow file discards the changes you have not saved.")
    dialog.get_by_role("button", name="Stay here", exact=True).click()
    expect(dialog).to_have_count(0, timeout=10000)
    _expect_canvas(page, OPEN_IDS, renamed)
    assert f"/dataflow/{open_id}" in page.url, page.url
    expect(save_state).to_have_attribute("data-curio-save-state", "unsaved", timeout=10000)

    # Discard and continue opens the file as a new dataflow, not yet saved.
    _pick_file(page, file_path)
    accept_confirm_dialog(page, title=DISCARD_TITLE, button="Discard and continue")
    _expect_canvas(page, FILE_IDS, FILE_NAME)
    page.wait_for_url("**/dataflow/new", timeout=30000)
    expect(save_state).to_have_attribute("data-curio-save-state", "unsaved", timeout=10000)

    # A loaded file is unsaved work too: loading another over it asks again,
    # and the second file takes its place.
    _pick_file(
        page,
        _write(tmp_path, "bus-stops-by-route.json", _spec(SECOND_FILE_NAME, SECOND_FILE_IDS)),
    )
    accept_confirm_dialog(page, title=DISCARD_TITLE, button="Discard and continue")
    _expect_canvas(page, SECOND_FILE_IDS, SECOND_FILE_NAME)

    # The dataflow that was open never received the file's nodes.
    _, _, node_ids = _saved_dataflow(current_server, token, open_id)
    assert node_ids == sorted(OPEN_IDS), node_ids
