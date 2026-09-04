"""Playwright E2E: pip exiting 0 is not the same as the library working.

A wheel whose native extension cannot load records a perfectly good version, so
``importlib.metadata`` finds it, ``pip_runner._is_satisfied`` returns True, pip
reports "already satisfied" and changes nothing. Every layer above then reads
that as success, and the user meets the failure much later as a node's raw
ImportError, with nothing connecting it to the install that promised otherwise.

That is live on the reference machine right now: ``import rasterio`` raises
``DLL load failed while importing _base`` while pip insists it is installed.

Six user-facing entry points install a package's libraries, and none of them had
E2E coverage for this case - only for the two cases pip DOES report. Each test
below drives one of them to the point where the product makes a claim, and reads
the claim.

Model: ``test_library_manager_js_e2e.py``, not ``test_library_manager_e2e.py``.
That second one really runs pip against PyPI and is not repeat-safe within a
server session. Nothing here touches a network:
``/api/testing/broken-library`` mints a distribution with valid metadata over a
module that raises on import, which is byte-for-byte the shape of the real
failure - and, because the version is satisfied, makes the install path SKIP pip
entirely. Deterministic and offline, which a genuinely broken wheel is not.

Run::

    CURIO_TESTING=1 pytest \\
        utk_curio/backend/tests/test_frontend/test_broken_library_e2e.py -v
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest
from playwright.sync_api import expect

from .utils import (
    api_json,
    require_owner_view,
    require_project_page,
    require_user_auth,
    save_workflow_test_screenshot,
    stub_login_and_enter_workflow,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

LIB = "brokenlib"
#: The wording the real thing uses on Windows. Asserted on, because "the user
#: sees an error" is not the claim - the claim is that they are told which
#: library and why, which is what turns a mystery into a fixable problem.
REASON_FRAGMENT = "DLL load failed while importing _base"

FIXTURE_ID = "curio.e2ebroken"
FIXTURE_DIR = f"{FIXTURE_ID}@1"
FIXTURE_NAME = "Broken Library Fixture"

SPEC_PLACEHOLDER = "e.g. numpy or scikit-learn==1.4.0"
NOTIFICATIONS = "Notifications"


def _fixture_draft(*, imports: str = LIB) -> dict:
    """A one-node package whose source imports *imports*.

    The dependency is DERIVED from this source by the factory, which is the
    same path a user's own node takes - so the fixture cannot declare something
    the product would not have declared for them.
    """
    return {
        "manifest": {
            "id": FIXTURE_ID,
            "version": "1.0.0",
            "createdAt": "2000-01-01T00:00:00Z",
            "name": FIXTURE_NAME,
            "publisher": "Curio E2E",
            "description": "Declares a library that installs and cannot be imported.",
            "license": "MIT",
            "compatibility": {"curioRuntime": ">=0.5.0", "major": 1},
            "permissions": [],
            "dependencies": {"packages": {}, "python": {}, "js": {}},
            "templates": [{
                "id": "broken-demo",
                "label": "Broken Demo",
                "category": "computation",
                "engine": "python",
                "editor": "code",
                "hasCode": True,
                "hasWidgets": False,
                "hasGrammar": False,
                "inputPorts": [],
                "outputPorts": [{"types": ["JSON"], "cardinality": "1"}],
                "source": "sources/broken-demo.py",
            }],
        },
        "sources": {
            "broken-demo": {
                "filename": "broken-demo.py",
                "code": f"import {imports}\n\n\ndef run():\n    return {{}}\n",
            },
        },
    }


def _testing_post(current_server: str, path: str, payload: dict) -> dict:
    """The testing blueprint takes no auth; api_json always sends a token."""
    return api_json(
        f"{current_server}/api/testing/{path}", "unused",
        method="POST", payload=payload, timeout=120.0,
    )


@pytest.fixture()
def broken_library(current_server: str):
    """Stage a library pip is satisfied by and python cannot import.

    Minted inside the backend process, because that is where the question is
    asked: ``pip_runner`` probes in a subprocess of the backend, so the fake has
    to be on that process's ``sys.path`` and its children's ``PYTHONPATH``,
    neither of which a pytest process can reach.
    """
    staged = _testing_post(current_server, "broken-library", {"action": "install"})
    # The premise, measured rather than assumed. If either half stops holding,
    # every test below would be exercising some other bug.
    assert staged["versionSatisfied"] is True, staged
    assert REASON_FRAGMENT in (staged["importError"] or ""), staged
    yield staged
    _testing_post(current_server, "broken-library", {"action": "remove"})


@pytest.fixture()
def catalog_fixture(current_server: str):
    """Publish, then unpublish, a catalog package declaring the broken library.

    The catalog surfaces (the drawer, the catalog page, a dataflow's declared
    packages) install a package rather than a loose library, so there has to be
    a package to install. Published through the product's own route, so what the
    test installs is a real catalog entry rather than a hand-built directory.
    """
    def _token(username: str) -> str:
        return api_json(
            f"{current_server}/api/testing/stub-login", "unused", method="POST",
            payload={"username": username, "name": "Catalog Fixture"},
        )["token"]

    published = api_json(
        f"{current_server}/api/packages/factory/publish-catalog",
        _token("catalog_fixture_publisher"),
        method="POST",
        payload={**_fixture_draft(), "replace": True},
        timeout=120.0,
    )
    yield published["package"]
    try:
        api_json(
            f"{current_server}/api/packages/catalog/{FIXTURE_DIR}",
            _token("catalog_fixture_publisher"), method="DELETE", timeout=60.0,
        )
    except Exception as exc:  # noqa: BLE001 — teardown must not mask a failure
        print(f"[teardown] unpublish {FIXTURE_DIR} failed: {exc}")


@pytest.fixture()
def uninstall_fixture_package(current_server: str):
    """Drop the store copy; the e2e DB recycles user ids and the store does not.

    Without this a later test inherits the package - and therefore inherits an
    "already installed" state that would quietly void its install assertion.
    """
    tokens: list[str] = []
    yield tokens.append
    for token in tokens:
        try:
            api_json(f"{current_server}/api/packages/{FIXTURE_DIR}", token,
                     method="DELETE", timeout=60.0)
        except Exception as exc:  # noqa: BLE001
            print(f"[teardown] DELETE {FIXTURE_DIR} failed: {exc}")


def _enter_canvas(page, app_frontend, current_server, *, username, name,
                  project_name, project_spec=None) -> dict:
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    session = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name=name,
        username=username,
        project_name=project_name,
        project_spec=project_spec,
    )
    require_owner_view(page)
    return session


def _open_libraries_dialog(page):
    page.get_by_role("button", name=re.compile(r"^Data")).click(force=True)
    page.get_by_role("button", name="Installed libraries", exact=True).click()
    dialog = page.get_by_role("dialog").filter(
        has=page.get_by_role("heading", name="Installed libraries", exact=True)
    )
    expect(dialog).to_be_visible(timeout=15000)
    return dialog


def _add_library(page, dialog, spec: str):
    dialog.get_by_placeholder(SPEC_PLACEHOLDER).fill(spec)
    add = dialog.get_by_role("button", name="Add", exact=True)
    expect(add).to_be_enabled()
    with page.expect_response(
        lambda r: r.url.endswith("/api/packages/libraries")
        and r.request.method == "POST",
        timeout=120000,
    ) as posted:
        add.click()
    return posted.value


def _open_node_catalog(page):
    page.get_by_role("button", name=re.compile(r"^Data")).click(force=True)
    page.get_by_role("button", name="Node Catalog", exact=True).click()
    drawer = page.get_by_role("dialog").filter(
        has=page.get_by_role("heading", name="Node Catalog", exact=True)
    )
    expect(drawer).to_be_visible(timeout=20000)
    return drawer


# ---------------------------------------------------------------------------
# 1. The Installed libraries dialog
# ---------------------------------------------------------------------------

def test_the_libraries_dialog_names_the_library_and_the_reason(
    app_frontend: "FrontendPage", current_server: str, page, broken_library,
):
    """The reference case, end to end.

    pip is satisfied by the metadata and SKIPS, so ``installed`` is empty and
    ``skipped`` names the library - which the dialog used to read as
    "✓ Already installed". The user then met the failure the next time a node
    imported it, with nothing tying the two together.
    """
    _enter_canvas(page, app_frontend, current_server,
                  username="brokenlib_dialog", name="Broken Dialog",
                  project_name="BrokenLibDialog")
    dialog = _open_libraries_dialog(page)

    response = _add_library(page, dialog, LIB)

    assert response.ok, f"{response.status}: {response.text()[:400]}"
    body = response.json()
    # The premise at the HTTP layer: pip changed nothing and still succeeded.
    assert body["installed"] == [], body
    assert body["skipped"] == [LIB], body

    # The claim the user reads names the library AND why it does not work.
    expect(dialog.get_by_text(
        re.compile(rf"{LIB} installed, but it cannot be imported")
    )).to_be_visible(timeout=30000)
    expect(dialog.get_by_text(re.compile(REASON_FRAGMENT))).to_be_visible()
    # And it is not simultaneously reported as fine.
    expect(dialog.get_by_text("✓ Already installed")).to_have_count(0)
    expect(dialog.get_by_text("✓ Installed")).to_have_count(0)

    save_workflow_test_screenshot(
        page, "broken-library",
        test_name="test_the_libraries_dialog_names_the_library_and_the_reason",
        fit_reactflow=False,
        clip_selector='[role="dialog"]',
        max_diff_ratio=0.03,
    )


def test_a_working_library_is_still_reported_as_installed(
    app_frontend: "FrontendPage", current_server: str, page,
):
    """The success control, and it is load-bearing.

    A suite that only asserts failures would not notice a fix that shouts at
    everyone. ``flask`` is a base-install dependency, so it is satisfied and
    skipped exactly as the broken one is - the ONLY difference between this test
    and the one above is whether the import works.
    """
    _enter_canvas(page, app_frontend, current_server,
                  username="brokenlib_ok", name="Working Lib",
                  project_name="WorkingLib")
    dialog = _open_libraries_dialog(page)

    response = _add_library(page, dialog, "flask")

    assert response.ok, f"{response.status}: {response.text()[:400]}"
    assert response.json()["skipped"] == ["flask"], response.json()
    expect(dialog.get_by_text("✓ Already installed")).to_be_visible(timeout=30000)
    expect(dialog.get_by_text(re.compile("cannot be imported"))).to_have_count(0)
    expect(dialog.get_by_text(re.compile(r"Couldn't install"))).to_have_count(0)


def test_a_malformed_requirement_is_refused_before_pip_runs(
    app_frontend: "FrontendPage", current_server: str, page,
):
    """400, and a different sentence: this one is the user's typo, not the
    environment's problem, and telling them apart is the whole point of having
    two answers."""
    _enter_canvas(page, app_frontend, current_server,
                  username="brokenlib_spec", name="Bad Spec",
                  project_name="BadSpec")
    dialog = _open_libraries_dialog(page)

    response = _add_library(page, dialog, "not a spec!!")

    assert response.status == 400, f"{response.status}: {response.text()[:400]}"
    expect(dialog.get_by_text(
        re.compile(r"Couldn't install not a spec")
    )).to_be_visible(timeout=30000)
    expect(dialog.get_by_text(
        re.compile(r"is not a Python package name")
    )).to_be_visible()
    # Not the import wording: a name pip never accepted was never installed.
    expect(dialog.get_by_text(re.compile("cannot be imported"))).to_have_count(0)


# ---------------------------------------------------------------------------
# 2. Node Catalog drawer -> add the package to this project
# ---------------------------------------------------------------------------

def test_adding_a_package_to_a_project_reports_its_broken_library(
    app_frontend: "FrontendPage", current_server: str, page,
    broken_library, catalog_fixture, uninstall_fixture_package,
):
    """The package arrives; its library does not work; the toast says so.

    This is the last moment the failure is still attached to the package that
    brought it in. After it, the user meets a node's ImportError.
    """
    session = _enter_canvas(
        page, app_frontend, current_server,
        username="brokenlib_drawer", name="Drawer User",
        project_name="BrokenLibDrawer")
    uninstall_fixture_package(session["token"])

    drawer = _open_node_catalog(page)
    card = drawer.locator(f'article[data-pkg-dir="{FIXTURE_DIR}"]')
    expect(card).to_have_count(1, timeout=20000)

    with page.expect_response(
        lambda r: r.url.endswith("/api/packages/resolve"), timeout=30000
    ):
        card.get_by_role("button", name="Add to project", exact=True).click()

    confirm = page.get_by_role("dialog").filter(
        has=page.get_by_role("heading", name=f'Add "{FIXTURE_NAME}"', exact=True)
    )
    expect(confirm).to_be_visible(timeout=15000)
    with page.expect_response(
        lambda r: "/api/packages/projects/" in r.url
        and r.url.endswith("/install")
        and r.request.method == "POST",
        timeout=120000,
    ) as installed:
        confirm.get_by_role("button", name="Add to project", exact=True).click()

    response = installed.value
    # Not a 5xx and not a rollback: the package installed fine, and the repair
    # for a broken build belongs to the user. Report, do not undo.
    assert response.status == 201, f"{response.status}: {response.text()[:400]}"
    assert response.json()["importErrors"] == {
        LIB: broken_library["importError"],
    }, response.json()

    toasts = page.get_by_label(NOTIFICATIONS)
    expect(toasts).to_contain_text(LIB, timeout=30000)
    expect(toasts).to_contain_text(REASON_FRAGMENT)
    expect(toasts).not_to_contain_text(f"Added {FIXTURE_NAME} to this project.")

    save_workflow_test_screenshot(
        page, "broken-library",
        test_name="test_adding_a_package_to_a_project_reports_its_broken_library",
        fit_reactflow=False,
        clip_selector='[aria-label="Notifications"]',
        max_diff_ratio=0.05,
    )

    # The package really is installed, which is what makes "report, do not undo"
    # a claim rather than a slogan.
    installed_dirs = {
        p["dirName"]
        for p in api_json(f"{current_server}/api/packages", session["token"])["packages"]
    }
    assert FIXTURE_DIR in installed_dirs


# ---------------------------------------------------------------------------
# 3. Node Catalog page -> add the package to every project
# ---------------------------------------------------------------------------

def test_adding_a_package_to_every_project_reports_its_broken_library(
    app_frontend: "FrontendPage", current_server: str, page,
    broken_library, catalog_fixture, uninstall_fixture_package,
):
    """The account-wide install, which said nothing at all.

    The backend answered ``importErrors`` here before this surface read it: the
    page reported how many projects it had patched, which is a different
    question from whether the thing it added to all of them works.
    """
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    session = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Catalog Page User",
        username="brokenlib_page",
        project_name="BrokenLibPage",
    )
    uninstall_fixture_package(session["token"])

    page.goto(f"{app_frontend.base_url}/catalog/nodes")
    page.wait_for_load_state("domcontentloaded")

    # The card on this page carries no account-wide write - selecting it opens
    # the detail drawer, and the install lives there (catalogActionScope #3).
    card = page.locator(f'article[data-pkg-dir="{FIXTURE_DIR}"]')
    expect(card).to_have_count(1, timeout=30000)
    card.click()

    drawer_add = page.get_by_role("button", name="Add to all projects", exact=True)
    expect(drawer_add).to_be_visible(timeout=15000)
    with page.expect_response(
        lambda r: r.url.endswith("/api/packages/resolve"), timeout=30000
    ):
        drawer_add.click()

    confirm = page.get_by_role("dialog").filter(
        has=page.get_by_role("heading", name=f'Add "{FIXTURE_NAME}"', exact=True)
    )
    expect(confirm).to_be_visible(timeout=15000)
    with page.expect_response(
        lambda r: r.url.endswith("/api/packages/defaults")
        and r.request.method == "POST",
        timeout=120000,
    ) as installed:
        confirm.get_by_role("button", name="Add to all projects", exact=True).click()

    response = installed.value
    assert response.status == 201, f"{response.status}: {response.text()[:400]}"
    assert response.json()["importErrors"] == {LIB: broken_library["importError"]}

    toasts = page.get_by_label(NOTIFICATIONS)
    expect(toasts).to_contain_text(LIB, timeout=30000)
    expect(toasts).to_contain_text(REASON_FRAGMENT)


# ---------------------------------------------------------------------------
# 4. Opening a dataflow that declares the package
# ---------------------------------------------------------------------------

def test_opening_a_dataflow_that_declares_it_reports_the_broken_library(
    app_frontend: "FrontendPage", current_server: str, page,
    broken_library, catalog_fixture, uninstall_fixture_package,
):
    """Nobody pressed Install here: the dataflow declared the package and the
    canvas installed it on open. The toast is the only place this is said."""
    spec = {
        "dataflow": {
            "name": "DeclaresBroken",
            "task": "",
            "nodes": [],
            "edges": [],
            "packages": [FIXTURE_DIR],
        }
    }
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")

    # Arm the teardown before the navigation that installs, so a failure part
    # way through still leaves the next test a clean store.
    token = api_json(
        f"{current_server}/api/testing/stub-login", "unused", method="POST",
        payload={"username": "brokenlib_open", "name": "Open User"},
    )["token"]
    uninstall_fixture_package(token)

    with page.expect_response(
        lambda r: r.url.endswith("/api/packages/workflow-deps/install")
        and r.request.method == "POST",
        timeout=120000,
    ) as installed:
        stub_login_and_enter_workflow(
            page,
            frontend_url=app_frontend.base_url,
            backend_url=current_server,
            name="Open User",
            username="brokenlib_open",
            project_name="DeclaresBroken",
            project_spec=spec,
        )

    response = installed.value
    assert response.ok, f"{response.status}: {response.text()[:400]}"
    assert response.json()["importErrors"] == {LIB: broken_library["importError"]}

    toasts = page.get_by_label(NOTIFICATIONS)
    expect(toasts).to_contain_text(LIB, timeout=30000)
    expect(toasts).to_contain_text(REASON_FRAGMENT)


# ---------------------------------------------------------------------------
# 5. Sideloading a .curio.zip
# ---------------------------------------------------------------------------

def test_sideloading_an_archive_reports_its_broken_library(
    app_frontend: "FrontendPage", current_server: str, page, tmp_path,
    broken_library, uninstall_fixture_package,
):
    """A sideload used to write the files and never run pip at all.

    And the follow-up "add to project" could not repair it: that path returns
    early for a package already in the store. So a sideloaded package's
    libraries were nobody's job, and the archive reported a clean 201.
    """
    from utk_curio.backend.app.packages.factory import build_packageage_archive

    archive = tmp_path / "broken.curio.zip"
    archive.write_bytes(build_packageage_archive(_fixture_draft()).archive)

    session = _enter_canvas(
        page, app_frontend, current_server,
        username="brokenlib_upload", name="Upload User",
        project_name="BrokenLibUpload")
    uninstall_fixture_package(session["token"])

    drawer = _open_node_catalog(page)
    with page.expect_response(
        lambda r: r.url.endswith("/api/packages/upload")
        and r.request.method == "POST",
        timeout=120000,
    ) as uploaded:
        with page.expect_file_chooser() as chooser:
            drawer.get_by_role("button", name="Import package").click()
        chooser.value.set_files(str(archive))

    response = uploaded.value
    assert response.status == 201, f"{response.status}: {response.text()[:400]}"
    assert response.json()["importErrors"] == {LIB: broken_library["importError"]}

    toasts = page.get_by_label(NOTIFICATIONS)
    expect(toasts).to_contain_text(LIB, timeout=30000)
    expect(toasts).to_contain_text(REASON_FRAGMENT)


# ---------------------------------------------------------------------------
# 6. Save As -> Save and install
# ---------------------------------------------------------------------------

SAVE_AS_NODE_ID = "broken-save-as-node"
SAVE_AS_NEW = "__save_as_new__"
SAVE_AS_PACKAGE_NAME = "Broken Save As Package"


def _save_as_spec() -> dict:
    return {
        "dataflow": {
            "name": "BrokenSaveAs",
            "task": "",
            "nodes": [{
                "id": SAVE_AS_NODE_ID,
                "type": "curio.builtin/computation-analysis",
                "x": 420,
                "y": 300,
                # The wizard DERIVES dependencies.python from this body.
                "content": f"import {LIB}\nreturn [1]",
                "in": "DEFAULT",
                "out": "DEFAULT",
                "goal": "",
                "metadata": {"keywords": []},
            }],
            "edges": [],
        }
    }


def test_saving_a_node_as_a_package_reports_the_library_its_code_imports(
    app_frontend: "FrontendPage", current_server: str, page, broken_library,
):
    """The sharpest case of the three that never ran pip.

    ``factory._apply_detected_dependencies`` OVERWRITES ``dependencies.python``
    with deps read out of the node's source, so this node body produces a
    manifest declaring the library - and nothing installed it, nothing probed
    it, and "Save and install" reported success over a package whose very first
    run would raise.
    """
    from .utils import _wait_for_reactflow_ready

    _enter_canvas(
        page, app_frontend, current_server,
        username="brokenlib_saveas", name="Save As User",
        project_name="BrokenSaveAs", project_spec=_save_as_spec())

    node = page.locator(f'.react-flow__node[data-id="{SAVE_AS_NODE_ID}"]')
    node.wait_for(state="visible", timeout=60000)
    _wait_for_reactflow_ready(page)
    node.scroll_into_view_if_needed()

    node.get_by_role("button", name=re.compile(r"^Node settings for ")).click()
    page.get_by_role("button", name="Save as package node…").click()

    modal = page.get_by_role(
        "heading", name="Save as package node", level=2,
    ).locator("xpath=..")
    expect(modal).to_be_visible(timeout=15000)
    modal.locator("#save-as-package-target").select_option(SAVE_AS_NEW)
    modal.locator("#save-as-new-package-name").fill(SAVE_AS_PACKAGE_NAME)

    with page.expect_response(
        lambda r: r.url.endswith("/api/packages/factory/install")
        and r.request.method == "POST",
        timeout=120000,
    ) as saved:
        modal.get_by_role("button", name="Save", exact=True).click()

    response = saved.value
    assert response.status == 201, f"{response.status}: {response.text()[:400]}"
    body = response.json()
    # The manifest really did declare it, derived from the node body above.
    assert body["package"]["dependencies"]["python"] == {LIB: "*"}, body["package"]
    assert body["importErrors"] == {LIB: broken_library["importError"]}, body

    toasts = page.get_by_label(NOTIFICATIONS)
    expect(toasts).to_contain_text(LIB, timeout=30000)
    expect(toasts).to_contain_text(REASON_FRAGMENT)
