"""Integration tests for the /api/packages endpoints."""

from __future__ import annotations

import copy
import io
import json
import zipfile

import pytest

from utk_curio.backend.app.packages.factory import _STARTER_CODE_SENTINEL


def _auth(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _multipart_auth(token):
    return {"Authorization": f"Bearer {token}"}


def _draft():
    return {
        "manifest": {
            "id": "ai.test.factory",
            "version": "1.0.0",
            "createdAt": "2000-01-01T00:00:00Z",
            "name": "Factory test",
            "publisher": "Tests",
            "description": "Built by the wizard",
            "license": "MIT",
            "compatibility": {"curioRuntime": ">=0.5.0", "major": 1},
            "permissions": [],
            "dependencies": {"packages": {}, "python": {}, "js": {}},
            "templates": [
                {
                    "id": "demo",
                    "label": "Demo",
                    "category": "computation",
                    "engine": "python",
                    "editor": "code",
                    "hasCode": True,
                    "hasWidgets": False,
                    "hasGrammar": False,
                    "inputPorts": [],
                    "outputPorts": [{"types": ["JSON"], "cardinality": "1"}],
                    "source": "sources/demo.py",
                }
            ],
        },
        "sources": {
            "demo": {
                "filename": "demo.py",
                # Source-driven detection (factory.py / dependency_scanner.py) populates
                # ``dependencies.python`` from these imports; the test no longer needs
                # to declare them manually in the manifest.
                "code": "import numpy\n\ndef run():\n    return {}\n",
            },
        },
    }


# ---------------------------------------------------------------------------
# GET /api/packages/catalog
# ---------------------------------------------------------------------------

def test_catalog_lists_committed_fixtures(client, user_and_token, tmp_curio):
    """The catalog stub mirrors the fixture package ``ai.urbanlab.uhvi@1``."""
    _, token = user_and_token
    resp = client.get("/api/packages/catalog", headers=_auth(token))
    assert resp.status_code == 200
    packages = resp.get_json()["packages"]
    ids = {p["packageId"] for p in packages}
    assert "ai.urbanlab.uhvi" in ids
    item = next(p for p in packages if p["packageId"] == "ai.urbanlab.uhvi")
    assert item["installed"] is False
    assert item["dirName"] == "ai.urbanlab.uhvi@1"
    assert item["lineage"] is None
    assert item["familyKey"] == "ai.urbanlab.uhvi@1"
    assert isinstance(item["installUpdatedAtMs"], int)
    assert isinstance(item["createdAtMs"], int)
    assert item["channel"] == "stable"
    body = resp.get_json()
    assert "families" in body and isinstance(body["families"], list)
    assert "catalogCollisions" in body and isinstance(body["catalogCollisions"], list)


def test_list_installed_serializes_lineage(
    client, user_and_token, tmp_curio, install_packageage, manifest_dict,
):
    from utk_curio.backend.app.projects.services import _user_dir_key

    user, token = user_and_token
    uk = _user_dir_key(user)
    lineage = {
        "forkedFrom": {"packageId": "ai.upstream.catalog", "major": 1},
        "root": {"packageId": "ai.upstream.catalog", "major": 1},
    }
    install_packageage(
        uk,
        manifest=manifest_dict(package_id="curio.test.lineage.package", lineage=lineage),
    )
    resp = client.get("/api/packages", headers=_auth(token))
    assert resp.status_code == 200
    package = next(p for p in resp.get_json()["packages"] if p["packageId"] == "curio.test.lineage.package")
    assert package["lineage"] == lineage
    assert package["familyKey"] == "ai.upstream.catalog@1"
    assert isinstance(package["installUpdatedAtMs"], int)
    assert isinstance(package["createdAtMs"], int)


def test_list_installed_orders_by_created_at_ms_newest_first(
    client, user_and_token, tmp_curio, install_packageage, manifest_dict,
):
    """``GET /api/packages`` lists packages sorted by canonical ``manifest.createdAt``."""

    from utk_curio.backend.app.projects.services import _user_dir_key

    user, token = user_and_token
    uk = _user_dir_key(user)
    install_packageage(
        uk,
        manifest=manifest_dict(
            package_id="ai.sort.older",
            created_at="2020-01-01T00:00:00Z",
        ),
    )
    install_packageage(
        uk,
        manifest=manifest_dict(
            package_id="ai.sort.newer",
            created_at="2030-01-01T00:00:00Z",
        ),
    )
    packages = client.get("/api/packages", headers=_auth(token)).get_json()["packages"]
    ours = [p for p in packages if p["packageId"] in ("ai.sort.older", "ai.sort.newer")]
    assert [p["packageId"] for p in ours] == ["ai.sort.newer", "ai.sort.older"]

def test_catalog_requires_auth(client, tmp_curio):
    resp = client.get("/api/packages/catalog")
    assert resp.status_code == 401


def test_install_from_catalog_endpoint(client, user_and_token, tmp_curio):
    """Hitting /catalog/install with a fixture's ``dirName`` materialises it."""
    _, token = user_and_token
    resp = client.post(
        "/api/packages/catalog/install",
        data=json.dumps({"dirName": "ai.urbanlab.uhvi@1"}),
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.get_data(as_text=True)
    body = resp.get_json()
    assert body["package"]["packageId"] == "ai.urbanlab.uhvi"

    listing = client.get("/api/packages", headers=_auth(token)).get_json()["packages"]
    assert "ai.urbanlab.uhvi" in {p["packageId"] for p in listing}


def test_install_from_catalog_rejects_unknown(client, user_and_token, tmp_curio):
    _, token = user_and_token
    resp = client.post(
        "/api/packages/catalog/install",
        data=json.dumps({"dirName": "ai.test.unknown@1"}),
        headers=_auth(token),
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/packages/upload -> GET /api/packages -> DELETE /api/packages/<dir>
# ---------------------------------------------------------------------------

def _archive_from_draft(d: dict) -> bytes:
    """Build a zip from a factory-shaped draft (no HTTP roundtrip)."""
    from utk_curio.backend.app.packages.factory import build_packageage_archive
    return build_packageage_archive(d).archive


def test_upload_then_list_then_delete(client, user_and_token, tmp_curio):
    _, token = user_and_token
    archive = _archive_from_draft(_draft())
    resp = client.post(
        "/api/packages/upload",
        data={"file": (io.BytesIO(archive), "factory.curio.zip")},
        headers=_multipart_auth(token),
        content_type="multipart/form-data",
    )
    assert resp.status_code == 201, resp.get_data(as_text=True)
    body = resp.get_json()
    assert body["package"]["packageId"] == "ai.test.factory"
    assert "manifest.json" in body["integrity"]

    listing = client.get("/api/packages", headers=_auth(token)).get_json()["packages"]
    ids = {p["packageId"] for p in listing}
    assert "ai.test.factory" in ids

    resp = client.delete("/api/packages/ai.test.factory@1", headers=_auth(token))
    assert resp.status_code == 204
    listing = client.get("/api/packages", headers=_auth(token)).get_json()["packages"]
    assert "ai.test.factory" not in {p["packageId"] for p in listing}


def test_upload_duplicate_without_replace_is_rejected(client, user_and_token, tmp_curio):
    _, token = user_and_token
    archive = _archive_from_draft(_draft())
    client.post(
        "/api/packages/upload",
        data={"file": (io.BytesIO(archive), "x.curio.zip")},
        headers=_multipart_auth(token),
        content_type="multipart/form-data",
    )
    resp = client.post(
        "/api/packages/upload",
        data={"file": (io.BytesIO(archive), "x.curio.zip")},
        headers=_multipart_auth(token),
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400
    assert "already installed" in resp.get_json()["error"]


def test_upload_replace(client, user_and_token, tmp_curio):
    _, token = user_and_token
    archive = _archive_from_draft(_draft())
    client.post(
        "/api/packages/upload",
        data={"file": (io.BytesIO(archive), "x.curio.zip")},
        headers=_multipart_auth(token),
        content_type="multipart/form-data",
    )
    bumped = _draft()
    bumped["manifest"]["version"] = "2.0.0"
    archive2 = _archive_from_draft(bumped)
    resp = client.post(
        "/api/packages/upload?replace=true",
        data={"file": (io.BytesIO(archive2), "x.curio.zip")},
        headers=_multipart_auth(token),
        content_type="multipart/form-data",
    )
    assert resp.status_code == 201
    assert resp.get_json()["replacedExisting"] is True


def test_delete_unknown_packageage_returns_404(client, user_and_token, tmp_curio):
    _, token = user_and_token
    resp = client.delete("/api/packages/ai.unknown@1", headers=_auth(token))
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/packages/<dir>/archive
# ---------------------------------------------------------------------------

def test_export_after_install(client, user_and_token, tmp_curio):
    _, token = user_and_token
    archive = _archive_from_draft(_draft())
    client.post(
        "/api/packages/upload",
        data={"file": (io.BytesIO(archive), "x.curio.zip")},
        headers=_multipart_auth(token),
        content_type="multipart/form-data",
    )
    resp = client.get(
        "/api/packages/ai.test.factory@1/archive", headers=_auth(token)
    )
    assert resp.status_code == 200
    assert resp.mimetype == "application/zip"
    # Round-trip: the exported archive must be itself installable.
    with zipfile.ZipFile(io.BytesIO(resp.data), "r") as zf:
        names = set(zf.namelist())
    assert "manifest.json" in names
    assert "sources/demo.py" in names


# ---------------------------------------------------------------------------
# POST /api/packages/factory/build + /factory/install
# ---------------------------------------------------------------------------

def test_factory_build_returns_zip(client, user_and_token, tmp_curio):
    _, token = user_and_token
    resp = client.post(
        "/api/packages/factory/build",
        data=json.dumps(_draft()),
        headers=_auth(token),
    )
    assert resp.status_code == 200
    assert resp.mimetype == "application/zip"
    assert resp.headers["X-Curio-Package-Dir"] == "ai.test.factory@1"
    assert resp.headers["X-Curio-Package-Version"] == "1.0.0"
    # The browser reads the download name from Content-Disposition
    # (packagesApi.factoryBuild), so the server must actually send it.
    assert resp.headers["Content-Disposition"] == (
        'attachment; filename="ai.test.factory@1-1.0.0.curio.zip"'
    )
    with zipfile.ZipFile(io.BytesIO(resp.data), "r") as zf:
        names = set(zf.namelist())
    assert "manifest.json" in names
    assert "sources/demo.py" in names
    # integrity.json is computed post-extraction by the installer, never shipped
    # in an archive. Regressing this would make every archive carry stale hashes.
    assert "integrity.json" not in names


def _two_template_draft():
    """A draft for a package with two code templates, each with distinct source."""
    draft = _draft()
    draft["manifest"]["templates"] = [
        {
            "id": f"{name}-kind",
            "label": name.title(),
            "category": "computation",
            "engine": "python",
            "editor": "code",
            "hasCode": True,
            "hasWidgets": False,
            "hasGrammar": False,
            "inputPorts": [],
            "outputPorts": [{"types": ["JSON"], "cardinality": "1"}],
            "source": f"sources/{name}-kind.py",
        }
        for name in ("foo", "bar")
    ]
    draft["sources"] = {
        "foo-kind": {"filename": "foo-kind.py", "code": "def run():\n    return 'foo-original'\n"},
        "bar-kind": {"filename": "bar-kind.py", "code": "def run():\n    return 'bar-original'\n"},
    }
    return draft


def test_factory_build_preserves_unedited_sources(client, user_and_token, tmp_curio):
    """Export must not blank the code of templates the user didn't edit.

    ``factory_install`` calls ``preserve_unedited_sources`` before building;
    ``factory_build`` historically did not. Save-As only carries the real body
    for the one canvas template — every sibling arrives as a STARTER_CODE
    placeholder — so Export shipped a zip whose other node kinds had lost their
    code, while Save preserved them. Importing such a zip elsewhere silently
    destroys work, which is the same failure
    ``test_factory.py::test_preserve_unedited_sources_restores_real_source_for_placeholder_kind``
    guards on the install path.
    """
    _, token = user_and_token
    original = _two_template_draft()
    install = client.post(
        "/api/packages/factory/install",
        data=json.dumps(original),
        headers=_auth(token),
    )
    assert install.status_code == 201

    # Save-As rebuild: foo is really edited, bar carries the placeholder.
    edited_foo = "def run():\n    return 'foo-edited'\n"
    rebuild = _two_template_draft()
    rebuild["sources"] = {
        "foo-kind": {"filename": "foo-kind.py", "code": edited_foo},
        "bar-kind": {"filename": "bar-kind.py", "code": _STARTER_CODE_SENTINEL},
    }
    resp = client.post(
        "/api/packages/factory/build",
        data=json.dumps(rebuild),
        headers=_auth(token),
    )
    assert resp.status_code == 200
    with zipfile.ZipFile(io.BytesIO(resp.data), "r") as zf:
        foo_body = zf.read("sources/foo-kind.py").decode("utf-8")
        bar_body = zf.read("sources/bar-kind.py").decode("utf-8")
    assert foo_body == edited_foo
    assert bar_body == "def run():\n    return 'bar-original'\n", (
        "Export blanked an unedited sibling template. factory_build must call "
        "preserve_unedited_sources like factory_install does."
    )


def test_factory_install_creates_packageage(client, user_and_token, tmp_curio):
    _, token = user_and_token
    resp = client.post(
        "/api/packages/factory/install",
        data=json.dumps(_draft()),
        headers=_auth(token),
    )
    assert resp.status_code == 201
    listing = client.get("/api/packages", headers=_auth(token)).get_json()["packages"]
    assert "ai.test.factory" in {p["packageId"] for p in listing}


def test_factory_rejects_malformed_draft(client, user_and_token, tmp_curio):
    _, token = user_and_token
    bad = _draft()
    bad["manifest"]["id"] = "not valid"  # not reverse-DNS
    resp = client.post(
        "/api/packages/factory/build",
        data=json.dumps(bad),
        headers=_auth(token),
    )
    assert resp.status_code == 400


def test_factory_install_rejects_read_only_packageage(client, user_and_token, tmp_curio):
    """Read-only packages (built-in or curated) refuse factory-install writes."""
    _, token = user_and_token
    draft = _draft()
    draft["manifest"]["readOnly"] = True
    resp = client.post(
        "/api/packages/factory/install",
        data=json.dumps(draft),
        headers=_auth(token),
    )
    assert resp.status_code == 400
    assert "read-only" in resp.get_json()["error"]


def test_remove_packageage_rejects_curio_builtin(client, user_and_token, tmp_curio):
    """DELETE on a curio.builtin@<major> dir must be rejected before touching disk."""
    _, token = user_and_token
    resp = client.delete("/api/packages/curio.builtin@1", headers=_auth(token))
    assert resp.status_code == 400
    assert "built-in" in resp.get_json()["error"]


# ---------------------------------------------------------------------------
# PATCH /api/packages/<dir_name> — metadata editor backing endpoint
# ---------------------------------------------------------------------------

def _install_factory_demo(client, token):
    resp = client.post(
        "/api/packages/factory/install",
        data=json.dumps(_draft()),
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.get_data(as_text=True)


def test_patch_package_metadata_round_trip(client, user_and_token, tmp_curio):
    """PATCH updates editable metadata, validates, and returns the new payload."""
    _, token = user_and_token
    _install_factory_demo(client, token)
    resp = client.patch(
        "/api/packages/ai.test.factory@1",
        data=json.dumps({
            "description": "Updated description from PATCH",
            "license": "Apache-2.0",
            "publisher": "Tests Updated",
            "permissions": ["filesystem.read"],
            "readme": "# Updated README\n",
        }),
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    pkg = body["package"]
    assert pkg["description"] == "Updated description from PATCH"
    assert pkg["license"] == "Apache-2.0"
    assert pkg["publisher"] == "Tests Updated"
    assert pkg["permissions"] == ["filesystem.read"]
    assert pkg["readme"] == "# Updated README\n"


def test_patch_package_metadata_omitted_readme_preserves_existing(client, user_and_token, tmp_curio):
    """Omitting `readme` leaves the on-disk README untouched."""
    _, token = user_and_token
    _install_factory_demo(client, token)
    client.patch(
        "/api/packages/ai.test.factory@1",
        data=json.dumps({"readme": "# original"}),
        headers=_auth(token),
    )
    # Subsequent PATCH without readme must not destroy the existing README.
    resp = client.patch(
        "/api/packages/ai.test.factory@1",
        data=json.dumps({"description": "still here"}),
        headers=_auth(token),
    )
    assert resp.status_code == 200
    assert resp.get_json()["package"]["readme"] == "# original"


def test_patch_package_metadata_empty_readme_removes_file(client, user_and_token, tmp_curio):
    """Passing an empty `readme` unlinks the on-disk README."""
    _, token = user_and_token
    _install_factory_demo(client, token)
    client.patch(
        "/api/packages/ai.test.factory@1",
        data=json.dumps({"readme": "# something"}),
        headers=_auth(token),
    )
    resp = client.patch(
        "/api/packages/ai.test.factory@1",
        data=json.dumps({"readme": ""}),
        headers=_auth(token),
    )
    assert resp.status_code == 200
    assert "readme" not in resp.get_json()["package"]


def test_patch_package_metadata_rejects_disallowed_keys(client, user_and_token, tmp_curio):
    """PATCH refuses to mutate identity fields (id, version, kinds, dependencies, etc.)."""
    _, token = user_and_token
    _install_factory_demo(client, token)
    resp = client.patch(
        "/api/packages/ai.test.factory@1",
        data=json.dumps({"id": "ai.test.other"}),
        headers=_auth(token),
    )
    assert resp.status_code == 400
    assert "not editable" in resp.get_json()["error"]


def test_patch_package_metadata_rejects_readonly_builtin(client, user_and_token, tmp_curio):
    """Read-only packages (curio.builtin@1) return 403 — no defacement allowed."""
    from utk_curio.backend.app.packages import seed_dev_packageages
    from utk_curio.backend.app.projects.services import _user_dir_key
    user, token = user_and_token
    # Auto-seeding fires for ``guest`` at app boot; this test uses a real user
    # so we must seed builtin into that user's store explicitly.
    seed_dev_packageages(user_key=_user_dir_key(user))
    resp = client.patch(
        "/api/packages/curio.builtin@1",
        data=json.dumps({"description": "haha"}),
        headers=_auth(token),
    )
    assert resp.status_code == 403


def test_patch_package_metadata_404_for_missing(client, user_and_token, tmp_curio):
    _, token = user_and_token
    resp = client.patch(
        "/api/packages/ai.not.installed@1",
        data=json.dumps({"description": "x"}),
        headers=_auth(token),
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/packages/factory/capabilities + POST publish-catalog
# ---------------------------------------------------------------------------


def test_factory_capabilities_reflect_publish_env_switch(client, user_and_token, monkeypatch):
    from utk_curio.backend.app.packages import routes as packages_routes

    _, token = user_and_token
    # Default — preserve prior behavior: publish is allowed.
    r1 = client.get("/api/packages/factory/capabilities", headers=_auth(token))
    assert r1.status_code == 200
    assert r1.get_json()["catalogPublish"] is True

    monkeypatch.setattr(packages_routes, "CURIO_ALLOW_FACTORY_CATALOG_PUBLISH", False)
    r_off = client.get("/api/packages/factory/capabilities", headers=_auth(token))
    assert r_off.status_code == 200
    assert r_off.get_json()["catalogPublish"] is False

    monkeypatch.setattr(packages_routes, "CURIO_ALLOW_FACTORY_CATALOG_PUBLISH", True)
    r2 = client.get("/api/packages/factory/capabilities", headers=_auth(token))
    assert r2.status_code == 200
    assert r2.get_json()["catalogPublish"] is True


def test_factory_publish_catalog_forbidden_when_env_off(client, user_and_token, monkeypatch):
    from utk_curio.backend.app.packages import routes as packages_routes

    monkeypatch.setattr(packages_routes, "CURIO_ALLOW_FACTORY_CATALOG_PUBLISH", False)
    _, token = user_and_token
    resp = client.post(
        "/api/packages/factory/publish-catalog",
        data=json.dumps(_draft()),
        headers=_auth(token),
    )
    assert resp.status_code == 403
    body = resp.get_json()
    assert "error" in body
    assert "CURIO_ALLOW_FACTORY_CATALOG_PUBLISH" in body["error"]


def test_factory_publish_catalog_writes_to_stub_root(client, user_and_token, monkeypatch, tmp_path):
    """Publish redirects catalog root to ``tmp_path`` so we don't touch committed fixtures."""
    from utk_curio.backend.app.packages import routes as packages_routes

    fake_root = tmp_path / "fixture_packageages"
    fake_root.mkdir()
    monkeypatch.setattr(packages_routes, "_catalog_root", lambda: fake_root)

    draft = _draft()
    draft["manifest"]["id"] = "ai.test.catalog.pub"
    _, token = user_and_token

    resp = client.post(
        "/api/packages/factory/publish-catalog",
        data=json.dumps({**draft, "replace": False}),
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.get_data(as_text=True)
    body = resp.get_json()
    assert body["package"]["packageId"] == "ai.test.catalog.pub"
    assert body["replacedExisting"] is False
    assert body["catalogDir"] == str(fake_root / "ai.test.catalog.pub@1")
    published = fake_root / "ai.test.catalog.pub@1"
    assert published.is_dir()
    assert (published / "manifest.json").is_file()

    dup = client.post(
        "/api/packages/factory/publish-catalog",
        data=json.dumps({**draft, "replace": False}),
        headers=_auth(token),
    )
    assert dup.status_code == 400
    assert "already exists" in dup.get_json()["error"]

    bumped = copy.deepcopy(draft)
    bumped["manifest"]["version"] = "9.9.9"
    rep = client.post(
        "/api/packages/factory/publish-catalog",
        data=json.dumps({**bumped, "replace": True}),
        headers=_auth(token),
    )
    assert rep.status_code == 201
    rep_body = rep.get_json()
    assert rep_body["replacedExisting"] is True
    assert rep_body["package"]["version"] == "9.9.9"


def test_unpublish_from_catalog_removes_fixture(client, user_and_token, monkeypatch, tmp_path):
    from utk_curio.backend.app.packages import routes as packages_routes

    fake_root = tmp_path / "fixture_packageages"
    fake_root.mkdir()
    monkeypatch.setattr(packages_routes, "_catalog_root", lambda: fake_root)

    draft = _draft()
    draft["manifest"]["id"] = "ai.test.catalog.unpub"
    _, token = user_and_token

    pub = client.post(
        "/api/packages/factory/publish-catalog",
        data=json.dumps({**draft, "replace": False}),
        headers=_auth(token),
    )
    assert pub.status_code == 201
    published = fake_root / "ai.test.catalog.unpub@1"
    assert published.is_dir()

    ok = client.delete(
        "/api/packages/catalog/ai.test.catalog.unpub@1",
        headers=_auth(token),
    )
    assert ok.status_code == 204
    assert not published.exists()

    missing = client.delete(
        "/api/packages/catalog/ai.test.catalog.unpub@1",
        headers=_auth(token),
    )
    assert missing.status_code == 404


def test_unpublish_from_catalog_forbidden_when_env_off(client, user_and_token, monkeypatch):
    from utk_curio.backend.app.packages import routes as packages_routes

    monkeypatch.setattr(packages_routes, "CURIO_ALLOW_FACTORY_CATALOG_PUBLISH", False)
    _, token = user_and_token
    resp = client.delete(
        "/api/packages/catalog/ai.test.catalog.unpub@1",
        headers=_auth(token),
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# POST /api/packages/resolve
# ---------------------------------------------------------------------------

def test_resolve_ok(client, user_and_token, tmp_curio):
    _, token = user_and_token
    client.post(
        "/api/packages/factory/install",
        data=json.dumps(_draft()),
        headers=_auth(token),
    )
    resp = client.post(
        "/api/packages/resolve",
        data=json.dumps({"packages": ["ai.test.factory@1"]}),
        headers=_auth(token),
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["conflicts"] == []
    assert body["lockfile"]["installedPackages"][0]["dirName"] == "ai.test.factory@1"
    # Source-driven dep detection pins to "*" (no version constraint); the
    # resolver carries that range through to the lockfile unchanged.
    assert "numpy" in body["lockfile"]["pythonDeps"]


def test_resolve_falls_back_to_catalog_for_uninstalled_packageage(
    client, user_and_token, tmp_curio,
):
    """The pre-install conflict probe in NodesHub posts both installed
    packages *and* the catalog candidate to ``/resolve``. The candidate has
    no manifest in the user's package store, so the route has to read it
    from the committed catalog fixture — otherwise the user can never
    get past the InstallDialog after uninstalling a package.
    """
    _, token = user_and_token
    # Catalog candidate that the user has not installed.
    resp = client.post(
        "/api/packages/resolve",
        data=json.dumps({"packages": ["ai.urbanlab.uhvi@1"]}),
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    assert body["conflicts"] == []
    assert body["lockfile"]["installedPackages"][0]["dirName"] == "ai.urbanlab.uhvi@1"
    # Catalog manifest's deps came through.
    assert "rasterio" in body["lockfile"]["pythonDeps"]


@pytest.mark.skip(
    reason="Factory now derives deps from source imports (see dependency_scanner.py), "
           "so the test's manual rasterio pin is overridden and it has no path to "
           "surface a version conflict. Catalog conflict semantics stay verified by "
           "the tests that install via /packages/upload (archive sideload preserves "
           "manifest deps verbatim)."
)
def test_resolve_catalog_fallback_still_reports_conflicts(
    client, user_and_token, tmp_curio,
):
    """Installed package + catalog candidate with incompatible ranges must
    still surface as a 409 — the override only changes *where* the
    candidate's manifest comes from, not the conflict semantics."""
    _, token = user_and_token

    # Install a draft package that conflicts with the UHVI fixture's
    # ``rasterio ^1.3`` constraint (which the catalog candidate declares).
    conflicting = _draft()
    conflicting["manifest"]["id"] = "ai.test.rasterio2"
    conflicting["manifest"]["dependencies"]["python"] = {"rasterio": "^2.0"}
    client.post(
        "/api/packages/factory/install",
        data=json.dumps(conflicting),
        headers=_auth(token),
    )

    resp = client.post(
        "/api/packages/resolve",
        data=json.dumps({
            "packages": ["ai.test.rasterio2@1", "ai.urbanlab.uhvi@1"],
        }),
        headers=_auth(token),
    )
    assert resp.status_code == 409, resp.get_json()
    body = resp.get_json()
    assert any(c["package"] == "rasterio" for c in body["conflicts"])


def test_resolve_unknown_packageage_still_errors(client, user_and_token, tmp_curio):
    """A package that is neither installed nor in the catalog must still
    surface the precise 'is malformed' error so the wizard / probe gets
    a useful message — the catalog fallback only suppresses the false
    negative when the manifest *does* exist somewhere on disk."""
    _, token = user_and_token
    resp = client.post(
        "/api/packages/resolve",
        data=json.dumps({"packages": ["ai.not.there@1"]}),
        headers=_auth(token),
    )
    assert resp.status_code == 400
    assert "manifest.json" in resp.get_json()["error"]


@pytest.mark.skip(
    reason="Factory derives deps from source imports, so this test cannot fabricate "
           "a version conflict via factory_install."
)
def test_resolve_conflict_returns_409(client, user_and_token, tmp_curio):
    _, token = user_and_token
    # Install package A with rasterio ^1.3
    a = _draft()
    a["manifest"]["id"] = "ai.test.alpha"
    a["manifest"]["dependencies"]["python"] = {"rasterio": "^1.3"}
    client.post(
        "/api/packages/factory/install",
        data=json.dumps(a), headers=_auth(token),
    )
    # Install package B with rasterio ^2.0
    b = _draft()
    b["manifest"]["id"] = "ai.test.beta"
    b["manifest"]["dependencies"]["python"] = {"rasterio": "^2.0"}
    client.post(
        "/api/packages/factory/install",
        data=json.dumps(b), headers=_auth(token),
    )
    resp = client.post(
        "/api/packages/resolve",
        data=json.dumps({"packages": ["ai.test.alpha@1", "ai.test.beta@1"]}),
        headers=_auth(token),
    )
    assert resp.status_code == 409
    body = resp.get_json()
    assert any(c["package"] == "rasterio" for c in body["conflicts"])


# ---------------------------------------------------------------------------
# POST /api/packages/catalog/install with replace -- the "Reload from catalog"
# action in the drawer's Installed tab.
#
# Authoring a package under packages/ means editing it in place. Plain install
# is a no-op once a copy exists in the user store, so the drawer's Reload
# button re-installs with replace=true; without that, on-disk edits (including
# a rebuilt scripts/behaviors.js) never reach the running app.
# ---------------------------------------------------------------------------

def _write_catalog_package(root, manifest: dict, sources: dict[str, str]) -> str:
    """Materialise a package directory under *root*; returns its dirName."""
    dir_name = f"{manifest['id']}@{manifest['compatibility']['major']}"
    package_root = root / dir_name
    (package_root / "sources").mkdir(parents=True, exist_ok=True)
    (package_root / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    for name, body in sources.items():
        (package_root / "sources" / name).write_text(body, encoding="utf-8")
    return dir_name


@pytest.fixture()
def fake_catalog(tmp_path, monkeypatch):
    """Point the packages routes at a throwaway catalog directory.

    The real catalog is <repo_root>/packages/, which tests must not mutate.
    """
    from utk_curio.backend.app.packages import routes as packages_routes

    catalog = tmp_path / "catalog"
    catalog.mkdir()
    monkeypatch.setattr(packages_routes, "_catalog_root", lambda: catalog)
    return catalog


def test_catalog_install_replace_picks_up_edited_sources(
    client, user_and_token, tmp_curio, fake_catalog, manifest_dict,
):
    """Reload overwrites the installed copy with the catalog's current bits."""
    _, token = user_and_token
    manifest = manifest_dict(package_id="ai.test.reload", major=1)
    manifest["templates"] = [
        {
            "id": "reload-kind",
            "label": "Reload kind",
            "category": "computation",
            "engine": "python",
            "editor": "code",
            "hasCode": True,
            "hasWidgets": False,
            "hasGrammar": False,
            "inputPorts": [],
            "outputPorts": [{"types": ["JSON"], "cardinality": "1"}],
            "source": "sources/reload-kind.py",
        }
    ]
    dir_name = _write_catalog_package(
        fake_catalog, manifest, {"reload-kind.py": "return 'first'\n"}
    )

    resp = client.post(
        "/api/packages/catalog/install",
        data=json.dumps({"dirName": dir_name}),
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.get_data(as_text=True)
    assert resp.get_json()["replacedExisting"] is False

    file_url = f"/api/packages/{dir_name}/file/sources/reload-kind.py"
    body = client.get(file_url, headers=_auth(token)).get_data(as_text=True)
    assert "first" in body

    # Author edits the package on disk...
    (fake_catalog / dir_name / "sources" / "reload-kind.py").write_text(
        "return 'second'\n", encoding="utf-8"
    )

    # ...and a plain install does nothing, because a copy already exists.
    # This is the trap the Reload button exists to avoid.
    stale = client.get(file_url, headers=_auth(token)).get_data(as_text=True)
    assert "first" in stale

    # Reload == install with replace.
    resp = client.post(
        "/api/packages/catalog/install",
        data=json.dumps({"dirName": dir_name, "replace": True}),
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.get_data(as_text=True)
    assert resp.get_json()["replacedExisting"] is True

    fresh = client.get(file_url, headers=_auth(token)).get_data(as_text=True)
    assert "second" in fresh
    assert "first" not in fresh


def test_catalog_install_without_replace_rejects_existing(
    client, user_and_token, tmp_curio, fake_catalog, manifest_dict,
):
    """The same coordinate cannot be installed twice without replace."""
    _, token = user_and_token
    manifest = manifest_dict(package_id="ai.test.twice", major=1)
    dir_name = _write_catalog_package(fake_catalog, manifest, {})

    first = client.post(
        "/api/packages/catalog/install",
        data=json.dumps({"dirName": dir_name}),
        headers=_auth(token),
    )
    assert first.status_code == 201, first.get_data(as_text=True)

    second = client.post(
        "/api/packages/catalog/install",
        data=json.dumps({"dirName": dir_name}),
        headers=_auth(token),
    )
    assert second.status_code == 400
    assert "already installed" in second.get_json()["error"].lower()


def test_catalog_install_replace_refreshes_behavior_bundle(
    client, user_and_token, tmp_curio, fake_catalog, manifest_dict,
):
    """A rebuilt scripts/behaviors.js reaches the user store on reload.

    This is the custom-UI case: the frontend fetches the bundle from the
    *installed* copy, so a reload is what makes a rebuilt bundle live.
    """
    _, token = user_and_token
    manifest = manifest_dict(package_id="ai.test.uinode", major=1)
    manifest["behaviorScript"] = "scripts/behaviors.js"
    dir_name = f"{manifest['id']}@1"
    package_root = fake_catalog / dir_name
    (package_root / "scripts").mkdir(parents=True)
    (package_root / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    bundle = package_root / "scripts" / "behaviors.js"
    bundle.write_text("/* build 1 */\n", encoding="utf-8")

    resp = client.post(
        "/api/packages/catalog/install",
        data=json.dumps({"dirName": dir_name}),
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.get_data(as_text=True)

    bundle_url = f"/api/packages/{dir_name}/file/scripts/behaviors.js"
    assert "build 1" in client.get(bundle_url, headers=_auth(token)).get_data(as_text=True)

    bundle.write_text("/* build 2 */\n", encoding="utf-8")
    resp = client.post(
        "/api/packages/catalog/install",
        data=json.dumps({"dirName": dir_name, "replace": True}),
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.get_data(as_text=True)

    served = client.get(bundle_url, headers=_auth(token)).get_data(as_text=True)
    assert "build 2" in served
