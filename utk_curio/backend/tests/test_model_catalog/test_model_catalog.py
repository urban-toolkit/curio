"""The Model Catalog: the model packages Curio ships, read where they are, a
person's own in their store, and ``curio_load_model`` reaching a node for a
model the person's store holds."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from utk_curio.backend.app.datasets.domain.code_refs import MODEL_CALL_RE, model_ids_in_code
from utk_curio.backend.app.model_catalog.domain.manifest import (
    ModelManifestError,
    manifest_dict,
    parse_manifest,
)
from utk_curio.backend.app.model_catalog.service import (
    ModelCatalogError,
    ModelCatalogService,
)

REPO = Path(__file__).resolve().parents[4]
PACKAGES = REPO / "packages"
DDRNET = "model.curio.ddrnet23-slim"
DEEP_UMBRA = "model.scout.deep-umbra"
WEATHER_GNN = "model.scout.weather-gnn"


@pytest.fixture()
def auth(user_and_token):
    _user, token = user_and_token
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def shipped(monkeypatch):
    """The package catalog Curio ships, which holds its model packages."""
    monkeypatch.setenv("CURIO_PACKAGES_ROOT", str(PACKAGES))
    return PACKAGES


def _add(user, model_id: str) -> Path:
    """*model_id*'s shipped package added to *user*'s store, as Add (or the
    examples' seeding) adds it: the copy holds no weights."""
    from utk_curio.backend.app.packages.application.store_install import install_package_from_directory
    from utk_curio.backend.app.packages.repositories.store import package_dir

    install_package_from_directory(_user_key(user), PACKAGES / f"{model_id}@1")
    return package_dir(_user_key(user), f"{model_id}@1")


def _onnx_manifest(**overrides):
    raw = {
        "id": "model.example.tiny", "name": "Tiny", "version": "1.0.0", "compatibility": {"major": 1},
        "license": "MIT", "runtime": "onnx", "task": "semantic-segmentation", "entry": "files/m.onnx",
        "labels": ["a", "b"], "input": {"width": 64, "height": 32, "dtype": "float32", "scale": 0.00392},
    }
    raw.update(overrides)
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

    @pytest.mark.parametrize("change, message", [
        ({"runtime": "tflite"}, "runtime must be one of"),
        ({"task": "detection"}, "task must be one of"),
        ({"entry": "../m.onnx"}, "inside the model's folder"),
        ({"entry": "/abs/m.onnx"}, "inside the model's folder"),
        ({"entry": "files/m.bin"}, "entry is its .onnx file"),
        ({"labels": []}, "names its labels"),
        ({"license": ""}, "license must be"),
        ({"input": {"width": 64, "height": 32, "dtype": "int64"}}, "input.dtype"),
        ({"input": {"width": 64, "height": 32, "std": [1, 0, 1]}}, "zero"),
        ({"id": "Not An Id"}, "is not a model id"),
        ({"version": "1"}, "version must look like"),
        ({"homepage": "http://x.example"}, "https"),
        ({"input": {"width": 64, "height": 32, "layout": "CHW"}}, "input.layout must be one of"),
        ({"input": {"width": 64, "height": 32, "layout": "NHWC"}}, "NCHW for this task"),
    ])
    def test_what_it_refuses(self, change, message):
        with pytest.raises(ModelManifestError, match=message):
            parse_manifest(_onnx_manifest(**change))

    def test_a_folder_is_named_for_its_model(self):
        with pytest.raises(ModelManifestError, match="<id>@<major>"):
            parse_manifest(_onnx_manifest(), dir_name="model.example.other@1")

    def test_a_transformers_checkpoint_may_leave_labels_to_its_config(self):
        manifest = parse_manifest(_onnx_manifest(runtime="transformers", entry="files", labels=[], input=None))
        assert manifest.labels == () and manifest.input is None

    def test_an_image_to_image_model_has_no_labels_and_may_read_nhwc(self):
        manifest = parse_manifest(_onnx_manifest(
            task="image-to-image", labels=[],
            input={"width": 512, "height": 512, "dtype": "float32", "layout": "NHWC"},
        ))
        assert manifest.labels == () and manifest.input.layout == "NHWC"
        assert parse_manifest(manifest_dict(manifest)) == manifest

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

    def test_a_node_regression_model_reads_a_graph_of_any_size(self):
        """It has no labels and no image input: the node feeds it a graph (#740)."""
        manifest = parse_manifest(_onnx_manifest(task="node-regression", labels=[], input=None))
        assert manifest.labels == () and manifest.input is None
        assert parse_manifest(manifest_dict(manifest)) == manifest

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

    def test_it_round_trips(self):
        parsed = parse_manifest(_onnx_manifest())
        assert parse_manifest(manifest_dict(parsed)) == parsed


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


class TestTheCatalog:
    def test_it_lists_the_shipped_model_without_a_path(self, app, shipped, user_and_token):
        user, _ = user_and_token
        items = ModelCatalogService(user).list_catalog()["items"]
        row = next(item for item in items if item["id"] == DDRNET)
        assert row["origin"] == "shipped" and row["runtime"] == "onnx" and row["labelCount"] == 19
        assert str(PACKAGES) not in json.dumps(items)

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

    def test_a_shipped_model_cannot_be_deleted(self, app, shipped, user_and_token):
        user, _ = user_and_token
        with pytest.raises(ModelCatalogError) as exc:
            ModelCatalogService(user).delete_model(DDRNET)
        assert exc.value.status == 403

    def test_a_download_is_added_listed_used_and_deleted(self, app, shipped, user_and_token, tmp_path):
        """A model the Discovery Catalog downloaded is a model package in the
        person's store, with its weights: listed as theirs, found by its source
        row, run from the store, and deleted from it."""
        from utk_curio.backend.app.packages.repositories.store import package_dir
        from utk_curio.backend.app.packages.service import resolve_model_dirs

        user, _ = user_and_token
        model_id = _downloaded(user, tmp_path, source={"sourceId": "source.x@1", "resourceId": "org/tiny"})
        service = ModelCatalogService(user)
        row = service.get_model(model_id)
        assert (row["origin"], row["sizeBytes"]) == ("downloaded", 4) and not (tmp_path / "incoming").exists()
        assert service.find_by_discovery_resource("source.x@1", "org/tiny")["id"] == model_id
        folder = Path(resolve_model_dirs(_user_key(user), [model_id])[model_id])
        assert folder == package_dir(_user_key(user), f"{model_id}@1")
        assert (folder / "models" / "m.onnx").read_bytes() == b"onnx"
        assert service.delete_model(model_id) == {"deleted": model_id}
        assert not folder.exists()

    def test_another_persons_download_is_not_theirs(self, app, db, shipped, user_and_token, tmp_path):
        from utk_curio.backend.app.packages.service import resolve_model_dirs
        from utk_curio.backend.app.users.models import User

        user, _ = user_and_token
        model_id = _downloaded(user, tmp_path)
        bob = User(username="bob", name="Bob", email="bob@test.com")
        db.session.add(bob)
        db.session.commit()
        assert resolve_model_dirs(_user_key(bob), [model_id]) == {}
        with pytest.raises(ModelCatalogError) as exc:
            ModelCatalogService(bob).get_model(model_id)
        assert exc.value.status == 404

    def test_a_broken_folder_is_left_out(self, app, monkeypatch, tmp_path, user_and_token):
        """A package catalog holding DDRNet23-Slim's package and a folder whose
        manifest cannot be read lists the one model."""
        root = tmp_path / "packages"
        (root / f"{DDRNET}@1").mkdir(parents=True)
        shutil.copyfile(PACKAGES / f"{DDRNET}@1" / "manifest.json", root / f"{DDRNET}@1" / "manifest.json")
        (root / "model.example.broken@1").mkdir()
        (root / "model.example.broken@1" / "manifest.json").write_text("{not json", encoding="utf-8")
        monkeypatch.setenv("CURIO_PACKAGES_ROOT", str(root))
        user, _ = user_and_token
        ids = [item["id"] for item in ModelCatalogService(user).list_catalog()["items"]]
        assert ids == [DDRNET]


def _user_key(user) -> str:
    from utk_curio.backend.app.projects.services import _user_dir_key

    return _user_dir_key(user)


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
    """The model packages, through ``/api/models``: the catalog's (Deep Umbra
    and the weather GNN), and those imported or published into a person's
    store. Each model shows once, with its weights' fields."""

    def test_the_listing_shows_each_model_package_once_with_its_weights_fields(self, client, auth, shipped):
        items = client.get("/api/models/catalog", headers=auth).get_json()["items"]
        # One row a model: DDRNet23-Slim, Deep Umbra and the weather GNN, the
        # three the palette counts.
        assert sorted(item["id"] for item in items) == sorted([DDRNET, DEEP_UMBRA, WEATHER_GNN])
        rows = {item["id"]: item for item in items}
        for model_id, task in ((DEEP_UMBRA, "image-to-image"), (WEATHER_GNN, "node-regression")):
            row = rows[model_id]
            weights = next((PACKAGES / f"{model_id}@1" / "models").iterdir())
            assert (row["origin"], row["dirName"], row["runtime"], row["task"]) == (
                "shipped", f"{model_id}@1", "onnx", task)
            assert (row["license"], row["publisher"]) == (
                "Used with the permission of SCOUT's authors", "SCOUT (urban-toolkit/scout)")
            assert row["sizeBytes"] == weights.stat().st_size
            assert row["labels"] == [] and row["hasLicenseText"] is False
        assert rows[DEEP_UMBRA]["name"] == "Deep Umbra (accumulated shadows)"
        assert rows[DEEP_UMBRA]["input"] == {"width": 512, "height": 512, "dtype": "float32"}
        assert "input" not in rows[WEATHER_GNN]
        # DDRNet23-Slim, a model package now, reads as it did from models/.
        ddrnet = rows[DDRNET]
        assert (ddrnet["origin"], ddrnet["dirName"], ddrnet["runtime"], ddrnet["task"]) == (
            "shipped", f"{DDRNET}@1", "onnx", "semantic-segmentation")
        assert (ddrnet["name"], ddrnet["license"], ddrnet["hasLicenseText"]) == (
            "DDRNet23-Slim (street scenes)", "MIT; trained on Cityscapes", True)
        assert ddrnet["publisher"] == "DDRNet authors; ONNX export by Qualcomm AI Hub Models (v0.63.0, w8a8)"
        assert ddrnet["homepage"] == "https://huggingface.co/qualcomm/DDRNet23-Slim"
        assert ddrnet["input"] == {"width": 2048, "height": 1024, "dtype": "uint8"}
        assert (ddrnet["labelCount"], ddrnet["sizeBytes"], ddrnet["createdAt"]) == (19, 23_076_949, "2026-10-01T00:00:00Z")
        assert ddrnet["dependencies"] == ["onnxruntime"]
        from utk_curio.backend.app.packages.service import catalog_root

        assert str(catalog_root()) not in json.dumps(items) and str(PACKAGES) not in json.dumps(items)

    def test_one_is_opened_by_its_id_and_a_shipped_one_has_no_license_text(self, client, auth, shipped):
        row = client.get(f"/api/models/{DEEP_UMBRA}", headers=auth).get_json()
        assert (row["id"], row["origin"]) == (DEEP_UMBRA, "shipped")
        assert client.get(f"/api/models/{DEEP_UMBRA}@1", headers=auth).get_json()["id"] == DEEP_UMBRA
        assert client.get(f"/api/models/{DEEP_UMBRA}/license", headers=auth).status_code == 404

    def test_a_copy_in_the_store_is_the_shipped_model_and_is_not_deleted(self, client, auth, user_and_token, shipped):
        """Seeded for the examples, or added: the copy holds no weights, so the
        model is the catalog's, listed once and refused a delete."""
        from utk_curio.backend.app.packages.application.store_install import install_package_from_directory
        from utk_curio.backend.app.packages.repositories.store import package_dir

        user, _ = user_and_token
        install_package_from_directory(_user_key(user), PACKAGES / f"{DEEP_UMBRA}@1")
        copy = package_dir(_user_key(user), f"{DEEP_UMBRA}@1")
        assert (copy / "manifest.json").is_file() and not (copy / "models").exists()

        items = client.get("/api/models/catalog", headers=auth).get_json()["items"]
        assert [item["origin"] for item in items if item["id"] == DEEP_UMBRA] == ["shipped"]
        assert client.get(f"/api/models/{DEEP_UMBRA}", headers=auth).get_json()["origin"] == "shipped"
        assert client.delete(f"/api/models/{DEEP_UMBRA}", headers=auth).status_code == 403
        assert (copy / "manifest.json").is_file()

    def test_an_imported_one_is_listed_opened_licensed_and_deleted(self, client, auth, user_and_token, shipped, tmp_path):
        """A model package in the person's store with its own weights: theirs,
        with its weights' license text, and deleted as the Node Catalog removes
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

        items = client.get("/api/models/catalog", headers=auth).get_json()["items"]
        (row,) = [item for item in items if item["id"] == "ai.test.relief-model"]
        assert (row["origin"], row["task"], row["license"], row["publisher"], row["hasLicenseText"]) == (
            "downloaded", "node-regression", "CC-BY-4.0", "Test Lab", True)
        assert row["sizeBytes"] == 10
        assert client.get("/api/models/ai.test.relief-model", headers=auth).get_json()["name"] == "Relief model"
        license_text = client.get("/api/models/ai.test.relief-model/license", headers=auth).get_json()["text"]
        assert license_text == "The weights are free to use.\n"

        deleted = client.delete("/api/models/ai.test.relief-model", headers=auth)
        assert deleted.status_code == 200, deleted.get_data(as_text=True)
        assert deleted.get_json() == {"deleted": "ai.test.relief-model"}
        assert not package_dir(key, "ai.test.relief-model@1").exists()
        assert projects_storage.read_spec(key, project_id)["dataflow"]["packages"] == []
        assert client.get("/api/models/ai.test.relief-model", headers=auth).status_code == 404


class TestTheRoutes:
    def test_they_need_a_session(self, client, shipped):
        assert client.get("/api/models/catalog").status_code == 401

    def test_the_listing_and_one_model(self, client, auth, shipped):
        items = client.get("/api/models/catalog", headers=auth).get_json()["items"]
        assert DDRNET in [item["id"] for item in items]
        row = client.get(f"/api/models/{DDRNET}", headers=auth).get_json()
        assert row["name"].startswith("DDRNet23-Slim")

    def test_the_license_text(self, client, auth, shipped):
        text = client.get(f"/api/models/{DDRNET}/license", headers=auth).get_json()["text"]
        assert "MIT License" in text

    def test_an_unknown_model_is_404_and_a_shipped_one_is_not_deleted(self, client, auth, shipped):
        assert client.get("/api/models/model.example.none", headers=auth).status_code == 404
        assert client.delete(f"/api/models/{DDRNET}", headers=auth).status_code == 403

    def test_a_search(self, client, auth, shipped):
        assert client.get("/api/models/catalog?q=cityscapes", headers=auth).get_json()["items"]
        assert client.get("/api/models/catalog?q=nothing-like-it", headers=auth).get_json()["items"] == []


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
