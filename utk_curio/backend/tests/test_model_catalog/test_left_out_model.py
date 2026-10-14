"""Deep Umbra on a pip install: listed, then fetched the first time a node runs it.

The pip package leaves out Deep Umbra's weights (``packages/model.scout.deep-umbra@1/
models/deep_umbra.onnx``, one of the files ``datasets/infrastructure/
left_out_files.json`` lists) and keeps the rest of its model package. So a pip
install's Model Catalog lists the model, and a node that runs it, once its
package is in the user's store (seeded for the examples, or added), gets a
folder holding the package's manifest and the weights, fetched from GitHub on
that first run, as ``curio_load_model`` and the isolated sandbox's staging
read a model folder.

No test opens a socket (``FakeGitHub``); the code under test is imported
inside each test.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from utk_curio.backend.tests._support.left_out_files import (
    COMMIT,
    REPO,
    FakeGitHub,
    catalog_copy,
    url_of,
    write_record,
)

MODEL_ID = "model.scout.deep-umbra"
FOLDER = "packages/model.scout.deep-umbra@1"
WEIGHTS = f"{FOLDER}/models/deep_umbra.onnx"
CLONE = "https://github.com/urban-toolkit/curio"


@pytest.fixture()
def auth(user_and_token):
    _user, token = user_and_token
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def pip_packages(tmp_path, monkeypatch):
    """The package catalog as a pip install has it: Deep Umbra's model package
    without its weights, and the release's record of them."""
    from utk_curio.backend.app.datasets.infrastructure import left_out_files

    root = tmp_path / "site-packages"
    catalog_copy(FOLDER, root)
    monkeypatch.setenv("CURIO_PACKAGES_ROOT", str(root / "packages"))
    monkeypatch.setattr(left_out_files, "RECORD_PATH", write_record(tmp_path / "record.json", [WEIGHTS]))
    assert (root / FOLDER / "manifest.json").is_file() and not (root / WEIGHTS).exists()
    return root


def _capture_sandbox(monkeypatch):
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


def _add(user, pip_packages) -> None:
    """Deep Umbra's package in *user*'s store, as the examples' seeding puts it
    there on a pip install: a copy without the weights."""
    from utk_curio.backend.app.packages.application.store_install import install_package_from_directory
    from utk_curio.backend.app.projects.services import _user_dir_key

    install_package_from_directory(_user_dir_key(user), pip_packages / FOLDER)


def _run(client, auth):
    return client.post("/processPythonCode", headers=auth, json={
        "code": f'model = curio_load_model("{MODEL_ID}")\nreturn 1',
        "nodeType": "COMPUTATION_ANALYSIS",
        "input": "",
    })


def test_the_model_catalog_lists_a_left_out_model_before_fetching_it(pip_packages, monkeypatch):
    from utk_curio.backend.app.model_catalog.service import ModelCatalogService

    github = FakeGitHub().serve(monkeypatch)

    items = {item["id"]: item for item in ModelCatalogService(None).list_catalog()["items"]}

    assert MODEL_ID in items, sorted(items)
    assert items[MODEL_ID]["origin"] == "shipped"
    assert items[MODEL_ID]["sizeBytes"] == (REPO / WEIGHTS).stat().st_size
    assert github.urls == []


def test_a_node_fetches_a_left_out_model_into_a_folder_it_loads(
    client, auth, user_and_token, pip_packages, monkeypatch,
):
    from utk_curio.backend.app.datasets.infrastructure import left_out_files
    from utk_curio.backend.app.packages.repositories.manifests import load_package_manifest

    github = FakeGitHub().serve(monkeypatch)
    sent = _capture_sandbox(monkeypatch)
    _add(user_and_token[0], pip_packages)

    for _ in range(2):
        resp = _run(client, auth)
        assert resp.status_code == 200, resp.get_data(as_text=True)

    assert len(sent) == 2
    folder = Path(sent[0]["models"][MODEL_ID])
    assert sent[1]["models"][MODEL_ID] == str(folder)
    assert folder == left_out_files.fetched_root(COMMIT) / FOLDER
    assert (folder / "models" / "deep_umbra.onnx").read_bytes() == (REPO / WEIGHTS).read_bytes()
    assert (folder / "manifest.json").read_bytes() == (REPO / FOLDER / "manifest.json").read_bytes()
    manifest = load_package_manifest(folder)
    assert (manifest.package_id, manifest.model.entry) == (MODEL_ID, "models/deep_umbra.onnx")
    # Fetched on the first run only.
    assert github.urls == [url_of(WEIGHTS)]


def test_a_failed_model_download_fails_the_node_with_what_failed(
    client, auth, user_and_token, pip_packages, monkeypatch,
):
    """The node fails with the download's own error, and the sandbox is not
    asked to run it."""
    FakeGitHub(fail=OSError("Network is unreachable")).serve(monkeypatch)
    sent = _capture_sandbox(monkeypatch)
    _add(user_and_token[0], pip_packages)

    resp = _run(client, auth)

    assert resp.status_code == 200, resp.get_data(as_text=True)
    reply = resp.get_json()
    assert not reply["output"].get("path"), reply
    for words in (WEIGHTS, url_of(WEIGHTS), "Network is unreachable", CLONE):
        assert words in reply["stderr"], reply["stderr"]
    assert sent == []
