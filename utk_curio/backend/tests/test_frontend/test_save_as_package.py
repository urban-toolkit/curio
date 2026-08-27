"""Playwright E2E: Save a canvas node as a package, export it, load it back.

The whole authoring loop, and the only test that walks the two-modal chain that
reaches it. There is no direct "Save as" affordance: the path is the node header
gear -> the Node settings modal -> its ``Save as package node…`` button ->
``NodeSaveAsModal``.

The Export button is new (committed in ``381d03d``) and shipped with only
source-text tests - assertions that read the ``.tsx`` off disk and grep it. This
is the first test that actually presses it.

Two behaviours make the round trip work, and both are asserted:

* **Export does not install.** ``onExport`` calls only ``factoryBuild`` +
  ``triggerBlobDownload`` - no ``factoryInstall``, no ``installToProject``, no
  registry refresh. So the package exists nowhere but the download, and loading
  it back is a clean first install (201), not the duplicate-400 that
  ``test_package_export_import.py`` covers.
* **The destination must be chosen explicitly.** ``NodeSaveAsModal`` defaults to
  the first installed *writable* package, not "New package…". Without an explicit
  selection this would export a modified copy of an existing package, whose
  coordinate is already installed - and the import would 400 for a reason with
  nothing to do with the feature.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_save_as_package.py -v
"""
from __future__ import annotations

import io
import json
import re
import zipfile
from typing import TYPE_CHECKING

import pytest
from playwright.sync_api import expect

from .utils import (
    _wait_for_reactflow_ready,
    api_json,
    open_tools_palette,
    require_project_page,
    require_user_auth,
    save_workflow_test_screenshot,
    require_owner_view,
    stub_login_and_enter_workflow,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

NODE_ID = "save-as-source-node"
# Distinctive enough to find inside the exported archive's sources/.
NODE_CODE = "MARKER_SAVE_AS_ROUNDTRIP = 41 + 1\nreturn [MARKER_SAVE_AS_ROUNDTRIP]"
NEW_PACKAGE_NAME = "Saved Roundtrip Package"

SAVE_AS_NEW = "__save_as_new__"
DRAWER_ROOT = '[data-curio-node-catalog-drawer="true"]'
# factoryUiMakeId() is Math.random-derived, so the coordinate differs every run.
DRAFT_ID_RE = re.compile(r"^curio\.canvas\.draft\.[a-z][a-z0-9-]*$")


def _spec() -> dict:
    return {
        "dataflow": {
            "name": "SaveAsSource",
            "task": "",
            "nodes": [
                {
                    "id": NODE_ID,
                    "type": "curio.builtin/computation-analysis",
                    "x": 420,
                    "y": 300,
                    "content": NODE_CODE,
                    "in": "DEFAULT",
                    "out": "DEFAULT",
                    "goal": "",
                    "metadata": {"keywords": []},
                }
            ],
            "edges": [],
        }
    }


@pytest.fixture
def uninstall_packages(current_server):
    """Remove the sideloaded clone; nothing else ever will.

    It is not in the committed catalog, so ``prune_unreferenced_packages`` cannot
    collect it, and ``.curio/users/<id>/packages/`` outlives ``reset-db`` while
    sqlite recycles user ids from 1.
    """
    registered: list[tuple[str, str, str]] = []

    def register(token: str, dir_name: str, project_id: str) -> None:
        registered.append((token, dir_name, project_id))

    yield register

    for token, dir_name, project_id in registered:
        for url in (
            f"{current_server}/api/packages/projects/{project_id}/{dir_name}",
            f"{current_server}/api/packages/{dir_name}",
        ):
            try:
                api_json(url, token, method="DELETE")
            except Exception as exc:  # noqa: BLE001 - teardown must not mask failures
                print(f"[teardown] DELETE {url} failed: {exc}")


def test_save_node_as_package_export_then_load_back(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
    tmp_path,
    uninstall_packages,
):
    require_project_page()
    require_user_auth()

    page.emulate_media(reduced_motion="reduce")
    result = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Save As User",
        username="save_as_user",
        project_name="Save As Source",
        project_spec=_spec(),
    )
    token = result["token"]
    project_id = result["project"]["id"]
    require_owner_view(page)

    node = page.locator(f'.react-flow__node[data-id="{NODE_ID}"]')
    node.wait_for(state="visible", timeout=60000)
    # Settle the canvas before clicking anything on a node. ReactFlow's initial
    # fitView animates the viewport transform, and Playwright's actionability
    # check requires a stable bounding box - a visible-but-still-moving gear
    # makes click() time out with no useful message.
    _wait_for_reactflow_ready(page)
    node.scroll_into_view_if_needed()

    # 1. The gear renders only for a node whose descriptor came from a package -
    #    builtins ship as curio.builtin@1, so a stock node qualifies. Activation
    #    is on pointerup (a press-and-drag moves the node instead), and the
    #    native click is deliberately swallowed; Playwright's click() dispatches
    #    pointerdown + pointerup at one point, so it satisfies the handler.
    gear = node.get_by_role("button", name=re.compile(r"^Node settings for "))
    expect(gear).to_be_visible(timeout=30000)
    gear.click()

    # 2. Node settings -> Save as package node… (U+2026, not three dots).
    save_as_entry = page.get_by_role("button", name="Save as package node…")
    expect(save_as_entry).to_be_visible(timeout=15000)
    save_as_entry.click()

    modal = page.get_by_role("heading", name="Save as package node", level=2).locator(
        "xpath=.."
    )
    expect(modal).to_be_visible(timeout=15000)

    # 3. Choose "New package…" explicitly - see the module docstring.
    target = modal.locator("#save-as-package-target")
    expect(target).to_be_visible()
    target.select_option(SAVE_AS_NEW)
    name_input = modal.locator("#save-as-new-package-name")
    expect(name_input).to_be_visible()
    name_input.fill(NEW_PACKAGE_NAME)

    # Visual baseline of the Save-As modal in its ready-to-export state: the
    # destination explicitly set to "New package..." and the name filled in.
    # The generated package id is random per run but is not displayed here, so
    # the capture stays deterministic.
    save_workflow_test_screenshot(
        page, "save-as-modal", test_name="test_save_node_as_package_export_then_load_back",
    )

    # 4. Export. Never hard-code the filename: the package id is randomised per
    #    Save-As, so the archive is curio.canvas.draft.<random>@1-0.1.0.curio.zip.
    with page.expect_download(timeout=60000) as download:
        modal.get_by_role("button", name="Export", exact=True).click()

    filename = download.value.suggested_filename
    assert filename.endswith(".curio.zip"), filename
    saved = tmp_path / filename
    download.value.save_as(str(saved))

    expect(page.get_by_label("Notifications")).to_contain_text(
        f"Exported {filename}.", timeout=20000
    )
    # Export is not a commit, so unlike Save it leaves the modal open.
    expect(modal).to_be_visible()

    # 5. Validate the archive in Python.
    archive = saved.read_bytes()
    with zipfile.ZipFile(io.BytesIO(archive)) as zf:
        assert zf.testzip() is None, "exported archive has a corrupt member"
        names = set(zf.namelist())
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        sources = {
            n: zf.read(n).decode("utf-8") for n in names if n.startswith("sources/")
        }

    assert DRAFT_ID_RE.match(manifest["id"]), manifest["id"]
    assert manifest["name"] == NEW_PACKAGE_NAME, manifest["name"]
    assert len(manifest["templates"]) == 1, manifest["templates"]
    assert "integrity.json" not in names, names
    # The canvas node's body is what got packaged - not a starter placeholder.
    assert any("MARKER_SAVE_AS_ROUNDTRIP" in body for body in sources.values()), sources

    dir_name = f"{manifest['id']}@{manifest['compatibility']['major']}"

    # 6. Export must NOT have installed anything: that is what makes the import
    #    below a clean first install rather than a duplicate. If this fails, step
    #    8 would be testing nothing.
    installed_ids = {
        p["packageId"] for p in api_json(f"{current_server}/api/packages", token)["packages"]
    }
    assert manifest["id"] not in installed_ids, (
        f"Export installed {dir_name}; it should only produce a download"
    )

    # 7. Close the Save-As modal before touching the drawer.
    modal.get_by_role("button", name="Cancel", exact=True).click()
    expect(modal).to_have_count(0, timeout=10000)

    # 8. Load it back through the Node Catalog drawer footer.
    uninstall_packages(token, dir_name, project_id)
    page.get_by_role("button", name="Data ⏷", exact=True).click(force=True)
    page.get_by_role("button", name="Node Catalog", exact=True).click()
    drawer = page.get_by_role("dialog").filter(
        has=page.get_by_role("heading", name="Node Catalog", exact=True)
    )
    expect(drawer).to_be_visible(timeout=15000)

    with page.expect_response(
        lambda r: r.url.endswith("/api/packages/upload")
        and r.request.method == "POST",
        timeout=60000,
    ) as upload:
        with page.expect_file_chooser() as chooser:
            drawer.get_by_role("button", name="Import package").click()
        chooser.value.set_files(str(saved))

    assert upload.value.status == 201, upload.value.text()[:500]

    # 9. It is a real installed package now: listed under "In dataflow" (which
    #    renders MyPackagesList, so the per-row Remove label is the stable hook)
    #    and present in the palette, since onPickArchive also writes the lockfile.
    drawer.get_by_role("navigation", name="Catalog sections").get_by_role(
        "button", name="In dataflow"
    ).click()
    expect(
        drawer.get_by_role("button", name=f"Remove {NEW_PACKAGE_NAME}", exact=True)
    ).to_be_visible(timeout=30000)

    drawer.locator("header").get_by_role(
        "button", name="Close Node Catalog drawer"
    ).click()
    expect(page.locator(DRAWER_ROOT)).to_have_count(0, timeout=5000)

    palette = open_tools_palette(page, "packages")
    expect(
        palette.locator(f'[data-pkg-palette-coords~="{dir_name}"]')
    ).to_have_count(1, timeout=30000)

    lockfile = api_json(
        f"{current_server}/api/packages/projects/{project_id}", token
    )["packages"]
    assert dir_name in lockfile, lockfile
