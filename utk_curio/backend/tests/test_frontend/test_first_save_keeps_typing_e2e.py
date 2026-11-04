"""Playwright E2E: what is typed while a dataflow's first save is out reaches it.

File > Save on a canvas never saved makes the dataflow: its create sends the
canvas as it is, and the canvas then binds to the dataflow's doc, which holds
what was sent. Code typed into a node while the create is out is in the editor
alone; it must reach the doc, and so the dataflow the server keeps, once the
canvas binds, though no save sends it.

The create is held at the network until the typing is done, so the typing
lands while it is out on every run.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_first_save_keeps_typing_e2e.py -v
"""
from __future__ import annotations

import re
import time
from typing import TYPE_CHECKING

from .utils import (
    api_json,
    drag_builtin_to_canvas,
    end_routes,
    read_node_code,
    require_owner_view,
    require_project_page,
    require_user_auth,
    set_node_code,
    stub_db_login,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

#: The node's code when File > Save is clicked, and once typed on while the
#: create was out.
SENT = "x = 1\n# typed before the save\nreturn x\n"
TYPED = "x = 1\n# typed before the save\n# typed while the first save was out\nreturn x\n"


def _held_creates(page) -> list:
    """Hold every create of a dataflow (``POST /api/projects``) until the test
    lets it go; anything else goes on."""
    held: list = []

    def hold(route) -> None:
        if route.request.method == "POST":
            held.append(route)
        else:
            route.continue_()

    page.route(re.compile(r".*/api/projects(\?.*)?$"), hold)
    return held


def _server_code(server: str, token: str, project_id: str, node_id: str):
    spec = api_json(f"{server}/api/projects/{project_id}", token)["spec"]
    node = next((n for n in spec["dataflow"]["nodes"] if n["id"] == node_id), None)
    return None if node is None else node.get("content")


def test_typing_while_the_first_save_is_out_reaches_the_dataflow(
    app_frontend: "FrontendPage", current_server: str, page,
):
    require_project_page()
    require_user_auth()
    base = app_frontend.base_url
    page.emulate_media(reduced_motion="reduce")
    session = stub_db_login(
        page, frontend_url=base, backend_url=current_server,
        name="First Save Typist", username="first_save_typist",
    )
    page.goto(f"{base}/dataflow/new")
    require_owner_view(page)
    page.wait_for_selector(".react-flow", timeout=30000)

    node_id = drag_builtin_to_canvas(page, "#tile-computation-analysis", at=(320, 220))
    set_node_code(page, node_id, SENT)

    held = _held_creates(page)
    try:
        page.get_by_role("button", name=re.compile("File")).click(force=True)
        save_btn = page.get_by_role("button", name="Save dataflow", exact=True)
        save_btn.wait_for(state="visible", timeout=10000)
        save_btn.click()
        deadline = time.monotonic() + 30
        while not held:
            assert time.monotonic() < deadline, "File > Save sent no create of the dataflow"
            page.wait_for_timeout(100)

        # The create is out: type on.
        set_node_code(page, node_id, TYPED)
        assert read_node_code(page, node_id) == TYPED
        held[0].continue_()

        page.wait_for_url(re.compile(r".*/dataflow/[0-9a-f-]{36}$"), timeout=60000)
    finally:
        # A create still held (the test failed before letting it go) goes on,
        # so taking the route off waits for nothing.
        for route in held:
            try:
                route.continue_()
            except Exception:  # noqa: BLE001 - already let go
                pass
        end_routes(page)
    project_id = re.search(r"/dataflow/([0-9a-f-]{36})$", page.url).group(1)

    # The canvas binds, and the doc takes what the editor holds. Nothing
    # else sends it: no tab saves a dataflow it is bound to.
    deadline = time.monotonic() + 60
    seen = None
    while time.monotonic() < deadline:
        seen = _server_code(current_server, session["token"], project_id, node_id)
        if seen == TYPED:
            break
        page.wait_for_timeout(500)
    assert seen == TYPED, (
        f"the dataflow the server keeps holds {seen!r} for the node: what was typed while its "
        "first save was out never reached it"
    )
    assert read_node_code(page, node_id) == TYPED, "the editor lost what was typed while the save was out"
