"""``curio_load_model``: a Model Catalog folder reaching a node, in process and isolated.

A model is a folder whose files name each other (an ``.onnx`` graph reads its
external weights by relative name), so under isolation the tree is staged
whole, each file at its own relative path.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from utk_curio.sandbox.isolation import child, protocol
from utk_curio.sandbox.util import staging
from utk_curio.sandbox.util.models import make_model_folder


@pytest.fixture
def model(tmp_path):
    root = tmp_path / "models" / "model.example.tiny@1"
    (root / "files" / "nested").mkdir(parents=True)
    (root / "manifest.json").write_text("{}", encoding="utf-8")
    (root / "files" / "m.onnx").write_bytes(b"graph naming m.data")
    (root / "files" / "m.data").write_bytes(b"weights")
    (root / "files" / "nested" / "config.json").write_text("{}", encoding="utf-8")
    return root


@pytest.fixture
def scratch(tmp_path):
    path = tmp_path / "scratch"
    path.mkdir()
    return path


def test_a_model_is_staged_as_its_whole_tree(model, scratch):
    staged = staging.stage_model_dirs({"model.example.tiny": str(model)}, scratch)
    assert staged == {"model.example.tiny": "model_0"}
    target = scratch / "model_0"
    names = sorted(str(p.relative_to(target)) for p in target.rglob("*") if p.is_file())
    assert names == ["files/m.data", "files/m.onnx", "files/nested/config.json", "manifest.json"]
    assert (target / "files" / "m.data").read_bytes() == b"weights"


def test_staged_files_are_links_where_the_disk_allows(model, scratch):
    staging.stage_model_dirs({"m": str(model)}, scratch)
    source, staged = model / "files" / "m.data", scratch / "model_0" / "files" / "m.data"
    if hasattr(os, "link"):
        assert os.stat(source).st_ino == os.stat(staged).st_ino


def test_a_link_out_of_the_folder_is_not_followed(model, scratch, tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("not the model's", encoding="utf-8")
    (model / "files" / "escape.txt").symlink_to(secret)
    staging.stage_model_dirs({"m": str(model)}, scratch)
    assert not (scratch / "model_0" / "files" / "escape.txt").exists()


def test_a_missing_folder_is_dropped_not_raised(scratch, tmp_path):
    assert staging.stage_model_dirs({"gone": str(tmp_path / "nope")}, scratch) == {}


def test_two_models_get_two_folders(model, scratch, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    (other / "x.onnx").write_bytes(b"x")
    staged = staging.stage_model_dirs({"a": str(model), "b": str(other)}, scratch)
    assert staged == {"a": "model_0", "b": "model_1"}


def test_the_resolver_names_a_missing_model():
    curio_load_model = make_model_folder({"a": "/models/a@1"})
    assert curio_load_model("a") == "/models/a@1"
    with pytest.raises(RuntimeError, match="Model 'b' is not available.*Model Catalog"):
        curio_load_model("b")


def test_a_staged_name_is_joined_to_scratch(scratch):
    assert make_model_folder({"a": "model_0"}, base=str(scratch))("a") == os.path.join(str(scratch), "model_0")


def test_the_request_carries_the_staged_names(scratch):
    request = protocol.build_exec_request(
        code="", node_type="x", data_type="", scratch_dir=scratch, input_spec={"kind": "none"},
        models={"a": "model_0"},
    )
    assert request["models"] == {"a": "model_0"}


def _namespace():
    import numpy as np
    import pandas as pd

    return {"np": np, "pd": pd}


def test_an_isolated_child_reads_the_staged_model(model, scratch):
    staged = staging.stage_model_dirs({"model.example.tiny": str(model)}, scratch)
    request = {
        "code": (
            "    import os\n"
            "    folder = curio_load_model('model.example.tiny')\n"
            "    return open(os.path.join(folder, 'files', 'm.data'), 'rb').read().decode()\n"
        ),
        "node_type": "curio.builtin/computation-analysis", "data_type": "",
        "scratch_dir": str(scratch), "input": {"kind": "none"}, "dataset_paths": {},
        "models": staged, "session_imports": [], "limits": {},
    }
    result = child.run_node(request, _namespace)
    assert result["ok"], result["stderr"]
    assert result["output"]["value"] == "weights"


def test_an_in_process_run_reads_the_model_where_it_is(model):
    from utk_curio.sandbox.app.worker import _worker_init, execute_code
    from utk_curio.sandbox.util.db import init_db

    _worker_init()
    init_db()
    code = (
        "    import os\n"
        "    return os.path.isfile(os.path.join(curio_load_model('m'), 'files', 'm.onnx'))\n"
    )
    result = execute_code(code, "", "PYTHON_COMPUTATION", "", save_dataset=False, models={"m": str(model)})
    assert result["stderr"] == ""
    assert result["output"]["dataType"] == "bool"
