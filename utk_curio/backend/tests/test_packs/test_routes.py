"""Integration tests for the /api/packs endpoints."""

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
            "dependencies": {"packs": {}, "python": {"numpy": "^1.26"}, "js": {}},
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
                    "templateDir": "templates/demo",
                    "defaultTemplate": "templates/demo/Default.py",
                }
            ],
        },
        "sources": {"demo": {"Default.py": "def run():\n    return {}\n"}},
    }


# ---------------------------------------------------------------------------
# GET /api/packs/catalog
# ---------------------------------------------------------------------------

def test_catalog_lists_committed_fixtures(client, user_and_token, tmp_curio):
    """The catalog stub mirrors the fixture pack ``ai.urbanlab.uhvi@1``."""
    _, token = user_and_token
    resp = client.get("/api/packs/catalog", headers=_auth(token))
    assert resp.status_code == 200
    packs = resp.get_json()["packs"]
    ids = {p["packId"] for p in packs}
    assert "ai.urbanlab.uhvi" in ids
    item = next(p for p in packs if p["packId"] == "ai.urbanlab.uhvi")
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
    client, user_and_token, tmp_curio, install_pack, manifest_dict,
):
    from utk_curio.backend.app.projects.services import _user_dir_key

    user, token = user_and_token
    uk = _user_dir_key(user)
    lineage = {
        "forkedFrom": {"packId": "ai.upstream.catalog", "major": 1},
        "root": {"packId": "ai.upstream.catalog", "major": 1},
    }
    install_pack(
        uk,
        manifest=manifest_dict(pack_id="curio.test.lineage.pack", lineage=lineage),
    )
    resp = client.get("/api/packs", headers=_auth(token))
    assert resp.status_code == 200
    pack = next(p for p in resp.get_json()["packs"] if p["packId"] == "curio.test.lineage.pack")
    assert pack["lineage"] == lineage
    assert pack["familyKey"] == "ai.upstream.catalog@1"
    assert isinstance(pack["installUpdatedAtMs"], int)
    assert isinstance(pack["createdAtMs"], int)


def test_list_installed_orders_by_created_at_ms_newest_first(
    client, user_and_token, tmp_curio, install_pack, manifest_dict,
):
    """``GET /api/packs`` lists packs sorted by canonical ``manifest.createdAt``."""

    from utk_curio.backend.app.projects.services import _user_dir_key

    user, token = user_and_token
    uk = _user_dir_key(user)
    install_pack(
        uk,
        manifest=manifest_dict(
            pack_id="ai.sort.older",
            created_at="2020-01-01T00:00:00Z",
        ),
    )
    install_pack(
        uk,
        manifest=manifest_dict(
            pack_id="ai.sort.newer",
            created_at="2030-01-01T00:00:00Z",
        ),
    )
    packs = client.get("/api/packs", headers=_auth(token)).get_json()["packs"]
    ours = [p for p in packs if p["packId"] in ("ai.sort.older", "ai.sort.newer")]
    assert [p["packId"] for p in ours] == ["ai.sort.newer", "ai.sort.older"]

def test_fork_install_sets_parent_palette_dock_hidden_and_toggle_round_trip(client, user_and_token, tmp_curio, install_pack, manifest_dict):
    from utk_curio.backend.app.projects.services import _user_dir_key

    user, token = user_and_token
    uk = _user_dir_key(user)
    install_pack(uk, manifest=manifest_dict(pack_id="ai.palette.parentdock"))
    lineage = {
        "forkedFrom": {"packId": "ai.palette.parentdock", "major": 1},
        "root": {"packId": "ai.palette.parentdock", "major": 1},
    }
    install_pack(
        uk,
        manifest=manifest_dict(pack_id="ai.palette.forkdock", lineage=lineage),
    )

    packs = client.get("/api/packs", headers=_auth(token)).get_json()["packs"]
    parent = next(p for p in packs if p["packId"] == "ai.palette.parentdock")
    assert parent["paletteDock"]["hiddenFromForkPaletteDock"] is True

    rev = client.post(
        "/api/packs/palette-dock/fork-parents",
        data=json.dumps({"visible": True}),
        headers=_auth(token),
    )
    assert rev.status_code == 204

    shown = client.get("/api/packs", headers=_auth(token)).get_json()["packs"]
    parent_shown = next(p for p in shown if p["packId"] == "ai.palette.parentdock")
    assert "paletteDock" not in parent_shown

    hid = client.post(
        "/api/packs/palette-dock/fork-parents",
        data=json.dumps({"visible": False}),
        headers=_auth(token),
    )
    assert hid.status_code == 204

    hidden_again = client.get("/api/packs", headers=_auth(token)).get_json()["packs"]
    parent_hidden = next(p for p in hidden_again if p["packId"] == "ai.palette.parentdock")
    assert parent_hidden["paletteDock"]["hiddenFromForkPaletteDock"] is True


def test_fork_parents_palette_endpoint_requires_visible_boolean(client, user_and_token, tmp_curio):
    _, token = user_and_token
    bad = client.post(
        "/api/packs/palette-dock/fork-parents",
        data=json.dumps({}),
        headers=_auth(token),
    )
    assert bad.status_code == 400


def test_fork_parents_palette_noop_when_no_fork_lineage_installed(client, user_and_token, tmp_curio):
    _, token = user_and_token
    ok = client.post(
        "/api/packs/palette-dock/fork-parents",
        data=json.dumps({"visible": True}),
        headers=_auth(token),
    )
    assert ok.status_code == 204


def test_pack_palette_dock_visible_per_install(client, user_and_token, tmp_curio, install_pack, manifest_dict):
    from utk_curio.backend.app.projects.services import _user_dir_key

    user, token = user_and_token
    uk = _user_dir_key(user)
    install_pack(uk, manifest=manifest_dict(pack_id="ai.palette.onesie"))

    vis = client.post(
        "/api/packs/ai.palette.onesie@1/palette-dock-visible",
        data=json.dumps({"visible": False}),
        headers=_auth(token),
    )
    assert vis.status_code == 204

    packs = client.get("/api/packs", headers=_auth(token)).get_json()["packs"]
    row = next(p for p in packs if p["packId"] == "ai.palette.onesie")
    assert row["paletteDock"]["hiddenFromForkPaletteDock"] is True

    rev = client.post(
        "/api/packs/ai.palette.onesie@1/palette-dock-visible",
        data=json.dumps({"visible": True}),
        headers=_auth(token),
    )
    assert rev.status_code == 204

    packs2 = client.get("/api/packs", headers=_auth(token)).get_json()["packs"]
    row2 = next(p for p in packs2 if p["packId"] == "ai.palette.onesie")
    assert "paletteDock" not in row2


def test_catalog_requires_auth(client, tmp_curio):
    resp = client.get("/api/packs/catalog")
    assert resp.status_code == 401


def test_install_from_catalog_endpoint(client, user_and_token, tmp_curio):
    """Hitting /catalog/install with a fixture's ``dirName`` materialises it."""
    _, token = user_and_token
    resp = client.post(
        "/api/packs/catalog/install",
        data=json.dumps({"dirName": "ai.urbanlab.uhvi@1"}),
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.get_data(as_text=True)
    body = resp.get_json()
    assert body["pack"]["packId"] == "ai.urbanlab.uhvi"

    listing = client.get("/api/packs", headers=_auth(token)).get_json()["packs"]
    assert "ai.urbanlab.uhvi" in {p["packId"] for p in listing}


def test_install_from_catalog_rejects_unknown(client, user_and_token, tmp_curio):
    _, token = user_and_token
    resp = client.post(
        "/api/packs/catalog/install",
        data=json.dumps({"dirName": "ai.test.unknown@1"}),
        headers=_auth(token),
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/packs/upload -> GET /api/packs -> DELETE /api/packs/<dir>
# ---------------------------------------------------------------------------

def _archive_from_draft(d: dict) -> bytes:
    """Build a zip from a factory-shaped draft (no HTTP roundtrip)."""
    from utk_curio.backend.app.packs.factory import build_pack_archive
    return build_pack_archive(d).archive


def test_upload_then_list_then_delete(client, user_and_token, tmp_curio):
    _, token = user_and_token
    archive = _archive_from_draft(_draft())
    resp = client.post(
        "/api/packs/upload",
        data={"file": (io.BytesIO(archive), "factory.curio-nodepack")},
        headers=_multipart_auth(token),
        content_type="multipart/form-data",
    )
    assert resp.status_code == 201, resp.get_data(as_text=True)
    body = resp.get_json()
    assert body["pack"]["packId"] == "ai.test.factory"
    assert "manifest.json" in body["integrity"]

    listing = client.get("/api/packs", headers=_auth(token)).get_json()["packs"]
    ids = {p["packId"] for p in listing}
    assert "ai.test.factory" in ids

    resp = client.delete("/api/packs/ai.test.factory@1", headers=_auth(token))
    assert resp.status_code == 204
    listing = client.get("/api/packs", headers=_auth(token)).get_json()["packs"]
    assert "ai.test.factory" not in {p["packId"] for p in listing}


def test_upload_duplicate_without_replace_is_rejected(client, user_and_token, tmp_curio):
    _, token = user_and_token
    archive = _archive_from_draft(_draft())
    client.post(
        "/api/packs/upload",
        data={"file": (io.BytesIO(archive), "x.curio-nodepack")},
        headers=_multipart_auth(token),
        content_type="multipart/form-data",
    )
    resp = client.post(
        "/api/packs/upload",
        data={"file": (io.BytesIO(archive), "x.curio-nodepack")},
        headers=_multipart_auth(token),
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400
    assert "already installed" in resp.get_json()["error"]


def test_upload_replace(client, user_and_token, tmp_curio):
    _, token = user_and_token
    archive = _archive_from_draft(_draft())
    client.post(
        "/api/packs/upload",
        data={"file": (io.BytesIO(archive), "x.curio-nodepack")},
        headers=_multipart_auth(token),
        content_type="multipart/form-data",
    )
    bumped = _draft()
    bumped["manifest"]["version"] = "2.0.0"
    archive2 = _archive_from_draft(bumped)
    resp = client.post(
        "/api/packs/upload?replace=true",
        data={"file": (io.BytesIO(archive2), "x.curio-nodepack")},
        headers=_multipart_auth(token),
        content_type="multipart/form-data",
    )
    assert resp.status_code == 201
    assert resp.get_json()["replacedExisting"] is True


def test_delete_unknown_pack_returns_404(client, user_and_token, tmp_curio):
    _, token = user_and_token
    resp = client.delete("/api/packs/ai.unknown@1", headers=_auth(token))
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/packs/<dir>/archive
# ---------------------------------------------------------------------------

def test_export_after_install(client, user_and_token, tmp_curio):
    _, token = user_and_token
    archive = _archive_from_draft(_draft())
    client.post(
        "/api/packs/upload",
        data={"file": (io.BytesIO(archive), "x.curio-nodepack")},
        headers=_multipart_auth(token),
        content_type="multipart/form-data",
    )
    resp = client.get(
        "/api/packs/ai.test.factory@1/archive", headers=_auth(token)
    )
    assert resp.status_code == 200
    assert resp.mimetype == "application/zip"
    # Round-trip: the exported archive must be itself installable.
    with zipfile.ZipFile(io.BytesIO(resp.data), "r") as zf:
        names = set(zf.namelist())
    assert "manifest.json" in names
    assert "templates/demo/Default.py" in names


# ---------------------------------------------------------------------------
# POST /api/packs/factory/build + /factory/install
# ---------------------------------------------------------------------------

def test_factory_build_returns_zip(client, user_and_token, tmp_curio):
    _, token = user_and_token
    resp = client.post(
        "/api/packs/factory/build",
        data=json.dumps(_draft()),
        headers=_auth(token),
    )
    assert resp.status_code == 200
    assert resp.mimetype == "application/zip"
    assert resp.headers["X-Curio-Pack-Dir"] == "ai.test.factory@1"


def test_factory_install_creates_pack(client, user_and_token, tmp_curio):
    _, token = user_and_token
    resp = client.post(
        "/api/packs/factory/install",
        data=json.dumps(_draft()),
        headers=_auth(token),
    )
    assert resp.status_code == 201
    listing = client.get("/api/packs", headers=_auth(token)).get_json()["packs"]
    assert "ai.test.factory" in {p["packId"] for p in listing}


def test_factory_rejects_malformed_draft(client, user_and_token, tmp_curio):
    _, token = user_and_token
    bad = _draft()
    bad["manifest"]["id"] = "not valid"  # not reverse-DNS
    resp = client.post(
        "/api/packs/factory/build",
        data=json.dumps(bad),
        headers=_auth(token),
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# GET /api/packs/factory/capabilities + POST publish-catalog
# ---------------------------------------------------------------------------


def test_factory_capabilities_reflect_publish_env_switch(client, user_and_token, monkeypatch):
    _, token = user_and_token
    monkeypatch.delenv("CURIO_ALLOW_FACTORY_CATALOG_PUBLISH", raising=False)
    r1 = client.get("/api/packs/factory/capabilities", headers=_auth(token))
    assert r1.status_code == 200
    assert r1.get_json()["catalogPublish"] is True

    monkeypatch.setenv("CURIO_ALLOW_FACTORY_CATALOG_PUBLISH", "0")
    r_off = client.get("/api/packs/factory/capabilities", headers=_auth(token))
    assert r_off.status_code == 200
    assert r_off.get_json()["catalogPublish"] is False

    monkeypatch.setenv("CURIO_ALLOW_FACTORY_CATALOG_PUBLISH", "yes")
    r2 = client.get("/api/packs/factory/capabilities", headers=_auth(token))
    assert r2.status_code == 200
    assert r2.get_json()["catalogPublish"] is True


def test_factory_publish_catalog_forbidden_when_env_off(client, user_and_token, monkeypatch):
    monkeypatch.setenv("CURIO_ALLOW_FACTORY_CATALOG_PUBLISH", "false")
    _, token = user_and_token
    resp = client.post(
        "/api/packs/factory/publish-catalog",
        data=json.dumps(_draft()),
        headers=_auth(token),
    )
    assert resp.status_code == 403
    body = resp.get_json()
    assert "error" in body
    assert "CURIO_ALLOW_FACTORY_CATALOG_PUBLISH" in body["error"]


def test_factory_publish_catalog_writes_to_stub_root(client, user_and_token, monkeypatch, tmp_path):
    """Publish redirects catalog root to ``tmp_path`` so we don't touch committed fixtures."""
    from utk_curio.backend.app.packs import routes as packs_routes

    monkeypatch.delenv("CURIO_ALLOW_FACTORY_CATALOG_PUBLISH", raising=False)
    fake_root = tmp_path / "fixture_packs"
    fake_root.mkdir()
    monkeypatch.setattr(packs_routes, "_catalog_root", lambda: fake_root)

    draft = _draft()
    draft["manifest"]["id"] = "ai.test.catalog.pub"
    _, token = user_and_token

    resp = client.post(
        "/api/packs/factory/publish-catalog",
        data=json.dumps({**draft, "replace": False}),
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.get_data(as_text=True)
    body = resp.get_json()
    assert body["pack"]["packId"] == "ai.test.catalog.pub"
    assert body["replacedExisting"] is False
    assert body["catalogDir"] == str(fake_root / "ai.test.catalog.pub@1")
    published = fake_root / "ai.test.catalog.pub@1"
    assert published.is_dir()
    assert (published / "manifest.json").is_file()

    dup = client.post(
        "/api/packs/factory/publish-catalog",
        data=json.dumps({**draft, "replace": False}),
        headers=_auth(token),
    )
    assert dup.status_code == 400
    assert "already exists" in dup.get_json()["error"]

    bumped = copy.deepcopy(draft)
    bumped["manifest"]["version"] = "9.9.9"
    rep = client.post(
        "/api/packs/factory/publish-catalog",
        data=json.dumps({**bumped, "replace": True}),
        headers=_auth(token),
    )
    assert rep.status_code == 201
    rep_body = rep.get_json()
    assert rep_body["replacedExisting"] is True
    assert rep_body["pack"]["version"] == "9.9.9"


def test_unpublish_from_catalog_removes_fixture(client, user_and_token, monkeypatch, tmp_path):
    from utk_curio.backend.app.packs import routes as packs_routes

    monkeypatch.delenv("CURIO_ALLOW_FACTORY_CATALOG_PUBLISH", raising=False)
    fake_root = tmp_path / "fixture_packs"
    fake_root.mkdir()
    monkeypatch.setattr(packs_routes, "_catalog_root", lambda: fake_root)

    draft = _draft()
    draft["manifest"]["id"] = "ai.test.catalog.unpub"
    _, token = user_and_token

    pub = client.post(
        "/api/packs/factory/publish-catalog",
        data=json.dumps({**draft, "replace": False}),
        headers=_auth(token),
    )
    assert pub.status_code == 201
    published = fake_root / "ai.test.catalog.unpub@1"
    assert published.is_dir()

    ok = client.delete(
        "/api/packs/catalog/ai.test.catalog.unpub@1",
        headers=_auth(token),
    )
    assert ok.status_code == 204
    assert not published.exists()

    missing = client.delete(
        "/api/packs/catalog/ai.test.catalog.unpub@1",
        headers=_auth(token),
    )
    assert missing.status_code == 404


def test_unpublish_from_catalog_forbidden_when_env_off(client, user_and_token, monkeypatch):
    monkeypatch.setenv("CURIO_ALLOW_FACTORY_CATALOG_PUBLISH", "off")
    _, token = user_and_token
    resp = client.delete(
        "/api/packs/catalog/ai.test.catalog.unpub@1",
        headers=_auth(token),
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# POST /api/packs/resolve
# ---------------------------------------------------------------------------

def test_resolve_ok(client, user_and_token, tmp_curio):
    _, token = user_and_token
    client.post(
        "/api/packs/factory/install",
        data=json.dumps(_draft()),
        headers=_auth(token),
    )
    resp = client.post(
        "/api/packs/resolve",
        data=json.dumps({"packs": ["ai.test.factory@1"]}),
        headers=_auth(token),
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["conflicts"] == []
    assert body["lockfile"]["installedPacks"][0]["dirName"] == "ai.test.factory@1"
    assert body["lockfile"]["pythonDeps"]["numpy"].startswith(">=1.26")


def test_install_deps_forwards_to_sandbox(client, user_and_token, tmp_curio, monkeypatch):
    """``/install-deps`` resolves, then hands merged deps to the sandbox."""
    _, token = user_and_token

    # Install a pack with a single python dep so the resolver has
    # something to forward.
    client.post(
        "/api/packs/factory/install",
        data=json.dumps(_draft()),
        headers=_auth(token),
    )

    captured: dict = {}

    def _fake_forward(packages):
        captured["packages"] = packages
        return ({"installed": packages}, 200)

    from utk_curio.backend.app.packs import routes as pack_routes
    monkeypatch.setattr(pack_routes, "_forward_to_sandbox_install", _fake_forward)

    resp = client.post(
        "/api/packs/install-deps",
        data=json.dumps({"packs": ["ai.test.factory@1"]}),
        headers=_auth(token),
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["conflicts"] == []
    assert "numpy>=1.26.0,<2.0.0" in body["pipRequirements"]
    assert captured["packages"] == body["pipRequirements"]
    assert body["lockfile"]["installedPacks"][0]["dirName"] == "ai.test.factory@1"


def test_install_deps_conflict_skips_sandbox(client, user_and_token, tmp_curio, monkeypatch):
    """A range conflict returns 409 and never invokes the sandbox forwarder."""
    _, token = user_and_token

    a = _draft()
    a["manifest"]["id"] = "ai.test.alpha"
    a["manifest"]["dependencies"]["python"] = {"rasterio": "^1.3"}
    client.post(
        "/api/packs/factory/install",
        data=json.dumps(a), headers=_auth(token),
    )
    b = _draft()
    b["manifest"]["id"] = "ai.test.beta"
    b["manifest"]["dependencies"]["python"] = {"rasterio": "^2.0"}
    client.post(
        "/api/packs/factory/install",
        data=json.dumps(b), headers=_auth(token),
    )

    invoked = {"count": 0}

    def _fake_forward(_packages):  # pragma: no cover — must not run
        invoked["count"] += 1
        return ({}, 200)

    from utk_curio.backend.app.packs import routes as pack_routes
    monkeypatch.setattr(pack_routes, "_forward_to_sandbox_install", _fake_forward)

    resp = client.post(
        "/api/packs/install-deps",
        data=json.dumps({"packs": ["ai.test.alpha@1", "ai.test.beta@1"]}),
        headers=_auth(token),
    )
    assert resp.status_code == 409
    assert invoked["count"] == 0
    assert any(c["package"] == "rasterio" for c in resp.get_json()["conflicts"])


def test_resolve_falls_back_to_catalog_for_uninstalled_pack(
    client, user_and_token, tmp_curio,
):
    """The pre-install conflict probe in NodesHub posts both installed
    packs *and* the catalog candidate to ``/resolve``. The candidate has
    no manifest in the user's pack store, so the route has to read it
    from the committed catalog fixture — otherwise the user can never
    get past the InstallDialog after uninstalling a pack.
    """
    _, token = user_and_token
    # Catalog candidate that the user has not installed.
    resp = client.post(
        "/api/packs/resolve",
        data=json.dumps({"packs": ["ai.urbanlab.uhvi@1"]}),
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    assert body["conflicts"] == []
    assert body["lockfile"]["installedPacks"][0]["dirName"] == "ai.urbanlab.uhvi@1"
    # Catalog manifest's deps came through.
    assert "rasterio" in body["lockfile"]["pythonDeps"]


def test_resolve_catalog_fallback_still_reports_conflicts(
    client, user_and_token, tmp_curio,
):
    """Installed pack + catalog candidate with incompatible ranges must
    still surface as a 409 — the override only changes *where* the
    candidate's manifest comes from, not the conflict semantics."""
    _, token = user_and_token

    # Install a draft pack that conflicts with the UHVI fixture's
    # ``rasterio ^1.3`` constraint (which the catalog candidate declares).
    conflicting = _draft()
    conflicting["manifest"]["id"] = "ai.test.rasterio2"
    conflicting["manifest"]["dependencies"]["python"] = {"rasterio": "^2.0"}
    client.post(
        "/api/packs/factory/install",
        data=json.dumps(conflicting),
        headers=_auth(token),
    )

    resp = client.post(
        "/api/packs/resolve",
        data=json.dumps({
            "packs": ["ai.test.rasterio2@1", "ai.urbanlab.uhvi@1"],
        }),
        headers=_auth(token),
    )
    assert resp.status_code == 409, resp.get_json()
    body = resp.get_json()
    assert any(c["package"] == "rasterio" for c in body["conflicts"])


def test_resolve_unknown_pack_still_errors(client, user_and_token, tmp_curio):
    """A pack that is neither installed nor in the catalog must still
    surface the precise 'is malformed' error so the wizard / probe gets
    a useful message — the catalog fallback only suppresses the false
    negative when the manifest *does* exist somewhere on disk."""
    _, token = user_and_token
    resp = client.post(
        "/api/packs/resolve",
        data=json.dumps({"packs": ["ai.not.there@1"]}),
        headers=_auth(token),
    )
    assert resp.status_code == 400
    assert "manifest.json" in resp.get_json()["error"]


def test_resolve_conflict_returns_409(client, user_and_token, tmp_curio):
    _, token = user_and_token
    # Install pack A with rasterio ^1.3
    a = _draft()
    a["manifest"]["id"] = "ai.test.alpha"
    a["manifest"]["dependencies"]["python"] = {"rasterio": "^1.3"}
    client.post(
        "/api/packs/factory/install",
        data=json.dumps(a), headers=_auth(token),
    )
    # Install pack B with rasterio ^2.0
    b = _draft()
    b["manifest"]["id"] = "ai.test.beta"
    b["manifest"]["dependencies"]["python"] = {"rasterio": "^2.0"}
    client.post(
        "/api/packs/factory/install",
        data=json.dumps(b), headers=_auth(token),
    )
    resp = client.post(
        "/api/packs/resolve",
        data=json.dumps({"packs": ["ai.test.alpha@1", "ai.test.beta@1"]}),
        headers=_auth(token),
    )
    assert resp.status_code == 409
    body = resp.get_json()
    assert any(c["package"] == "rasterio" for c in body["conflicts"])
