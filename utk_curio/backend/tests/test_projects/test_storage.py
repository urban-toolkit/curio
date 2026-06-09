"""Tests for projects/storage.py — FS operations."""
import json
import pytest

from utk_curio.backend.app.projects import storage
from utk_curio.backend.app.projects.schemas import OutputRef


def test_ensure_project_dir(tmp_curio):
    d = storage.ensure_project_dir("1", "proj-aaa")
    assert d.exists()
    assert (d / "data").exists()


def test_write_and_read_spec(tmp_curio):
    spec = {"dataflow": {"name": "test", "nodes": [], "edges": []}}
    storage.write_spec("1", "proj-bbb", spec)
    result = storage.read_spec("1", "proj-bbb")
    assert result == spec


def test_read_spec_missing(tmp_curio):
    assert storage.read_spec("1", "no-exist") is None


def test_copy_outputs_happy(tmp_curio):
    shared = storage._shared_data_dir()
    shared.mkdir(parents=True, exist_ok=True)
    (shared / "file1.data").write_bytes(b"hello")

    refs = [OutputRef(node_id="n1", filename="file1.data")]
    copied = storage.copy_outputs("1", "proj-ccc", refs)
    assert len(copied) == 1

    proj_data = storage.project_dir("1", "proj-ccc") / "data" / "file1.data"
    assert proj_data.read_bytes() == b"hello"


def test_copy_outputs_missing_source(tmp_curio):
    refs = [OutputRef(node_id="n1", filename="missing.data")]
    copied = storage.copy_outputs("1", "proj-ddd", refs)
    assert len(copied) == 0


def test_hydrate_outputs(tmp_curio):
    proj_dir = storage.ensure_project_dir("1", "proj-eee")
    (proj_dir / "data" / "out.data").write_bytes(b"world")

    refs = [OutputRef(node_id="n1", filename="out.data")]
    hydrated = storage.hydrate_outputs("1", "proj-eee", refs)
    assert len(hydrated) == 1

    shared = storage._shared_data_dir()
    assert (shared / "out.data").read_bytes() == b"world"


def test_hydrate_outputs_from_user_dataset_store(tmp_curio):
    from utk_curio.backend.app.datasets.installer import install_computed_file_for_node

    user_key = "1"
    node_id = "node-hydrate"
    install_computed_file_for_node(
        user_key,
        b"city,count\nChicago,10\n",
        "hydrate_out.csv",
        "csv",
        node_id=node_id,
    )

    spec = {
        "dataflow": {
            "datasets": [{
                "datasetId": "computed.node-hydrate",
                "dirName": "computed.node-hydrate@1",
                "origin": "computed",
                "producerNodeId": node_id,
            }],
        },
    }
    refs = [OutputRef(node_id=node_id, filename="hydrate_out.csv")]
    hydrated = storage.hydrate_outputs("1", "proj-hydrate", refs, spec=spec)
    assert len(hydrated) == 1

    shared = storage._shared_data_dir()
    assert (shared / "hydrate_out.csv").read_text(encoding="utf-8").startswith("city,count")


def test_path_traversal_blocked(tmp_curio):
    with pytest.raises(PermissionError, match="traversal"):
        storage.project_dir("1", "../../etc")


def test_write_and_read_manifest(tmp_curio):
    storage.ensure_project_dir("1", "proj-fff")
    refs = [OutputRef(node_id="n1", filename="x.data")]
    storage.write_manifest("1", "proj-fff", 1, refs)
    m = storage.read_manifest("1", "proj-fff")
    assert m["project_id"] == "proj-fff"
    assert len(m["outputs"]) == 1


def test_delete_tree(tmp_curio):
    d = storage.ensure_project_dir("1", "proj-ggg")
    assert d.exists()
    storage.delete_tree("1", "proj-ggg")
    assert not d.exists()
