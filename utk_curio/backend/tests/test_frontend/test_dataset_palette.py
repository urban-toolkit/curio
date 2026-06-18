"""Playwright E2E: a saved computed dataset shows in the dataset palette.

Covers the user-visible side of two recent fixes:

* the dataset palette counter is consistent with the installed datasets it
  lists (it no longer folds volatile session ``liveOutputs`` into the query), and
* a computed dataset that was saved (auto-installed) stays in the palette — it
  is sourced from the persisted catalog, so it survives reloads and is removed
  only by an explicit uninstall.

Rather than build + run a node through the canvas (which needs the live
sandbox + WebGPU), we seed a *real* installed computed dataset directly: the
e2e process shares the backend's filesystem (same ``CURIO_LAUNCH_CWD``), so we
materialize ``computed.<node>@1/`` via the production installer and reference it
from the seeded project spec — exactly the on-disk state a toggle-on node run
leaves behind.

Run with the e2e harness, e.g.::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_dataset_palette.py --headed
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.request import Request, urlopen

from playwright.sync_api import expect

from .utils import get_shared_data_dir, require_project_page, stub_db_login

if TYPE_CHECKING:
    from .utils import FrontendPage


def _seed_installed_computed_dataset(user_id: int, node_id: str) -> tuple[dict, str]:
    """Materialize ``computed.<node>@1/`` on disk; return (dataflow ref, dataset id)."""
    from utk_curio.backend.app.datasets.bundle import install_node_output
    from utk_curio.backend.app.datasets.installer import sanitize_node_id_segment

    # A parquet artifact in the shared output dir (bytes need not be valid
    # parquet — the installer copies them and the palette only renders manifest
    # metadata). Mirrors the shape post-run auto-install consumes.
    parquet_name = "1718000000222_cafe0002_output.parquet"
    (Path(get_shared_data_dir()) / parquet_name).write_bytes(b"PAR1")

    result = install_node_output(
        str(user_id),
        node_id=node_id,
        path_ref=parquet_name,
        data_type="dataframe",
    )
    assert result is not None, "installer should materialize the computed dataset dir"

    dataset_id = f"computed.{sanitize_node_id_segment(node_id)}"
    ref = {
        "datasetId": dataset_id,
        "dirName": f"{dataset_id}@1",
        "origin": "computed",
        "producerNodeId": node_id,
    }
    return ref, dataset_id


def _spec_with_dataset(ref: dict) -> dict:
    return {
        "dataflow": {
            "name": "Palette Persistence",
            "nodes": [],
            "edges": [],
            "datasets": [ref],
        }
    }


def _get_json(url: str, token: str) -> dict:
    req = Request(url, headers={"Authorization": f"Bearer {token}"}, method="GET")
    with urlopen(req, timeout=10) as resp:  # noqa: S310 (trusted local URL)
        return json.loads(resp.read().decode("utf-8") or "{}")


def _open_palette(page):
    trigger = page.locator('#datasets-palette button[title="Open dataset palette"]')
    trigger.wait_for(state="visible", timeout=30000)
    trigger.click(force=True)
    panel = page.get_by_role("region", name="Dataset palette")
    panel.wait_for(state="visible", timeout=10000)
    return panel


def test_saved_computed_dataset_shows_in_palette_and_persists(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
):
    require_project_page()

    base = app_frontend.base_url
    username = "palette_user"
    node_id = "node-palette"

    # 1. Create the user (installs the session cookie on this page's context).
    login = stub_db_login(
        page,
        frontend_url=base,
        backend_url=current_server,
        username=username,
        name="Palette User",
    )
    user_id = login["user"]["id"]
    token = login["token"]

    # 2. Seed a real installed computed dataset on disk + a project referencing it.
    ref, dataset_id = _seed_installed_computed_dataset(user_id, node_id)
    seeded = stub_db_login(
        page,
        frontend_url=base,
        backend_url=current_server,
        username=username,
        name="Palette User",
        project_name="Palette Persistence",
        project_spec=_spec_with_dataset(ref),
    )
    project_id = seeded["project"]["id"]

    # 2b. Assert backend-side first so a seeding problem is distinguishable from
    #     a browser-timing one: the dataflow catalog must list the computed
    #     dataset as installed.
    catalog = _get_json(
        f"{current_server}/api/datasets/catalog?includeHub=false&dataflowId={project_id}",
        token,
    )
    item = next((i for i in catalog["items"] if i["id"] == dataset_id), None)
    assert item is not None, (
        f"seeded computed dataset {dataset_id} missing from catalog: "
        f"{[i['id'] for i in catalog['items']]}"
    )
    assert item.get("installed") is True, f"computed dataset not marked installed: {item}"
    dataset_title = item["title"]

    # 3. Open the dataflow and the dataset palette; the dataset must render.
    page.goto(f"{base}/dataflow/{project_id}")
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_url(f"**/dataflow/{project_id}", timeout=15000)

    panel = _open_palette(page)
    # Auto-retrying assertions ride out the async catalog fetch (the accordion
    # shows the empty hint until the request resolves).
    expect(panel.get_by_text(dataset_title, exact=False).first).to_be_visible(timeout=15000)
    expect(panel.get_by_text("No installed datasets yet.")).to_have_count(0)

    # 4. Persistence: a reload re-fetches the catalog from the backend; the
    #    saved computed dataset must still be there.
    page.reload()
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_url(f"**/dataflow/{project_id}", timeout=15000)

    panel = _open_palette(page)
    expect(panel.get_by_text(dataset_title, exact=False).first).to_be_visible(timeout=15000)
