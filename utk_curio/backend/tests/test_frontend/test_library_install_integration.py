"""Does a library installed through the UI's endpoint become importable by a node?

Stack-level, browser-free. It lives in ``test_frontend/`` only to reuse the
``curio_servers`` / ``current_server`` / ``sandbox_server`` fixtures - it requests
no ``page``, so there is no Playwright, no Chromium and no DOM involved.

The claim is not obvious. User Python runs via ``exec()`` **in-process** inside
the long-lived sandbox Flask process, against a warm ``sys.modules``
(``worker.py`` ``execute_code``), and there is no ``importlib.invalidate_caches()``
anywhere in the tree. It works only because the backend and the sandbox are
launched from the same ``sys.executable`` (``main.py``), so pip writes into the
site-packages the sandbox already imports from, and CPython's ``FileFinder``
invalidates its directory listing when the directory mtime changes.
``useEnsureWorkflowDeps`` states the contract in prose - "nodes executed before
it finishes fail with a normal ModuleNotFoundError and succeed on re-run" - and
nothing enforced it.

Isolating it from the UI is deliberate: when the browser-level version of this
flow fails, this test says immediately whether the process boundary or the front
end is at fault.

``inflection`` is the subject because it is pure Python with no dependencies and
is absent from the sandbox's ``_globals_cache``. Anything in that cache
(``pandas``, ``geopandas``, the DuckDB helpers, …) is already in ``sys.modules``
for the sandbox's lifetime and could never demonstrate a fresh import.

NOT repeat-safe: teardown pip-uninstalls the library, but
``sys.modules['inflection']`` stays warm in the still-running sandbox, so the
negative control cannot be re-armed within one server session. Restart the
servers between runs.

This test really runs pip, so it needs network access to PyPI. It skips rather
than fails when the index is unreachable.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_library_install_integration.py -v
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
from pathlib import Path

import pytest

from .utils import REPO_ROOT, api_json, load_artifact_as_dict, require_user_auth

LIB = "inflection"

# The sandbox wraps user code as ``def userCode(arg):`` and the frontend indents
# it before posting, so the payload arrives pre-indented.
#
# ``worker.py`` also refuses code that mentions ``arg`` when no input is wired,
# and that guard is a plain substring test - any occurrence at all (even inside
# a word like "large" or "target") would turn both runs into the same misleading
# error and quietly void this test.
PY_CODE = (
    "    import inflection\n"
    "    return [inflection.camelize('hello_world')]\n"
)
assert "arg" not in PY_CODE, "worker.py refuses code containing 'arg' with no input"

_NET_FAIL_RE = re.compile(
    r"Could not find a version|Temporary failure in name resolution|ProxyError|"
    r"Network is unreachable|Read timed out|SSLError|No matching distribution",
    re.I,
)


def _stub_token(backend_url: str, username: str) -> tuple[int, str]:
    """A user id + bearer token, with no browser involved."""
    body = api_json(
        f"{backend_url}/api/testing/stub-login",
        token="",
        method="POST",
        payload={"username": username, "name": "Library Integration"},
    )
    return body["user"]["id"], body["token"]


def _exec_python(sandbox_url: str, code: str) -> dict:
    """POST user code to the sandbox the way /processPythonCode does."""
    return api_json(
        f"{sandbox_url}/exec",
        token="",
        method="POST",
        payload={
            "code": code,
            "file_path": "",
            "nodeType": "curio.builtin/computation-analysis",
            "dataType": "",
            "save_dataset": False,
        },
        timeout=120.0,
    )


def _delete_library(backend_url: str, token: str, name: str) -> None:
    try:
        api_json(
            f"{backend_url}/api/packages/libraries/python/{name}",
            token,
            method="DELETE",
            timeout=300.0,
        )
    except (urllib.error.URLError, OSError) as exc:  # best-effort
        print(f"[teardown] DELETE library {name} failed: {exc}")


@pytest.fixture
def library_teardown(current_server):
    """Uninstall whatever the test installed, through the real DELETE route.

    Non-autouse on purpose: the autouse ``e2e_clean_db`` finalizes *last*, so an
    explicitly requested fixture still has a live stub user (and a valid token)
    to authenticate with. The route is used rather than a direct pip call because
    it runs in the backend process - the interpreter guaranteed to match the
    sandbox's. The pytest process's ``sys.executable`` is not.
    """
    registered: list[tuple[str, str]] = []  # (token, library name)
    user_ids: set[int] = set()

    def register(token: str, name: str, user_id: int) -> None:
        registered.append((token, name))
        user_ids.add(user_id)

    yield register

    for token, name in registered:
        _delete_library(current_server, token, name)

    # reset-db truncates SQL only and sqlite recycles user ids from 1, so a
    # leftover list file would leak into the next test's view.
    base = Path(os.environ.get("CURIO_LAUNCH_CWD", REPO_ROOT))
    for uid in user_ids:
        (base / ".curio" / "users" / str(uid) / "installed-libraries.json").unlink(
            missing_ok=True
        )


def test_installed_library_becomes_importable_by_the_sandbox(
    current_server, sandbox_server, library_teardown
):
    require_user_auth()

    user_id, token = _stub_token(current_server, "lib_integration_user")
    # Register before installing, so a mid-test failure still cleans up.
    library_teardown(token, LIB, user_id)

    # Self-healing pre-clean: remove_library_route pip-uninstalls whenever no
    # installed package declares the lib, even for a spec that was never added -
    # so a leaked earlier run cannot make this one vacuous.
    _delete_library(current_server, token, LIB)

    # 1. Negative control. The failure contract is an EMPTY output path; a
    #    non-empty stderr on its own is not failure (warnings land there too).
    before = _exec_python(sandbox_server, PY_CODE)
    assert before["output"]["path"] == "", (
        f"{LIB} was importable before installing it - a previous run leaked it "
        f"into this interpreter. Run `pip uninstall {LIB}` and retry."
    )
    assert "ModuleNotFoundError" in before["stderr"], before["stderr"][:400]
    assert LIB in before["stderr"]

    # 2. Install through the same endpoint the Installed-libraries modal calls.
    try:
        report = api_json(
            f"{current_server}/api/packages/libraries",
            token,
            method="POST",
            payload={"kind": "python", "spec": LIB},
            timeout=300.0,
        )
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        if exc.code == 502 and _NET_FAIL_RE.search(detail):
            pytest.skip(f"no PyPI access from the backend: {detail[:200]}")
        raise AssertionError(f"library install failed ({exc.code}): {detail[:800]}")

    # A first-ever install is deterministic: _is_satisfied raises
    # PackageNotFoundError, so the lib is installed rather than reported skipped.
    assert report["installed"] == [LIB], report
    assert report["skipped"] == [], report
    assert report["standalone"]["python"] == [LIB], report

    # 3. The same node code now succeeds - with no sandbox restart in between.
    after = _exec_python(sandbox_server, PY_CODE)
    assert after["output"]["path"], (
        f"{LIB} still not importable after a confirmed install. The sandbox's "
        f"in-process exec() may need importlib.invalidate_caches().\n"
        f"stderr: {after['stderr'][:600]}"
    )
    assert "ModuleNotFoundError" not in after["stderr"]

    # 4. And it computed *with* the library, not merely imported it.
    artifact = load_artifact_as_dict(after["output"]["path"])
    assert "HelloWorld" in json.dumps(artifact), artifact

    # 5. Persistence: the standalone list is its own durable record.
    listing = api_json(f"{current_server}/api/packages/libraries", token)
    assert LIB in listing["standalone"]["python"], listing


def test_js_library_install_is_rejected_by_the_stack(current_server):
    """JS install is unimplemented, and the running server agrees.

    ``test_libraries.py`` asserts the 501 through the Flask test client; this
    asserts it against the real process, where a stray npm subprocess or a
    partial write would actually show up.
    """
    require_user_auth()
    _, token = _stub_token(current_server, "lib_js_reject_user")

    before = api_json(f"{current_server}/api/packages/libraries", token)

    try:
        api_json(
            f"{current_server}/api/packages/libraries",
            token,
            method="POST",
            payload={"kind": "js", "spec": "lodash"},
        )
    except urllib.error.HTTPError as exc:
        assert exc.code == 501, exc.code
        assert "not yet supported" in exc.read().decode("utf-8", "replace")
    else:
        pytest.fail("JS library install unexpectedly succeeded")

    after = api_json(f"{current_server}/api/packages/libraries", token)
    assert after["standalone"]["js"] == before["standalone"]["js"]
    assert "lodash" not in after["standalone"]["js"]
