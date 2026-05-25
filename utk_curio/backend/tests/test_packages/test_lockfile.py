"""Tests for the per-project lockfile + per-user defaults model.

Covers the four pieces added in the lockfile epic:

  * ``spec_packages`` pure helpers (backfill from node types).
  * ``defaults`` file I/O.
  * ``services`` orchestration (install_to_project, install_to_defaults,
    uninstall_from_project, prune_unreferenced_packages).
  * REST endpoints under ``/api/packages/projects/...`` and
    ``/api/packages/defaults``.

Uses real catalog packages (``ai.urbanlab.uhvi@1``, ``curio.builtin``)
so the install paths exercise the same code as production.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from utk_curio.backend.app.packages import defaults as defaults_io
from utk_curio.backend.app.packages import services as packages_services
from utk_curio.backend.app.packages.spec_packages import (
    dir_name_from_node_type,
    project_packages,
    set_project_packages,
)
from utk_curio.backend.app.packages.storage import (
    package_dir,
    user_packageages_dir,
)
from utk_curio.backend.app.projects import services as projects_services
from utk_curio.backend.app.projects import storage as projects_storage
from utk_curio.backend.app.projects.schemas import ProjectCreate


REAL_CATALOG = Path(__file__).resolve().parents[4] / "packages"
UHVI_DIR = "ai.urbanlab.uhvi@1"
UHVI_TEMPLATE_REF = "ai.urbanlab.uhvi/uhvi-load@1"


def _auth(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# ---------------------------------------------------------------------------
# Pure helpers (spec_packages.py)
# ---------------------------------------------------------------------------

class TestSpecPackagesHelpers:
    def test_versioned_type_yields_dir_name(self):
        assert dir_name_from_node_type("ai.urbanlab.uhvi/uhvi-load@1") == "ai.urbanlab.uhvi@1"

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
        spec = {"dataflow": {"packages": ["ai.urbanlab.uhvi@1"], "nodes": []}}
        assert project_packages(spec) == {"ai.urbanlab.uhvi@1"}

    def test_project_packages_backfills_from_nodes(self):
        spec = {
            "dataflow": {
                "packages": [],  # empty triggers backfill
                "nodes": [
                    {"type": "ai.urbanlab.uhvi/uhvi-load@1"},
                    {"type": "ai.urbanlab.uhvi/uhvi-load@1"},  # dedupe
                    {"type": "curio.builtin/data-loading"},  # unversioned, no resolver
                ],
            }
        }
        assert project_packages(spec) == {"ai.urbanlab.uhvi@1"}

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
        defaults_io.save_defaults("guest", ["ai.urbanlab.uhvi@1", "curio.builtin@1"])
        assert defaults_io.load_defaults("guest") == {
            "ai.urbanlab.uhvi@1", "curio.builtin@1",
        }

    def test_corrupt_file_treated_as_empty(self, tmp_curio):
        defaults_io._defaults_path("guest").parent.mkdir(parents=True, exist_ok=True)
        defaults_io._defaults_path("guest").write_text("not json")
        assert defaults_io.load_defaults("guest") == set()

    def test_invalid_dirs_are_filtered(self, tmp_curio):
        defaults_io.save_defaults("guest", ["valid.pkg@1", "INVALID", "x"])
        assert defaults_io.load_defaults("guest") == {"valid.pkg@1"}

    def test_add_and_remove_idempotent(self, tmp_curio):
        defaults_io.add_to_defaults("guest", "ai.urbanlab.uhvi@1")
        defaults_io.add_to_defaults("guest", "ai.urbanlab.uhvi@1")  # idempotent
        assert defaults_io.load_defaults("guest") == {"ai.urbanlab.uhvi@1"}
        defaults_io.remove_from_defaults("guest", "ai.urbanlab.uhvi@1")
        defaults_io.remove_from_defaults("guest", "ai.urbanlab.uhvi@1")  # idempotent
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

        assert not (user_packageages_dir(user_key) / UHVI_DIR).is_dir()

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
        assert not (user_packageages_dir(user_key) / UHVI_DIR).is_dir()

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
        assert not (user_packageages_dir(user_key) / UHVI_DIR).is_dir()

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

    def test_get_defaults_starts_empty(self, client, user_and_token):
        _, token = user_and_token
        resp = client.get("/api/packages/defaults", headers=_auth(token))
        assert resp.status_code == 200
        assert resp.get_json() == {"packages": []}

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

    def test_no_delete_defaults_endpoint(self, client, user_and_token):
        """The plan deliberately omits this endpoint. The app's global error
        handler wraps the Werkzeug NotFound as a 500, so accept anything
        non-2xx — the only point is that no route matches."""
        _, token = user_and_token
        resp = client.delete(
            f"/api/packages/defaults/{UHVI_DIR}",
            headers=_auth(token),
        )
        assert resp.status_code >= 400
