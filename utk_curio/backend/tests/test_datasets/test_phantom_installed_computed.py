"""Regression tests for phantom "installed" computed datasets (dev/66).

A computed dataset whose legacy un-namespaced store dir (``computed.<node>@1``)
merely exists on disk must list as *available*, never ``installed`` — the old
disk-existence marker flagged it installed with no spec ref, so the drawer's
Installed tab offered an Uninstall that 404d ("Dataset is not installed in this
dataflow"). And execution without a saved dataflow must not mint new
un-namespaced dirs at all: the save-time installer persists the namespaced
dataset on the first project save instead.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock

from utk_curio.backend.app.datasets.infrastructure.storage import dataset_dir
from utk_curio.backend.app.datasets.install.installer import (
    install_computed_file_for_node,
    sanitize_node_id_segment,
)
from utk_curio.backend.app.projects.services import _user_dir_key
from utk_curio.backend.tests.test_datasets.computed_test_helpers import (
    auth_headers,
    create_project,
)


def test_legacy_store_dir_is_not_marked_installed(client, app, user_and_token):
    """The reported bug: ``computed.niteroi-join@1`` exists in the account store
    (legacy un-namespaced, no dataflow lineage), the open dataflow has NO refs —
    the catalog row must be available, not installed."""
    user, token = user_and_token
    node_id = "niteroi-join"
    with app.app_context():
        user_key = _user_dir_key(user)
        # Seed the legacy dir exactly as the old execution path did:
        # dataflow_id=None → un-namespaced ``computed.<node>@1``.
        install_computed_file_for_node(
            user_key,
            b"PAR1",
            "1786031362581_176e2081_output.parquet",
            "parquet",
            node_id=node_id,
            dataflow_id=None,
            title="JS Computation",
        )

    project_id = create_project(client, token, name="Phantom install repro")
    dataset_id = f"computed.{sanitize_node_id_segment(node_id)}"

    catalog = client.get(
        f"/api/datasets/catalog?includeHub=true&dataflowId={project_id}",
        headers=auth_headers(token),
    ).get_json()
    row = next((i for i in catalog["items"] if i["id"] == dataset_id), None)
    assert row is not None, "account-store computed dataset must stay visible"
    # Available, not installed: no ref exists, so an Uninstall would 404.
    assert row.get("installed") is not True


def _mock_sandbox(monkeypatch, output):
    resp = MagicMock()
    resp.json.return_value = {"stdout": "", "stderr": "", "output": output}
    monkeypatch.setattr(
        "utk_curio.backend.app.api.routes._sandbox_call",
        lambda *args, **kwargs: resp,
    )


def test_execution_without_dataflow_id_skips_and_mints_no_legacy_dir(
    client, app, user_and_token, monkeypatch
):
    """Executing a producing node with no saved dataflow (no ``dataflowId``)
    must skip the auto-save with a clear diagnostic and create no un-namespaced
    ``computed.<node>@1`` dir — the writer that kept re-poisoning the store."""
    user, token = user_and_token
    shared = Path(os.environ["CURIO_SHARED_DATA"])
    artifact = "1790000000003_0ddba11.json"
    (shared / artifact).write_text(json.dumps({"hello": "world"}), encoding="utf-8")

    node_id = "unsaved-flow-node"
    _mock_sandbox(monkeypatch, {"path": artifact, "dataType": "dict"})

    resp = client.post(
        "/processPythonCode",
        data=json.dumps({
            "code": "    return out\n",
            "nodeType": "PYTHON_COMPUTATION",
            "nodeId": node_id,
            # No dataflowId: the dataflow has never been saved.
            "input": {"path": "", "dataType": "str"},
            "saveOutputDataset": True,
        }),
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()

    assert body.get("installedDataset") is None
    diag = body.get("datasetDiagnostic", {})
    assert diag.get("status") == "skipped"
    assert "not saved" in (diag.get("reason") or "").lower()

    with app.app_context():
        user_key = _user_dir_key(user)
        legacy_dir = dataset_dir(
            user_key, f"computed.{sanitize_node_id_segment(node_id)}@1"
        )
        assert not legacy_dir.exists()
