"""Playwright: a node that hits ModuleNotFoundError says what to install (#299).

Before this, running a node whose code imported something the interpreter did
not have produced a raw traceback and nothing else. Everything needed to fix it
already existed - the import-name to PyPI-name table, the pip runner, the
per-user library record, and the route the Installed-libraries modal calls - so
the gap was only that nobody joined them up at the point of failure.

**Offline by construction, except where it says otherwise.** The first three
tests never reach PyPI: the module they import does not exist and is not meant
to, and pip's two failure answers are staged deterministically through
``/api/testing/pip-behaviour`` - which exists precisely because "pip itself
failed" and "the spec was rejected" cannot be provoked from outside the process
that runs pip. So the whole chain - detect, offer, call the real route, report
pip's verdict honestly - is proven with no network.

The one test that does install for real is marked and skips when the index is
unreachable. It uses ``humanize``: ``inflection`` (test_library_install_integration)
and ``titlecase`` (test_library_manager_e2e) are taken, and those modules'
docstrings say that separation is deliberate so the three cannot poison each
other's negative control.

NOT repeat-safe within one server session. The real-install test leaves the
library importable in the still-running sandbox, so its negative control cannot
be re-armed; it skips rather than fails when it finds that state. Restart the
servers to re-run it.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_missing_module_install_e2e.py -v
"""
from __future__ import annotations

import re
import time
import urllib.error

import pytest
from playwright.sync_api import expect

from .test_library_install_integration import library_teardown  # noqa: F401
from .utils import (
    SandboxRuns,
    _wait_for_reactflow_ready,
    api_json,
    install_session_cookie,
    play_node,
    read_node_output_text,
    require_owner_view,
    require_project_page,
    require_user_auth,
    stub_db_user,
    wait_for_node_done,
    wait_for_node_settled,
)

USERNAME = "missingmodule"
USER_NAME = "Missing Module User"

NODE_ID = "missing-module-node"

#: Absent on purpose and never installable, so the offline tests can never
#: accidentally reach an index. The name is not a real project.
ABSENT_MODULE = "curio_e2e_absent_lib"

#: Pure Python, no dependencies, and absent from the sandbox's _globals_cache -
#: anything in that cache is already in sys.modules for the sandbox's lifetime
#: and could never demonstrate a fresh import. Deliberately a third library, so
#: this cannot poison the two sibling modules' negative controls.
REAL_LIB = "humanize"

_NET_FAIL_RE = re.compile(
    r"Could not find a version|Temporary failure in name resolution|ProxyError|"
    r"Network is unreachable|Read timed out|SSLError|No matching distribution",
    re.I,
)


def _node_code(module: str) -> str:
    # The sandbox wraps user code as ``def userCode(arg):`` and the frontend
    # indents it before posting, so the payload arrives pre-indented. worker.py
    # also refuses code mentioning "arg" when no input is wired, and that guard
    # is a plain substring test - any occurrence at all would turn every run
    # into the same misleading error and quietly void these tests.
    code = f"    import {module}\n    return [1]\n"
    assert "arg" not in code, "worker.py refuses code containing 'arg' with no input"
    return code


def _project_spec(module: str) -> dict:
    return {
        "dataflow": {
            "name": "MissingModuleE2E",
            "task": "",
            "nodes": [
                {
                    "id": NODE_ID,
                    "type": "curio.builtin/data-loading",
                    "x": 200, "y": 160,
                    "content": _node_code(module),
                    "in": "DEFAULT", "out": "DEFAULT", "goal": "",
                    "metadata": {"keywords": []},
                },
            ],
            "edges": [],
        }
    }


def _testing_post(current_server: str, path: str, payload: dict) -> dict:
    """The testing blueprint takes no auth; api_json always sends a token."""
    return api_json(
        f"{current_server}/api/testing/{path}", "unused",
        method="POST", payload=payload, timeout=120.0,
    )


@pytest.fixture()
def pip_behaviour(current_server: str):
    """Make this backend's pip fail on purpose, and put it back afterwards."""
    def _set(mode: str) -> None:
        _testing_post(current_server, "pip-behaviour", {"mode": mode})

    yield _set
    _set("normal")


def _open_node_dataflow(page, frontend_server, current_server, module: str):
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    login = stub_db_user(current_server, username=USERNAME, name=USER_NAME)
    token = login["token"]
    install_session_cookie(page, frontend_server, token)

    project = api_json(
        f"{current_server}/api/testing/stub-project", token, method="POST",
        payload={
            "username": USERNAME,
            "name": "Missing Module",
            "spec": _project_spec(module),
        },
    )
    page.goto(f"{frontend_server}/dataflow/{project['id']}")
    page.wait_for_url(f"**/dataflow/{project['id']}", timeout=20000)
    require_owner_view(page)
    _wait_for_reactflow_ready(page)
    return token, project["id"]


def _reply_to(page, token: str, project_id: str, start, *, until_done: bool = False) -> dict:
    """Start the node's run with *start* and return the reply the run got.

    A run stays in the page or goes to the server (a signed-in owner's does):
    the reply is the page's ``/processPythonCode`` answer, or else the step the
    run on the server recorded, which keeps the reply's ``missingModule``. The
    node is then waited for: settled, or with *until_done*, a success.
    """
    answers = []

    def _answer(response) -> None:
        if response.url.endswith("/processPythonCode") and response.request.method == "POST":
            answers.append(response)

    page.on("response", _answer)
    sent = SandboxRuns(page, token, project_id)
    step = None
    try:
        start()
        deadline = time.monotonic() + 120
        while not answers:
            step = next((
                s for s in reversed(sent.new_steps())
                if s["nodeId"] == NODE_ID and s["status"] in ("ok", "error")
            ), None)
            if step is not None:
                break
            assert time.monotonic() < deadline, "the node's run never answered, in the page or on the server"
            page.wait_for_timeout(250)
    finally:
        page.remove_listener("response", _answer)
        sent.stop()
    if until_done:
        wait_for_node_done(page, NODE_ID, timeout_ms=60000)
    else:
        wait_for_node_settled(page, NODE_ID, timeout_ms=60000)
    if answers:
        return answers[-1].json()
    return {
        "output": {"path": step["outputPath"] or ""},
        "stderr": step["stderrTail"] or "",
        "missingModule": step.get("missingModule"),
    }


def _run_the_node(page, token: str, project_id: str) -> dict:
    """Press the node's play control and return the reply its run got.

    ``play_node`` rather than a click of our own: the control is an ``<svg>``
    inside React Flow's transformed viewport, and the helper already owns the
    dispatch that survives that.
    """
    return _reply_to(page, token, project_id, lambda: play_node(page, NODE_ID))


def _notice(page):
    return page.locator(f'[data-curio-missing-module="{ABSENT_MODULE}"]')


class TestMissingModuleNotice:
    """The offline half: detect, offer, and report pip's answer honestly."""

    def test_the_panel_names_the_library_without_hiding_the_traceback(
        self, workflow_page, frontend_server, current_server
    ):
        page = workflow_page
        token, project_id = _open_node_dataflow(page, frontend_server, current_server, ABSENT_MODULE)

        body = _run_the_node(page, token, project_id)

        # The backend's half of the claim.
        assert body["missingModule"], f"no missingModule on a failed run: {body}"
        assert body["missingModule"]["module"] == ABSENT_MODULE
        assert body["missingModule"]["installable"] is True

        # The traceback is still there in full - the notice is additional.
        error_text = read_node_output_text(page, NODE_ID)
        assert "ModuleNotFoundError" in error_text, error_text[:400]
        assert ABSENT_MODULE in error_text

        expect(_notice(page)).to_be_visible(timeout=20000)
        expect(
            page.get_by_role("button", name=f"Install {ABSENT_MODULE}")
        ).to_be_visible(timeout=20000)

    def test_a_pip_failure_is_reported_as_a_pip_failure(
        self, workflow_page, frontend_server, current_server, pip_behaviour
    ):
        page = workflow_page
        token, project_id = _open_node_dataflow(page, frontend_server, current_server, ABSENT_MODULE)
        _run_the_node(page, token, project_id)

        # pip exits non-zero. The route answers 502, and the panel must say so
        # rather than claiming an install that did not happen.
        pip_behaviour("install-error")
        with page.expect_response(
            lambda r: "/api/packages/libraries" in r.url
            and r.request.method == "POST",
            timeout=120000,
        ) as info:
            page.get_by_role("button", name=f"Install {ABSENT_MODULE}").click()
        assert info.value.status == 502, info.value.text()[:300]

        notice = _notice(page)
        expect(notice).to_contain_text("Couldn't install", timeout=20000)
        expect(notice).not_to_contain_text("Installed " + ABSENT_MODULE)
        # And the retry is one click, not a page reload.
        expect(notice.get_by_role("button", name="Try again")).to_be_visible()

    def test_a_rejected_requirement_is_the_callers_mistake_not_an_upstream_one(
        self, workflow_page, frontend_server, current_server, pip_behaviour
    ):
        page = workflow_page
        token, project_id = _open_node_dataflow(page, frontend_server, current_server, ABSENT_MODULE)
        _run_the_node(page, token, project_id)

        # A requirement pip's grammar rejects is a 400, not a 502 - the
        # distinction the route exists to hold, and the panel must not blur it
        # into "pip failed".
        pip_behaviour("spec-error")
        with page.expect_response(
            lambda r: "/api/packages/libraries" in r.url
            and r.request.method == "POST",
            timeout=120000,
        ) as info:
            page.get_by_role("button", name=f"Install {ABSENT_MODULE}").click()
        assert info.value.status == 400, info.value.text()[:300]

        expect(_notice(page)).to_contain_text("Couldn't install", timeout=20000)


def test_installing_from_the_node_panel_then_rerunning_succeeds(
    workflow_page, frontend_server, current_server, library_teardown
):
    """The round trip, for real. Needs PyPI; skips when the index is unreachable.

    The sibling ``test_library_install_integration.py`` owns the claim that pip
    writes into the site-packages the warm sandbox already imports from. This
    one owns the claim that the NODE PANEL reaches the same place: install from
    the failure, run again, succeed - without leaving the canvas.
    """
    page = workflow_page
    token, project_id = _open_node_dataflow(
        page, frontend_server, current_server, REAL_LIB
    )

    # Registered before installing, so a mid-test failure still cleans up.
    library_teardown(token, REAL_LIB)

    # Self-healing pre-clean, so a leaked earlier run cannot make this vacuous.
    try:
        api_json(
            f"{current_server}/api/packages/libraries/python/{REAL_LIB}",
            token, method="DELETE", timeout=300.0,
        )
    except urllib.error.HTTPError:
        pass

    body = _run_the_node(page, token, project_id)
    if not body.get("missingModule"):
        pytest.skip(
            f"{REAL_LIB} is already importable in this sandbox; the negative "
            f"control cannot be re-armed without restarting the servers"
        )
    assert body["missingModule"]["module"] == REAL_LIB

    with page.expect_response(
        lambda r: "/api/packages/libraries" in r.url and r.request.method == "POST",
        timeout=600000,
    ) as info:
        page.get_by_role("button", name=f"Install {REAL_LIB}").click()
    install = info.value
    if install.status == 502 and _NET_FAIL_RE.search(install.text()):
        pytest.skip(f"no PyPI access from the backend: {install.text()[:200]}")
    assert install.status == 201, install.text()[:400]

    notice = page.locator(f'[data-curio-missing-module="{REAL_LIB}"]')
    expect(notice.get_by_role("button", name="Run node")).to_be_visible(timeout=600000)

    # And the same node now runs. This is the whole point: the user never left
    # the canvas and never opened a modal.
    after = _reply_to(
        page, token, project_id,
        lambda: notice.get_by_role("button", name="Run node").click(),
        until_done=True,
    )
    assert after["output"]["path"], (
        f"{REAL_LIB} still not importable after a confirmed install; "
        f"stderr: {after['stderr'][:400]}"
    )
    assert after["missingModule"] is None
