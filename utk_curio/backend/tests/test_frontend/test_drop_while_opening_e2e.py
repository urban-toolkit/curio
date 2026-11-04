"""Playwright E2E: a file dropped while a dataflow's link opens lands once it has.

alice owns a dataflow with one node and invited bob to edit it. bob opens its
link. His tab asks for the dataflow, and the dataflow's room names his tab its
role apart from that answer, often first. Until the answer was in, the canvas
was titled "DefaultDataflow" and took drops the owner's way: a file bob
dropped then was refused as the dataflow still opening, with no node and no
import (#1251's e2e met it, and waited for the title to step around it).

The answer is held at the network until his drop is made, so the drop comes
while the dataflow opens on every run. While it opens, the title says so;
once it is in, his file goes his way, as a drop made then would: into his own
Data Catalog, with alice asked to add it, and a Data Loading node of it on
his canvas, beside alice's node, and in the dataflow the server keeps.

Run::

    CURIO_E2E_USE_EXISTING=1 pytest \\
        utk_curio/backend/tests/test_frontend/test_drop_while_opening_e2e.py -v
"""
from __future__ import annotations

import re
import time
from typing import TYPE_CHECKING

from playwright.sync_api import expect

from .test_computed_json_output_e2e import _record_toasts
from .test_data_loading_drop_e2e import _drop_file
from .utils import (
    CANVAS_DROP_TARGET,
    api_json,
    canvas_nodes,
    close_after_routes,
    dataset_widget_state,
    require_project_page,
    require_user_auth,
    stub_db_login,
    stub_db_user,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

OWNER = "opening_owner_e2e"
EDITOR = "opening_editor_e2e"
NAME = "Bus plan"
TITLE = "[data-curio-canvas-title] h1"
#: What the title says while the dataflow is opening.
OPENING = "Opening dataflow…"
#: alice's node, and the node bob's file makes.
LOADED = "curio.builtin/computation-analysis"
LOADER = "curio.builtin/data-loading"
BUS_STOPS = "stop_id,routes\n1,22\n2,29\n3,36\n"
#: What refused a drop while the dataflow opened.
STILL_OPENING = "still opening"


def _spec() -> dict:
    return {
        "name": NAME,
        "dataflow": {
            "name": NAME,
            "nodes": [{"id": "opening-stops", "type": LOADED, "x": 0, "y": 0, "content": "stops = 3\n"}],
            "edges": [],
        },
    }


def _held_load(page, project_id: str) -> list:
    """Hold the read of the dataflow an editor's link falls through to
    (``GET /api/projects/<id>/shared``) until the test lets it go."""
    held: list = []

    def hold(route) -> None:
        held.append(route)

    page.route(re.compile(rf".*/api/projects/{project_id}/shared(\?.*)?$"), hold)
    return held


def _within(page, seconds: float, read, done):
    """What *read* returns once *done* says so, or after *seconds*."""
    deadline = time.monotonic() + seconds
    seen = read()
    while not done(seen) and time.monotonic() < deadline:
        page.wait_for_timeout(500)
        seen = read()
    return seen


def test_a_file_dropped_while_the_link_opens_lands_once_the_dataflow_is_in(
    app_frontend: "FrontendPage", current_server: str, browser,
):
    require_project_page()
    require_user_auth()
    base = app_frontend.base_url
    owner = stub_db_user(
        current_server, username=OWNER, name="Alice", project_name=NAME, project_spec=_spec(),
    )
    project_id, owner_token = owner["project"]["id"], owner["token"]

    def dataflow_nodes() -> list:
        return sorted(
            node.get("type") for node in
            api_json(f"{current_server}/api/projects/{project_id}", owner_token)["spec"]["dataflow"]["nodes"]
        )

    def asked_of_alice() -> list:
        requests = api_json(f"{current_server}/api/dataflows/{project_id}/datasets/requests", owner_token)
        return [(r["datasetId"], r["by"]["name"]) for r in requests["requests"]]

    context = browser.new_context(viewport={"width": 1280, "height": 768}, reduced_motion="reduce")
    held: list = []
    try:
        page = context.new_page()
        stub_db_login(page, frontend_url=base, backend_url=current_server, username=EDITOR, name="Bob")
        api_json(f"{current_server}/api/projects/{project_id}/editors", owner_token,
                 method="POST", payload={"username": EDITOR})
        held = _held_load(page, project_id)
        page.goto(f"{base}/dataflow/{project_id}", timeout=120000)
        page.locator(CANVAS_DROP_TARGET).wait_for(state="visible", timeout=60000)
        asked = _within(page, 60, lambda: len(held), lambda count: count > 0)
        assert asked, "bob's tab never asked for the dataflow its link names"
        # The room names his tab its role apart from the load: here, first.
        try:
            page.locator('[data-curio-room-role="editor"]').wait_for(state="attached", timeout=30000)
        except Exception as exc:  # noqa: BLE001 - said in the test's words
            raise AssertionError("the dataflow's room never named bob's tab its editor") from exc
        _record_toasts(page)
        title_while_opening = page.locator(TITLE).inner_text()

        # He drops a file of his on the canvas while the dataflow opens.
        _drop_file(page, CANVAS_DROP_TARGET, "bus_stops.csv", BUS_STOPS, at=(760, 300))

        # The dataflow comes in.
        held.pop(0).continue_()
        try:
            expect(page.locator(TITLE)).to_have_text(NAME, timeout=60000)
        except AssertionError as exc:
            raise AssertionError("bob's tab never loaded the dataflow its link names") from exc
        on_his_canvas = _within(
            page, 60,
            lambda: sorted(node["nodeType"] for node in canvas_nodes(page)),
            lambda types: LOADER in types,
        )
        his_loaders = [node["id"] for node in canvas_nodes(page) if node["nodeType"] == LOADER]
        his_datasets = [dataset_widget_state(page, node)["value"] for node in his_loaders]
        in_the_dataflow = _within(page, 30, dataflow_nodes, lambda types: LOADER in types)
        asked_for = _within(page, 30, asked_of_alice, lambda asks: len(asks) > 0)
        told = page.evaluate("() => window.__curioToastLog || []")
    finally:
        # A load still held (the test failed before letting it go) goes on,
        # so taking the routes off waits for nothing.
        for route in held:
            try:
                route.continue_()
            except Exception:  # noqa: BLE001 - already let go
                pass
        close_after_routes(context)

    seen = {
        "title while the dataflow opened": title_while_opening,
        "on bob's canvas": on_his_canvas,
        "in the dataflow": in_the_dataflow,
        "his node loads a dataset he imported": [str(value).split(".")[0] for value in his_datasets],
        "alice is asked for that dataset, by bob": asked_for == [(value, "Bob") for value in his_datasets],
        "refused as still opening": [toast for toast in told if STILL_OPENING in toast],
    }
    assert seen == {
        "title while the dataflow opened": OPENING,
        "on bob's canvas": sorted([LOADED, LOADER]),
        "in the dataflow": sorted([LOADED, LOADER]),
        "his node loads a dataset he imported": ["imported"],
        "alice is asked for that dataset, by bob": True,
        "refused as still opening": [],
    }, f"his nodes load {his_datasets}, alice is asked for {asked_for}; bob's tab said {told}"
