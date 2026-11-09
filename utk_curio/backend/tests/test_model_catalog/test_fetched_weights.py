"""Model packages whose weights their ``fetch`` names, downloaded the first time a node needs them.

A model package can ship without its weights and name them in its model
block's ``fetch``: files of a Hugging Face repository at one commit, each with
its digest (``packages/domain/model_fetch.py``). The first time a node runs a
shipped package's model, the backend downloads them
(``packages/infrastructure/fetched_weights.py``) through the code a pip
install's left-out files download with (``left_out_files``), into the
package's entry folder, or under the folder ``curio.py start
--model-weights-dir`` names, where Curio reads them in place.
``scripts/fetch_model_weights.py`` fetches them there ahead.

- The ``concept-segmentation`` type and the ``fetch`` block, as the schema and
  the parser read them, and what each refuses, a template of that type with
  no source of its own among it.
- Where a run reads the weights: the package's own folder, or the flag's
  folder, which the sandbox gets apart from the model's and reads in place.
- The first use: one download, each file checked against its digest, with no
  token and an idle timeout, before the sandbox is asked to run the node; a
  second use reads them in place; two first uses download once; a file that
  does not match, a cut download, a gated or gone source, an address the
  egress policy refuses and a folder Curio cannot write each place nothing
  and fail the node's run, saying what failed and naming the script.
- The Model Catalog's listing says the weights download on first use until
  they are here.
- Integrity, ``scripts/regen_integrity.py`` among it, leaves them out.
- Export, Publish and Save as package node refuse the package, saying why.
- No shipped package keeps a folder under ``models/`` but a fetched entry,
  which ``.gitignore``, ``.dockerignore`` and ``MANIFEST.in`` leave out.

The package is made in each test's own folder, never in ``packages/``. No test
opens a socket: ``FakeHuggingFace`` stands in for Hugging Face
(``test_scripts/test_fetch_model_weights.py`` covers the script). The code
under test is imported inside each test.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import shutil
import stat
import threading
import time
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


REPOSITORY = "acme/tiny-prompted"
FETCH = {
    "huggingface": REPOSITORY,
    "revision": REVISION,
    "files": [
        {"path": "config.json", "gitSha1": _git_blob_sha1(CONFIG)},
        {"path": "model.safetensors", "sha256": hashlib.sha256(WEIGHTS).hexdigest()},
    ],
}
#: What Hugging Face holds of the repository at REVISION.
FILES = {"config.json": CONFIG, "model.safetensors": WEIGHTS}
SCRIPT = f"scripts/fetch_model_weights.py {PACKAGE_ID}"


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


#: The test package's one node, whose code it ships.
SOURCE = "sources/find.py"


def _template(**change) -> dict:
    """The test package's template; a None in *change* removes a key."""
    template = {"id": "find", "label": "Find", "category": "computation", "engine": "python", "editor": "code",
                "source": SOURCE, "inputPorts": [], "outputPorts": [{"types": ["DATAFRAME"]}]}
    for key, value in change.items():
        if value is None:
            template.pop(key, None)
        else:
            template[key] = value
    return template


def _manifest(**top) -> dict:
    raw = {
        "id": PACKAGE_ID, "version": "1.0.0", "name": NAME, "publisher": "Test", "license": "MIT",
        "compatibility": {"major": 1}, "kind": "model",
        "templates": [_template()],
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
    (folder / "sources").mkdir(exist_ok=True)
    (folder / SOURCE).write_text(
        f'model = curio_load_model("{PACKAGE_ID}")\nreturn input_0\n', encoding="utf-8",
    )
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


def test_a_concept_segmentation_template_with_no_source_of_its_own_is_refused():
    """Its node is the code its package ships: Curio writes no cell for the
    type, so the parser and the schema refuse a template without a source,
    saying why. A semantic segmentation model's template still may have none,
    and opens with the cell Curio writes for it."""
    from utk_curio.backend.app.packages.domain.manifest import ManifestError

    refused = _manifest(templates=[_template(), _template(id="plain", source=None)])
    with pytest.raises(ManifestError, match=re.escape(
        "manifest.json.templates['plain']: a concept-segmentation model's node runs the code its package ships, "
        "so the template names its source (sources/<file>.py)"
    )):
        _parse(refused)
    assert list(_validator().iter_errors(refused))

    segmentation = _manifest(
        templates=[_template(source=None)],
        model=_block(type="semantic-segmentation", fetch=None, labels=["road", "sky"]),
    )
    assert _parse(segmentation).templates[0].source is None
    assert list(_validator().iter_errors(segmentation)) == []


# ---------------------------------------------------------------------------
# Where a run reads the weights
# ---------------------------------------------------------------------------

def _hugging_face(monkeypatch, files=None, **kwargs):
    """A Hugging Face serving the test package's files at REVISION, the
    weights through a redirect to its CDN, as the code under test's."""
    from utk_curio.backend.tests._support.fetched_weights import FakeHuggingFace

    return FakeHuggingFace(
        REPOSITORY, REVISION, FILES if files is None else files, redirect=("model.safetensors",), **kwargs,
    ).serve(monkeypatch)


def _no_download(monkeypatch):
    """A Hugging Face that fails the test it is asked anything in."""
    return _hugging_face(monkeypatch, fail=AssertionError("Hugging Face was asked for a file"))


def _urls() -> list[str]:
    """What a first use asks for: each file the block lists, and the weights
    again on the CDN the redirect names."""
    from utk_curio.backend.tests._support.fetched_weights import CDN, resolve_url

    return [
        resolve_url(REPOSITORY, REVISION, "config.json"),
        resolve_url(REPOSITORY, REVISION, "model.safetensors"),
        f"{CDN}/model.safetensors",
    ]


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def _left_in(entry: Path) -> list[str]:
    """The names in *entry* that are not the files the block lists: the
    download's lock, and anything a download left."""
    return sorted(path.name for path in entry.iterdir() if path.name not in FILES)


def test_a_first_use_downloads_the_weights_into_the_catalogs_copy_and_a_second_reads_them_there(
    catalog, monkeypatch,
):
    """Added, its copy holds no weights, nor does the catalog: resolving it
    downloads each file the block lists into the catalog's copy, with no
    token, waiting at most the idle timeout for each answer, each file
    checked and readable by every account, the models/ folder its owner's as
    isolation leaves a shipped package's. The next resolve reads them there,
    and an account that never added the model gets none, and downloads
    nothing."""
    from utk_curio.backend.app.datasets.infrastructure import left_out_files
    from utk_curio.backend.app.packages.service import resolve_model_dirs, resolve_model_weights

    hugging_face = _hugging_face(monkeypatch)
    copy = _add("guest", catalog)

    assert resolve_model_dirs("guest", [PACKAGE_ID]) == {PACKAGE_ID: str((catalog / DIR).resolve())}

    assert hugging_face.urls == _urls()
    assert {request.timeout_s for request in hugging_face.requests} == {left_out_files.IDLE_TIMEOUT_S}
    assert [request.headers for request in hugging_face.requests] == [{}, {}, {}], "a token or a header was sent"
    entry = catalog / DIR / ENTRY
    assert {name: (entry / name).read_bytes() for name in FILES} == FILES
    assert [_mode(entry / name) for name in FILES] == [0o644, 0o644]
    assert (_mode(entry), _mode(entry.parent)) == (0o755, 0o700)
    assert _left_in(entry) == [".download.lock"]
    assert _mode(entry / ".download.lock") == 0o644
    assert not (copy / "models").exists()

    assert resolve_model_dirs("guest", [PACKAGE_ID]) == {PACKAGE_ID: str((catalog / DIR).resolve())}
    assert resolve_model_weights("guest", [PACKAGE_ID]) == {}
    assert resolve_model_dirs("7", [PACKAGE_ID]) == {}
    assert len(hugging_face.requests) == 3


def test_weights_fetched_into_the_package_are_read_there(catalog, monkeypatch):
    from utk_curio.backend.app.packages.application.model_packages import weights_on_first_use
    from utk_curio.backend.app.packages.repositories.manifests import load_package_manifest
    from utk_curio.backend.app.packages.service import resolve_model_dirs, resolve_model_weights

    _no_download(monkeypatch)
    copy = _add("guest", catalog)
    _fetch_into(catalog / DIR)

    assert resolve_model_dirs("guest", [PACKAGE_ID]) == {PACKAGE_ID: str((catalog / DIR).resolve())}
    assert resolve_model_weights("guest", [PACKAGE_ID]) == {}
    assert not weights_on_first_use(load_package_manifest(copy), copy)
    assert not (copy / "models").exists()


def test_with_the_flag_the_weights_are_read_in_place_from_its_folder(catalog, weights_dir, monkeypatch):
    """``<dir>/<package id>@<major>/<entry>``: the run gets the catalog's
    folder for the manifest and the flag's folder for the weights, and
    nothing is copied into the account's store."""
    from utk_curio.backend.app.packages.application.model_packages import weights_on_first_use
    from utk_curio.backend.app.packages.repositories.manifests import load_package_manifest
    from utk_curio.backend.app.packages.service import resolve_model_dirs, resolve_model_weights

    _no_download(monkeypatch)
    copy = _add("guest", catalog)
    root = _fetch_into(weights_dir / DIR)

    assert resolve_model_dirs("guest", [PACKAGE_ID, f"{PACKAGE_ID}@1"]) == {
        PACKAGE_ID: str((catalog / DIR).resolve()), f"{PACKAGE_ID}@1": str((catalog / DIR).resolve()),
    }
    assert resolve_model_weights("guest", [PACKAGE_ID]) == {PACKAGE_ID: str(root.resolve())}
    assert not weights_on_first_use(load_package_manifest(copy), copy)
    assert not (copy / "models").exists()


def test_with_the_flag_the_packages_own_folder_and_a_stopped_fetch_count_as_not_here(catalog, weights_dir):
    """The flag names the one place: weights left in the package's folder are
    not read, and a folder that lacks one listed file is not complete, so the
    weights download on first use. Asking where they are read downloads
    nothing."""
    from utk_curio.backend.app.packages.application.model_packages import weights_on_first_use
    from utk_curio.backend.app.packages.repositories.manifests import load_package_manifest
    from utk_curio.backend.app.packages.service import resolve_model_weights

    copy = _add("guest", catalog)
    _fetch_into(catalog / DIR)
    _fetch_into(weights_dir / DIR, "config.json")
    manifest = load_package_manifest(copy)

    assert resolve_model_weights("guest", [PACKAGE_ID]) == {}
    assert weights_on_first_use(manifest, copy)
    assert weights_on_first_use(manifest, catalog / DIR)
    assert not (weights_dir / DIR / ENTRY / "model.safetensors").exists()

    _fetch_into(weights_dir / DIR)
    assert not weights_on_first_use(manifest, copy)


def test_with_the_flag_a_first_use_downloads_only_what_the_flags_folder_lacks(catalog, weights_dir, monkeypatch):
    """Into ``<dir>/<package id>@<major>/<entry>``, which isolated node code
    reads in place: every folder made there every account may enter, the
    files readable by all, and a file already there is not asked for again.
    The catalog's copy and the account's stay as they were."""
    from utk_curio.backend.app.packages.service import resolve_model_dirs, resolve_model_weights
    from utk_curio.backend.tests._support.fetched_weights import resolve_url

    copy = _add("guest", catalog)
    root = _fetch_into(weights_dir / DIR, "config.json")
    hugging_face = _hugging_face(monkeypatch)
    umask = os.umask(0o077)
    try:
        assert resolve_model_dirs("guest", [PACKAGE_ID]) == {PACKAGE_ID: str((catalog / DIR).resolve())}
    finally:
        os.umask(umask)

    assert hugging_face.urls == _urls()[1:]
    assert resolve_url(REPOSITORY, REVISION, "config.json") not in hugging_face.urls
    entry = root / ENTRY
    assert (entry / "model.safetensors").read_bytes() == WEIGHTS
    assert (_mode(entry / "model.safetensors"), _mode(entry / ".download.lock")) == (0o644, 0o644)
    assert resolve_model_weights("guest", [PACKAGE_ID]) == {PACKAGE_ID: str(root.resolve())}
    assert not (catalog / DIR / "models").exists() and not (copy / "models").exists()

    # A first use on an empty folder makes each folder every account enters.
    shutil.rmtree(root)
    os.umask(0o077)
    try:
        resolve_model_dirs("guest", [PACKAGE_ID])
    finally:
        os.umask(umask)
    assert [_mode(folder) for folder in (root, root / "models", entry)] == [0o755, 0o755, 0o755]
    assert {name: (entry / name).read_bytes() for name in FILES} == FILES


def test_two_first_uses_download_once(catalog, monkeypatch):
    """While one first use downloads the weights, a second waits for it
    rather than downloading them again, then reads what the first placed."""
    from utk_curio.backend.app.packages.service import resolve_model_dirs

    entered, release = threading.Event(), threading.Event()

    def hold(_url):
        entered.set()
        assert release.wait(30)

    hugging_face = _hugging_face(monkeypatch, before=hold)
    _add("guest", catalog)
    results, errors = [], []

    def resolve():
        try:
            results.append(resolve_model_dirs("guest", [PACKAGE_ID]))
        except Exception as exc:  # noqa: BLE001 - reported below, by the test's thread
            errors.append(exc)

    first = threading.Thread(target=resolve)
    first.start()
    assert entered.wait(30)
    second = threading.Thread(target=resolve)
    second.start()
    time.sleep(0.5)
    assert len(hugging_face.requests) == 1, hugging_face.urls
    release.set()
    first.join(30)
    second.join(30)

    assert errors == []
    assert hugging_face.urls == _urls()
    assert results == [{PACKAGE_ID: str((catalog / DIR).resolve())}] * 2
    assert {name: (catalog / DIR / ENTRY / name).read_bytes() for name in FILES} == FILES


def _failed_first_use(catalog) -> str:
    """The message a first use that fails leaves for the node's run
    (``left_out_files.failures``); the model still resolves to the catalog's
    copy, with no weights."""
    from utk_curio.backend.app.datasets.infrastructure import left_out_files
    from utk_curio.backend.app.packages.service import resolve_model_dirs, resolve_model_weights

    with left_out_files.failures() as failed:
        assert resolve_model_dirs("guest", [PACKAGE_ID]) == {PACKAGE_ID: str((catalog / DIR).resolve())}
        assert resolve_model_weights("guest", [PACKAGE_ID]) == {}
    assert list(failed) == [f"{PACKAGE_ID}@1"], failed
    return failed[f"{PACKAGE_ID}@1"]


def test_a_file_whose_digest_does_not_match_is_refused_and_never_placed(catalog, monkeypatch):
    tampered = WEIGHTS[:-1] + b"X"
    _hugging_face(monkeypatch, files={**FILES, "model.safetensors": tampered})
    _add("guest", catalog)

    message = _failed_first_use(catalog)

    expected = hashlib.sha256(WEIGHTS).hexdigest()
    assert f"sha256 {hashlib.sha256(tampered).hexdigest()}" in message and f"sha256 {expected}" in message, message
    assert "so it was not placed" in message and SCRIPT in message, message
    entry = catalog / DIR / ENTRY
    assert not (entry / "model.safetensors").exists()
    assert _left_in(entry) == [".download.lock"], "a file that does not match, or a partial file, was left"


def test_a_download_cut_midway_leaves_nothing_and_the_next_use_fetches_it_whole(catalog, monkeypatch):
    _hugging_face(monkeypatch, cut=OSError("Connection reset by peer"))
    _add("guest", catalog)

    message = _failed_first_use(catalog)

    assert "Connection reset by peer" in message and SCRIPT in message, message
    entry = catalog / DIR / ENTRY
    assert not any((entry / name).exists() for name in FILES)
    assert _left_in(entry) == [".download.lock"]

    from utk_curio.backend.app.packages.service import resolve_model_dirs

    hugging_face = _hugging_face(monkeypatch)
    resolve_model_dirs("guest", [PACKAGE_ID])
    assert hugging_face.urls == _urls()
    assert {name: (entry / name).read_bytes() for name in FILES} == FILES


def test_a_partial_file_a_dead_download_left_is_removed_and_a_live_ones_kept(catalog, monkeypatch):
    """A process that died mid-download left its partial file: the next
    first use removes it. One another download still writes is newer, and
    stays."""
    from utk_curio.backend.app.datasets.infrastructure import left_out_files
    from utk_curio.backend.app.packages.service import resolve_model_dirs

    entry = catalog / DIR / ENTRY
    entry.mkdir(parents=True)
    dead, live = entry / ".model.safetensors.dead1.part", entry / ".model.safetensors.live1.part"
    dead.write_bytes(WEIGHTS[:100])
    live.write_bytes(WEIGHTS[:100])
    long_ago = time.time() - left_out_files.STALE_PARTIAL_S - 60
    os.utime(dead, (long_ago, long_ago))
    _hugging_face(monkeypatch)
    _add("guest", catalog)

    resolve_model_dirs("guest", [PACKAGE_ID])

    assert not dead.exists() and live.exists()
    assert {name: (entry / name).read_bytes() for name in FILES} == FILES


@pytest.mark.parametrize("status, code, says, asks_for_a_token", [
    (401, "GatedRepo", f"Hugging Face refused it (HTTP 401): {REPOSITORY} is gated, or gone", True),
    (403, None, f"Hugging Face refused it (HTTP 403): {REPOSITORY} is gated, or gone", True),
    (401, "RepoNotFound", f"Hugging Face has no config.json in {REPOSITORY} at {REVISION} (HTTP 401)", False),
    (404, "EntryNotFound", f"Hugging Face has no config.json in {REPOSITORY} at {REVISION} (HTTP 404)", False),
], ids=["gated", "refused", "gone", "no such file"])
def test_a_source_that_refuses_fails_the_run_naming_it_and_the_script(
    client, user_and_token, catalog, monkeypatch, status, code, says, asks_for_a_token,
):
    """Gated or gone: the node's run fails with the download's message, which
    names the source and the script that fetches the weights ahead, with a
    token for a gated repository. The sandbox is not asked, and nothing is
    placed."""
    from utk_curio.backend.tests._support.fetched_weights import resolve_url

    user, token = user_and_token
    _add(_key(user), catalog)
    _hugging_face(monkeypatch, status=status, error_code=code)
    sent = _capture_sandbox(monkeypatch)

    reply = _play(client, token)

    assert reply.status_code == 200, reply.get_data(as_text=True)
    body = reply.get_json()
    assert not body["output"].get("path"), body
    stderr = body["stderr"]
    assert says in stderr, stderr
    assert resolve_url(REPOSITORY, REVISION, "config.json") in stderr, stderr
    assert f"https://huggingface.co/{REPOSITORY}" in stderr and SCRIPT in stderr, stderr
    assert ("HF_TOKEN=" in stderr) is asks_for_a_token, stderr
    assert sent == []
    assert not any((catalog / DIR / ENTRY / name).exists() for name in FILES)


def test_the_download_goes_through_the_egress_policy(catalog, monkeypatch):
    """A host that resolves to a private address is refused before any request."""
    from utk_curio.backend.app.datasets.infrastructure import left_out_files

    hugging_face = _hugging_face(monkeypatch)
    monkeypatch.setattr(left_out_files, "resolver", lambda host: ["169.254.169.254"])
    _add("guest", catalog)

    message = _failed_first_use(catalog)

    assert hugging_face.requests == []
    assert "non-public address" in message, message


def test_a_file_bigger_than_the_model_is_refused(catalog, monkeypatch):
    """Each file is bounded by the model's sizeBytes: the block lists no size
    of its own for each."""
    _hugging_face(monkeypatch, files={**FILES, "model.safetensors": WEIGHTS * 2})
    _add("guest", catalog)

    message = _failed_first_use(catalog)

    assert f"over the {len(CONFIG) + len(WEIGHTS)}-byte bound" in message, message
    assert not (catalog / DIR / ENTRY / "model.safetensors").exists()


def test_a_folder_curio_cannot_write_says_so_and_names_the_script_with_into(catalog, tmp_curio, monkeypatch):
    """With nowhere to put the weights, the node's run says where it could
    not write, to start Curio with --model-weights-dir naming a folder it can
    write, and the script that fetches them there ahead. Nothing is asked of
    Hugging Face."""
    hugging_face = _hugging_face(monkeypatch)
    blocked = tmp_curio / "a-file"
    blocked.write_text("not a folder", encoding="utf-8")
    monkeypatch.setenv("CURIO_MODEL_WEIGHTS_DIR", str(blocked / "model-weights"))
    _add("guest", catalog)

    message = _failed_first_use(catalog)

    assert message.startswith(
        f"Curio could not write the weights of {PACKAGE_ID} into {blocked.resolve() / 'model-weights' / DIR / ENTRY}: "
    ), message
    assert "Start Curio with --model-weights-dir naming a folder it can write" in message, message
    assert f"{SCRIPT} --into <that folder>" in message, message
    assert hugging_face.requests == []


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
    _no_download(monkeypatch)
    sent = _capture_sandbox(monkeypatch)

    reply = _play(client, token)

    assert reply.status_code == 200, reply.get_data(as_text=True)
    assert sent[0]["models"] == {PACKAGE_ID: str((catalog / DIR).resolve())}
    assert sent[0]["model_weights"] == {PACKAGE_ID: str(root.resolve())}


def test_a_nodes_first_run_downloads_the_weights_once_before_the_sandbox_runs_it(
    client, user_and_token, catalog, weights_dir, monkeypatch,
):
    """The download is the backend's, before it asks the sandbox to run the
    node: the sandbox has been asked nothing while a byte of it is asked for,
    so the node's time limit, which the sandbox keeps, starts after it. The
    run then reads the weights in place, and so does the next, which asks
    Hugging Face for nothing."""
    user, token = user_and_token
    _add(_key(user), catalog)
    sent = _capture_sandbox(monkeypatch)
    asked_while_downloading = []
    hugging_face = _hugging_face(monkeypatch, before=lambda _url: asked_while_downloading.append(len(sent)))

    for _ in range(2):
        reply = _play(client, token)
        assert reply.status_code == 200, reply.get_data(as_text=True)

    assert hugging_face.urls == _urls()
    assert asked_while_downloading == [0, 0, 0]
    root = (weights_dir / DIR).resolve()
    assert len(sent) == 2
    for body in sent:
        assert body["models"] == {PACKAGE_ID: str((catalog / DIR).resolve())}
        assert body["model_weights"] == {PACKAGE_ID: str(root)}
    assert {name: (root / ENTRY / name).read_bytes() for name in FILES} == FILES


def test_a_run_without_the_flag_downloads_into_the_catalogs_copy_and_sends_no_weights_folder(
    client, user_and_token, catalog, monkeypatch,
):
    user, token = user_and_token
    _add(_key(user), catalog)
    hugging_face = _hugging_face(monkeypatch)
    sent = _capture_sandbox(monkeypatch)

    reply = _play(client, token)

    assert reply.status_code == 200, reply.get_data(as_text=True)
    assert hugging_face.urls == _urls()
    assert sent[0]["models"] == {PACKAGE_ID: str((catalog / DIR).resolve())}
    assert "model_weights" not in sent[0]
    assert {name: (catalog / DIR / ENTRY / name).read_bytes() for name in FILES} == FILES


# ---------------------------------------------------------------------------
# The Model Catalog's listing
# ---------------------------------------------------------------------------

def _catalog_row(client, token) -> dict:
    resp = client.get("/api/packages/catalog?kind=model", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return {row["dirName"]: row for row in resp.get_json()["packages"]}[DIR]


def test_the_listing_says_the_weights_download_on_first_use_until_they_are_here(
    client, user_and_token, catalog, monkeypatch,
):
    """As it says of a pip install's left-out weights, with nothing
    downloaded to say so."""
    token = user_and_token[1]
    _no_download(monkeypatch)

    row = _catalog_row(client, token)
    assert (row["model"]["type"], row["model"]["fetch"]) == ("concept-segmentation", FETCH)
    assert row["model"]["downloadsOnFirstUse"] is True
    assert "weightsNotFetched" not in row["model"]

    _fetch_into(catalog / DIR)
    assert _catalog_row(client, token)["model"]["downloadsOnFirstUse"] is False


def test_an_accounts_own_package_whose_fetch_the_catalog_does_not_ship_never_downloads(catalog, monkeypatch):
    """A download trusts a shipped manifest's fetch alone: a package of the
    account's own that names one, which the catalog does not hold, resolves
    with no weights, its node says they are not here, and its listing does
    not say they download."""
    from utk_curio.backend.app.packages.application.model_packages import weights_on_first_use
    from utk_curio.backend.app.packages.application.store_install import install_package_from_directory
    from utk_curio.backend.app.packages.repositories.manifests import load_package_manifest
    from utk_curio.backend.app.packages.repositories.store import package_dir
    from utk_curio.backend.app.packages.service import resolve_model_dirs, resolve_model_weights

    _no_download(monkeypatch)
    own = _write_package(catalog.parent / "own" / "model.test.own@1", _manifest(id="model.test.own"))
    install_package_from_directory("guest", own)
    copy = package_dir("guest", "model.test.own@1")

    resolved = resolve_model_dirs("guest", ["model.test.own"])
    assert {key: Path(value).resolve() for key, value in resolved.items()} == {"model.test.own": copy.resolve()}
    assert resolve_model_weights("guest", ["model.test.own"]) == {}
    assert not weights_on_first_use(load_package_manifest(copy), copy)
    assert not (copy / "models").exists()


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
    assert sorted(listed) == ["manifest.json", "models/LICENSE.txt", SOURCE], listed
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
    assert "2 GiB" in message and "Each Curio downloads them the first time a node runs the model." in message, message


def test_export_refuses_it_from_the_account_and_from_the_catalog_saying_why(catalog):
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
