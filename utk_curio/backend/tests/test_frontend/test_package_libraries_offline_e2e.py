"""Playwright E2E: a package's library installs by itself, offline, on each path that adds the package.

A package declares its libraries (``dependencies.python``); they are never
Curio's own dependencies. They install when the package is added, when a
dataflow whose lockfile names it is opened, or at launch for the packages the
shipped examples declare (``--with-examples``). Each test below adds
``test.wheelhouse-probe@1``, a test package kept beside these tests
(``packages/``), along one path, and checks that the library was not
installed before, that pip installed it, and that the package's node runs and
prints the message the library holds.

Offline by construction: the library is a wheel of a few hundred bytes the
test builds, staged in the backend's own wheelhouse, and the backend's pip
reads that and no index (``PIP_NO_INDEX`` with ``PIP_FIND_LINKS``, as
``test_backend_runtime.py`` installs ``tinylib``). See
``utils/offline_install.py``.

* A node card dragged from the Node Catalog drawer onto the canvas opens the
  Add review, which lists the library; after the confirm the node appears and
  runs. A hosted guest's drop is refused and no node appears: guests never
  install.
* Loading a dataflow whose lockfile names the package adds it, and Run All
  runs its node.
* Add on the Node Catalog page installs the library, and the node dropped from
  the palette runs.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_package_libraries_offline_e2e.py -v
"""
from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING

import pytest
from playwright.sync_api import expect

from .utils import (
    CANVAS_DROP_TARGET,
    TEST_PACKAGES_DIR,
    WHEELHOUSE_PROBE,
    WHEELHOUSE_PROBE_PACKAGE,
    allow_guest_login_env,
    api_json,
    canvas_node_type,
    canvas_nodes,
    close_tools_palette,
    drag_to_canvas,
    drag_with_the_mouse_onto_canvas,
    library_installed,
    node_locator,
    offline_catalog_package,
    open_new_workflow,
    open_tools_palette,
    read_node_output_text,
    require_owner_view,
    require_project_page,
    require_user_auth,
    run_all_and_wait,
    run_node_and_wait,
    save_node_closeup,
    save_workflow_test_screenshot,
    stub_db_login,
    stub_login_and_enter_workflow,
    wait_for_drawer_closed,
    wait_for_projects_page,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

LIB = WHEELHOUSE_PROBE
PKG_DIR = WHEELHOUSE_PROBE_PACKAGE
PKG_NAME = "Wheelhouse Probe"
NODE_TYPE = "test.wheelhouse-probe/probe"
PROBE_CODE = (TEST_PACKAGES_DIR / PKG_DIR / "sources" / "probe.py").read_text(encoding="utf-8")

BAR = "header[data-curio-menu-bar]"
NODE_DRAWER = '[data-curio-node-catalog-drawer="true"]'
CARD = f'article[data-pkg-dir="{PKG_DIR}"]'
ADD_REVIEW = '[data-curio-add-review="true"]'
NOTIFICATIONS = '[aria-label="Notifications"]'
#: Where a card from the drawer is dropped, from the canvas's top-left corner:
#: left of the 520 px drawer, under its scrim.
UNDER_THE_SCRIM = (320.0, 220.0)
#: The frames of the drop: the Add review, and the node after the install.
DROP_STEM = "package-card-drop"

GUEST_REFUSAL = (
    f"Adding {PKG_NAME} is not available for guest users, because every guest shares "
    f"one account. Sign in with an account to add it."
)


@pytest.fixture()
def probe_package(current_server: str):
    """The test package in this backend's catalog, its library only in the wheelhouse."""
    with offline_catalog_package(current_server, PKG_DIR, [LIB]):
        yield


def _username(kind: str) -> str:
    return f"offline_{kind}_{uuid.uuid4().hex[:10]}"


def _enter_canvas(page, app_frontend, current_server, *, kind: str) -> dict:
    require_project_page()
    require_user_auth()
    # Before navigating: the drawers slide in through useSlideDrawerPresentation,
    # which reads prefers-reduced-motion.
    page.emulate_media(reduced_motion="reduce")
    session = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Offline Install User",
        username=_username(kind),
        project_name="Offline install",
    )
    require_owner_view(page)
    _wait_for_canvas(page)
    return session


def _wait_for_canvas(page) -> None:
    page.locator(CANVAS_DROP_TARGET).wait_for(state="visible", timeout=45000)
    page.wait_for_function("() => !!window.__curio_reactFlow", timeout=30000)


def _store_dirs(server: str, token: str) -> list[str]:
    return [p.get("dirName") for p in api_json(f"{server}/api/packages", token)["packages"]]


def _assert_not_added_yet(server: str, token: str) -> None:
    store = _store_dirs(server, token)
    assert PKG_DIR not in store, f"{PKG_DIR} is in this account's store before the test adds it: {store}"
    assert not library_installed(server, LIB), f"{LIB.dist} is installed before the test adds {PKG_DIR}"


def _node_ids(page) -> set[str]:
    return {node["id"] for node in canvas_nodes(page)}


def _new_node(page, before: set[str], *, timeout: float = 30000) -> str:
    page.wait_for_function(
        "(n) => window.__curio_reactFlow.getNodes().length > n", arg=len(before), timeout=timeout,
    )
    created = sorted(_node_ids(page) - before)
    assert len(created) == 1, f"expected one new node, got {created}"
    return created[0]


def _record_package_writes(page) -> list[str]:
    """Every request that could add or install a package, as it is sent."""
    sent: list[str] = []
    page.on(
        "request",
        lambda r: sent.append(f"{r.method} {r.url}")
        if r.method != "GET" and "/api/packages" in r.url else None,
    )
    return sent


def _open_node_catalog_drawer(page):
    page.locator(BAR).get_by_role("button", name="Node Catalog", exact=True).click()
    drawer = page.locator(NODE_DRAWER)
    expect(drawer).to_have_attribute("aria-hidden", "false", timeout=15000)
    return drawer


def _add_review(page):
    return page.get_by_role("dialog").filter(
        has=page.get_by_role("heading", name=f'Add "{PKG_NAME}"', exact=True)
    )


def _assert_lists_the_library(review) -> None:
    expect(review.locator("code", has_text=f"python · {LIB.dist}")).to_be_visible(timeout=10000)
    expect(review.locator("code").filter(has_text=LIB.version)).to_have_count(1)


def _assert_the_node_ran_the_library(page, node_id: str) -> None:
    output = read_node_output_text(page, node_id)
    assert LIB.message in output, f"the node's output does not show {LIB.module} imported: {output!r}"


def _enter_as_hosted_guest(page, base_url: str) -> None:
    page.goto(f"{base_url}/auth/signin")
    page.wait_for_load_state("domcontentloaded")
    page.get_by_text("Continue as Guest").click()
    page.wait_for_url("**/projects", timeout=30000)
    wait_for_projects_page(page, timeout=10000)
    open_new_workflow(page)
    _wait_for_canvas(page)


def _load_dataflow(page, path: str) -> None:
    """File -> Load dataflow with *path* (as ``test_workflow_deps_e2e`` does)."""
    page.wait_for_load_state("domcontentloaded")
    file_menu = page.get_by_test_id("file-menu-btn")
    file_menu.wait_for(state="visible", timeout=60000)
    file_menu.click(force=True)  # the ReactFlow pane swallows plain clicks
    load = page.get_by_role("button", name="Load dataflow")
    load.wait_for(state="visible", timeout=15000)
    with page.expect_file_chooser() as chooser:
        page.get_by_text("Load dataflow").click()
    chooser.value.set_files(path)


def _expand_palette_package(anchor) -> None:
    """Open the palette accordion so its rows can be dragged."""
    details = anchor.locator("details").first
    details.wait_for(state="attached", timeout=15000)
    if not details.evaluate("(el) => el.open"):
        anchor.locator("summary").first.locator("span[title]").first.click()
    expect(details).to_have_attribute("open", "", timeout=10000)


def test_a_node_card_dropped_from_the_drawer_opens_the_add_review_and_its_node_runs_with_the_library(
    app_frontend: "FrontendPage", current_server: str, page, probe_package,
):
    session = _enter_canvas(page, app_frontend, current_server, kind="drop")
    _assert_not_added_yet(current_server, session["token"])

    drawer = _open_node_catalog_drawer(page)
    card = drawer.locator(CARD)
    expect(card).to_have_count(1, timeout=30000)
    expect(card).to_have_attribute("draggable", "true")
    writes = _record_package_writes(page)
    before = _node_ids(page)

    drop = drag_with_the_mouse_onto_canvas(page, card.locator("h3"), at=UNDER_THE_SCRIM)

    assert drop["onCanvas"], f"the card's drop landed on {drop['droppedOn']}, not on the canvas"
    review = _add_review(page)
    expect(review).to_be_visible(timeout=30000)
    _assert_lists_the_library(review)
    # The review comes first: nothing is added, installed or created before it.
    adds = [w for w in writes if w.endswith("/install") or "/api/packages/defaults" in w]
    assert (sorted(_node_ids(page) - before), adds) == ([], []), (
        f"the drop made nodes or added the package before the review was confirmed: {writes}"
    )
    save_workflow_test_screenshot(
        page, DROP_STEM, test_name="add-review", fit_reactflow=False, clip_selector=ADD_REVIEW,
    )

    with page.expect_response(
        lambda r: "/api/packages/projects/" in r.url and r.url.endswith("/install")
        and r.request.method == "POST",
        timeout=180000,
    ) as added:
        review.get_by_role("button", name="Add to project", exact=True).click()
    response = added.value
    assert response.status == 201, f"{response.status}: {response.text()[:600]}"
    assert not response.json().get("importErrors"), response.json()
    assert library_installed(current_server, LIB), f"{PKG_DIR} was added and pip never installed {LIB.dist}"

    node = _new_node(page, before)
    assert (canvas_node_type(page, node) or "").startswith(NODE_TYPE), canvas_node_type(page, node)
    expect(review).to_have_count(0)

    # The drawer's scrim lies over the canvas: close it, then frame and run the node.
    page.keyboard.press("Escape")
    wait_for_drawer_closed(page, NODE_DRAWER)
    save_node_closeup(page, DROP_STEM, node, test_name="node", sweep_toasts=True)
    run_node_and_wait(page, node, node_type=NODE_TYPE)
    _assert_the_node_ran_the_library(page, node)


def test_a_hosted_guest_dropping_a_node_card_is_refused_and_no_node_appears(
    app_frontend: "FrontendPage", current_server: str, page, probe_package,
):
    require_project_page()
    require_user_auth()
    assert allow_guest_login_env(), "this stack turns guest login off, so it has no hosted guest to refuse"
    page.emulate_media(reduced_motion="reduce")
    _enter_as_hosted_guest(page, app_frontend.base_url)

    drawer = _open_node_catalog_drawer(page)
    card = drawer.locator(CARD)
    expect(card).to_have_count(1, timeout=30000)
    expect(card).to_have_attribute("draggable", "true")
    writes = _record_package_writes(page)
    before = _node_ids(page)

    drop = drag_with_the_mouse_onto_canvas(page, card.locator("h3"), at=UNDER_THE_SCRIM)

    assert drop["onCanvas"], f"the card's drop landed on {drop['droppedOn']}, not on the canvas"
    expect(page.locator(NOTIFICATIONS).get_by_text(GUEST_REFUSAL)).to_be_visible(timeout=10000)
    expect(_add_review(page)).to_have_count(0)
    assert (sorted(_node_ids(page) - before), writes) == ([], []), (
        f"a hosted guest's drop made nodes or reached the package routes: {writes}"
    )
    assert not library_installed(current_server, LIB)


def test_loading_a_dataflow_whose_lockfile_names_the_package_adds_it_and_run_all_runs_its_node(
    app_frontend: "FrontendPage", current_server: str, page, tmp_path, probe_package,
):
    session = _enter_canvas(page, app_frontend, current_server, kind="lockfile")
    token = session["token"]
    _assert_not_added_yet(current_server, token)

    node_id = "offline-probe-node"
    spec = {
        "dataflow": {
            "name": "Names the wheelhouse probe",
            "task": "",
            "nodes": [{
                "id": node_id,
                "type": NODE_TYPE,
                "x": 400,
                "y": 300,
                "content": PROBE_CODE,
                "in": "DEFAULT",
                "out": "DEFAULT",
                "goal": "",
                "metadata": {"keywords": []},
            }],
            "edges": [],
            "packages": [PKG_DIR],
        }
    }
    spec_file = tmp_path / "names-the-wheelhouse-probe.json"
    spec_file.write_text(json.dumps(spec), encoding="utf-8")

    with page.expect_response(
        lambda r: "/api/packages/workflow-deps/install" in r.url and r.request.method == "POST",
        timeout=180000,
    ) as installed:
        _load_dataflow(page, str(spec_file))
    response = installed.value
    assert response.ok, f"{response.status}: {response.text()[:600]}"
    assert response.json()["installedPackages"] == [PKG_DIR], response.json()
    expect(page.locator(NOTIFICATIONS)).to_contain_text(f"Installed {PKG_DIR}.", timeout=30000)
    assert library_installed(current_server, LIB), f"{PKG_DIR} was added and pip never installed {LIB.dist}"
    assert PKG_DIR in _store_dirs(current_server, token)

    # The node is the package's own once the registry knows the package.
    node_locator(page, node_id).locator(".monaco-editor").first.wait_for(state="attached", timeout=60000)
    run_all_and_wait(page)
    _assert_the_node_ran_the_library(page, node_id)


def test_adding_the_package_on_the_catalog_page_installs_its_library_and_its_node_runs_from_the_palette(
    app_frontend: "FrontendPage", current_server: str, page, probe_package,
):
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    session = stub_db_login(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        username=_username("catalog"),
        name="Offline Catalog User",
    )
    _assert_not_added_yet(current_server, session["token"])

    page.goto(f"{app_frontend.base_url}/catalog/nodes")
    page.wait_for_load_state("domcontentloaded")
    card = page.locator(CARD)
    expect(card).to_have_count(1, timeout=30000)
    card.click()
    add = page.get_by_role("button", name="Add to all projects", exact=True)
    expect(add).to_be_visible(timeout=15000)
    with page.expect_response(lambda r: r.url.endswith("/api/packages/resolve"), timeout=30000):
        add.click()
    review = _add_review(page)
    expect(review).to_be_visible(timeout=15000)
    _assert_lists_the_library(review)

    with page.expect_response(
        lambda r: r.url.endswith("/api/packages/defaults") and r.request.method == "POST",
        timeout=180000,
    ) as added:
        review.get_by_role("button", name="Add to all projects", exact=True).click()
    response = added.value
    assert response.status == 201, f"{response.status}: {response.text()[:600]}"
    assert not response.json().get("importErrors"), response.json()
    assert library_installed(current_server, LIB), f"{PKG_DIR} was added and pip never installed {LIB.dist}"

    # A new dataflow starts with the account's packages: the node is in its palette.
    page.goto(f"{app_frontend.base_url}/projects")
    wait_for_projects_page(page, timeout=30000)
    open_new_workflow(page)
    _wait_for_canvas(page)
    open_tools_palette(page, "packages")
    anchor = page.locator(f'#packages-palette [data-pkg-palette-coords~="{PKG_DIR}"]')
    expect(anchor).to_have_count(1, timeout=30000)
    _expand_palette_package(anchor)
    row = anchor.locator("div:has(> [data-pkg-template-id])").filter(has_text=PKG_NAME)
    expect(row).to_have_count(1, timeout=20000)
    node = drag_to_canvas(page, row, at=(150, 150))
    close_tools_palette(page, "packages")

    assert (canvas_node_type(page, node) or "").startswith(NODE_TYPE), canvas_node_type(page, node)
    run_node_and_wait(page, node, node_type=NODE_TYPE)
    _assert_the_node_ran_the_library(page, node)
