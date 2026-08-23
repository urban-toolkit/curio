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


def test_install_abandons_the_partial_set_on_a_mid_loop_failure(
    client, user_and_token, tmp_curio, monkeypatch
):
    """A failure part-way through discards the names that already installed.

    The route returns on the first PackageServiceError, so ``installedPackages``
    never reaches the client even for the packages that succeeded. The frontend
    consequently reports "Could not install a, b" for the whole set. Pinning it
    because the alternative (report partial success) is a plausible future
    change that should be made deliberately, not by accident.
    """
    attempted: list[str] = []

    def _second_fails(uk, dn):
        attempted.append(dn)
        if dn == "ai.urbanlab.uhvi@1":
            raise packages_services.PackageServiceError("no wheel", 502)
        return True

    monkeypatch.setattr(packages_services, "install_to_store", _second_fails)
    _, token = user_and_token
    resp = _install(client, token, ["curio.example-ui@1", "ai.urbanlab.uhvi@1"])
    assert resp.status_code == 502
    assert "ai.urbanlab.uhvi@1" in resp.get_json()["error"]
    # The first one really was installed, but the response says nothing about it.
    assert attempted == ["curio.example-ui@1", "ai.urbanlab.uhvi@1"]
    assert "installedPackages" not in resp.get_json()


# ---------------------------------------------------------------------------
# The load-time cycle: declare -> check -> install -> check
# ---------------------------------------------------------------------------

def test_check_is_a_pure_probe_and_installs_nothing(
    client, user_and_token, tmp_curio, monkeypatch
):
    """/check must not have side effects.

    The frontend probes on *every* dataflow load, so a side-effecting check
    would mean merely opening a dataflow installs its declared packages —
    bypassing the owner-only gate that ProjectLoader enforces for shared links.
    """
    installs: list[str] = []
    monkeypatch.setattr(
        packages_services, "install_to_store",
        lambda uk, dn: installs.append(dn) or True,
    )
    _, token = user_and_token
    resp = _check(client, token, ["curio.example-ui@1", "curio.weather@1"])
    assert resp.status_code == 200
    assert resp.get_json()["packages"] == ["curio.example-ui@1", "curio.weather@1"]
    assert installs == []


def test_check_accepts_an_empty_declaration(client, user_and_token, tmp_curio):
    """A dataflow with no declared packages probes clean, not 400.

    Unlike /install (which 400s on an empty list, since installing nothing is a
    caller bug), /check is called unconditionally by the loader.
    """
    _, token = user_and_token
    resp = _check(client, token, [])
    assert resp.status_code == 200
    assert resp.get_json()["packages"] == []


def test_declared_package_is_installed_and_then_probes_clean(
    client, user_and_token, tmp_curio
):
    """The real load-time cycle, unstubbed: needed -> install -> satisfied.

    Every other /install test stubs ``install_to_store``, so none of them prove
    that installing actually satisfies the check. This one runs the production
    service against the committed catalog. ``curio.example-ui@1`` is the target
    because it declares no python deps, so the store copy is the only work done.
    """
    _, token = user_and_token
    declared = ["curio.example-ui@1"]

    # 1. A fresh user has only curio.builtin seeded, so it reads as needed.
    assert _check(client, token, declared).get_json()["packages"] == declared

    # 2. Install it for real.
    resp = _install(client, token, declared)
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["installedPackages"] == declared

    # 3. It is now in the store and listed by the packages API.
    listing = client.get("/api/packages", headers=_auth(token)).get_json()["packages"]
    assert "curio.example-ui" in {p["packageId"] for p in listing}

    # 4. The same probe now comes back clean — the load-time flow has converged.
    assert _check(client, token, declared).get_json()["packages"] == []


def test_installing_a_declared_package_twice_is_idempotent(
    client, user_and_token, tmp_curio
):
    """Re-loading the same dataflow must not fail on the second install.

    ``install_to_store`` short-circuits when the package is already in the
    store, so a reload that races the check (or a check that flags a package for
    a missing dep) stays a no-op rather than hitting the installer's
    "already installed" guard.
    """
    _, token = user_and_token
    declared = ["curio.example-ui@1"]
    assert _install(client, token, declared).status_code == 200
    second = _install(client, token, declared)
    assert second.status_code == 200, second.get_json()
    assert second.get_json()["installedPackages"] == declared
