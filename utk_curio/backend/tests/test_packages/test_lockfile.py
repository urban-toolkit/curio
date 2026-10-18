"""Tests for the per-project lockfile + per-user defaults model.

Covers the four pieces added in the lockfile epic:

  * ``spec_packages`` pure helpers (backfill from node types).
  * ``defaults`` file I/O.
  * ``services`` orchestration (install_to_project, install_to_defaults,
    uninstall_from_project, prune_unreferenced_packages).
  * REST endpoints under ``/api/packages/projects/...`` and
    ``/api/packages/defaults``.

Uses real catalog packages (``ai.utk.uhvi@1``, ``curio.builtin``)
so the install paths exercise the same code as production.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from utk_curio.backend.app.packages.repositories import defaults as defaults_io
from utk_curio.backend.app.packages import service as packages_services
from utk_curio.backend.app.packages.application import (
    store_install,
    store_reads,
)
from utk_curio.backend.app.packages.domain.spec_packages import (
    dir_name_from_node_type,
    preserve_project_packages,
    project_packages,
    referencing_nodes,
    set_project_packages,
)
from utk_curio.backend.app.packages.repositories.store import (
    package_dir,
    user_packages_dir,
)
from utk_curio.backend.app.projects import services as projects_services
from utk_curio.backend.app.projects import storage as projects_storage
from utk_curio.backend.app.projects.schemas import ProjectCreate


REAL_CATALOG = Path(__file__).resolve().parents[4] / "packages"
UHVI_DIR = "ai.utk.uhvi@1"
UHVI_TEMPLATE_REF = "ai.utk.uhvi/uhvi-load@1"


def _auth(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# ---------------------------------------------------------------------------
# Pure helpers (spec_packages.py)
# ---------------------------------------------------------------------------

class TestSpecPackagesHelpers:
    def test_versioned_type_yields_dir_name(self):
        assert dir_name_from_node_type("ai.utk.uhvi/uhvi-load@1") == "ai.utk.uhvi@1"

    def test_unversioned_without_resolver_returns_none(self):
        assert dir_name_from_node_type("curio.builtin/data-loading") is None

    def test_unversioned_with_resolver_picks_highest(self):
        assert (
            dir_name_from_node_type(
                "curio.builtin/data-loading",
                {"curio.builtin": [1, 2]},
            )
            == "curio.builtin@2"
        )

    def test_malformed_returns_none(self):
        for bad in ("", None, 42, "no-slash", "x/y@notnum", "X/y@1"):
            assert dir_name_from_node_type(bad) is None  # type: ignore[arg-type]

    def test_project_packages_prefers_declared(self):
        spec = {"dataflow": {"packages": ["ai.utk.uhvi@1"], "nodes": []}}
        assert project_packages(spec) == {"ai.utk.uhvi@1"}

    def test_project_packages_backfills_from_nodes(self):
        spec = {
            "dataflow": {
                "packages": [],  # empty triggers backfill
                "nodes": [
                    {"type": "ai.utk.uhvi/uhvi-load@1"},
                    {"type": "ai.utk.uhvi/uhvi-load@1"},  # dedupe
                    {"type": "curio.builtin/data-loading"},  # unversioned, no resolver
                ],
            }
        }
        assert project_packages(spec) == {"ai.utk.uhvi@1"}

    def test_project_packages_backfill_uses_resolver(self):
        spec = {
            "dataflow": {
                "packages": [],
                "nodes": [{"type": "curio.builtin/data-loading"}],
            }
        }
        assert project_packages(spec, {"curio.builtin": [1]}) == {"curio.builtin@1"}

    def test_set_project_packages_writes_sorted_list(self):
        spec: dict = {"dataflow": {}}
        set_project_packages(spec, ["b@1", "a@2", "b@1"])
        assert spec["dataflow"]["packages"] == ["a@2", "b@1"]


# ---------------------------------------------------------------------------
# Defaults file I/O (defaults.py)
# ---------------------------------------------------------------------------

class TestDefaults:
    def test_missing_file_is_empty(self, tmp_curio):
        assert defaults_io.load_defaults("guest") == set()

    def test_round_trip(self, tmp_curio):
        defaults_io.save_defaults("guest", ["ai.utk.uhvi@1", "curio.builtin@1"])
        assert defaults_io.load_defaults("guest") == {
            "ai.utk.uhvi@1", "curio.builtin@1",
        }

    def test_corrupt_file_treated_as_empty(self, tmp_curio):
        defaults_io._defaults_path("guest").parent.mkdir(parents=True, exist_ok=True)
        defaults_io._defaults_path("guest").write_text("not json")
        assert defaults_io.load_defaults("guest") == set()

    def test_invalid_dirs_are_filtered(self, tmp_curio):
        defaults_io.save_defaults("guest", ["valid.pkg@1", "INVALID", "x"])
        assert defaults_io.load_defaults("guest") == {"valid.pkg@1"}

    def test_add_and_remove_idempotent(self, tmp_curio):
        defaults_io.add_to_defaults("guest", "ai.utk.uhvi@1")
        defaults_io.add_to_defaults("guest", "ai.utk.uhvi@1")  # idempotent
        assert defaults_io.load_defaults("guest") == {"ai.utk.uhvi@1"}
        defaults_io.remove_from_defaults("guest", "ai.utk.uhvi@1")
        defaults_io.remove_from_defaults("guest", "ai.utk.uhvi@1")  # idempotent
        assert defaults_io.load_defaults("guest") == set()


# ---------------------------------------------------------------------------
# Service-level: install/uninstall in a single project
# ---------------------------------------------------------------------------

@pytest.fixture()
def alice_project(client, user_and_token):
    """Create one project for Alice and return its id."""
    _, token = user_and_token
    body = {
        "name": "test-proj",
        "spec": {"dataflow": {"nodes": [], "edges": [], "packages": []}},
        "outputs": [],
    }
    resp = client.post("/api/projects", json=body, headers=_auth(token))
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()["id"]


def _user_key_for(user) -> str:
    return projects_services._user_dir_key(user)


class TestProjectInstall:
    def test_install_adds_to_lockfile_and_user_store(self, app, user_and_token, alice_project):
        user, _ = user_and_token
        user_key = _user_key_for(user)

        assert not (user_packages_dir(user_key) / UHVI_DIR).is_dir()

        result = packages_services.install_to_project(user_key, alice_project, UHVI_DIR)
        assert result["packages"] == [UHVI_DIR]
        assert result["addedToUserStore"] is True

        spec = projects_storage.read_spec(user_key, alice_project)
        assert spec["dataflow"]["packages"] == [UHVI_DIR]
        assert (package_dir(user_key, UHVI_DIR) / "manifest.json").is_file()

    def test_install_idempotent(self, app, user_and_token, alice_project):
        user, _ = user_and_token
        user_key = _user_key_for(user)
        packages_services.install_to_project(user_key, alice_project, UHVI_DIR)
        # Second install: no user-store write needed.
        result = packages_services.install_to_project(user_key, alice_project, UHVI_DIR)
        assert result["packages"] == [UHVI_DIR]
        assert result["addedToUserStore"] is False

    def test_install_rejects_unknown_catalog_pkg(self, app, user_and_token, alice_project):
        user, _ = user_and_token
        user_key = _user_key_for(user)
        with pytest.raises(packages_services.PackageServiceError) as exc:
            packages_services.install_to_project(user_key, alice_project, "nope.does.not.exist@1")
        assert exc.value.status == 404


class TestProjectUninstall:
    def test_uninstall_prunes_when_no_other_project_references(
        self, app, user_and_token, alice_project,
    ):
        user, _ = user_and_token
        user_key = _user_key_for(user)
        packages_services.install_to_project(user_key, alice_project, UHVI_DIR)
        assert (package_dir(user_key, UHVI_DIR) / "manifest.json").is_file()

        result = packages_services.uninstall_from_project(user_key, alice_project, UHVI_DIR)
        assert result["packages"] == []
        assert UHVI_DIR in result["pruned"]
        # Defaults was never populated for this package, so nothing to remove there.
        assert result["removedFromDefaults"] == []
        assert not (user_packages_dir(user_key) / UHVI_DIR).is_dir()

    def test_uninstall_skips_prune_when_other_project_references(
        self, app, user_and_token, alice_project, client,
    ):
        user, token = user_and_token
        user_key = _user_key_for(user)

        # Second project owned by the same user, also referencing UHVI.
        resp = client.post(
            "/api/projects",
            json={"name": "p2", "spec": {"dataflow": {"nodes": [], "edges": [], "packages": []}}, "outputs": []},
            headers=_auth(token),
        )
        assert resp.status_code == 201
        second_id = resp.get_json()["id"]

        packages_services.install_to_project(user_key, alice_project, UHVI_DIR)
        packages_services.install_to_project(user_key, second_id, UHVI_DIR)

        result = packages_services.uninstall_from_project(user_key, alice_project, UHVI_DIR)
        assert result["pruned"] == []
        assert (package_dir(user_key, UHVI_DIR) / "manifest.json").is_file()

        # Now uninstall from the last project: the prune should fire.
        result = packages_services.uninstall_from_project(user_key, second_id, UHVI_DIR)
        assert result["pruned"] == [UHVI_DIR]
        assert not (user_packages_dir(user_key) / UHVI_DIR).is_dir()

    def test_uninstall_builtin_rejected(self, app, user_and_token, alice_project):
        user, _ = user_and_token
        user_key = _user_key_for(user)
        with pytest.raises(packages_services.PackageServiceError, match="built-in"):
            packages_services.uninstall_from_project(user_key, alice_project, "curio.builtin@1")


# ---------------------------------------------------------------------------
# Service-level: defaults install (global) + new-project seeding
# ---------------------------------------------------------------------------

class TestDefaultsInstall:
    def test_global_install_walks_all_projects(self, app, user_and_token, client):
        user, token = user_and_token
        user_key = _user_key_for(user)
        # Two existing projects.
        ids = []
        for n in ("p1", "p2"):
            resp = client.post(
                "/api/projects",
                json={"name": n, "spec": {"dataflow": {"nodes": [], "edges": [], "packages": []}}, "outputs": []},
                headers=_auth(token),
            )
            ids.append(resp.get_json()["id"])

        payload = packages_services.install_to_defaults(user, UHVI_DIR)
        assert UHVI_DIR in payload["packages"]
        assert {p["id"] for p in payload["projects"]} == set(ids)
        assert all(p["ok"] for p in payload["projects"])
        for project_id in ids:
            spec = projects_storage.read_spec(user_key, project_id)
            assert UHVI_DIR in spec["dataflow"]["packages"]

    def test_new_project_seeds_from_defaults(self, app, user_and_token):
        user, _ = user_and_token
        user_key = _user_key_for(user)
        defaults_io.save_defaults(user_key, [UHVI_DIR])

        data = ProjectCreate(
            name="seeded",
            spec={"dataflow": {"nodes": [], "edges": [], "packages": []}},
            outputs=[],
        )
        detail = projects_services.save_project(user, data)
        spec = projects_storage.read_spec(user_key, detail.id)
        assert UHVI_DIR in spec["dataflow"]["packages"]


# ---------------------------------------------------------------------------
# HTTP endpoints
# ---------------------------------------------------------------------------

class TestHttpEndpoints:
    def test_get_project_packages_returns_lockfile(self, client, user_and_token, alice_project):
        _, token = user_and_token
        resp = client.get(
            f"/api/packages/projects/{alice_project}",
            headers=_auth(token),
        )
        assert resp.status_code == 200
        assert resp.get_json() == {"packages": []}

    def test_install_endpoint_writes_lockfile(self, client, user_and_token, alice_project):
        _, token = user_and_token
        resp = client.post(
            f"/api/packages/projects/{alice_project}/install",
            json={"dirName": UHVI_DIR},
            headers=_auth(token),
        )
        assert resp.status_code == 201, resp.get_data(as_text=True)
        assert UHVI_DIR in resp.get_json()["packages"]

    def test_install_endpoint_rejects_bad_dir(self, client, user_and_token, alice_project):
        _, token = user_and_token
        resp = client.post(
            f"/api/packages/projects/{alice_project}/install",
            json={"dirName": "not-a-dirname"},
            headers=_auth(token),
        )
        assert resp.status_code == 400

    def test_uninstall_endpoint_drops_from_lockfile(self, client, user_and_token, alice_project):
        _, token = user_and_token
        client.post(
            f"/api/packages/projects/{alice_project}/install",
            json={"dirName": UHVI_DIR},
            headers=_auth(token),
        )
        resp = client.delete(
            f"/api/packages/projects/{alice_project}/{UHVI_DIR}",
            headers=_auth(token),
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["packages"] == []
        assert UHVI_DIR in body["pruned"]

    def test_get_defaults_seeds_builtin_for_new_user(self, client, user_and_token):
        """``GET /api/packages/defaults`` lazy-seeds ``curio.builtin@1`` on the
        first request for any non-guest user, so the catalog page's "Installed"
        badge renders correctly on fresh accounts. The seed is idempotent — a
        second call returns the same set without duplicates."""
        _, token = user_and_token
        resp = client.get("/api/packages/defaults", headers=_auth(token))
        assert resp.status_code == 200
        assert resp.get_json() == {"packages": ["curio.builtin@1"]}

        resp2 = client.get("/api/packages/defaults", headers=_auth(token))
        assert resp2.get_json() == {"packages": ["curio.builtin@1"]}

    def test_post_defaults_adds_to_list_and_walks_projects(
        self, client, user_and_token, alice_project,
    ):
        _, token = user_and_token
        resp = client.post(
            "/api/packages/defaults",
            json={"dirName": UHVI_DIR},
            headers=_auth(token),
        )
        assert resp.status_code == 201, resp.get_data(as_text=True)
        body = resp.get_json()
        assert UHVI_DIR in body["packages"]
        # The existing project should have been patched.
        proj_ids = {p["id"] for p in body["projects"] if p["ok"]}
        assert alice_project in proj_ids

    def test_delete_defaults_detaches_without_touching_projects(
        self, client, user_and_token, alice_project,
    ):
        """Added for #220. This endpoint used to be deliberately absent.

        The omission left "add to all projects" irreversible for a package:
        datasets have had ``DELETE /api/datasets/defaults/<id>`` throughout, so
        the two catalogs disagreed about whether that decision could be undone.

        Detach only, matching the dataset route: the package stays in the
        lockfiles of projects that already have it, and in the user store. Only
        the seeding of FUTURE projects stops.
        """
        _, token = user_and_token
        client.post(
            "/api/packages/defaults",
            json={"dirName": UHVI_DIR},
            headers=_auth(token),
        )

        resp = client.delete(
            f"/api/packages/defaults/{UHVI_DIR}",
            headers=_auth(token),
        )
        assert resp.status_code == 200, resp.get_data(as_text=True)
        assert UHVI_DIR not in resp.get_json()["packages"]

        # The project the POST patched keeps it: removing a default is not a
        # retroactive uninstall.
        proj = client.get(
            f"/api/packages/projects/{alice_project}", headers=_auth(token)
        )
        assert UHVI_DIR in proj.get_json()["packages"]

    def test_delete_defaults_is_idempotent(self, client, user_and_token):
        """A second removal (a double click, a retry) is not an error."""
        _, token = user_and_token
        resp = client.delete(
            f"/api/packages/defaults/{UHVI_DIR}",
            headers=_auth(token),
        )
        assert resp.status_code == 200, resp.get_data(as_text=True)
        assert UHVI_DIR not in resp.get_json()["packages"]


class TestRestartHonestyOnCatalogInstall:
    """dev/92 B-2: the catalog path is an install authority too — its
    response carries restartRecommended exactly when pip actually changed
    shared libraries; a no-op/already-installed path stays silent."""

    def test_pip_installed_libs_ride_the_response(self, app, user_and_token,
                                                  alice_project, monkeypatch):
        user, _ = user_and_token
        user_key = _user_key_for(user)
        monkeypatch.setattr(
            store_install, "_ensure_user_store_install",
            lambda uk, dn: packages_services.InstallOutcome(
                copied=True, installed=["geo-sdk", "tiny-lib"],
            ),
        )
        result = packages_services.install_to_project(user_key, alice_project, UHVI_DIR)
        assert result["restartRecommended"] == {"libs": ["geo-sdk", "tiny-lib"]}

    def test_silent_when_nothing_actually_installed(self, app, user_and_token,
                                                    alice_project):
        user, _ = user_and_token
        user_key = _user_key_for(user)
        result = packages_services.install_to_project(user_key, alice_project, UHVI_DIR)
        assert "restartRecommended" not in result  # UHVI declares no python deps
        again = packages_services.install_to_project(user_key, alice_project, UHVI_DIR)
        assert "restartRecommended" not in again


class TestCatalogOverlayRouting:
    """dev/97: the catalog authority routes through the SAME rule as promote
    — overlay for backend-bearing packages, host portion only in the restart
    signal."""

    def test_backend_only_catalog_install_builds_overlay_no_restart(
            self, app, user_and_token, alice_project, monkeypatch):
        from types import SimpleNamespace

        from utk_curio.backend.app.packages.infrastructure import backend_runtime
        from utk_curio.backend.app.packages.infrastructure import pip_runner

        user, _ = user_and_token
        user_key = _user_key_for(user)
        calls = {"overlay": None}
        fake_manifest = SimpleNamespace(
            python_deps={"tinylib": "1.0.0"},
            backend=SimpleNamespace(handlers=[SimpleNamespace(name="h")]),
            templates=[SimpleNamespace(engine="javascript", has_code=False)],
            permissions=[],
        )
        monkeypatch.setattr(
            store_install, "install_package_from_directory",
            lambda uk, src, replace=False: SimpleNamespace(manifest=fake_manifest))
        monkeypatch.setattr(
            store_reads, "_is_installed_in_user_store", lambda uk, dn: False)
        monkeypatch.setattr(
            'utk_curio.backend.app.packages.infrastructure.backend_runtime.record_entry_pin',
            lambda uk, dn: None)
        monkeypatch.setattr(
            backend_runtime, "build_overlay",
            lambda uk, dn, deps, on_line=None: calls.__setitem__("overlay", (dn, dict(deps)))
            or {"libs": ["tinylib==1.0.0"], "bytes": 5})

        def _never_host(deps, on_line=None):  # pragma: no cover
            raise AssertionError("host pip must not run for overlay-only routing")

        monkeypatch.setattr(pip_runner, "install_python_deps", _never_host)
        result = packages_services.install_to_project(user_key, alice_project, UHVI_DIR)
        assert calls["overlay"] == (UHVI_DIR, {"tinylib": "1.0.0"})
        # Host portion empty → no restart notice (dev/92 narrowed by dev/97).
        assert "restartRecommended" not in result


class TestUpdateFromCatalog:
    """#434: an update is a replace of the one store copy from the catalog.

    "Update all projects" and the drawer's "Update" used to post a plain install,
    which returns early for a package already in the store. Lockfiles name only
    ``<id>@<major>``, so replacing the store copy is the whole update.
    """

    COUNTER_DIR = "ai.test.counter@1"

    def _write_counter(self, catalog: Path, version: str, handler: str) -> None:
        from utk_curio.backend.app.packages.domain import backend_contract as bc

        pkg = catalog / self.COUNTER_DIR
        (pkg / "backend").mkdir(parents=True, exist_ok=True)
        (pkg / "manifest.json").write_text(json.dumps({
            "id": "ai.test.counter", "version": version, "name": "Counter",
            "publisher": "Tests", "description": "d",
            "compatibility": {"curioRuntime": ">=0.5.0", "major": 1},
            "permissions": [bc.PERMISSION_SERVER_CODE],
            "templates": [{
                "id": "counter", "label": "Counter", "category": "computation",
                "engine": "python", "editor": "none", "hasCode": False,
                "inputPorts": [], "outputPorts": [{"types": ["JSON"], "cardinality": "1"}],
                "backendHandler": "count",
            }],
            "backend": {"entry": "backend/handler.py",
                        "handlers": [{"name": "count", "timeoutClass": "quick"}]},
        }), encoding="utf-8")
        (pkg / "backend" / "handler.py").write_text(handler, encoding="utf-8")

    def test_the_replace_lands_the_new_version_and_repins_the_backend_entry(
        self, app, user_and_token, alice_project, monkeypatch, tmp_path,
    ):
        from utk_curio.backend.app.packages.infrastructure import backend_runtime
        from utk_curio.backend.app.packages.repositories import catalog_dir

        catalog = tmp_path / "catalog"
        monkeypatch.setattr(catalog_dir, "catalog_root", lambda: catalog)
        user, _ = user_and_token
        user_key = _user_key_for(user)

        self._write_counter(catalog, "1.0.0", "HANDLERS = {}\n")
        packages_services.install_to_project(user_key, alice_project, self.COUNTER_DIR)
        new_handler = "HANDLERS = {'count': lambda payload: 1}\n"
        self._write_counter(catalog, "1.1.0", new_handler)

        store_install.install_from_catalog(user_key, self.COUNTER_DIR, replace=True)

        manifest = json.loads(
            (package_dir(user_key, self.COUNTER_DIR) / "manifest.json").read_text())
        assert manifest["version"] == "1.1.0"
        # Invocation checks the handler against this pin and refuses a drifted
        # one with "reinstall": a replace that kept the old pin broke the
        # package it had just updated.
        assert backend_runtime.pinned_entry_digest(user_key, self.COUNTER_DIR) == \
            backend_runtime.entry_digest(new_handler.encode("utf-8"))
        spec = projects_storage.read_spec(user_key, alice_project)
        assert self.COUNTER_DIR in spec["dataflow"]["packages"]


# ---------------------------------------------------------------------------
# memo dev/101 — the lockfile is backend-owned on update
# ---------------------------------------------------------------------------

class TestPreserveProjectPackages:
    def test_disk_wins_over_the_client_mirror(self):
        disk = {"dataflow": {"nodes": [], "packages": [UHVI_DIR]}}
        client = {"dataflow": {"nodes": [], "packages": []}}
        preserve_project_packages(client, disk)
        assert client["dataflow"]["packages"] == [UHVI_DIR]

    def test_client_cannot_add_what_disk_lacks(self):
        disk = {"dataflow": {"nodes": [], "packages": []}}
        client = {"dataflow": {"nodes": [], "packages": ["stale.tab@1"]}}
        preserve_project_packages(client, disk)
        assert client["dataflow"]["packages"] == []

    def test_legacy_empty_list_with_nodes_becomes_explicit(self):
        """The reported state: ``[]`` on disk, a node of the package's type on
        the canvas. The carried-forward value is the EFFECTIVE lockfile, so the
        next save writes it down instead of leaving the backfill implicit."""
        disk = {"dataflow": {"nodes": [{"type": UHVI_TEMPLATE_REF}], "packages": []}}
        client = {"dataflow": {"nodes": [{"type": UHVI_TEMPLATE_REF}], "packages": []}}
        preserve_project_packages(client, disk)
        assert client["dataflow"]["packages"] == [UHVI_DIR]

    def test_no_dataflow_on_disk_leaves_the_client_value(self):
        client = {"dataflow": {"nodes": [], "packages": ["fresh.pkg@1"]}}
        preserve_project_packages(client, None)
        assert client["dataflow"]["packages"] == ["fresh.pkg@1"]
        preserve_project_packages(client, {"dataflow": "corrupt"})
        assert client["dataflow"]["packages"] == ["fresh.pkg@1"]

    def test_none_effective_is_a_no_op(self):
        assert preserve_project_packages(None, {"dataflow": {}}) is None


class TestReferencingNodes:
    def test_versioned_and_unversioned_types_are_counted(self):
        spec = {"dataflow": {"nodes": [
            {"id": "a", "type": UHVI_TEMPLATE_REF},
            {"id": "b", "type": "ai.utk.uhvi/uhvi-load"},
            {"id": "c", "type": "curio.builtin/data-loading@1"},
            "garbage",
        ]}}
        assert referencing_nodes(spec, UHVI_DIR, {"ai.utk.uhvi": [1]}) == ["a", "b"]
        # Without a resolver the unversioned reference cannot be attributed.
        assert referencing_nodes(spec, UHVI_DIR) == ["a"]

    def test_nodes_without_ids_still_count(self):
        spec = {"dataflow": {"nodes": [{"type": UHVI_TEMPLATE_REF}]}}
        assert referencing_nodes(spec, UHVI_DIR) == ["#0"]

    def test_no_dataflow_is_empty(self):
        assert referencing_nodes(None, UHVI_DIR) == []
        assert referencing_nodes({"dataflow": None}, UHVI_DIR) == []


class TestUninstallRefusesWhileNodesUseThePackage:
    """memo dev/101 D2 — the delete that silently did nothing."""

    def _spec_with_uhvi_node(self, user_key, project_id):
        spec = projects_storage.read_spec(user_key, project_id)
        spec["dataflow"]["nodes"] = [
            {"id": "n-uhvi", "type": UHVI_TEMPLATE_REF, "data": {}},
        ]
        projects_storage.write_spec(user_key, project_id, spec)

    def test_service_refuses_with_the_node_count(self, app, user_and_token, alice_project):
        user, _ = user_and_token
        user_key = _user_key_for(user)
        packages_services.install_to_project(user_key, alice_project, UHVI_DIR)
        self._spec_with_uhvi_node(user_key, alice_project)

        with pytest.raises(packages_services.PackageServiceError) as exc:
            packages_services.uninstall_from_project(user_key, alice_project, UHVI_DIR)
        assert exc.value.status == 409
        assert "1 node on this canvas uses ai.utk.uhvi@1" in str(exc.value)
        # Nothing moved: lockfile intact, store copy intact.
        assert projects_storage.read_spec(user_key, alice_project)["dataflow"]["packages"] == [UHVI_DIR]
        assert (package_dir(user_key, UHVI_DIR) / "manifest.json").is_file()

    def test_the_reported_state_is_refused_not_no_opped(self, app, user_and_token, alice_project):
        """``[]`` on disk + a node of the package's type: before, uninstall
        computed the backfilled set, wrote ``[]`` (already ``[]``), prune saw the
        node, nothing happened, 200. Now it says why."""
        user, _ = user_and_token
        user_key = _user_key_for(user)
        packages_services.install_to_project(user_key, alice_project, UHVI_DIR)
        spec = projects_storage.read_spec(user_key, alice_project)
        spec["dataflow"]["nodes"] = [{"id": "n1", "type": UHVI_TEMPLATE_REF}, {"id": "n2", "type": UHVI_TEMPLATE_REF}]
        spec["dataflow"]["packages"] = []  # the clobbered lockfile
        projects_storage.write_spec(user_key, alice_project, spec)

        with pytest.raises(packages_services.PackageServiceError) as exc:
            packages_services.uninstall_from_project(user_key, alice_project, UHVI_DIR)
        assert exc.value.status == 409
        assert "2 nodes on this canvas use ai.utk.uhvi@1 — delete them first" in str(exc.value)

    def test_after_the_nodes_go_the_uninstall_succeeds(self, app, user_and_token, alice_project):
        user, _ = user_and_token
        user_key = _user_key_for(user)
        packages_services.install_to_project(user_key, alice_project, UHVI_DIR)
        self._spec_with_uhvi_node(user_key, alice_project)
        with pytest.raises(packages_services.PackageServiceError):
            packages_services.uninstall_from_project(user_key, alice_project, UHVI_DIR)

        spec = projects_storage.read_spec(user_key, alice_project)
        spec["dataflow"]["nodes"] = []
        projects_storage.write_spec(user_key, alice_project, spec)
        result = packages_services.uninstall_from_project(user_key, alice_project, UHVI_DIR)
        assert result["packages"] == []
        assert result["pruned"] == [UHVI_DIR]

    def test_route_returns_409_with_the_message(self, client, user_and_token, alice_project):
        user, token = user_and_token
        user_key = _user_key_for(user)
        packages_services.install_to_project(user_key, alice_project, UHVI_DIR)
        self._spec_with_uhvi_node(user_key, alice_project)
        resp = client.delete(
            f"/api/packages/projects/{alice_project}/{UHVI_DIR}", headers=_auth(token),
        )
        assert resp.status_code == 409
        assert "delete it first" in resp.get_json()["error"]


# ---------------------------------------------------------------------------
# Uninstalling from the store detaches the package from the lockfiles too
# ---------------------------------------------------------------------------

def test_uninstall_detaches_the_package_from_every_project(
    client, user_and_token, alice_project, tmp_curio,
):
    """A lockfile entry is Curio's reference, so Curio removes it.

    Deleting a package from the user store used to leave every dataflow that
    had installed it naming a package that is no longer there. The canvas
    reinstalls anything in the lockfile it cannot find (``useEnsureWorkflowDeps``),
    so reopening that dataflow retried an install that cannot succeed and
    ended in "Could not install <coordinate>" -- every time, for good. It
    also broke the next sideload of the same archive, which is how the e2e
    package roundtrip started failing under load.
    """
    user, token = user_and_token
    user_key = _user_key_for(user)
    dir_name = UHVI_DIR

    packages_services.install_to_project(user_key, alice_project, dir_name)
    assert dir_name in packages_services.get_project_lockfile(user_key, alice_project)

    assert client.delete(
        f"/api/packages/{dir_name}", headers=_auth(token),
    ).status_code == 204

    assert dir_name not in packages_services.get_project_lockfile(
        user_key, alice_project,
    ), "the dataflow still names a package that is no longer installed"


def test_uninstall_leaves_other_packages_in_the_lockfile_alone(
    client, user_and_token, alice_project, tmp_curio,
):
    """The sweep is per coordinate, not a lockfile reset."""
    user, token = user_and_token
    user_key = _user_key_for(user)

    packages_services.install_to_project(user_key, alice_project, UHVI_DIR)
    before = packages_services.get_project_lockfile(user_key, alice_project)
    others = before - {UHVI_DIR}

    client.delete(f"/api/packages/{UHVI_DIR}", headers=_auth(token))

    after = packages_services.get_project_lockfile(user_key, alice_project)
    assert after == others


# ---------------------------------------------------------------------------
# Remove from account (the Node and Model Catalog pages)
# ---------------------------------------------------------------------------

def _store_rows(client, token, query: str = "") -> dict:
    resp = client.get(f"/api/packages{query}", headers=_auth(token))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return {row["dirName"]: row for row in resp.get_json()["packages"]}


class TestRemoveFromAccount:
    """A catalog page removes a package from the account only while no
    dataflow uses it, which it decides as the prune after Remove from project
    does: a dataflow uses a package its lockfile names."""

    def test_the_store_listing_says_which_packages_a_dataflow_uses(
        self, client, user_and_token, alice_project,
    ):
        user, token = user_and_token
        user_key = _user_key_for(user)
        store_install.install_from_catalog(user_key, UHVI_DIR, replace=False)
        assert _store_rows(client, token, "?usage=true")[UHVI_DIR]["inUse"] is False

        packages_services.install_to_project(user_key, alice_project, UHVI_DIR)
        assert _store_rows(client, token, "?usage=true")[UHVI_DIR]["inUse"] is True
        # Without the flag the listing reads no dataflow.
        assert "inUse" not in _store_rows(client, token)[UHVI_DIR]

    def test_a_package_a_dataflow_uses_is_refused(self, client, user_and_token, alice_project):
        user, token = user_and_token
        user_key = _user_key_for(user)
        packages_services.install_to_project(user_key, alice_project, UHVI_DIR)

        resp = client.delete(f"/api/packages/{UHVI_DIR}?unusedOnly=true", headers=_auth(token))
        assert resp.status_code == 409, resp.get_data(as_text=True)
        assert (package_dir(user_key, UHVI_DIR) / "manifest.json").is_file()
        assert UHVI_DIR in packages_services.get_project_lockfile(user_key, alice_project)

    def test_a_package_no_dataflow_uses_leaves_the_store_and_the_defaults(
        self, client, user_and_token,
    ):
        """Add to all projects before the account has a dataflow puts the
        package in the store and the defaults, and in no lockfile."""
        user, token = user_and_token
        user_key = _user_key_for(user)
        packages_services.install_to_defaults(user, UHVI_DIR)
        assert UHVI_DIR in defaults_io.load_defaults(user_key)

        resp = client.delete(f"/api/packages/{UHVI_DIR}?unusedOnly=true", headers=_auth(token))
        assert resp.status_code == 204, resp.get_data(as_text=True)
        assert not (user_packages_dir(user_key) / UHVI_DIR).is_dir()
        assert UHVI_DIR not in defaults_io.load_defaults(user_key)


# ---------------------------------------------------------------------------
# A node bound to a model (metadata.modelRefs) uses the model's package
# ---------------------------------------------------------------------------

DDRNET_DIR = "model.curio.ddrnet23-slim@1"
DDRNET_ID = "model.curio.ddrnet23-slim"


def _python_node(node_id: str, *, bound: bool, model_ref: str = DDRNET_ID, runs: str = DDRNET_ID) -> dict:
    """A built-in Python node whose code runs the model *runs* (DDRNet): bound
    to DDRNet as a drop of the model onto the node binds it
    (``metadata.modelRefs``), or naming it in its code only."""
    metadata: dict = {"keywords": []}
    if bound:
        metadata["modelRefs"] = [{"id": model_ref, "name": "DDRNet23-Slim (street scenes)"}]
    return {
        "id": node_id,
        "type": "curio.builtin/computation-analysis",
        "content": f'model = curio_load_model("{runs}")\nreturn 1\n',
        "metadata": metadata,
    }


def _with_nodes(user_key: str, project_id: str, nodes: list[dict], packages: list[str] | None = None) -> None:
    spec = projects_storage.read_spec(user_key, project_id)
    spec["dataflow"]["nodes"] = nodes
    if packages is not None:
        spec["dataflow"]["packages"] = packages
    projects_storage.write_spec(user_key, project_id, spec)


class TestModelRefsCountAsInUse:
    """A model package is in use while a node's type or its ``modelRefs``
    names it. A literal ``curio_load_model`` call is only a code reference:
    the drawer's Remove dialog warns about it, and it keeps nothing."""

    def test_a_node_bound_to_the_model_references_its_package(self):
        spec = {"dataflow": {"nodes": [
            _python_node("bound", bound=True),
            _python_node("by-major", bound=True, model_ref=DDRNET_DIR),
            _python_node("in-code-only", bound=False),
            {"id": "loader", "type": "curio.builtin/data-loading@1"},
        ]}}
        assert referencing_nodes(spec, DDRNET_DIR, {DDRNET_ID: [1]}) == ["bound", "by-major"]
        assert referencing_nodes(spec, "model.curio.other@1", {DDRNET_ID: [1]}) == []

    def test_a_binding_counts_only_while_the_code_still_names_its_model(self):
        """A hand edit to another model leaves the drop's ref behind, as the
        canvas's ``nodeLinkedModelIds`` reads it: that ref keeps nothing."""
        from utk_curio.backend.app.datasets.domain.code_refs import model_ids_in_code

        spec = {"dataflow": {"nodes": [
            _python_node("bound", bound=True),
            _python_node("edited", bound=True, runs="model.example.local-relief"),
        ]}}
        assert referencing_nodes(spec, DDRNET_DIR, {DDRNET_ID: [1]}, model_ids_in_code) == ["bound"]

    def test_remove_from_project_takes_a_model_whose_binding_the_code_no_longer_names(
        self, app, user_and_token, alice_project,
    ):
        user, _ = user_and_token
        user_key = _user_key_for(user)
        packages_services.install_to_project(user_key, alice_project, DDRNET_DIR)
        _with_nodes(user_key, alice_project, [_python_node("edited", bound=True, runs="model.example.local-relief")])

        result = packages_services.uninstall_from_project(user_key, alice_project, DDRNET_DIR)

        assert result["packages"] == []
        assert result["pruned"] == [DDRNET_DIR]

    def test_remove_from_project_is_refused_while_a_node_is_bound_to_the_model(
        self, app, user_and_token, alice_project,
    ):
        user, _ = user_and_token
        user_key = _user_key_for(user)
        packages_services.install_to_project(user_key, alice_project, DDRNET_DIR)
        _with_nodes(user_key, alice_project, [_python_node("bound", bound=True)])

        with pytest.raises(packages_services.PackageServiceError) as exc:
            packages_services.uninstall_from_project(user_key, alice_project, DDRNET_DIR)
        assert exc.value.status == 409
        assert f"1 node on this canvas uses {DDRNET_DIR}" in str(exc.value)
        assert DDRNET_DIR in projects_storage.read_spec(user_key, alice_project)["dataflow"]["packages"]

    def test_a_call_in_code_alone_keeps_no_model(self, app, user_and_token, alice_project):
        user, _ = user_and_token
        user_key = _user_key_for(user)
        packages_services.install_to_project(user_key, alice_project, DDRNET_DIR)
        _with_nodes(user_key, alice_project, [_python_node("in-code-only", bound=False)])

        result = packages_services.uninstall_from_project(user_key, alice_project, DDRNET_DIR)

        assert result["packages"] == []
        assert result["pruned"] == [DDRNET_DIR]

    def test_remove_from_account_is_refused_while_a_node_is_bound_to_the_model(
        self, client, user_and_token, alice_project,
    ):
        """The node's dataflow does not name the model in its lockfile: the
        binding alone keeps it."""
        user, token = user_and_token
        user_key = _user_key_for(user)
        store_install.install_from_catalog(user_key, DDRNET_DIR, replace=False)
        _with_nodes(user_key, alice_project, [_python_node("bound", bound=True)], packages=["curio.builtin@1"])

        assert _store_rows(client, token, "?usage=true")[DDRNET_DIR]["inUse"] is True
        resp = client.delete(f"/api/packages/{DDRNET_DIR}?unusedOnly=true", headers=_auth(token))
        assert resp.status_code == 409, resp.get_data(as_text=True)
        assert (package_dir(user_key, DDRNET_DIR) / "manifest.json").is_file()

        # Bound no longer, it leaves.
        _with_nodes(user_key, alice_project, [_python_node("in-code-only", bound=False)])
        resp = client.delete(f"/api/packages/{DDRNET_DIR}?unusedOnly=true", headers=_auth(token))
        assert resp.status_code == 204, resp.get_data(as_text=True)


# ---------------------------------------------------------------------------
# GET /api/packages/<dir>/usage: the dataflows that use a package
# ---------------------------------------------------------------------------

LOCAL_RELIEF_ID = "model.example.local-relief"


class TestPackageUsage:
    """The account's dataflows that use a package, as ``GET
    /api/datasets/<id>/usage`` answers for a dataset. ``codeOnly`` marks a
    dataflow whose nodes name the model in their code alone: a literal
    ``curio_load_model("<id>")``, with no binding, no node of the package and
    no lockfile entry. Nothing in it keeps the model, so the Model Catalog's
    Remove names it, as the Data Catalog's names a dataflow that loads a
    dataset in code."""

    @staticmethod
    def _project(client, token, name: str, nodes: list[dict], packages: list[str] | None = None) -> str:
        # A lockfile of its own: an empty one would take the account's defaults.
        spec = {"dataflow": {
            "name": name, "nodes": nodes, "edges": [], "packages": packages or ["curio.builtin@1"],
        }}
        resp = client.post("/api/projects", json={"name": name, "spec": spec, "outputs": []}, headers=_auth(token))
        assert resp.status_code == 201, resp.get_data(as_text=True)
        return resp.get_json()["id"]

    @staticmethod
    def _usage(client, token, dir_name: str) -> list[dict]:
        resp = client.get(f"/api/packages/{dir_name}/usage", headers=_auth(token))
        assert resp.status_code == 200, resp.get_data(as_text=True)
        return resp.get_json()["dataflows"]

    def test_lists_each_dataflow_that_uses_the_model_and_marks_those_that_only_name_it_in_code(
        self, client, user_and_token,
    ):
        user, token = user_and_token
        store_install.install_from_catalog(_user_key_for(user), DDRNET_DIR, replace=False)
        own_node = {
            "id": "segment", "type": "model.curio.ddrnet23-slim/image-segmentation@1",
            "content": f'model = curio_load_model("{DDRNET_ID}")\n', "metadata": {"keywords": []},
        }
        ids = {
            "Code only": self._project(client, token, "Code only", [_python_node("in-code", bound=False)]),
            "Bound": self._project(client, token, "Bound", [_python_node("bound", bound=True)]),
            "Its own node": self._project(client, token, "Its own node", [own_node]),
            "In its lockfile": self._project(
                client, token, "In its lockfile", [_python_node("in-code", bound=False)],
                packages=["curio.builtin@1", DDRNET_DIR],
            ),
            "Bound and in code": self._project(
                client, token, "Bound and in code",
                [_python_node("bound", bound=True), _python_node("in-code", bound=False)],
            ),
        }
        other = self._project(
            client, token, "Another model", [_python_node("relief", bound=False, runs=LOCAL_RELIEF_ID)],
        )

        rows = self._usage(client, token, DDRNET_DIR)

        ours = [row for row in rows if row["dataflowId"] in ids.values()]
        assert [(row["dataflowName"], row["codeOnly"]) for row in ours] == [
            ("Bound", False),
            ("Bound and in code", False),
            ("Code only", True),
            ("In its lockfile", False),
            ("Its own node", False),
        ]
        by_name = {row["dataflowName"]: row for row in ours}
        assert by_name["Code only"]["dataflowId"] == ids["Code only"]
        assert by_name["Code only"]["nodes"] == [
            {"nodeId": "in-code", "nodeType": "curio.builtin/computation-analysis"},
        ]
        assert by_name["Bound and in code"]["nodeCount"] == 2
        assert [node["nodeId"] for node in by_name["Bound and in code"]["nodes"]] == ["bound", "in-code"]
        assert other not in {row["dataflowId"] for row in rows}

    def test_a_binding_the_code_no_longer_names_keeps_nothing_and_the_model_the_code_names_is_in_code_only(
        self, client, user_and_token,
    ):
        """A hand edit to another model leaves the drop's ref behind: the
        dataflow no longer uses the model the ref names, and names the other
        one in its code alone."""
        user, token = user_and_token
        store_install.install_from_catalog(_user_key_for(user), DDRNET_DIR, replace=False)
        edited = self._project(
            client, token, "Edited by hand", [_python_node("edited", bound=True, runs=LOCAL_RELIEF_ID)],
        )

        assert edited not in {row["dataflowId"] for row in self._usage(client, token, DDRNET_DIR)}
        relief = {row["dataflowId"]: row for row in self._usage(client, token, f"{LOCAL_RELIEF_ID}@1")}
        assert relief[edited]["codeOnly"] is True
        assert [node["nodeId"] for node in relief[edited]["nodes"]] == ["edited"]
