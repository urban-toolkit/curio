"""Tests for the per-user 'Installed libraries' surface.

Covers the storage helpers (``libraries.py``) and the HTTP endpoints
(``GET/POST/DELETE /api/packages/libraries``). The pip runner is stubbed
by ``conftest.py`` so these tests don't shell out.
"""

from __future__ import annotations

import json

import pytest

from utk_curio.backend.app.packages import libraries as libs
from utk_curio.backend.app.packages import pip_runner
from utk_curio.backend.app.packages import routes as packages_routes
from utk_curio.backend.app.packages.pip_runner import InstallReport, UninstallReport


def _auth(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def test_load_missing_file_returns_empty(tmp_curio):
    data = libs.list_standalone("guest")
    assert data == {"python": [], "js": []}


def test_add_then_list_round_trip(tmp_curio):
    libs.add_library("guest", "python", "numpy")
    libs.add_library("guest", "python", "scikit-learn==1.4.0")
    data = libs.list_standalone("guest")
    assert sorted(data["python"]) == ["numpy", "scikit-learn==1.4.0"]
    assert data["js"] == []


def test_add_is_idempotent(tmp_curio):
    libs.add_library("guest", "python", "numpy")
    libs.add_library("guest", "python", "numpy")
    assert libs.list_standalone("guest")["python"] == ["numpy"]


def test_add_rejects_unknown_kind(tmp_curio):
    try:
        libs.add_library("guest", "rust", "tokio")
    except ValueError as e:
        assert "kind" in str(e)
    else:  # pragma: no cover
        raise AssertionError("expected ValueError")


def test_remove_idempotent(tmp_curio):
    libs.add_library("guest", "python", "numpy")
    libs.remove_library("guest", "python", "numpy")
    libs.remove_library("guest", "python", "numpy")  # already gone
    assert libs.list_standalone("guest")["python"] == []


def test_corrupt_file_is_treated_as_empty(tmp_curio):
    p = libs._path("guest")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{not json", encoding="utf-8")
    assert libs.list_standalone("guest") == {"python": [], "js": []}


def test_package_derived_reads_installed_manifests(
    tmp_curio, install_packageage, manifest_dict,
):
    install_packageage(
        "guest",
        manifest=manifest_dict(
            package_id="ai.test.pyheavy",
            python_deps={"torch": ">=2.0", "transformers": "~=4.30"},
        ),
    )
    derived = libs.package_derived("guest")
    derived_python = sorted([(e.name, e.spec) for e in derived if e.kind == "python"])
    assert ("torch", ">=2.0") in derived_python
    assert ("transformers", "~=4.30") in derived_python
    assert all(e.source.startswith("ai.test.pyheavy@") for e in derived if e.kind == "python")


def test_package_derived_reports_real_install_state(
    tmp_curio, install_packageage, manifest_dict,
):
    """A package can declare a dep that isn't actually installed — the entry
    must report ``installed`` truthfully (flask present, a bogus name absent),
    so the modal stops showing declared-but-missing libs as installed."""
    install_packageage(
        "guest",
        manifest=manifest_dict(
            package_id="ai.test.realstate",
            python_deps={"flask": "", "zzz_not_a_real_package_qq": ">=1"},
        ),
    )
    derived = {e.name: e for e in libs.package_derived("guest") if e.kind == "python"}
    assert derived["flask"].installed is True
    assert derived["zzz_not_a_real_package_qq"].installed is False


def test_aggregate_combines_standalone_and_package(
    tmp_curio, install_packageage, manifest_dict,
):
    libs.add_library("guest", "python", "scikit-learn==1.4")
    install_packageage(
        "guest",
        manifest=manifest_dict(
            package_id="ai.test.combine",
            python_deps={"numpy": "^1.26"},
        ),
    )
    agg = libs.aggregate("guest")
    assert agg.standalone["python"] == ["scikit-learn==1.4"]
    package_names = {e.name for e in agg.from_packages}
    assert "numpy" in package_names


# ---------------------------------------------------------------------------
# HTTP endpoints
# ---------------------------------------------------------------------------

class TestLibraryRoutes:
    def test_list_empty_for_fresh_user(self, client, user_and_token):
        _, token = user_and_token
        resp = client.get("/api/packages/libraries", headers=_auth(token))
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["standalone"] == {"python": [], "js": []}
        # Fresh user is auto-seeded with curio.builtin@1 which has no deps
        assert isinstance(body["fromPackages"], list)

    def test_post_python_then_list(self, client, user_and_token):
        _, token = user_and_token
        resp = client.post(
            "/api/packages/libraries",
            json={"kind": "python", "spec": "numpy"},
            headers=_auth(token),
        )
        assert resp.status_code == 201, resp.get_data(as_text=True)
        listed = client.get("/api/packages/libraries", headers=_auth(token)).get_json()
        assert listed["standalone"]["python"] == ["numpy"]

    def test_post_rejects_empty_spec(self, client, user_and_token):
        _, token = user_and_token
        resp = client.post(
            "/api/packages/libraries",
            json={"kind": "python", "spec": "  "},
            headers=_auth(token),
        )
        assert resp.status_code == 400

    def test_post_js_returns_501_not_supported(self, client, user_and_token):
        _, token = user_and_token
        resp = client.post(
            "/api/packages/libraries",
            json={"kind": "js", "spec": "lodash"},
            headers=_auth(token),
        )
        assert resp.status_code == 501

    def test_delete_round_trip(self, client, user_and_token):
        _, token = user_and_token
        client.post(
            "/api/packages/libraries",
            json={"kind": "python", "spec": "numpy"},
            headers=_auth(token),
        )
        resp = client.delete(
            "/api/packages/libraries/python/numpy",
            headers=_auth(token),
        )
        assert resp.status_code == 200
        assert resp.get_json()["standalone"]["python"] == []

    def test_post_includes_package_derived_in_list(
        self, client, user_and_token, install_packageage, manifest_dict,
    ):
        from utk_curio.backend.app.projects.services import _user_dir_key
        user, token = user_and_token
        install_packageage(
            _user_dir_key(user),
            manifest=manifest_dict(
                package_id="ai.test.routes",
                python_deps={"requests": ">=2.0"},
            ),
        )
        body = client.get("/api/packages/libraries", headers=_auth(token)).get_json()
        derived_names = [e["name"] for e in body["fromPackages"]]
        assert "requests" in derived_names


# ---------------------------------------------------------------------------
# Spec parsing + the pip-uninstall ref-count gate
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "spec, expected",
    [
        ("numpy", ("numpy", "")),
        ("  numpy  ", ("numpy", "")),
        ("scikit-learn==1.4.0", ("scikit-learn", "==1.4.0")),
        ("pkg>=1", ("pkg", ">=1")),
        ("pkg<=2", ("pkg", "<=2")),
        ("pkg~=2.1", ("pkg", "~=2.1")),
        ("pkg!=3", ("pkg", "!=3")),
        ("pkg<4,>=2", ("pkg", "<4,>=2")),
        # npm-ish separator: the '@' is consumed, the version kept verbatim.
        ("pkg@1.2", ("pkg", "1.2")),
        # A leading '@' is a scoped name, not a separator — splitting there
        # would yield the meaningless name "". The guard is blunt though: it
        # skips the '@' branch entirely, so a *versioned* scoped name keeps its
        # version in the name. Latent rather than live — scoped names only arise
        # for JS specs, and JS install/remove both 501 (no runner exists).
        ("@scope/pkg", ("@scope/pkg", "")),
        ("@scope/pkg@1.2", ("@scope/pkg@1.2", "")),
    ],
)
def test_split_lib_spec(spec, expected):
    assert packages_routes._split_lib_spec(spec) == expected


def test_remove_keeps_a_library_a_package_still_declares(
    client, user_and_token, tmp_curio, monkeypatch, install_packageage, manifest_dict,
):
    """Removing a standalone entry must not pip-uninstall a package's dependency.

    Both can name the same library. The standalone list is the user's own, but
    an installed package needs the lib to run, so the ref-count gate keeps it on
    disk and only drops the list entry.
    """
    from utk_curio.backend.app.projects.services import _user_dir_key

    user, token = user_and_token
    install_packageage(
        _user_dir_key(user),
        manifest=manifest_dict(package_id="ai.test.needsflask", python_deps={"flask": ""}),
    )

    uninstalled: list[list[str]] = []
    monkeypatch.setattr(
        pip_runner,
        "uninstall_python_deps",
        lambda names: uninstalled.append(list(names))
        or UninstallReport(removed=[], kept=list(names)),
    )

    client.post(
        "/api/packages/libraries",
        headers=_auth(token),
        data=json.dumps({"kind": "python", "spec": "flask"}),
    )
    resp = client.delete("/api/packages/libraries/python/flask", headers=_auth(token))

    assert resp.status_code == 200
    assert "flask" not in resp.get_json()["standalone"]["python"]
    assert uninstalled == [], "a package still declares flask — it must stay installed"


def test_remove_uninstalls_a_library_no_package_declares(
    client, user_and_token, tmp_curio, monkeypatch,
):
    """The mirror case: nothing else needs it, so it really is pip-uninstalled."""
    _, token = user_and_token
    uninstalled: list[list[str]] = []
    monkeypatch.setattr(
        pip_runner,
        "uninstall_python_deps",
        lambda names: uninstalled.append(list(names))
        or UninstallReport(removed=list(names), kept=[]),
    )

    client.post(
        "/api/packages/libraries",
        headers=_auth(token),
        data=json.dumps({"kind": "python", "spec": "inflection"}),
    )
    resp = client.delete(
        "/api/packages/libraries/python/inflection", headers=_auth(token)
    )

    assert resp.status_code == 200
    assert uninstalled == [["inflection"]]


def test_delete_js_library_returns_501(client, user_and_token, tmp_curio):
    """DELETE mirrors POST: there is no JS runner, so neither direction works."""
    _, token = user_and_token
    resp = client.delete("/api/packages/libraries/js/lodash", headers=_auth(token))
    assert resp.status_code == 501
    assert "not yet supported" in resp.get_json()["error"]


def test_js_add_never_reaches_pip(client, user_and_token, tmp_curio, monkeypatch):
    """The 501 returns before the installer, so no pip process is started."""
    _, token = user_and_token
    calls: list[dict] = []
    monkeypatch.setattr(
        pip_runner,
        "install_python_deps",
        lambda deps, **kw: calls.append(dict(deps))
        or InstallReport(installed=[], skipped=[]),
    )
    resp = client.post(
        "/api/packages/libraries",
        headers=_auth(token),
        data=json.dumps({"kind": "js", "spec": "lodash"}),
    )
    assert resp.status_code == 501
    assert calls == []
