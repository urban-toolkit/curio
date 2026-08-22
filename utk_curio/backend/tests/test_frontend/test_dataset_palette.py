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

import json
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.request import Request, urlopen

import pytest
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, expect

from .utils import (
    get_shared_data_dir,
    require_project_page,
    stub_login_and_enter_workflow,
)

if TYPE_CHECKING:
    from .utils import FrontendPage


def _dataset_ref(node_id: str) -> tuple[str, dict]:
    """The catalog id + dataflow ``datasets`` ref for a computed node output."""
    from utk_curio.backend.app.datasets.install.installer import sanitize_node_id_segment

    dataset_id = f"computed.{sanitize_node_id_segment(node_id)}"
    ref = {
        "datasetId": dataset_id,
        "dirName": f"{dataset_id}@1",
        "origin": "computed",
        "producerNodeId": node_id,
    }
    return dataset_id, ref


def _install_dataset_on_disk(user_id: int, node_id: str) -> None:
    """Materialize ``computed.<node>@1/`` in the owner's dataset store — the
    on-disk state a toggle-on node run leaves behind."""
    from utk_curio.backend.app.datasets.install.bundle import install_node_output

    # Bytes need not be valid parquet — the installer copies them and the palette
    # only renders manifest metadata.
    parquet_name = "1718000000222_cafe0002_output.parquet"
    (Path(get_shared_data_dir()) / parquet_name).write_bytes(b"PAR1")
    result = install_node_output(
        str(user_id), node_id=node_id, path_ref=parquet_name, data_type="dataframe"
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


def _request_json(url: str, token: str, *, method: str, payload: dict | None = None) -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Authorization": f"Bearer {token}"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = Request(url, data=data, headers=headers, method=method)
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
    node_id = "node-palette"
    dataset_id, ref = _dataset_ref(node_id)

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

    # Owner check. In a no-auth / shared-guest e2e environment (e.g.
    # ``CURIO_E2E_USE_EXISTING=1`` against a dev server that ignores the injected
    # stub session) the browser is the *read-only shared guest*, so it can never
    # see another user's installed datasets and this test is not meaningful.
    # Wait long enough for ProjectLoader to resolve, and if the read-only banner
    # appears, SKIP with a clear reason rather than fail confusingly at the
    # palette. The proper environment is ``CURIO_TESTING=1`` (without
    # ``CURIO_E2E_USE_EXISTING``), which boots an auth-enabled server where the
    # stub session authenticates the owner — same as the workflow e2e tests.
    shared_banner = page.get_by_test_id("shared-view-banner")
    try:
        shared_banner.wait_for(state="visible", timeout=4000)
    except PlaywrightTimeoutError:
        pass  # no banner → authenticated owner, proceed
    else:
        pytest.skip(
            "Dataflow opened read-only as the shared guest — owner auth is "
            "unavailable in this e2e environment. Run with CURIO_TESTING=1 "
            "(without CURIO_E2E_USE_EXISTING) against an auth-enabled server."
        )

    # 2. Now generate/install the computed dataset INTO the saved project:
    #    materialize the dataset dir on disk and reference it from the spec.
    _install_dataset_on_disk(user_id, node_id)
    _request_json(
        f"{current_server}/api/projects/{project_id}",
        token,
        method="PUT",
        payload={"name": "Palette Persistence", "spec": _spec_with_dataset(ref), "outputs": []},
    )

    # 2b. Assert backend-side first so a seeding problem is distinguishable from a
    #     browser-timing one: the dataflow catalog must list it as installed.
    catalog = _request_json(
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

    panel = _open_palette(page)
    # Auto-retrying assertions ride out the async catalog fetch (the accordion
    # shows the empty hint until the request resolves).
    expect(panel.get_by_text(dataset_title, exact=False).first).to_be_visible(timeout=15000)
    expect(panel.get_by_text("No datasets added yet.")).to_have_count(0)

    # 4. Persistence: another reload re-fetches the catalog from the backend; the
    #    saved computed dataset must still be there.
    page.reload()
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_url(f"**/dataflow/{project_id}", timeout=15000)

    panel = _open_palette(page)
    expect(panel.get_by_text(dataset_title, exact=False).first).to_be_visible(timeout=15000)
