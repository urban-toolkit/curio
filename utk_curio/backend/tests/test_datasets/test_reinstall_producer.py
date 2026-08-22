"""Reinstalling a computed dataset must preserve its producer link.

A computed dataset encodes its producing node in its id/dirName
(``computed.<sanitizedNodeId>``). When a dataset is uninstalled and reinstalled
from a previous computed node, the install flow can receive an item whose
``producerNodeId`` was dropped (origin flipped to "imported"). The install must
recover the producer so the persisted ref keeps ``producerNodeId`` / computed
origin and the catalog/palette upstream badge stays visible.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from utk_curio.backend.app.datasets.install.installer import (
    node_segment_from_computed_id,
)
from utk_curio.backend.tests.test_datasets.computed_test_helpers import (
    auth_headers,
    create_project,
    save_project_with_output,
)


def test_producer_segment_recovery_uses_node_segment():
    """#167 parser cleanup: recovery parses the NODE segment — never the full
    ``<dataflow>.<node>`` pair a namespaced id carries."""
    assert node_segment_from_computed_id("computed.node-7") == "node-7"
    assert node_segment_from_computed_id("computed.whatif-modified-map@1") == "whatif-modified-map"
    assert node_segment_from_computed_id("computed.x@3") == "x"
    # Namespaced form: only the node segment comes back.
    assert node_segment_from_computed_id("computed.flow-uuid.node-7@1") == "node-7"
    # Not a computed dataset.
    assert node_segment_from_computed_id("it.urbanlab.example") is None
    assert node_segment_from_computed_id(None) is None


def test_reinstall_preserves_producer_node_id(client, user_and_token):
    """Reinstalling with a producer-less ``sourceItem`` recovers producerNodeId
    from the computed id and restores the computed origin."""
    _, token = user_and_token
    project_id = create_project(client, token, name="Reinstall producer")
    shared = Path(os.environ["CURIO_SHARED_DATA"])
    (shared / "result.csv").write_text("id,value\n1,42\n", encoding="utf-8")

    # Auto-install a computed dataset for node "map-node" (gets producerNodeId).
    save_project_with_output(client, token, project_id, "result.csv", node_id="map-node")
    catalog = client.get(
        f"/api/datasets/catalog?includeHub=false&dataflowId={project_id}",
        headers=auth_headers(token),
    ).get_json()
    computed = next(i for i in catalog["items"] if i["origin"] == "computed")
    assert computed["producerNodeId"] == "map-node"

    # Reinstall as if the ref had lost its producer link: origin "imported",
    # producerNodeId null, but the same on-disk dirName.
    resp = client.post(
        f"/api/dataflows/{project_id}/datasets/install",
        data=json.dumps({
            "datasetId": computed["id"],
            "sourceItem": {
                "id": computed["id"],
                "dirName": computed["dirName"],
                "origin": "imported",
                "producerNodeId": None,
            },
        }),
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()

    # The producer link and computed origin are recovered.
    assert body["producerNodeId"] == "map-node"
    assert body["origin"] == "computed"

    # And the persisted ref carries it, so the next listing keeps the badge.
    relisted = client.get(
        f"/api/datasets/catalog?includeHub=false&dataflowId={project_id}",
        headers=auth_headers(token),
    ).get_json()
    reinstalled = next(i for i in relisted["items"] if i["id"] == computed["id"])
    assert reinstalled["producerNodeId"] == "map-node"
    assert reinstalled["origin"] == "computed"
