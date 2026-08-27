"""Tests for :mod:`utk_curio.backend.app.packages.build_promotion` (dev/89 commit 7):
exact-digest promotion, stale protection, backup + rollback honesty, the
persisted journal (disconnect-safe idempotency), pip-at-Apply compensation,
project-lockfile update, and the activation confirmation order.
"""

from __future__ import annotations

import pytest

from utk_curio.backend.app.packages import build_promotion, build_staging
from utk_curio.backend.app.packages.build_extension import installed_package_digest
from utk_curio.backend.app.packages.build_models import parse_build_request
from utk_curio.backend.app.packages.build_packager import assemble_archive
from utk_curio.backend.app.packages.build_promotion import (
    PromotionError,
    confirm_nodes_created,
    confirm_registry_ready,
    load_journal,
    promote,
    rollback,
)
from utk_curio.backend.app.packages.installer import install_packageage_from_archive
from utk_curio.backend.app.packages.storage import package_dir

_DEPS = {"python": {}, "js": {}, "packages": {}}


def _kind(template_id: str = "demo-kind") -> dict:
    return {
        "id": template_id, "label": "Demo", "category": "computation",
        "engine": "python", "editor": "code", "hasCode": True,
        "hasWidgets": False, "hasGrammar": False,
        "inputPorts": [], "outputPorts": [{"types": ["JSON"], "cardinality": "1"}],
        "templateDir": f"starters/{template_id}",
        "defaultTemplate": f"starters/{template_id}/Default.py",
    }


def _stage_build(manifest_dict, *, version="1.0.0", body="return arg\n",
                 python_deps=None, user_key="guest") -> str:
    """Assemble + stage one valid built archive; returns its digest."""
    manifest = manifest_dict(kinds=[_kind()], version=version,
                             python_deps=python_deps)
    request = parse_build_request({
        "mode": "create", "target": "ai.test.demo@1", "manifest": manifest,
        "files": {"starters/demo-kind/Default.py": {"text": body}},
    })
    archive, _ = assemble_archive(request, request.files, None, {
        "python": python_deps or {}, "js": {}, "packages": {},
    })
    return build_staging.stage_artifact(user_key, archive)


class TestPromoteCreate:
    def test_happy_path_journal(self, tmp_curio, manifest_dict):
        digest = _stage_build(manifest_dict)
        journal = promote("guest", target="ai.test.demo@1", artifact_digest=digest)
        assert journal["status"] == "awaiting-activation"
        steps = [s["step"] for s in journal["steps"]]
        assert steps == ["verified", "installed"]  # no backup for a fresh create
        assert journal["backupHeld"] is False
        target = package_dir("guest", "ai.test.demo@1")
        assert (target / "manifest.json").is_file()
        assert (target / "integrity.json").is_file()  # installer-generated

    def test_repeated_apply_returns_journal_not_reinstall(self, tmp_curio, manifest_dict):
        digest = _stage_build(manifest_dict)
        first = promote("guest", target="ai.test.demo@1", artifact_digest=digest)
        again = promote("guest", target="ai.test.demo@1", artifact_digest=digest)
        assert again == first
        assert [s["step"] for s in again["steps"]] == ["verified", "installed"]

    def test_create_collision_refused(self, tmp_curio, manifest_dict, install_packageage):
        install_packageage("guest")  # ai.test.demo@1 already installed
        digest = _stage_build(manifest_dict)
        with pytest.raises(PromotionError, match="already installed") as exc:
            promote("guest", target="ai.test.demo@1", artifact_digest=digest)
        assert exc.value.status == 409

    def test_unstaged_artifact_refused(self, tmp_curio):
        with pytest.raises(PromotionError, match="staged artifact unavailable") as exc:
            promote("guest", target="ai.test.demo@1", artifact_digest="0" * 64)
        assert exc.value.status == 410

    def test_target_mismatch_refused(self, tmp_curio, manifest_dict):
        digest = _stage_build(manifest_dict)
        with pytest.raises(PromotionError, match="targets") as exc:
            promote("guest", target="ai.test.other@1", artifact_digest=digest)
        assert exc.value.status == 409
        assert not package_dir("guest", "ai.test.other@1").exists()


class TestPromoteExtend:
    def _install_base(self, install_packageage, manifest_dict) -> str:
        install_packageage(
            "guest", manifest=manifest_dict(kinds=[_kind()]),
            sources={"demo-kind": {"Default.py": "def run():\n    return 1\n"}})
        return installed_package_digest("guest", "ai.test.demo@1")

    def test_extend_replaces_with_backup(self, tmp_curio, manifest_dict,
                                         install_packageage):
        base_digest = self._install_base(install_packageage, manifest_dict)
        digest = _stage_build(manifest_dict, version="1.1.0", body="return 2\n")
        journal = promote("guest", target="ai.test.demo@1",
                          artifact_digest=digest, base_digest=base_digest)
        steps = [s["step"] for s in journal["steps"]]
        assert steps == ["verified", "backed-up", "installed"]
        assert journal["backupHeld"] is True and journal["priorDigest"] == base_digest
        body = (package_dir("guest", "ai.test.demo@1")
                / "starters" / "demo-kind" / "Default.py").read_text()
        assert body == "return 2\n"

    def test_stale_base_refused_untouched(self, tmp_curio, manifest_dict,
                                          install_packageage):
        self._install_base(install_packageage, manifest_dict)
        digest = _stage_build(manifest_dict, version="1.1.0", body="return 2\n")
        with pytest.raises(PromotionError, match="stale base") as exc:
            promote("guest", target="ai.test.demo@1",
                    artifact_digest=digest, base_digest="e" * 64)
        assert exc.value.status == 409
        body = (package_dir("guest", "ai.test.demo@1")
                / "starters" / "demo-kind" / "Default.py").read_text()
        assert "return 1" in body  # nothing was overwritten

    def test_rollback_restores_prior_package(self, tmp_curio, manifest_dict,
                                             install_packageage):
        base_digest = self._install_base(install_packageage, manifest_dict)
        digest = _stage_build(manifest_dict, version="1.1.0", body="return 2\n")
        promote("guest", target="ai.test.demo@1",
                artifact_digest=digest, base_digest=base_digest)
        journal = rollback("guest", digest, "registry activation failed")
        assert journal["status"] == "rolled-back"
        assert journal["rollback"]["reason"] == "registry activation failed"
        assert installed_package_digest("guest", "ai.test.demo@1") == base_digest

    def test_rollback_of_create_uninstalls(self, tmp_curio, manifest_dict):
        digest = _stage_build(manifest_dict)
        promote("guest", target="ai.test.demo@1", artifact_digest=digest)
        journal = rollback("guest", digest, "activation failed")
        assert journal["status"] == "rolled-back"
        assert not package_dir("guest", "ai.test.demo@1").exists()


class TestPipAtApply:
    def test_pip_failure_compensates(self, tmp_curio, manifest_dict, monkeypatch,
                                     install_packageage):
        from utk_curio.backend.app.packages import pip_runner

        base_digest = TestPromoteExtend()._install_base(install_packageage, manifest_dict)

        def _boom(deps):
            raise pip_runner.PipInstallError("no wheel for left-pad-py")

        monkeypatch.setattr(pip_runner, "install_python_deps", _boom)
        digest = _stage_build(manifest_dict, version="1.1.0", body="return 2\n",
                              python_deps={"left-pad-py": "^1.0.0"})
        with pytest.raises(PromotionError, match="restored") as exc:
            promote("guest", target="ai.test.demo@1",
                    artifact_digest=digest, base_digest=base_digest)
        assert exc.value.status == 502
        journal = load_journal("guest", digest)
        assert journal["status"] == "rolled-back"
        # The prior package is back, byte-identical.
        assert installed_package_digest("guest", "ai.test.demo@1") == base_digest


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def project(client, user_and_token):
    _, token = user_and_token
    resp = client.post("/api/projects", json={
        "name": "promo-proj",
        "spec": {"dataflow": {"nodes": [], "edges": [], "packages": []}},
        "outputs": [],
    }, headers=_auth(token))
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()["id"]


class TestLockfileAndActivation:
    def test_lockfile_updated_after_install(self, tmp_curio, manifest_dict,
                                            user_and_token, project):
        from utk_curio.backend.app.projects import services as projects_services

        user, _ = user_and_token
        user_key = projects_services._user_dir_key(user)
        digest = _stage_build(manifest_dict, user_key=user_key)
        journal = promote(user_key, target="ai.test.demo@1",
                          artifact_digest=digest, project_id=project)
        assert "lockfile-updated" in [s["step"] for s in journal["steps"]]
        assert journal["lockfileAdded"] is True
        from utk_curio.backend.app.packages.services import get_project_lockfile

        assert "ai.test.demo@1" in get_project_lockfile(user_key, project)

        # Rollback removes the entry this promotion added.
        rolled = rollback(user_key, digest, "activation failed")
        assert rolled["status"] == "rolled-back"
        assert "ai.test.demo@1" not in get_project_lockfile(user_key, project)

    def test_activation_confirmation_order(self, tmp_curio, manifest_dict):
        digest = _stage_build(manifest_dict)
        promote("guest", target="ai.test.demo@1", artifact_digest=digest)
        with pytest.raises(PromotionError, match="registry refresh has not been confirmed"):
            confirm_nodes_created("guest", digest)
        confirm_registry_ready("guest", digest)
        journal = confirm_nodes_created("guest", digest)
        assert journal["status"] == "completed"
        assert [s["step"] for s in journal["steps"]] == [
            "verified", "installed", "registry-ready", "nodes-created"]
        # Completion drops the compensation surface: staged artifact discarded.
        assert not build_staging.has_artifact("guest", digest)

    def test_completed_promotion_cannot_roll_back(self, tmp_curio, manifest_dict):
        digest = _stage_build(manifest_dict)
        promote("guest", target="ai.test.demo@1", artifact_digest=digest)
        confirm_registry_ready("guest", digest)
        confirm_nodes_created("guest", digest)
        with pytest.raises(PromotionError, match="already completed"):
            rollback("guest", digest, "too late")

    def test_confirm_without_journal_refused(self, tmp_curio):
        with pytest.raises(PromotionError, match="no promotion journal"):
            confirm_registry_ready("guest", "0" * 64)


class TestRestartHonesty:
    """dev/92 B-2: pip's InstallReport is KEPT at Apply — a lib that actually
    landed/changed in the shared interpreter becomes restartRecommended on
    the journal; skipped-only (idempotent) installs recommend nothing."""

    def _promote_with_pip(self, tmp_curio, manifest_dict, monkeypatch, *,
                          installed, skipped):
        from utk_curio.backend.app.packages import pip_runner

        monkeypatch.setattr(
            pip_runner, "install_python_deps",
            lambda deps, on_line=None: pip_runner.InstallReport(
                installed=list(installed), skipped=list(skipped)),
        )
        digest = _stage_build(manifest_dict, python_deps={"torch": "2.4.0",
                                                          "shapely": "2.0.0"})
        return promote("guest", target="ai.test.demo@1", artifact_digest=digest)

    def test_actually_installed_libs_recommend_a_restart(
            self, tmp_curio, manifest_dict, monkeypatch):
        journal = self._promote_with_pip(
            tmp_curio, manifest_dict, monkeypatch,
            installed=["torch"], skipped=["shapely"])
        assert journal["restartRecommended"] == {"libs": ["torch"]}
        # The persisted journal carries it too (disconnect-safe).
        from utk_curio.backend.app.packages.build_promotion import load_journal

        stored = load_journal("guest", journal["artifactDigest"])
        assert stored["restartRecommended"] == {"libs": ["torch"]}

    def test_skipped_only_install_stays_silent(
            self, tmp_curio, manifest_dict, monkeypatch):
        journal = self._promote_with_pip(
            tmp_curio, manifest_dict, monkeypatch,
            installed=[], skipped=["torch", "shapely"])
        assert "restartRecommended" not in journal

    def test_no_python_deps_stays_silent(self, tmp_curio, manifest_dict, monkeypatch):
        from utk_curio.backend.app.packages import pip_runner

        def _never(deps, on_line=None):  # pragma: no cover — must not run
            raise AssertionError("pip must not be invoked without declared deps")

        monkeypatch.setattr(pip_runner, "install_python_deps", _never)
        digest = _stage_build(manifest_dict)
        journal = promote("guest", target="ai.test.demo@1", artifact_digest=digest)
        assert "restartRecommended" not in journal


def _stage_backend_build(manifest_dict, *, entry_src, python_deps=None,
                         warm_python_kind=False, user_key="guest") -> str:
    """A staged backend-bearing archive (dev/97 routing/probe tests)."""
    kinds = [{
        "id": "counter-kind", "label": "Counter", "category": "computation",
        "engine": "python", "editor": "none", "hasCode": False,
        "hasWidgets": False, "hasGrammar": False,
        "inputPorts": [], "outputPorts": [{"types": ["JSON"], "cardinality": "1"}],
        "backendHandler": "word-count",
    }]
    if warm_python_kind:
        kinds.append({
            "id": "warm-kind", "label": "Warm", "category": "computation",
            "engine": "python", "editor": "code", "hasCode": True,
            "hasWidgets": False, "hasGrammar": False,
            "inputPorts": [], "outputPorts": [],
        })
    manifest = manifest_dict(kinds=kinds, python_deps=python_deps)
    manifest["permissions"] = ["server-code"]
    manifest["backend"] = {"entry": "backend/handler.py",
                           "handlers": [{"name": "word-count",
                                         "timeoutClass": "quick"}]}
    request = parse_build_request({
        "mode": "create", "target": "ai.test.demo@1", "manifest": manifest,
        "files": {"backend/handler.py": {"text": entry_src}},
    })
    archive, _ = assemble_archive(request, request.files, None, {
        "python": python_deps or {}, "js": {}, "packages": {},
    })
    return build_staging.stage_artifact(user_key, archive)


class TestOverlayRoutingAndPostApplyProbe:
    """dev/97: ONE routing rule at Apply (overlay / host / both), the
    journal's overlay provenance, dev/92's restart signal narrowed to the
    HOST portion, and the post-Apply probe (REAL worker) gating activation
    with rollback compensation."""

    _OK_ENTRY = "def handle(payload):\n    return {'ok': True}\n"

    def test_backend_only_deps_go_overlay_only_no_restart(
            self, tmp_curio, manifest_dict, monkeypatch):
        from utk_curio.backend.app.packages import backend_runtime, pip_runner

        calls = {}

        def _fake_overlay(user_key, dir_name, deps, on_line=None):
            calls["overlay"] = (dir_name, dict(deps))
            return {"libs": [f"{n}=={v}" for n, v in sorted(deps.items())],
                    "bytes": 1234}

        def _never_host(deps, on_line=None):  # pragma: no cover
            raise AssertionError("host pip must not run for overlay-only routing")

        monkeypatch.setattr(backend_runtime, "build_overlay", _fake_overlay)
        monkeypatch.setattr(pip_runner, "install_python_deps", _never_host)
        digest = _stage_backend_build(manifest_dict, entry_src=self._OK_ENTRY,
                                      python_deps={"tinylib": "1.0.0"})
        journal = promote("guest", target="ai.test.demo@1", artifact_digest=digest)
        assert journal["status"] == "awaiting-activation"
        assert calls["overlay"] == ("ai.test.demo@1", {"tinylib": "1.0.0"})
        assert journal["overlay"]["libs"] == ["tinylib==1.0.0"]
        assert journal["overlay"]["bytes"] == 1234
        assert "shared interpreter is not touched" in journal["overlay"]["reason"]
        # dev/92 narrowed: overlay changes never split-brain fresh workers.
        assert "restartRecommended" not in journal

    def test_mixed_manifest_routes_both_restart_from_host_half(
            self, tmp_curio, manifest_dict, monkeypatch):
        from utk_curio.backend.app.packages import backend_runtime, pip_runner

        calls = {"overlay": False, "host": False}
        monkeypatch.setattr(
            backend_runtime, "build_overlay",
            lambda uk, dn, deps, on_line=None: calls.__setitem__("overlay", True)
            or {"libs": ["tinylib==1.0.0"], "bytes": 10})
        monkeypatch.setattr(
            pip_runner, "install_python_deps",
            lambda deps, on_line=None: calls.__setitem__("host", True)
            or pip_runner.InstallReport(installed=["tinylib"], skipped=[]))
        digest = _stage_backend_build(manifest_dict, entry_src=self._OK_ENTRY,
                                      python_deps={"tinylib": "1.0.0"},
                                      warm_python_kind=True)
        journal = promote("guest", target="ai.test.demo@1", artifact_digest=digest)
        assert calls == {"overlay": True, "host": True}
        assert journal["restartRecommended"] == {"libs": ["tinylib"]}
        assert "python node templates" in journal["overlay"]["reason"]

    def test_post_apply_probe_passes_a_healthy_backend(
            self, tmp_curio, manifest_dict):
        digest = _stage_backend_build(manifest_dict, entry_src=self._OK_ENTRY)
        journal = promote("guest", target="ai.test.demo@1", artifact_digest=digest)
        assert journal["status"] == "awaiting-activation"

    def test_post_apply_probe_failure_rolls_back(self, tmp_curio, manifest_dict):
        digest = _stage_backend_build(
            manifest_dict, entry_src="import not_a_real_module\n" + self._OK_ENTRY)
        with pytest.raises(PromotionError) as exc:
            promote("guest", target="ai.test.demo@1", artifact_digest=digest)
        assert exc.value.status == 422
        assert "failed its post-apply probe" in str(exc.value)
        assert "not_a_real_module" in str(exc.value)
        assert "restored" in str(exc.value)
        # The fresh create rolled back — nothing remains installed.
        assert not (package_dir("guest", "ai.test.demo@1")).exists()

    def test_overlay_reaches_the_post_apply_probe(self, tmp_curio, manifest_dict,
                                                  monkeypatch):
        # Module-level import of a dep that exists ONLY in the overlay: the
        # probe passes exactly because the overlay rides PYTHONPATH — the
        # shadowing edge exercised end to end with a real worker.
        from utk_curio.backend.app.packages import backend_runtime

        def _fake_overlay(user_key, dir_name, deps, on_line=None):
            overlay = backend_runtime.overlay_dir_for(user_key, dir_name)
            overlay.mkdir(parents=True, exist_ok=True)
            (overlay / "ovl_dep.py").write_text("X = 1\n", encoding="utf-8")
            return {"libs": ["ovl-dep==1.0"], "bytes": 8}

        monkeypatch.setattr(backend_runtime, "build_overlay", _fake_overlay)
        digest = _stage_backend_build(
            manifest_dict,
            entry_src="import ovl_dep\ndef handle(payload):\n"
                      "    return {'x': ovl_dep.X}\n",
            python_deps={"ovl-dep": "1.0"})
        journal = promote("guest", target="ai.test.demo@1", artifact_digest=digest)
        assert journal["status"] == "awaiting-activation"
        assert journal["overlay"]["libs"] == ["ovl-dep==1.0"]
