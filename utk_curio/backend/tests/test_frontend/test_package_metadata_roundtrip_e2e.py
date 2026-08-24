"""Playwright E2E: the configuration steps of package creation, through a round trip.

Making a package is a multi step process, and the steps that carry *authoring
intent* are the two modals nothing else opens for real: **Node settings**
(``NodeTemplateConfigModal`` - kind description, editor mode, engine, ports) and
**Edit package metadata** (``PackageMetadataModal`` - publisher, license,
permissions, README). This file fills each one in and then checks the values are
still there after the package is exported to a ``.curio.zip``, uninstalled, and
loaded back.

They are two tests rather than one because they are two independent claims and
each should be able to fail on its own. The Node settings leg landed as a strict
xfail pinning a real bug - the modal handoff dropped every edit - and turned
green once ``NodeSaveAsModal`` started selecting its node off React Flow's store
rather than sampling it once; see that test's docstring.

The chains under test are long and entirely implicit. For the kind:
``NodeTemplateConfigModal.onSave`` writes ``packageTemplateConfig`` onto the
canvas node (``styles.tsx``), and ``templateDraftFromCanvasNode`` reads it back
out into the factory draft (``palettePackageFactoryDraft.ts`` via
``applyCanvasTemplateConfigToTemplateDraft``). For the package: the metadata
PATCH rewrites ``manifest.json`` plus a sibling ``README.md`` on disk
(``packages/routes.py``), and the archive re-zips the installed directory
verbatim. Any link dropping a field is silent - the package still builds,
installs and runs, just without what the user typed.

Covered more cheaply elsewhere and deliberately not re-asserted here:
``test_package_export_import.py`` owns the download bytes, the
duplicate-coordinate 400 banner and the project lockfile;
``test_package_roundtrip_e2e.py`` owns dragging imported kinds out and running
them; ``test_save_as_package.py`` owns the modal's own Export button;
``test_packages/test_routes.py`` owns the PATCH allowlist and the same
PATCH -> export -> re-upload join at the route layer, without a browser.

Two fields are deliberately **not** round-tripped, both because the product does
not carry them rather than because they were forgotten:

* ``#pkg-meta-runtime`` (``compatibility.curioRuntime``) is write-only in the UI.
  ``PackageMetadataModal`` initialises it blank on every open and never reads it
  back out of the payload, so a reopened modal cannot show it.
* The ``Provenance tab`` / ``Explanation tab`` checkboxes never reach the wire.
  ``applyCanvasTemplateConfigToTemplateDraft`` does not copy ``hasProvenance`` /
  ``hasExplanation`` into the template draft, and ``toApiPayload`` emits no such
  manifest field. They are canvas-local, and
  ``nodeTemplateConfigModal.test.tsx`` covers their in-modal behaviour instead.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_package_metadata_roundtrip_e2e.py -v
"""
from __future__ import annotations

import io
import json
import zipfile
from typing import TYPE_CHECKING

import pytest
from playwright.sync_api import expect

from .utils import (
    _wait_for_reactflow_ready,
    activate_header_icon,
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

NODE_ID = "pkg-config-source-node"
NODE_CODE = "MARKER_PKG_CONFIG_ROUNDTRIP = 7 * 6\nreturn [MARKER_PKG_CONFIG_ROUNDTRIP]"

# Kind-level configuration, typed into the Node settings modal.
KIND_LABEL = "Configured Kind"
KIND_DESCRIPTION = "Kind description typed into the Node settings modal."

# The seeded node is curio.builtin/computation-analysis, whose descriptor ships
# exactly one input and one output port, both "[1,n]" over six types. So the
# modal opens with one row in each section, and the edits below are: rewrite row
# 0 of each, then append a second input row. Every type list differs from the
# descriptor default, so a config that silently failed to apply leaves the
# six-type defaults behind and fails loudly rather than coincidentally matching.
EXPECTED_INPUT_PORTS = [
    {"types": ["DATAFRAME"], "cardinality": "1"},
    {"types": ["JSON"], "cardinality": "[0,1]"},
]
EXPECTED_OUTPUT_PORTS = [
    {"types": ["VALUE"], "cardinality": "[1,n]"},
]

# Package-level metadata, typed into the Edit package metadata modal.
PACKAGE_NAME = "Configured Metadata Package"
PUBLISHER = "E2E Publisher"
LICENSE = "Apache-2.0"
PERMISSIONS_INPUT = "filesystem.read, network.fetch"
EXPECTED_PERMISSIONS = ["filesystem.read", "network.fetch"]
README_TEXT = (
    "# Configured Metadata Package\n"
    "\n"
    "Written through the metadata modal by the e2e round trip.\n"
)

SAVE_AS_NEW = "__save_as_new__"
DRAWER_ROOT = '[data-curio-node-catalog-drawer="true"]'
SCREENSHOT_STEM = "package-metadata-roundtrip"


def _spec() -> dict:
    """One node, so the canvas is not empty.

    Load-bearing for the baselines: ``save_workflow_test_screenshot`` pins the
    viewport with ``_wait_for_reactflow_ready`` first, and that waits for at
    least one ``.react-flow__node``. It is also the node these tests configure
    and save.
    """
    return {
        "dataflow": {
            "name": "PackageConfigSource",
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
    """Remove every store copy a test installed, through the real routes.

    Mandatory, not hygiene. ``.curio/users/<id>/packages/`` outlives
    ``reset-db`` while sqlite recycles user ids from 1, and a canvas draft
    package is not in the committed catalog so ``prune_unreferenced_packages``
    will never collect it. Without this the second run of this file finds the
    coordinate already installed and the import step fails as a collision - a
    test that stops testing after it first passes.

    Non-autouse and requested explicitly so it finalises *before* the autouse
    ``e2e_clean_db``, while the stub user and its token are still valid.
    """
    registered: list[tuple[str, str, str | None]] = []

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
                # A 404 on the second URL is normal: removing the last project
                # reference prunes the store copy too.
                print(f"[teardown] DELETE {url} failed: {exc}")


def _enter_dataflow(page, app_frontend, current_server, *, username: str):
    """One stub user PER TEST.

    Sharing a username across tests in a file is a 401 waiting to happen:
    ``e2e_clean_db`` truncates ``user`` / ``user_session`` between tests and
    sqlite recycles the id, so the second login lands on a coordinate the
    backend has already seen.
    """
    # Before navigating: the Node Catalog drawer slides in via translate3d, so
    # to_be_visible is not a gate on its own, and the provider reads
    # prefers-reduced-motion through useSyncExternalStore.
    page.emulate_media(reduced_motion="reduce")
    session = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Package Configurator",
        username=username,
        project_name="Package Metadata Roundtrip",
        project_spec=_spec(),
    )
    skip_if_shared_view(page)
    _wait_for_reactflow_ready(page)
    return session


# ---------------------------------------------------------------------------
# Node settings modal
# ---------------------------------------------------------------------------

def _open_node_settings(page):
    node_el = page.locator(f'.react-flow__node[data-id="{NODE_ID}"]')
    # The gear activates on pointerdown/pointerup and swallows the native click
    # (useHeaderIconDragClick), so a plain .click() does nothing.
    activate_header_icon(node_el.locator('button[aria-label^="Node settings for"]'))
    expect(page.get_by_role("heading", name="Node settings")).to_be_visible(
        timeout=10000
    )


def _port_section(page, title: str):
    """The ``TemplatePortEditor`` block for one section.

    Its rows carry no label, id or test id, and every class name is a hashed CSS
    module, so the section heading is the only stable anchor: match the label's
    exact text and step up to the wrapper that also holds the rows.
    """
    return page.get_by_text(title, exact=True).locator("xpath=..")


def _set_port_row(section, index: int, types: str, cardinality: str) -> None:
    """Rewrite one port row. One ``input`` and one ``select`` per row, in order."""
    section.locator("input").nth(index).fill(types)
    section.locator("select").nth(index).select_option(cardinality)


def _configure_kind(page) -> None:
    """Fill in every Node settings field that is meant to reach the manifest."""
    page.locator("#kind-config-label").fill(KIND_LABEL)
    page.locator("#kind-config-description").fill(KIND_DESCRIPTION)

    inputs = _port_section(page, "Input ports")
    expect(inputs.locator("input")).to_have_count(1)
    _set_port_row(inputs, 0, "DATAFRAME", "1")
    inputs.get_by_role("button", name="+ Add port").click()
    expect(inputs.locator("input")).to_have_count(2)
    _set_port_row(inputs, 1, "JSON", "[0,1]")

    outputs = _port_section(page, "Output ports")
    expect(outputs.locator("input")).to_have_count(1)
    # Cardinality left at the descriptor's "[1,n]" on purpose: it is the one
    # value that must survive *without* being retyped, so the round trip is not
    # trivially satisfied by "whatever the modal last wrote".
    outputs.locator("input").nth(0).fill("VALUE")


def _save_as_new_package(page) -> str:
    """Save As -> New package; return the installed ``dirName``.

    Assumes the Node settings modal is open: its ``Save as package node...``
    button is the only route to ``NodeSaveAsModal``.
    """
    # Substring match: the button label ends in a U+2026 ellipsis.
    page.get_by_role("button", name="Save as package node").click()
    expect(page.get_by_role("heading", name="Save as package node")).to_be_visible(
        timeout=10000
    )
    # Explicit: the modal defaults to the first writable *installed* package, so
    # without this the draft would target an already-installed coordinate.
    page.locator("#save-as-package-target").select_option(SAVE_AS_NEW)
    page.locator("#save-as-new-package-name").fill(PACKAGE_NAME)

    with page.expect_response(
        lambda r: r.url.endswith("/api/packages/factory/install")
        and r.request.method == "POST",
        timeout=60000,
    ) as installed:
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


# ---------------------------------------------------------------------------
# Palette / metadata modal
# ---------------------------------------------------------------------------

def _package_anchor(page, dir_name: str):
    return page.locator(f'#packages-palette [data-pkg-palette-coords~="{dir_name}"]')


def _open_metadata_modal(page, anchor):
    # Lives in the accordion <summary>, so the package need not be expanded.
    anchor.locator(f'button[aria-label="Edit metadata for {PACKAGE_NAME}"]').click()
    expect(page.get_by_role("heading", name="Edit package metadata")).to_be_visible(
        timeout=15000
    )
    # The modal fetches GET /api/packages before it renders any input, showing a
    # "Loading..." body until then. Gating on a field rather than the heading
    # avoids filling a form that is about to be replaced by the load.
    expect(page.locator("#pkg-meta-publisher")).to_be_visible(timeout=15000)


def _installed_package(current_server: str, token: str, dir_name: str) -> dict:
    packages = api_json(f"{current_server}/api/packages", token)["packages"]
    found = next((p for p in packages if p["dirName"] == dir_name), None)
    assert found is not None, (
        f"{dir_name} is not installed; the store holds "
        f"{[p['dirName'] for p in packages]}"
    )
    return found


def _assert_package_metadata(pkg: dict, *, where: str) -> None:
    """Every Edit package metadata field that reaches the wire."""
    assert pkg["name"] == PACKAGE_NAME, f"{where}: {pkg['name']!r}"
    assert pkg["publisher"] == PUBLISHER, f"{where}: {pkg['publisher']!r}"
    assert pkg["license"] == LICENSE, f"{where}: {pkg['license']!r}"
    assert pkg["permissions"] == EXPECTED_PERMISSIONS, f"{where}: {pkg['permissions']}"
    # README is a sibling file on disk that _manifest_to_payload reads back into
    # the payload, so this also proves the file itself travelled in the archive.
    assert pkg.get("readme") == README_TEXT, f"{where}: {pkg.get('readme')!r}"


# ---------------------------------------------------------------------------

def test_package_metadata_survives_export_and_reimport(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
    tmp_path,
    uninstall_packages,
):
    """Edit package metadata -> export -> uninstall -> import -> it is all still there."""
    require_project_page()
    require_user_auth()
    session = _enter_dataflow(
        page, app_frontend, current_server, username="pkg_metadata_user"
    )
    token = session["token"]
    project_id = session["project"]["id"]

    # ------------------------------------------------------------------
    # 1. Make a package to hang metadata off
    # ------------------------------------------------------------------
    # No kind configuration here: this test's subject is the package-level
    # metadata, and the kind-level configuration is a separate claim owned by
    # test_node_settings_configuration_reaches_the_saved_package below.
    _open_node_settings(page)
    dir_name = _save_as_new_package(page)
    uninstall_packages(token, dir_name, project_id)

    # ------------------------------------------------------------------
    # 2. Edit the metadata
    # ------------------------------------------------------------------
    open_tools_palette(page, "packages")
    anchor = _package_anchor(page, dir_name)
    expect(anchor).to_have_count(1, timeout=20000)
    _open_metadata_modal(page, anchor)

    page.locator("#pkg-meta-publisher").fill(PUBLISHER)
    page.locator("#pkg-meta-license").fill(LICENSE)
    page.locator("#pkg-meta-permissions").fill(PERMISSIONS_INPUT)
    page.locator("#pkg-meta-readme").fill(README_TEXT)

    # Baseline of the filled form, captured before the click that closes it. The
    # subtitle carries the generated coordinate (curio.canvas.draft.<random>@1 -
    # v0.1.0), which differs on every run; the suite's default tolerance (20% of
    # pixels at 30/255 per channel) absorbs a one-line text change comfortably.
    # Do not tighten it.
    save_workflow_test_screenshot(
        page, SCREENSHOT_STEM,
        test_name="test_package_metadata_modal_filled",
    )

    # Matched on the method alone, not on the coordinate: packagesApi runs the
    # dirName through encodeURIComponent, so the "@" in
    # "curio.canvas.draft.<slug>@1" reaches the wire as "%40" and a predicate
    # built from the raw dirName never fires. PATCH is unique under
    # /api/packages/ anyway.
    with page.expect_response(
        lambda r: r.request.method == "PATCH" and "/api/packages/" in r.url,
        timeout=60000,
    ) as patched:
        page.get_by_role("button", name="Save changes", exact=True).click()
    assert patched.value.ok, (
        f"metadata PATCH failed ({patched.value.status}): "
        f"{patched.value.text()[:500]}"
    )
    expect(page.get_by_role("heading", name="Edit package metadata")).to_have_count(
        0, timeout=20000
    )
    expect(
        page.get_by_label("Notifications").get_by_text(
            f"Metadata updated for {PACKAGE_NAME}."
        )
    ).to_be_visible(timeout=20000)

    # Server truth before any round trip, so a PATCH regression is
    # distinguishable from an archive regression.
    _assert_package_metadata(
        _installed_package(current_server, token, dir_name), where="after PATCH"
    )

    # ------------------------------------------------------------------
    # 3. Export
    # ------------------------------------------------------------------
    anchor = _package_anchor(page, dir_name)
    expect(anchor).to_have_count(1, timeout=20000)
    with page.expect_download(timeout=60000) as download:
        anchor.locator('button[title="Export package"]').click(force=True)
    archive_path = tmp_path / f"{dir_name}.curio.zip"
    download.value.save_as(str(archive_path))

    # Read the archive in Python rather than letting the import reveal a loss:
    # if the zip is already missing a field, this says so at the step that
    # dropped it instead of sixty lines later.
    archive = archive_path.read_bytes()
    with zipfile.ZipFile(io.BytesIO(archive)) as zf:
        assert zf.testzip() is None, "downloaded archive has a corrupt member"
        names = set(zf.namelist())
        assert "manifest.json" in names, names
        assert "README.md" in names, (
            f"the PATCHed README is not in the archive: {sorted(names)}"
        )
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        # Every template's declared source must actually ship. The installer
        # resolves `source` while validating the extracted tree, so a manifest
        # pointing at a file the archive omits fails the *import* with a bare
        # ENOENT 500 - a long way from the export that dropped it.
        for tpl in manifest["templates"]:
            assert tpl["source"] in names, (
                f"template {tpl['id']!r} declares source {tpl['source']!r}, "
                f"which the archive does not contain: {sorted(names)}"
            )
        # Byte-exact, not normalised: the PATCH route writes README.md with
        # newline="" precisely so an author's LF does not become CRLF on
        # Windows and ship a different archive than the same edit on Linux.
        assert zf.read("README.md").decode("utf-8") == README_TEXT
    assert manifest["publisher"] == PUBLISHER, manifest["publisher"]
    assert manifest["license"] == LICENSE, manifest["license"]
    assert manifest["permissions"] == EXPECTED_PERMISSIONS, manifest["permissions"]

    # ------------------------------------------------------------------
    # 4. Bridge: drop the store copy so the import is a real first install
    # ------------------------------------------------------------------
    # The upload route rejects an archive whose coordinate is already installed,
    # and no UI path sets replace=true, so this delete is what makes the import
    # below test anything at all.
    api_json(f"{current_server}/api/packages/{dir_name}", token, method="DELETE")
    page.reload()
    page.wait_for_load_state("domcontentloaded")
    open_tools_palette(page, "packages")
    expect(_package_anchor(page, dir_name)).to_have_count(0, timeout=20000)

    # ------------------------------------------------------------------
    # 5. Load it back in through the Node Catalog drawer
    # ------------------------------------------------------------------
    page.get_by_role("button", name="Data ⏷", exact=True).click(force=True)
    page.get_by_role("button", name="Node Catalog", exact=True).click()
    page.locator(DRAWER_ROOT).wait_for(state="attached", timeout=15000)
    # Filtered by heading: the install dialog is also role="dialog" but carries
    # no accessible name, so a bare get_by_role would be a strict-mode violation.
    drawer = page.get_by_role("dialog").filter(
        has=page.get_by_role("heading", name="Node Catalog", exact=True)
    )
    expect(drawer).to_be_visible(timeout=10000)

    with page.expect_response(
        lambda r: "/api/packages/upload" in r.url and r.request.method == "POST",
        timeout=60000,
    ) as uploaded:
        with page.expect_file_chooser() as chooser:
            drawer.get_by_role("button", name="Import package").click()
        chooser.value.set_files(str(archive_path))
    assert uploaded.value.ok, (
        f"import failed ({uploaded.value.status}): {uploaded.value.text()[:500]}"
    )
    # A second store copy now exists, so it needs registering again.
    uninstall_packages(token, dir_name, project_id)
    assert uploaded.value.json()["package"]["dirName"] == dir_name

    # Scoped to <header>: the scrim carries the same aria-label as the close
    # button, so a page-level lookup is a strict-mode violation.
    drawer.locator("header").get_by_role(
        "button", name="Close Node Catalog drawer"
    ).click()
    expect(page.locator(DRAWER_ROOT)).to_have_count(0, timeout=5000)

    # ------------------------------------------------------------------
    # 6. THE POINT: every edited field came back
    # ------------------------------------------------------------------
    _assert_package_metadata(
        _installed_package(current_server, token, dir_name), where="after re-import"
    )

    open_tools_palette(page, "packages")
    anchor = _package_anchor(page, dir_name)
    expect(anchor).to_have_count(1, timeout=30000)

    # And the UI reads the reinstalled copy rather than a stale registry entry:
    # reopen the metadata modal and check it pre-populates from the archive.
    _open_metadata_modal(page, anchor)
    expect(page.locator("#pkg-meta-publisher")).to_have_value(PUBLISHER)
    expect(page.locator("#pkg-meta-license")).to_have_value(LICENSE)
    expect(page.locator("#pkg-meta-permissions")).to_have_value(PERMISSIONS_INPUT)
    expect(page.locator("#pkg-meta-readme")).to_have_value(README_TEXT)

    save_workflow_test_screenshot(
        page, SCREENSHOT_STEM,
        test_name="test_package_metadata_after_reimport",
    )

    page.get_by_role("button", name="Cancel", exact=True).click()
    expect(page.get_by_role("heading", name="Edit package metadata")).to_have_count(
        0, timeout=10000
    )


def test_node_settings_configuration_reaches_the_saved_package(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
    uninstall_packages,
):
    """Configure a kind in Node settings, save it, and read the manifest back.

    This is the handoff between the two modals, and it was broken until
    ``NodeSaveAsModal`` started selecting its node off React Flow's store
    instead of sampling it once. The old ``useMemo(() => getNodes().find(...),
    [show, nodeId, getNodes])`` ran on the exact render where ``show`` flips
    true - but the Node settings ``onSave`` (styles.tsx) calls
    ``updateDataNode`` and ``setSaveAsOpen(true)`` in one batch, and
    ``updateDataNode`` writes FlowProvider's ``useNodesState`` array, which
    reaches the store only when React Flow's prop-sync effect runs, i.e. after
    that render. The memo captured the pre-edit node and, since none of its
    deps ever changed again, held it for the modal's lifetime: every edit made
    in Node settings was silently dropped from the saved package.

    Nothing else would catch a regression here. ``test_package_roundtrip_e2e.py``
    sets its labels through the node header pencil in a separate interaction, by
    which time the store has long since synced, so it never exercises the
    same-batch handoff at all.
    """
    require_project_page()
    require_user_auth()
    session = _enter_dataflow(
        page, app_frontend, current_server, username="pkg_kindconfig_user"
    )
    token = session["token"]
    project_id = session["project"]["id"]

    _open_node_settings(page)
    _configure_kind(page)

    # Baseline of the configured modal, captured before the click that closes
    # it. The rendered port rows are the only place this configuration is
    # visible at all - the assertions below read it back out of JSON. Worth a
    # shot of its own because the modal rendering correctly and the package
    # receiving what it rendered were, for a while, two different things.
    save_workflow_test_screenshot(
        page, SCREENSHOT_STEM,
        test_name="test_node_settings_configured",
    )

    dir_name = _save_as_new_package(page)
    uninstall_packages(token, dir_name, project_id)

    pkg = _installed_package(current_server, token, dir_name)
    templates = pkg["templates"]
    assert len(templates) == 1, templates
    tpl = templates[0]
    assert tpl["label"] == KIND_LABEL, tpl["label"]
    assert tpl["description"] == KIND_DESCRIPTION, tpl["description"]
    assert tpl["inputPorts"] == EXPECTED_INPUT_PORTS, tpl["inputPorts"]
    assert tpl["outputPorts"] == EXPECTED_OUTPUT_PORTS, tpl["outputPorts"]
