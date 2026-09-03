"""Playwright E2E: File > Load dataflow says why a file could not be imported.

#238: picking a malformed JSON left the canvas exactly as it was and printed the
parse error to the browser console. Nothing on screen distinguished "that file
is broken" from "the click missed the menu row", so the reporter concluded the
import had silently done nothing.

The assertions here are deliberately about the *toast*, not the console: a
console line is not a user-facing report, and the whole defect was that the two
had been confused. ``dismiss_toasts`` is never called before an assertion in
this module - it erases the evidence.

Run::

    CURIO_TESTING=1 pytest \
        utk_curio/backend/tests/test_frontend/test_dataflow_import_errors_e2e.py -v
"""
from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

import pytest
from playwright.sync_api import expect

from .utils import (
    require_owner_view,
    require_project_page,
    require_user_auth,
    stub_login_and_enter_workflow,
)

if TYPE_CHECKING:
    from .utils import FrontendPage


TOASTS = '[aria-label="Notifications"]'

# A two-node dataflow, enough that a successful load is visibly different from a
# refused one.
VALID_SPEC = {
    "dataflow": {
        "name": "Imported",
        "nodes": [
            {
                "id": "import-1",
                "type": "curio.builtin/data-loading@1",
                "content": "print('one')",
                "x": 0,
                "y": 0,
            },
            {
                "id": "import-2",
                "type": "curio.builtin/data-loading@1",
                "content": "print('two')",
                "x": 400,
                "y": 0,
            },
        ],
        "edges": [],
    }
}


def _enter_dataflow(page, app_frontend, current_server, *, username):
    page.emulate_media(reduced_motion="reduce")
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Import Errors User",
        username=username,
        project_name="ImportErrors",
    )
    require_owner_view(page)
    # 60s, matching ``upload_workflow``: 30s is enough in isolation but not
    # when this file runs behind the rest of the suite on a loaded machine.
    page.wait_for_selector(".react-flow", timeout=60000)


def _pick_file(page, path):
    """Drive File > Load dataflow and hand the chooser *path*."""
    file_menu = page.get_by_role("button", name=re.compile(r"^File"))
    file_menu.wait_for(state="visible", timeout=30000)
    file_menu.click(force=True)

    load_row = page.get_by_role("button", name="Load dataflow", exact=True)
    load_row.wait_for(state="visible", timeout=15000)
    with page.expect_file_chooser() as fc:
        load_row.click()
    fc.value.set_files(str(path))


def _node_count(page) -> int:
    return page.evaluate("document.querySelectorAll('.react-flow__node').length")


def _toast_text(page, timeout: float = 10000) -> str:
    toast = page.locator(f"{TOASTS} .toast").first
    expect(toast).to_be_visible(timeout=timeout)
    return toast.inner_text()


@pytest.fixture()
def canvas(app_frontend: "FrontendPage", current_server: str, page, request):
    require_project_page()
    require_user_auth()
    # One user per test: ``e2e_clean_db`` is autouse but the stub-login helper
    # reuses an existing row, and a shared account would carry a previous
    # test's canvas into this one.
    _enter_dataflow(
        page, app_frontend, current_server,
        username=f"importerr_{abs(hash(request.node.name)) % 10**8}",
    )
    return page


def test_malformed_json_is_reported_and_changes_nothing(canvas, tmp_path):
    """The exact reproduction from the issue."""
    bad = tmp_path / "invalid-dataflow.json"
    bad.write_text("{ this is not valid JSON }", encoding="utf-8")

    before = _node_count(canvas)
    _pick_file(canvas, bad)

    text = _toast_text(canvas)
    assert "not valid JSON" in text, f"unhelpful toast: {text!r}"
    # The parser's own complaint rides along so the user can find the character.
    assert "(" in text and ")" in text, f"no parser detail in toast: {text!r}"
    assert _node_count(canvas) == before, "a refused import must not touch the canvas"


def test_valid_json_that_is_not_a_dataflow_says_so(canvas, tmp_path):
    """Told apart from a syntax error, or the user hunts for one that is not there."""
    not_a_flow = tmp_path / "shopping-list.json"
    not_a_flow.write_text('{"milk": 2, "eggs": 12}', encoding="utf-8")

    before = _node_count(canvas)
    _pick_file(canvas, not_a_flow)

    text = _toast_text(canvas)
    assert "not a Curio dataflow" in text, f"unhelpful toast: {text!r}"
    assert "not valid JSON" not in text, f"misreported as a syntax error: {text!r}"
    assert _node_count(canvas) == before


def test_a_real_dataflow_still_loads(canvas, tmp_path):
    """The negative control: the new gate must not refuse good files."""
    good = tmp_path / "flow.json"
    good.write_text(json.dumps(VALID_SPEC), encoding="utf-8")

    _pick_file(canvas, good)

    canvas.wait_for_function(
        "document.querySelectorAll('.react-flow__node').length >= 2",
        timeout=30000,
    )
    # No error toast: a successful import is silent.
    errors = canvas.locator(f'{TOASTS} [role="alert"]')
    assert errors.count() == 0, f"unexpected error toast: {errors.first.inner_text()}"


def test_a_json_the_os_gave_no_mime_type_for_still_loads(canvas, tmp_path):
    """The Windows path the issue was filed from.

    The old gate was ``file.type === "application/json"`` alone, and Windows
    reports an empty type for ``.json`` whenever nothing is registered for the
    extension. A perfectly good dataflow was refused there, silently, by the
    same branch that refused genuinely wrong files.
    """
    before = _node_count(canvas)

    file_menu = canvas.get_by_role("button", name=re.compile(r"^File"))
    file_menu.wait_for(state="visible", timeout=30000)
    file_menu.click(force=True)
    load_row = canvas.get_by_role("button", name="Load dataflow", exact=True)
    load_row.wait_for(state="visible", timeout=15000)
    with canvas.expect_file_chooser() as fc:
        load_row.click()
    fc.value.set_files({
        "name": "flow.json",
        "mimeType": "",
        "buffer": json.dumps(VALID_SPEC).encode("utf-8"),
    })

    canvas.wait_for_function(
        f"document.querySelectorAll('.react-flow__node').length >= {before + 2}",
        timeout=30000,
    )
    errors = canvas.locator(f'{TOASTS} [role="alert"]')
    assert errors.count() == 0, f"unexpected error toast: {errors.first.inner_text()}"
