"""Playwright E2E: an invited editor's own data waits for the owner, who applies it.

alice owns a dataflow and invited bob to edit it; each has a tab on it. bob
drops a CSV file of his on the canvas: it goes into his own Data Catalog, the
drop makes a Data Loading node that loads it, and alice is asked to add it, so
the node's dataset pill reads WAITING, on her canvas too, and her Data
Catalog drawer shows his request under Waiting for review, on the review card
an install an agent asks for has. She applies it: the dataset is copied into
her Data Catalog and added to her dataflow, bob's pill stops waiting, and his
node loads her copy: with his own copy deleted from his Data Catalog, his run
of the node still loads it.

The frames: bob's node waiting, alice's request under Waiting for review, and
bob's node after she applied it and he ran it.

Run::

    CURIO_E2E_USE_EXISTING=1 pytest \\
        utk_curio/backend/tests/test_frontend/test_editor_data_request_e2e.py -v
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

from playwright.sync_api import expect

from .test_computed_json_output_e2e import _record_toasts
from .test_data_loading_drop_e2e import _drop_file
from .utils import (
    CANVAS_DROP_TARGET,
    api_json,
    canvas_nodes,
    dataset_widget_state,
    node_locator,
    play_node,
    read_node_error_text,
    require_project_page,
    require_user_auth,
    save_node_closeup,
    save_workflow_test_screenshot,
    stub_db_login,
    wait_for_node_run_to_end,
    watch_node_run,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

FRAMES = "editor-data-request"
OWNER = "data_request_owner_e2e"
EDITOR = "data_request_editor_e2e"
#: alice's dataflow, empty, which a tab's title names once the tab loaded it.
NAME = "Bus plan"
TITLE = "[data-curio-canvas-title] h1"
LOADER_TYPE = "curio.builtin/data-loading"
BUS_STOPS = "stop_id,routes\n1,22\n2,29\n3,36\n"
#: A node's dataset pill while the dataset it loads waits for the owner.
WAITING = "[data-curio-waits-for-owner]"
#: The Data Catalog drawer's requests, Waiting for review.
REQUESTS = '[data-curio-dataset-requests="true"]'
DRAWER_ROOT = '[data-curio-dataset-catalog-drawer="true"]'


def _spec() -> dict:
    return {"name": NAME, "dataflow": {"name": NAME, "nodes": [], "edges": []}}


def _open_as(page, base: str, project_id: str, role: str) -> None:
    """Open the dataflow's link and wait for the tab to load it and for its
    room to name this tab's role.

    The room answers apart from the load, and often first. Until the load is
    in, an editor's canvas acts as an owner's: a file dropped then asks the
    owner nothing, and is refused as the dataflow still opening. The dataflow
    is empty, so no node of it says the load is in: its name in the title does.
    """
    page.goto(f"{base}/dataflow/{project_id}", timeout=120000)
    page.locator(CANVAS_DROP_TARGET).wait_for(state="visible", timeout=60000)
    try:
        expect(page.locator(TITLE)).to_have_text(NAME, timeout=60000)
    except AssertionError as exc:
        raise AssertionError(f"the {role}'s tab never loaded the dataflow its link opened") from exc
    try:
        page.locator(f'[data-curio-room-role="{role}"]').wait_for(state="attached", timeout=30000)
    except Exception as exc:  # noqa: BLE001 - said in the test's words
        raise AssertionError(f"the dataflow's room never named this tab its {role}") from exc


def _open_data_catalog(page):
    """The canvas's Data Catalog drawer, open."""
    page.get_by_role("button", name="Data Catalog", exact=True).click()
    root = page.locator(DRAWER_ROOT)
    root.wait_for(state="attached", timeout=15000)
    expect(root).to_have_attribute("aria-hidden", "false", timeout=10000)
    return root


def _requests(server: str, project_id: str, token: str) -> list:
    return api_json(f"{server}/api/dataflows/{project_id}/datasets/requests", token)["requests"]


def test_an_editors_dropped_file_waits_for_the_owner_who_applies_it(
    app_frontend: "FrontendPage", current_server: str, browser,
):
    require_project_page()
    require_user_auth()
    base = app_frontend.base_url
    viewport = {"width": 1280, "height": 768}
    owner_ctx = browser.new_context(viewport=viewport, reduced_motion="reduce")
    editor_ctx = browser.new_context(viewport=viewport, reduced_motion="reduce")
    try:
        owner, editor = owner_ctx.new_page(), editor_ctx.new_page()
        stubbed = stub_db_login(
            owner, frontend_url=base, backend_url=current_server,
            username=OWNER, name="Alice", project_name=NAME, project_spec=_spec(),
        )
        project_id, owner_token = stubbed["project"]["id"], stubbed["token"]
        editor_token = stub_db_login(
            editor, frontend_url=base, backend_url=current_server, username=EDITOR, name="Bob",
        )["token"]
        api_json(f"{current_server}/api/projects/{project_id}/editors", owner_token,
                 method="POST", payload={"username": EDITOR})
        _open_as(owner, base, project_id, "owner")
        _open_as(editor, base, project_id, "editor")

        # bob drops his file on the empty canvas: a Data Loading node that loads it.
        # What his tab tells him is kept, for a drop that makes nothing.
        _record_toasts(editor)
        before = {node["id"] for node in canvas_nodes(editor)}
        _drop_file(editor, CANVAS_DROP_TARGET, "bus_stops.csv", BUS_STOPS, at=(170, 200))
        try:
            editor.wait_for_function(
                "(n) => window.__curio_reactFlow.getNodes().length > n", arg=len(before), timeout=60000,
            )
        except Exception as exc:  # noqa: BLE001 - said in the test's words
            told = editor.evaluate("() => window.__curioToastLog || []")
            raise AssertionError(f"bob's dropped file made no node on alice's dataflow; his tab said {told}") from exc
        [loader] = [node["id"] for node in canvas_nodes(editor) if node["id"] not in before]
        dataset_id = dataset_widget_state(editor, loader)["value"]
        assert str(dataset_id).startswith("imported."), dataset_id

        # It asks alice: one request in her review, and the node's pill waits.
        pill = node_locator(editor, loader).locator(WAITING)
        expect(pill).to_have_text("WAITING", timeout=60000)
        asked = _requests(current_server, project_id, owner_token)
        assert [(r["datasetId"], r["by"]["name"]) for r in asked] == [(dataset_id, "Bob")], asked
        save_node_closeup(editor, FRAMES, loader, test_name="editors-node-waits-for-the-owner", sweep_toasts=True)

        # alice's canvas knows of it: the node bob placed waits there too, and
        # its pill asks her. Her drawer shows his request under Waiting for review.
        theirs = node_locator(owner, loader).locator(WAITING)
        expect(theirs).to_have_text("WAITING", timeout=60000)
        expect(theirs).to_have_attribute("data-tooltip", re.compile("Bob asks you to add"))
        _open_data_catalog(owner)
        requests = owner.locator(REQUESTS)
        expect(requests).to_contain_text("Waiting for review", timeout=30000)
        expect(requests).to_contain_text("Asked by Bob")
        card = requests.get_by_role("group")
        expect(card).to_have_count(1)
        save_workflow_test_screenshot(
            owner, FRAMES, test_name="owners-drawer-waiting-for-review",
            clip_selector=REQUESTS, fit_reactflow=False, sweep_toasts=True,
        )

        # Her Apply copies it into her store and her dataflow: bob's pill stops waiting.
        card.get_by_role("button", name="Apply").click()
        expect(owner.locator(REQUESTS)).to_have_count(0, timeout=60000)
        listed = api_json(f"{current_server}/api/projects/{project_id}", owner_token)["spec"]["dataflow"]
        assert dataset_id in [ref.get("datasetId") for ref in listed.get("datasets") or []], listed.get("datasets")
        expect(node_locator(editor, loader).locator(WAITING)).to_have_count(0, timeout=60000)

        # His node loads her copy: with his own copy deleted from his Data
        # Catalog, his run of the node still loads the file.
        api_json(f"{current_server}/api/datasets/{dataset_id}", editor_token, method="DELETE")
        watch_node_run(editor, loader)
        play_node(editor, loader)
        status = wait_for_node_run_to_end(editor, loader, node_type=LOADER_TYPE)
        assert status == "done", (
            f"bob's run of his node did not load alice's copy: {read_node_error_text(node_locator(editor, loader))}"
        )
        save_node_closeup(editor, FRAMES, loader, test_name="editors-node-after-the-owner-applied", sweep_toasts=True)
    finally:
        owner_ctx.close()
        editor_ctx.close()
