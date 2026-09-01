"""Playwright E2E: a package authored from the canvas, then built with and run.

The subject is the far end of the authoring loop: after a round trip through an
archive, does a kind that came from someone's canvas node actually *work* for the
person who imports it? So the payoff here is the last third - the imported kind
is dragged in twice, chained onto a catalog dataset, run, and checked against the
numbers the original node produced, then persisted into the consuming dataflow's
spec. Nothing else in the suite runs a package node at all.

Two neighbours own the middle of this journey, and this test defers to both
rather than re-asserting them:

* ``test_save_as_package.py`` owns the two-modal Save-As chain and the modal's
  *Export* button - which deliberately does not install, so its archive is a
  clean first import. This test takes the other branch: **Save** (which does
  install) followed by the palette accordion's own export control.
* ``test_package_export_import.py`` owns the export/import mechanics: the
  download bytes against the endpoint's own, the duplicate-coordinate rejection
  banner, and the renamed-clone install. So the archive is validated here only
  enough to trust the bytes being re-imported.

``test_packages/test_installer.py`` owns the byte-level round trip.

Both halves live in one test because the archive is a *browser download*. There
is no server-side artifact to hand to a second test, and the autouse
``e2e_clean_db`` truncates the user and project between tests, so a producer test
could not hand its session to a consumer test even if the bytes survived.

The store-level uninstall in between is required, not tidiness. Saving from the
canvas installs the package it just built under a generated id
(``curio.canvas.draft.<slug>@1``, so the name typed into the modal is only a
display name), and the upload route rejects an archive whose id is already in the
store. Without the delete the import fails as a collision instead of testing
anything, and with it the importing side genuinely starts without the package.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_package_roundtrip_e2e.py -v
"""
from __future__ import annotations

import io
import re
import zipfile
from typing import TYPE_CHECKING

import pytest
from playwright.sync_api import expect

from .utils import (
    accept_confirm_dialog,
    activate_header_icon,
    api_json,
    connect_nodes,
    drag_to_canvas,
    open_tools_palette,
    require_project_page,
    require_user_auth,
    run_node_and_wait,
    save_workflow_test_screenshot,
    set_node_code,
    require_owner_view,
    stub_login_and_enter_workflow,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

DATASET_ID = "data.urbanlab.acs-neighborhood-profile"
DATASET_ROWS = 3  # rows in the committed CSV fixture

PACKAGE_NAME = "E2E Roundtrip"
# A label distinct from the built-in default, for two reasons: the palette row is
# located by it, and NodeSaveAsModal decides between "add a kind" and "replace a
# kind" by matching the node's label against the target package's kinds.
HEAD_LABEL = "E2E Head"

TRANSFORM_TILE = "#step-transformation"
TRANSFORM_TYPE = "curio.builtin/data-transformation"
LOADER_TYPE = "curio.builtin/data-loading"

# The inline output box shows stdout plus "Saved to file: …" - never the return
# value itself - so a result assertion has to print what it wants to check.
HEAD_MARKER = "E2E_HEAD_ROWS"
HEAD_CODE = (
    "df = arg\n"
    f'print("{HEAD_MARKER}", len(df))\n'
    "return df.head(2)\n"
)

DATASET_DRAWER = '[data-curio-dataset-catalog-drawer="true"]'
PACKAGE_DRAWER = '[data-curio-node-catalog-drawer="true"]'
CARD = 'article:not([role="status"])'

# Node geometry: 525x350 at zoom 1 in a 1280x720 viewport. These three offsets
# keep every facing pair of handles unobstructed and on screen; see
# ``connect_nodes``, which refuses to drag from a covered handle.
POS_LOADER = (40, 30)
POS_FIRST = (660, 30)
POS_SECOND = (40, 390)


# ---------------------------------------------------------------------------
# Drawer / palette helpers
# ---------------------------------------------------------------------------

def _dataset_drawer(page):
    root = page.locator(DATASET_DRAWER)
    root.wait_for(state="attached", timeout=15000)
    # aria-hidden IS the presented signal: until the rAF flips it, every role
    # query inside the subtree returns zero matches.
    expect(root).to_have_attribute("aria-hidden", "false", timeout=10000)
    dialog = page.get_by_role("dialog").filter(
        has=page.get_by_role("heading", name="Data Catalog", exact=True)
    )
    expect(dialog).to_be_visible(timeout=10000)
    return dialog


def _open_package_drawer(page, project_id: str):
    """Data menu -> Node Catalog, not returning until the drawer has a project.

    ``projectId`` reaches the drawer through FlowContext only once
    ``loadProject`` resolves, and ``onPickArchive`` skips the lockfile write
    entirely when it is still null - the archive installs into the user store and
    then stays invisible, because ``refreshPackageRegistry`` intersects the store
    with the project lockfile. The drawer's own
    ``GET /api/packages/projects/<id>`` fires exactly when it learns the project,
    which makes that response the precondition to wait for.
    """
    page.get_by_role("button", name="Data ⏷", exact=True).click(force=True)
    with page.expect_response(
        lambda r: f"/api/packages/projects/{project_id}" in r.url
        and r.request.method == "GET",
        timeout=30000,
    ):
        page.get_by_role("button", name="Node Catalog", exact=True).click()

    page.locator(PACKAGE_DRAWER).wait_for(state="attached", timeout=15000)
    # Resolved by heading: the install dialog is also a role="dialog" but carries
    # no accessible name, so a bare get_by_role would be a strict-mode violation
    # whenever it is open.
    dialog = page.get_by_role("dialog").filter(
        has=page.get_by_role("heading", name="Node Catalog", exact=True)
    )
    expect(dialog).to_be_visible(timeout=10000)
    return dialog


def _add_dataset_and_get_palette_row(page):
    """Add the hub dataset to the current dataflow; return its palette row."""
    palette = open_tools_palette(page, "datasets")
    palette.get_by_role("button", name="Browse Data Catalog +").click(force=True)
    drawer = _dataset_drawer(page)
    card = drawer.locator(f'{CARD}[data-dataset-id="{DATASET_ID}"]')
    expect(card).to_have_count(1, timeout=15000)

    card.get_by_role("button", name="Add to dataflow", exact=True).click()
    with page.expect_response(
        lambda r: "/datasets/install" in r.url and r.request.method == "POST" and r.ok,
        timeout=60000,
    ):
        # The Data catalog confirms an add now (#196), so the card click only
        # opens the dialog - the POST follows the confirm.
        accept_confirm_dialog(
            page, title=re.compile(r"^Add "), button="Add to dataflow"
        )

    # Re-resolve rather than reuse the handle: the install flips origin
    # hub -> imported, which changes the React key so the card is replaced.
    expect(
        drawer.locator(f'{CARD}[data-dataset-id="{DATASET_ID}"]').get_by_role(
            "button", name="Remove from dataflow", exact=True
        )
    ).to_be_visible(timeout=20000)

    # This drawer has no Escape handler, so close through the header button.
    drawer.locator("header").get_by_role(
        "button", name="Close Data Catalog drawer"
    ).click()
    expect(page.locator(DATASET_DRAWER)).to_have_count(0, timeout=5000)

    row = page.locator(f'#datasets-palette [data-dataset-id="{DATASET_ID}"]')
    expect(row).to_have_count(1, timeout=20000)
    return row


def _package_anchor(page, dir_name):
    """The palette block for one installed package (summary actions + kind rows)."""
    return page.locator(f'#packages-palette [data-pkg-palette-coords~="{dir_name}"]')


def _expand_package(anchor) -> None:
    """Open the palette accordion so its kind rows are draggable.

    The rows are always in the DOM (a ``<details>`` body), so a count assertion
    passes while the accordion is shut; only a drag needs them visible.
    """
    details = anchor.locator("details").first
    details.wait_for(state="attached", timeout=15000)
    if not details.evaluate("(el) => el.open"):
        anchor.locator("summary").first.click(force=True)
    expect(details).to_have_attribute("open", "", timeout=10000)


def _template_row(anchor, label):
    """The palette row for one kind, located by its visible label.

    ``data-pkg-template-id`` sits on the drag grip while the label lives in the
    grip's sibling button, so the row wrapper is what carries both. Returning the
    wrapper is enough: ``drag_to_canvas`` resolves the ``[draggable]`` inside it.
    """
    return anchor.locator("div:has(> [data-pkg-template-id])").filter(has_text=label)


# ---------------------------------------------------------------------------
# Save-as-package helpers
# ---------------------------------------------------------------------------

def _rename_node(page, node_id, label):
    node_el = page.locator(f'.react-flow__node[data-id="{node_id}"]')
    activate_header_icon(node_el.locator('button[aria-label^="Edit node title:"]'))
    # Not get_by_label("Node title"): that substring-matches the pencil button's
    # own "Edit node title: …" label as well.
    title_input = node_el.locator('input[aria-label="Node title"]')
    title_input.fill(label)
    title_input.press("Enter")
    expect(
        node_el.locator(f'button[aria-label="Edit node title: {label}"]')
    ).to_be_visible(timeout=10000)


def _save_into_package(page, node_id, *, new_package: str | None = None,
                       existing: str | None = None) -> str:
    """Save one canvas node as a package kind; return the package's dirName."""
    node_el = page.locator(f'.react-flow__node[data-id="{node_id}"]')
    activate_header_icon(node_el.locator('button[aria-label^="Node settings for"]'))
    expect(page.get_by_role("heading", name="Node settings")).to_be_visible(
        timeout=10000
    )
    # Matched by prefix: the label ends in a U+2026 ellipsis.
    page.get_by_role("button", name=re.compile("^Save as package node")).click()
    expect(page.get_by_role("heading", name="Save as package node")).to_be_visible(
        timeout=10000
    )

    target = page.locator("#save-as-package-target")
    if new_package is not None:
        # "New package…" is always the first option; selecting by label would
        # depend on the ellipsis character.
        target.select_option(index=0)
        page.locator("#save-as-new-package-name").fill(new_package)
    else:
        labels = target.locator("option").all_text_contents()
        match = next((label for label in labels if existing in label), None)
        assert match, f"{existing!r} is not offered as a destination: {labels}"
        target.select_option(label=match)

    with page.expect_response(
        lambda r: r.url.endswith("/api/packages/factory/install")
        and r.request.method == "POST",
        timeout=60000,
    ) as installed:
        # "Save" for a new kind, "Replace" when the label already exists - a
        # distinct label means this is always Save, and asserting the button's
        # text is how we notice if that stops being true.
        save_btn = page.get_by_role("button", name="Save", exact=True)
        expect(save_btn).to_be_visible()
        save_btn.click()

    response = installed.value
    assert response.ok, (
        f"factory install failed ({response.status}): {response.text()[:500]}"
    )
    expect(page.get_by_role("heading", name="Save as package node")).to_have_count(
        0, timeout=20000
    )
    return response.json()["package"]["dirName"]


@pytest.fixture
def uninstall_packages(current_server):
    """Remove packages this test installed, through the real DELETE route.

    Mandatory, not hygiene: the store lives at ``.curio/users/<id>/packages/``
    and survives ``reset-db`` while sqlite recycles user ids from 1. Every save
    mints a fresh generated id, so a leak does not collide with the next run -
    it just accumulates dead packages in the palette of every later test.
    """
    registered: dict[str, str] = {}
    yield lambda token, dir_name: registered.setdefault(dir_name, token)
    for dir_name, token in registered.items():
        try:
            api_json(
                f"{current_server}/api/packages/{dir_name}", token, method="DELETE",
                timeout=60.0,
            )
        except Exception as exc:  # noqa: BLE001 - teardown must not mask failures
            print(f"[teardown] DELETE package {dir_name} failed: {exc}")


def test_save_export_import_and_run_package_nodes(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
    tmp_path,
    uninstall_packages,
):
    require_project_page()
    require_user_auth()

    # Before navigating: the drawers slide via translate3d, so to_be_visible is
    # not a gate on its own, and the provider reads prefers-reduced-motion
    # through useSyncExternalStore.
    page.emulate_media(reduced_motion="reduce")
    session = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Package Author",
        username="package_author",
        project_name="Package Roundtrip",
    )
    require_owner_view(page)
    token = session["token"]

    # ------------------------------------------------------------------
    # PRODUCER: a working node on top of a catalog dataset
    # ------------------------------------------------------------------
    dataset_row = _add_dataset_and_get_palette_row(page)
    loader_id = drag_to_canvas(page, dataset_row, at=POS_LOADER)
    head_id = drag_to_canvas(page, page.locator(TRANSFORM_TILE), at=POS_FIRST)
    connect_nodes(page, loader_id, head_id)
    set_node_code(page, head_id, HEAD_CODE)
    _rename_node(page, head_id, HEAD_LABEL)

    run_node_and_wait(page, loader_id, node_type=LOADER_TYPE)
    head_output = run_node_and_wait(page, head_id, node_type=TRANSFORM_TYPE)
    # The baseline the imported copy has to reproduce.
    assert f"{HEAD_MARKER} {DATASET_ROWS}" in head_output, head_output

    # ------------------------------------------------------------------
    # PACKAGE: the canvas node becomes a kind
    # ------------------------------------------------------------------
    dir_name = _save_into_package(page, head_id, new_package=PACKAGE_NAME)
    uninstall_packages(token, dir_name)

    open_tools_palette(page, "packages")
    anchor = _package_anchor(page, dir_name)
    expect(anchor).to_have_count(1, timeout=20000)
    expect(_template_row(anchor, HEAD_LABEL)).to_have_count(1, timeout=20000)

    # ------------------------------------------------------------------
    # EXPORT: a real browser download, the only way to get the bytes
    # ------------------------------------------------------------------
    with page.expect_download(timeout=60000) as download:
        anchor.locator('button[title="Export package"]').click(force=True)
    archive = tmp_path / "roundtrip.curio.zip"
    download.value.save_as(archive)
    # Only a sanity check on the bytes about to be re-imported; the download path
    # itself is test_package_export_import.py's subject.
    with zipfile.ZipFile(archive) as zf:
        assert zf.testzip() is None, "downloaded archive has a corrupt member"
        assert "manifest.json" in set(zf.namelist()), zf.namelist()

    # ------------------------------------------------------------------
    # BRIDGE: drop the store copy, so the import is a real first install
    # ------------------------------------------------------------------
    api_json(f"{current_server}/api/packages/{dir_name}", token, method="DELETE")
    page.reload()
    page.wait_for_load_state("domcontentloaded")
    open_tools_palette(page, "packages")
    expect(_package_anchor(page, dir_name)).to_have_count(0, timeout=20000)

    # ------------------------------------------------------------------
    # CONSUMER: a fresh empty dataflow that imports the archive and uses it
    # ------------------------------------------------------------------
    # A stubbed project for the same user, which is how every other test in the
    # suite gets an empty canvas, and it keeps this test off two things that are
    # someone else's subject: creating a dataflow through the File menu
    # (test_project_save_load.py) and saving a still-empty one, which did not
    # reliably leave /dataflow/new while this test was being written.
    #
    # It also wants to be an already-saved dataflow. Both catalogs can add to an
    # unsaved one - ``onInstall`` calls ``ensureProjectId``, which creates the
    # project on demand - but ``onPickArchive`` has no such fallback: its
    # ``installToProject`` step is skipped outright when ``projectId`` is null, so
    # the archive would install into the user store and stay invisible on the
    # canvas.
    consumer = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Package Author",
        username="package_author",
        project_name="Package Consumer",
    )
    token = consumer["token"]
    consumer_project_id = consumer["project"]["id"]

    drawer = _open_package_drawer(page, consumer_project_id)
    # Importing is two requests, and the second is the one that matters here:
    # the upload writes the user store, then installToProject writes the
    # dataflow's lockfile. Waiting only for the upload leaves the lockfile query
    # below racing a request that has not been sent yet.
    with page.expect_response(
        lambda r: f"/api/packages/projects/{consumer_project_id}/install" in r.url
        and r.request.method == "POST",
        timeout=60000,
    ) as installed_to_project:
        with page.expect_response(
            # /api/packages/upload, not /api/packages: sideloading an archive is
            # its own multipart route.
            lambda r: "/api/packages/upload" in r.url and r.request.method == "POST",
            timeout=60000,
        ) as uploaded:
            with page.expect_file_chooser() as chooser:
                drawer.get_by_role("button", name="Import package").click()
            chooser.value.set_files(str(archive))
    assert uploaded.value.ok, (
        f"import failed ({uploaded.value.status}): {uploaded.value.text()[:500]}"
    )
    assert installed_to_project.value.ok, (
        f"the import did not reach the dataflow's lockfile "
        f"({installed_to_project.value.status}): "
        f"{installed_to_project.value.text()[:500]}"
    )
    uninstall_packages(token, dir_name)
    # Server truth: the archive installed under the same coordinate it was
    # exported from. Not asserted through a drawer card, because the drawer's
    # cards are catalog entries and a sideloaded archive is never one.
    assert uploaded.value.json()["package"]["dirName"] == dir_name
    expect(drawer.locator('[role="alert"]')).to_have_count(0)

    # The import also has to write the project lockfile, because
    # refreshPackageRegistry intersects the user store with it - a package
    # missing here installed fine and is still invisible on the canvas.
    lockfile = api_json(
        f"{current_server}/api/packages/projects/{consumer_project_id}", token
    )["packages"]
    assert dir_name in lockfile, (
        f"the imported package is not in the consuming dataflow's lockfile: "
        f"{lockfile}"
    )

    drawer.locator("header").get_by_role(
        "button", name="Close Node Catalog drawer"
    ).click()
    expect(page.locator(PACKAGE_DRAWER)).to_have_count(0, timeout=5000)

    # THE POINT: the kind is in the palette with no reload, and it carries the
    # code it was saved with. Dragged twice and chained, so the assertion covers
    # both "a package node runs" and "one feeds another".
    consumer_row = _add_dataset_and_get_palette_row(page)
    new_loader = drag_to_canvas(page, consumer_row, at=POS_LOADER)

    open_tools_palette(page, "packages")
    anchor = _package_anchor(page, dir_name)
    expect(anchor).to_have_count(1, timeout=20000)
    _expand_package(anchor)
    head_row = _template_row(anchor, HEAD_LABEL)
    expect(head_row).to_have_count(1, timeout=20000)
    first_id = drag_to_canvas(page, head_row, at=POS_FIRST)
    second_id = drag_to_canvas(page, head_row, at=POS_SECOND)

    connect_nodes(page, new_loader, first_id)
    connect_nodes(page, first_id, second_id)

    run_node_and_wait(page, new_loader, node_type=LOADER_TYPE)
    first_output = run_node_and_wait(page, first_id, node_type=TRANSFORM_TYPE)
    second_output = run_node_and_wait(page, second_id, node_type=TRANSFORM_TYPE)
    # The whole dataset reaches the first copy, and its head(2) reaches the
    # second - so the imported kind both runs and propagates.
    assert f"{HEAD_MARKER} {DATASET_ROWS}" in first_output, first_output
    assert f"{HEAD_MARKER} 2" in second_output, second_output

    # And the consuming dataflow persists the imported kinds, so a reload gets
    # the same graph back rather than three dangling node types.
    page.get_by_role("button", name=re.compile("File")).click(force=True)
    save_btn = page.get_by_role("button", name="Save dataflow", exact=True)
    save_btn.wait_for(state="visible", timeout=10000)
    with page.expect_response(
        lambda r: f"/api/projects/{consumer_project_id}" in r.url
        and r.request.method in ("PUT", "PATCH")
        and r.ok,
        timeout=30000,
    ):
        save_btn.click()

    spec = api_json(
        f"{current_server}/api/projects/{consumer_project_id}", token
    )["spec"]
    dataflow = spec["dataflow"]
    assert len(dataflow["nodes"]) == 3, dataflow["nodes"]
    assert len(dataflow["edges"]) == 2, dataflow["edges"]
    package_id = dir_name.split("@", 1)[0]
    from_package = [
        node for node in dataflow["nodes"]
        if str(node.get("type", "")).startswith(package_id)
    ]
    assert len(from_package) == 2, (
        f"expected both package nodes in the saved spec, got "
        f"{[node.get('type') for node in dataflow['nodes']]}"
    )
    # Visual baseline for a canvas nobody hand-checks otherwise. The semantic
    # assertions above cover what each node computed; this covers what the
    # canvas *looks* like - most usefully that the edge is actually drawn, which
    # a store-level edge assertion cannot see. Compared at the suite's default
    # tolerance (20% of pixels, 30/255 per channel), which is what absorbs the
    # per-run "Saved to file: <timestamp>_<hash>" text in each output box.
    # The helper fitViews first, so baseline and comparison share one viewport,
    # and it writes the baseline on the first run if the file is absent.
    save_workflow_test_screenshot(
        page, "package-roundtrip", test_name="test_save_export_import_and_run_package_nodes",
    )



def test_two_kinds_saved_into_one_package_keep_their_own_code(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
    uninstall_packages,
):
    """Two nodes saved into one package must not share a source file.

    Browser-driven because only the Save-as flow builds this draft, but verified
    against the archive rather than the canvas: the mix-up is invisible in the
    palette (two rows, two labels) and shows up only in what the kinds point at.

    No dataset and no runs - the defect is in what gets written, so the cheapest
    proof is the archive the package exports.
    """
    require_project_page()
    require_user_auth()

    page.emulate_media(reduced_motion="reduce")
    session = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Package Author",
        username="pkg_two_kinds",
        project_name="Two Kinds",
    )
    require_owner_view(page)
    token = session["token"]

    first = drag_to_canvas(page, page.locator(TRANSFORM_TILE), at=POS_FIRST)
    second = drag_to_canvas(page, page.locator(TRANSFORM_TILE), at=POS_SECOND)
    set_node_code(page, first, "return ['first']\n")
    set_node_code(page, second, "return ['second']\n")
    _rename_node(page, first, "E2E First")
    _rename_node(page, second, "E2E Second")

    dir_name = _save_into_package(page, first, new_package="E2E Two Kinds")
    uninstall_packages(token, dir_name)
    assert _save_into_package(page, second, existing="E2E Two Kinds") == dir_name

    archive = api_json(
        f"{current_server}/api/packages/{dir_name}/archive", token, raw=True
    )
    with zipfile.ZipFile(io.BytesIO(archive)) as zf:
        sources = {
            name: zf.read(name).decode("utf-8", "replace")
            for name in zf.namelist()
            if name.startswith("sources/")
        }

    assert len(sources) >= 2, (
        f"two kinds were saved but the archive carries {len(sources)} source "
        f"file(s): {sorted(sources)}"
    )
    bodies = list(sources.values())
    assert any("first" in body for body in bodies), sources
    assert any("second" in body for body in bodies), sources
