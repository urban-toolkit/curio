"""Hugging Face models: a model source, searched like a portal, added to the
Model Catalog as a model package in the user's store.

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
#: The package whose node the source names for the models it adds, and the
#: package that node's code calls.
DDRNET_ID = "model.curio.ddrnet23-slim"
DDRNET_DIR = f"{DDRNET_ID}@1"
SEGMENTATION_DIR = "curio.segmentation@1"


def _ddrnet_code(model_id: str) -> str:
    """DDRNet23-Slim's node's code, its ``curio_load_model`` call naming *model_id*."""
    code = (Path(__file__).resolve().parents[4] / "packages" / DDRNET_DIR / "sources" / "image-segmentation.py").read_text(
        encoding="utf-8")
    return code.replace(f'curio_load_model("{DDRNET_ID}")', f'curio_load_model("{model_id}")')


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
def live(app, shipped_root, fixture_corpus):
    """The recorded Hub, and the test's own store, which downloads go to."""
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


class TestItLandsAsAModelPackage:
    """An added Hugging Face model is a model package in the user's store: its
    files under ``models/``, its ``model`` block written from the repo's
    configs, one Image Segmentation node, the one the source's manifest names
    (DDRNet23-Slim's), its code naming the model, the Segmentation package its
    code calls, which the add brings, and its libraries installed by the
    packages' own path. It replaces the folder the Model Catalog kept
    downloads in."""

    def _add(self, client, auth, repo):
        res = acquire(client, auth, SOURCE, repo)
        assert res.status_code == 202, res.get_data(as_text=True)
        job = wait_for(client, auth, res.get_json()["jobId"], timeout=60)
        return job

    @staticmethod
    def _key(user) -> str:
        from utk_curio.backend.app.projects.services import _user_dir_key

        return _user_dir_key(user)

    def _package(self, user, model_id: str):
        """The model package's folder in *user*'s store, and its manifest."""
        folder = self._package_folder(user, f"{model_id}@1")
        return folder, json.loads((folder / "manifest.json").read_text(encoding="utf-8"))

    def _package_folder(self, user, dir_name: str) -> Path:
        """The folder of *dir_name* in *user*'s store."""
        from utk_curio.backend.app.packages.repositories.store import package_dir

        return package_dir(self._key(user), dir_name)

    @staticmethod
    def _listed(client, auth, model_id: str) -> dict:
        """The Model Catalog's row for *model_id*: the account's model packages,
        as the packages service lists them."""
        resp = client.get("/api/packages?kind=model", headers=auth)
        assert resp.status_code == 200, resp.get_data(as_text=True)
        rows = {row["packageId"]: row for row in resp.get_json()["packages"]}
        assert model_id in rows, sorted(rows)
        return rows[model_id]

    def test_an_onnx_model_becomes_a_model_package_with_its_labels_and_input(self, client, auth, live, user_and_token):
        job = self._add(client, auth, ONNX_REPO)
        assert job["status"] == "completed", job
        assert job["stageMessage"] == "Added to your Model Catalog" and job["dataset"] is None
        model = job["model"]
        assert model["id"].startswith("imported.x") and model["dirName"] == f"{model['id']}@1"
        block = self._listed(client, auth, model["id"])["model"]
        assert block["runtime"] == "onnx" and block["downloadsOnFirstUse"] is False
        assert len(block["labels"]) == 150 and "wall" in block["labels"]
        assert {key: block["input"][key] for key in ("width", "height", "dtype")} == {
            "width": 512, "height": 512, "dtype": "float32"}
        assert block["discoverySource"]["resourceId"] == ONNX_REPO

        user, _ = user_and_token
        folder, manifest = self._package(user, model["id"])
        assert (manifest["id"], manifest["kind"], manifest["license"]) == (model["id"], "model", "MIT")
        block = manifest["model"]
        assert (block["type"], block["runtime"], block["entry"]) == (
            "semantic-segmentation", "onnx", "models/onnx/model.onnx")
        assert (folder / block["entry"]).is_file() and (folder / "models" / "config.json").is_file()
        assert block["input"]["mean"] and block["input"]["std"]
        assert block["sizeBytes"] == sum(path.stat().st_size for path in (folder / "models").rglob("*") if path.is_file())
        assert block["discoverySource"]["resourceId"] == ONNX_REPO
        assert manifest["dependencies"]["python"] == {"onnxruntime": ">=1.17"}
        assert (folder / "integrity.json").is_file()
        # Its node is the one the source names, DDRNet23-Slim's, field for
        # field, with its code naming this model, and its package names the
        # package that code calls, which the add brought into the store.
        node = json.loads((Path(__file__).resolve().parents[4] / "packages" / DDRNET_DIR / "manifest.json")
                          .read_text(encoding="utf-8"))
        [template] = manifest["templates"]
        assert template == node["templates"][0]
        assert (template["id"], template["label"], template["source"]) == (
            "image-segmentation", "Image Segmentation", "sources/image-segmentation.py")
        assert (folder / template["source"]).read_text(encoding="utf-8") == _ddrnet_code(model["id"])
        assert manifest["dependencies"]["packages"] == node["dependencies"]["packages"] == {SEGMENTATION_DIR: "*"}
        segmentation = self._package_folder(user, SEGMENTATION_DIR)
        assert (segmentation / "sources" / "semantic_segmentation.py").is_file()

    def test_its_node_opens_with_ddrnets_code_naming_it(self, client, auth, live):
        """The starters the canvas fills a fresh node from: the package's Image
        Segmentation node loads the model by its id and segments with the
        Segmentation package's ``segment_images``, as DDRNet23-Slim's does."""
        model = self._add(client, auth, ONNX_REPO)["model"]
        starters = client.get("/starters", headers=auth).get_json()
        [starter] = [s for s in starters if s["type"] == f"{model['id']}/image-segmentation@1"]
        assert starter["name"] == "image-segmentation"
        assert starter["code"] == _ddrnet_code(model["id"])
        assert f'model = curio_load_model("{model["id"]}")' in starter["code"]
        assert "return segment_images(input_0, model, curio_derived_file, classes=classes)" in starter["code"]

    def test_an_added_model_runs_in_its_node(self, app, client, auth, live, user_and_token, tmp_path):
        """The whole route: what an add writes is what the backend resolves for
        a run of its node from the user's store, the model's folder and the
        modules the node is handed (the Segmentation package's), and the
        node's own code runs on them as the sandbox runs it, on two of example
        10's photos. The graph is the synthetic stand-in, so the classes are
        noise; their shares still have to cover the image."""
        import importlib.util

        from utk_curio.backend.app.packages.service import modules_for_node, resolve_model_dirs
        from utk_curio.sandbox.util.catalog_helpers import CurioModel
        from utk_curio.sandbox.util.collections import make_collection_helpers
        from utk_curio.sandbox.util.input_names import call_as_node
        from utk_curio.sandbox.util.package_modules import importable
        from utk_curio.sandbox.util.staging import stage_package_modules

        model = self._add(client, auth, ONNX_REPO)["model"]
        user, _ = user_and_token
        key = self._key(user)
        folder = resolve_model_dirs(key, [model["id"]])[model["id"]]
        handed = modules_for_node(key, f"{model['id']}/image-segmentation")
        assert handed == {
            "root": str(self._package_folder(user, SEGMENTATION_DIR) / "sources"), "names": ["semantic_segmentation"],
        }, handed
        repo = Path(__file__).resolve().parents[4]
        sample = "data.curio.mapillary-sample"
        index = repo / "datasets" / f"{sample}@1" / "data" / "index.parquet"
        storage = repo / "docs" / "examples" / "data" / "storage"
        helpers = make_collection_helpers(
            lambda _id: str(index), {sample: {"kind": "images", "root": str(storage)}}, str(tmp_path / "media")
        )
        photos = helpers["curio_load_collection"](sample).head(2)
        code = (self._package_folder(user, model["dirName"]) / "sources" / "image-segmentation.py").read_text(
            encoding="utf-8")
        run = tmp_path / "run"
        run.mkdir()
        staged = stage_package_modules(handed, str(run))
        namespace = {
            "curio_load_model": lambda model_id: CurioModel(model_id, folder),
            "curio_derived_file": helpers["curio_derived_file"],
        }
        with importable(str(run / staged["root"]), staged["names"]):
            assert importlib.util.find_spec("semantic_segmentation") is not None
            out = call_as_node("\n".join("    " + line for line in code.splitlines()), namespace, photos, [0])
        labels = self._listed(client, auth, model["id"])["model"]["labels"]
        shares = out[[f"{label}_pct" for label in labels]]
        assert shares.sum(axis=1).between(99.5, 100.5).all()
        assert out["dominant_class"].isin(labels).all()
        assert out["overlay_url"].notna().all() and out["segment_error"].isna().all()

    def test_a_transformers_checkpoint(self, client, auth, live, user_and_token):
        """Its checkpoint is a folder of its own under ``models/``, which its
        model block names."""
        model = self._add(client, auth, TRANSFORMERS_REPO)["model"]
        block = self._listed(client, auth, model["id"])["model"]
        assert block["runtime"] == "transformers" and block["license"] == "mit"
        assert len(block["labels"]) == 150
        user, _ = user_and_token
        folder, manifest = self._package(user, model["id"])
        assert manifest["model"]["entry"] == "models/checkpoint"
        assert (folder / "models" / "checkpoint" / "config.json").is_file()

    def test_its_libraries_install_by_the_packages_path(self, client, auth, live, pip):
        """As a package's dependencies.python installs: the package's folder
        name, its manifest's declaration, so the libraries go where node code
        finds them."""
        job = self._add(client, auth, TRANSFORMERS_REPO)
        model = job["model"]
        assert model["dependencies"] == ["safetensors", "torch", "transformers"]
        assert len(pip) == 1
        assert pip[0]["dir_name"] == model["dirName"] and pip[0]["backend"] is None
        assert pip[0]["deps"]["torch"] == ">=2.6"
        assert job["dependencies"] == {"importErrors": {}}

    def test_an_onnx_model_declares_onnxruntime_and_installs_it(self, client, auth, live, pip):
        """onnxruntime is not one of Curio's own libraries: an ONNX model's
        package declares it, and it installs by the packages' path, as a
        Transformers model's libraries do."""
        job = self._add(client, auth, ONNX_REPO)
        model = job["model"]
        assert model["dependencies"] == ["onnxruntime"]
        assert [(call["dir_name"], call["deps"]) for call in pip] == [(model["dirName"], {"onnxruntime": ">=1.17"})]
        assert job["dependencies"] == {"importErrors": {}}

    @pytest.mark.parametrize("repo, library", [(TRANSFORMERS_REPO, "torch"), (ONNX_REPO, "onnxruntime")])
    def test_someone_who_may_not_install_is_refused_before_any_download(
        self, client, auth, live, pip, monkeypatch, repo, library,
    ):
        from utk_curio.backend.app.packages import service as packages_service

        monkeypatch.setattr(packages_service, "model_library_refusal",
                            lambda user: "this Curio does not install packages for guests")
        fetched = []
        monkeypatch.setattr(hfm.HuggingFaceModels, "file_url",
                            lambda self, plan, path: fetched.append(path) or f"{self.base}/x")
        job = self._add(client, auth, repo)
        assert job["status"] == "failed" and "does not install packages for guests" in job["error"]
        assert library in job["error"] and fetched == [] and pip == []

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
        """Without --deploy the shared guest is the one local user, and the
        model package lands in the guest's store."""
        from utk_curio.backend import config
        from utk_curio.backend.app.common.user_storage import GUEST_KEY
        from utk_curio.backend.app.packages.repositories.store import package_dir

        monkeypatch.setattr(config, "CURIO_NO_AUTH", True)
        job = self._add(client, self._shared_guest_auth(db), ONNX_REPO)
        assert job["status"] == "completed", job
        assert (package_dir(GUEST_KEY, job["model"]["dirName"]) / "manifest.json").is_file()

    def test_a_refresh_replaces_the_model_and_keeps_its_id(self, app, client, auth, live, user_and_token):
        """#623: a refresh used to add a second copy under a new id, and keep
        every earlier one; a node naming the first id kept the stale files.
        It installs over the package, under its id."""
        from utk_curio.backend.app.packages.service import held_model_packages

        first = self._add(client, auth, ONNX_REPO)["model"]
        res = acquire(client, auth, SOURCE, ONNX_REPO, refresh=True)
        assert res.status_code == 202, res.get_data(as_text=True)
        again = wait_for(client, auth, res.get_json()["jobId"], timeout=60)
        assert again["status"] == "completed", again
        assert again["model"]["id"] == first["id"]
        # The account's own model packages: one, from that row.
        listed = client.get("/api/packages?kind=model", headers=auth).get_json()["packages"]
        downloaded = [row for row in listed if (row["model"].get("discoverySource") or {}).get("sourceId")]
        assert [row["packageId"] for row in downloaded] == [first["id"]]
        user, _token = user_and_token
        held = [
            listed.folder.name for listed in held_model_packages(self._key(user))
            if (listed.manifest.model.discovery_source or {}).get("resourceId") == ONNX_REPO
        ]
        assert held == [f"{first['id']}@1"], held

    def test_an_added_model_is_dated_by_the_record_clock(self, client, auth, live):
        """An e2e test that photographs catalog ages sets the record clock to its
        browser's date (``/api/testing/clock``); what it adds carries it."""
        from datetime import datetime, timedelta, timezone

        from utk_curio.backend.app.common import record_clock

        calendar = datetime(2026, 10, 7, 6, 0, tzinfo=timezone.utc)
        record_clock.set_now(calendar)
        try:
            model = self._add(client, auth, ONNX_REPO)["model"]
        finally:
            record_clock.set_now(None)
        row = self._listed(client, auth, model["id"])
        created = datetime.fromisoformat(row["createdAt"].replace("Z", "+00:00"))
        assert calendar <= created < calendar + timedelta(minutes=1), row["createdAt"]

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


class TestTheNodeAModelGets:
    def test_the_shipped_source_names_ddrnets_node(self):
        """The node a model this source adds gets is named in its manifest,
        never in Curio's code: DDRNet23-Slim's Image Segmentation."""
        assert _manifest().provider.options["node"] == f"{DDRNET_ID}/image-segmentation"

    @pytest.mark.parametrize("node, refusal", [
        (None, "names no node for the models it adds"),
        ("model.test.nowhere/segment", "the catalog has no package model.test.nowhere"),
        (f"{DDRNET_ID}/no-such-node", "has no node no-such-node with code of its own"),
    ], ids=["no-node", "no-package", "no-template"])
    def test_a_source_whose_node_the_catalog_lacks_adds_no_model_and_fetches_nothing(self, app, node, refusal):
        import dataclasses

        from utk_curio.backend.app.discovery.application.model_acquire import ModelAcquire

        manifest = _manifest()
        options = {key: value for key, value in manifest.provider.options.items() if key != "node"}
        if node is not None:
            options["node"] = node
        source = dataclasses.replace(manifest, provider=dataclasses.replace(manifest.provider, options=options))

        class Unasked:
            def plan(self, repo):
                raise AssertionError(f"the Hub was asked for {repo}, which this source gives no node")

        acquire_ = ModelAcquire(user=None, user_key="guest", provider_for=lambda m: Unasked())
        with pytest.raises(CapabilityUnsupported, match=refusal):
            acquire_.acquire(source, ONNX_REPO)


#: The node Curio wrote for a segmentation model it downloaded before a
#: source named one, as main's ``domain/default_cells.py`` held it: no
#: ``source``, so a node of it opened with the ``curio_segment`` call Curio
#: wrote for it.
MAINS_NODE = {
    "behavior": "code",
    "category": "computation",
    "description": (
        "Label every pixel of each image with a Model Catalog model: drag a model onto the node to choose it. "
        "Input: a collection's rows, each with a path (Data Loading on street-level images). Output: the same "
        "rows with one column per class asked for (its share of the image's pixels, in percent), "
        "dominant_class, dominant_pct and an overlay_url a Simple View shows."
    ),
    "editor": "code",
    "engine": "python",
    "hasCode": True,
    "hasGrammar": False,
    "hasWidgets": False,
    "iconRef": "fa-solid:wand-magic-sparkles",
    "id": "image-segmentation",
    "inputPorts": [{"cardinality": "1", "types": ["GEODATAFRAME", "DATAFRAME"]}],
    "label": "Image Segmentation",
    "outputPorts": [{"cardinality": "1", "types": ["GEODATAFRAME"]}],
    "paletteOrder": 0,
}
#: The id of a model downloaded before its source named its node.
OLD_MODEL_ID = "imported.x0123456789ab"


class TestADownloadFromBeforeItsSourceNamedANode:
    """A segmentation model downloaded before this source named the node a
    model gets kept the node Curio wrote then, with no code of its own, and
    named no package. A read of the store, the seeder's pass that refreshes a
    catalog copy the catalog moved on from, brings it to the node a download
    gets now: DDRNet23-Slim's, its code naming the model, and the
    Segmentation package that code imports. Nothing else of it changes, it is
    done once, and a package made otherwise is left as it is."""

    @staticmethod
    def _key(user) -> str:
        from utk_curio.backend.app.projects.services import _user_dir_key

        return _user_dir_key(user)

    @staticmethod
    def _as_main_built_it(user_key: str, tmp_path: Path, *, downloaded: bool = True, node: dict = MAINS_NODE) -> Path:
        """The package main's download made of an ONNX export, installed as
        it installed one: its files under ``models/``, its manifest, and no
        code of its own, through the store's archive install
        (``install_downloaded_model``, given no sources)."""
        import shutil

        from utk_curio.backend.app.packages.repositories.store import package_dir
        from utk_curio.backend.app.packages.service import install_downloaded_model

        files = tmp_path / "download" / "models"
        (files / "onnx").mkdir(parents=True)
        shutil.copyfile(FIXTURES / "huggingface-models" / "synthetic-segmentation.onnx", files / "onnx" / "model.onnx")
        (files / "config.json").write_text(json.dumps({"id2label": {"0": "wall", "1": "sky"}}), encoding="utf-8")
        block = {
            "type": "semantic-segmentation",
            "runtime": "onnx",
            "labels": ["wall", "sky"],
            "license": "other",
            "publisher": "Xenova",
            "homepage": f"https://huggingface.co/{ONNX_REPO}",
            "sizeBytes": sum(path.stat().st_size for path in files.rglob("*") if path.is_file()),
            "entry": "models/onnx/model.onnx",
            "input": {"width": 512, "height": 512, "dtype": "float32", "layout": "NCHW", "scale": 1 / 255,
                      "mean": [0.485, 0.456, 0.406], "std": [0.229, 0.224, 0.225]},
        }
        if downloaded:
            block["discoverySource"] = {
                "sourceId": SOURCE, "sourceName": "Hugging Face models", "resourceId": ONNX_REPO,
                "revision": "0" * 40, "fetchedAt": "2026-11-01T12:00:00Z",
            }
        install_downloaded_model(user_key, files, {
            "id": OLD_MODEL_ID,
            "kind": "model",
            "name": ONNX_REPO,
            "version": "1.0.0",
            "compatibility": {"major": 1},
            "createdAt": "2026-11-01T12:00:00Z",
            "description": f"{ONNX_REPO} from Hugging Face, commit 000000000000.",
            "publisher": "Xenova",
            "license": "MIT",
            "permissions": [],
            "dependencies": {"js": {}, "packages": {}, "python": {"onnxruntime": ">=1.17"}},
            "model": block,
            "templates": [dict(node)],
        })
        return package_dir(user_key, f"{OLD_MODEL_ID}@1")

    @staticmethod
    def _files(folder: Path) -> dict[str, bytes]:
        return {path.relative_to(folder).as_posix(): path.read_bytes() for path in sorted(folder.rglob("*"))
                if path.is_file()}

    def test_a_read_of_the_store_brings_it_to_the_node_a_download_gets(
            self, client, auth, live, user_and_token, tmp_path):
        from utk_curio.backend.app.packages.repositories.archive import integrity_mismatch
        from utk_curio.backend.app.packages.repositories.store import package_dir

        user, _ = user_and_token
        key = self._key(user)
        folder = self._as_main_built_it(key, tmp_path)
        before = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        weights = {rel: data for rel, data in self._files(folder).items() if rel.startswith("models/")}
        assert not (folder / "sources").exists() and not package_dir(key, SEGMENTATION_DIR).exists()

        listed = client.get("/api/packages?kind=model", headers=auth)
        assert listed.status_code == 200, listed.get_data(as_text=True)

        after = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        ddrnet = json.loads((Path(__file__).resolve().parents[4] / "packages" / DDRNET_DIR / "manifest.json")
                            .read_text(encoding="utf-8"))
        assert after["templates"] == ddrnet["templates"]
        assert (folder / "sources" / "image-segmentation.py").read_text(encoding="utf-8") == _ddrnet_code(OLD_MODEL_ID)
        assert after["dependencies"] == {**before["dependencies"], "packages": {SEGMENTATION_DIR: "*"}}
        rest = ("templates", "dependencies")
        assert {k: v for k, v in after.items() if k not in rest} == {k: v for k, v in before.items() if k not in rest}
        assert {rel: data for rel, data in self._files(folder).items() if rel.startswith("models/")} == weights
        assert integrity_mismatch(folder) is None
        assert (package_dir(key, SEGMENTATION_DIR) / "sources" / "semantic_segmentation.py").is_file()
        # A new node of it opens with that code, as one of a model added now does.
        starters = client.get("/starters", headers=auth).get_json()
        [starter] = [s for s in starters if s["type"] == f"{OLD_MODEL_ID}/image-segmentation@1"]
        assert starter["code"] == _ddrnet_code(OLD_MODEL_ID)

    def test_it_is_brought_once(self, client, auth, live, user_and_token, tmp_path):
        folder = self._as_main_built_it(self._key(user_and_token[0]), tmp_path)
        assert client.get("/api/packages", headers=auth).status_code == 200
        brought = self._files(folder)
        written = [folder / "manifest.json", folder / "sources" / "image-segmentation.py"]
        stamps = [path.stat().st_mtime_ns for path in written]

        assert client.get("/api/packages", headers=auth).status_code == 200

        assert self._files(folder) == brought
        assert [path.stat().st_mtime_ns for path in written] == stamps

    @pytest.mark.parametrize("made", ["with-code-of-its-own", "not-downloaded", "of-another-node"])
    def test_a_package_made_otherwise_is_left_as_it_is(self, client, auth, live, user_and_token, tmp_path, made):
        folder = self._as_main_built_it(
            self._key(user_and_token[0]), tmp_path, downloaded=made != "not-downloaded",
            node={**MAINS_NODE, "id": "segment-photos"} if made == "of-another-node" else MAINS_NODE,
        )
        if made == "with-code-of-its-own":
            (folder / "sources").mkdir()
            (folder / "sources" / "image-segmentation.py").write_text("return input_0\n", encoding="utf-8")
        kept = self._files(folder)

        assert client.get("/api/packages", headers=auth).status_code == 200

        assert self._files(folder) == kept


class TestATokenWhereTheHubAsks:
    def test_a_refusal_says_to_add_a_token(self, tmp_path):
        from utk_curio.backend.app.discovery.application.model_acquire import ModelAcquire

        class Refusing:
            def download(self, url, sink, **kwargs):
                raise DiscoveryTransportError("huggingface.co answered 401")

        provider = _provider()
        plan = provider.plan(ONNX_REPO)
        provider.transport = Refusing()
        acquire_ = ModelAcquire(user=None, user_key="alice", provider_for=lambda m: provider)
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


# ── file names ─────────────────────────────────────────────────────────────


def _info(*files, architectures=None):
    """A repo's ``?blobs=true`` answer with the two configs and *files*."""
    info = {
        "id": "a/b", "sha": "0" * 40,
        "siblings": [{"rfilename": f, "size": 1} for f in ("config.json", "preprocessor_config.json", *files)],
    }
    if architectures:
        info["config"] = {"architectures": architectures}
    return info


class TestAFileStaysInTheModelsFolder:
    @pytest.mark.parametrize("graph", [
        "../model.onnx", "onnx/../../model.onnx", "/etc/model.onnx", "onnx\\model.onnx",
    ])
    def test_a_graph_whose_name_would_leave_it_is_refused(self, graph):
        with pytest.raises(CapabilityUnsupported, match="will not write"):
            _provider().plan("a/b", _info(graph))

    def test_weights_whose_name_holds_a_backslash_are_refused(self):
        info = _info("..\\model.safetensors", architectures=["SegformerForSemanticSegmentation"])
        with pytest.raises(CapabilityUnsupported, match="will not write"):
            _provider().plan("a/b", info)

    def test_a_download_never_lands_outside_it(self, tmp_path):
        from utk_curio.backend.app.discovery.application.model_acquire import ModelAcquire

        class Writes:
            def download(self, url, sink, **kwargs):
                sink(b"onnx")

        provider = _provider()
        provider.transport = Writes()
        acquire_ = ModelAcquire(user=None, user_key="alice", provider_for=lambda m: provider)
        target = tmp_path / "model" / "files"
        for path in ("../outside/model.onnx", str(tmp_path / "outside" / "model.onnx")):
            plan = hfm.ModelPlan(repo="a/b", revision="0" * 40, runtime="onnx",
                                 files=((path, 4),), graph=path, license="")
            with pytest.raises(CapabilityUnsupported, match="will not write"):
                acquire_._fetch(provider, plan, target, progress=None, stage=None, cancelled=None)
        assert not (tmp_path / "model" / "outside").exists()
        assert not (tmp_path / "outside").exists()
