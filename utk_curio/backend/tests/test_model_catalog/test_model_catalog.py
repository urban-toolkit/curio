"""The Model Catalog: shipped models read where they are, downloads in a
person's store, and ``curio_load_model`` reaching a node."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from utk_curio.backend.app.datasets.domain.code_refs import MODEL_CALL_RE, model_ids_in_code
from utk_curio.backend.app.model_catalog.domain.manifest import (
    ModelManifestError,
    load_manifest,
    manifest_dict,
    parse_manifest,
)
from utk_curio.backend.app.model_catalog.infrastructure import storage
from utk_curio.backend.app.model_catalog.service import (
    ModelCatalogError,
    ModelCatalogService,
    resolve_exec_models,
)

REPO = Path(__file__).resolve().parents[4]
SHIPPED = REPO / "models"
DDRNET = "model.curio.ddrnet23-slim"


@pytest.fixture()
def auth(user_and_token):
    _user, token = user_and_token
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def shipped(monkeypatch):
    monkeypatch.setenv(storage.ENV_ROOT, str(SHIPPED))
    return SHIPPED


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
        manifest = load_manifest(SHIPPED / f"{DDRNET}@1")
        assert (manifest.runtime, manifest.task) == ("onnx", "semantic-segmentation")
        assert (manifest.input.width, manifest.input.height, manifest.input.dtype) == (2048, 1024, "uint8")
        assert len(manifest.labels) == 19 and {"vegetation", "terrain", "sky", "road"} <= set(manifest.labels)
        folder = SHIPPED / f"{DDRNET}@1"
        assert (folder / manifest.entry).is_file()
        # The graph reads its weights by this name, next to it.
        assert (folder / "files" / "ddrnet23_slim.data").is_file()
        assert manifest.license and (folder / manifest.license_file).is_file()
        text = (folder / manifest.license_file).read_text(encoding="utf-8")
        assert "MIT License" in text and "Cityscapes" in text

    def test_its_size_is_its_files(self):
        folder = SHIPPED / f"{DDRNET}@1"
        manifest = load_manifest(folder)
        assert manifest.size_bytes == sum(p.stat().st_size for p in (folder / "files").iterdir())

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
        """SCOUT's shadow model, which the Accumulated Shadow node of
        ``scout.shadow@1`` runs: an image-to-image ONNX graph on 512 by 512
        NHWC float32 planes, with SCOUT as its publisher."""
        folder = SHIPPED / "model.scout.deep-umbra@1"
        manifest = load_manifest(folder)
        assert (manifest.runtime, manifest.task, manifest.labels) == ("onnx", "image-to-image", ())
        assert (manifest.input.width, manifest.input.height, manifest.input.dtype, manifest.input.layout) == (
            512, 512, "float32", "NHWC",
        )
        assert manifest.publisher == "SCOUT (urban-toolkit/scout)" and manifest.license
        assert manifest.size_bytes == sum(p.stat().st_size for p in (folder / "files").iterdir())

    def test_it_round_trips(self):
        parsed = parse_manifest(_onnx_manifest())
        assert parse_manifest(manifest_dict(parsed)) == parsed


class TestTheCatalog:
    def test_it_lists_the_shipped_model_without_a_path(self, app, shipped, user_and_token):
        user, _ = user_and_token
        items = ModelCatalogService(user).list_catalog()["items"]
        row = next(item for item in items if item["id"] == DDRNET)
        assert row["origin"] == "shipped" and row["runtime"] == "onnx" and row["labelCount"] == 19
        assert str(SHIPPED) not in json.dumps(items)

    def test_a_shipped_model_is_used_where_it_is(self, app, shipped, user_and_token):
        user, _ = user_and_token
        assert ModelCatalogService(user).resolve_dir(DDRNET) == (SHIPPED / f"{DDRNET}@1").resolve()
        assert ModelCatalogService(user).resolve_dir(f"{DDRNET}@1") == (SHIPPED / f"{DDRNET}@1").resolve()

    def test_a_shipped_model_cannot_be_deleted(self, app, shipped, user_and_token):
        user, _ = user_and_token
        with pytest.raises(ModelCatalogError) as exc:
            ModelCatalogService(user).delete_model(DDRNET)
        assert exc.value.status == 403

    def test_a_download_is_added_listed_used_and_deleted(self, app, shipped, user_and_token, tmp_path):
        user, _ = user_and_token
        service = ModelCatalogService(user)
        incoming = tmp_path / "incoming"
        (incoming / "files").mkdir(parents=True)
        (incoming / "files" / "m.onnx").write_bytes(b"onnx")
        raw = _onnx_manifest(discoverySource={"sourceId": "source.x@1", "resourceId": "org/tiny"})
        row = service.install_downloaded(incoming, raw)
        assert row["origin"] == "downloaded" and row["id"].startswith("imported.x")
        assert row["sizeBytes"] == 4 and not incoming.exists()
        assert service.find_by_discovery_resource("source.x@1", "org/tiny")["id"] == row["id"]
        folder = service.resolve_dir(row["id"])
        assert storage.user_models_dir(service.user_key).resolve() in folder.parents
        assert service.delete_model(row["id"]) == {"deleted": row["id"]}
        assert not folder.exists()

    def test_another_persons_download_is_not_theirs(self, app, db, shipped, user_and_token, tmp_path):
        from utk_curio.backend.app.users.models import User

        user, _ = user_and_token
        incoming = tmp_path / "incoming"
        (incoming / "files").mkdir(parents=True)
        (incoming / "files" / "m.onnx").write_bytes(b"onnx")
        row = ModelCatalogService(user).install_downloaded(incoming, _onnx_manifest())
        bob = User(username="bob", name="Bob", email="bob@test.com")
        db.session.add(bob)
        db.session.commit()
        with pytest.raises(ModelCatalogError) as exc:
            ModelCatalogService(bob).resolve_dir(row["id"])
        assert exc.value.status == 404

    def test_a_broken_folder_is_left_out(self, app, monkeypatch, tmp_path, user_and_token):
        root = tmp_path / "models"
        shutil.copytree(SHIPPED / f"{DDRNET}@1", root / f"{DDRNET}@1")
        (root / "model.example.broken@1").mkdir()
        (root / "model.example.broken@1" / "manifest.json").write_text("{not json", encoding="utf-8")
        monkeypatch.setenv(storage.ENV_ROOT, str(root))
        user, _ = user_and_token
        ids = [item["id"] for item in ModelCatalogService(user).list_catalog()["items"]]
        assert ids == [DDRNET]


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
        user, _ = user_and_token
        resolved = resolve_exec_models(f'curio_load_model("{DDRNET}")\ncurio_load_model("model.example.none")', user)
        assert resolved == {DDRNET: str((SHIPPED / f"{DDRNET}@1").resolve())}

    def test_a_run_sends_them_to_the_sandbox(self, client, auth, shipped, monkeypatch):
        from utk_curio.backend.app.execution import node_exec

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
        assert sent.get("models") == {DDRNET: str((SHIPPED / f"{DDRNET}@1").resolve())}

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
    def test_the_image_and_the_wheel_carry_models(self):
        # Read as the shipped sources' packaging checks read theirs: a built
        # image does not carry its own Dockerfile.
        from utk_curio.backend.tests.test_discovery.test_shipped_sources import _packaging_file

        assert "COPY models/ models/" in _packaging_file("Dockerfile")
        assert "recursive-include models" in _packaging_file("MANIFEST.in")

    def test_an_isolated_child_reaches_models_only_as_staged_links(self):
        from utk_curio.sandbox.isolation import hardening

        assert "models" in {relative for relative, _ in hardening.SENSITIVE_PATHS}
        assert "models" in hardening.HARDLINK_SOURCES
