"""Hugging Face models: a model source, searched like a portal, added to the
Model Catalog.

Against the recorded corpus (``fixtures/huggingface-models``): the Hub's real
answers, with every weights file indexed to a synthetic stand-in, so no
one's weights are in the repository.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from utk_curio.backend.app.discovery.domain import manifest as M
from utk_curio.backend.app.discovery.domain.errors import (
    CapabilityUnsupported,
    CredentialRequired,
    DownloadTooLarge,
)
from utk_curio.backend.app.discovery.domain.manifest import load_source_manifest
from utk_curio.backend.app.discovery.domain.resource import SearchQuery
from utk_curio.backend.app.discovery.infrastructure.transport import (
    DiscoveryTransportError,
    FixtureDiscoveryTransport,
)
from utk_curio.backend.app.discovery.providers import build_model_provider, huggingface_models as hfm
from utk_curio.backend.tests.test_discovery.conftest import FIXTURES, SHIPPED_ROOT, a_manifest
from utk_curio.backend.tests.test_discovery.test_acquire import acquire, wait_for

SOURCE = "source.huggingface.models@1"
ONNX_REPO = "Xenova/segformer-b0-finetuned-ade-512-512"
TRANSFORMERS_REPO = "openmmlab/upernet-convnext-tiny"
PICKLE_REPO = "openmmlab/upernet-convnext-small"


@pytest.fixture()
def auth(user_and_token):
    _user, token = user_and_token
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def pip(monkeypatch):
    """The packages' own dependency installer, recorded rather than run: no
    test installs torch."""
    from utk_curio.backend.app.packages.application import provisioning

    calls = []

    def provision(user_key, dir_name, declaration):
        calls.append({"user_key": user_key, "dir_name": dir_name, "deps": dict(declaration.python_deps),
                      "backend": declaration.backend, "templates": tuple(declaration.templates)})
        return {"importErrors": {}}

    monkeypatch.setattr(provisioning, "provision_declared_deps", provision)
    return calls


@pytest.fixture()
def live(app, shipped_root, fixture_corpus, monkeypatch):
    from utk_curio.backend.app.model_catalog.infrastructure import storage as model_storage

    # The shipped models stay where they are; downloads go to the test's store.
    monkeypatch.setenv(model_storage.ENV_ROOT, str(Path(__file__).resolve().parents[4] / "models"))
    return app


def _manifest():
    return load_source_manifest(SHIPPED_ROOT / SOURCE)


def _provider():
    return build_model_provider(_manifest(), FixtureDiscoveryTransport(FIXTURES))


class TestTheManifest:
    def test_the_shipped_source_is_a_model_source(self):
        manifest = _manifest()
        assert manifest.is_model and not manifest.is_storage and not manifest.is_service
        assert manifest.capabilities.formats == ("model",)
        assert manifest.auth.secret_id == "huggingface.token" and not manifest.auth.needs_token

    def test_its_capabilities_and_resources_are_not_declared(self):
        raw = a_manifest(provider={"type": "huggingface-models", "baseUrl": "https://huggingface.co"})
        with pytest.raises(M.ManifestError, match="capabilities is fixed"):
            M._parse_manifest(raw, where="manifest.json")
        raw.pop("capabilities")
        raw["resources"] = [{"id": "x", "name": "X", "kind": "table", "format": "csv", "path": "x.csv"}]
        with pytest.raises(M.ManifestError, match="resources only applies"):
            M._parse_manifest(raw, where="manifest.json")


class TestSearch:
    def test_rows_are_models_curio_can_load(self):
        page = _provider().search(SearchQuery(text="segformer", limit=20))
        assert page.resources
        for row in page.resources:
            assert row.kind == "model" and row.formats == ("model",)
            assert "ONNX" in row.description or "safetensors" in row.description
            assert row.landing_url == f"https://huggingface.co/{row.resource_id}"
        assert ONNX_REPO in {row.resource_id for row in page.resources}

    def test_a_next_page_is_its_cursor(self):
        page = _provider().search(SearchQuery(text="segformer", limit=20))
        assert page.next_cursor is None or isinstance(page.next_cursor, str)
        headers = {"Link": '<https://huggingface.co/api/models?limit=20&cursor=abc%3D>; rel="next"'}
        assert hfm._next_cursor(headers) == "abc="
        assert hfm._next_cursor({}) is None

    def test_a_repo_without_loadable_weights_is_left_out(self):
        provider = _provider()
        assert provider._row({"id": "a/b", "tags": ["pytorch"]}) is None
        assert provider._row({"id": "a/b", "tags": ["onnx"]}) is not None
        assert provider._row({"id": "a/b", "tags": ["onnx"], "private": True}) is None
        assert provider._row({"id": "../etc", "tags": ["onnx"]}) is None


class TestWhatAnAddFetches:
    def test_an_onnx_export_fetches_its_graph_and_configs(self):
        plan = _provider().plan(ONNX_REPO)
        assert plan.runtime == "onnx" and plan.graph == "onnx/model.onnx"
        assert [p for p, _s in plan.files] == ["config.json", "preprocessor_config.json", "onnx/model.onnx"]
        assert len(plan.revision) == 40

    def test_a_transformers_checkpoint_fetches_safetensors(self):
        plan = _provider().plan(TRANSFORMERS_REPO)
        assert plan.runtime == "transformers" and plan.architecture == "UperNetForSemanticSegmentation"
        assert [p for p, _s in plan.files] == ["config.json", "preprocessor_config.json", "model.safetensors"]
        assert plan.license == "mit"

    def test_pickled_weights_are_refused_and_say_why(self):
        with pytest.raises(CapabilityUnsupported, match="only pytorch_model.bin.*load without running code"):
            _provider().plan(PICKLE_REPO)

    def test_a_model_too_big_is_refused(self, monkeypatch):
        monkeypatch.setattr(hfm, "MAX_MODEL_BYTES", 1024)
        with pytest.raises(DownloadTooLarge, match="a model may be at most"):
            _provider().plan(ONNX_REPO)

    def test_an_architecture_curio_does_not_run_is_refused(self):
        info = {
            "id": "a/b", "sha": "0" * 40, "config": {"architectures": ["Mask2FormerForUniversalSegmentation"]},
            "siblings": [{"rfilename": f, "size": 1} for f in ("config.json", "preprocessor_config.json", "model.safetensors")],
        }
        with pytest.raises(CapabilityUnsupported, match="not a semantic segmentation model"):
            _provider().plan("a/b", info)

    def test_files_come_from_the_pinned_commit_on_the_hub(self):
        provider = _provider()
        plan = provider.plan(ONNX_REPO)
        assert provider.file_url(plan, "onnx/model.onnx") == (
            f"https://huggingface.co/{ONNX_REPO}/resolve/{plan.revision}/onnx/model.onnx"
        )


class TestItLandsInTheModelCatalog:
    def _add(self, client, auth, repo):
        res = acquire(client, auth, SOURCE, repo)
        assert res.status_code == 202, res.get_data(as_text=True)
        job = wait_for(client, auth, res.get_json()["jobId"], timeout=60)
        return job

    def test_an_onnx_model_with_its_labels_and_input(self, client, auth, live):
        job = self._add(client, auth, ONNX_REPO)
        assert job["status"] == "completed", job
        assert job["stageMessage"] == "Added to your Model Catalog" and job["dataset"] is None
        model = job["model"]
        assert model["origin"] == "downloaded" and model["runtime"] == "onnx"
        assert model["labelCount"] == 150 and "wall" in model["labels"]
        assert model["input"] == {"width": 512, "height": 512, "dtype": "float32"}
        assert model["discoverySource"]["resourceId"] == ONNX_REPO
        listed = client.get("/api/models/catalog", headers=auth).get_json()["items"]
        assert model["id"] in {item["id"] for item in listed}

    def test_its_files_keep_their_relative_paths(self, app, client, auth, live, user_and_token):
        from utk_curio.backend.app.model_catalog.service import ModelCatalogService

        model = self._add(client, auth, ONNX_REPO)["model"]
        user, _ = user_and_token
        folder = ModelCatalogService(user).resolve_dir(model["id"])
        assert (folder / "files" / "onnx" / "model.onnx").is_file()
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["entry"] == "files/onnx/model.onnx"
        assert manifest["input"]["mean"] and manifest["input"]["std"]

    def test_an_added_model_runs_in_a_node(self, app, client, auth, live, user_and_token, tmp_path):
        """The whole route: what an add writes is what ``curio_segment`` reads,
        on two of example 10's photos. The graph is the synthetic stand-in, so
        the classes are noise; their shares still have to cover the image."""
        from utk_curio.backend.app.model_catalog.service import ModelCatalogService
        from utk_curio.sandbox.util.catalog_helpers import CurioModel
        from utk_curio.sandbox.util.collections import make_collection_helpers
        from utk_curio.sandbox.util.vision import make_curio_segment

        model = self._add(client, auth, ONNX_REPO)["model"]
        user, _ = user_and_token
        folder = ModelCatalogService(user).resolve_dir(model["id"])
        repo = Path(__file__).resolve().parents[4]
        sample = "data.curio.mapillary-sample"
        index = repo / "datasets" / f"{sample}@1" / "data" / "index.parquet"
        storage = repo / "docs" / "examples" / "data" / "storage"
        helpers = make_collection_helpers(
            lambda _id: str(index), {sample: {"kind": "images", "root": str(storage)}}, str(tmp_path)
        )
        photos = helpers["curio_load_collection"](sample).head(2)
        out = make_curio_segment(helpers["curio_derived_file"])(photos, CurioModel(model["id"], str(folder)), None)
        shares = out[[f"{label}_pct" for label in model["labels"]]]
        assert shares.sum(axis=1).between(99.5, 100.5).all()
        assert out["dominant_class"].isin(model["labels"]).all()
        assert out["overlay_url"].notna().all() and out["segment_error"].isna().all()

    def test_a_transformers_checkpoint(self, client, auth, live):
        model = self._add(client, auth, TRANSFORMERS_REPO)["model"]
        assert model["runtime"] == "transformers" and model["license"] == "mit"
        assert model["labelCount"] == 150

    def test_its_libraries_install_by_the_packages_path(self, client, auth, live, pip):
        """As a package's dependencies.python installs: the model's folder name
        in place of the package's, no backend surface, so the libraries go
        where node code finds them."""
        job = self._add(client, auth, TRANSFORMERS_REPO)
        model = job["model"]
        assert model["dependencies"] == ["safetensors", "torch", "transformers"]
        assert len(pip) == 1
        assert pip[0]["dir_name"] == model["dirName"] and pip[0]["backend"] is None
        assert pip[0]["deps"]["torch"] == ">=2.6"
        assert job["dependencies"] == {"importErrors": {}}

    def test_an_onnx_model_installs_nothing(self, client, auth, live, pip):
        """onnxruntime comes with the Street Vision package."""
        job = self._add(client, auth, ONNX_REPO)
        assert job["model"]["dependencies"] == [] and pip == [] and job["dependencies"] is None

    def test_someone_who_may_not_install_is_refused_before_any_download(self, client, auth, live, pip, monkeypatch):
        from utk_curio.backend.app.model_catalog import service as model_service

        monkeypatch.setattr(model_service.ModelCatalogService, "install_refusal",
                            lambda self: "this Curio does not install packages for guests")
        fetched = []
        monkeypatch.setattr(hfm.HuggingFaceModels, "file_url",
                            lambda self, plan, path: fetched.append(path) or f"{self.base}/x")
        job = self._add(client, auth, TRANSFORMERS_REPO)
        assert job["status"] == "failed" and "does not install packages for guests" in job["error"]
        assert "torch" in job["error"] and fetched == [] and pip == []

    def test_a_refused_repo_fails_its_job_with_the_reason(self, client, auth, live):
        job = self._add(client, auth, PICKLE_REPO)
        assert job["status"] == "failed" and "load without running code" in job["error"]

    def test_the_same_add_again_asks_nothing(self, client, auth, live, monkeypatch):
        first = self._add(client, auth, ONNX_REPO)["model"]

        def no_second(*_a, **_k):
            raise AssertionError("the Hub was asked for a model already held")

        monkeypatch.setattr(hfm.HuggingFaceModels, "plan", no_second)
        again = acquire(client, auth, SOURCE, ONNX_REPO)
        assert again.status_code == 200
        assert again.get_json()["model"]["id"] == first["id"]

    def _shared_guest_auth(self, db):
        from utk_curio.backend import config
        from utk_curio.backend.app.users.models import User, UserSession

        guest = User(username=config.CURIO_SHARED_GUEST_USERNAME, name="Guest",
                     email="guest@test.com", is_guest=True)
        db.session.add(guest)
        db.session.flush()
        db.session.add(UserSession(user_id=guest.id, token="guest-models"))
        db.session.commit()
        return {"Authorization": "Bearer guest-models"}

    def test_a_hosted_guest_is_refused_any_model_before_any_download(self, client, db, live, monkeypatch):
        """#623: every guest on a --deploy instance is one account on one
        disk, so a guest adds no model, whatever its runtime needs."""
        from utk_curio.backend import config

        monkeypatch.setattr(config, "CURIO_NO_AUTH", False)
        fetched = []
        monkeypatch.setattr(hfm.HuggingFaceModels, "file_url",
                            lambda self, plan, path: fetched.append(path) or f"{self.base}/x")
        job = self._add(client, self._shared_guest_auth(db), ONNX_REPO)
        assert job["status"] == "failed", job
        assert "guest" in job["error"] and fetched == []

    def test_the_local_guest_still_adds_one(self, client, db, live, monkeypatch):
        """Without --deploy the shared guest is the one local user."""
        from utk_curio.backend import config

        monkeypatch.setattr(config, "CURIO_NO_AUTH", True)
        job = self._add(client, self._shared_guest_auth(db), ONNX_REPO)
        assert job["status"] == "completed", job

    def test_a_refresh_replaces_the_model_and_keeps_its_id(self, app, client, auth, live, user_and_token):
        """#623: a refresh used to add a second copy under a new id, and keep
        every earlier one; a node naming the first id kept the stale files."""
        from utk_curio.backend.app.model_catalog.infrastructure import storage as model_storage

        first = self._add(client, auth, ONNX_REPO)["model"]
        res = acquire(client, auth, SOURCE, ONNX_REPO, refresh=True)
        assert res.status_code == 202, res.get_data(as_text=True)
        again = wait_for(client, auth, res.get_json()["jobId"], timeout=60)
        assert again["status"] == "completed", again
        assert again["model"]["id"] == first["id"]
        listed = client.get("/api/models/catalog", headers=auth).get_json()["items"]
        downloaded = [item for item in listed if item.get("origin") == "downloaded"]
        assert [item["id"] for item in downloaded] == [first["id"]]
        user, _token = user_and_token
        from utk_curio.backend.app.projects.services import _user_dir_key

        folders = [p.name for p in model_storage.user_models_dir(_user_dir_key(user)).iterdir()
                   if not p.name.startswith(".")]
        assert len(folders) == 1, folders

    def test_a_search_row_says_it_is_held(self, client, auth, live):
        model = self._add(client, auth, ONNX_REPO)["model"]
        rows = client.get(f"/api/discovery/sources/{SOURCE}/search?q=segformer", headers=auth).get_json()["resources"]
        row = next(r for r in rows if r["resourceId"] == ONNX_REPO)
        assert row["alreadyHeldModelId"] == model["id"] and row["alreadyHeldDatasetId"] is None

    def test_a_describe_says_what_an_add_fetches(self, client, auth, live):
        row = client.get(f"/api/discovery/sources/{SOURCE}/resources/{PICKLE_REPO}", headers=auth).get_json()
        assert "load without running code" in row["extra"]["cannotAdd"]
        row = client.get(f"/api/discovery/sources/{SOURCE}/resources/{ONNX_REPO}", headers=auth).get_json()
        assert row["extra"]["runtime"] == "onnx" and "onnx/model.onnx" in row["extra"]["files"]

    def test_a_bad_repo_id_is_refused_before_any_job(self, client, auth, live):
        res = acquire(client, auth, SOURCE, "../../etc/passwd")
        assert res.status_code == 404

    def test_parameters_are_refused(self, client, auth, live):
        res = acquire(client, auth, SOURCE, ONNX_REPO, parameters={"area": {"box": [0, 0, 1, 1]}})
        assert res.status_code in (400, 422)


class TestItIsNotData:
    def test_the_federated_search_leaves_it_out(self, client, auth, live):
        body = client.get("/api/discovery/search?q=segformer", headers=auth).get_json()
        assert SOURCE not in {leg["sourceId"] for leg in body["sources"]}
        assert all(row["sourceId"] != SOURCE for row in body["resources"])

    def test_no_agent_tool_offers_it(self, app, shipped_root):
        from utk_curio.backend.app.agents.application import tools

        listing = tools._discovery_service().list_catalog()["sources"]
        row = next(s for s in listing if s["dirName"] == SOURCE)
        assert row["kind"] == "model"
        assert SOURCE not in {s["dirName"] for s in tools._portal_rows(listing)}


class TestATokenWhereTheHubAsks:
    def test_a_refusal_says_to_add_a_token(self, tmp_path):
        from utk_curio.backend.app.discovery.application.model_acquire import ModelAcquire

        class Refusing:
            def download(self, url, sink, **kwargs):
                raise DiscoveryTransportError("huggingface.co answered 401")

        provider = _provider()
        plan = provider.plan(ONNX_REPO)
        provider.transport = Refusing()
        acquire_ = ModelAcquire(user_key="alice", provider_for=lambda m: provider, models=lambda: None)
        with pytest.raises(CredentialRequired, match="Hugging Face token"):
            acquire_._fetch(provider, plan, tmp_path, progress=None, stage=None, cancelled=None)


def test_labels_and_input_come_from_the_repo_configs():
    from utk_curio.backend.app.discovery.application.model_acquire import labels_of, onnx_input

    assert labels_of({"id2label": {"1": "b", "0": "a"}}) == ["a", "b"]
    assert labels_of({"id2label": {"0": "a", "2": "c"}}) == []
    assert onnx_input({"size": {"height": 256, "width": 320}, "rescale_factor": 0.5, "do_normalize": False}) == {
        "width": 320, "height": 256, "dtype": "float32", "layout": "NCHW", "scale": 0.5,
    }
    assert onnx_input({"size": {"shortest_edge": 224}})["width"] == 224
