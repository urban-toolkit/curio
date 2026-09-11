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
from types import SimpleNamespace

from utk_curio.backend.app.packages import pip_runner as packages_routes_pip
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


def test_check_defers_install_on_demand_packages(client, user_and_token, tmp_curio):
    """A heavy package is reported missing, but flagged not-to-be-installed.

    Both halves matter and they used to be in tension (#233). The canvas has to
    be able to SAY which package a node needs - saying nothing is what left
    three nodes on "Loading node…" with no explanation. But opening a dataflow
    must not start a ~3 GB torch download on the user's behalf, so the same
    response marks it deferred and the auto-installer skips it.
    """
    _, token = user_and_token
    resp = _check(client, token, ["curio.streetvision@1", "curio.weather@1"])
    assert resp.status_code == 200
    body = resp.get_json()
    # Still reported as missing: the UI needs to name it.
    assert "curio.streetvision@1" in body["packages"]
    assert "curio.weather@1" in body["packages"]
    # ...but only the heavy one is held back.
    assert body["deferred"] == ["curio.streetvision@1"]


def test_check_reports_no_deferrals_for_ordinary_packages(
    client, user_and_token, tmp_curio
):
    """The key is always present, so a caller never has to feature-detect."""
    _, token = user_and_token
    resp = _check(client, token, ["curio.weather@1"])
    assert resp.get_json()["deferred"] == []


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


def test_check_reports_an_installed_but_unimportable_dep_as_broken(
    client, user_and_token, tmp_curio, monkeypatch
):
    """Version-satisfying and still unimportable → reported, NOT flagged for install.

    Metadata presence is not importability: a wheel whose native extension
    cannot load (GDAL, CUDA) records a perfectly good version, so the version
    check alone calls it satisfied and the failure only surfaces later as a raw
    ImportError from whichever node runs first. Reinstalling does not fix it -
    pip says "already satisfied" and does nothing - so it belongs in ``broken``,
    where the client warns, and never in ``packages``, where the client installs.
    """
    _, token = user_and_token
    monkeypatch.setattr(
        packages_routes, "list_user_packageages",
        lambda uk: [Path("curio.weather@1")],
    )
    monkeypatch.setattr(
        packages_services, "_read_python_deps",
        lambda uk, dn: {"flask": ""},
    )
    monkeypatch.setattr(
        packages_routes_pip, "import_failures",
        lambda deps: {d: "ImportError: DLL load failed while importing _base" for d in deps},
    )
    resp = _check(client, token, ["curio.weather@1"])
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["packages"] == [], "a broken extension is not fixed by installing"
    assert body["broken"] == [
        {
            "package": "curio.weather@1",
            "dep": "flask",
            "error": "ImportError: DLL load failed while importing _base",
        }
    ]


def test_check_does_not_probe_a_dep_it_already_flagged_for_install(
    client, user_and_token, tmp_curio, monkeypatch
):
    """A dep pip will install anyway is not also reported as broken.

    Otherwise a plain missing library would produce both a "will install" and a
    "cannot be repaired" message for the same thing, and the second is wrong.
    """
    _, token = user_and_token
    monkeypatch.setattr(
        packages_routes, "list_user_packageages",
        lambda uk: [Path("curio.weather@1")],
    )
    monkeypatch.setattr(
        packages_services, "_read_python_deps",
        lambda uk, dn: {"zzz_not_a_real_package_qq": ">=1"},
    )
    probed: list[set] = []

    def _spy(deps):
        probed.append(set(deps))
        return {d: "should not be consulted" for d in deps}

    monkeypatch.setattr(packages_routes_pip, "import_failures", _spy)
    resp = _check(client, token, ["curio.weather@1"])
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["packages"] == ["curio.weather@1"]
    assert body["broken"] == []
    # The probe is still called once (batched), but with nothing in it - the dep
    # pip will install anyway must not also be reported as unrepairable.
    assert probed == [set()], probed


def test_check_reports_nothing_broken_when_every_dep_imports(
    client, user_and_token, tmp_curio, monkeypatch
):
    """The healthy case, unmocked: flask really is importable here."""
    _, token = user_and_token
    monkeypatch.setattr(
        packages_routes, "list_user_packageages",
        lambda uk: [Path("curio.weather@1")],
    )
    monkeypatch.setattr(
        packages_services, "_read_python_deps",
        lambda uk, dn: {"flask": ""},
    )
    resp = _check(client, token, ["curio.weather@1"])
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["packages"] == []
    assert body["broken"] == []


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
        lambda uk, dn: calls.append(dn) or packages_services.InstallOutcome(copied=True),
    )
    _, token = user_and_token
    resp = _install(client, token, ["curio.weather@1"])
    assert resp.status_code == 200
    assert resp.get_json()["installedPackages"] == ["curio.weather@1"]
    assert calls == ["curio.weather@1"]


def test_install_reports_a_library_that_cannot_be_imported(
    client, user_and_token, tmp_curio, monkeypatch,
):
    """Installing a package is not the same as its libraries working.

    pip counts metadata as satisfaction, so a wheel whose native extension
    cannot load - a rasterio built against a different GDAL is the everyday
    case - installs without complaint. The route answered with a bare
    ``installedPackages`` list, the canvas toasted "Installed", and the user
    met the failure later as a node's ImportError with nothing connecting the
    two.
    """
    monkeypatch.setattr(
        packages_services, "install_to_store",
        lambda uk, dn: packages_services.InstallOutcome(
            copied=True, import_errors={"rasterio": "ImportError: DLL load failed"},
        ),
    )
    _, token = user_and_token

    resp = _install(client, token, ["curio.weather@1"])

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["installedPackages"] == ["curio.weather@1"]
    assert body["importErrors"] == {"rasterio": "ImportError: DLL load failed"}


def test_install_reports_no_import_errors_when_the_libraries_work(
    client, user_and_token, tmp_curio, monkeypatch,
):
    monkeypatch.setattr(
        packages_services, "install_to_store",
        lambda uk, dn: packages_services.InstallOutcome(copied=True),
    )
    _, token = user_and_token

    resp = _install(client, token, ["curio.weather@1"])

    assert resp.status_code == 200
    assert resp.get_json()["importErrors"] == {}


def test_install_rejects_empty_packages(client, user_and_token, tmp_curio):
    _, token = user_and_token
    resp = _install(client, token, [])
    assert resp.status_code == 400


def test_install_rejects_invalid_dirname(client, user_and_token, tmp_curio, monkeypatch):
    called = False

    def _fake(uk, dn):
        nonlocal called
        called = True
        return packages_services.InstallOutcome(copied=True)

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
        return packages_services.InstallOutcome(copied=True)

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
    would mean merely opening a dataflow installs its declared packages -
    bypassing the owner-only gate that ProjectLoader enforces for shared links.
    """
    installs: list[str] = []
    monkeypatch.setattr(
        packages_services, "install_to_store",
        lambda uk, dn: installs.append(dn) or packages_services.InstallOutcome(copied=True),
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

    # 4. The same probe now comes back clean - the load-time flow has converged.
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


# ---------------------------------------------------------------------------
# services.install_to_store — the already-in-store REPAIR branch
# ---------------------------------------------------------------------------


def test_repairing_a_backend_package_rebuilds_its_overlay_not_the_host(
    monkeypatch, tmp_curio,
):
    """The repair has to route like the install did.

    ``/check`` flags an installed package whose declared dep went missing, and
    the repair used to call ``install_python_deps`` unconditionally - putting a
    backend-bearing package's libraries in the shared interpreter its handlers
    never import from. pip exited 0, the dep read as satisfied, and the handler
    kept raising ImportError.
    """
    from utk_curio.backend.app.packages import backend_runtime, pip_runner
    from utk_curio.backend.app.packages import services as svc

    manifest = SimpleNamespace(
        python_deps={"tinylib": "1.0.0"},
        backend=SimpleNamespace(handlers=[SimpleNamespace(name="h")]),
        templates=[SimpleNamespace(engine="javascript", has_code=False)],
    )
    monkeypatch.setattr(svc, "_is_installed_in_user_store", lambda uk, dn: True)
    monkeypatch.setattr(svc, "_read_manifest", lambda uk, dn: manifest)
    monkeypatch.setattr(
        svc, "_declared_import_failures", lambda uk, dn, m=None: {})

    built: list[tuple] = []
    monkeypatch.setattr(
        backend_runtime, "build_overlay",
        lambda uk, dn, deps, on_line=None: built.append((dn, dict(deps)))
        or {"libs": ["tinylib==1.0.0"], "bytes": 5},
    )

    def _never_host(deps, on_line=None):  # pragma: no cover
        raise AssertionError("host pip must not run for overlay-only routing")

    monkeypatch.setattr(pip_runner, "install_python_deps", _never_host)

    outcome = svc.install_to_store("1", "my.pkg@1")

    assert built == [("my.pkg@1", {"tinylib": "1.0.0"})]
    assert outcome.copied is False
    # Host portion empty → no restart notice (dev/92 narrowed by dev/97).
    assert outcome.installed == []


def test_a_working_overlay_is_not_wiped_and_rebuilt_on_every_ask(
    monkeypatch, tmp_curio, tmp_path,
):
    """``/workflow-deps/check`` asks again on every dataflow open.

    It decides what a dataflow needs from HOST metadata, so a backend-bearing
    package's overlay-only deps read as missing every time and the repair runs.
    ``build_overlay`` wipes before it builds, so answering that with a rebuild
    deletes a working overlay and re-runs pip over the network - and offline,
    where the rebuild fails, leaves the package with no overlay at all.
    """
    from utk_curio.backend.app.packages import backend_runtime, pip_runner
    from utk_curio.backend.app.packages import services as svc

    overlay = tmp_path / "overlay"
    overlay.mkdir()
    monkeypatch.setattr(backend_runtime, "overlay_dir_for", lambda uk, dn: overlay)
    monkeypatch.setattr(pip_runner, "import_failures_in", lambda deps, path: {})

    def _never(uk, dn, deps, on_line=None):  # pragma: no cover
        raise AssertionError("wiped and rebuilt an overlay that already works")

    monkeypatch.setattr(backend_runtime, "build_overlay", _never)

    manifest = SimpleNamespace(
        python_deps={"tinylib": "1.0.0"},
        backend=SimpleNamespace(handlers=[SimpleNamespace(name="h")]),
        templates=[SimpleNamespace(engine="javascript", has_code=False)],
    )
    outcome = svc.provision_python_deps("1", "my.pkg@1", manifest)

    assert outcome.import_errors == {}
    assert overlay.is_dir(), "the working overlay must still be there"


def test_a_healthy_overlay_is_probed_once_per_install(monkeypatch, tmp_curio, tmp_path):
    """Deciding whether to rebuild and reporting the verdict are one question.

    They were asked separately - once to condition the rebuild, once to fill in
    importErrors - and the overlay probe is deliberately unmemoised, so a
    working overlay paid two full subprocesses of cold imports for one install.
    """
    from utk_curio.backend.app.packages import backend_runtime, pip_runner
    from utk_curio.backend.app.packages import services as svc

    overlay = tmp_path / "overlay"
    overlay.mkdir()
    monkeypatch.setattr(backend_runtime, "overlay_dir_for", lambda uk, dn: overlay)
    probes: list = []
    monkeypatch.setattr(
        pip_runner, "import_failures_in",
        lambda deps, path: probes.append(sorted(deps)) or {})
    monkeypatch.setattr(
        backend_runtime, "build_overlay",
        lambda uk, dn, deps, on_line=None: (_ for _ in ()).throw(
            AssertionError("rebuilt a working overlay")))

    manifest = SimpleNamespace(
        python_deps={"tinylib": "1.0.0"},
        backend=SimpleNamespace(handlers=[SimpleNamespace(name="h")]),
        templates=[SimpleNamespace(engine="javascript", has_code=False)],
    )
    outcome = svc.provision_python_deps("1", "my.pkg@1", manifest)

    assert probes == [["tinylib"]], f"expected one overlay probe, got {len(probes)}"
    assert outcome.import_errors == {}


def test_a_rebuilt_overlay_reports_the_new_verdict(monkeypatch, tmp_curio, tmp_path):
    """After a rebuild the answer must come from the overlay that now exists,
    not from the one the rebuild replaced."""
    from utk_curio.backend.app.packages import backend_runtime, pip_runner
    from utk_curio.backend.app.packages import services as svc

    overlay = tmp_path / "overlay"
    overlay.mkdir()
    monkeypatch.setattr(backend_runtime, "overlay_dir_for", lambda uk, dn: overlay)
    monkeypatch.setattr(
        backend_runtime, "build_overlay",
        lambda uk, dn, deps, on_line=None: {"libs": [], "bytes": 1})
    answers = iter([
        {"tinylib": "ImportError: before"},   # broken, so it rebuilds
        {"tinylib": "ImportError: after"},    # still broken afterwards
    ])
    monkeypatch.setattr(
        pip_runner, "import_failures_in", lambda deps, path: next(answers))

    manifest = SimpleNamespace(
        python_deps={"tinylib": "1.0.0"},
        backend=SimpleNamespace(handlers=[SimpleNamespace(name="h")]),
        templates=[SimpleNamespace(engine="javascript", has_code=False)],
    )
    outcome = svc.provision_python_deps("1", "my.pkg@1", manifest)

    assert outcome.import_errors == {"tinylib": "ImportError: after"}


def test_a_broken_overlay_is_still_rebuilt(monkeypatch, tmp_curio, tmp_path):
    """The other half: skipping the rebuild must not mean never repairing."""
    from utk_curio.backend.app.packages import backend_runtime, pip_runner
    from utk_curio.backend.app.packages import services as svc

    overlay = tmp_path / "overlay"
    overlay.mkdir()
    monkeypatch.setattr(backend_runtime, "overlay_dir_for", lambda uk, dn: overlay)
    monkeypatch.setattr(
        pip_runner, "import_failures_in",
        lambda deps, path: {"tinylib": "ImportError: boom"})
    built: list = []
    monkeypatch.setattr(
        backend_runtime, "build_overlay",
        lambda uk, dn, deps, on_line=None: built.append(dn) or {"libs": [], "bytes": 1})

    manifest = SimpleNamespace(
        python_deps={"tinylib": "1.0.0"},
        backend=SimpleNamespace(handlers=[SimpleNamespace(name="h")]),
        templates=[SimpleNamespace(engine="javascript", has_code=False)],
    )
    svc.provision_python_deps("1", "my.pkg@1", manifest)

    assert built == ["my.pkg@1"]


def test_an_overlay_that_was_never_built_is_built(monkeypatch, tmp_curio, tmp_path):
    """A first install has nothing to preserve."""
    from utk_curio.backend.app.packages import backend_runtime, pip_runner
    from utk_curio.backend.app.packages import services as svc

    monkeypatch.setattr(
        backend_runtime, "overlay_dir_for", lambda uk, dn: tmp_path / "absent")
    monkeypatch.setattr(pip_runner, "import_failures_in", lambda deps, path: {})
    built: list = []
    monkeypatch.setattr(
        backend_runtime, "build_overlay",
        lambda uk, dn, deps, on_line=None: built.append(dn) or {"libs": [], "bytes": 1})

    manifest = SimpleNamespace(
        python_deps={"tinylib": "1.0.0"},
        backend=SimpleNamespace(handlers=[SimpleNamespace(name="h")]),
        templates=[SimpleNamespace(engine="javascript", has_code=False)],
    )
    svc.provision_python_deps("1", "my.pkg@1", manifest)

    assert built == ["my.pkg@1"]


def test_repairing_an_installed_package_still_reports_a_broken_library(
    monkeypatch, tmp_curio,
):
    """The branch that changes nothing is exactly where the lie lived.

    pip skips a dep whose metadata already satisfies the requirement, so the
    repair run for a broken wheel is a no-op that exits 0. Without a probe the
    route answers "installed" and the user meets the failure as a node's
    ImportError.
    """
    from utk_curio.backend.app.packages import pip_runner
    from utk_curio.backend.app.packages import services as svc

    manifest = SimpleNamespace(
        python_deps={"rasterio": ""}, backend=None,
        templates=[SimpleNamespace(engine="python", has_code=True)],
    )
    monkeypatch.setattr(svc, "_is_installed_in_user_store", lambda uk, dn: True)
    monkeypatch.setattr(svc, "_read_manifest", lambda uk, dn: manifest)
    monkeypatch.setattr(
        pip_runner, "install_python_deps",
        lambda deps, on_line=None: pip_runner.InstallReport(
            installed=[], skipped=["rasterio"]),
    )
    monkeypatch.setattr(
        pip_runner, "import_failures",
        lambda deps: {"rasterio": "ImportError: DLL load failed"},
    )

    outcome = svc.install_to_store("1", "my.pkg@1")

    assert outcome.import_errors == {"rasterio": "ImportError: DLL load failed"}
    assert outcome.installed == []


# ---------------------------------------------------------------------------
# services._declared_import_failures — the rule EVERY install path shares
# ---------------------------------------------------------------------------
#
# The route-by-route version of this check kept missing surfaces, so it lives
# at the service seam now: one function, consulted by whichever install path
# ran, which is why these tests call it directly rather than through a route.


def _manifest(python_deps, *, backend=None, templates=()):
    return SimpleNamespace(
        python_deps=dict(python_deps), backend=backend, templates=list(templates),
    )


def test_declared_import_failures_probes_the_manifests_deps(monkeypatch):
    """It must probe what the manifest declares, not what pip happened to fetch.

    The broken case is precisely the one where pip fetched nothing, because the
    metadata already satisfied the requirement.
    """
    probed: list[list[str]] = []
    import utk_curio.backend.app.packages.pip_runner as pip_runner
    monkeypatch.setattr(
        pip_runner, "import_failures",
        lambda deps: probed.append(sorted(deps)) or {"rasterio": "ImportError: boom"},
    )

    out = packages_services._declared_import_failures(
        "1", "curio.weather@1", _manifest({"rasterio": ">=1.3", "numpy": ""}),
    )

    assert out == {"rasterio": "ImportError: boom"}
    assert probed == [["numpy", "rasterio"]]


def test_declared_import_failures_is_empty_when_nothing_is_declared(monkeypatch):
    """No declared deps means no probe at all - the 19s cost is not free."""
    called = False

    def _probe(deps):
        nonlocal called
        called = True
        return {}

    import utk_curio.backend.app.packages.pip_runner as pip_runner
    monkeypatch.setattr(pip_runner, "import_failures", _probe)

    assert packages_services._declared_import_failures("1", "x@1", _manifest({})) == {}
    assert not called


def test_a_probe_that_raises_does_not_fail_the_install(monkeypatch):
    """The install succeeded; a broken probe must not turn that into an error."""
    import utk_curio.backend.app.packages.pip_runner as pip_runner

    def _boom(deps):
        raise OSError("no interpreter")

    monkeypatch.setattr(pip_runner, "import_failures", _boom)

    assert packages_services._declared_import_failures(
        "1", "x@1", _manifest({"rasterio": ""}),
    ) == {}


def test_a_backend_packages_deps_are_probed_in_the_overlay_not_the_host(
    monkeypatch, tmp_path,
):
    """The overlay is a different environment, so it is a different question.

    ``install_python_deps_to_target`` puts a backend-bearing package's libraries
    in a directory the backend process never imports from; workers get it on
    PYTHONPATH. Asking the host would report every one of them "not installed" -
    a failure that isn't there - and would vouch for nothing that is.
    """
    from utk_curio.backend.app.packages import backend_runtime, pip_runner

    overlay = tmp_path / "overlay"
    overlay.mkdir()
    monkeypatch.setattr(
        backend_runtime, "overlay_dir_for", lambda uk, dn: overlay)

    def _never_host(deps):  # pragma: no cover - the assertion is that it is unused
        raise AssertionError("the host was probed for an overlay-only package")

    seen: list[tuple[list[str], str]] = []
    monkeypatch.setattr(pip_runner, "import_failures", _never_host)
    monkeypatch.setattr(
        pip_runner, "import_failures_in",
        lambda deps, path: seen.append((sorted(deps), path))
        or {"tinylib": "ImportError: boom"},
    )

    manifest = _manifest(
        {"tinylib": "1.0.0"},
        backend=SimpleNamespace(handlers=[SimpleNamespace(name="h")]),
        templates=[SimpleNamespace(engine="javascript", has_code=False)],
    )
    out = packages_services._declared_import_failures("1", "pkg@1", manifest)

    assert out == {"tinylib": "ImportError: boom"}
    assert seen == [(["tinylib"], str(overlay))]


def test_an_overlay_that_was_never_built_is_reported_not_passed_over(
    monkeypatch, tmp_path,
):
    """Reaching this branch means the deps are declared AND routed to an overlay.

    So a missing directory is exactly the state where the package's handlers
    cannot import what they need - it happens when an offline sideload's
    ``build_overlay`` fails and rmtree's the half-build on the way out. This
    used to answer ``{}``, which is a clean bill of health nobody earned, on the
    one shape where the libraries are hardest to reach.
    """
    from utk_curio.backend.app.packages import backend_runtime, pip_runner

    monkeypatch.setattr(
        backend_runtime, "overlay_dir_for", lambda uk, dn: tmp_path / "never-built")

    def _boom(*a, **kw):  # pragma: no cover
        raise AssertionError("probed an overlay that does not exist")

    monkeypatch.setattr(pip_runner, "import_failures_in", _boom)
    monkeypatch.setattr(pip_runner, "import_failures", _boom)

    manifest = _manifest(
        {"tinylib": "1.0.0"},
        backend=SimpleNamespace(handlers=[SimpleNamespace(name="h")]),
        templates=[SimpleNamespace(engine="javascript", has_code=False)],
    )
    out = packages_services._declared_import_failures("1", "pkg@1", manifest)

    # Named, with a reason that says what to do about it - and without spawning
    # a probe against a directory nothing wrote to.
    assert list(out) == ["tinylib"]
    assert "overlay has not been built" in out["tinylib"]


def test_a_both_destination_package_is_probed_in_both_environments(
    monkeypatch, tmp_path,
):
    """A python template and a backend handler read from different sys.paths.

    Vouching for one and not the other is how a package ships half-working.
    """
    from utk_curio.backend.app.packages import backend_runtime, pip_runner

    overlay = tmp_path / "overlay"
    overlay.mkdir()
    monkeypatch.setattr(
        backend_runtime, "overlay_dir_for", lambda uk, dn: overlay)
    monkeypatch.setattr(
        pip_runner, "import_failures_in", lambda deps, path: {"a": "overlay broke"})
    monkeypatch.setattr(
        pip_runner, "import_failures", lambda deps: {"b": "host broke"})

    manifest = _manifest(
        {"a": "", "b": ""},
        backend=SimpleNamespace(handlers=[SimpleNamespace(name="h")]),
        templates=[SimpleNamespace(engine="python", has_code=True)],
    )
    assert packages_services._declared_import_failures("1", "pkg@1", manifest) == {
        "a": "overlay broke", "b": "host broke",
    }


def test_an_unreadable_manifest_reports_nothing_rather_than_guessing(monkeypatch):
    """A manifest that will not parse is a different complaint from this one."""
    monkeypatch.setattr(packages_services, "_read_manifest", lambda uk, dn: None)
    assert packages_services._declared_import_failures("1", "x@1") == {}
