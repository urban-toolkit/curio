"""Playwright E2E: exporting a dataset from the Data Catalog detail panel.

The Export button in ``DatasetDetailPanel`` is the only way to get a dataset's
bytes out of Curio, and the *filename* it produces is decided almost entirely in
the browser. ``datasetCatalogApi.downloadDataset`` fetches with a bearer token,
then derives the name through four fallbacks in order: an RFC 5987
``filename*`` token, a plain quoted ``filename`` token, the dataset id with its
dots rewritten to underscores, and finally an extension taken from the blob's
own MIME type (or the nominal format) if the chosen name lacks one. Only the
last two are reachable without a browser.

The assertion that earns this test is the exact filename, because it is a single
value that pins three independent things at once:

* **``Content-Disposition`` is CORS-exposed.** The download is cross-origin
  (frontend :8080 -> backend :5002) and ``Content-Disposition`` is not a
  safelisted response header, so JavaScript can only read it because
  ``app/__init__.py`` sends ``Access-Control-Expose-Headers``. Drop that header
  and every export silently falls back to the id-derived name - no error, no
  failing request, just a wrongly named file. A Python test can never catch it:
  CORS exposure constrains the browser, not the server, so ``urlopen`` sees the
  header either way.
* **The quoted-token regex handles spaces.** ``_download_name`` (backend
  ``application/export.py``) deliberately keeps the human title verbatim, so the
  server sends ``filename="Chicago Community Areas.geojson"``. A regex that
  forgot to strip the quotes would download a file whose name still contains
  them.
* **The extension is not appended twice.** The server name already ends in the
  right extension, so the MIME-based guarantee step has to leave it alone.

Covered more cheaply elsewhere and deliberately not re-asserted here: the
drawer's listing, search and add-to-dataflow propagation are
``test_data_catalog.py``'s subject; ``test_datasets/`` owns the download route,
the parquet-to-csv/geojson export conversion and the name derivation itself; and
``src/tests/components/DatasetDetailPanel.test.tsx`` owns the panel's header
actions, timestamps and lineage.

Nothing here installs anything. A hub dataset is exportable straight from the
catalog, so this test needs no dataset in the project lockfile and leaves no
copy in ``.curio/users/<id>/`` to clean up.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_dataset_export.py -v
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from playwright.sync_api import expect

from .utils import (
    _wait_for_reactflow_ready,
    api_json,
    require_project_page,
    require_user_auth,
    save_workflow_test_screenshot,
    skip_if_shared_view,
    stub_login_and_enter_workflow,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

DRAWER_ROOT = '[data-curio-dataset-catalog-drawer="true"]'
# The "Adding…" placeholder is an <article role="status"> carrying the same title
# as the real card, so every card locator has to exclude it.
CARD = 'article:not([role="status"])'

# Both committed hub datasets that are exportable as a single file, with the
# filename the server's Content-Disposition asks for. `_download_name` keeps the
# manifest `name` verbatim (spaces and casing) and appends the data file's real
# suffix, so these are the titles as shown in the catalog.
GEOJSON = (
    "data.urbanlab.chicago-community-areas",
    "Chicago Community Areas",
    "Chicago Community Areas.geojson",
)
CSV = (
    "data.urbanlab.acs-neighborhood-profile",
    "ACS Neighborhood Profile",
    "ACS Neighborhood Profile.csv",
)


def _fallback_name(dataset_id: str, extension: str) -> str:
    """What the client would download if it could not read the header.

    ``datasetId.replace(/\\./g, "_")`` plus the MIME/format extension. Dots are
    rewritten because a computed id like ``computed.n13…`` would otherwise leave
    the OS treating the trailing segment as the file extension.
    """
    return f"{dataset_id.replace('.', '_')}{extension}"


def _one_node_spec() -> dict:
    """A single node so the canvas is not empty.

    ``save_workflow_test_screenshot`` pins the viewport with
    ``_wait_for_reactflow_ready`` before capturing, and that waits for at least
    one ``.react-flow__node``. An empty dataflow therefore times out.
    """
    return {
        "dataflow": {
            "name": "DatasetExportBaseline",
            "task": "",
            "nodes": [
                {
                    "id": "dataset-export-baseline-node",
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


def _enter_dataflow(page, app_frontend, current_server, *, username: str):
    # Before navigating: the drawer slides via translate3d, so to_be_visible is
    # not a gate, and the provider reads prefers-reduced-motion through
    # useSyncExternalStore.
    page.emulate_media(reduced_motion="reduce")
    result = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Dataset Export User",
        username=username,
        project_name="Dataset Export",
        project_spec=_one_node_spec(),
    )
    skip_if_shared_view(page)
    # Gate on the canvas before driving the top menu. A node on screen means
    # ProjectLoader finished and UpMenu is mounted; without this the first
    # action is a click on "Data" that fails with a bare 30s locator timeout if
    # the project is still loading, which says nothing about why. Later tests in
    # a session are the ones that hit it, because the servers are busiest then.
    _wait_for_reactflow_ready(page)
    return result


def _drawer(page):
    root = page.locator(DRAWER_ROOT)
    root.wait_for(state="attached", timeout=15000)
    # aria-hidden IS the presented signal: until the rAF flips it, every role
    # query inside the subtree returns zero matches.
    expect(root).to_have_attribute("aria-hidden", "false", timeout=10000)
    dialog = page.get_by_role("dialog").filter(
        has=page.get_by_role("heading", name="Data Catalog", exact=True)
    )
    expect(dialog).to_be_visible(timeout=10000)
    return dialog


def _open_drawer_from_menu(page):
    page.get_by_role("button", name="Data ⏷", exact=True).click(force=True)
    page.get_by_role("button", name="Data Catalog", exact=True).click()
    return _drawer(page)


def _open_details(page, drawer, dataset_id: str, title: str):
    """Open one card's detail modal; return the modal's Export button.

    The trigger is the card's format avatar, whose accessible name carries the
    format abbreviation (``View <title> (GEOJSON) details``), so it is matched by
    prefix rather than spelling out the abbreviation for each format.
    """
    card = drawer.locator(f'{CARD}[data-dataset-id="{dataset_id}"]')
    expect(card).to_have_count(1, timeout=20000)
    card.locator(f'button[aria-label^="View {title} ("]').click()

    # The modal fetches GET /api/datasets/<id> before rendering the panel body,
    # so gate on the panel's own tab strip rather than the modal frame.
    expect(
        page.get_by_role("navigation", name="Dataset detail sections")
    ).to_be_visible(timeout=20000)
    export = page.get_by_role("button", name="Export", exact=True)
    expect(export).to_be_enabled(timeout=10000)
    return export


def _close_details(page):
    # ModalShell's own dismiss. Scoped to the overlay layer would be nicer, but
    # the dataset drawer has no "Close" label of its own, so this is unambiguous.
    page.get_by_role("button", name="Close", exact=True).click()
    expect(
        page.get_by_role("navigation", name="Dataset detail sections")
    ).to_have_count(0, timeout=10000)


@pytest.mark.parametrize(
    "dataset_id,title,expected_filename",
    [GEOJSON, CSV],
    ids=["geojson", "csv"],
)
def test_export_downloads_the_server_named_file(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
    tmp_path,
    dataset_id: str,
    title: str,
    expected_filename: str,
):
    """Export a hub dataset and check the name and the bytes.

    Parametrized over both exportable formats because the extension is chosen
    from the blob's MIME type: a geojson-only test would pass with the CSV
    mapping missing entirely, and vice versa.
    """
    require_project_page()
    require_user_auth()
    # One stub user per parametrized case: e2e_clean_db truncates user and
    # user_session between tests while sqlite recycles the id, so a shared
    # username makes the second login land on a coordinate the backend has seen.
    session = _enter_dataflow(
        page, app_frontend, current_server,
        username=f"dataset_export_{expected_filename.split('.')[-1]}_user",
    )
    token = session["token"]

    drawer = _open_drawer_from_menu(page)
    export = _open_details(page, drawer, dataset_id, title)

    with page.expect_download(timeout=60000) as download:
        export.click()

    # THE POINT. Equality with the server's own name proves the header crossed
    # the origin boundary and was parsed intact; see the module docstring.
    assert download.value.suggested_filename == expected_filename, (
        f"expected the Content-Disposition name {expected_filename!r}, got "
        f"{download.value.suggested_filename!r}"
    )
    extension = f".{expected_filename.rsplit('.', 1)[1]}"
    assert download.value.suggested_filename != _fallback_name(dataset_id, extension), (
        "the export fell back to the id-derived name, which means JavaScript "
        "could not read Content-Disposition - check "
        "Access-Control-Expose-Headers in app/__init__.py"
    )

    saved = tmp_path / expected_filename
    download.value.save_as(str(saved))
    body = saved.read_bytes()

    # The object URL is revoked on the line after anchor.click(), so a truncated
    # download is the real hazard on this path. Compare against the endpoint's
    # own bytes, the same way test_package_export_import.py does.
    direct = api_json(
        f"{current_server}/api/datasets/{dataset_id}/download", token, raw=True
    )
    assert len(body) == len(direct), (
        f"downloaded {len(body)} bytes but the endpoint served {len(direct)} - "
        f"the blob was revoked before Chromium finished reading it"
    )
    assert body == direct, "downloaded bytes differ from the endpoint's"
    assert body, "the exported dataset is empty"

    # Export is otherwise silent, so the absence of the failure toast is the
    # only other signal available.
    expect(
        page.get_by_label("Notifications").get_by_text("Could not export dataset.")
    ).to_have_count(0)

    save_workflow_test_screenshot(
        page, "dataset-export",
        test_name=f"test_export_downloads_the_server_named_file_{extension.lstrip('.')}",
    )

    _close_details(page)
