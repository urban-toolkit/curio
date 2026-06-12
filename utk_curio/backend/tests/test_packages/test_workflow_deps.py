"""Integration tests for /api/packages/workflow-deps/{check,install}.

These power the load-time "this dataflow needs X, Y — installing" toast:
the frontend posts the loaded spec's nodes + lockfile to ``/check`` and
pipes the reported missing deps into ``/install``. The inline AST scan is
the part that matters for the bundled examples — e.g. example 09 imports
pythermalcomfort inside curio.builtin code nodes, so its ``dataflow.packages``
lockfile is empty and lockfile resolution alone can't see the need.
"""

from __future__ import annotations

import json

from utk_curio.backend.app.packages import pip_runner


def _auth(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _check(client, token, nodes=None, packages=None):
    return client.post(
        "/api/packages/workflow-deps/check",
        headers=_auth(token),
        data=json.dumps({"nodes": nodes or [], "packages": packages or []}),
    )


# ---------------------------------------------------------------------------
# POST /workflow-deps/check
# ---------------------------------------------------------------------------

def test_check_reports_missing_inline_import(client, user_and_token, tmp_curio):
    """A node importing a nonexistent module lands in ``missing``; one
    importing a framework lib (flask is always present — the backend runs
    on it) lands in ``satisfied``; stdlib imports are filtered out."""
    _, token = user_and_token
    nodes = [
        {"content": "import zzz_not_a_real_package_qq\nreturn 1"},
        {"content": "import flask\nimport os\nreturn 2"},
    ]
    resp = _check(client, token, nodes=nodes)
    assert resp.status_code == 200
    body = resp.get_json()
    missing_names = {m["name"] for m in body["missing"]}
    assert "zzz_not_a_real_package_qq" in missing_names
    assert "flask" in body["satisfied"]
    assert "os" not in missing_names and "os" not in body["satisfied"]


def test_check_skips_non_python_content(client, user_and_token, tmp_curio):
    """JS node sources fail the Python AST parse and contribute nothing."""
    _, token = user_and_token
    nodes = [{"content": "import * as lib from '@urban-toolkit/autk-db';\nreturn 1;"}]
    resp = _check(client, token, nodes=nodes)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["missing"] == []
    assert body["satisfied"] == []


def test_check_treats_importable_alias_dist_as_satisfied(client, user_and_token, tmp_curio):
    """An inline import whose import name differs from its PyPI distribution
    name (dateutil -> python-dateutil) must NOT be reported missing — the
    importability fallback keeps it off the auto-install path. python-dateutil
    is a transitive dep of pandas, so it is always present in the env."""
    _, token = user_and_token
    nodes = [{"content": "import dateutil\nreturn 1"}]
    resp = _check(client, token, nodes=nodes)
    assert resp.status_code == 200
    body = resp.get_json()
    assert "dateutil" in body["satisfied"]
    assert all(m["name"] != "dateutil" for m in body["missing"])


def test_check_merges_lockfile_deps_with_ranged_specs(
    client, user_and_token, tmp_curio, monkeypatch
):
    """Lockfile packages contribute their manifests' ranged specs, which
    win over the bare inline names."""
    _, token = user_and_token

    class _FakeResult:
        python_deps = {"zzz_not_a_real_package_qq": ">=9.9"}

    from utk_curio.backend.app.packages import routes as packages_routes
    monkeypatch.setattr(
        packages_routes, "resolve_for_project", lambda *a, **k: _FakeResult()
    )

    nodes = [{"content": "import zzz_not_a_real_package_qq"}]
    resp = _check(client, token, nodes=nodes, packages=["curio.weather@1"])
    assert resp.status_code == 200
    body = resp.get_json()
    assert {"name": "zzz_not_a_real_package_qq", "spec": ">=9.9"} in body["missing"]


def test_check_tolerates_lockfile_resolution_failure(client, user_and_token, tmp_curio):
    """A bogus lockfile entry must not block the inline scan (best-effort)."""
    _, token = user_and_token
    nodes = [{"content": "import zzz_not_a_real_package_qq"}]
    resp = _check(client, token, nodes=nodes, packages=["no.such.package@1"])
    assert resp.status_code == 200
    missing_names = {m["name"] for m in resp.get_json()["missing"]}
    assert "zzz_not_a_real_package_qq" in missing_names


def test_check_rejects_malformed_body(client, user_and_token, tmp_curio):
    _, token = user_and_token
    resp = client.post(
        "/api/packages/workflow-deps/check",
        headers=_auth(token),
        data=json.dumps({"nodes": "not-a-list"}),
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# POST /workflow-deps/install
# ---------------------------------------------------------------------------

def test_install_batches_through_pip_runner(client, user_and_token, tmp_curio, monkeypatch):
    captured: dict = {}

    # Mirror the real InstallReport shape: ``installed`` holds pip argv specs,
    # ``skipped`` holds bare names. The route passes the report through verbatim.
    def _fake_install(deps, **kwargs):
        captured.update(deps)
        return pip_runner.InstallReport(
            installed=["pythermalcomfort~=3.9"], skipped=["rasterstats"]
        )

    monkeypatch.setattr(pip_runner, "install_python_deps", _fake_install)
    _, token = user_and_token
    resp = client.post(
        "/api/packages/workflow-deps/install",
        headers=_auth(token),
        data=json.dumps({"deps": {"pythermalcomfort": "^3.9", "rasterstats": ""}}),
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["installed"] == ["pythermalcomfort~=3.9"]
    assert body["skipped"] == ["rasterstats"]
    # The route forwards the cleaned deps dict unchanged to pip_runner.
    assert captured == {"pythermalcomfort": "^3.9", "rasterstats": ""}


def test_install_rejects_flag_smuggling_names(client, user_and_token, tmp_curio, monkeypatch):
    """Names are validated so a hostile spec can't become a pip flag."""
    called = False

    def _fake_install(deps, **kwargs):
        nonlocal called
        called = True
        return pip_runner.InstallReport(installed=[], skipped=[])

    monkeypatch.setattr(pip_runner, "install_python_deps", _fake_install)
    _, token = user_and_token
    for bad in ("--index-url=https://evil", "name with spaces", ""):
        resp = client.post(
            "/api/packages/workflow-deps/install",
            headers=_auth(token),
            data=json.dumps({"deps": {bad: ""}}),
        )
        assert resp.status_code == 400, bad
    assert not called


def test_install_rejects_empty_deps(client, user_and_token, tmp_curio):
    _, token = user_and_token
    resp = client.post(
        "/api/packages/workflow-deps/install",
        headers=_auth(token),
        data=json.dumps({"deps": {}}),
    )
    assert resp.status_code == 400


def test_install_surfaces_pip_failure_as_502(client, user_and_token, tmp_curio, monkeypatch):
    def _fail(deps, **kwargs):
        raise pip_runner.PipInstallError("pip install failed (exit 1): boom")

    monkeypatch.setattr(pip_runner, "install_python_deps", _fail)
    _, token = user_and_token
    resp = client.post(
        "/api/packages/workflow-deps/install",
        headers=_auth(token),
        data=json.dumps({"deps": {"numpy": ""}}),
    )
    assert resp.status_code == 502
    assert "boom" in resp.get_json()["error"]
