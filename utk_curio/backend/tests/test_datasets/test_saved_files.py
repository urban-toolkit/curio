"""Files a node saves from its code: ``curio_save_file`` / ``curio_save_folder``
and ``curio_computed_path`` (datasets/install/saved.py, execution/node_exec.py).

- what a run saved becomes ``computed.<dataflowId>.files.<name>@1`` in the
  account's store: a file in its own format, a folder as a bundle, with the
  node and the dataflow as its lineage, and the run's folder is removed;
- only a path under the shared ``saved/`` folder is installed;
- a later run of the dataflow reads a name back as that dataset's file, or the
  bundle's ``files/`` folder, and a run of a dataflow never saved cannot save;
- deleting the dataflow deletes what its nodes saved, and nothing else;
- a run orders the node reading a name after the node saving it.
"""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import pytest

from utk_curio.backend.app.datasets.domain.manifest import load_dataset_manifest
from utk_curio.backend.app.datasets.domain.saved_files import (
    FILE_FORMATS,
    NAME_RE,
    computed_names_in_code,
    saved_names_in_code,
)
from utk_curio.backend.app.datasets.infrastructure.storage import dataset_dir
from utk_curio.backend.app.datasets.install.saved import (
    install_saved_files,
    remove_saved_datasets,
    saved_dataset_id,
)
from utk_curio.backend.app.execution.node_exec import UNSAVED_DATAFLOW_REASON, resolve_computed
from utk_curio.backend.app.execution.run_engine import plan_run
from utk_curio.backend.app.execution.run_plan import SAVED_FILE_EDGE, saved_file_edges
from utk_curio.backend.app.projects.services import _user_dir_key

FLOW = "flow-1"


def _run_folder() -> Path:
    folder = Path(os.environ["CURIO_SHARED_DATA"]) / "saved" / uuid.uuid4().hex
    folder.mkdir(parents=True)
    return folder


def _saved_file(run: Path, name: str, ext: str, text: str) -> dict:
    path = run / name / f"{name}.{ext}"
    path.parent.mkdir(parents=True)
    path.write_text(text, encoding="utf-8")
    return {"name": name, "kind": "file", "file": path.name, "path": str(path)}


def _saved_folder(run: Path, name: str, files: dict) -> dict:
    folder = run / name / "files"
    for relative, data in files.items():
        (folder / relative).parent.mkdir(parents=True, exist_ok=True)
        (folder / relative).write_bytes(data)
    return {"name": name, "kind": "folder", "path": str(folder)}


def test_the_rules_are_the_sandboxs():
    from utk_curio.sandbox.util import saved_files as sandbox

    assert NAME_RE.pattern == sandbox.NAME_RE.pattern
    assert FILE_FORMATS == sandbox.FILE_FORMATS


def test_names_in_code_are_the_literal_calls():
    code = (
        'a.to_csv(curio_save_file("daily-means.csv"))\n'
        'folder = curio_save_folder("tiles")\n'
        'x = curio_computed_path("tiles"); y = curio_computed_path(\'daily-means\')\n'
        'z = curio_computed_path(name)\n'
    )
    assert saved_names_in_code(code) == ["daily-means", "tiles"]
    assert computed_names_in_code(code) == ["tiles", "daily-means"]
    assert saved_dataset_id("Flow 1", "tiles") == "computed.flow-1.files.tiles"
    with pytest.raises(ValueError):
        saved_dataset_id(FLOW, "Tiles")


def test_a_file_and_a_folder_become_computed_datasets_of_the_dataflow(app, user_and_token):
    user, _ = user_and_token
    with app.app_context():
        key = _user_dir_key(user)
        run = _run_folder()
        entries = [
            _saved_file(run, "summary", "csv", "a,b\n1,2\n"),
            _saved_folder(run, "tiles", {"16_1_2.png": b"png", "16/1/x.txt": b"x"}),
        ]
        results = install_saved_files(key, entries, dataflow_id=FLOW, node_id="node-a",
                                      node_type="curio.builtin/computation-analysis", dataflow_name="Shadows")
        assert [(r["name"], r["status"], r["id"]) for r in results] == [
            ("summary", "installed", "computed.flow-1.files.summary"),
            ("tiles", "installed", "computed.flow-1.files.tiles"),
        ]

        summary = load_dataset_manifest(dataset_dir(key, "computed.flow-1.files.summary@1"))
        assert (summary.format, summary.data_file) == ("csv", "data/summary.csv")
        assert (summary.producer_node_id, summary.producer_dataflow_id, summary.producer_dataflow_name) == (
            "node-a", FLOW, "Shadows",
        )
        root = dataset_dir(key, "computed.flow-1.files.tiles@1")
        tiles = load_dataset_manifest(root)
        assert (tiles.format, tiles.data_file) == ("bundle", "data/bundle.json")
        bundle = json.loads((root / "data" / "bundle.json").read_text())
        assert [p["file"] for p in bundle["parts"]] == ["data/files/16/1/x.txt", "data/files/16_1_2.png"]
        assert (root / "data" / "files" / "16_1_2.png").read_bytes() == b"png"
        assert not run.exists(), "the run's saved folder is removed once installed"


def test_running_again_replaces_the_dataset(app, user_and_token):
    user, _ = user_and_token
    with app.app_context():
        key = _user_dir_key(user)
        install_saved_files(key, [_saved_folder(_run_folder(), "tiles", {"a.png": b"1", "b.png": b"2"})],
                            dataflow_id=FLOW, node_id="node-a")
        install_saved_files(key, [_saved_folder(_run_folder(), "tiles", {"c.png": b"3"})],
                            dataflow_id=FLOW, node_id="node-a")
        files = dataset_dir(key, "computed.flow-1.files.tiles@1") / "data" / "files"
        assert sorted(p.name for p in files.iterdir()) == ["c.png"]


def test_a_path_outside_the_saved_folder_is_refused(app, user_and_token, tmp_path):
    user, _ = user_and_token
    with app.app_context():
        key = _user_dir_key(user)
        outside = tmp_path / "secret.csv"
        outside.write_text("x\n1\n")
        [result] = install_saved_files(
            key, [{"name": "secret", "kind": "file", "file": "secret.csv", "path": str(outside)}],
            dataflow_id=FLOW, node_id="node-a",
        )
        assert result["status"] == "failed"
        assert not dataset_dir(key, "computed.flow-1.files.secret@1").exists()


def test_a_later_run_reads_a_name_back(app, client, user_and_token):
    from utk_curio.backend.tests.test_datasets.computed_test_helpers import create_project

    user, token = user_and_token
    flow, other_flow = create_project(client, token, "Saves"), create_project(client, token, "Other")
    with app.app_context():
        key = _user_dir_key(user)
        install_saved_files(key, [_saved_file(_run_folder(), "summary", "csv", "a\n1\n"),
                                  _saved_folder(_run_folder(), "tiles", {"a.png": b"1"})],
                            dataflow_id=flow, node_id="node-a")
        paths: dict = {}
        computed = resolve_computed(
            'curio_computed_path("summary"); curio_computed_path("tiles"); curio_computed_path("nothing")',
            flow, user, paths,
        )
        summary, tiles = saved_dataset_id(flow, "summary"), saved_dataset_id(flow, "tiles")
        assert computed["canSave"] is True
        assert computed["names"] == {"summary": summary, "tiles": tiles}
        assert paths[summary].endswith(f"{summary}@1/data/summary.csv")
        assert paths[tiles].endswith(f"{tiles}@1/data/bundle.json")

        # Another dataflow's nodes do not see them.
        other: dict = {}
        assert resolve_computed('curio_computed_path("summary")', other_flow, user, other)["names"] == {}
        assert other == {}


def test_a_dataflow_never_saved_cannot_save(app, user_and_token):
    user, _ = user_and_token
    with app.app_context():
        computed = resolve_computed('curio_save_file("summary.csv")', None, user, {})
    assert computed == {"names": {}, "canSave": False, "reason": UNSAVED_DATAFLOW_REASON}


def test_deleting_the_dataflow_deletes_what_it_saved(app, user_and_token):
    user, _ = user_and_token
    with app.app_context():
        key = _user_dir_key(user)
        install_saved_files(key, [_saved_file(_run_folder(), "summary", "csv", "a\n1\n")],
                            dataflow_id=FLOW, node_id="node-a")
        install_saved_files(key, [_saved_file(_run_folder(), "summary", "csv", "a\n2\n")],
                            dataflow_id="flow-2", node_id="node-a")
        assert remove_saved_datasets(key, FLOW) == 1
        assert not dataset_dir(key, "computed.flow-1.files.summary@1").exists()
        assert dataset_dir(key, "computed.flow-2.files.summary@1").exists()


def test_deleting_a_project_deletes_what_its_nodes_saved(app, client, user_and_token):
    from utk_curio.backend.app.projects import services
    from utk_curio.backend.tests.test_datasets.computed_test_helpers import create_project

    user, token = user_and_token
    project_id = create_project(client, token)
    with app.app_context():
        key = _user_dir_key(user)
        install_saved_files(key, [_saved_file(_run_folder(), "summary", "csv", "a\n1\n")],
                            dataflow_id=project_id, node_id="node-a")
        root = dataset_dir(key, f"{saved_dataset_id(project_id, 'summary')}@1")
        assert root.exists()
        services.delete_project(user, project_id)
        assert not root.exists()


def _node(node_id, content="return 1", kind="curio.builtin/computation-analysis"):
    return {"id": node_id, "type": kind, "content": content, "x": 0, "y": 0}


def test_a_run_orders_the_reader_after_the_saver_with_no_edge():
    nodes = [
        _node("reader", 'return pd.read_csv(curio_computed_path("summary"))'),
        _node("saver", 'df.to_csv(curio_save_file("summary.csv"))\nreturn df'),
        _node("alone"),
    ]
    edges = saved_file_edges(nodes)
    assert [(e["source"], e["target"], e["type"]) for e in edges] == [("saver", "reader", SAVED_FILE_EDGE)]

    spec = {"dataflow": {"nodes": nodes, "edges": []}}
    plan = plan_run(spec)
    level = {node_id: index for index, ids in enumerate(plan.levels) for node_id in ids}
    assert level["saver"] < level["reader"]
    # Playing the reader runs the saver first, but the ordering edge is no input.
    played = plan_run(spec, target_node_id="reader")
    assert {n for ids in played.levels for n in ids} == {"saver", "reader"}
    assert played.spec.upstream_nodes("reader") == []


def test_a_node_reading_what_it_saves_orders_nothing():
    nodes = [_node("both", 'curio_save_file("x.csv"); curio_computed_path("x")')]
    assert saved_file_edges(nodes) == []
