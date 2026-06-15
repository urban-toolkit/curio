"""Integration tests for /api/packages/workflow-deps/{check,install}.

A dataflow declares the catalog packages it depends on in its
``dataflow.packages`` lockfile. On load the frontend posts that lockfile to
/check to learn which declared packages aren't ready, then installs them via
/install — installing a package provisions its nodes and its declared python
libraries. (e.g. example 09 declares ``curio.weather@1``, which brings
rasterio / pythermalcomfort / rasterstats.)
"""

from __future__ import annotations

import json
from pathlib import Path

from utk_curio.backend.app.packages import routes as packages_routes
from utk_curio.backend.app.packages import services as packages_services


def _auth(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _check(client, token, packages):
    return client.post(
        "/api/packages/workflow-deps/check",
        headers=_auth(token),
        data=json.dumps({"packages": packages}),
    )


def _install(client, token, packages):
    return client.post(
        "/api/packages/workflow-deps/install",
        headers=_auth(token),
        data=json.dumps({"packages": packages}),
    )


# ---------------------------------------------------------------------------
# POST /workflow-deps/check
# ---------------------------------------------------------------------------

def test_check_flags_declared_package_not_in_store(client, user_and_token, tmp_curio):
    """A declared package absent from the user's store needs installing."""
    _, token = user_and_token
    resp = _check(client, token, ["curio.weather@1"])
    assert resp.status_code == 200
    assert resp.get_json()["packages"] == ["curio.weather@1"]


def test_check_skips_invalid_dirnames(client, user_and_token, tmp_curio):
    _, token = user_and_token
    resp = _check(client, token, ["not a dirname", "curio.weather@1"])
    assert resp.status_code == 200
    assert resp.get_json()["packages"] == ["curio.weather@1"]


def test_check_omits_installed_package_with_satisfied_deps(
    client, user_and_token, tmp_curio, monkeypatch
):
    """In the store + every declared dep present → not flagged."""
    _, token = user_and_token
    monkeypatch.setattr(
        packages_routes, "list_user_packageages",
        lambda uk: [Path("curio.weather@1")],
    )
    monkeypatch.setattr(
        packages_services, "_read_python_deps",
        lambda uk, dn: {"flask": ""},  # flask is always present (backend runs on it)
    )
    resp = _check(client, token, ["curio.weather@1"])
    assert resp.status_code == 200
    assert resp.get_json()["packages"] == []


def test_check_flags_installed_package_with_missing_dep(
    client, user_and_token, tmp_curio, monkeypatch
):
    """In the store but a declared dep was pip-uninstalled → flagged (repair)."""
    _, token = user_and_token
    monkeypatch.setattr(
        packages_routes, "list_user_packageages",
        lambda uk: [Path("curio.weather@1")],
    )
    monkeypatch.setattr(
        packages_services, "_read_python_deps",
        lambda uk, dn: {"zzz_not_a_real_package_qq": ">=1"},
    )
    resp = _check(client, token, ["curio.weather@1"])
    assert resp.status_code == 200
    assert resp.get_json()["packages"] == ["curio.weather@1"]


def test_check_rejects_malformed_body(client, user_and_token, tmp_curio):
    _, token = user_and_token
    resp = client.post(
        "/api/packages/workflow-deps/check",
        headers=_auth(token),
        data=json.dumps({"packages": "not-a-list"}),
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# POST /workflow-deps/install
# ---------------------------------------------------------------------------

def test_install_installs_each_package_to_store(client, user_and_token, tmp_curio, monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(
        packages_services, "install_to_store",
        lambda uk, dn: calls.append(dn) or True,
    )
    _, token = user_and_token
    resp = _install(client, token, ["curio.weather@1"])
    assert resp.status_code == 200
    assert resp.get_json()["installedPackages"] == ["curio.weather@1"]
    assert calls == ["curio.weather@1"]


def test_install_rejects_empty_packages(client, user_and_token, tmp_curio):
    _, token = user_and_token
    resp = _install(client, token, [])
    assert resp.status_code == 400


def test_install_rejects_invalid_dirname(client, user_and_token, tmp_curio, monkeypatch):
    called = False

    def _fake(uk, dn):
        nonlocal called
        called = True
        return True

    monkeypatch.setattr(packages_services, "install_to_store", _fake)
    _, token = user_and_token
    resp = _install(client, token, ["--evil", "curio.weather@1"])
    assert resp.status_code == 400
    assert not called


def test_install_surfaces_service_error(client, user_and_token, tmp_curio, monkeypatch):
    def _fail(uk, dn):
        raise packages_services.PackageServiceError("boom", 502)

    monkeypatch.setattr(packages_services, "install_to_store", _fail)
    _, token = user_and_token
    resp = _install(client, token, ["curio.weather@1"])
    assert resp.status_code == 502
    assert "boom" in resp.get_json()["error"]
