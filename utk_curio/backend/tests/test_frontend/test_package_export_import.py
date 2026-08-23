"""Playwright E2E: exporting a package and loading it back in.

Export is the one part of this flow only a browser can prove. It is not a
navigation to the archive endpoint — ``packagesApi.downloadArchive`` fetches with
a bearer token, then ``triggerBlobDownload`` builds an object URL on a detached
``<a download>``, clicks it, and revokes the URL on the very next line. Nothing
below the browser exercises that, and the e2e suite had never tested a download
at all.

Import is covered here for its *drawer-specific* behaviour: the error banner a
duplicate produces, and the lockfile + palette wiring a fresh coordinate gets.

Covered more cheaply and not re-asserted here: the byte-level round trip and the
duplicate-rejection semantics live in ``test_packages/test_installer.py``
(including the renamed-archive fork), and the ``Content-Disposition`` header in
``test_packages/test_routes.py`` — the client synthesises its own filename and
ignores that header, so no browser test could observe it.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_package_export_import.py -v
"""
from __future__ import annotations

import io
import json
import zipfile
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
PKG_NAME = "Example: Custom UI Node"
EXPORT_LABEL = f"Export {PKG_NAME} as a .curio.zip archive"

CLONE_ID = "e2e.roundtrip-pkg"
CLONE_DIR = f"{CLONE_ID}@1"
CLONE_NAME = "Roundtrip Clone"

DRAWER_ROOT = '[data-curio-node-catalog-drawer="true"]'


@pytest.fixture
def uninstall_packages(current_server):
    """Remove packages this test installed, through the real routes.

    The sideloaded clone is not in the catalog, so ``prune_unreferenced_packages``
    will never collect it — and ``.curio/users/<id>/packages/`` outlives
    ``reset-db`` while sqlite recycles user ids from 1.
    """
    registered: list[tuple[str, str, str | None]] = []  # (token, dirName, projectId)

    def register(token: str, dir_name: str, project_id: str | None = None) -> None:
        registered.append((token, dir_name, project_id))

    yield register

    for token, dir_name, project_id in registered:
        for url in (
            f"{current_server}/api/packages/projects/{project_id}/{dir_name}"
            if project_id
            else None,
            f"{current_server}/api/packages/{dir_name}",
        ):
            if not url:
                continue
            try:
                api_json(url, token, method="DELETE")
            except Exception as exc:  # noqa: BLE001 - teardown must not mask failures
                print(f"[teardown] DELETE {url} failed: {exc}")


def _one_node_spec() -> dict:
    """A single node so the canvas is not empty.

    ``save_workflow_test_screenshot`` pins the viewport with
    ``_wait_for_reactflow_ready`` before capturing, and that waits for at least
    one ``.react-flow__node``. An empty dataflow therefore times out. A node also
    makes the baseline more useful: it shows the drawer against real canvas
    content rather than blank space.
    """
    return {
        "dataflow": {
            "name": "CatalogBaseline",
            "task": "",
            "nodes": [
                {
                    "id": "catalog-baseline-node",
                    "type": "curio.builtin/computation-analysis",
                    "x": 420,
                    "y": 300,
                    "content": "return [1]",
                    "in": "DEFAULT",
                    "out": "DEFAULT",
                    "goal": "",
                    "metadata": {"keywords": []},
                }
            ],
            "edges": [],
        }
    }


def _enter_dataflow(page, app_frontend, current_server, *, username):
    """One stub user PER TEST.

    Sharing a username across tests in a file is a 401 waiting to happen:
    ``e2e_clean_db`` truncates ``user``/``user_session`` between tests and sqlite
    recycles the id, so the second login lands on a coordinate the backend has
    already seen. Every other file here gives each test its own name.
    """
    page.emulate_media(reduced_motion="reduce")
    result = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Export User",
        username=username,
        project_name="Package Export",
        project_spec=_one_node_spec(),
    )
    skip_if_shared_view(page)
    return result


def _drawer(page):
    page.locator(DRAWER_ROOT).wait_for(state="attached", timeout=15000)
    dialog = page.get_by_role("dialog").filter(
        has=page.get_by_role("heading", name="Node Catalog", exact=True)
    )
    expect(dialog).to_be_visible(timeout=10000)
    return dialog


def _open_drawer_from_menu(page):
    page.get_by_role("button", name="Data ⏷", exact=True).click(force=True)
    page.get_by_role("button", name="Node Catalog", exact=True).click()
    return _drawer(page)


def _close_drawer(page, drawer):
    # Scoped to <header>: the scrim carries the same aria-label as the real
    # close button, so a page-level lookup is a strict-mode violation.
    drawer.locator("header").get_by_role(
        "button", name="Close Node Catalog drawer"
    ).click()
    expect(page.locator(DRAWER_ROOT)).to_have_count(0, timeout=5000)


def _import_archive(page, drawer, path):
    with page.expect_file_chooser() as chooser:
        drawer.get_by_role("button", name="Import package").click()
    chooser.value.set_files(str(path))


def _rewrite_package_id(archive: bytes, new_id: str, new_name: str) -> bytes:
    """Copy the archive, changing only manifest.json's id and name.

    ``dir_name`` is derived purely from the manifest and nothing verifies
    integrity on install, so this yields an independent package rather than a
    collision — which is what makes export -> edit -> re-import usable at all
    (there is no UI path that sets ``replace=true``).
    """
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(archive)) as src:
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
            for item in src.infolist():
                body = src.read(item.filename)
                if item.filename == "manifest.json":
                    manifest = json.loads(body.decode("utf-8"))
                    manifest["id"] = new_id
                    manifest["name"] = new_name
                    body = json.dumps(manifest, indent=2).encode("utf-8")
                dst.writestr(item.filename, body)
    return out.getvalue()


def test_export_then_load_package_through_node_catalog(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
    tmp_path,
    uninstall_packages,
):
    require_project_page()
    require_user_auth()
    result = _enter_dataflow(
        page, app_frontend, current_server, username="pkg_roundtrip_user"
    )
    token = result["token"]
    project_id = result["project"]["id"]

    # 1. Seed over the API rather than driving the drawer twice: the export
    #    affordance only exists for a package in BOTH the user store and this
    #    project's lockfile, and only curio.builtin is seeded by default.
    #    curio.example-ui@1 declares no python deps, so nothing reaches pip.
    catalog = api_json(f"{current_server}/api/packages/catalog", token)
    row = next(p for p in catalog["packages"] if p["dirName"] == PKG_DIR)
    assert row["dependencies"]["python"] == {}, row["dependencies"]["python"]
    api_json(
        f"{current_server}/api/packages/projects/{project_id}/install",
        token,
        method="POST",
        payload={"dirName": PKG_DIR},
        timeout=120.0,
    )
    uninstall_packages(token, PKG_DIR, project_id)
    page.reload()
    page.wait_for_load_state("domcontentloaded")

    # 2. Export. The button lives in the <summary> of the palette accordion, so
    #    it is reachable without expanding. Its accessible name uses the manifest
    #    NAME while the row is keyed by dirName.
    palette = open_tools_palette(page, "packages")
    row_locator = palette.locator(f'[data-pkg-palette-coords~="{PKG_DIR}"]')
    expect(row_locator).to_have_count(1, timeout=20000)

    with page.expect_download(timeout=30000) as download:
        row_locator.get_by_role("button", name=EXPORT_LABEL).click()

    # The filename is computed client-side as `${dirName}.curio.zip`; the
    # Content-Disposition header is ignored on this path.
    assert download.value.suggested_filename == f"{PKG_DIR}.curio.zip"
    saved = tmp_path / download.value.suggested_filename
    download.value.save_as(str(saved))

    # Export is otherwise silent, so the absence of the failure toast is the
    # only other signal available.
    expect(
        page.get_by_label("Notifications").get_by_text("Couldn't export")
    ).to_have_count(0)

    # 3. Validate the artifact in Python, not the browser.
    archive = saved.read_bytes()
    # triggerBlobDownload revokes the object URL on the line after a.click(), so
    # a truncated download is the one real flake risk on this path. Compare
    # against the endpoint's own bytes and verify every CRC before trusting it.
    direct = api_json(
        f"{current_server}/api/packages/{PKG_DIR}/archive", token, raw=True
    )
    assert len(archive) == len(direct), (
        f"downloaded {len(archive)} bytes but the endpoint served {len(direct)} — "
        f"the blob was revoked before Chromium finished reading it"
    )
    with zipfile.ZipFile(io.BytesIO(archive)) as zf:
        assert zf.testzip() is None, "downloaded archive has a corrupt member"
        names = set(zf.namelist())
    assert "manifest.json" in names, names
    assert any(n.startswith("sources/") for n in names), names
    # Hashes describe files as installed; an archive never carries them.
    assert "integrity.json" not in names, names

    # 4. Negative leg: re-importing the same coordinate is a guaranteed 400.
    #    onPickArchive never sets replace=true and no UI path does, so this is
    #    the real user-visible outcome of "export then put it back".
    drawer = _open_drawer_from_menu(page)
    _import_archive(page, drawer, saved)
    banner = drawer.locator('[role="alert"]')
    expect(banner).to_be_visible(timeout=30000)
    expect(banner).to_contain_text("already installed")
    expect(banner).to_contain_text(PKG_DIR)

    lock_after_reject = api_json(
        f"{current_server}/api/packages/projects/{project_id}", token
    )["packages"]
    assert PKG_DIR in lock_after_reject
    assert CLONE_DIR not in lock_after_reject

    # 5. Positive leg: a renamed clone installs alongside and wires up fully.
    # Clear the failure banner first, the way a user would — and so a stuck
    # `busy` state or an intercepted click surfaces here rather than as an
    # unexplained timeout on the upload below.
    drawer.get_by_role("button", name="Dismiss error").click()
    expect(banner).to_have_count(0, timeout=10000)
    expect(drawer.get_by_role("button", name="Import package")).to_be_enabled()

    clone = tmp_path / f"{CLONE_DIR}.curio.zip"
    clone.write_bytes(_rewrite_package_id(archive, CLONE_ID, CLONE_NAME))
    uninstall_packages(token, CLONE_DIR, project_id)

    with page.expect_response(
        lambda r: r.url.endswith("/api/packages/upload")
        and r.request.method == "POST"
        and r.ok,
        timeout=60000,
    ):
        _import_archive(page, drawer, clone)

    # The clone is sideloaded, so it shows under "In dataflow" but never under
    # Browse, which lists the committed packages/ catalog. That tab renders
    # MyPackagesList rather than PackageCard, so there is no data-pkg-dir to key
    # on — the per-row Remove control's aria-label is the stable hook.
    tabs = drawer.get_by_role("navigation", name="Catalog sections")
    tabs.get_by_role("button", name="In dataflow").click()
    expect(
        drawer.get_by_role("button", name=f"Remove {CLONE_NAME}", exact=True)
    ).to_be_visible(timeout=30000)

    # 6. onPickArchive also writes the project lockfile — without that the
    #    package would be invisible in-project, since refreshPackageRegistry
    #    intersects the user store with the lockfile.
    _close_drawer(page, drawer)
    expect(
        page.locator(f'#packages-palette [data-pkg-palette-coords~="{CLONE_DIR}"]')
    ).to_have_count(1, timeout=30000)

    lock_final = api_json(
        f"{current_server}/api/packages/projects/{project_id}", token
    )["packages"]
    assert {PKG_DIR, CLONE_DIR} <= set(lock_final), lock_final

    # 7. The clone is exportable in turn — the round trip closes.
    clone_row = page.locator(
        f'#packages-palette [data-pkg-palette-coords~="{CLONE_DIR}"]'
    )
    expect(
        clone_row.get_by_role(
            "button", name=f"Export {CLONE_NAME} as a .curio.zip archive"
        )
    ).to_be_visible(timeout=20000)


def test_export_from_the_drawer_in_dataflow_tab(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
    tmp_path,
    uninstall_packages,
):
    """The drawer's own export control, distinct from the palette accordion's.

    ``MyPackagesList`` has always rendered an export button when handed a
    handler, but ``NodeCatalogDrawer`` never passed one — so the affordance was
    dead code and the palette was the only route to an archive. Now that it is
    wired, this is the test that keeps it wired: nothing else would notice the
    prop being dropped again, because a missing button is not an error.

    Deliberately a second test rather than an extra leg on the round-trip above:
    it asserts the *same* archive is reachable from a *different* surface, so
    coupling them would hide which one broke.
    """
    require_project_page()
    require_user_auth()
    result = _enter_dataflow(
        page, app_frontend, current_server, username="pkg_drawer_export_user"
    )
    token = result["token"]
    project_id = result["project"]["id"]

    api_json(
        f"{current_server}/api/packages/projects/{project_id}/install",
        token,
        method="POST",
        payload={"dirName": PKG_DIR},
        timeout=120.0,
    )
    uninstall_packages(token, PKG_DIR, project_id)
    page.reload()
    page.wait_for_load_state("domcontentloaded")

    drawer = _open_drawer_from_menu(page)
    # The export control lives on the "In dataflow" rows, which render
    # MyPackagesList (no data-pkg-dir there) — the aria-label uses the manifest
    # NAME, while the palette accordion's uses a longer ".curio.zip archive" form.
    drawer.get_by_role("navigation", name="Catalog sections").get_by_role(
        "button", name="In dataflow"
    ).click()
    export_button = drawer.get_by_role("button", name=f"Export {PKG_NAME}", exact=True)
    expect(export_button).to_be_visible(timeout=30000)

    # Visual baseline of the In dataflow tab with its row actions. This is the
    # surface whose export control was dead code until it was wired, so a
    # baseline here records what "wired" looks like.
    save_workflow_test_screenshot(
        page, "package-export-drawer",
        test_name="test_export_from_the_drawer_in_dataflow_tab",
    )

    with page.expect_download(timeout=30000) as download:
        export_button.click()

    assert download.value.suggested_filename == f"{PKG_DIR}.curio.zip"
    saved = tmp_path / download.value.suggested_filename
    download.value.save_as(str(saved))

    # Same bytes the endpoint serves, and a complete archive — the blob URL is
    # revoked on the line after the click, so a truncated download is the one
    # real hazard on this path.
    direct = api_json(
        f"{current_server}/api/packages/{PKG_DIR}/archive", token, raw=True
    )
    archive = saved.read_bytes()
    assert len(archive) == len(direct), (
        f"downloaded {len(archive)} bytes but the endpoint served {len(direct)}"
    )
    with zipfile.ZipFile(io.BytesIO(archive)) as zf:
        assert zf.testzip() is None, "downloaded archive has a corrupt member"
        names = set(zf.namelist())
    assert "manifest.json" in names, names
    assert "integrity.json" not in names, names

    expect(
        page.get_by_label("Notifications").get_by_text("Couldn't export")
    ).to_have_count(0)

