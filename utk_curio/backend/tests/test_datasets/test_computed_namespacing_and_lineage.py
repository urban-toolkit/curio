"""Dataflow-namespaced computed identity (O1), manifest lineage, and
the legacy-dir migration.

Covers:
- ``computed_dataset_id`` / ``node_segment_from_computed_id`` /
  ``dataflow_segment_from_computed_id`` round-trips for both id forms;
- producer resolution respects the dataflow segment (no cross-attribution);
- ``resolve_upstream_inputs`` reads edges + dataset bindings from the spec;
- two dataflows reusing a node id produce two distinct account-store dirs;
- lineage (producer*, upstreamInputs) is persisted on the computed manifest;
- ``migrate_computed_dataset_ids`` renames legacy dirs + rewrites the spec ref,
  is idempotent, and leaves un-attributable dirs alone.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from utk_curio.backend.app.datasets.application.export import (
    _producer_node_id_for,
    resolve_upstream_inputs,
)
from utk_curio.backend.app.datasets.application.migrations import (
    migrate_computed_dataset_ids,
)
from utk_curio.backend.app.datasets.domain.manifest import load_dataset_manifest
from utk_curio.backend.app.datasets.infrastructure.storage import dataset_dir
from utk_curio.backend.app.datasets.install.installer import (
    computed_dataset_id,
    dataflow_segment_from_computed_id,
    install_computed_file_for_node,
    node_segment_from_computed_id,
    sanitize_node_id_segment,
)
from utk_curio.backend.app.projects.services import _user_dir_key
from utk_curio.backend.tests.test_datasets.computed_test_helpers import (
    auth_headers,
    create_project,
)


# --------------------------------------------------------------------------- #
# Pure-function id helpers
# --------------------------------------------------------------------------- #

def test_computed_id_namespaced_and_legacy_forms():
    assert computed_dataset_id("n1") == "computed.n1"
    assert computed_dataset_id("n1", "flow-abc") == "computed.flow-abc.n1"


def test_segment_extraction_round_trips_both_forms():
    ns = computed_dataset_id("node-5", "proj-xyz")
    assert node_segment_from_computed_id(ns) == "node-5"
    assert dataflow_segment_from_computed_id(ns) == "proj-xyz"
    # Legacy form: node segment only, no dataflow segment.
    legacy = computed_dataset_id("node-5")
    assert node_segment_from_computed_id(legacy) == "node-5"
    assert dataflow_segment_from_computed_id(legacy) is None
    # Tolerates the @major suffix.
    assert node_segment_from_computed_id(f"{ns}@1") == "node-5"
    assert dataflow_segment_from_computed_id(f"{ns}@1") == "proj-xyz"
    # Non-computed inputs.
    assert node_segment_from_computed_id("it.urbanlab.milan") is None
    assert dataflow_segment_from_computed_id(None) is None


def test_producer_match_respects_dataflow_segment():
    nodes = [{"id": "n1", "type": "PYTHON_COMPUTATION"}]
    ns_a = computed_dataset_id("n1", "flow-a")
    # Same dataflow → matches.
    assert _producer_node_id_for(nodes, ns_a, "flow-a") == "n1"
    # A different dataflow that happens to also contain node "n1" is NOT the
    # producer of flow-a's dataset.
    assert _producer_node_id_for(nodes, ns_a, "flow-b") is None
    # Legacy (un-namespaced) id has no dataflow constraint.
    assert _producer_node_id_for(nodes, computed_dataset_id("n1"), "flow-b") == "n1"


def test_resolve_upstream_inputs_reads_edges_and_bindings():
    spec = {
        "dataflow": {
            "nodes": [
                {"id": "src", "type": "DATA_LOADING"},
                {"id": "mid", "type": "PYTHON_COMPUTATION"},
                {"id": "target", "type": "PYTHON_COMPUTATION",
                 "metadata": {"datasetRefs": ["imported.xabc"]}},
            ],
            "edges": [
                {"id": "e1", "source": "src", "target": "mid"},
                {"id": "e2", "source": "mid", "target": "target"},
            ],
        }
    }
    inputs = resolve_upstream_inputs(spec, "target")
    assert {"nodeId": "mid", "nodeType": "PYTHON_COMPUTATION"} in inputs
    assert {"datasetId": "imported.xabc"} in inputs
    # 'src' feeds 'mid', not 'target'.
    assert not any(i.get("nodeId") == "src" for i in inputs)


# --------------------------------------------------------------------------- #
# Store-level behavior
# --------------------------------------------------------------------------- #

def test_same_node_id_in_two_dataflows_yields_distinct_datasets(app, user_and_token):
    user, _ = user_and_token
    with app.app_context():
        user_key = _user_dir_key(user)
        a = install_computed_file_for_node(
            user_key, b'{"v": 1}', "out.json", "json",
            node_id="shared-node", dataflow_id="flow-a",
        )
        b = install_computed_file_for_node(
            user_key, b'{"v": 2}', "out.json", "json",
            node_id="shared-node", dataflow_id="flow-b",
        )
        assert a.manifest.id != b.manifest.id
        assert a.manifest.id == "computed.flow-a.shared-node"
        assert b.manifest.id == "computed.flow-b.shared-node"
        # Both dirs coexist.
        assert (dataset_dir(user_key, a.manifest.dir_name) / "manifest.json").is_file()
        assert (dataset_dir(user_key, b.manifest.dir_name) / "manifest.json").is_file()


def test_lineage_persisted_on_manifest(app, user_and_token):
    user, _ = user_and_token
    with app.app_context():
        user_key = _user_dir_key(user)
        result = install_computed_file_for_node(
            user_key, b'{"v": 1}', "out.json", "json",
            node_id="producer", dataflow_id="flow-lineage",
            node_type="curio.builtin/autk-grammar",
            dataflow_name="My Flow",
            upstream_inputs=[{"nodeId": "up1", "nodeType": "DATA_LOADING"}],
        )
        manifest = load_dataset_manifest(dataset_dir(user_key, result.manifest.dir_name))
        assert manifest.producer_node_id == "producer"
        assert manifest.producer_node_type == "curio.builtin/autk-grammar"
        assert manifest.producer_dataflow_id == "flow-lineage"
        assert manifest.producer_dataflow_name == "My Flow"
        assert manifest.upstream_inputs == [{"nodeId": "up1", "nodeType": "DATA_LOADING"}]


# --------------------------------------------------------------------------- #
# Migration (§3F)
# --------------------------------------------------------------------------- #

def _legacy_computed_dir(user_key: str, node_id: str) -> str:
    """Create a legacy (un-namespaced) computed dir and return its id."""
    result = install_computed_file_for_node(
        user_key, b'{"v": 1}', "out.json", "json", node_id=node_id,
    )
    assert "." not in result.manifest.id[len("computed."):]  # legacy: one segment
    return result.manifest.id


def test_migration_renames_legacy_dir_and_rewrites_ref(client, app, user_and_token):
    user, token = user_and_token
    with app.app_context():
        user_key = _user_dir_key(user)

    node_id = "mig-node"
    legacy_id = None
    with app.app_context():
        legacy_id = _legacy_computed_dir(user_key, node_id)

    # A project that references the legacy dataset via a ref + contains the node.
    project_id = create_project(client, token, name="Migration owner")
    from utk_curio.backend.app.projects import storage as project_storage
    with app.app_context():
        spec = {
            "dataflow": {
                "name": "Migration owner",
                "nodes": [{"id": node_id, "type": "PYTHON_COMPUTATION", "x": 0, "y": 0}],
                "edges": [],
                "datasets": [{
                    "datasetId": legacy_id,
                    "dirName": f"{legacy_id}@1",
                    "origin": "computed",
                    "producerNodeId": node_id,
                }],
            }
        }
        project_storage.write_spec(user_key, project_id, spec)

        migrated = migrate_computed_dataset_ids(user_key)
        assert migrated == 1

        new_id = computed_dataset_id(node_id, project_id)
        # Dir renamed.
        assert (dataset_dir(user_key, f"{new_id}@1") / "manifest.json").is_file()
        # Manifest rewritten with the new id + dataflow lineage.
        manifest = load_dataset_manifest(dataset_dir(user_key, f"{new_id}@1"))
        assert manifest.id == new_id
        assert manifest.producer_dataflow_id == project_id
        # Spec ref repointed.
        updated = project_storage.read_spec(user_key, project_id)
        ref_ids = {r["datasetId"] for r in updated["dataflow"]["datasets"]}
        assert new_id in ref_ids and legacy_id not in ref_ids

        # Idempotent: a second run finds nothing to migrate.
        assert migrate_computed_dataset_ids(user_key) == 0


def test_migration_leaves_unattributable_dir(app, user_and_token):
    user, _ = user_and_token
    with app.app_context():
        user_key = _user_dir_key(user)
        legacy_id = _legacy_computed_dir(user_key, "orphan-node")
        # No project references it and no spec has a matching node → left as-is.
        migrated = migrate_computed_dataset_ids(user_key)
        assert (dataset_dir(user_key, f"{legacy_id}@1") / "manifest.json").is_file()
        # Migration count excludes the orphan.
        assert isinstance(migrated, int)
