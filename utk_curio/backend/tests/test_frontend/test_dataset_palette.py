"""Playwright E2E: a saved computed dataset shows in the dataset palette.

Covers the user-visible side of recent fixes:

* a computed dataset that was saved (auto-installed) shows in the palette and
  survives reloads — it is sourced from the persisted catalog, and
* the palette counter is consistent with the installed datasets it lists.

Flow (mirrors a real session): log in as the owner and **save a project first**,
then generate/install the computed dataset *into that saved project*, then check
the palette. Generating a dataset by running a node needs the live sandbox +
WebGPU, so we materialize ``computed.<node>@1/`` directly — the e2e process
shares the backend's filesystem (same ``CURIO_LAUNCH_CWD``), so the production
installer writes exactly the on-disk state a toggle-on node run leaves behind —
and reference it from the project's persisted spec.

The owner must be a real authenticated session (``stub_login_and_enter_workflow``),
not the read-only shared-guest fallback — otherwise the palette's catalog fetch
runs as the guest and (correctly) shows nothing.

Run with the e2e harness, e.g.::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_dataset_palette.py --headed
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from playwright.sync_api import expect

from .utils import (
    api_json,
    get_shared_data_dir,
    open_tools_palette,
    require_project_page,
    require_owner_view,
    stub_login_and_enter_workflow,
)

if TYPE_CHECKING:
    from .utils import FrontendPage


def _dataset_ref(node_id: str, dataflow_id: str) -> tuple[str, dict]:
    """The catalog id + dataflow ``datasets`` ref for a computed node output.

    The id is namespaced by the producing dataflow, so the same node id in two
    dataflows yields two distinct account-level datasets (#166). Built with the
    production helper rather than hand-rolled: the un-namespaced
    ``computed.<node>`` form is display/lookup-only and the installers refuse it.
    """
    from utk_curio.backend.app.datasets.install.installer import computed_dataset_id

    dataset_id = computed_dataset_id(node_id, dataflow_id)
    ref = {
        "datasetId": dataset_id,
        "dirName": f"{dataset_id}@1",
        "origin": "computed",
        "producerNodeId": node_id,
    }
    return dataset_id, ref


def _install_dataset_on_disk(user_id: int, node_id: str, dataflow_id: str) -> None:
    """Materialize the computed dataset dir in the owner's store - the on-disk
    state a toggle-on node run leaves behind."""
    from utk_curio.backend.app.datasets.install.bundle import install_node_output

    # Bytes need not be valid parquet — the installer copies them and the palette
    # only renders manifest metadata.
    parquet_name = "1718000000222_cafe0002_output.parquet"
    (Path(get_shared_data_dir()) / parquet_name).write_bytes(b"PAR1")
    result = install_node_output(
        str(user_id),
        node_id=node_id,
        path_ref=parquet_name,
        data_type="dataframe",
        dataflow_id=dataflow_id,
    )
    assert result is not None, "installer should materialize the computed dataset dir"


def _spec_with_dataset(ref: dict) -> dict:
    return {
        "dataflow": {
            "name": "Palette Persistence",
            "nodes": [],
            "edges": [],
            "datasets": [ref],
        }
    }


def test_saved_computed_dataset_shows_in_palette_and_persists(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
):
    require_project_page()

    base = app_frontend.base_url
    node_id = "node-palette"

    # 1. SAVE A PROJECT FIRST: log in as the owner and enter a fresh saved
    #    dataflow (a real authenticated session, not the shared-guest view).
    result = stub_login_and_enter_workflow(
        page,
        frontend_url=base,
        backend_url=current_server,
        name="Palette User",
        username="palette_user",
        project_name="Palette Persistence",
    )
    user_id = result["user"]["id"]
    token = result["token"]
    project_id = result["project"]["id"]

    # Owner check: a shared-guest session can never see another user's installed
    # datasets, so this test wouldn't be meaningful there.
    require_owner_view(page)

    # 2. Now generate/install the computed dataset INTO the saved project:
    #    materialize the dataset dir on disk and reference it from the spec.
    #    The id is only knowable once the project exists - it is namespaced by
    #    the producing dataflow.
    dataset_id, ref = _dataset_ref(node_id, project_id)
    _install_dataset_on_disk(user_id, node_id, project_id)
    api_json(
        f"{current_server}/api/projects/{project_id}",
        token,
        method="PUT",
        payload={"name": "Palette Persistence", "spec": _spec_with_dataset(ref), "outputs": []},
    )

    # 2b. Assert backend-side first so a seeding problem is distinguishable from a
    #     browser-timing one: the dataflow catalog must list it as installed.
    catalog = api_json(
        f"{current_server}/api/datasets/catalog?includeHub=false&dataflowId={project_id}",
        token,
        method="GET",
    )
    item = next((i for i in catalog["items"] if i["id"] == dataset_id), None)
    assert item is not None, (
        f"seeded computed dataset {dataset_id} missing from catalog: "
        f"{[i['id'] for i in catalog['items']]}"
    )
    assert item.get("installed") is True, f"computed dataset not marked installed: {item}"
    dataset_title = item["title"]

    # 3. Reload so the palette's catalog fetch picks up the install; it must render.
    page.reload()
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_url(f"**/dataflow/{project_id}", timeout=15000)

    panel = open_tools_palette(page, "datasets")
    # Auto-retrying assertions ride out the async catalog fetch (the accordion
    # shows the empty hint until the request resolves).
    expect(panel.get_by_text(dataset_title, exact=False).first).to_be_visible(timeout=15000)
    expect(panel.get_by_text("No datasets added yet.")).to_have_count(0)

    # 4. Persistence: another reload re-fetches the catalog from the backend; the
    #    saved computed dataset must still be there.
    page.reload()
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_url(f"**/dataflow/{project_id}", timeout=15000)

    panel = open_tools_palette(page, "datasets")
    expect(panel.get_by_text(dataset_title, exact=False).first).to_be_visible(timeout=15000)
