"""The Model Catalog on the Node Catalog's code (PR #819 port, step 4.4).

The Model Catalog keeps its own top-bar button, page, drawer and details
modal, built from the Node Catalog's and listing the model packages (kind
``model``) through the same packages service:

* the button opens its own drawer, with the Node Catalog drawer's tabs, and a
  card opens its own details modal with the model's fields, both licenses,
  the node a drop creates and the package's modules;
* the Node Catalog, drawer and page, lists no model package;
* Browse all, In project and Remove work as for a node package;
* a model package exported as a ``.curio.zip`` from one account imports into
  another through the Model Catalog drawer, and runs there.

Frames: the drawer, the details and the page.
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from playwright.sync_api import expect

from .utils import (
    EXPORT_DOWNLOAD_TIMEOUT_MS,
    REPO_ROOT,
    accept_confirm_dialog,
    require_owner_view,
    require_project_page,
    require_user_auth,
    run_node_and_wait,
    save_workflow_test_screenshot,
    stub_login_and_enter_workflow,
    wait_for_drawer_closed,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

MODEL_DRAWER = '[data-curio-model-catalog-drawer="true"]'
NODE_DRAWER = '[data-curio-node-catalog-drawer="true"]'

DDRNET = "model.curio.ddrnet23-slim@1"
DEEP_UMBRA = "model.scout.deep-umbra@1"
WEATHER_GNN = "model.scout.weather-gnn@1"
SHIPPED_MODELS = (DDRNET, DEEP_UMBRA, WEATHER_GNN)

LOCAL_RELIEF_ID = "model.example.local-relief"
LOCAL_RELIEF = f"{LOCAL_RELIEF_ID}@1"
LOCAL_RELIEF_FOLDER = Path(REPO_ROOT) / "docs" / "bring-your-own-model" / LOCAL_RELIEF

RUN_NODE = "runs-local-relief"
RELIEF_MARKER = "LOCAL_RELIEF_RAN"


def _spec(*, code: str = "return [1]", node_id: str = "model-catalog-node") -> dict:
    """One node, so the canvas is not empty (a capture waits for a node)."""
    return {
        "dataflow": {
            "name": "ModelCatalog",
            "task": "",
            "nodes": [
                {
                    "id": node_id,
                    "type": "curio.builtin/computation-analysis",
                    "x": 420,
                    "y": 300,
                    "content": code,
                    "in": "DEFAULT",
                    "out": "DEFAULT",
                    "goal": "",
                    "metadata": {"keywords": []},
                }
            ],
            "edges": [],
        }
    }


def _enter(page, app_frontend, current_server, *, username: str, spec: dict | None = None) -> dict:
    """One stub user per test (and per account in a test)."""
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    result = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Model Catalog User",
        username=username,
        project_name="Model Catalog",
        project_spec=spec or _spec(),
    )
    require_owner_view(page)
    return result


def _open_drawer(page, title: str, root: str):
    # The rail's palette trigger also says "<title>", with a count beside it:
    # exact=True picks the top bar's own button.
    page.get_by_role("button", name=title, exact=True).click()
    page.locator(root).wait_for(state="attached", timeout=15000)
    dialog = page.get_by_role("dialog").filter(has=page.get_by_role("heading", name=title, exact=True))
    expect(dialog).to_be_visible(timeout=10000)
    return dialog


def _close_drawer(page, root: str) -> None:
    page.keyboard.press("Escape")
    wait_for_drawer_closed(page, root)


def _card(scope, dir_name: str):
    return scope.locator(f'article[data-pkg-dir="{dir_name}"]')


def _tab(drawer, name: str):
    return drawer.get_by_role("button", name=name)


def _row(modal, label: str):
    """The value beside *label* in the details modal's info grid."""
    return modal.locator(f"xpath=.//dt[normalize-space()='{label}']/following-sibling::dd[1]")


def _add_to_project(page, card, name: str) -> None:
    with page.expect_response(lambda r: r.url.endswith("/api/packages/resolve"), timeout=30000):
        card.get_by_role("button", name="Add to project", exact=True).click()
    review = page.get_by_role("dialog").filter(has=page.get_by_role("heading", name=f'Add "{name}"', exact=True))
    expect(review).to_be_visible(timeout=10000)
    with page.expect_response(
        lambda r: "/api/packages/projects/" in r.url and r.url.endswith("/install")
        and r.request.method == "POST" and r.ok,
        timeout=120000,
    ):
        review.get_by_role("button", name="Add to project", exact=True).click()
    expect(review).to_have_count(0, timeout=30000)


@pytest.mark.catalog_calendar
def test_the_model_catalog_button_opens_its_own_drawer_and_a_card_its_details(
    app_frontend: "FrontendPage", current_server: str, page
):
    _enter(page, app_frontend, current_server, username="modelcat_drawer")

    drawer = _open_drawer(page, "Model Catalog", MODEL_DRAWER)
    expect(_tab(drawer, "Browse all")).to_be_visible()
    expect(_tab(drawer, "In project")).to_be_visible()
    for dir_name in SHIPPED_MODELS:
        expect(_card(drawer, dir_name)).to_have_count(1, timeout=15000)
    # Only model packages: Curio's own nodes are the Node Catalog's.
    expect(_card(drawer, "curio.builtin@1")).to_have_count(0)
    # The weights' license is on the card.
    expect(_card(drawer, DEEP_UMBRA)).to_contain_text("Used with the permission of SCOUT's authors")
    expect(_card(drawer, DDRNET)).to_contain_text("MIT; trained on Cityscapes")
    expect(drawer.locator('[role="alert"]')).to_have_count(0)

    # DDRNet23-Slim's labels, and its weights' license text.
    _card(drawer, DDRNET).get_by_role("button", name="View details", exact=True).click()
    modal = page.get_by_role("dialog", name="Model details")
    expect(modal).to_be_visible(timeout=10000)
    expect(_row(modal, "Labels")).to_have_text("19")
    expect(_row(modal, "Node")).to_have_text("Image Segmentation")
    modal.get_by_role("button", name="View license").click()
    expect(modal.locator('[data-curio-model-license="true"]')).to_contain_text("Cityscapes", timeout=10000)
    modal.get_by_role("button", name="Close").click()
    expect(modal).to_have_count(0, timeout=10000)

    # Every check comes before the captures, so a frame that has no baseline
    # yet cannot hide one.
    save_workflow_test_screenshot(page, "model-catalog-drawer", test_name="test_drawer")

    _card(drawer, DEEP_UMBRA).get_by_role("button", name="View details", exact=True).click()
    modal = page.get_by_role("dialog", name="Model details")
    expect(modal).to_be_visible(timeout=10000)
    expect(_row(modal, "Type")).to_have_text("Image to image")
    expect(_row(modal, "Runtime")).to_have_text("ONNX")
    expect(_row(modal, "Input size")).to_have_text("512 × 512, float32")
    expect(_row(modal, "Size")).to_have_text("10.0 MB")
    expect(_row(modal, "Code license")).to_have_text("MIT")
    expect(_row(modal, "Weights license")).to_have_text("Used with the permission of SCOUT's authors")
    expect(_row(modal, "Node")).to_have_text("Accumulated Shadow")
    # The weights are in this image, so nothing downloads on first use.
    expect(modal.get_by_text("Downloads on first use")).to_have_count(0)
    expect(modal.get_by_role("heading", name="Modules")).to_be_visible()
    expect(modal).to_contain_text("deep_umbra")
    save_workflow_test_screenshot(page, "model-catalog-details", test_name="test_details")


def test_the_node_catalog_lists_no_model_package(app_frontend: "FrontendPage", current_server: str, page):
    _enter(page, app_frontend, current_server, username="modelcat_nodes")

    drawer = _open_drawer(page, "Node Catalog", NODE_DRAWER)
    expect(_card(drawer, "curio.builtin@1")).to_have_count(1, timeout=15000)
    for dir_name in SHIPPED_MODELS:
        expect(_card(drawer, dir_name)).to_have_count(0)
    _close_drawer(page, NODE_DRAWER)

    page.goto(f"{app_frontend.base_url}/catalog/nodes")
    grid = page.locator("main")
    expect(_card(grid, "curio.builtin@1")).to_have_count(1, timeout=30000)
    for dir_name in SHIPPED_MODELS:
        expect(_card(grid, dir_name)).to_have_count(0)


@pytest.mark.catalog_calendar
def test_the_model_catalog_page_lists_the_model_packages(app_frontend: "FrontendPage", current_server: str, page):
    _enter(page, app_frontend, current_server, username="modelcat_page")
    page.goto(f"{app_frontend.base_url}/catalog/models")
    grid = page.locator("main")
    for dir_name in SHIPPED_MODELS:
        expect(_card(grid, dir_name)).to_have_count(1, timeout=30000)
    expect(_card(grid, "curio.builtin@1")).to_have_count(0)
    expect(page.get_by_role("button", name="Import package")).to_be_visible()
    expect(_card(grid, DEEP_UMBRA)).to_contain_text("Used with the permission of SCOUT's authors")
    save_workflow_test_screenshot(page, "model-catalog-page", test_name="test_page")


def test_browse_all_in_project_and_remove(app_frontend: "FrontendPage", current_server: str, page):
    # DDRNet23-Slim: its one library, onnxruntime, is the one example 10's
    # nodes already run with, so the Add installs nothing new.
    name = "DDRNet23-Slim (street scenes)"
    _enter(page, app_frontend, current_server, username="modelcat_scope")
    drawer = _open_drawer(page, "Model Catalog", MODEL_DRAWER)
    expect(_card(drawer, DDRNET)).to_have_count(1, timeout=15000)

    # A fresh dataflow holds no model.
    _tab(drawer, "In project").click()
    expect(drawer.get_by_text("No models added to this project yet.")).to_be_visible()

    # Browse all: Add, through the Node Catalog's review.
    _tab(drawer, "Browse all").click()
    _add_to_project(page, _card(drawer, DDRNET), name)
    expect(_card(drawer, DDRNET).get_by_role("button", name="Remove from project", exact=True)).to_be_visible(
        timeout=20000
    )

    # In project: it is there, and the tab counts it.
    _tab(drawer, "In project").click()
    expect(_card(drawer, DDRNET)).to_have_count(1, timeout=10000)
    expect(_card(drawer, WEATHER_GNN)).to_have_count(0)
    expect(_tab(drawer, "In project")).to_contain_text("1")

    # Remove asks first, then takes it out of the dataflow.
    _card(drawer, DDRNET).get_by_role("button", name="Remove from project", exact=True).click()
    with page.expect_response(
        lambda r: "/api/packages/projects/" in r.url and r.request.method == "DELETE" and r.ok, timeout=30000
    ):
        accept_confirm_dialog(page, title=f"Remove {name}?", button="Remove")
    expect(_card(drawer, DDRNET)).to_have_count(0, timeout=10000)
    expect(drawer.get_by_text("No models added to this project yet.")).to_be_visible()


def _local_relief_archive(path):
    """Local Relief's folder as a ``.curio.zip``, as an export writes one: the
    package's files at the root, its integrity record left out."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for file in sorted(LOCAL_RELIEF_FOLDER.rglob("*")):
            relative = file.relative_to(LOCAL_RELIEF_FOLDER).as_posix()
            if file.is_file() and relative != "integrity.json" and "__pycache__" not in relative:
                archive.write(file, relative)
    return path


def _import_into_project(page, drawer, path) -> None:
    with page.expect_response(
        lambda r: "/api/packages/projects/" in r.url and r.url.endswith("/install")
        and r.request.method == "POST" and r.ok,
        timeout=180000,
    ):
        with page.expect_file_chooser() as chooser:
            drawer.get_by_role("button", name="Import package").click()
        chooser.value.set_files(str(path))


def test_an_exported_model_package_imports_and_runs_in_another_account(
    app_frontend: "FrontendPage", current_server: str, page, tmp_path
):
    # Account A imports Local Relief through the Model Catalog drawer...
    _enter(page, app_frontend, current_server, username="modelcat_export")
    drawer = _open_drawer(page, "Model Catalog", MODEL_DRAWER)
    _import_into_project(page, drawer, _local_relief_archive(tmp_path / "local-relief.curio.zip"))
    _tab(drawer, "In project").click()
    card = _card(drawer, LOCAL_RELIEF)
    expect(card).to_have_count(1, timeout=20000)

    # ...and exports it from its details, weights and all.
    card.get_by_role("button", name="View details", exact=True).click()
    modal = page.get_by_role("dialog", name="Model details")
    expect(modal).to_be_visible(timeout=10000)
    with page.expect_download(timeout=EXPORT_DOWNLOAD_TIMEOUT_MS) as download:
        modal.get_by_role("button", name="Export", exact=True).click()
    exported = tmp_path / "exported.curio.zip"
    download.value.save_as(str(exported))
    with zipfile.ZipFile(exported) as archive:
        names = set(archive.namelist())
    assert {"manifest.json", "models/local_relief.onnx"} <= names, sorted(names)

    # Account B imports that archive into a dataflow whose node loads it.
    code = (
        "import numpy as np\n"
        f'model = curio_load_model("{LOCAL_RELIEF_ID}")\n'
        'relief = model.run({"height": np.arange(64, dtype=np.float32).reshape(1, 1, 8, 8)})[0]\n'
        f'print("{RELIEF_MARKER}", tuple(relief.shape))\n'
        "return float(np.abs(relief).sum())"
    )
    _enter(page, app_frontend, current_server, username="modelcat_import", spec=_spec(code=code, node_id=RUN_NODE))
    drawer = _open_drawer(page, "Model Catalog", MODEL_DRAWER)
    _import_into_project(page, drawer, exported)
    _tab(drawer, "In project").click()
    expect(_card(drawer, LOCAL_RELIEF)).to_have_count(1, timeout=20000)
    _close_drawer(page, MODEL_DRAWER)

    text = run_node_and_wait(page, RUN_NODE, timeout_ms=180000)
    assert f"{RELIEF_MARKER} (1, 1, 8, 8)" in text, text
