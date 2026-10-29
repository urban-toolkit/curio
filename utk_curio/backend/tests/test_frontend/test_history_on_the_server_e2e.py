"""Playwright E2E: a dataflow's history is the server's, the same for the owner
and the editors the owner invited.

Two browsers, the owner's and an invited editor's, change one dataflow: each
adds a node. Their Provenance drawers list the same versions, and the owner's
File > Save is a version that reaches the editor's open drawer. Then the
owner's Undo in a Map Editor node waits, as on a slow network, while the
editor deletes an edit there: when the Undo reaches the server the node no
longer holds the code it began from, so nothing is undone, and the owner is
told who changed the node.

Every stack with sign-in serves this: there is no switch for it.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from playwright.sync_api import expect

from .test_widget_tags_e2e import _open_tab
from .utils import (
    api_json,
    close_after_routes,
    drag_builtin_to_canvas,
    node_locator,
    require_project_page,
    require_user_auth,
    save_dataflow,
    stub_db_login,
    wait_for_drawer_closed,
)
from .walkthroughs.steps import (
    PROVENANCE_DRAWER,
    PROVENANCE_PANEL,
    await_drawer_at_rest,
    await_provenance_history,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

OWNER, OWNER_NAME = "history_owner_e2e", "History Owner"
EDITOR, EDITOR_NAME = "history_editor_e2e", "History Editor"
LOAD, EDIT = "history-load", "history-edit"

#: The comment lines a Map Editor node's code starts with.
NOTE = (
    "# Map Editor writes this code from its edit list: each edit, in the\n"
    "# order it was made, on the features whose key is one of its ids. It is\n"
    "# written again when the list changes.\n"
)
#: Two removals, of buildings 1 and 2.
TWO_REMOVALS = NOTE + (
    "return curio_edit_features(input_0, [\n"
    '    {"op": "remove", "ids": [1]},\n'
    '    {"op": "remove", "ids": [2]},\n'
    '], key="building_id", layer="input_0")\n'
)


def _spec() -> dict:
    """A data node feeding a Map Editor node with two edits, linked to no map:
    its list is there to switch off, delete and undo."""

    def node(node_id, node_type, x, content, title):
        return {
            "id": node_id, "type": node_type, "x": x, "y": 0, "content": content, "title": title,
            "in": "DEFAULT", "out": "DEFAULT", "goal": "",
            "metadata": {"keywords": [], "packageTemplateLabel": title},
        }

    return {
        "name": "Shared history",
        "dataflow": {
            "name": "Shared history",
            "nodes": [
                node(LOAD, "curio.builtin/data-loading", 0, "", "Buildings"),
                node(EDIT, "curio.builtin/edit-features", 700, TWO_REMOVALS, "Map Editor"),
            ],
            "edges": [
                {"id": f"e-{LOAD}-{EDIT}", "source": LOAD, "target": EDIT, "sourceHandle": "out", "targetHandle": "in"},
            ],
        },
    }


#: Someone of a role, as a chip in the dock's people (the owner's, say).
PERSON = '[role="group"][aria-label="People here"] button[data-collab-role="{}"]'


def _open_as(page, base: str, project_id: str, role: str) -> None:
    """Open the dataflow's link and wait until its room names this tab's role
    (``data-curio-room-role``), with the canvas bound to the dataflow's doc.
    Any tab but the owner's also waits for the owner's chip in its dock: the
    owner opens first, so the tab knows who the owner is."""
    page.goto(f"{base}/dataflow/{project_id}", timeout=120000)
    node_locator(page, EDIT).wait_for(timeout=30000)
    try:
        page.locator(f'[data-curio-room-role="{role}"]').wait_for(state="attached", timeout=30000)
        page.wait_for_function("() => !!window.__curio_awareness", timeout=30000)
    except Exception as exc:  # noqa: BLE001 - said in the test's words
        raise AssertionError(f"the dataflow's room never named this tab its {role}, with its doc bound") from exc
    if role == "owner":
        return
    try:
        page.locator(PERSON.format("owner")).first.wait_for(timeout=30000)
    except Exception as exc:  # noqa: BLE001 - said in the test's words
        raise AssertionError(f"the {role}'s dock never showed the owner") from exc


def _open_versions(page):
    page.get_by_role("button", name="View menu", exact=True).click()
    page.get_by_test_id("provenance-menu-item").click()
    panel = page.locator(PROVENANCE_PANEL)
    panel.wait_for(state="visible", timeout=20000)
    await_drawer_at_rest(page)
    await_provenance_history(page)
    return panel


def _close_versions(page) -> None:
    page.get_by_role("button", name="Close Dataflow provenance", exact=True).click()
    wait_for_drawer_closed(page, PROVENANCE_DRAWER)


#: The versions a drawer lists, top to bottom: each one's id and title.
_VERSIONS_JS = """(sel) => Array.from(document.querySelectorAll(sel + ' [data-provenance-item]')).map(
    (el) => [el.dataset.provenanceItem, (el.querySelector('button span:nth-child(3)') || el).textContent])"""


def _versions(page) -> list:
    return page.evaluate(_VERSIONS_JS, PROVENANCE_DRAWER)


def _same_versions(owner, editor, *, at_least: int, timeout: float = 30.0) -> list:
    """The versions both drawers list once they list the same ones, *at_least*
    of them: each drawer reads the server's history again on every change."""
    deadline = time.time() + timeout
    mine, theirs = _versions(owner), _versions(editor)
    while time.time() < deadline:
        mine, theirs = _versions(owner), _versions(editor)
        if mine == theirs and len(mine) >= at_least:
            return mine
        owner.wait_for_timeout(250)
    raise AssertionError(f"the two drawers list different versions:\nowner: {mine}\neditor: {theirs}")


def _invite(backend: str, project_id: str, token: str) -> None:
    api_json(f"{backend}/api/projects/{project_id}/editors", token, method="POST", payload={"username": EDITOR})


def test_two_browsers_list_the_same_versions_and_the_owners_save_reaches_the_editor(
    app_frontend: "FrontendPage", current_server: str, browser,
):
    require_project_page()
    require_user_auth()
    base = app_frontend.base_url
    viewport = {"width": 1280, "height": 768}
    owner_ctx = browser.new_context(viewport=viewport)
    editor_ctx = browser.new_context(viewport=viewport)
    try:
        owner, editor = owner_ctx.new_page(), editor_ctx.new_page()
        stubbed = stub_db_login(
            owner, frontend_url=base, backend_url=current_server, username=OWNER, name=OWNER_NAME,
            project_name="Shared history", project_spec=_spec(),
        )
        project_id, token = stubbed["project"]["id"], stubbed["token"]
        stub_db_login(editor, frontend_url=base, backend_url=current_server, username=EDITOR, name=EDITOR_NAME)
        _invite(current_server, project_id, token)
        _open_as(owner, base, project_id, "owner")
        _open_as(editor, base, project_id, "editor")

        # Each adds a node, which reaches the other's canvas.
        by_owner = drag_builtin_to_canvas(owner, "#tile-computation-analysis", at=(300, 450))
        node_locator(editor, by_owner).wait_for(timeout=15000)
        by_editor = drag_builtin_to_canvas(editor, "#tile-computation-analysis", at=(700, 450))
        node_locator(owner, by_editor).wait_for(timeout=15000)

        # The loaded dataflow's four versions (no node, the two nodes, their
        # connection), then the two nodes added: the same versions in both
        # drawers.
        _open_versions(owner)
        _open_versions(editor)
        listed = _same_versions(owner, editor, at_least=6)
        added = [title for _version, title in listed if title.startswith("Node added")]
        assert len(added) == 4, f"the drawers list {listed}: not the two loaded nodes and the two added"

        # The owner's File > Save is a version, and it reaches the editor's
        # drawer, open all along.
        _close_versions(owner)
        save_dataflow(owner)
        saved = editor.locator(f"{PROVENANCE_DRAWER} [data-provenance-item]", has_text="Saved")
        expect(saved).to_have_count(1, timeout=20000)
        _open_versions(owner)
        after = _same_versions(owner, editor, at_least=len(listed) + 1)
        assert [version for version, _title in after[:len(listed)]] == [version for version, _title in listed], (
            f"the save changed the versions before it: {listed} -> {after}"
        )
        assert [title for _version, title in after[len(listed):]].count("Saved") == 1, after
    finally:
        close_after_routes(owner_ctx)
        close_after_routes(editor_ctx)


def test_an_undo_after_another_persons_edit_is_refused_and_says_who_changed_the_node(
    app_frontend: "FrontendPage", current_server: str, browser,
):
    require_project_page()
    require_user_auth()
    base = app_frontend.base_url
    viewport = {"width": 1280, "height": 768}
    owner_ctx = browser.new_context(viewport=viewport)
    editor_ctx = browser.new_context(viewport=viewport)
    try:
        owner, editor = owner_ctx.new_page(), editor_ctx.new_page()
        stubbed = stub_db_login(
            owner, frontend_url=base, backend_url=current_server, username=f"{OWNER}_undo", name=OWNER_NAME,
            project_name="Shared history", project_spec=_spec(),
        )
        project_id, token = stubbed["project"]["id"], stubbed["token"]
        stub_db_login(editor, frontend_url=base, backend_url=current_server, username=EDITOR, name=EDITOR_NAME)
        _invite(current_server, project_id, token)
        _open_as(owner, base, project_id, "owner")
        _open_as(editor, base, project_id, "editor")
        for page in (owner, editor):
            _open_tab(page, EDIT, "output")
        mine, theirs = node_locator(owner, EDIT), node_locator(editor, EDIT)
        expect(mine.locator('[data-edit-list="2"]')).to_have_count(1, timeout=20000)

        # The owner switches the first edit off: an entry of the node's
        # history, which Undo walks back.
        mine.get_by_label("Use edit 1").click()
        undo = mine.get_by_test_id("interaction-undo")
        expect(undo).to_be_enabled(timeout=20000)

        # The owner's Undo waits on the way, as on a slow network.
        held = []
        owner.route(f"**/api/projects/{project_id}/history/nodes/{EDIT}/code", lambda route: held.append(route))
        undo.click()
        deadline = time.time() + 15
        while not held and time.time() < deadline:
            owner.wait_for_timeout(100)
        assert held, "the owner's Undo never asked the server"

        # Meanwhile the editor deletes the second edit, which reaches the owner.
        theirs.get_by_label("Delete edit 2").click()
        expect(theirs.locator('[data-edit-list="1"]')).to_have_count(1, timeout=15000)
        expect(mine.locator('[data-edit-list="1"]')).to_have_count(1, timeout=15000)

        # The Undo reaches the server now: the node holds the editor's code,
        # not the one the Undo began from, so nothing is undone.
        with owner.expect_response(lambda r: r.url.endswith(f"/history/nodes/{EDIT}/code")) as answered:
            held[0].continue_()
        assert answered.value.status == 409, answered.value.text()
        expect(owner.get_by_text(f"{EDITOR_NAME} changed this node after; nothing was undone.")).to_be_visible(
            timeout=10000,
        )
        owner.wait_for_timeout(1000)
        for page_node in (mine, theirs):
            expect(page_node.locator('[data-edit-list="1"]')).to_have_count(1)
        spec = api_json(f"{current_server}/api/projects/{project_id}", token)["spec"]
        code = next(n for n in spec["dataflow"]["nodes"] if n["id"] == EDIT)["content"]
        assert '"ids": [2]' not in code and '"ids": [1]' in code, f"the editor's deletion did not stay:\n{code}"
        versions = api_json(f"{current_server}/api/projects/{project_id}/history", token)["versions"]
        assert not [v for v in versions if v.get("kind") == "code"], f"a refused Undo made a version: {versions}"
    finally:
        close_after_routes(owner_ctx)
        close_after_routes(editor_ctx)
