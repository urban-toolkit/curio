"""Playwright E2E: a dataflow the page left while it opened keeps nothing of its late answer.

The canvas opens the dataflow its route names, and before that load is in,
File > Load puts a file on the canvas as a new dataflow, which File > Save
makes. When the first dataflow's answer came after that, the canvas took it as
the dataflow it is on: its runs went to the first dataflow, whose server copy
holds none of the canvas's nodes, and were refused with "node '...' is not in
the dataflow" while the URL, the room and the doc stayed on the second. That
is how run 42191681614 (attempt 1) failed two ``test_workflows`` tests: the
stub dataflow's load took 11 s to answer while ``loaded_workflow`` loaded the
file and the class's first test saved it.

The answer is held at the network until the file is saved, and 11 s at least,
so on every run it comes after the save. Then the node is played: it runs on
the dataflow the route names, and the title is the file's all along.

Run::

    CURIO_E2E_USE_EXISTING=1 pytest \\
        utk_curio/backend/tests/test_frontend/test_left_while_opening_e2e.py -v
"""
from __future__ import annotations

import json
import re
import time
from typing import TYPE_CHECKING

from playwright.sync_api import expect

from .test_computed_json_output_e2e import _record_toasts
from .test_drop_while_opening_e2e import _within
from .utils import (
    close_after_routes,
    node_locator,
    require_project_page,
    require_user_auth,
    save_dataflow,
    stub_db_login,
    upload_workflow,
    wait_for_node_run_to_end,
    wait_for_run_guard_released,
    watch_node_run,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

USER = "left_while_opening_e2e"
#: The dataflow the route opens first, and the file loaded while it opens.
OPENED_FIRST = "Opened first"
NAME = "Loaded meanwhile"
NODE = "left-while-opening-count"
TITLE = "[data-curio-canvas-title] h1"
#: What the title says while the dataflow is opening.
OPENING = "Opening dataflow…"
#: How long the first dataflow's answer took in run 42191681614.
HELD_FOR_S = 11
#: What the server answers a run of a node its copy of the dataflow lacks.
NOT_IN_THE_DATAFLOW = "is not in the dataflow"
RUN_START = re.compile(r".*/api/projects/([^/?]+)/runs$")


def _file(tmp_path) -> str:
    path = tmp_path / "loaded_meanwhile.json"
    path.write_text(json.dumps({
        "name": NAME,
        "dataflow": {
            "name": NAME,
            "nodes": [{
                "id": NODE, "type": "curio.builtin/python-computation", "x": 0, "y": 0,
                "content": "return 3", "in": "DEFAULT", "out": "DEFAULT", "goal": "",
            }],
            "edges": [],
        },
    }), encoding="utf-8")
    return str(path)


def _held_load(page, project_id: str) -> list:
    """Hold the read of the dataflow the route names (``GET
    /api/projects/<id>``, with its ``?results=last``) until the test lets it go."""
    held: list = []

    def hold(route) -> None:
        if route.request.method != "GET":
            route.continue_()
            return
        held.append(route)

    page.route(re.compile(rf".*/api/projects/{project_id}(\?.*)?$"), hold)
    return held


def _let_go(held: list) -> None:
    """Send every held read on. One the page no longer waits for (a page that
    left the dataflow cancels its read) has nothing to go on to."""
    while held:
        try:
            held.pop(0).continue_()
        except Exception:  # noqa: BLE001 - the page cancelled it
            pass


def _run_start(response) -> bool:
    return response.request.method == "POST" and RUN_START.match(response.url) is not None


def test_a_file_loaded_while_a_dataflow_opens_runs_on_its_own_dataflow(
    app_frontend: "FrontendPage", current_server: str, browser, tmp_path,
):
    require_project_page()
    require_user_auth()
    base = app_frontend.base_url
    context = browser.new_context(viewport={"width": 1280, "height": 768}, reduced_motion="reduce")
    held: list = []
    try:
        page = context.new_page()
        login = stub_db_login(
            page, frontend_url=base, backend_url=current_server,
            username=USER, name="Left While Opening", project_name=OPENED_FIRST,
        )
        first = login["project"]["id"]
        held = _held_load(page, first)
        page.goto(f"{base}/dataflow/{first}", timeout=120000)
        asked = _within(page, 60, lambda: len(held), lambda count: count > 0)
        assert asked, "the canvas never asked for the dataflow its route names"
        asked_at = time.monotonic()
        _record_toasts(page)

        # While it opens, a file is loaded as a new dataflow and saved, as
        # ``loaded_workflow`` and the first test of its class do.
        upload_workflow(page, app_frontend, _file(tmp_path), 1)
        second = save_dataflow(page)["id"]
        page.wait_for_url(f"**/dataflow/{second}", timeout=30000)
        title_while_held = page.locator(TITLE).inner_text()

        # The first dataflow's answer comes now.
        page.wait_for_timeout(max(0.0, HELD_FOR_S - (time.monotonic() - asked_at)) * 1000)
        held_for = time.monotonic() - asked_at
        _let_go(held)
        try:
            expect(page.locator(TITLE)).not_to_have_text(OPENING, timeout=60000)
        except AssertionError:
            pass  # still opening: said by the title below
        title_after = page.locator(TITLE).inner_text()
        route_id = page.url.rstrip("/").rsplit("/", 1)[-1]

        play = node_locator(page, NODE).locator("svg.fa-circle-play")
        play.wait_for(state="visible", timeout=30000)
        wait_for_run_guard_released(page, timeout_ms=60000)
        watch_node_run(page, NODE)
        with page.expect_response(_run_start, timeout=60000) as started:
            play.dispatch_event("click")
        run = started.value
        run_on = RUN_START.match(run.url).group(1)
        ran = wait_for_node_run_to_end(page, NODE, timeout_ms=120000) if run.ok else f"refused ({run.status})"
        told = page.evaluate("() => window.__curioToastLog || []")
    finally:
        # A read still held (the test failed before letting it go) goes on,
        # so taking the routes off waits for nothing.
        _let_go(held)
        close_after_routes(context)

    names = {first: "the first dataflow", second: "the saved file's dataflow"}
    seen = {
        "the route": names.get(route_id, route_id),
        "the title once the file was saved, the first dataflow's answer held": title_while_held,
        "the title once that answer came": title_after,
        "the run went to": names.get(run_on, run_on),
        "the node's run": ran,
        "refused as not in the dataflow": [toast for toast in told if NOT_IN_THE_DATAFLOW in toast],
    }
    assert seen == {
        "the route": "the saved file's dataflow",
        "the title once the file was saved, the first dataflow's answer held": NAME,
        "the title once that answer came": NAME,
        "the run went to": "the saved file's dataflow",
        "the node's run": "done",
        "refused as not in the dataflow": [],
    }, f"the first dataflow's answer was held {held_for:.0f} s; the page said {told}"
