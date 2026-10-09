"""Reinstalling a computed dataset must preserve its producer link.

A computed dataset encodes its producing node in its id/dirName
(``computed.<sanitizedNodeId>``). When a dataset is uninstalled and reinstalled
from a previous computed node, the install flow can receive an item whose
``producerNodeId`` was dropped (origin flipped to "imported"). The install must
recover the producer so the persisted ref keeps ``producerNodeId`` / computed
origin and the catalog/palette upstream badge stays visible.

A re-install also removes the dataset's folder and writes it again, so a
listing running at that moment can find a data file gone right after it
checked for it (#780). The listing must still answer.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from utk_curio.backend.app.datasets.domain.catalog_item import item_from_file
from utk_curio.backend.app.datasets.install.installer import (
    install_computed_file_for_node,
    node_segment_from_computed_id,
)
from utk_curio.backend.app.projects.services import _user_dir_key
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
    assert node_segment_from_computed_id("it.utk.example") is None
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


def _is_file_says_yes_once(monkeypatch, target: Path) -> None:
    """Make ``Path.is_file`` answer True once for *target*, which is gone: the
    answer a check gives just before a re-install removes the file. Every
    other call gets the real answer."""
    real_is_file = Path.is_file
    pending = [Path(os.path.realpath(target))]

    def is_file(self):
        if pending and Path(os.path.realpath(self)) == pending[0]:
            pending.clear()
            return True
        return real_is_file(self)

    monkeypatch.setattr(Path, "is_file", is_file)


def test_listing_answers_while_a_reinstall_removes_the_data_file(
    app, client, user_and_token, monkeypatch
):
    """The listing checks a computed dataset's data file, a re-install removes
    it, then the listing reads its size (#780). The listing must answer 200
    and list the dataset with no size and no path."""
    user, token = user_and_token
    with app.app_context():
        result = install_computed_file_for_node(
            _user_dir_key(user), b"id,value\n1,42\n", "out.csv", "csv",
            node_id="node-780", dataflow_id="flow-780",
        )
    data_file = result.dest / result.manifest.data_file
    assert data_file.is_file()

    data_file.unlink()
    _is_file_says_yes_once(monkeypatch, data_file)

    resp = client.get(
        "/api/datasets/catalog?includeHub=true", headers=auth_headers(token)
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    items = {i["id"]: i for i in resp.get_json()["items"]}
    assert result.manifest.id in items
    listed = items[result.manifest.id]
    assert (listed["sizeBytes"], listed["path"]) == (None, None)


def test_a_workspace_file_removed_after_its_check_is_left_out(tmp_path, monkeypatch):
    """The workspace listing's item builder checks a file, then reads its size
    and date; a file removed between the two is left out, not an error."""
    gone = tmp_path / "gone.csv"
    gone.write_text("id,value\n1,42\n", encoding="utf-8")
    gone.unlink()
    _is_file_says_yes_once(monkeypatch, gone)

    assert item_from_file(gone, source_label="Workspace data") is None
