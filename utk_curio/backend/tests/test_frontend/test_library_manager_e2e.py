"""Playwright E2E: install a Python library from the UI and use it in a node.

The claim under test is the whole point of the Installed-libraries modal: a user
who hits ``ModuleNotFoundError`` can install the missing library without leaving
the canvas, and the node they were already working on then runs. So the test
runs the *same node* twice, once either side of the install, and the negative run
is load-bearing rather than decoration.

Split from ``test_library_install_integration.py`` on purpose. That test is
browser-free and owns the hard part of the claim (pip writes into the
site-packages the long-lived sandbox already imports from, so no restart and no
``importlib.invalidate_caches()`` is needed). This one owns the modal: the form,
the in-flight state, the table row, and the fact that the UI's install reaches
the same interpreter. When both fail, the browser-free one says whether the
process boundary or the front end is at fault.

``titlecase`` is the subject because it is pure Python, has no dependencies, and
is absent from the sandbox's ``_globals_cache`` — anything in that cache
(``pandas``, ``geopandas``, …) is already in ``sys.modules`` for the sandbox's
lifetime and could never demonstrate a fresh import. It is deliberately a
different library from the sibling test's ``inflection`` so the two cannot
poison each other's negative control.

NOT repeat-safe within one server session: teardown pip-uninstalls the library,
but ``sys.modules['titlecase']`` stays warm in the still-running sandbox, so the
negative control cannot be re-armed. The test skips (rather than fails) when it
finds the library already importable. Restart the servers to re-run it.

Really runs pip, so it needs PyPI access, and skips when the index is
unreachable.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_library_manager_e2e.py -v
"""
from __future__ import annotations

import os
import re
import urllib.error
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from playwright.sync_api import expect

from .utils import (
    REPO_ROOT,
    api_json,
    drag_to_canvas,
    play_node,
    read_node_output_text,
    require_project_page,
    require_user_auth,
    save_workflow_test_screenshot,
    set_node_code,
    skip_if_shared_view,
    stub_login_and_enter_workflow,
    wait_for_node_done,
    wait_for_node_settled,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

LIB = "titlecase"
ANALYSIS_TILE = "#step-analysis"
ANALYSIS_TYPE = "curio.builtin/computation-analysis"

SPEC_PLACEHOLDER = "e.g. numpy or scikit-learn==1.4.0"

# One node, dropped clear of the tool rail. Nothing is connected here, so the
# 525x350 spacing rule that governs the multi-node tests does not apply.
POS_NODE = (150, 150)

# ``worker.py`` refuses code that mentions ``arg`` when no input is wired, and
# that guard is a plain substring test — any occurrence at all (even inside a
# word like "large" or "target") would make both runs fail the same way and
# quietly void the test.
MARKER = "CURIO_E2E_TITLE"
NODE_CODE = (
    f"from {LIB} import {LIB}\n"
    f'result = {LIB}("this is a test")\n'
    f'print("{MARKER}", result)\n'
    "return [result]\n"
)
assert "arg" not in NODE_CODE, "worker.py refuses code containing 'arg' with no input"

_NET_FAIL_RE = re.compile(
    r"Could not find a version|Temporary failure in name resolution|ProxyError|"
    r"Network is unreachable|Read timed out|SSLError|No matching distribution",
    re.I,
)


@pytest.fixture
def library_teardown(current_server):
    """Uninstall whatever the test installed, through the real DELETE route.

    Non-autouse on purpose: the autouse ``e2e_clean_db`` finalizes *last*, so an
    explicitly requested fixture still has a live stub user (and a valid token)
    to authenticate with. The route is used rather than a direct pip call because
    it runs in the backend process — the interpreter guaranteed to match the
    sandbox's. The pytest process's ``sys.executable`` is not.
    """
    registered: list[tuple[str, str, int]] = []
    yield lambda token, name, user_id: registered.append((token, name, user_id))

    for token, name, _ in registered:
        try:
            api_json(
                f"{current_server}/api/packages/libraries/python/{name}",
                token,
                method="DELETE",
                timeout=300.0,
            )
        except (urllib.error.URLError, OSError) as exc:  # best-effort
            print(f"[teardown] DELETE library {name} failed: {exc}")

    # reset-db truncates SQL only and sqlite recycles user ids from 1, so a
    # leftover list file would leak into the next test's view.
    base = Path(os.environ.get("CURIO_LAUNCH_CWD", REPO_ROOT))
    for _, _, user_id in registered:
        (base / ".curio" / "users" / str(user_id) / "installed-libraries.json").unlink(
            missing_ok=True
        )


def _open_library_modal(page):
    page.get_by_role("button", name="Data ⏷", exact=True).click(force=True)
    page.get_by_role("button", name="Installed libraries", exact=True).click()
    expect(page.get_by_role("heading", name="Installed libraries")).to_be_visible(
        timeout=10000
    )


def test_install_library_from_ui_then_use_it(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
    library_teardown,
):
    require_project_page()
    require_user_auth()

    page.emulate_media(reduced_motion="reduce")
    session = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Library User",
        username="library_user",
        project_name="Library Install",
    )
    skip_if_shared_view(page)
    token = session["token"]
    user_id = session["user"]["id"]
    # Register before installing, so a mid-test failure still cleans up.
    library_teardown(token, LIB, user_id)

    # 1. A node that needs a library nobody has installed.
    node_id = drag_to_canvas(page, page.locator(ANALYSIS_TILE), at=POS_NODE)
    set_node_code(page, node_id, NODE_CODE)

    play_node(page, node_id)
    status = wait_for_node_settled(page, node_id, node_type=ANALYSIS_TYPE)
    failure_text = read_node_output_text(page, node_id)
    if status == "done":
        pytest.skip(
            f"{LIB} is already importable in the running sandbox, so the "
            f"negative control cannot be armed. Restart the servers (its "
            f"sys.modules entry stays warm after an uninstall) and re-run."
        )
    assert "ModuleNotFoundError" in failure_text, failure_text
    assert LIB in failure_text, failure_text

    # 2. Install it from the modal, without leaving the canvas.
    _open_library_modal(page)
    spec_input = page.get_by_placeholder(SPEC_PLACEHOLDER)
    expect(spec_input).to_be_visible()
    spec_input.fill(LIB)

    add_btn = page.get_by_role("button", name="Add", exact=True)
    expect(add_btn).to_be_enabled()
    try:
        with page.expect_response(
            lambda r: r.url.endswith("/api/packages/libraries")
            and r.request.method == "POST",
            # A real pip run against PyPI; the route's own budget is 300 s.
            timeout=300000,
        ) as install:
            add_btn.click()
    except Exception as exc:  # noqa: BLE001 - turn a hang into a readable failure
        raise AssertionError(f"the install request never completed: {exc}") from None

    response = install.value
    if response.status == 502 and _NET_FAIL_RE.search(response.text()):
        pytest.skip(f"no PyPI access from the backend: {response.text()[:200]}")
    assert response.ok, f"install failed ({response.status}): {response.text()[:800]}"

    report = response.json()
    # A first-ever install is deterministic: _is_satisfied raises
    # PackageNotFoundError, so the lib is installed rather than reported skipped.
    assert report["installed"] == [LIB], report

    # The UI holds "Installing…" for MIN_PROGRESS_MS so the pip-skip path stays
    # visible, so both settled labels are legitimate; neither is "Failed".
    expect(page.get_by_text(re.compile(r"✓ (Already installed|Installed)"))).to_be_visible(
        timeout=30000
    )
    expect(page.get_by_text("⚠ Failed")).to_have_count(0)
    # The table is the durable record, not the transient status pill.
    expect(page.get_by_role("cell", name=LIB, exact=True)).to_be_visible(timeout=20000)

    page.get_by_role("button", name="Close", exact=True).click()
    expect(page.get_by_role("heading", name="Installed libraries")).to_have_count(0)

    # 3. THE POINT: the same node now runs, against the same sandbox process.
    play_node(page, node_id)
    wait_for_node_done(page, node_id, node_type=ANALYSIS_TYPE)
    output = read_node_output_text(page, node_id)
    # And it computed *with* the library rather than merely importing it.
    assert f"{MARKER} This Is a Test" in output, output

    # 4. Server-side truth: the standalone list is its own durable record.
    listing = api_json(f"{current_server}/api/packages/libraries", token)
    assert LIB in listing["standalone"]["python"], listing
    # Visual baseline for a canvas nobody hand-checks otherwise. The semantic
    # assertions above cover what each node computed; this covers what the
    # canvas *looks* like — most usefully that the edge is actually drawn, which
    # a store-level edge assertion cannot see. Compared at the suite's default
    # tolerance (20% of pixels, 30/255 per channel), which is what absorbs the
    # per-run "Saved to file: <timestamp>_<hash>" text in each output box.
    # The helper fitViews first, so baseline and comparison share one viewport,
    # and it writes the baseline on the first run if the file is absent.
    save_workflow_test_screenshot(
        page, "library-manager", test_name="test_install_library_from_ui_then_use_it",
    )

