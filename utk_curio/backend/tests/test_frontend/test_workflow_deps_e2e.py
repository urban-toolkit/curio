"""Playwright E2E: loading a dataflow auto-installs the packages it declares.

A dataflow records the catalog packages it depends on in ``dataflow.packages``.
Loading one is supposed to notice the missing ones and install them, so the
nodes it uses actually appear in the palette instead of rendering as unknown
types. That claim spans four boundaries no cheaper layer crosses at once: the
file import, the ``ensureWorkflowDeps`` probe/install pair, the package registry
refresh, and the palette's own filter (installed ∩ project lockfile).

Covered below this level:

* ``test_packages/test_workflow_deps.py`` - the /check and /install routes,
  including the real unstubbed declare → install → probe-clean cycle.
* ``src/tests/hook/useEnsureWorkflowDeps.test.ts`` - when the hook installs,
  what it installs, and its silent-on-check-failure contract.
* ``src/tests/components/projectLoaderTrustedDeps.test.tsx`` - the owner-only
  gate (a shared link must never trigger an install).

What only a browser proves is the end-to-end consequence, which is what this
test asserts.

``curio.example-ui@1`` is the declared package because it has zero python deps,
so no pip runs. Never point this at ``curio.weather@1``,
``ai.urbanlab.uhvi@1`` or ``curio.streetvision@1``: those pull
rasterio/geopandas/torch through a synchronous 30-minute-capped pip call, and the
resulting user-store copy makes every later ``curio start`` re-resolve them.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_workflow_deps_e2e.py -v
"""
from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

import pytest
from playwright.sync_api import expect

from .utils import (
    api_json,
    open_tools_palette,
    require_project_page,
    require_user_auth,
    save_workflow_test_screenshot,
    skip_if_shared_view,
    stub_login_and_enter_workflow,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

PKG_DIR = "curio.example-ui@1"
PKG_ID = "curio.example-ui"


def _dataflow_declaring(pkg_dir: str) -> dict:
    """A minimal importable dataflow that declares one package dependency."""
    return {
        "dataflow": {
            "name": "DeclaredDeps",
            "task": "",
            "nodes": [
                {
                    "id": "declared-deps-node",
                    "type": "curio.builtin/computation-analysis",
                    "x": 400,
                    "y": 300,
                    "content": "return [1]",
                    "in": "DEFAULT",
                    "out": "DEFAULT",
                    "goal": "",
                    "metadata": {"keywords": []},
                }
            ],
            "edges": [],
            "packages": [pkg_dir],
        }
    }


def _installed_package_ids(server: str, token: str) -> set[str]:
    listing = api_json(f"{server}/api/packages", token)["packages"]
    return {p["packageId"] for p in listing}


@pytest.fixture
def uninstall_declared_package(current_server):
    """Remove packages this test installed, through the real DELETE route.

    Mandatory, not hygiene: ``/api/testing/reset-db`` truncates SQL only, while
    ``.curio/users/<id>/packages/`` persists and sqlite recycles user ids from 1.
    Without this, the second run of this file finds the package already in the
    store and skips - a test that silently stops testing after it first passes.

    Non-autouse on purpose: the autouse ``e2e_clean_db`` finalizes *last*, so an
    explicitly-requested fixture still has a valid stub user (and token) to
    authenticate with.
    """
    registered: list[tuple[str, str]] = []  # (token, dirName)

    def register(token: str, dir_name: str) -> None:
        registered.append((token, dir_name))

    yield register

    for token, dir_name in registered:
        try:
            api_json(
                f"{current_server}/api/packages/{dir_name}", token, method="DELETE"
            )
        except Exception as exc:  # noqa: BLE001 - teardown must never mask a failure
            print(f"[teardown] DELETE /api/packages/{dir_name} failed: {exc}")


def _import_dataflow(page, path: str) -> None:
    """Drive File -> Load dataflow with *path*.

    Deliberately not ``utils.upload_workflow``: that helper hides the tools menu
    bar when it finishes, which would take the palette this test asserts on out
    of the DOM.
    """
    page.wait_for_load_state("domcontentloaded")
    file_menu = page.get_by_test_id("file-menu-btn")
    file_menu.wait_for(state="visible", timeout=60000)
    file_menu.click(force=True)  # the ReactFlow pane swallows plain clicks
    load = page.get_by_role("button", name="Load dataflow")
    load.wait_for(state="visible", timeout=15000)
    with page.expect_file_chooser() as chooser:
        # Click the text, not the role: the handler sits on the wrapping
        # dropdown row (same idiom as utils.upload_workflow).
        page.get_by_text("Load dataflow").click()
    chooser.value.set_files(path)
    # The import is applied before ensureWorkflowDeps fires, so a rendered node
    # means the spec landed and the dep flow has started.
    page.wait_for_function(
        "document.querySelectorAll('.react-flow__node').length >= 1",
        timeout=60000,
    )


def test_importing_a_dataflow_installs_its_declared_packages(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
    tmp_path,
    uninstall_declared_package,
):
    require_project_page()
    require_user_auth()

    result = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Deps User",
        username="deps_user",
        project_name="Declared Deps",
    )
    token = result["token"]
    # Register before the install so a mid-test failure still cleans up.
    uninstall_declared_package(token, PKG_DIR)
    skip_if_shared_view(page)

    # Precondition, asserted backend-side so a dirty user store is
    # distinguishable from a browser-timing problem. The store persists across
    # runs while user ids recycle, so a leaked copy would make the whole test
    # vacuous - it would "pass" without ever installing anything.
    before = _installed_package_ids(current_server, token)
    if PKG_ID in before:
        pytest.skip(
            f"{PKG_DIR} is already in this user's store, so the install can't be "
            f"observed. Remove .curio/users/*/packages/{PKG_DIR} and re-run."
        )

    # Guard against ever installing a pip-heavy package by mistake: only the
    # declared coordinate may reach the install endpoint.
    def _only_the_declared_package(route):
        body = route.request.post_data or ""
        if PKG_DIR in body:
            route.continue_()
        else:
            route.abort()

    page.route("**/api/packages/workflow-deps/install", _only_the_declared_package)

    spec_file = tmp_path / "declared-deps.json"
    spec_file.write_text(json.dumps(_dataflow_declaring(PKG_DIR)), encoding="utf-8")

    with page.expect_response(
        lambda r: "/api/packages/workflow-deps/install" in r.url
        and r.request.method == "POST"
        and r.status == 200,
        timeout=60000,
    ) as install_call:
        _import_dataflow(page, str(spec_file))

    assert install_call.value.json()["installedPackages"] == [PKG_DIR]

    # The user-visible signal: a warning while it works, then confirmation.
    notifications = page.get_by_label("Notifications")
    expect(notifications).to_contain_text(f"Installed {PKG_DIR}.", timeout=30000)

    # Backend truth: it really is in the store now.
    after = _installed_package_ids(current_server, token)
    assert PKG_ID in after, (
        f"{PKG_DIR} was reported installed but is absent from GET /api/packages: "
        f"{sorted(after)}"
    )

    # Visual baseline after the auto-install: the imported dataflow on canvas
    # with the newly installed package present.
    save_workflow_test_screenshot(
        page, "workflow-deps-import",
        test_name="test_importing_a_dataflow_installs_its_declared_packages",
    )

    # The point of installing: the package's nodes become usable. The palette
    # filters installed packages by the project lockfile, which the import set
    # from dataflow.packages - so this also proves that ordering held.
    palette = open_tools_palette(page, "packages")
    expect(
        palette.locator(f'[data-pkg-palette-coords~="{PKG_DIR}"]')
    ).to_have_count(1, timeout=30000)


def test_loading_a_dataflow_with_no_declared_packages_installs_nothing(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
    tmp_path,
):
    """The common case must stay silent: no probe toast, no install request."""
    require_project_page()
    require_user_auth()

    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="No Deps User",
        username="nodeps_user",
        project_name="No Declared Deps",
    )
    skip_if_shared_view(page)

    spec = _dataflow_declaring(PKG_DIR)
    spec["dataflow"]["packages"] = []
    spec_file = tmp_path / "no-deps.json"
    spec_file.write_text(json.dumps(spec), encoding="utf-8")

    install_calls: list[str] = []
    page.on(
        "request",
        lambda req: (
            install_calls.append(req.url)
            if "/api/packages/workflow-deps/" in req.url
            else None
        ),
    )

    _import_dataflow(page, str(spec_file))

    # An empty declaration short-circuits in the hook before the probe, so not
    # even /check should be hit.
    assert install_calls == [], f"unexpected workflow-deps traffic: {install_calls}"
    expect(
        page.get_by_label("Notifications").get_by_text(re.compile("installing them now", re.I))
    ).to_have_count(0)
