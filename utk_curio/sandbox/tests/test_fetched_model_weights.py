"""Weights a model package's fetch names: read in place, never copied into a run.

A model package whose weights its model block's ``fetch`` names ships without
them, and the backend downloads them before a node's first run of the model.
With ``curio.py start --model-weights-dir`` they sit in a folder of their own,
which a deployment mounts, and the backend sends that folder in
``model_weights`` beside the model's own folder in ``models``:

- an isolated run stages the model's folder (its manifest) into the scratch
  directory, and never the weights: a hardlink cannot cross the mount they
  sit on, so staging them would copy gigabytes into every run;
- the child, and an in-process run, read them where they are
  (``CurioModel.path``);
- a model whose weights are not here, whose download failed or stopped,
  stops at ``curio_load_model``, naming the script that fetches them;
- ``curio_segment`` refuses a ``concept-segmentation`` model.

New names are imported inside the tests, so a checkout without them fails
each test on its own.
"""

from __future__ import annotations

import errno
import json
import os
import shutil
import textwrap
from pathlib import Path

import pytest

MODEL_ID = "model.test.prompted"
DIR = f"{MODEL_ID}@1"
ENTRY = "models/checkpoint"
FILES = {"config.json": b'{"model_type": "tiny"}', "model.safetensors": bytes(range(256)) * 4}


def _manifest() -> dict:
    return {
        "id": MODEL_ID, "version": "1.0.0", "name": "Prompted segmenter", "kind": "model",
        "model": {
            "type": "concept-segmentation", "runtime": "transformers", "entry": ENTRY,
            "labels": ["person", "bicycle"], "license": "Acme's terms",
            "fetch": {
                "huggingface": "acme/tiny-prompted", "revision": "3c879f39826c281e95690f02c7821c4de09afae7",
                "files": [{"path": "config.json", "gitSha1": "0" * 40},
                          {"path": "model.safetensors", "sha256": "0" * 64}],
            },
        },
    }


@pytest.fixture
def package(tmp_path):
    """The catalog's copy of the package: its manifest, no weights."""
    folder = tmp_path / "catalog" / DIR
    folder.mkdir(parents=True)
    (folder / "manifest.json").write_text(json.dumps(_manifest()), encoding="utf-8")
    return folder


def _fetch_into(root: Path, *names: str) -> Path:
    entry = root / ENTRY
    entry.mkdir(parents=True, exist_ok=True)
    for name, data in FILES.items():
        if not names or name in names:
            (entry / name).write_bytes(data)
    return root


@pytest.fixture
def weights(tmp_path):
    """The package's folder under ``--model-weights-dir``, every file fetched."""
    return _fetch_into(tmp_path / "model-weights" / DIR)


@pytest.fixture
def scratch(tmp_path):
    path = tmp_path / "scratch"
    path.mkdir()
    return path


def _namespace():
    import numpy as np
    import pandas as pd

    return {"np": np, "pd": pd}


# ---------------------------------------------------------------------------
# Without the weights
# ---------------------------------------------------------------------------

def test_a_model_whose_weights_are_not_here_says_how_to_fetch_them(package):
    """A first use whose download failed, as on a server that cannot reach
    Hugging Face."""
    from utk_curio.sandbox.util.catalog_helpers import install_catalog_helpers
    from utk_curio.sandbox.util.models import NOT_FETCHED

    namespace = {}
    install_catalog_helpers(
        namespace, data_path=str, formats={}, collections={}, media_dir=None, models={MODEL_ID: str(package)},
    )
    with pytest.raises(RuntimeError) as raised:
        namespace["curio_load_model"](MODEL_ID)
    assert str(raised.value) == NOT_FETCHED.format(model_id=MODEL_ID)
    assert str(raised.value) == (
        f"The weights of model '{MODEL_ID}' are not on this Curio, and Curio could not download them. "
        f"Whoever runs this Curio can fetch them once, with: python scripts/fetch_model_weights.py {MODEL_ID}"
    )


def test_a_fetch_that_stopped_halfway_is_not_fetched(package, tmp_path):
    from utk_curio.sandbox.util.catalog_helpers import CurioModel
    from utk_curio.sandbox.util.models import NOT_FETCHED

    root = _fetch_into(tmp_path / "model-weights" / DIR, "config.json")
    with pytest.raises(RuntimeError) as raised:
        CurioModel(MODEL_ID, str(package), str(root))
    assert str(raised.value) == NOT_FETCHED.format(model_id=MODEL_ID)


# ---------------------------------------------------------------------------
# Read in place
# ---------------------------------------------------------------------------

def test_the_weights_are_read_where_they_are_and_the_labels_are_the_prompts(package, weights):
    """The manifest from the model's folder, the weights from theirs. The
    labels a manifest lists, a concept segmentation model's prompts, come back
    as every model's do, with no runner opened."""
    from utk_curio.sandbox.util.catalog_helpers import CurioModel

    model = CurioModel(MODEL_ID, str(package), str(weights))

    assert model.folder == str(package)
    assert model.path == str(weights / ENTRY)
    assert sorted(os.listdir(model.path)) == sorted(FILES)
    assert model.labels == ["person", "bicycle"]
    assert model._runner is None


def test_weights_fetched_into_the_models_own_folder_are_read_there(package):
    from utk_curio.sandbox.util.catalog_helpers import CurioModel

    _fetch_into(package)
    assert CurioModel(MODEL_ID, str(package)).path == str(package / ENTRY)


def test_curio_segment_refuses_a_concept_segmentation_model(package, weights):
    from utk_curio.sandbox.util.catalog_helpers import CurioModel
    from utk_curio.sandbox.util.vision import make_curio_segment

    with pytest.raises(ValueError, match="finds the things text prompts name"):
        make_curio_segment()(None, CurioModel(MODEL_ID, str(package), str(weights)))


def test_an_in_process_run_reads_them_in_place(package, weights):
    from utk_curio.sandbox.app.worker import _worker_init, execute_code
    from utk_curio.sandbox.util.db import init_db

    _worker_init()
    init_db()
    code = (
        "    import os\n"
        f"    model = curio_load_model('{MODEL_ID}')\n"
        f"    assert model.path == {str(weights / ENTRY)!r}, model.path\n"
        "    return os.path.isfile(os.path.join(model.path, 'model.safetensors'))\n"
    )
    result = execute_code(
        code, "", "PYTHON_COMPUTATION", "", save_dataset=False,
        models={MODEL_ID: str(package)}, model_weights={MODEL_ID: str(weights)},
    )
    assert result["stderr"] == ""
    assert result["output"]["dataType"] == "bool"


def test_an_isolated_child_reads_them_in_place(package, weights, scratch):
    """The model's folder is staged; the weights are not, and the child reads
    them at their own absolute path."""
    from utk_curio.sandbox.isolation import child
    from utk_curio.sandbox.util import staging

    staged = staging.stage_model_dirs({MODEL_ID: str(package)}, scratch)
    request = {
        "code": f"    return curio_load_model('{MODEL_ID}').path\n",
        "node_type": "curio.builtin/python-computation", "data_type": "",
        "scratch_dir": str(scratch), "input": {"kind": "none"}, "dataset_paths": {},
        "models": staged, "model_weights": {MODEL_ID: str(weights)}, "session_imports": [], "limits": {},
    }

    result = child.run_node(request, _namespace)

    assert result["ok"], result["stderr"]
    assert result["output"]["value"] == str(weights / ENTRY)
    assert (scratch / "model_0" / "manifest.json").is_file()
    assert not (scratch / "model_0" / "models").exists()


def test_the_request_carries_them_absolute_and_unstaged(scratch, weights):
    """Over the wire to the zygote, which hands the child the request whole."""
    from utk_curio.sandbox.isolation import protocol

    request = protocol.build_exec_request(
        code="", node_type="x", data_type="", scratch_dir=scratch, input_spec={"kind": "none"},
        models={MODEL_ID: "model_0"}, model_weights={MODEL_ID: str(weights)},
    )
    assert request["models"] == {MODEL_ID: "model_0"}
    assert request["model_weights"] == {MODEL_ID: str(weights)}
    received = protocol.decode_request(protocol.encode_request(request))
    assert received["model_weights"] == {MODEL_ID: str(weights)}


# ---------------------------------------------------------------------------
# An isolated run, up to its zygote: nothing of the weights is linked or copied
# ---------------------------------------------------------------------------

class _Zygote:
    """The zygote's half of an isolated run: keeps the request it is handed
    and the files its scratch directory holds while the child would run."""

    handed: list = []

    def __init__(self, socket_path):
        self.socket_path = socket_path

    def run(self, request, wall_timeout=None):
        scratch = Path(request["scratch_dir"])
        files = sorted(path.relative_to(scratch).as_posix() for path in scratch.rglob("*") if path.is_file())
        _Zygote.handed.append((request, files))
        return 0, None, False


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """A sandbox on a data folder of its own that runs Python isolated, whose
    links all fail as across two mounts: what it hands its zygote, and every
    file staging copied."""
    from utk_curio.sandbox.app import api
    from utk_curio.sandbox.isolation import runner, supervisor
    from utk_curio.sandbox.util import staging
    from utk_curio.sandbox.util.db import init_db, release_connection

    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))
    monkeypatch.setenv("CURIO_SHARED_DATA", "./.curio/data/")
    (tmp_path / ".curio" / "data").mkdir(parents=True)
    config = runner.IsolationConfig.from_environment({
        "CURIO_EXEC_PARALLELISM": "1",
        "CURIO_EXEC_SOCKET": str(tmp_path / "exec-zygote.sock"),
        "CURIO_LAUNCH_CWD": str(tmp_path),
    })
    monkeypatch.setattr(api, "_isolation_state", (runner.execute_isolated, config))
    monkeypatch.setattr(supervisor, "ZygoteClient", _Zygote)
    monkeypatch.setattr(
        supervisor, "read_child_manifest",
        lambda scratch_dir: {"ok": False, "stdout": ["the child ran"], "stderr": ""},
    )

    def no_link(source, destination):
        raise OSError(errno.EXDEV, "Invalid cross-device link", str(source))

    copied = []
    copy = shutil.copy2

    def recorded_copy(source, destination, *args, **kwargs):
        copied.append(Path(source))
        return copy(source, destination, *args, **kwargs)

    _Zygote.handed = []
    release_connection()
    init_db()
    # Staging's own link and copy, as it calls them during the run.
    monkeypatch.setattr(staging.os, "link", no_link)
    monkeypatch.setattr(staging.shutil, "copy2", recorded_copy)
    yield _Zygote.handed, copied
    release_connection()


def test_an_isolated_run_never_copies_them_even_where_links_cannot_reach_them(isolated, package, weights):
    """Every link fails here, as between the weights' read-only mount and the
    scratch directory: the model's manifest is copied in, and the weights are
    neither linked nor copied. The child gets their own absolute folder."""
    from utk_curio.sandbox.app import app

    handed, copied = isolated
    resp = app.test_client().post("/exec", json={
        "code": textwrap.indent(f"return curio_load_model('{MODEL_ID}').path\n", "    "),
        "file_path": "",
        "nodeType": "model.test.prompted/find",
        "dataType": "",
        "session_id": "session-fetched-weights",
        "save_dataset": False,
        "models": {MODEL_ID: str(package)},
        "model_weights": {MODEL_ID: str(weights)},
    })
    reply = json.loads(resp.get_data(as_text=True))
    resp.close()

    assert reply["stdout"] == ["the child ran"], reply
    request, files = handed[-1]
    assert request["models"] == {MODEL_ID: "model_0"}
    assert request["model_weights"] == {MODEL_ID: str(weights)}
    assert "model_0/manifest.json" in files, files
    assert not [name for name in files if name.startswith("model_0/models/")], files
    assert copied, "the model's manifest was neither linked nor copied: staging did not run"
    assert not [source for source in copied if weights in source.parents], copied


def test_weights_outside_the_models_ids_or_not_absolute_never_reach_the_child(isolated, package, weights):
    """The route keeps a weights folder only for a model the run resolved,
    and only an absolute one: the run goes on without either entry, and the
    child is handed neither. Its reply is read, as the caller reads it: the
    run happens while the reply streams."""
    from utk_curio.sandbox.app import app

    handed, copied = isolated
    resp = app.test_client().post("/exec", json={
        "code": textwrap.indent("return 1\n", "    "),
        "file_path": "",
        "nodeType": "model.test.prompted/find",
        "dataType": "",
        "session_id": "session-fetched-weights",
        "save_dataset": False,
        "models": {MODEL_ID: str(package)},
        "model_weights": {"model.test.other": str(weights), MODEL_ID: "model-weights/relative"},
    })
    status, body = resp.status_code, resp.get_data(as_text=True)
    resp.close()

    assert status == 200, (status, body)
    assert json.loads(body)["stdout"] == ["the child ran"], body
    assert len(handed) == 1, handed
    request, files = handed[-1]
    assert request["models"] == {MODEL_ID: "model_0"}
    assert request["model_weights"] == {}
    assert str(weights) not in json.dumps(request)
    assert not [name for name in files if name.startswith("model_0/models/")], files
    assert not [source for source in copied if weights in source.parents], copied
