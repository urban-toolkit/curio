"""Computed node outputs surface in the account-level Data Catalog.

A saved computed dataset is browsable in the account catalog (``includeHub``,
no/other dataflow) as an available — not installed — item, carrying its
producer/workflow lineage, so it can be installed into a project later.
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path

from utk_curio.backend.app.datasets.install.installer import computed_dataset_id
from utk_curio.backend.tests.test_datasets.computed_test_helpers import (
    auth_headers,
    create_project,
    save_project_with_output,
)


def _catalog(client, token, *, dataflow_id=None, live_outputs=None):
    url = "/api/datasets/catalog?includeHub=true"
    if dataflow_id:
        url += f"&dataflowId={dataflow_id}"
    if live_outputs is not None:
        encoded = base64.b64encode(json.dumps(live_outputs).encode()).decode()
        url += f"&liveOutputs={encoded}"
    resp = client.get(url, headers=auth_headers(token))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return resp.get_json()["items"]


def _write_refs(app, user, project_id, refs):
    """Write dataflow.datasets refs straight into the persisted spec."""
    from utk_curio.backend.app.projects import storage as project_storage
    from utk_curio.backend.app.projects.services import _user_dir_key

    with app.app_context():
        user_key = _user_dir_key(user)
        spec = project_storage.read_spec(user_key, project_id) or {"dataflow": {}}
        spec.setdefault("dataflow", {})["datasets"] = refs
        project_storage.write_spec(user_key, project_id, spec)


def test_saved_computed_dataset_is_browsable_account_level(client, user_and_token):
    _, token = user_and_token
    project_id = create_project(client, token, name="Producer flow")
    shared = Path(os.environ["CURIO_SHARED_DATA"])
    (shared / "acct_out.csv").write_text("city,count\nChicago,10\n", encoding="utf-8")
    save_project_with_output(client, token, project_id, "acct_out.csv", node_id="prod-node")

    expected_id = computed_dataset_id("prod-node", project_id)

    # Account-level browse (no dataflow context): the dataset is present and NOT
    # installed anywhere — available to install later.
    items = _catalog(client, token)
    item = next((i for i in items if i["id"] == expected_id), None)
    assert item is not None, [i["id"] for i in items]
    assert item["origin"] == "computed"
    assert item["installed"] is False
    # Lineage links it to the producing workflow + node.
    assert item["producerNodeId"] == "prod-node"
    assert item["producerDataflowId"] == project_id


def test_computed_dataset_shows_available_in_another_dataflow(client, user_and_token):
    _, token = user_and_token
    producer = create_project(client, token, name="Producer")
    other = create_project(client, token, name="Other flow")
    shared = Path(os.environ["CURIO_SHARED_DATA"])
    (shared / "cross_out.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    save_project_with_output(client, token, producer, "cross_out.csv", node_id="x-node")

    expected_id = computed_dataset_id("x-node", producer)

    # Browsing the catalog from a DIFFERENT dataflow: the dataset is visible
    # (account-level) but not installed in that other dataflow.
    items = _catalog(client, token, dataflow_id=other)
    item = next((i for i in items if i["id"] == expected_id), None)
    assert item is not None, [i["id"] for i in items]
    assert item["installed"] is False
    assert item["producerDataflowId"] == producer


def test_reused_node_id_does_not_cross_mark_installed(app, client, user_and_token):
    """#168: installed-state matching must key on the full namespaced id.

    Duplicate Project copies node ids AND dataset refs verbatim, so the copy's
    ref points at the ORIGINAL's dataset while both dataflows share the
    producer node id. A bare producer-node match then falsely marks the copy's
    own dataset installed.
    """
    user, token = user_and_token
    a = create_project(client, token, name="Original")
    b = create_project(client, token, name="Original (copy)")
    shared = Path(os.environ["CURIO_SHARED_DATA"])
    (shared / "dup_out_a.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    save_project_with_output(client, token, a, "dup_out_a.csv", node_id="shared-n")
    (shared / "dup_out_b.csv").write_text("a,b\n3,4\n", encoding="utf-8")
    save_project_with_output(client, token, b, "dup_out_b.csv", node_id="shared-n")

    id_a = computed_dataset_id("shared-n", a)
    id_b = computed_dataset_id("shared-n", b)

    # B's spec carries a ref copied verbatim from A.
    _write_refs(app, user, b, [{
        "datasetId": id_a, "dirName": f"{id_a}@1",
        "origin": "computed", "producerNodeId": "shared-n",
    }])

    items = _catalog(client, token, dataflow_id=b)
    by_id = {i["id"]: i for i in items}
    # The ref points at A's dataset — that one IS installed in B.
    assert by_id[id_a]["installed"] is True
    # B's own dataset shares the producer node id but has no ref: it must NOT
    # be marked installed by a bare producer-node match.
    assert by_id[id_b]["installed"] is False


def test_unmigrated_legacy_ref_marks_open_dataflows_dataset_installed(app, client, user_and_token):
    """#168: a spec ref still carrying the pre-namespacing ``computed.<node>``
    id (dir long since renamed) matches the open dataflow's namespaced dataset —
    and only the open dataflow's."""
    user, token = user_and_token
    df = create_project(client, token, name="Legacy ref flow")
    other = create_project(client, token, name="Bystander flow")
    shared = Path(os.environ["CURIO_SHARED_DATA"])
    (shared / "legacy_out.csv").write_text("a\n1\n", encoding="utf-8")
    save_project_with_output(client, token, df, "legacy_out.csv", node_id="leg-node")

    namespaced = computed_dataset_id("leg-node", df)
    legacy_ref = {
        "datasetId": "computed.leg-node", "dirName": "computed.leg-node@1",
        "origin": "computed", "producerNodeId": "leg-node",
    }

    _write_refs(app, user, df, [legacy_ref])
    items = _catalog(client, token, dataflow_id=df)
    item = next(i for i in items if i["id"] == namespaced)
    assert item["installed"] is True

    # Alias is scoped to the owning dataflow: the same legacy ref in ANOTHER
    # dataflow must not mark this dataflow's dataset installed there.
    _write_refs(app, user, df, [])
    _write_refs(app, user, other, [dict(legacy_ref)])
    items = _catalog(client, token, dataflow_id=other)
    item = next(i for i in items if i["id"] == namespaced)
    assert item["installed"] is False


def test_needs_reinstall_flagged_on_id_match_when_output_changed(app, client, user_and_token):
    """#168 (latent fix): a re-executed node's newer live output flags
    needsReinstall on the id-matched installed dataset."""
    user, token = user_and_token
    df = create_project(client, token, name="Reinstall flow")
    shared = Path(os.environ["CURIO_SHARED_DATA"])
    (shared / "ri_out.csv").write_text("a\n1\n", encoding="utf-8")
    save_project_with_output(client, token, df, "ri_out.csv", node_id="ri-node")

    dataset_id = computed_dataset_id("ri-node", df)
    _write_refs(app, user, df, [{
        "datasetId": dataset_id, "dirName": f"{dataset_id}@1",
        "origin": "computed", "producerNodeId": "ri-node",
    }])

    # Same filename → no reinstall prompt.
    items = _catalog(client, token, dataflow_id=df,
                     live_outputs=[{"node_id": "ri-node", "filename": "ri_out.csv"}])
    item = next(i for i in items if i["id"] == dataset_id)
    assert item.get("needsReinstall") is not True

    # The node re-ran and produced a new artifact → reinstall prompt.
    items = _catalog(client, token, dataflow_id=df,
                     live_outputs=[{"node_id": "ri-node", "filename": "ri_out2.csv"}])
    item = next(i for i in items if i["id"] == dataset_id)
    assert item.get("needsReinstall") is True
