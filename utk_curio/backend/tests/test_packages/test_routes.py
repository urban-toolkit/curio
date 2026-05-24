"""Integration tests for the /api/packages endpoints."""

from __future__ import annotations

import copy
import io
import json
import zipfile


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
            "dependencies": {"packages": {}, "python": {"numpy": "^1.26"}, "js": {}},
            "kinds": [
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
        "sources": {"demo": {"filename": "demo.py", "code": "def run():\n    return {}\n"}},
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
        data={"file": (io.BytesIO(archive), "factory.curio-package")},
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
        data={"file": (io.BytesIO(archive), "x.curio-package")},
        headers=_multipart_auth(token),
        content_type="multipart/form-data",
    )
    resp = client.post(
        "/api/packages/upload",
        data={"file": (io.BytesIO(archive), "x.curio-package")},
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
        data={"file": (io.BytesIO(archive), "x.curio-package")},
        headers=_multipart_auth(token),
        content_type="multipart/form-data",
    )
    bumped = _draft()
    bumped["manifest"]["version"] = "2.0.0"
    archive2 = _archive_from_draft(bumped)
    resp = client.post(
        "/api/packages/upload?replace=true",
        data={"file": (io.BytesIO(archive2), "x.curio-package")},
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
        data={"file": (io.BytesIO(archive), "x.curio-package")},
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
# GET /api/packages/factory/capabilities + POST publish-catalog
# ---------------------------------------------------------------------------


def test_factory_capabilities_reflect_publish_env_switch(client, user_and_token, monkeypatch):
    _, token = user_and_token
    monkeypatch.delenv("CURIO_ALLOW_FACTORY_CATALOG_PUBLISH", raising=False)
    r1 = client.get("/api/packages/factory/capabilities", headers=_auth(token))
    assert r1.status_code == 200
    assert r1.get_json()["catalogPublish"] is True

    monkeypatch.setenv("CURIO_ALLOW_FACTORY_CATALOG_PUBLISH", "0")
    r_off = client.get("/api/packages/factory/capabilities", headers=_auth(token))
    assert r_off.status_code == 200
    assert r_off.get_json()["catalogPublish"] is False

    monkeypatch.setenv("CURIO_ALLOW_FACTORY_CATALOG_PUBLISH", "yes")
    r2 = client.get("/api/packages/factory/capabilities", headers=_auth(token))
    assert r2.status_code == 200
    assert r2.get_json()["catalogPublish"] is True


def test_factory_publish_catalog_forbidden_when_env_off(client, user_and_token, monkeypatch):
    monkeypatch.setenv("CURIO_ALLOW_FACTORY_CATALOG_PUBLISH", "false")
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

    monkeypatch.delenv("CURIO_ALLOW_FACTORY_CATALOG_PUBLISH", raising=False)
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

    monkeypatch.delenv("CURIO_ALLOW_FACTORY_CATALOG_PUBLISH", raising=False)
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
    monkeypatch.setenv("CURIO_ALLOW_FACTORY_CATALOG_PUBLISH", "off")
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
    assert body["lockfile"]["pythonDeps"]["numpy"].startswith(">=1.26")


def test_install_deps_forwards_to_sandbox(client, user_and_token, tmp_curio, monkeypatch):
    """``/install-deps`` resolves, then hands merged deps to the sandbox."""
    _, token = user_and_token

    # Install a package with a single python dep so the resolver has
    # something to forward.
    client.post(
        "/api/packages/factory/install",
        data=json.dumps(_draft()),
        headers=_auth(token),
    )

    captured: dict = {}

    def _fake_forward(packages):
        captured["packages"] = packages
        return ({"installed": packages}, 200)

    from utk_curio.backend.app.packages import routes as package_routes
    monkeypatch.setattr(package_routes, "_forward_to_sandbox_install", _fake_forward)

    resp = client.post(
        "/api/packages/install-deps",
        data=json.dumps({"packages": ["ai.test.factory@1"]}),
        headers=_auth(token),
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["conflicts"] == []
    assert "numpy>=1.26.0,<2.0.0" in body["pipRequirements"]
    assert captured["packages"] == body["pipRequirements"]
    assert body["lockfile"]["installedPackages"][0]["dirName"] == "ai.test.factory@1"


def test_install_deps_conflict_skips_sandbox(client, user_and_token, tmp_curio, monkeypatch):
    """A range conflict returns 409 and never invokes the sandbox forwarder."""
    _, token = user_and_token

    a = _draft()
    a["manifest"]["id"] = "ai.test.alpha"
    a["manifest"]["dependencies"]["python"] = {"rasterio": "^1.3"}
    client.post(
        "/api/packages/factory/install",
        data=json.dumps(a), headers=_auth(token),
    )
    b = _draft()
    b["manifest"]["id"] = "ai.test.beta"
    b["manifest"]["dependencies"]["python"] = {"rasterio": "^2.0"}
    client.post(
        "/api/packages/factory/install",
        data=json.dumps(b), headers=_auth(token),
    )

    invoked = {"count": 0}

    def _fake_forward(_packages):  # pragma: no cover — must not run
        invoked["count"] += 1
        return ({}, 200)

    from utk_curio.backend.app.packages import routes as package_routes
    monkeypatch.setattr(package_routes, "_forward_to_sandbox_install", _fake_forward)

    resp = client.post(
        "/api/packages/install-deps",
        data=json.dumps({"packages": ["ai.test.alpha@1", "ai.test.beta@1"]}),
        headers=_auth(token),
    )
    assert resp.status_code == 409
    assert invoked["count"] == 0
    assert any(c["package"] == "rasterio" for c in resp.get_json()["conflicts"])


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
