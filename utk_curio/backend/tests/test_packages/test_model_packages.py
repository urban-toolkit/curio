"""Model packages: a node package of kind ``model``, which ships its weights.

A model package is a node package (its node, its code, its modules) with a
``model`` block saying how to run the weights under its ``models/`` folder.
The shipped example is Local Relief, in ``docs/bring-your-own-model/``.

- The manifest: the schema and the parser read ``kind`` and the ``model``
  block, with the Model Catalog's checks; the listings carry both and filter
  by kind.
- The archive: ``models/`` belongs to a model package only, whose files may be
  far bigger than a node package's, and every zip goes through disk.
- A user's copy of a shipped model package holds no ``models/``: its weights
  are read where they ship, or where a pip install fetches them, and a
  weight left out of the pip package counts as present until then.
- ``curio_load_model("<id>")`` reaches a model package's weights.

No test opens a socket (``FakeGitHub``). The code under test is imported
inside each test, so a tree without it fails test by test.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import tracemalloc
import zipfile
from pathlib import Path

import pytest

from utk_curio.backend.tests._support.left_out_files import (
    COMMIT,
    FakeGitHub,
    url_of,
    write_record,
)

REPO = Path(__file__).resolve().parents[4]
SCHEMA = REPO / "docs" / "schemas" / "node-package.v4.json"
GUIDE = REPO / "docs" / "bring-your-own-model"
MODEL_ID = "model.example.local-relief"
DIR = f"{MODEL_ID}@1"
LOCAL_RELIEF = GUIDE / DIR
WEIGHT = "models/local_relief.onnx"
#: Where Local Relief's weight would be in the repository if it shipped in
#: ``packages/``: the path a pip install's list of left-out files names.
WEIGHT_REPO_PATH = f"packages/{DIR}/{WEIGHT}"
MIB = 1024 * 1024


def _weight() -> bytes:
    return (LOCAL_RELIEF / WEIGHT).read_bytes()


def _parse(raw: dict, dir_name: str = "ai.test.tiny-model@1"):
    from utk_curio.backend.app.packages.domain.manifest import package_manifest_from_dict

    return package_manifest_from_dict(raw, manifest_path=Path("manifest.json"), dir_name=dir_name)


def _validator():
    from jsonschema import Draft202012Validator

    return Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8")))


def _model_manifest(model: dict | None = None, **top) -> dict:
    """A model package's manifest: one node with a widget, and a segmentation
    model. *model* changes the ``model`` block (a None value removes a key);
    *top* changes the top level."""
    block = {
        "type": "semantic-segmentation", "runtime": "onnx", "entry": "models/m.onnx",
        "labels": ["a", "b"], "input": {"width": 64, "height": 32, "dtype": "float32", "scale": 0.00392},
        "license": "MIT", "sizeBytes": 10,
    }
    for key, value in (model or {}).items():
        if value is None:
            block.pop(key, None)
        else:
            block[key] = value
    raw = {
        "id": "ai.test.tiny-model", "version": "1.0.0", "name": "Tiny model", "publisher": "Test",
        "license": "MIT", "compatibility": {"major": 1}, "kind": "model",
        "templates": [{
            "id": "tiny", "label": "Tiny", "category": "computation", "engine": "python", "editor": "code",
            "inputPorts": [{"types": ["RASTER"]}], "outputPorts": [{"types": ["RASTER"]}],
            "widgets": [{"name": "season", "type": "choice", "default": "summer",
                         "options": {"choices": ["summer", "winter"]}}],
        }],
        "model": block,
    }
    raw.update(top)
    return {key: value for key, value in raw.items() if value is not None}


def _write_random(path: Path, size: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as out:
        left = size
        while left:
            step = min(left, MIB)
            out.write(os.urandom(step))
            left -= step


def _big_model_package(root: Path, size: int, *, package_id: str = "ai.test.big-model") -> Path:
    """A model package whose one weight is *size* bytes of noise."""
    folder = root / f"{package_id}@1"
    _write_random(folder / "models" / "w.onnx", size)
    manifest = {
        "id": package_id, "version": "1.0.0", "name": package_id, "publisher": "Test", "license": "MIT",
        "compatibility": {"major": 1}, "kind": "model",
        "templates": [{"id": "run", "label": "Run", "category": "computation", "engine": "python",
                       "editor": "code", "inputPorts": [], "outputPorts": [{"types": ["JSON"]}]}],
        "model": {"type": "node-regression", "runtime": "onnx", "entry": "models/w.onnx",
                  "labels": [], "license": "MIT", "sizeBytes": size},
    }
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return folder


def _peak(call):
    """``(what call returned, the most memory Python held while it ran)``."""
    tracemalloc.start()
    try:
        result = call()
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return result, peak


def _capture_sandbox(monkeypatch):
    """The backend's calls to the sandbox, recorded instead of made."""
    from utk_curio.backend.app.execution import node_exec

    sent = []

    class Reply:
        status_code = 200

        def json(self):
            return {"stdout": [], "stderr": "", "output": {"path": "", "dataType": "str"}}

    monkeypatch.setattr(
        node_exec, "sandbox_request", lambda method, path, **kw: sent.append(json.loads(kw["data"])) or Reply()
    )
    return sent


def _run_loader(client, token):
    return client.post("/processPythonCode", headers={"Authorization": f"Bearer {token}"}, json={
        "code": f'model = curio_load_model("{MODEL_ID}")\nreturn 1',
        "nodeType": "COMPUTATION_ANALYSIS",
        "input": "",
    })


def _key(user) -> str:
    from utk_curio.backend.app.projects.services import _user_dir_key

    return _user_dir_key(user)


@pytest.fixture()
def catalog(tmp_curio, monkeypatch):
    """A package catalog holding Local Relief, as ``packages/`` would."""
    root = tmp_curio / "catalog"
    shutil.copytree(LOCAL_RELIEF, root / DIR)
    monkeypatch.setenv("CURIO_PACKAGES_ROOT", str(root))
    return root


@pytest.fixture()
def pip_catalog(tmp_curio, monkeypatch):
    """The same catalog as a pip install would have it, had Local Relief
    shipped in ``packages/`` with its weight left out of the pip package: the
    folder without the weight, the list naming it, and the release's record."""
    from utk_curio.backend.app.datasets.infrastructure import left_out_files

    root = tmp_curio / "site-packages" / "packages"
    shutil.copytree(LOCAL_RELIEF, root / DIR, ignore=shutil.ignore_patterns("local_relief.onnx"))
    listing = tmp_curio / "left_out_files.json"
    listing.write_text(json.dumps({"files": [WEIGHT_REPO_PATH]}), encoding="utf-8")
    monkeypatch.setattr(left_out_files, "LIST_PATH", listing)
    monkeypatch.setattr(left_out_files, "RECORD_PATH", write_record(
        tmp_curio / "record.json", [WEIGHT_REPO_PATH], contents={WEIGHT_REPO_PATH: _weight()},
    ))
    monkeypatch.setenv("CURIO_PACKAGES_ROOT", str(root))
    assert not (root / DIR / WEIGHT).exists()
    return root


# ---------------------------------------------------------------------------
# The manifest
# ---------------------------------------------------------------------------

class TestTheModelBlock:
    def test_local_relief_validates_and_says_how_to_run_its_weights(self):
        """The shipped example: one MIT model package, its node, its module and
        its weight, validated by the schema and by the parser."""
        from utk_curio.backend.app.packages.repositories.archive import _build_integrity
        from utk_curio.backend.app.packages.repositories.manifests import load_package_manifest

        raw = json.loads((LOCAL_RELIEF / "manifest.json").read_text(encoding="utf-8"))
        errors = [f"{list(e.absolute_path)}: {e.message}" for e in _validator().iter_errors(raw)]
        assert not errors, errors

        manifest = load_package_manifest(LOCAL_RELIEF)
        assert (manifest.package_id, manifest.kind, manifest.license) == (MODEL_ID, "model", "MIT")
        model = manifest.model
        assert (model.type, model.runtime, model.entry, model.labels) == ("image-to-image", "onnx", WEIGHT, ())
        assert (model.input.width, model.input.height, model.input.dtype, model.input.layout) == (
            64, 64, "float32", "NCHW")
        assert model.license == "MIT" and model.publisher == "Curio"
        assert model.size_bytes == (LOCAL_RELIEF / WEIGHT).stat().st_size == 2394
        assert [t.template_id for t in manifest.templates] == ["local-relief"]
        assert manifest.templates[0].source == "sources/local-relief.py"
        for rel in ("sources/local-relief.py", "sources/local_relief/__init__.py", "sources/local_relief/run.py"):
            assert (LOCAL_RELIEF / rel).is_file(), rel
        # It needs only its runtime: rasterio comes with Curio's own nodes.
        assert manifest.python_deps == {"onnxruntime": ">=1.17"}
        # Its integrity.json names every file, the weight among them.
        integrity = json.loads((LOCAL_RELIEF / "integrity.json").read_text(encoding="utf-8"))["sha256"]
        assert integrity == _build_integrity(LOCAL_RELIEF) and WEIGHT in integrity
        # The script that exports the weight sits beside the package.
        assert "model.example.local-relief@1\" / \"models\" / \"local_relief.onnx\"" in (
            GUIDE / "export_local_relief.py").read_text(encoding="utf-8")

    def test_a_model_block_with_widgets_validates(self):
        manifest = _parse(_model_manifest())
        assert manifest.kind == "model"
        assert manifest.model.labels == ("a", "b") and manifest.model.entry == "models/m.onnx"
        assert manifest.templates[0].widgets[0]["name"] == "season"
        assert not list(_validator().iter_errors(_model_manifest()))
        # The schema holds a model block to its kind, as the parser does.
        without_block = {key: value for key, value in _model_manifest().items() if key != "model"}
        assert list(_validator().iter_errors(without_block))
        assert list(_validator().iter_errors(_model_manifest(kind="node")))
        assert list(_validator().iter_errors(_model_manifest(model={"entry": "files/m.onnx"})))

    @pytest.mark.parametrize("model, message", [
        ({"runtime": "tflite"}, "runtime must be one of"),
        ({"type": "detection"}, "type must be one of"),
        ({"entry": "../m.onnx"}, "under models/"),
        ({"entry": "/abs/m.onnx"}, "under models/"),
        ({"entry": "files/m.onnx"}, "under models/"),
        ({"entry": "models/../m.onnx"}, "under models/"),
        ({"entry": "models/m.bin"}, "entry is its .onnx file"),
        ({"labels": []}, "names its labels"),
        ({"license": ""}, "license must be"),
        ({"input": {"width": 64, "height": 32, "dtype": "int64"}}, "input.dtype"),
        ({"input": {"width": 64, "height": 32, "std": [1, 0, 1]}}, "zero"),
        ({"homepage": "http://x.example"}, "https"),
        ({"input": {"width": 64, "height": 32, "layout": "CHW"}}, "input.layout must be one of"),
        ({"input": {"width": 64, "height": 32, "layout": "NHWC"}}, "NCHW for this type"),
        ({"sizeBytes": -1}, "sizeBytes"),
    ])
    def test_what_the_model_block_refuses(self, model, message):
        from utk_curio.backend.app.packages.domain.manifest import ManifestError

        with pytest.raises(ManifestError, match=message):
            _parse(_model_manifest(model=model))

    @pytest.mark.parametrize("raw, message", [
        ({key: value for key, value in _model_manifest().items() if key != "model"}, "declares its model"),
        (_model_manifest(kind="node"), "only a model package"),
        (_model_manifest(kind="widget"), "kind must be"),
    ])
    def test_a_model_block_belongs_to_a_model_package(self, raw, message):
        from utk_curio.backend.app.packages.domain.manifest import ManifestError

        with pytest.raises(ManifestError, match=message):
            _parse(raw)

    def test_the_other_types_and_runtimes_read(self):
        image = _parse(_model_manifest(model={
            "type": "image-to-image", "labels": [],
            "input": {"width": 512, "height": 512, "dtype": "float32", "layout": "NHWC"},
        }))
        assert image.model.labels == () and image.model.input.layout == "NHWC"
        graph = _parse(_model_manifest(model={"type": "node-regression", "labels": [], "input": None}))
        assert graph.model.input is None
        checkpoint = _parse(_model_manifest(model={
            "runtime": "transformers", "entry": "models/checkpoint", "labels": [], "input": None,
        }))
        assert checkpoint.model.entry == "models/checkpoint"

    def test_a_package_without_a_kind_is_a_node_package(self, manifest_dict):
        manifest = _parse(manifest_dict(package_id="ai.test.demo"), dir_name="ai.test.demo@1")
        assert manifest.kind == "node" and manifest.model is None


# ---------------------------------------------------------------------------
# The listings
# ---------------------------------------------------------------------------

def test_the_listings_carry_kind_and_model_and_filter_by_kind(client, user_and_token, catalog, make_archive, manifest_dict):
    from utk_curio.backend.app.packages.application.store_install import (
        install_package_from_archive,
        install_package_from_directory,
    )

    user, token = user_and_token
    headers = {"Authorization": f"Bearer {token}"}
    key = _key(user)
    install_package_from_directory(key, catalog / DIR)
    install_package_from_archive(key, make_archive())
    node_dir = catalog / "ai.test.node@1"
    node_dir.mkdir()
    (node_dir / "manifest.json").write_text(json.dumps(manifest_dict(package_id="ai.test.node")), encoding="utf-8")

    for route, node in (("/api/packages", "ai.test.demo@1"), ("/api/packages/catalog", "ai.test.node@1")):
        reply = client.get(route, headers=headers)
        assert reply.status_code == 200, reply.get_data(as_text=True)
        every = {p["dirName"]: p for p in reply.get_json()["packages"]}
        assert every[DIR]["kind"] == "model", route
        assert {
            "type": "image-to-image", "runtime": "onnx", "entry": WEIGHT, "license": "MIT",
            "publisher": "Curio", "sizeBytes": 2394, "labels": [],
        }.items() <= every[DIR]["model"].items(), route
        assert every[DIR]["model"]["input"]["width"] == 64
        assert every[node]["kind"] == "node" and every[node].get("model") is None, route

        models = [p["dirName"] for p in client.get(f"{route}?kind=model", headers=headers).get_json()["packages"]]
        assert models == [DIR], route
        nodes = [p["dirName"] for p in client.get(f"{route}?kind=node", headers=headers).get_json()["packages"]]
        assert node in nodes and DIR not in nodes, route
        refused = client.get(f"{route}?kind=widget", headers=headers)
        assert refused.status_code == 400 and "kind" in refused.get_json()["error"], route


# ---------------------------------------------------------------------------
# The archive
# ---------------------------------------------------------------------------

def test_a_model_file_at_the_cap_streams_through_import_export_and_publish(tmp_curio, monkeypatch):
    """Sizes patched: a weight exactly at the model cap goes in from a
    ``.curio.zip`` on disk, out as one, and into the shared catalog, and
    Python never holds more than a few MiB of it at once."""
    from utk_curio.backend.app.packages.application import publishing, store_install
    from utk_curio.backend.app.packages.repositories import archive
    from utk_curio.backend.app.packages.repositories.store import package_dir

    cap = 24 * MIB
    monkeypatch.setattr(archive, "_MAX_MODEL_FILE_BYTES", cap)
    monkeypatch.setenv("CURIO_PACKAGES_ROOT", str(tmp_curio / "catalog"))
    source = _big_model_package(tmp_curio / "authored", cap)
    zipped = archive.zip_package_tree_to(source, tmp_curio / "big.curio.zip")

    def install():
        with open(zipped, "rb") as stream:
            return store_install.install_package_from_archive("guest", stream)

    result, peak = _peak(install)
    assert result.manifest.kind == "model"
    assert peak < cap / 4, f"the import held {peak:,} bytes"
    store = package_dir("guest", "ai.test.big-model@1")
    assert (store / "models" / "w.onnx").stat().st_size == cap

    exported, peak = _peak(lambda: store_install.export_package_archive_to(
        "guest", "ai.test.big-model@1", tmp_curio / "exported.curio.zip",
    ))
    assert peak < cap / 4, f"the export held {peak:,} bytes"
    with zipfile.ZipFile(exported) as zf:
        assert zf.getinfo("models/w.onnx").file_size == cap

    (_published, catalog_path), peak = _peak(lambda: publishing.publish_installed_to_catalog(
        "guest", "ai.test.big-model@1", replace=False,
    ))
    assert peak < cap / 4, f"the publish held {peak:,} bytes"
    assert (catalog_path / "models" / "w.onnx").stat().st_size == cap


def test_a_model_file_over_the_cap_is_refused_and_node_packages_keep_their_caps(tmp_curio, monkeypatch, manifest_dict):
    from utk_curio.backend.app.packages.application.store_install import install_package_from_archive
    from utk_curio.backend.app.packages.repositories import archive
    from utk_curio.backend.app.packages.repositories.archive import InstallerError

    monkeypatch.setattr(archive, "_MAX_MODEL_FILE_BYTES", 4 * MIB)
    monkeypatch.setattr(archive, "_MAX_FILE_BYTES", MIB)
    monkeypatch.setattr(archive, "_MAX_TOTAL_BYTES", 2 * MIB)

    def install(folder):
        zipped = archive.zip_package_tree_to(folder, folder.parent / f"{folder.name}.curio.zip")
        with open(zipped, "rb") as stream:
            return install_package_from_archive("guest", stream)

    with pytest.raises(InstallerError, match="exceeds per-file"):
        install(_big_model_package(tmp_curio / "over", 4 * MIB + 1))
    assert install(_big_model_package(tmp_curio / "at", 4 * MIB, package_id="ai.test.fits")).manifest.kind == "model"

    node = tmp_curio / "node" / "ai.test.big-node@1"
    _write_random(node / "sources" / "blob.bin", 2 * MIB)
    (node / "manifest.json").write_text(json.dumps(manifest_dict(package_id="ai.test.big-node")), encoding="utf-8")
    with pytest.raises(InstallerError, match="exceeds per-file"):
        install(node)


def test_an_imported_model_package_keeps_its_weights(tmp_curio):
    from utk_curio.backend.app.packages.application.store_install import install_package_from_archive
    from utk_curio.backend.app.packages.repositories.archive import zip_package_tree
    from utk_curio.backend.app.packages.repositories.store import package_dir

    result = install_package_from_archive("guest", zip_package_tree(LOCAL_RELIEF))

    assert result.manifest.kind == "model" and WEIGHT in result.integrity
    assert (package_dir("guest", DIR) / WEIGHT).read_bytes() == _weight()


# ---------------------------------------------------------------------------
# A user's copy of a shipped model package
# ---------------------------------------------------------------------------

def _store_map(store: Path) -> dict:
    return json.loads((store / "integrity.json").read_text(encoding="utf-8"))["sha256"]


def test_a_users_copy_holds_no_models(catalog):
    """Added from the catalog, or refreshed by a seeding pass after the catalog
    moved on: the copy has the manifest and the code, not the weights, and its
    integrity.json describes the copy, so the next pass leaves it alone."""
    from utk_curio.backend.app.packages.application import seeding
    from utk_curio.backend.app.packages.application.store_install import install_package_from_directory
    from utk_curio.backend.app.packages.repositories.archive import _build_integrity, refresh_package_integrity
    from utk_curio.backend.app.packages.repositories.store import package_dir

    install_package_from_directory("guest", catalog / DIR)
    store = package_dir("guest", DIR)
    for rel in ("manifest.json", "sources/local-relief.py", "sources/local_relief/run.py"):
        assert (store / rel).is_file(), rel
    assert not (store / "models").exists()
    assert _store_map(store) == _build_integrity(store)
    assert not [rel for rel in _store_map(store) if rel.startswith("models/")]
    assert seeding.seed_dev_packages(user_key="guest") == []

    run_py = catalog / DIR / "sources" / "local_relief" / "run.py"
    run_py.write_text(run_py.read_text(encoding="utf-8") + "\n# upgraded\n", encoding="utf-8")
    later = run_py.stat().st_mtime + 10
    os.utime(run_py, (later, later))
    refresh_package_integrity(catalog / DIR)

    assert seeding.seed_dev_packages(user_key="guest") == [DIR]
    assert "# upgraded" in (store / "sources" / "local_relief" / "run.py").read_text(encoding="utf-8")
    assert not (store / "models").exists()
    assert _store_map(store) == _build_integrity(store)
    assert seeding._package_is_healthy(store)
    assert seeding.seed_dev_packages(user_key="guest") == []


# ---------------------------------------------------------------------------
# A weight the pip package leaves out
# ---------------------------------------------------------------------------

def test_an_unfetched_weight_is_neither_unhealthy_nor_stale(pip_catalog, monkeypatch):
    from utk_curio.backend.app.packages.application import seeding
    from utk_curio.backend.app.packages.application.store_install import install_package_from_directory
    from utk_curio.backend.app.packages.repositories.store import package_dir

    github = FakeGitHub(fail=AssertionError("a weight was downloaded before a node ran it")).serve(monkeypatch)
    shipped = pip_catalog / DIR
    assert WEIGHT in _store_map(shipped)

    assert seeding._package_is_healthy(shipped)
    install_package_from_directory("guest", shipped)
    store = package_dir("guest", DIR)
    assert seeding._package_is_healthy(store)
    assert seeding.seed_dev_packages(user_key="guest") == []
    assert github.urls == []


def test_a_node_fetches_a_left_out_weight_once_and_loads_it(client, user_and_token, pip_catalog, monkeypatch):
    from utk_curio.backend.app.datasets.infrastructure import left_out_files
    from utk_curio.backend.app.packages.application.store_install import install_package_from_directory

    user, token = user_and_token
    install_package_from_directory(_key(user), pip_catalog / DIR)
    github = FakeGitHub(contents={WEIGHT_REPO_PATH: _weight()}).serve(monkeypatch)
    sent = _capture_sandbox(monkeypatch)

    for _ in range(2):
        reply = _run_loader(client, token)
        assert reply.status_code == 200, reply.get_data(as_text=True)

    assert len(sent) == 2
    folder = Path(sent[0]["models"][MODEL_ID])
    assert sent[1]["models"][MODEL_ID] == str(folder)
    assert folder == left_out_files.fetched_root(COMMIT) / "packages" / DIR
    assert (folder / WEIGHT).read_bytes() == _weight()
    assert (folder / "manifest.json").read_bytes() == (LOCAL_RELIEF / "manifest.json").read_bytes()
    assert github.urls == [url_of(WEIGHT_REPO_PATH)]


def test_a_fetched_weight_that_does_not_match_integrity_is_refused(client, user_and_token, pip_catalog, monkeypatch):
    """The release's record and GitHub agree, the package's integrity.json does
    not: nothing is placed, and the node fails saying so without running."""
    from utk_curio.backend.app.datasets.infrastructure import left_out_files
    from utk_curio.backend.app.packages.application.store_install import install_package_from_directory

    user, token = user_and_token
    install_package_from_directory(_key(user), pip_catalog / DIR)
    integrity_path = pip_catalog / DIR / "integrity.json"
    integrity = json.loads(integrity_path.read_text(encoding="utf-8"))
    integrity["sha256"][WEIGHT] = "0" * 64
    integrity_path.write_text(json.dumps(integrity), encoding="utf-8")
    FakeGitHub(contents={WEIGHT_REPO_PATH: _weight()}).serve(monkeypatch)
    sent = _capture_sandbox(monkeypatch)

    reply = _run_loader(client, token)

    assert reply.status_code == 200, reply.get_data(as_text=True)
    stderr = reply.get_json()["stderr"]
    assert WEIGHT_REPO_PATH in stderr and "integrity.json" in stderr, stderr
    assert sent == []
    assert not (left_out_files.fetched_root(COMMIT) / WEIGHT_REPO_PATH).exists()


def test_export_fetches_the_weight_first(pip_catalog, monkeypatch):
    """A user's copy holds no weights, and a pip install has not fetched them
    yet: the export fetches them, and the archive installs, weights and all,
    in another account."""
    from utk_curio.backend.app.packages.application.store_install import (
        export_package_archive,
        install_package_from_archive,
        install_package_from_directory,
    )
    from utk_curio.backend.app.packages.repositories.store import package_dir

    install_package_from_directory("guest", pip_catalog / DIR)
    github = FakeGitHub(contents={WEIGHT_REPO_PATH: _weight()}).serve(monkeypatch)

    archive = export_package_archive("guest", DIR)

    assert github.urls == [url_of(WEIGHT_REPO_PATH)]
    with zipfile.ZipFile(io.BytesIO(archive)) as zf:
        assert zf.read(WEIGHT) == _weight()
        assert "sources/local_relief/run.py" in zf.namelist()
    install_package_from_archive("7", archive)
    assert (package_dir("7", DIR) / WEIGHT).read_bytes() == _weight()


# ---------------------------------------------------------------------------
# curio_load_model
# ---------------------------------------------------------------------------

def test_a_node_loads_a_shipped_packages_weights_where_they_ship(client, user_and_token, catalog, monkeypatch):
    from utk_curio.backend.app.packages.application.store_install import install_package_from_directory
    from utk_curio.backend.app.packages.repositories.store import package_dir

    user, token = user_and_token
    install_package_from_directory(_key(user), catalog / DIR)
    sent = _capture_sandbox(monkeypatch)

    reply = _run_loader(client, token)

    assert reply.status_code == 200, reply.get_data(as_text=True)
    assert sent[0]["models"] == {MODEL_ID: str((catalog / DIR).resolve())}
    assert not (package_dir(_key(user), DIR) / "models").exists()


def test_a_node_loads_an_imported_packages_weights_from_the_users_store(client, user_and_token, monkeypatch, tmp_curio):
    from utk_curio.backend.app.packages.application.store_install import install_package_from_archive
    from utk_curio.backend.app.packages.repositories.archive import zip_package_tree
    from utk_curio.backend.app.packages.repositories.store import package_dir

    monkeypatch.setenv("CURIO_PACKAGES_ROOT", str(tmp_curio / "empty-catalog"))
    user, token = user_and_token
    install_package_from_archive(_key(user), zip_package_tree(LOCAL_RELIEF))
    sent = _capture_sandbox(monkeypatch)

    reply = _run_loader(client, token)

    assert reply.status_code == 200, reply.get_data(as_text=True)
    folder = Path(sent[0]["models"][MODEL_ID])
    assert folder == package_dir(_key(user), DIR)
    assert (folder / WEIGHT).read_bytes() == _weight()


# ---------------------------------------------------------------------------
# Models behave like nodes: only a model in the user's store runs
# ---------------------------------------------------------------------------

def test_a_model_never_added_resolves_to_no_folder(catalog):
    """A model package the catalog ships but the account never added (nor was
    seeded with) gives a node no folder, as an id that names no model package
    does; and no account resolves any model."""
    from utk_curio.backend.app.packages.service import resolve_model_dirs

    assert resolve_model_dirs("guest", [MODEL_ID, f"{MODEL_ID}@1", "model.example.none"]) == {}
    assert resolve_model_dirs(None, [MODEL_ID]) == {}


def test_an_added_model_resolves_by_its_id_and_its_major_for_its_account_only(catalog):
    """Added, its copy holds no weights, so its id and its id with its major
    resolve to the catalog's copy; another major and an id that names no model
    package do not, and another account, which has not added it, gets none."""
    from utk_curio.backend.app.packages.application.store_install import install_package_from_directory
    from utk_curio.backend.app.packages.service import resolve_model_dirs

    install_package_from_directory("guest", catalog / DIR)

    assert resolve_model_dirs("guest", [MODEL_ID, f"{MODEL_ID}@1", f"{MODEL_ID}@2", "model.example.none"]) == {
        MODEL_ID: str((catalog / DIR).resolve()),
        f"{MODEL_ID}@1": str((catalog / DIR).resolve()),
    }
    assert resolve_model_dirs("7", [MODEL_ID]) == {}


def test_a_node_whose_model_was_never_added_is_given_none(client, user_and_token, catalog, monkeypatch):
    """The run sends the sandbox no folder for a model the account never added,
    so ``curio_load_model`` says to add it; once added, the same run sends the
    weights where they ship."""
    from utk_curio.backend.app.packages.application.store_install import install_package_from_directory

    user, token = user_and_token
    sent = _capture_sandbox(monkeypatch)

    assert _run_loader(client, token).status_code == 200
    assert MODEL_ID not in (sent[-1].get("models") or {})

    install_package_from_directory(_key(user), catalog / DIR)
    assert _run_loader(client, token).status_code == 200
    assert sent[-1]["models"] == {MODEL_ID: str((catalog / DIR).resolve())}


# ---------------------------------------------------------------------------
# Where Local Relief ships
# ---------------------------------------------------------------------------

def test_the_wheel_leaves_local_relief_out(monkeypatch):
    """``MANIFEST.in``, applied as setuptools applies it, ships no file of the
    guide's folder; the Docker image copies it (the next test). setuptools
    first adds every Python module of the folders it packages, ``docs/``
    among them, so the export script must be taken out again, not only left
    out of the includes."""
    from setuptools._distutils.filelist import FileList

    monkeypatch.chdir(REPO)
    files = sorted(path.relative_to(REPO).as_posix() for path in GUIDE.rglob("*") if path.is_file())
    assert f"docs/bring-your-own-model/{DIR}/{WEIGHT}" in files
    assert "docs/bring-your-own-model/export_local_relief.py" in files
    listed = FileList()
    listed.set_allfiles(files)
    listed.files = [path for path in files if path.endswith(".py")]
    for line in (REPO / "MANIFEST.in").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            listed.process_template_line(line)
    assert listed.files == []


def test_the_image_copies_local_relief():
    from utk_curio.backend.tests.test_discovery.test_shipped_sources import _packaging_file

    assert "COPY docs/bring-your-own-model/ docs/bring-your-own-model/" in _packaging_file("Dockerfile")
