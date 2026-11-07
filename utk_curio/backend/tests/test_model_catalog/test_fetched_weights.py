"""Model packages whose operator fetches their weights: the ``fetch`` block.

A model package can ship without its weights and name them in its model
block's ``fetch``: files of a Hugging Face repository at one commit, each with
its digest (``packages/domain/model_fetch.py``). ``scripts/fetch_model_weights.py``
puts them in the package's entry folder, or under the folder
``curio.py start --model-weights-dir`` names, where Curio reads them in place.

- The ``concept-segmentation`` type and the ``fetch`` block, as the schema and
  the parser read them, and what each refuses.
- Where a run reads the weights: the package's own folder, or the flag's
  folder, which the sandbox gets apart from the model's and reads in place.
- Without them the model still resolves, so its node says how to fetch them,
  and the Model Catalog's listing says they are not fetched.
- Integrity, ``scripts/regen_integrity.py`` among it, leaves them out.
- Export, Publish and Save as package node refuse the package, saying why.
- No shipped package keeps a folder under ``models/`` but a fetched entry,
  which ``.gitignore``, ``.dockerignore`` and ``MANIFEST.in`` leave out.

The package is made in each test's own folder, never in ``packages/``. No test
opens a socket (``test_scripts/test_fetch_model_weights.py`` covers the fetch
itself). The code under test is imported inside each test.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
SCHEMA = REPO / "docs" / "schemas" / "node-package.v4.json"
PACKAGE_ID = "model.test.prompted"
DIR = f"{PACKAGE_ID}@1"
NAME = "Prompted segmenter"
ENTRY = "models/checkpoint"
REVISION = "3c879f39826c281e95690f02c7821c4de09afae7"
CONFIG = b'{"model_type": "tiny"}'
WEIGHTS = bytes(range(256)) * 16


def _git_blob_sha1(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data, usedforsecurity=False).hexdigest()


FETCH = {
    "huggingface": "acme/tiny-prompted",
    "revision": REVISION,
    "files": [
        {"path": "config.json", "gitSha1": _git_blob_sha1(CONFIG)},
        {"path": "model.safetensors", "sha256": hashlib.sha256(WEIGHTS).hexdigest()},
    ],
}


def _block(**change) -> dict:
    """The test package's model block; a None in *change* removes a key."""
    block = {
        "type": "concept-segmentation", "runtime": "transformers", "entry": ENTRY,
        "labels": ["person", "bicycle"], "license": "Acme's terms", "publisher": "Acme",
        "sizeBytes": len(CONFIG) + len(WEIGHTS), "fetch": FETCH,
    }
    for key, value in change.items():
        if value is None:
            block.pop(key, None)
        else:
            block[key] = value
    return block


def _manifest(**top) -> dict:
    raw = {
        "id": PACKAGE_ID, "version": "1.0.0", "name": NAME, "publisher": "Test", "license": "MIT",
        "compatibility": {"major": 1}, "kind": "model",
        "templates": [{"id": "find", "label": "Find", "category": "computation", "engine": "python",
                       "editor": "code", "inputPorts": [], "outputPorts": [{"types": ["DATAFRAME"]}]}],
        "model": _block(),
    }
    raw.update(top)
    return raw


def _parse(raw: dict):
    from utk_curio.backend.app.packages.domain.manifest import package_manifest_from_dict

    return package_manifest_from_dict(raw, manifest_path=Path("manifest.json"), dir_name=DIR)


def _validator():
    from jsonschema import Draft202012Validator

    return Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8")))


def _write_package(folder: Path, manifest: dict | None = None) -> Path:
    from utk_curio.backend.app.packages.repositories.archive import refresh_package_integrity

    folder.mkdir(parents=True, exist_ok=True)
    (folder / "manifest.json").write_text(json.dumps(manifest or _manifest()), encoding="utf-8")
    refresh_package_integrity(folder)
    return folder


def _fetch_into(root: Path, *names: str) -> Path:
    """The weights under *root* as ``scripts/fetch_model_weights.py`` leaves
    them: every file, or those *names* gives."""
    entry = root / ENTRY
    entry.mkdir(parents=True, exist_ok=True)
    for name, data in (("config.json", CONFIG), ("model.safetensors", WEIGHTS)):
        if not names or name in names:
            (entry / name).write_bytes(data)
    return root


def _add(user_key: str, catalog: Path) -> Path:
    """The catalog's package added to *user_key*'s store, as Add adds it."""
    from utk_curio.backend.app.packages.application.store_install import install_package_from_directory
    from utk_curio.backend.app.packages.repositories.store import package_dir

    install_package_from_directory(user_key, catalog / DIR)
    return package_dir(user_key, DIR)


def _key(user) -> str:
    from utk_curio.backend.app.projects.services import _user_dir_key

    return _user_dir_key(user)


@pytest.fixture()
def catalog(tmp_curio, monkeypatch):
    """A package catalog holding the test package without its weights, and
    no ``--model-weights-dir``."""
    root = tmp_curio / "catalog"
    _write_package(root / DIR)
    monkeypatch.setenv("CURIO_PACKAGES_ROOT", str(root))
    monkeypatch.delenv("CURIO_MODEL_WEIGHTS_DIR", raising=False)
    return root


@pytest.fixture()
def weights_dir(tmp_curio, monkeypatch):
    """The folder ``--model-weights-dir`` names (``CURIO_MODEL_WEIGHTS_DIR``)."""
    folder = tmp_curio / "model-weights"
    folder.mkdir()
    monkeypatch.setenv("CURIO_MODEL_WEIGHTS_DIR", str(folder))
    return folder


# ---------------------------------------------------------------------------
# The manifest
# ---------------------------------------------------------------------------

def test_a_concept_segmentation_model_with_a_fetch_block_reads_and_round_trips():
    """Its labels are its prompts, and its fetch block names each file with
    its digest; a listing's block reads back as the manifest's, and the
    schema takes the manifest."""
    from utk_curio.backend.app.packages.domain.model_block import model_block_dict, parse_model_block

    block = _parse(_manifest()).model
    assert (block.type, block.runtime, block.entry, block.labels) == (
        "concept-segmentation", "transformers", ENTRY, ("person", "bicycle"))
    assert (block.fetch.huggingface, block.fetch.revision) == ("acme/tiny-prompted", REVISION)
    assert [(item.path, item.sha256, item.git_sha1) for item in block.fetch.files] == [
        ("config.json", None, _git_blob_sha1(CONFIG)),
        ("model.safetensors", hashlib.sha256(WEIGHTS).hexdigest(), None),
    ]
    assert model_block_dict(block)["fetch"] == FETCH
    assert parse_model_block(model_block_dict(block)) == block
    assert list(_validator().iter_errors(_manifest())) == []


def test_the_schema_and_the_parser_name_the_same_model_types():
    from utk_curio.backend.app.packages.domain.model_block import TYPES

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    assert schema["$defs"]["model"]["properties"]["type"]["enum"] == list(TYPES)
    assert "concept-segmentation" in TYPES


def _files(*files) -> dict:
    return {"fetch": {**FETCH, "files": list(files)}}


#: (change to the model block, what the parser says, whether the schema
#: refuses it too).
REFUSED = [
    pytest.param({"fetch": {**FETCH, "revision": "main"}}, "revision must be a full commit hash", True,
                 id="a branch, not a commit"),
    pytest.param({"fetch": {**FETCH, "revision": REVISION[:12]}}, "revision must be a full commit hash", True,
                 id="a short hash"),
    pytest.param({"fetch": {**FETCH, "revision": REVISION.upper()}}, "revision must be a full commit hash", True,
                 id="an upper case hash"),
    pytest.param(_files({"path": "../config.json", "gitSha1": "a" * 40}), "with no '..'", True, id="a path out"),
    pytest.param(_files({"path": "/etc/passwd", "gitSha1": "a" * 40}), "is relative", True, id="an absolute path"),
    pytest.param(_files({"path": "a\\b.json", "gitSha1": "a" * 40}), "is relative", True, id="a backslash"),
    pytest.param(_files({"path": ".git/config", "gitSha1": "a" * 40}), "starts with a dot", True, id="a dot part"),
    pytest.param(_files({"path": "x.bin", "sha256": "a" * 64, "gitSha1": "a" * 40}), "names one digest", True,
                 id="two digests"),
    pytest.param(_files({"path": "x.bin"}), "names one digest", True, id="no digest"),
    pytest.param(_files({"path": "x.bin", "sha256": "a" * 63}), "sha256 is 64", True, id="a short sha256"),
    pytest.param(_files({"path": "x.bin", "gitSha1": "g" * 40}), "gitSha1 is 40", True, id="a gitSha1 not hex"),
    pytest.param(_files(), "files must list", True, id="no file"),
    pytest.param(_files(FETCH["files"][0], FETCH["files"][0]), "lists a path twice", False, id="a path twice"),
    pytest.param(_files({"path": "a", "gitSha1": "a" * 40}, {"path": "a/b", "gitSha1": "b" * 40}),
                 "as a file and as the folder", False, id="a file and its folder"),
    pytest.param({"fetch": {**FETCH, "huggingface": "acme"}}, "<owner>/<name>", True, id="no owner"),
    pytest.param({"fetch": {**FETCH, "huggingface": "acme/../x"}}, "<owner>/<name>", True, id="a path for a repo"),
    pytest.param({"fetch": {**FETCH, "mirror": "https://example.test"}}, "must be an object of", True,
                 id="a key it does not know"),
    pytest.param({"entry": "models/a/checkpoint"}, "a folder directly under models/", True, id="a deeper entry"),
    pytest.param({"runtime": "onnx", "entry": "models/m.onnx"}, "runtime is transformers", True,
                 id="an onnx model"),
]


@pytest.mark.parametrize("change, message, schema_refuses", REFUSED)
def test_a_fetch_block_that_cannot_be_read_is_refused(change, message, schema_refuses):
    """The parser refuses each, saying what is wrong; the schema refuses each
    it can express."""
    from utk_curio.backend.app.packages.domain.manifest import ManifestError

    with pytest.raises(ManifestError, match=r"\.model: fetch: .*" + re.escape(message)):
        _parse(_manifest(model=_block(**change)))
    if schema_refuses:
        assert list(_validator().iter_errors(_manifest(model=_block(**change)))), change


def test_a_package_whose_weights_are_fetched_names_none_to_download_on_first_use():
    from utk_curio.backend.app.packages.domain.manifest import ManifestError

    with pytest.raises(ManifestError, match="names none to download on first use"):
        _parse(_manifest(downloadOnFirstUse=[ENTRY]))


def test_its_node_opens_on_its_model_and_its_prompts_not_on_a_graph_skeleton(catalog):
    """A template with no source of its own: the model loaded by its id, its
    prompts and where its checkpoint is, never ONNX's model.run."""
    from utk_curio.backend.app.packages.application.model_packages import model_default_cell
    from utk_curio.backend.app.packages.repositories.manifests import load_package_manifest

    cell = model_default_cell(load_package_manifest(catalog / DIR), catalog / DIR)
    assert cell.startswith(f'model = curio_load_model("{PACKAGE_ID}")\n'), cell
    assert "model.labels" in cell and "model.path" in cell, cell
    assert "model.run" not in cell, cell


# ---------------------------------------------------------------------------
# Where a run reads the weights
# ---------------------------------------------------------------------------

def test_without_its_weights_the_model_still_resolves_so_its_node_says_how_to_fetch_them(catalog):
    """Added, its copy holds no weights, nor does the catalog: the run still
    gets the catalog's folder, whose manifest says what to fetch, and the
    sandbox's curio_load_model says how. An account that never added it gets
    none, as for every model."""
    from utk_curio.backend.app.packages.application.model_packages import weights_not_fetched
    from utk_curio.backend.app.packages.repositories.manifests import load_package_manifest
    from utk_curio.backend.app.packages.service import resolve_model_dirs, resolve_model_weights

    copy = _add("guest", catalog)

    assert not (copy / "models").exists()
    assert resolve_model_dirs("guest", [PACKAGE_ID]) == {PACKAGE_ID: str((catalog / DIR).resolve())}
    assert resolve_model_weights("guest", [PACKAGE_ID]) == {}
    assert weights_not_fetched(load_package_manifest(copy), copy)
    assert resolve_model_dirs("7", [PACKAGE_ID]) == {}


def test_weights_fetched_into_the_package_are_read_there(catalog):
    from utk_curio.backend.app.packages.application.model_packages import weights_not_fetched
    from utk_curio.backend.app.packages.repositories.manifests import load_package_manifest
    from utk_curio.backend.app.packages.service import resolve_model_dirs, resolve_model_weights

    copy = _add("guest", catalog)
    _fetch_into(catalog / DIR)

    assert resolve_model_dirs("guest", [PACKAGE_ID]) == {PACKAGE_ID: str((catalog / DIR).resolve())}
    assert resolve_model_weights("guest", [PACKAGE_ID]) == {}
    assert not weights_not_fetched(load_package_manifest(copy), copy)
    assert not (copy / "models").exists()


def test_with_the_flag_the_weights_are_read_in_place_from_its_folder(catalog, weights_dir):
    """``<dir>/<package id>@<major>/<entry>``: the run gets the catalog's
    folder for the manifest and the flag's folder for the weights, and
    nothing is copied into the account's store."""
    from utk_curio.backend.app.packages.application.model_packages import weights_not_fetched
    from utk_curio.backend.app.packages.repositories.manifests import load_package_manifest
    from utk_curio.backend.app.packages.service import resolve_model_dirs, resolve_model_weights

    copy = _add("guest", catalog)
    root = _fetch_into(weights_dir / DIR)

    assert resolve_model_dirs("guest", [PACKAGE_ID, f"{PACKAGE_ID}@1"]) == {
        PACKAGE_ID: str((catalog / DIR).resolve()), f"{PACKAGE_ID}@1": str((catalog / DIR).resolve()),
    }
    assert resolve_model_weights("guest", [PACKAGE_ID]) == {PACKAGE_ID: str(root.resolve())}
    assert not weights_not_fetched(load_package_manifest(copy), copy)
    assert not (copy / "models").exists()


def test_with_the_flag_the_packages_own_folder_and_a_stopped_fetch_count_as_not_fetched(catalog, weights_dir):
    """The flag names the one place: weights left in the package's folder are
    not read, and a folder that lacks one listed file is not complete."""
    from utk_curio.backend.app.packages.application.model_packages import weights_not_fetched
    from utk_curio.backend.app.packages.repositories.manifests import load_package_manifest
    from utk_curio.backend.app.packages.service import resolve_model_weights

    copy = _add("guest", catalog)
    _fetch_into(catalog / DIR)
    _fetch_into(weights_dir / DIR, "config.json")
    manifest = load_package_manifest(copy)

    assert resolve_model_weights("guest", [PACKAGE_ID]) == {}
    assert weights_not_fetched(manifest, copy)
    assert weights_not_fetched(manifest, catalog / DIR)

    _fetch_into(weights_dir / DIR)
    assert not weights_not_fetched(manifest, copy)


def _capture_sandbox(monkeypatch) -> list:
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


def _play(client, token):
    return client.post("/processPythonCode", headers={"Authorization": f"Bearer {token}"}, json={
        "code": f'model = curio_load_model("{PACKAGE_ID}")\nreturn 1',
        "nodeType": "PYTHON_COMPUTATION",
        "input": "",
    })


def test_a_run_sends_the_weights_folder_beside_the_models_folder(client, user_and_token, catalog, weights_dir,
                                                                 monkeypatch):
    user, token = user_and_token
    _add(_key(user), catalog)
    root = _fetch_into(weights_dir / DIR)
    sent = _capture_sandbox(monkeypatch)

    reply = _play(client, token)

    assert reply.status_code == 200, reply.get_data(as_text=True)
    assert sent[0]["models"] == {PACKAGE_ID: str((catalog / DIR).resolve())}
    assert sent[0]["model_weights"] == {PACKAGE_ID: str(root.resolve())}


def test_a_run_without_the_flag_or_the_weights_sends_no_weights_folder(client, user_and_token, catalog, monkeypatch):
    user, token = user_and_token
    _add(_key(user), catalog)
    sent = _capture_sandbox(monkeypatch)

    reply = _play(client, token)

    assert reply.status_code == 200, reply.get_data(as_text=True)
    assert sent[0]["models"] == {PACKAGE_ID: str((catalog / DIR).resolve())}
    assert "model_weights" not in sent[0]


# ---------------------------------------------------------------------------
# The Model Catalog's listing
# ---------------------------------------------------------------------------

def _catalog_row(client, token) -> dict:
    resp = client.get("/api/packages/catalog?kind=model", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return {row["dirName"]: row for row in resp.get_json()["packages"]}[DIR]


def test_the_listing_says_the_weights_are_not_fetched_until_they_are(client, user_and_token, catalog):
    _user, token = user_and_token

    row = _catalog_row(client, token)
    assert (row["model"]["type"], row["model"]["fetch"]) == ("concept-segmentation", FETCH)
    assert row["model"]["weightsNotFetched"] is True
    assert row["model"]["downloadsOnFirstUse"] is False

    _fetch_into(catalog / DIR)
    assert _catalog_row(client, token)["model"]["weightsNotFetched"] is False


# ---------------------------------------------------------------------------
# Integrity
# ---------------------------------------------------------------------------

def _regen_integrity_script():
    spec = importlib.util.spec_from_file_location("_curio_regen_integrity", REPO / "scripts" / "regen_integrity.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_integrity_leaves_a_fetched_packages_weights_out(catalog, capsys):
    """``scripts/regen_integrity.py``, the installer's map and the check of a
    package against its map all leave the fetched entry folder out, while a
    package's other files under ``models/`` stay named."""
    from utk_curio.backend.app.packages.application import seeding
    from utk_curio.backend.app.packages.repositories.archive import _build_integrity, integrity_mismatch

    package = catalog / DIR
    (package / "models").mkdir()
    (package / "models" / "LICENSE.txt").write_text("Acme's terms.\n", encoding="utf-8")
    _fetch_into(package)

    assert _regen_integrity_script()._regen_one(package) == 0
    listed = json.loads((package / "integrity.json").read_text(encoding="utf-8"))["sha256"]
    assert sorted(listed) == ["manifest.json", "models/LICENSE.txt"], listed
    assert _build_integrity(package) == listed
    assert integrity_mismatch(package) is None
    assert seeding._package_is_healthy(package)
    capsys.readouterr()


# ---------------------------------------------------------------------------
# Export, Publish and Save as package node refuse it
# ---------------------------------------------------------------------------

def _refused(raised, refused: str) -> None:
    from utk_curio.backend.app.packages.domain.errors import PackageServiceError

    assert isinstance(raised.value, PackageServiceError) and raised.value.status == 409, raised.value
    message = str(raised.value)
    assert message.startswith(f"{refused}: its weights come from Acme under their terms"), message
    assert "2 GiB" in message and "scripts/fetch_model_weights.py" in message, message


def test_export_refuses_it_from_the_account_and_from_the_catalog_saying_why(catalog, tmp_curio):
    """Even with its weights at hand, in the catalog's folder: nothing is
    zipped."""
    from utk_curio.backend.app.packages.application.store_install import (
        archive_file_for_download,
        export_package_archive,
    )
    from utk_curio.backend.app.packages.domain.errors import PackageServiceError

    _fetch_into(catalog / DIR)
    _add("guest", catalog)

    with pytest.raises(PackageServiceError) as raised:
        export_package_archive("guest", DIR)
    _refused(raised, f"{NAME} cannot be exported")
    # The catalog page's Export of a row the account never added.
    with pytest.raises(PackageServiceError) as raised:
        archive_file_for_download("7", DIR)
    _refused(raised, f"{NAME} cannot be exported")


def test_export_through_the_route_answers_409_saying_why(client, user_and_token, catalog):
    user, token = user_and_token
    _add(_key(user), catalog)

    resp = client.get(f"/api/packages/{DIR}/archive", headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 409, resp.get_data(as_text=True)
    assert f"{NAME} cannot be exported" in resp.get_data(as_text=True)


def test_publish_refuses_it_saying_why(catalog):
    from utk_curio.backend.app.packages.application.publishing import publish_installed_to_catalog
    from utk_curio.backend.app.packages.domain.errors import PackageServiceError

    _add("guest", catalog)

    with pytest.raises(PackageServiceError) as raised:
        publish_installed_to_catalog("guest", DIR, replace=True)
    _refused(raised, f"{NAME} cannot be published")


def test_save_as_package_node_refuses_a_node_that_loads_it(catalog):
    """A node that loads it would make a model package of its own, copying
    its weights: refused, saying why."""
    from utk_curio.backend.app.packages.application.factory_install import model_source_for_draft
    from utk_curio.backend.app.packages.domain.errors import PackageServiceError

    _add("guest", catalog)
    _fetch_into(catalog / DIR)
    draft = {
        "manifest": {"id": "curio.canvas.draft.finder", "templates": [{"id": "finder"}]},
        "sources": {"finder": {"code": f'model = curio_load_model("{PACKAGE_ID}")\nreturn input_0'}},
    }

    with pytest.raises(PackageServiceError) as raised:
        model_source_for_draft("guest", draft, None)
    _refused(raised, f"A node that loads {NAME} cannot be saved as a package")


# ---------------------------------------------------------------------------
# What ships
# ---------------------------------------------------------------------------

def test_no_shipped_package_keeps_a_folder_under_models_but_a_fetched_entry():
    """``.gitignore``, ``.dockerignore`` and ``MANIFEST.in`` leave out every
    folder directly under a package's ``models/``, the entry a fetch fills.
    So weights that ship in git are files there, never a folder."""
    from utk_curio import shipped

    wrong = []
    for folder in sorted(shipped.path("packages").glob("*/models/*")):
        if not folder.is_dir():
            continue
        package = folder.parents[1]
        model = json.loads((package / "manifest.json").read_text(encoding="utf-8")).get("model") or {}
        if model.get("fetch") is None or model.get("entry") != f"models/{folder.name}":
            wrong.append(folder.relative_to(package.parent).as_posix())
    assert not wrong, wrong


def test_the_sdist_leaves_a_fetched_entry_out_and_keeps_shipped_weights(monkeypatch):
    """``MANIFEST.in``'s rules, applied as setuptools applies them: the files
    of a folder under ``models/`` stay out of the sdist, and so of the wheel,
    while a weight beside them and the package's manifest ship."""
    from setuptools._distutils.filelist import FileList

    monkeypatch.chdir(REPO)
    fetched = [f"packages/{DIR}/{ENTRY}/config.json", f"packages/{DIR}/{ENTRY}/model.safetensors"]
    kept = [f"packages/{DIR}/manifest.json", "packages/model.test.shipped@1/models/w.onnx"]
    files = FileList()
    files.set_allfiles(sorted(fetched + kept))
    for line in (REPO / "MANIFEST.in").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            files.process_template_line(line)
    assert sorted(files.files) == sorted(kept)
