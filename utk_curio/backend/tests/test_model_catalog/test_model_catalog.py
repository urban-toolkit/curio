"""The Model Catalog's backend: the packages service, filtered to kind
``model``. The model packages Curio ships are read where they are, a person's
own sit in their store, and ``curio_load_model`` reaches a node for a model
the person's store holds. Nothing answers under ``/api/models`` any more.

Code main lacks is imported inside each test."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from utk_curio.backend.app.datasets.domain.code_refs import MODEL_CALL_RE, model_ids_in_code

REPO = Path(__file__).resolve().parents[4]
PACKAGES = REPO / "packages"
DDRNET = "model.curio.ddrnet23-slim"
DEEP_UMBRA = "model.scout.deep-umbra"
WEATHER_GNN = "model.scout.weather-gnn"
#: A node package that ships a module of its own.
SCOUT_RASTERS = "scout.rasters"


@pytest.fixture()
def auth(user_and_token):
    _user, token = user_and_token
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def shipped(monkeypatch):
    """The package catalog Curio ships, which holds its model packages."""
    monkeypatch.setenv("CURIO_PACKAGES_ROOT", str(PACKAGES))
    return PACKAGES


def _user_key(user) -> str:
    from utk_curio.backend.app.projects.services import _user_dir_key

    return _user_dir_key(user)


def _add(user, model_id: str) -> Path:
    """*model_id*'s shipped package added to *user*'s store, as Add (or the
    examples' seeding) adds it: the copy holds no weights."""
    from utk_curio.backend.app.packages.application.store_install import install_package_from_directory
    from utk_curio.backend.app.packages.repositories.store import package_dir

    install_package_from_directory(_user_key(user), PACKAGES / f"{model_id}@1")
    return package_dir(_user_key(user), f"{model_id}@1")


def _parse(raw: dict, dir_name: str):
    from utk_curio.backend.app.packages.domain.manifest import package_manifest_from_dict

    return package_manifest_from_dict(raw, manifest_path=Path("manifest.json"), dir_name=dir_name)


def _model_package(**top) -> dict:
    raw = {
        "id": "ai.test.tiny-model", "version": "1.0.0", "name": "Tiny", "publisher": "Test",
        "license": "MIT", "compatibility": {"major": 1}, "kind": "model",
        "templates": [{"id": "seg", "label": "Seg", "category": "computation", "engine": "python",
                       "editor": "code", "inputPorts": [], "outputPorts": []}],
        "model": {"type": "semantic-segmentation", "runtime": "onnx", "entry": "models/m.onnx",
                  "labels": ["a", "b"], "input": {"width": 64, "height": 32, "dtype": "float32", "scale": 0.00392},
                  "license": "MIT", "sizeBytes": 10},
    }
    raw.update(top)
    return raw


class TestTheManifest:
    def test_the_shipped_model_reads_and_says_how_to_feed_it(self):
        """DDRNet23-Slim, the model package whose Image Segmentation node example
        10 runs: an ONNX segmentation graph of 2048 by 1024 uint8 pixels and the
        19 Cityscapes classes. The package's license is its code's, MIT; its
        model block holds the weights', with their license text."""
        from utk_curio.backend.app.packages.repositories.manifests import load_package_manifest

        folder = PACKAGES / f"{DDRNET}@1"
        manifest = load_package_manifest(folder)
        block = manifest.model
        assert (manifest.kind, manifest.license, block.runtime, block.type) == (
            "model", "MIT", "onnx", "semantic-segmentation")
        assert (block.input.width, block.input.height, block.input.dtype) == (2048, 1024, "uint8")
        assert len(block.labels) == 19 and {"vegetation", "terrain", "sky", "road"} <= set(block.labels)
        assert block.entry == "models/ddrnet23_slim.onnx" and (folder / block.entry).is_file()
        # The graph reads its weights by this name, next to it.
        assert (folder / "models" / "ddrnet23_slim.data").is_file()
        assert block.license == "MIT; trained on Cityscapes" and block.license_file == "LICENSE"
        text = (folder / block.license_file).read_text(encoding="utf-8")
        assert "MIT License" in text and "Cityscapes" in text
        assert "models/ddrnet23_slim.onnx" in text and "files/" not in text

    def test_its_size_is_its_files(self):
        from utk_curio.backend.app.packages.repositories.manifests import load_package_manifest

        folder = PACKAGES / f"{DDRNET}@1"
        manifest = load_package_manifest(folder)
        assert manifest.model.size_bytes == sum(p.stat().st_size for p in (folder / "models").iterdir())
        assert manifest.model.size_bytes == 22_857_344 + 219_605

    @pytest.mark.parametrize("raw, dir_name, message", [
        (_model_package(id="Not An Id"), "ai.test.tiny-model@1", "id is missing or malformed"),
        (_model_package(version="1"), "ai.test.tiny-model@1", "must be semver"),
        (_model_package(), "ai.test.other@1", "does not match manifest id/major"),
    ])
    def test_a_model_packages_id_version_and_folder_are_a_packages(self, raw, dir_name, message):
        """The id, version and folder checks the Model Catalog's own manifest
        made are the package manifest's (the model block's own refusals are
        ``test_model_packages.py``'s)."""
        from utk_curio.backend.app.packages.domain.manifest import ManifestError

        with pytest.raises(ManifestError, match=message):
            _parse(raw, dir_name)

    @pytest.mark.parametrize("change", [
        {},
        {"type": "image-to-image", "labels": [],
         "input": {"width": 512, "height": 512, "dtype": "float32", "layout": "NHWC"}},
        {"type": "node-regression", "labels": [], "input": None},
        {"runtime": "transformers", "entry": "models/checkpoint", "labels": [], "input": None},
    ])
    def test_the_model_block_round_trips(self, change):
        """What a listing says of a model is what its manifest says: each type
        and runtime reads back from the block a payload carries."""
        from utk_curio.backend.app.packages.domain.model_block import model_block_dict, parse_model_block

        raw = {**_model_package()["model"], **change}
        block = parse_model_block({key: value for key, value in raw.items() if value is not None})
        assert parse_model_block(model_block_dict(block)) == block

    def test_the_shipped_deep_umbra_reads_and_its_size_is_its_file(self):
        """SCOUT's shadow model, the model package whose Accumulated Shadow
        node runs it: an image-to-image ONNX graph on 512 by 512 NHWC float32
        planes, with SCOUT as its weights' publisher."""
        from utk_curio.backend.app.packages.repositories.manifests import load_package_manifest

        folder = PACKAGES / f"{DEEP_UMBRA}@1"
        manifest = load_package_manifest(folder)
        block = manifest.model
        assert (manifest.kind, block.runtime, block.type, block.labels) == ("model", "onnx", "image-to-image", ())
        assert (block.input.width, block.input.height, block.input.dtype, block.input.layout) == (
            512, 512, "float32", "NHWC",
        )
        assert block.publisher == "SCOUT (urban-toolkit/scout)" and block.license
        assert block.size_bytes == sum(p.stat().st_size for p in (folder / "models").iterdir())

    def test_the_shipped_weather_gnn_reads_and_its_size_is_its_file(self):
        """SCOUT's weather GNN, the model package whose Weather Routing node
        runs it: a node-regression ONNX graph, with SCOUT as its weights'
        publisher."""
        from utk_curio.backend.app.packages.repositories.manifests import load_package_manifest

        folder = PACKAGES / f"{WEATHER_GNN}@1"
        manifest = load_package_manifest(folder)
        block = manifest.model
        assert (manifest.kind, block.runtime, block.type, block.labels, block.input) == (
            "model", "onnx", "node-regression", (), None)
        assert block.publisher == "SCOUT (urban-toolkit/scout)" and block.license
        assert block.size_bytes == sum(p.stat().st_size for p in (folder / "models").iterdir())


#: The id of the model package :func:`_downloaded` writes.
DOWNLOADED = "imported.xa1b2c3d4e5f6"


def _downloaded(user, tmp_path, *, source: dict | None = None) -> str:
    """A model package of *user*'s own with its weights, written into their
    store as the Discovery Catalog writes one; its id."""
    from utk_curio.backend.app.packages.service import install_downloaded_model, model_template

    files = tmp_path / "incoming"
    files.mkdir(parents=True)
    (files / "m.onnx").write_bytes(b"onnx")
    block = {
        "type": "semantic-segmentation", "runtime": "onnx", "entry": "models/m.onnx", "labels": ["a", "b"],
        "input": {"width": 64, "height": 32, "dtype": "float32", "scale": 0.00392},
        "license": "MIT", "publisher": "org", "sizeBytes": 4,
        **({"discoverySource": source} if source else {}),
    }
    install_downloaded_model(_user_key(user), files, {
        "id": DOWNLOADED, "kind": "model", "name": "Tiny", "version": "1.0.0", "compatibility": {"major": 1},
        "publisher": "org", "license": "MIT", "templates": [model_template("semantic-segmentation")],
        "model": block,
    })
    return DOWNLOADED


def _rows(client, auth, route: str) -> dict[str, dict]:
    resp = client.get(route, headers=auth)
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return {row["dirName"]: row for row in resp.get_json()["packages"]}


class TestTheCatalog:
    def test_it_lists_the_shipped_model_without_a_path(self, client, auth, shipped):
        rows = _rows(client, auth, "/api/packages/catalog?kind=model")
        row = rows[f"{DDRNET}@1"]
        assert (row["kind"], row["model"]["runtime"], len(row["model"]["labels"])) == ("model", "onnx", 19)
        assert str(PACKAGES) not in json.dumps(rows)

    def test_a_shipped_model_runs_once_added_and_where_it_ships(self, app, shipped, user_and_token):
        """Models behave like nodes: listed in the catalog, DDRNet23-Slim gives a
        node no folder until it is added; added, its id and its id with its
        major resolve to the catalog's copy, which holds the weights."""
        from utk_curio.backend.app.packages.service import resolve_model_dirs

        user, _ = user_and_token
        assert resolve_model_dirs(_user_key(user), [DDRNET]) == {}
        copy = _add(user, DDRNET)
        assert not (copy / "models").exists()
        folder = str((PACKAGES / f"{DDRNET}@1").resolve())
        assert resolve_model_dirs(_user_key(user), [DDRNET, f"{DDRNET}@1"]) == {DDRNET: folder, f"{DDRNET}@1": folder}

    def test_removing_a_shipped_model_removes_only_the_accounts_copy(self, client, auth, shipped, user_and_token):
        """Remove takes a shipped model package out of the account, as it takes
        a node package: the store's copy goes, and the catalog keeps the package
        and its weights."""
        user, _ = user_and_token
        copy = _add(user, DDRNET)
        assert f"{DDRNET}@1" in _rows(client, auth, "/api/packages?kind=model")
        removed = client.delete(f"/api/packages/{DDRNET}@1", headers=auth)
        assert removed.status_code == 204, removed.get_data(as_text=True)
        assert not copy.exists()
        assert f"{DDRNET}@1" not in _rows(client, auth, "/api/packages?kind=model")
        assert f"{DDRNET}@1" in _rows(client, auth, "/api/packages/catalog?kind=model")
        assert (PACKAGES / f"{DDRNET}@1" / "models" / "ddrnet23_slim.onnx").is_file()

    def test_a_download_is_added_listed_used_and_removed(self, client, auth, shipped, user_and_token, tmp_path):
        """A model the Discovery Catalog downloaded is a model package in the
        person's store, with its weights: listed as theirs, found by its source
        row, run from the store, and removed from it."""
        from utk_curio.backend.app.packages.repositories.store import package_dir
        from utk_curio.backend.app.packages.service import downloaded_model_package, resolve_model_dirs

        user, _ = user_and_token
        key = _user_key(user)
        model_id = _downloaded(user, tmp_path, source={"sourceId": "source.x@1", "resourceId": "org/tiny"})
        row = _rows(client, auth, "/api/packages?kind=model")[f"{model_id}@1"]
        assert (row["packageId"], row["model"]["sizeBytes"]) == (model_id, 4) and not (tmp_path / "incoming").exists()
        assert row["model"]["discoverySource"] == {"sourceId": "source.x@1", "resourceId": "org/tiny"}
        assert downloaded_model_package(key, "source.x@1", "org/tiny") == {
            "id": model_id, "dirName": f"{model_id}@1", "name": "Tiny", "dependencies": [],
        }
        assert downloaded_model_package(key, "source.x@1", "org/other") is None
        folder = Path(resolve_model_dirs(key, [model_id])[model_id])
        assert folder == package_dir(key, f"{model_id}@1")
        assert (folder / "models" / "m.onnx").read_bytes() == b"onnx"
        assert client.delete(f"/api/packages/{model_id}@1", headers=auth).status_code == 204
        assert not folder.exists()

    def test_another_persons_download_is_not_theirs(self, app, db, shipped, user_and_token, tmp_path):
        from utk_curio.backend.app.packages.application.catalog import installed_package_payloads
        from utk_curio.backend.app.packages.service import downloaded_model_package, resolve_model_dirs
        from utk_curio.backend.app.users.models import User

        user, _ = user_and_token
        model_id = _downloaded(user, tmp_path, source={"sourceId": "source.x@1", "resourceId": "org/tiny"})
        bob = User(username="bob", name="Bob", email="bob@test.com")
        db.session.add(bob)
        db.session.commit()
        assert resolve_model_dirs(_user_key(bob), [model_id]) == {}
        assert model_id not in [row["packageId"] for row in installed_package_payloads(_user_key(bob), "model")]
        assert downloaded_model_package(_user_key(bob), "source.x@1", "org/tiny") is None

    def test_a_broken_folder_is_left_out(self, app, monkeypatch, tmp_path, user_and_token):
        """A package catalog holding DDRNet23-Slim's package and a folder whose
        manifest cannot be read lists the one model."""
        from utk_curio.backend.app.packages.application.catalog import catalog_listing

        root = tmp_path / "packages"
        (root / f"{DDRNET}@1").mkdir(parents=True)
        shutil.copyfile(PACKAGES / f"{DDRNET}@1" / "manifest.json", root / f"{DDRNET}@1" / "manifest.json")
        (root / "model.example.broken@1").mkdir()
        (root / "model.example.broken@1" / "manifest.json").write_text("{not json", encoding="utf-8")
        monkeypatch.setenv("CURIO_PACKAGES_ROOT", str(root))
        user, _ = user_and_token
        ids = [row["packageId"] for row in catalog_listing(_user_key(user), "model")["packages"]]
        assert ids == [DDRNET]


def _imported_model_package(root: Path) -> Path:
    """A model package of a person's own, with its weights and their license
    text, as an import or a publish leaves it."""
    folder = root / "ai.test.relief-model@1"
    (folder / "models").mkdir(parents=True)
    (folder / "models" / "relief.onnx").write_bytes(b"onnx graph")
    (folder / "models" / "LICENSE.txt").write_text("The weights are free to use.\n", encoding="utf-8")
    manifest = {
        "id": "ai.test.relief-model", "version": "1.0.0", "name": "Relief model", "publisher": "Test",
        "license": "MIT", "compatibility": {"major": 1}, "kind": "model",
        "description": "A relief model of a person's own.",
        "templates": [{"id": "relief", "label": "Relief", "category": "computation", "engine": "python",
                       "editor": "code", "inputPorts": [{"types": ["RASTER"]}], "outputPorts": [{"types": ["RASTER"]}]}],
        "model": {"type": "node-regression", "runtime": "onnx", "entry": "models/relief.onnx", "labels": [],
                  "license": "CC-BY-4.0", "licenseFile": "models/LICENSE.txt", "publisher": "Test Lab",
                  "sizeBytes": 10},
    }
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return folder


class TestModelPackagesInTheModelCatalog:
    """The model packages, through the packages listings filtered to kind
    ``model``: the catalog's (DDRNet23-Slim, Deep Umbra and the weather GNN),
    and those imported or published into a person's store. Each shows once,
    with its weights' fields, its modules and its weights' license text."""

    def test_the_listing_shows_each_model_package_once_with_its_weights_fields(self, client, auth, shipped):
        rows = _rows(client, auth, "/api/packages/catalog?kind=model")
        # One row a model: the three the palette counts.
        assert sorted(rows) == sorted(f"{model_id}@1" for model_id in (DDRNET, DEEP_UMBRA, WEATHER_GNN))
        for model_id, model_type, module in (
            (DEEP_UMBRA, "image-to-image", "deep_umbra"), (WEATHER_GNN, "node-regression", "weather_routing"),
        ):
            row = rows[f"{model_id}@1"]
            block = row["model"]
            weights = next((PACKAGES / f"{model_id}@1" / "models").iterdir())
            assert (row["kind"], row["license"], block["runtime"], block["type"]) == ("model", "MIT", "onnx", model_type)
            assert (block["license"], block["publisher"]) == (
                "Used with the permission of SCOUT's authors", "SCOUT (urban-toolkit/scout)")
            assert block["sizeBytes"] == weights.stat().st_size
            assert block["labels"] == [] and "licenseFile" not in block
            # The module its node imports, and the weights at hand in a clone.
            assert row["modules"] == [module]
            assert block["downloadsOnFirstUse"] is False
        assert rows[f"{DEEP_UMBRA}@1"]["name"] == "Deep Umbra (accumulated shadows)"
        assert {key: rows[f"{DEEP_UMBRA}@1"]["model"]["input"][key] for key in ("width", "height", "dtype")} == {
            "width": 512, "height": 512, "dtype": "float32"}
        assert "input" not in rows[f"{WEATHER_GNN}@1"]["model"]
        ddrnet = rows[f"{DDRNET}@1"]
        block = ddrnet["model"]
        assert (ddrnet["name"], ddrnet["license"], block["license"], block["licenseFile"]) == (
            "DDRNet23-Slim (street scenes)", "MIT", "MIT; trained on Cityscapes", "LICENSE")
        assert block["publisher"] == "DDRNet authors; ONNX export by Qualcomm AI Hub Models (v0.63.0, w8a8)"
        assert block["homepage"] == "https://huggingface.co/qualcomm/DDRNet23-Slim"
        assert {key: block["input"][key] for key in ("width", "height", "dtype")} == {
            "width": 2048, "height": 1024, "dtype": "uint8"}
        assert (len(block["labels"]), block["sizeBytes"], ddrnet["createdAt"]) == (19, 23_076_949, "2026-10-01T00:00:00Z")
        assert sorted(ddrnet["dependencies"]["python"]) == ["onnxruntime"]
        assert ddrnet["modules"] == [] and block["downloadsOnFirstUse"] is False
        assert [template["label"] for template in ddrnet["templates"]] == ["Image Segmentation"]
        from utk_curio.backend.app.packages.service import catalog_root

        text = json.dumps(rows)
        assert str(catalog_root()) not in text and str(PACKAGES) not in text

    def test_every_package_lists_its_modules(self, client, auth, shipped, user_and_token):
        """A node package names its modules as a model package does, in the
        catalog and in the store; one that ships none names none."""
        from utk_curio.backend.app.packages.application.store_install import install_package_from_directory

        user, _ = user_and_token
        catalog = _rows(client, auth, "/api/packages/catalog?kind=node")
        assert catalog[f"{SCOUT_RASTERS}@1"]["modules"] == ["scout_rasters"]
        assert catalog["curio.builtin@1"]["modules"] == []
        install_package_from_directory(_user_key(user), PACKAGES / f"{SCOUT_RASTERS}@1")
        _add(user, DEEP_UMBRA)
        assert _rows(client, auth, "/api/packages?kind=node")[f"{SCOUT_RASTERS}@1"]["modules"] == [
            "scout_rasters"]
        assert _rows(client, auth, "/api/packages?kind=model")[f"{DEEP_UMBRA}@1"]["modules"] == ["deep_umbra"]

    def test_the_weights_license_text_is_read_where_the_package_is(self, client, auth, shipped, user_and_token):
        """DDRNet23-Slim's weights license text, from the catalog for an account
        that never added it and from the account's copy once added; a package
        whose weights have no license file has no text."""
        route = f"/api/packages/{DDRNET}@1/weights-license"
        before = client.get(route, headers=auth)
        assert before.status_code == 200, before.get_data(as_text=True)
        expected = (PACKAGES / f"{DDRNET}@1" / "LICENSE").read_text(encoding="utf-8")
        assert before.get_json()["text"] == expected and "Cityscapes" in expected
        _add(user_and_token[0], DDRNET)
        assert client.get(route, headers=auth).get_json()["text"] == expected
        assert client.get(f"/api/packages/{DEEP_UMBRA}@1/weights-license", headers=auth).status_code == 404
        assert client.get("/api/packages/model.example.none@1/weights-license", headers=auth).status_code == 404
        # A node package has no weights.
        assert client.get("/api/packages/curio.builtin@1/weights-license", headers=auth).status_code == 404

    def test_an_imported_one_is_listed_licensed_and_removed(self, client, auth, user_and_token, shipped, tmp_path):
        """A model package in the person's store with its own weights: theirs,
        with its weights' license text, and removed as the Node Catalog removes
        a package, from the store and from every dataflow's lockfile."""
        from utk_curio.backend.app.packages.application.store_install import install_package_from_archive
        from utk_curio.backend.app.packages.repositories.archive import zip_package_tree
        from utk_curio.backend.app.packages.repositories.store import package_dir
        from utk_curio.backend.app.projects import storage as projects_storage

        user, _ = user_and_token
        key = _user_key(user)
        install_package_from_archive(key, zip_package_tree(_imported_model_package(tmp_path / "incoming")))
        project = client.post("/api/projects", headers=auth, json={
            "name": "uses the relief model",
            "spec": {"dataflow": {"nodes": [], "edges": [], "packages": ["ai.test.relief-model@1"]}},
            "outputs": [],
        })
        assert project.status_code == 201, project.get_data(as_text=True)
        project_id = project.get_json()["id"]

        row = _rows(client, auth, "/api/packages?kind=model")["ai.test.relief-model@1"]
        block = row["model"]
        assert (row["name"], block["type"], block["license"], block["publisher"], block["sizeBytes"]) == (
            "Relief model", "node-regression", "CC-BY-4.0", "Test Lab", 10)
        assert block["downloadsOnFirstUse"] is False
        license_text = client.get("/api/packages/ai.test.relief-model@1/weights-license", headers=auth)
        assert license_text.get_json()["text"] == "The weights are free to use.\n"

        removed = client.delete("/api/packages/ai.test.relief-model@1", headers=auth)
        assert removed.status_code == 204, removed.get_data(as_text=True)
        assert not package_dir(key, "ai.test.relief-model@1").exists()
        assert projects_storage.read_spec(key, project_id)["dataflow"]["packages"] == []
        assert "ai.test.relief-model@1" not in _rows(client, auth, "/api/packages?kind=model")


class TestTheRoutes:
    def test_the_weights_license_needs_a_session(self, client, shipped):
        assert client.get(f"/api/packages/{DDRNET}@1/weights-license").status_code == 401

    @pytest.mark.parametrize("method, route", [
        ("get", "/api/models/catalog"),
        ("get", f"/api/models/{DDRNET}"),
        ("get", f"/api/models/{DDRNET}/license"),
        ("delete", f"/api/models/{DDRNET}"),
    ])
    def test_the_model_catalog_routes_are_gone(self, client, auth, shipped, method, route):
        """The Model Catalog is the packages service's: ``/api/models`` answers
        nothing."""
        assert getattr(client, method)(route, headers=auth).status_code == 404


class TestANodeReachesIt:
    def test_the_calls_in_code_are_found(self):
        code = f'm = curio_load_model("{DDRNET}")\nn = curio_load_model(\'other.model.x@2\')\ncurio_load_model("{DDRNET}")'
        assert model_ids_in_code(code) == [DDRNET, "other.model.x@2"]
        assert model_ids_in_code("curio_data_path('x.y')") == []
        assert not MODEL_CALL_RE.search('curio_load_model("a.b\')')

    def test_the_backend_resolves_them_for_the_account(self, app, shipped, user_and_token):
        """From the account's store: the model it added resolves, a model that
        names no package does not, and neither does one it never added."""
        from utk_curio.backend.app.execution.node_exec import resolve_models

        user, _ = user_and_token
        _add(user, DDRNET)
        resolved = resolve_models(
            f'curio_load_model("{DDRNET}")\ncurio_load_model("model.example.none")\n'
            f'curio_load_model("{DEEP_UMBRA}")', user,
        )
        assert resolved == {DDRNET: str((PACKAGES / f"{DDRNET}@1").resolve())}

    def test_a_run_sends_them_to_the_sandbox(self, client, auth, shipped, user_and_token, monkeypatch):
        from utk_curio.backend.app.execution import node_exec

        user, _ = user_and_token
        _add(user, DDRNET)
        sent = {}

        class Response:
            status_code = 200

            def json(self):
                return {"stdout": [], "stderr": "", "output": {"path": "", "dataType": "str"}}

        def fake_call(method, path, **kwargs):
            sent.update(json.loads(kwargs["data"]))
            return Response()

        monkeypatch.setattr(node_exec, "sandbox_request", fake_call)
        client.post("/processPythonCode", headers=auth, json={
            "code": f'model = curio_load_model("{DDRNET}")\nreturn 1', "nodeType": "COMPUTATION_ANALYSIS",
            "input": "",
        })
        assert sent.get("models") == {DDRNET: str((PACKAGES / f"{DDRNET}@1").resolve())}

    def test_code_that_runs_no_model_sends_no_models_key(self, client, auth, shipped, monkeypatch):
        from utk_curio.backend.app.execution import node_exec

        sent = {}

        class Response:
            status_code = 200

            def json(self):
                return {"stdout": [], "stderr": "", "output": {"path": "", "dataType": "str"}}

        monkeypatch.setattr(node_exec, "sandbox_request",
                            lambda method, path, **kw: sent.update(json.loads(kw["data"])) or Response())
        client.post("/processPythonCode", headers=auth, json={
            "code": "return 1", "nodeType": "COMPUTATION_ANALYSIS", "input": "",
        })
        assert "models" not in sent


class TestItShips:
    def test_models_ship_as_model_packages_and_no_models_folder_does(self):
        """The models Curio ships are model packages, in ``packages/``: the
        image and the wheel carry ``packages/`` with DDRNet23-Slim's weights,
        and no ``models/`` folder any more (nor a launcher flag that moved
        one)."""
        # Read as the shipped sources' packaging checks read theirs: a built
        # image does not carry its own Dockerfile.
        from utk_curio import shipped
        from utk_curio.backend.tests.test_discovery.test_shipped_sources import _packaging_file

        dockerfile, manifest_in = _packaging_file("Dockerfile"), _packaging_file("MANIFEST.in")
        assert "COPY packages/ packages/" in dockerfile and "COPY models/" not in dockerfile
        assert "recursive-include packages *" in manifest_in and "recursive-include models" not in manifest_in
        assert "ddrnet23_slim" not in manifest_in  # its weights are not left out of the wheel
        assert "models" not in shipped.FOLDERS and "packages" in shipped.FOLDERS
        assert not (REPO / "models").exists()
        assert (PACKAGES / f"{DDRNET}@1" / "models" / "ddrnet23_slim.onnx").is_file()

    def test_an_isolated_child_reaches_model_weights_only_as_staged_links(self):
        """A model package's weights, ``packages/*/models``, are closed to an
        execution account and staged into a run as hardlinks; there is no
        ``models/`` folder to close."""
        from utk_curio.sandbox.isolation import hardening

        sensitive = {relative for relative, _ in hardening.SENSITIVE_PATHS}
        assert "packages/*/models" in sensitive and "packages/*/models" in hardening.HARDLINK_SOURCES
        assert "models" not in sensitive and "models" not in hardening.HARDLINK_SOURCES

    def test_an_isolated_child_reaches_fetched_files_only_as_staged_links(self):
        """What a pip install downloads (Deep Umbra's graph among it) is kept as
        the shipped models are: the folder is closed to an execution account,
        and its files keep their modes, so the hardlink a run stages stays
        readable."""
        from utk_curio.backend.app.datasets.infrastructure import left_out_files
        from utk_curio.sandbox.isolation import hardening

        fetched = f".curio/{left_out_files.FETCHED}"
        assert fetched in {relative for relative, _ in hardening.SENSITIVE_PATHS}
        assert fetched in hardening.HARDLINK_SOURCES
