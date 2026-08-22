"""Execution-time computed-dataset persistence + diagnostics.

Executing a dataflow node must persist JSON outputs (dict/list/scalar) as
computed datasets immediately — parity with the project-save installer — not
only DataFrame/GeoDataFrame parquet. A node that produces no persistable
dataset must surface a per-node diagnostic instead of failing silently.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock

from utk_curio.backend.app.datasets.install.installer import computed_dataset_id, sanitize_node_id_segment
from utk_curio.backend.tests.test_datasets.computed_test_helpers import (
    auth_headers,
    create_project,
)


def _mock_sandbox(monkeypatch, output):
    resp = MagicMock()
    resp.json.return_value = {"stdout": "", "stderr": "", "output": output}
    monkeypatch.setattr(
        "utk_curio.backend.app.api.routes._sandbox_call",
        lambda *args, **kwargs: resp,
    )


def _exec(client, token, *, node_id, node_type, project_id):
    return client.post(
        "/processPythonCode",
        data=json.dumps({
            "code": "    return out\n",
            "nodeType": node_type,
            "nodeId": node_id,
            "dataflowId": project_id,
            "input": {"path": "", "dataType": "str"},
            "saveOutputDataset": True,
        }),
        headers=auth_headers(token),
    )


def test_json_dict_output_installs_on_execution(client, user_and_token, monkeypatch):
    """A node returning a dict (no 'dataset' parquet) installs as a json computed
    dataset on execution and reports an ``installed`` diagnostic."""
    _, token = user_and_token
    project_id = create_project(client, token, name="JSON output install")
    shared = Path(os.environ["CURIO_SHARED_DATA"])
    artifact = "1790000000000_deadbeef.json"
    (shared / artifact).write_text(json.dumps({"hello": "world"}), encoding="utf-8")

    node_id = "grammar-node"
    _mock_sandbox(monkeypatch, {"path": artifact, "dataType": "dict"})

    resp = _exec(client, token, node_id=node_id, node_type="PYTHON_COMPUTATION", project_id=project_id)
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()

    inst = body.get("installedDataset")
    assert inst is not None, body
    expected_id = computed_dataset_id(node_id, project_id)
    assert inst["id"] == expected_id
    assert inst["origin"] == "computed"
    assert inst["format"] == "json"
    assert body["datasetDiagnostic"]["status"] == "installed"
    assert body["datasetDiagnostic"]["dataType"] == "dict"

    # Visible in the dataflow catalog immediately — no manual save.
    catalog = client.get(
        f"/api/datasets/catalog?includeHub=false&dataflowId={project_id}",
        headers=auth_headers(token),
    ).get_json()
    assert any(i["id"] == expected_id and i["origin"] == "computed" for i in catalog["items"])


def test_sink_node_output_is_skipped_with_diagnostic(client, user_and_token, monkeypatch):
    """A visualization/sink node's output is not persisted; the diagnostic says so."""
    _, token = user_and_token
    project_id = create_project(client, token, name="Sink skip")
    shared = Path(os.environ["CURIO_SHARED_DATA"])
    artifact = "1790000000001_cafebabe.json"
    (shared / artifact).write_text(json.dumps({"$schema": "vega"}), encoding="utf-8")

    _mock_sandbox(monkeypatch, {"path": artifact, "dataType": "dict"})
    resp = _exec(
        client, token, node_id="viz-1", node_type="curio.builtin/vis-vega", project_id=project_id
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    assert body.get("installedDataset") is None
    diag = body.get("datasetDiagnostic", {})
    assert diag.get("status") == "skipped"
    assert "sink" in (diag.get("reason") or "").lower()


def test_versioned_sink_node_output_is_skipped_too(client, user_and_token, monkeypatch):
    """#169: palette-dragged sinks carry ``@<major>`` — the skip must still fire."""
    _, token = user_and_token
    project_id = create_project(client, token, name="Versioned sink skip")
    shared = Path(os.environ["CURIO_SHARED_DATA"])
    artifact = "1790000000004_cafebabe.json"
    (shared / artifact).write_text(json.dumps({"$schema": "vega"}), encoding="utf-8")

    _mock_sandbox(monkeypatch, {"path": artifact, "dataType": "dict"})
    resp = _exec(
        client, token, node_id="viz-2", node_type="curio.builtin/vis-vega@1", project_id=project_id
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    assert body.get("installedDataset") is None
    diag = body.get("datasetDiagnostic", {})
    assert diag.get("status") == "skipped"
    assert "sink" in (diag.get("reason") or "").lower()


def test_no_output_artifact_skips_with_diagnostic(client, user_and_token, monkeypatch):
    """A node whose output carries no artifact reference skips with a reason."""
    _, token = user_and_token
    project_id = create_project(client, token, name="No artifact")
    _mock_sandbox(monkeypatch, {"dataType": "null"})  # no 'path', no 'dataset'
    resp = _exec(client, token, node_id="empty-node", node_type="PYTHON_COMPUTATION", project_id=project_id)
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    assert body.get("installedDataset") is None
    assert body["datasetDiagnostic"]["status"] == "skipped"


def test_exec_without_dataflow_id_skips_persistence(client, user_and_token, monkeypatch):
    """#166: an unsaved dataflow (no dataflowId in the exec payload) must not
    mint a legacy un-namespaced ``computed.<node>`` dir — the auto-save that
    follows persists the namespaced dataset instead."""
    user, token = user_and_token
    shared = Path(os.environ["CURIO_SHARED_DATA"])
    artifact = "1790000000003_beadfeed.json"
    (shared / artifact).write_text(json.dumps({"unsaved": True}), encoding="utf-8")

    _mock_sandbox(monkeypatch, {"path": artifact, "dataType": "dict"})
    resp = client.post(
        "/processPythonCode",
        data=json.dumps({
            "code": "    return out\n",
            "nodeType": "PYTHON_COMPUTATION",
            "nodeId": "unsaved-node",
            # no dataflowId: the frontend omits the key for unsaved dataflows
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
    assert "not saved yet" in (diag.get("reason") or "")

    from utk_curio.backend.app.datasets.infrastructure.storage import list_user_datasets
    assert not any(
        d.name.startswith("computed.") for d in list_user_datasets(str(user.id))
    )


def test_dataframe_output_still_installs_via_dataset_key(client, user_and_token, monkeypatch):
    """Regression: a (geo)dataframe that saved a parquet still installs via the
    'dataset' key (the pre-existing path), unchanged."""
    _, token = user_and_token
    project_id = create_project(client, token, name="DF regression")
    shared = Path(os.environ["CURIO_SHARED_DATA"])
    parquet = "1790000000002_feed0001_output.parquet"
    (shared / parquet).write_bytes(b"PAR1")

    node_id = "df-node"
    _mock_sandbox(monkeypatch, {"path": "art-x", "dataType": "dataframe", "dataset": parquet})
    resp = _exec(client, token, node_id=node_id, node_type="PYTHON_COMPUTATION", project_id=project_id)
    assert resp.status_code == 200, resp.get_data(as_text=True)
    inst = resp.get_json().get("installedDataset")
    assert inst is not None
    assert inst["id"] == computed_dataset_id(node_id, project_id)
