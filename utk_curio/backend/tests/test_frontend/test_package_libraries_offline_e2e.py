"""Playwright E2E: a package's library installs by itself, offline, on each path that adds the package.

A package declares its libraries (``dependencies.python``); they are never
Curio's own dependencies. They install when the package is added, when a
dataflow whose lockfile names it is opened, or at launch for the packages the
shipped examples declare (``--with-examples``). Each test below adds a test
package kept beside these tests (``packages/``) along one path, and checks that
the library was not installed before, that pip installed it, and that the
package's node runs and prints the message the library holds.

Each test has a package and a library of its own, so each proves its own
install from scratch, even after an earlier test on the same backend imported
another test library.

Offline by construction: the library is a wheel of a few hundred bytes the
test builds, staged in the backend's own wheelhouse, and the backend's pip
reads that and no index (``PIP_NO_INDEX`` with ``PIP_FIND_LINKS``, as
``test_backend_runtime.py`` installs ``tinylib``). See
``utils/offline_install.py``.

* A node card dragged from the Node Catalog drawer onto the canvas opens the
  Add review, which lists the library; after the confirm the node appears and
  runs (``test.wheelhouse-probe@1``).
* A card of a package with two nodes opens a menu of them at the drop point.
  Escape closes it and makes no node; the node picked appears after the Add
  review and runs (``test.wheelhouse-pair@1``).
* A hosted guest's drop is refused before any menu, and no node appears:
  guests never install (``test.wheelhouse-guest@1``).
* Loading a dataflow whose lockfile names the package adds it, and Run All
  runs its node (``test.wheelhouse-lockfile@1``).
* Loading a dataflow whose lockfile names a package and not the package it
  names in ``dependencies.packages`` adds both, with both libraries, and Run
  All runs its node, which imports the other package's module
  (``test.wheelhouse-dependent@1``, which needs ``test.wheelhouse-dependency@1``).
* Add on the Node Catalog page installs the library, and the node dropped from
  the palette runs (``test.wheelhouse-catalog@1``).
* A model card dragged from the Model Catalog drawer onto the canvas opens the
  same Add review, which lists the library; after the confirm the model's node
  appears with ``curio_load_model("<id>")`` and runs the model
  (``test.wheelhouse-model@1``, a copy of Local Relief). A hosted guest's drop
  of that card is refused, and no node appears.

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
    OfflinePackage,
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
    offline_package,
    open_new_workflow,
    open_tools_palette,
    plant_catalog_package,
    read_node_code,
    read_node_output_text,
    remove_catalog_package,
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

#: One test package, and one library, per test.
#: The card drop, whose two frames are approved: keep the package as it is.
PROBE = offline_package("test.wheelhouse-probe@1")
#: Two nodes: its card's drop opens a menu of them.
PAIR = offline_package("test.wheelhouse-pair@1")
#: Two nodes too, so a hosted guest's refusal comes before any menu.
GUEST = offline_package("test.wheelhouse-guest@1")
LOCKFILE = offline_package("test.wheelhouse-lockfile@1")
#: A package that names another in ``dependencies.packages``, and the package
#: it names, whose module its node imports.
DEPENDENT = offline_package("test.wheelhouse-dependent@1")
DEPENDENCY = offline_package("test.wheelhouse-dependency@1")
DEPENDENCY_MODULE = "wheelhouse_dependency_module"
CATALOG = offline_package("test.wheelhouse-catalog@1")
#: A model package, a copy of Local Relief: its card's drop makes its one node.
MODEL = offline_package("test.wheelhouse-model@1")
MODEL_ID = "test.wheelhouse-model"

BAR = "header[data-curio-menu-bar]"
NODE_DRAWER = '[data-curio-node-catalog-drawer="true"]'
MODEL_DRAWER = '[data-curio-model-catalog-drawer="true"]'
ADD_REVIEW = '[data-curio-add-review="true"]'
NOTIFICATIONS = '[aria-label="Notifications"]'
#: Where a card from the drawer is dropped, from the canvas's top-left corner:
#: left of the 520 px drawer, under its scrim.
UNDER_THE_SCRIM = (320.0, 220.0)
#: The frames of the drop: the Add review, and the node after the install.
DROP_STEM = "package-card-drop"
#: The frames of the menu: open at the drop point, and the node picked.
MENU_STEM = "package-card-menu"
#: The frames of a model card's drop: the Add review, and the node after the install.
MODEL_DROP_STEM = "model-card-drop"


def _offline(server: str, package: OfflinePackage):
    """*package* in this backend's catalog, its library only in the wheelhouse."""
    return offline_catalog_package(server, package.dir_name, [package.library])


@pytest.fixture()
def probe_package(current_server: str):
    with _offline(current_server, PROBE):
        yield


@pytest.fixture()
def pair_package(current_server: str):
    with _offline(current_server, PAIR):
        yield


@pytest.fixture()
def guest_package(current_server: str):
    with _offline(current_server, GUEST):
        yield


@pytest.fixture()
def lockfile_package(current_server: str):
    with _offline(current_server, LOCKFILE):
        yield


@pytest.fixture()
def dependent_packages(current_server: str):
    """Both packages in the catalog, both libraries only in the wheelhouse."""
    with offline_catalog_package(current_server, DEPENDENT.dir_name, [DEPENDENT.library, DEPENDENCY.library]):
        plant_catalog_package(current_server, DEPENDENCY.dir_name)
        try:
            yield
        finally:
            remove_catalog_package(current_server, DEPENDENCY.dir_name)


@pytest.fixture()
def catalog_package(current_server: str):
    with _offline(current_server, CATALOG):
        yield


@pytest.fixture()
def model_package(current_server: str):
    with _offline(current_server, MODEL):
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


def _assert_not_added_yet(server: str, token: str, package: OfflinePackage) -> None:
    store = _store_dirs(server, token)
    assert package.dir_name not in store, (
        f"{package.dir_name} is in this account's store before the test adds it: {store}"
    )
    assert not library_installed(server, package.library), (
        f"{package.library.dist} is installed before the test adds {package.dir_name}"
    )


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


def _adds(writes: list[str]) -> list[str]:
    """The requests that add a package to a dataflow or an account."""
    return [w for w in writes if w.endswith("/install") or "/api/packages/defaults" in w]


def _card(package: OfflinePackage) -> str:
    return f'article[data-pkg-dir="{package.dir_name}"]'


def _open_node_catalog_drawer(page):
    page.locator(BAR).get_by_role("button", name="Node Catalog", exact=True).click()
    drawer = page.locator(NODE_DRAWER)
    expect(drawer).to_have_attribute("aria-hidden", "false", timeout=15000)
    return drawer


def _open_model_catalog_drawer(page):
    page.locator(BAR).get_by_role("button", name="Model Catalog", exact=True).click()
    drawer = page.locator(MODEL_DRAWER)
    expect(drawer).to_have_attribute("aria-hidden", "false", timeout=15000)
    return drawer


def _add_review(page, package: OfflinePackage):
    return page.get_by_role("dialog").filter(
        has=page.get_by_role("heading", name=f'Add "{package.name}"', exact=True)
    )


def _node_menu(page, package: OfflinePackage):
    """The menu of *package*'s nodes a drop of its card opens."""
    return page.get_by_role("menu", name=f"{package.name} nodes", exact=True)


def _node_menu_selector(package: OfflinePackage) -> str:
    return f'[data-curio-card-context-menu="true"][aria-label="{package.name} nodes"]'


def _guest_refusal(package: OfflinePackage) -> str:
    return (
        f"Adding {package.name} is not available for guest users, because every guest shares "
        f"one account. Sign in with an account to add it."
    )


def _assert_lists_the_library(review, package: OfflinePackage) -> None:
    library = package.library
    expect(review.locator("code", has_text=f"python · {library.dist}")).to_be_visible(timeout=10000)
    expect(review.locator("code").filter(has_text=library.version)).to_have_count(1)


def _assert_the_node_ran_the_library(page, node_id: str, package: OfflinePackage, *, shows: str = "") -> None:
    """The node's output holds the library's message, and *shows* when given."""
    library = package.library
    output = read_node_output_text(page, node_id)
    assert library.message in output, f"the node's output does not show {library.module} imported: {output!r}"
    assert shows in output, f"the node's output is not the one of the node it should be: {output!r}"


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


def _expect_project_install(page):
    """The confirmed Add review's install of the package into this dataflow."""
    return page.expect_response(
        lambda r: "/api/packages/projects/" in r.url and r.url.endswith("/install")
        and r.request.method == "POST",
        timeout=180000,
    )


def test_a_node_card_dropped_from_the_drawer_opens_the_add_review_and_its_node_runs_with_the_library(
    app_frontend: "FrontendPage", current_server: str, page, probe_package,
):
    session = _enter_canvas(page, app_frontend, current_server, kind="drop")
    _assert_not_added_yet(current_server, session["token"], PROBE)
    [probe] = PROBE.nodes

    drawer = _open_node_catalog_drawer(page)
    card = drawer.locator(_card(PROBE))
    expect(card).to_have_count(1, timeout=30000)
    expect(card).to_have_attribute("draggable", "true")
    writes = _record_package_writes(page)
    before = _node_ids(page)

    drop = drag_with_the_mouse_onto_canvas(page, card.locator("h3"), at=UNDER_THE_SCRIM)

    assert drop["onCanvas"], f"the card's drop landed on {drop['droppedOn']}, not on the canvas"
    review = _add_review(page, PROBE)
    expect(review).to_be_visible(timeout=30000)
    _assert_lists_the_library(review, PROBE)
    # The review comes first: nothing is added, installed or created before it.
    assert (sorted(_node_ids(page) - before), _adds(writes)) == ([], []), (
        f"the drop made nodes or added the package before the review was confirmed: {writes}"
    )
    save_workflow_test_screenshot(
        page, DROP_STEM, test_name="add-review", fit_reactflow=False, clip_selector=ADD_REVIEW,
    )

    with _expect_project_install(page) as added:
        review.get_by_role("button", name="Add to project", exact=True).click()
    response = added.value
    assert response.status == 201, f"{response.status}: {response.text()[:600]}"
    assert not response.json().get("importErrors"), response.json()
    assert library_installed(current_server, PROBE.library), (
        f"{PROBE.dir_name} was added and pip never installed {PROBE.library.dist}"
    )

    node = _new_node(page, before)
    assert (canvas_node_type(page, node) or "").startswith(probe.type), canvas_node_type(page, node)
    expect(review).to_have_count(0)

    # The drawer's scrim lies over the canvas: close it, then frame and run the node.
    page.keyboard.press("Escape")
    wait_for_drawer_closed(page, NODE_DRAWER)
    save_node_closeup(page, DROP_STEM, node, test_name="node", sweep_toasts=True)
    run_node_and_wait(page, node, node_type=probe.type)
    _assert_the_node_ran_the_library(page, node, PROBE)


def test_a_card_of_a_package_with_two_nodes_opens_a_menu_of_them_and_the_node_picked_runs_with_the_library(
    app_frontend: "FrontendPage", current_server: str, page, pair_package,
):
    session = _enter_canvas(page, app_frontend, current_server, kind="menu")
    _assert_not_added_yet(current_server, session["token"], PAIR)
    first, second = PAIR.nodes

    drawer = _open_node_catalog_drawer(page)
    card = drawer.locator(_card(PAIR))
    expect(card).to_have_count(1, timeout=30000)
    expect(card).to_have_attribute("draggable", "true")
    writes = _record_package_writes(page)
    before = _node_ids(page)
    menu = _node_menu(page, PAIR)

    # Escape closes the menu alone: no node, nothing asked of the package
    # routes, and the drawer under it stays open.
    drop = drag_with_the_mouse_onto_canvas(page, card.locator("h3"), at=UNDER_THE_SCRIM)
    assert drop["onCanvas"], f"the card's drop landed on {drop['droppedOn']}, not on the canvas"
    expect(menu).to_be_visible(timeout=10000)
    page.keyboard.press("Escape")
    expect(menu).to_have_count(0)
    expect(drawer).to_have_attribute("aria-hidden", "false")
    expect(_add_review(page, PAIR)).to_have_count(0)
    assert (sorted(_node_ids(page) - before), writes) == ([], []), (
        f"Escape on the menu made nodes or reached the package routes: {writes}"
    )

    # Dropped again: the menu at the drop point lists the package's nodes.
    drop = drag_with_the_mouse_onto_canvas(page, card.locator("h3"), at=UNDER_THE_SCRIM)
    assert drop["onCanvas"], f"the card's drop landed on {drop['droppedOn']}, not on the canvas"
    expect(menu).to_be_visible(timeout=10000)
    expect(menu.get_by_role("menuitem")).to_have_text([first.label, second.label])
    x, y = drop["target"]
    box = menu.bounding_box()
    assert box is not None and abs(box["x"] - x) <= 2 and abs(box["y"] - y) <= 2, (
        f"the menu opened at {box}, not at the drop point ({x:.0f}, {y:.0f})"
    )
    assert (sorted(_node_ids(page) - before), writes) == ([], []), (
        f"the drop made nodes or reached the package routes before a node was picked: {writes}"
    )
    # Off the menu, so no row is captured under the pointer.
    page.mouse.move(x - 80, y - 80)
    save_workflow_test_screenshot(
        page, MENU_STEM, test_name="open", fit_reactflow=False, clip_selector=_node_menu_selector(PAIR),
    )

    # The second node: a drop that made the first node whatever the pick
    # would fail here.
    menu.get_by_role("menuitem", name=second.label, exact=True).click()
    expect(menu).to_have_count(0)
    review = _add_review(page, PAIR)
    expect(review).to_be_visible(timeout=30000)
    _assert_lists_the_library(review, PAIR)
    assert (sorted(_node_ids(page) - before), _adds(writes)) == ([], []), (
        f"the pick made nodes or added the package before the review was confirmed: {writes}"
    )

    with _expect_project_install(page) as added:
        review.get_by_role("button", name="Add to project", exact=True).click()
    response = added.value
    assert response.status == 201, f"{response.status}: {response.text()[:600]}"
    assert not response.json().get("importErrors"), response.json()
    assert library_installed(current_server, PAIR.library), (
        f"{PAIR.dir_name} was added and pip never installed {PAIR.library.dist}"
    )

    node = _new_node(page, before)
    assert (canvas_node_type(page, node) or "").startswith(second.type), canvas_node_type(page, node)
    expect(review).to_have_count(0)

    # The drawer's scrim lies over the canvas: close it, then frame and run the node.
    page.keyboard.press("Escape")
    wait_for_drawer_closed(page, NODE_DRAWER)
    save_node_closeup(page, MENU_STEM, node, test_name="node", sweep_toasts=True)
    run_node_and_wait(page, node, node_type=second.type)
    _assert_the_node_ran_the_library(page, node, PAIR, shows=f"second: {PAIR.library.message}")


def test_a_hosted_guest_dropping_a_node_card_is_refused_before_any_menu_and_no_node_appears(
    app_frontend: "FrontendPage", current_server: str, page, guest_package,
):
    require_project_page()
    require_user_auth()
    assert allow_guest_login_env(), "this stack turns guest login off, so it has no hosted guest to refuse"
    assert len(GUEST.nodes) > 1, "the guest's package must have several nodes, whose drop opens a menu"
    page.emulate_media(reduced_motion="reduce")
    _enter_as_hosted_guest(page, app_frontend.base_url)

    drawer = _open_node_catalog_drawer(page)
    card = drawer.locator(_card(GUEST))
    expect(card).to_have_count(1, timeout=30000)
    expect(card).to_have_attribute("draggable", "true")
    writes = _record_package_writes(page)
    before = _node_ids(page)

    drop = drag_with_the_mouse_onto_canvas(page, card.locator("h3"), at=UNDER_THE_SCRIM)

    assert drop["onCanvas"], f"the card's drop landed on {drop['droppedOn']}, not on the canvas"
    expect(page.locator(NOTIFICATIONS).get_by_text(_guest_refusal(GUEST))).to_be_visible(timeout=10000)
    expect(_node_menu(page, GUEST)).to_have_count(0)
    expect(_add_review(page, GUEST)).to_have_count(0)
    assert (sorted(_node_ids(page) - before), writes) == ([], []), (
        f"a hosted guest's drop made nodes or reached the package routes: {writes}"
    )
    assert not library_installed(current_server, GUEST.library)


def test_loading_a_dataflow_whose_lockfile_names_the_package_adds_it_and_run_all_runs_its_node(
    app_frontend: "FrontendPage", current_server: str, page, tmp_path, lockfile_package,
):
    session = _enter_canvas(page, app_frontend, current_server, kind="lockfile")
    token = session["token"]
    _assert_not_added_yet(current_server, token, LOCKFILE)
    [probe] = LOCKFILE.nodes

    node_id = "offline-probe-node"
    spec = {
        "dataflow": {
            "name": "Names the wheelhouse lockfile probe",
            "task": "",
            "nodes": [{
                "id": node_id,
                "type": probe.type,
                "x": 400,
                "y": 300,
                "content": probe.code,
                "in": "DEFAULT",
                "out": "DEFAULT",
                "goal": "",
                "metadata": {"keywords": []},
            }],
            "edges": [],
            "packages": [LOCKFILE.dir_name],
        }
    }
    spec_file = tmp_path / "names-the-wheelhouse-lockfile-probe.json"
    spec_file.write_text(json.dumps(spec), encoding="utf-8")

    with page.expect_response(
        lambda r: "/api/packages/workflow-deps/install" in r.url and r.request.method == "POST",
        timeout=180000,
    ) as installed:
        _load_dataflow(page, str(spec_file))
    response = installed.value
    assert response.ok, f"{response.status}: {response.text()[:600]}"
    assert response.json()["installedPackages"] == [LOCKFILE.dir_name], response.json()
    expect(page.locator(NOTIFICATIONS)).to_contain_text(f"Installed {LOCKFILE.dir_name}.", timeout=30000)
    assert library_installed(current_server, LOCKFILE.library), (
        f"{LOCKFILE.dir_name} was added and pip never installed {LOCKFILE.library.dist}"
    )
    assert LOCKFILE.dir_name in _store_dirs(current_server, token)

    # The node is the package's own once the registry knows the package.
    node_locator(page, node_id).locator(".monaco-editor").first.wait_for(state="attached", timeout=60000)
    run_all_and_wait(page)
    _assert_the_node_ran_the_library(page, node_id, LOCKFILE)


def test_loading_a_dataflow_whose_package_needs_another_adds_both_and_its_node_imports_the_other_packages_module(
    app_frontend: "FrontendPage", current_server: str, page, tmp_path, dependent_packages,
):
    session = _enter_canvas(page, app_frontend, current_server, kind="dependent")
    token = session["token"]
    for package in (DEPENDENT, DEPENDENCY):
        _assert_not_added_yet(current_server, token, package)
    [probe] = DEPENDENT.nodes

    node_id = "offline-dependent-node"
    spec = {
        "dataflow": {
            "name": "Names a package that needs another",
            "task": "",
            "nodes": [{
                "id": node_id,
                "type": probe.type,
                "x": 400,
                "y": 300,
                "content": probe.code,
                "in": "DEFAULT",
                "out": "DEFAULT",
                "goal": "",
                "metadata": {"keywords": []},
            }],
            "edges": [],
            # The package alone: the one it needs comes with it.
            "packages": [DEPENDENT.dir_name],
        }
    }
    spec_file = tmp_path / "names-a-package-that-needs-another.json"
    spec_file.write_text(json.dumps(spec), encoding="utf-8")

    with page.expect_response(
        lambda r: "/api/packages/workflow-deps/install" in r.url and r.request.method == "POST",
        timeout=180000,
    ) as installed:
        _load_dataflow(page, str(spec_file))
    response = installed.value
    assert response.ok, f"{response.status}: {response.text()[:600]}"
    assert response.json()["installedPackages"] == [DEPENDENT.dir_name], response.json()
    store = _store_dirs(current_server, token)
    assert {DEPENDENT.dir_name, DEPENDENCY.dir_name} <= set(store), (
        f"{DEPENDENT.dir_name} was added without {DEPENDENCY.dir_name}, which it names: {store}"
    )
    for package in (DEPENDENT, DEPENDENCY):
        assert library_installed(current_server, package.library), (
            f"{package.dir_name} was added and pip never installed {package.library.dist}"
        )

    node_locator(page, node_id).locator(".monaco-editor").first.wait_for(state="attached", timeout=60000)
    run_all_and_wait(page)
    output = read_node_output_text(page, node_id)
    assert DEPENDENT.library.message in output, f"the node's output does not show its own library: {output!r}"
    assert f"{DEPENDENCY.library.message}, through {DEPENDENCY_MODULE}" in output, (
        f"the node's output does not show {DEPENDENCY_MODULE} imported from {DEPENDENCY.dir_name}: {output!r}"
    )


def test_adding_the_package_on_the_catalog_page_installs_its_library_and_its_node_runs_from_the_palette(
    app_frontend: "FrontendPage", current_server: str, page, catalog_package,
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
    _assert_not_added_yet(current_server, session["token"], CATALOG)
    [probe] = CATALOG.nodes

    page.goto(f"{app_frontend.base_url}/catalog/nodes")
    page.wait_for_load_state("domcontentloaded")
    card = page.locator(_card(CATALOG))
    expect(card).to_have_count(1, timeout=30000)
    card.click()
    add = page.get_by_role("button", name="Add to all projects", exact=True)
    expect(add).to_be_visible(timeout=15000)
    with page.expect_response(lambda r: r.url.endswith("/api/packages/resolve"), timeout=30000):
        add.click()
    review = _add_review(page, CATALOG)
    expect(review).to_be_visible(timeout=15000)
    _assert_lists_the_library(review, CATALOG)

    with page.expect_response(
        lambda r: r.url.endswith("/api/packages/defaults") and r.request.method == "POST",
        timeout=180000,
    ) as added:
        review.get_by_role("button", name="Add to all projects", exact=True).click()
    response = added.value
    assert response.status == 201, f"{response.status}: {response.text()[:600]}"
    assert not response.json().get("importErrors"), response.json()
    assert library_installed(current_server, CATALOG.library), (
        f"{CATALOG.dir_name} was added and pip never installed {CATALOG.library.dist}"
    )

    # A new dataflow starts with the account's packages: the node is in its palette.
    page.goto(f"{app_frontend.base_url}/projects")
    wait_for_projects_page(page, timeout=30000)
    open_new_workflow(page)
    _wait_for_canvas(page)
    open_tools_palette(page, "packages")
    anchor = page.locator(f'#packages-palette [data-pkg-palette-coords~="{CATALOG.dir_name}"]')
    expect(anchor).to_have_count(1, timeout=30000)
    _expand_palette_package(anchor)
    row = anchor.locator("div:has(> [data-pkg-template-id])").filter(has_text=probe.label)
    expect(row).to_have_count(1, timeout=20000)
    node = drag_to_canvas(page, row, at=(150, 150))
    close_tools_palette(page, "packages")

    assert (canvas_node_type(page, node) or "").startswith(probe.type), canvas_node_type(page, node)
    run_node_and_wait(page, node, node_type=probe.type)
    _assert_the_node_ran_the_library(page, node, CATALOG)


def test_a_model_card_whose_package_is_not_added_opens_the_add_review_and_its_node_runs_with_the_library(
    app_frontend: "FrontendPage", current_server: str, page, model_package,
):
    session = _enter_canvas(page, app_frontend, current_server, kind="model")
    _assert_not_added_yet(current_server, session["token"], MODEL)
    [relief] = MODEL.nodes

    drawer = _open_model_catalog_drawer(page)
    card = drawer.locator(_card(MODEL))
    expect(card).to_have_count(1, timeout=30000)
    expect(card).to_have_attribute("draggable", "true")
    writes = _record_package_writes(page)
    before = _node_ids(page)

    drop = drag_with_the_mouse_onto_canvas(page, card.locator("h3"), at=UNDER_THE_SCRIM)

    assert drop["onCanvas"], f"the card's drop landed on {drop['droppedOn']}, not on the canvas"
    review = _add_review(page, MODEL)
    expect(review).to_be_visible(timeout=30000)
    _assert_lists_the_library(review, MODEL)
    # The review comes first: nothing is added, installed or created before it.
    assert (sorted(_node_ids(page) - before), _adds(writes)) == ([], []), (
        f"the drop made nodes or added the package before the review was confirmed: {writes}"
    )
    save_workflow_test_screenshot(
        page, MODEL_DROP_STEM, test_name="add-review", fit_reactflow=False, clip_selector=ADD_REVIEW,
    )

    with _expect_project_install(page) as added:
        review.get_by_role("button", name="Add to project", exact=True).click()
    response = added.value
    assert response.status == 201, f"{response.status}: {response.text()[:600]}"
    assert not response.json().get("importErrors"), response.json()
    assert library_installed(current_server, MODEL.library), (
        f"{MODEL.dir_name} was added and pip never installed {MODEL.library.dist}"
    )

    node = _new_node(page, before)
    assert (canvas_node_type(page, node) or "").startswith(relief.type), canvas_node_type(page, node)
    expect(review).to_have_count(0)
    page.wait_for_function(
        """([id, needle]) => {
            const node = window.__curio_reactFlow.getNodes().find((n) => n.id === id);
            return !!node && typeof node.data.code === "string" && node.data.code.includes(needle);
        }""",
        arg=[node, f'curio_load_model("{MODEL_ID}")'],
        timeout=30000,
    )
    assert f'curio_load_model("{MODEL_ID}")' in read_node_code(page, node)

    # The drawer's scrim lies over the canvas: close it, then frame and run the node.
    page.keyboard.press("Escape")
    wait_for_drawer_closed(page, MODEL_DRAWER)
    save_node_closeup(page, MODEL_DROP_STEM, node, test_name="node", sweep_toasts=True)
    run_node_and_wait(page, node, node_type=relief.type)
    _assert_the_node_ran_the_library(page, node, MODEL, shows="relief (1, 1, 8, 8)")


def test_a_hosted_guest_dropping_a_model_card_is_refused_and_no_node_appears(
    app_frontend: "FrontendPage", current_server: str, page, model_package,
):
    require_project_page()
    require_user_auth()
    assert allow_guest_login_env(), "this stack turns guest login off, so it has no hosted guest to refuse"
    page.emulate_media(reduced_motion="reduce")
    _enter_as_hosted_guest(page, app_frontend.base_url)

    drawer = _open_model_catalog_drawer(page)
    card = drawer.locator(_card(MODEL))
    expect(card).to_have_count(1, timeout=30000)
    expect(card).to_have_attribute("draggable", "true")
    writes = _record_package_writes(page)
    before = _node_ids(page)

    drop = drag_with_the_mouse_onto_canvas(page, card.locator("h3"), at=UNDER_THE_SCRIM)

    assert drop["onCanvas"], f"the card's drop landed on {drop['droppedOn']}, not on the canvas"
    expect(page.locator(NOTIFICATIONS).get_by_text(_guest_refusal(MODEL))).to_be_visible(timeout=10000)
    expect(_add_review(page, MODEL)).to_have_count(0)
    assert (sorted(_node_ids(page) - before), writes) == ([], []), (
        f"a hosted guest's drop made nodes or reached the package routes: {writes}"
    )
    assert not library_installed(current_server, MODEL.library)
