"""Playwright E2E: an invited editor's own package waits for the owner, who applies it.

alice owns a dataflow and invited bob to edit it; each has a tab on it. bob's
store holds a package of his own, which he imported: Bus counts, whose node
imports a module the package ships. He drags its card from his Node Catalog
drawer onto alice's canvas: the drop makes its node at once and asks alice,
so the node's PACKAGE pill reads WAITING. On her canvas, whose account does
not hold the package, the node waits for her review, and her Node Catalog
drawer shows his request under Waiting for review, on the review card an
agent's package install has: the package's name, version, publisher and what
it may do. Her Apply opens the review her own Add opens; she confirms it, and
the package is copied into her store and added to her dataflow: the node on her
canvas becomes the package's node, and bob's pill stops waiting. With his own
copy deleted from his store, his run of the node imports the module from hers.

The frames: bob's node waiting, alice's request under Waiting for review, and
the node on her canvas after she applied it.

Run::

    CURIO_E2E_USE_EXISTING=1 pytest \\
        utk_curio/backend/tests/test_frontend/test_editor_package_request_e2e.py -v
"""
from __future__ import annotations

import io
import json
import re
import zipfile
from typing import TYPE_CHECKING
from urllib.request import Request, urlopen

from playwright.sync_api import expect

from .test_computed_json_output_e2e import _record_toasts
from .utils import (
    CANVAS_DROP_TARGET,
    api_json,
    drag_to_canvas_with_the_mouse,
    node_locator,
    play_node,
    read_node_error_text,
    read_node_output_text,
    require_project_page,
    require_user_auth,
    save_node_closeup,
    save_workflow_test_screenshot,
    stub_db_login,
    wait_for_drawer_closed,
    wait_for_node_run_to_end,
    watch_node_run,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

FRAMES = "editor-package-request"
OWNER = "package_request_owner_e2e"
EDITOR = "package_request_editor_e2e"
#: alice's dataflow, empty, which a tab's title names once the tab loaded it.
NAME = "Bus routes"
TITLE = "[data-curio-canvas-title] h1"
BUS_DIR = "test.bus-counts@1"
BUS_NODE = "test.bus-counts/count@1"
BAR = "header[data-curio-menu-bar]"
NODE_DRAWER = '[data-curio-node-catalog-drawer="true"]'
#: A pill or a card that waits for the owner's review.
WAITING = '[data-curio-waits-for-owner="true"]'
#: The Node Catalog drawer's requests, Waiting for review.
REQUESTS = '[data-curio-package-requests="node"]'
ADD_REVIEW = '[data-curio-add-review="true"]'
#: Where a card from the drawer is dropped, from the canvas's top-left corner:
#: left of the 520 px drawer, under its scrim.
UNDER_THE_SCRIM = (320.0, 220.0)
#: bob's package: one Python node, which imports the module beside it.
BUS_MANIFEST = {
    "id": "test.bus-counts", "version": "1.0.0", "name": "Bus counts", "publisher": "Bob",
    "description": "Counts the buses of a stop.", "license": "MIT", "compatibility": {"major": 1},
    "permissions": [], "dependencies": {"packages": {}, "python": {}, "js": {}},
    "templates": [{
        "id": "count", "label": "Bus count", "category": "computation", "engine": "python", "editor": "code",
        "hasCode": True, "inputPorts": [], "outputPorts": [{"types": ["JSON"], "cardinality": "1"}],
        "source": "sources/count.py",
    }],
}
BUS_FILES = {
    "sources/count.py": "from bus_helpers import buses\nreturn buses()\n",
    "sources/bus_helpers.py": "def buses():\n    return 'buses at the stop: 12'\n",
}


def _spec() -> dict:
    return {"name": NAME, "dataflow": {"name": NAME, "nodes": [], "edges": []}}


def _import_package(server: str, token: str) -> None:
    """Import bob's package into his own store, as Import package does."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(BUS_MANIFEST))
        for name, body in BUS_FILES.items():
            archive.writestr(name, body)
    boundary = "----curioE2EEditorPackage"
    head = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"bus.curio.zip\"\r\n"
        "Content-Type: application/zip\r\n\r\n"
    ).encode()
    tail = f"\r\n--{boundary}--\r\n".encode()
    req = Request(
        f"{server}/api/packages/upload", data=head + buffer.getvalue() + tail, method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urlopen(req, timeout=120) as resp:  # noqa: S310 - the local backend
        assert resp.status == 201, resp.read()[:300]


def _remove_package(server: str, token: str) -> None:
    """Take the package out of the store *token* signs in to: the e2e database
    gives its user ids to later tests, and the stores keep what they hold."""
    try:
        api_json(f"{server}/api/packages/{BUS_DIR}", token, method="DELETE")
    except Exception:  # noqa: BLE001 - a store that does not hold it is already clean
        pass


def _open_as(page, base: str, project_id: str, role: str) -> None:
    """Open the dataflow's link and wait for the tab to load it and for its
    room to name this tab's role. The dataflow is empty, so no node of it says
    the load is in: its name in the title does."""
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


def _open_node_catalog(page):
    """The canvas's Node Catalog drawer, open."""
    page.locator(BAR).get_by_role("button", name="Node Catalog", exact=True).click()
    drawer = page.locator(NODE_DRAWER)
    expect(drawer).to_have_attribute("aria-hidden", "false", timeout=15000)
    return drawer


def _close_node_catalog(page) -> None:
    page.keyboard.press("Escape")
    wait_for_drawer_closed(page, NODE_DRAWER)


def _requests(server: str, project_id: str, token: str) -> list:
    return api_json(f"{server}/api/dataflows/{project_id}/packages/requests", token)["requests"]


def test_an_editors_own_package_waits_for_the_owner_who_applies_it(
    app_frontend: "FrontendPage", current_server: str, browser,
):
    require_project_page()
    require_user_auth()
    base = app_frontend.base_url
    viewport = {"width": 1280, "height": 768}
    owner_ctx = browser.new_context(viewport=viewport, reduced_motion="reduce")
    editor_ctx = browser.new_context(viewport=viewport, reduced_motion="reduce")
    tokens: list[str] = []
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
        tokens = [owner_token, editor_token]
        api_json(f"{current_server}/api/projects/{project_id}/editors", owner_token,
                 method="POST", payload={"username": EDITOR})
        _import_package(current_server, editor_token)
        _open_as(owner, base, project_id, "owner")
        _open_as(editor, base, project_id, "editor")

        # bob drags his package's card onto alice's canvas: its node, at once.
        # What his tab tells him is kept, for a drop that makes nothing.
        _record_toasts(editor)
        drawer = _open_node_catalog(editor)
        card = drawer.locator(f'article[data-pkg-dir="{BUS_DIR}"]')
        expect(card).to_have_count(1, timeout=30000)
        try:
            node = drag_to_canvas_with_the_mouse(editor, card.locator("h3"), at=UNDER_THE_SCRIM)
        except AssertionError as exc:
            told = editor.evaluate("() => window.__curioToastLog || []")
            raise AssertionError(f"bob's drop of his package's card made no node; his tab said {told}") from exc
        _close_node_catalog(editor)

        # It asks alice: one request in her review, and the node's pill waits.
        pill = node_locator(editor, node).locator(WAITING)
        expect(pill).to_have_text(re.compile("WAITING"), timeout=60000)
        asked = _requests(current_server, project_id, owner_token)
        assert [(r["dirName"], r["by"]["name"], r["nodeIds"]) for r in asked] == [(BUS_DIR, "Bob", [node])], asked
        save_node_closeup(editor, FRAMES, node, test_name="editors-node-waits-for-the-owner", sweep_toasts=True)

        # On alice's canvas, whose account does not hold the package, the node
        # waits for her review; her Node Catalog drawer shows his request.
        theirs = node_locator(owner, node)
        expect(theirs).to_contain_text("Bob asks you to add Bus counts to this dataflow", timeout=60000)
        drawer = _open_node_catalog(owner)
        requests = drawer.locator(REQUESTS)
        expect(requests).to_contain_text("Waiting for review", timeout=30000)
        expect(requests).to_contain_text("Asked by Bob")
        request_card = requests.get_by_role("group")
        expect(request_card).to_have_count(1)
        expect(request_card).to_contain_text("Bus counts · v1.0.0 · Bob · from Bob's Node Catalog")
        expect(request_card).to_contain_text("Permissions requested: none")
        save_workflow_test_screenshot(
            owner, FRAMES, test_name="owners-node-catalog-waiting-for-review",
            clip_selector=REQUESTS, fit_reactflow=False, sweep_toasts=True,
        )

        # Her Apply opens the review her own Add opens; she confirms it there.
        request_card.get_by_role("button", name="Apply").click()
        review = owner.locator(ADD_REVIEW)
        expect(review).to_be_visible(timeout=30000)
        expect(review).to_contain_text('Add "Bus counts"')
        with owner.expect_response(
            lambda r: r.url.endswith("/apply") and r.request.method == "POST", timeout=180000,
        ) as applied:
            review.get_by_role("button", name="Add to project", exact=True).click()
        assert applied.value.status == 200, applied.value.text()[:600]
        expect(drawer.locator(REQUESTS)).to_have_count(0, timeout=60000)
        _close_node_catalog(owner)
        # The lockfile as it names its packages itself: the packages route
        # counts in the package of each node on the canvas too.
        dataflow = api_json(f"{current_server}/api/projects/{project_id}", owner_token)["spec"]["dataflow"]
        assert BUS_DIR in (dataflow.get("packages") or []), (
            f"her Apply did not name the package in her lockfile: packages {dataflow.get('packages')!r}, "
            f"dataflow keys {sorted(dataflow)}"
        )
        assert BUS_DIR in [p["dirName"] for p in api_json(f"{current_server}/api/packages", owner_token)["packages"]]

        # The node on her canvas is the package's node now, and bob's stops waiting.
        package_pill = theirs.get_by_role("button", name=f"Open package {BUS_DIR} in Packages palette")
        expect(package_pill).to_have_text("PACKAGE", timeout=60000)
        save_node_closeup(owner, FRAMES, node, test_name="owners-node-after-she-applied", sweep_toasts=True)
        expect(node_locator(editor, node).locator(WAITING)).to_have_count(0, timeout=60000)

        # With his own copy deleted from his store, his run of the node imports
        # the module from hers.
        _remove_package(current_server, editor_token)
        watch_node_run(editor, node)
        play_node(editor, node)
        status = wait_for_node_run_to_end(editor, node, node_type=BUS_NODE)
        assert status == "done", (
            f"bob's run of the node did not import alice's copy: {read_node_error_text(node_locator(editor, node))}"
        )
        assert "buses at the stop: 12" in read_node_output_text(editor, node)
    finally:
        for token in tokens:
            _remove_package(current_server, token)
        owner_ctx.close()
        editor_ctx.close()
