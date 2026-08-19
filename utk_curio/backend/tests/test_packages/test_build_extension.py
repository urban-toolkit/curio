"""Tests for :mod:`utk_curio.backend.app.packages.build_extension` (dev/89 commit 2).

Extension snapshots (eligibility, digest pinning), the merge planner
(preserved/modified/added at file and template level, v1 refusals), the
generalized preservation output, and apply-time stale verification.
"""

from __future__ import annotations

import json

import pytest

from utk_curio.backend.app.packages.build_extension import (
    ExtensionError,
    compute_files_digest,
    installed_package_digest,
    merged_files,
    plan_create,
    plan_extension,
    snapshot_installed_package,
    verify_base_unchanged,
)
from utk_curio.backend.app.packages.build_models import parse_build_request
from utk_curio.backend.app.packages.storage import package_dir


def _kind(template_id: str, label: str = "Kind") -> dict:
    return {
        "id": template_id,
        "label": label,
        "category": "computation",
        "engine": "python",
        "editor": "code",
        "hasCode": True,
        "hasWidgets": False,
        "hasGrammar": False,
        "inputPorts": [],
        "outputPorts": [{"types": ["JSON"], "cardinality": "1"}],
        "templateDir": f"starters/{template_id}",
        "defaultTemplate": f"starters/{template_id}/Default.py",
    }


@pytest.fixture()
def installed_demo(install_packageage, manifest_dict):
    """An installed two-template package plus its raw manifest dict."""
    manifest = manifest_dict(kinds=[_kind("demo-kind"), _kind("other-kind")])
    install_packageage(
        "guest", manifest=manifest,
        sources={
            "demo-kind": {"Default.py": "def run():\n    return {}\n"},
            "other-kind": {"Default.py": "def run():\n    return 1\n"},
        },
    )
    return manifest


def _extend_payload(base_manifest: dict, base_digest: str, **overrides) -> dict:
    draft_manifest = dict(base_manifest)
    draft_manifest["version"] = "1.1.0"
    draft_manifest["templates"] = list(base_manifest["templates"]) + [_kind("note-kind", "Note")]
    payload = {
        "mode": "extend",
        "target": "ai.test.demo@1",
        "baseDigest": base_digest,
        "manifest": draft_manifest,
        "files": {
            "sources/note-kind.tsx": {"text": "export const note = 1\n"},
        },
        "behaviorEntries": ["sources/note-kind.tsx"],
    }
    payload.update(overrides)
    return payload


class TestSnapshot:
    def test_snapshot_pins_digest_and_files(self, tmp_curio, installed_demo):
        snap = snapshot_installed_package("guest", "ai.test.demo@1")
        assert snap.dir_name == "ai.test.demo@1"
        assert "manifest.json" in snap.files
        assert "starters/demo-kind/Default.py" in snap.files
        assert "integrity.json" not in snap.files  # derived state, never snapshotted
        assert snap.base_digest == compute_files_digest(snap.files)
        assert snap.base_digest == installed_package_digest("guest", "ai.test.demo@1")

    def test_not_installed_refused(self, tmp_curio):
        with pytest.raises(ExtensionError, match="not installed"):
            snapshot_installed_package("guest", "ai.test.ghost@1")

    def test_read_only_refused(self, tmp_curio, install_packageage, manifest_dict):
        manifest = manifest_dict(package_id="ai.test.locked")
        manifest["readOnly"] = True
        install_packageage("guest", manifest=manifest)
        with pytest.raises(ExtensionError, match="read-only"):
            snapshot_installed_package("guest", "ai.test.locked@1")

    def test_builtin_refused(self, tmp_curio, install_packageage, manifest_dict):
        from utk_curio.backend.app.packages.seed import BUILTIN_PACKAGE_ID

        install_packageage("guest", manifest=manifest_dict(package_id=BUILTIN_PACKAGE_ID))
        with pytest.raises(ExtensionError, match="seeded builtin"):
            snapshot_installed_package("guest", f"{BUILTIN_PACKAGE_ID}@1")


class TestPlanExtension:
    def test_happy_plan(self, tmp_curio, installed_demo):
        snap = snapshot_installed_package("guest", "ai.test.demo@1")
        request = parse_build_request(_extend_payload(installed_demo, snap.base_digest))
        plan = plan_extension(snap, request)
        assert plan.mode == "extend" and plan.base_digest == snap.base_digest
        assert plan.files_added == ("sources/note-kind.tsx",)
        assert plan.files_modified == ()
        assert set(plan.files_preserved) == {
            "starters/demo-kind/Default.py", "starters/other-kind/Default.py",
        }
        assert plan.templates_added == ("note-kind",)
        assert set(plan.templates_preserved) == {"demo-kind", "other-kind"}
        assert plan.templates_modified == ()

    def test_modified_file_and_template_detected(self, tmp_curio, installed_demo):
        snap = snapshot_installed_package("guest", "ai.test.demo@1")
        payload = _extend_payload(installed_demo, snap.base_digest)
        payload["files"]["starters/demo-kind/Default.py"] = {
            "text": "def run():\n    return {'v': 2}\n"
        }
        revised = [dict(t, label="Demo v2") if t["id"] == "demo-kind" else t
                   for t in payload["manifest"]["templates"]]
        payload["manifest"] = dict(payload["manifest"], templates=revised)
        plan = plan_extension(snap, parse_build_request(payload))
        assert plan.files_modified == ("starters/demo-kind/Default.py",)
        assert "demo-kind" in plan.templates_modified

    def test_identical_resubmission_is_preserved_with_warning(self, tmp_curio, installed_demo):
        snap = snapshot_installed_package("guest", "ai.test.demo@1")
        payload = _extend_payload(installed_demo, snap.base_digest)
        payload["files"]["starters/demo-kind/Default.py"] = {
            "text": snap.files["starters/demo-kind/Default.py"].decode()
        }
        plan = plan_extension(snap, parse_build_request(payload))
        assert "starters/demo-kind/Default.py" in plan.files_preserved
        assert any("byte-identical" in w for w in plan.warnings)

    def test_stale_base_refused(self, tmp_curio, installed_demo):
        snap = snapshot_installed_package("guest", "ai.test.demo@1")
        request = parse_build_request(_extend_payload(installed_demo, "e" * 64))
        with pytest.raises(ExtensionError, match="stale base"):
            plan_extension(snap, request)

    def test_implicit_template_removal_refused(self, tmp_curio, installed_demo):
        snap = snapshot_installed_package("guest", "ai.test.demo@1")
        payload = _extend_payload(installed_demo, snap.base_digest)
        payload["manifest"] = dict(payload["manifest"], templates=[
            t for t in payload["manifest"]["templates"] if t["id"] != "other-kind"
        ])
        with pytest.raises(ExtensionError, match="implicit"):
            plan_extension(snap, parse_build_request(payload))

    def test_duplicate_draft_template_ids_refused(self, tmp_curio, installed_demo):
        snap = snapshot_installed_package("guest", "ai.test.demo@1")
        payload = _extend_payload(installed_demo, snap.base_digest)
        payload["manifest"] = dict(
            payload["manifest"],
            templates=payload["manifest"]["templates"] + [_kind("note-kind")],
        )
        with pytest.raises(ExtensionError, match="twice"):
            plan_extension(snap, parse_build_request(payload))

    def test_behavior_key_collision_refused(self, tmp_curio, installed_demo):
        snap = snapshot_installed_package("guest", "ai.test.demo@1")
        payload = _extend_payload(installed_demo, snap.base_digest)
        templates = [dict(t) for t in payload["manifest"]["templates"]]
        for t in templates:
            if t["id"] in ("demo-kind", "note-kind"):
                t["behavior"] = "shared-note"
        payload["manifest"] = dict(
            payload["manifest"], templates=templates,
            behaviorScript="scripts/behaviors.js",
        )
        with pytest.raises(ExtensionError, match="behavior key"):
            plan_extension(snap, parse_build_request(payload))

    def test_requested_node_must_target_merged_template(self, tmp_curio, installed_demo):
        snap = snapshot_installed_package("guest", "ai.test.demo@1")
        good = _extend_payload(installed_demo, snap.base_digest,
                               nodes=[{"templateId": "other-kind"}])
        plan_extension(snap, parse_build_request(good))  # base template — allowed
        bad = _extend_payload(installed_demo, snap.base_digest,
                              nodes=[{"templateId": "ghost-kind"}])
        with pytest.raises(ExtensionError, match="merged package does not declare"):
            plan_extension(snap, parse_build_request(bad))

    def test_target_and_mode_mismatch_refused(self, tmp_curio, installed_demo):
        snap = snapshot_installed_package("guest", "ai.test.demo@1")
        create_req = parse_build_request({
            "mode": "create", "target": "ai.test.demo@1",
            "manifest": {"id": "ai.test.demo", "compatibility": {"major": 1},
                         "templates": [_kind("demo-kind")]},
        })
        with pytest.raises(ExtensionError, match="requires an extend request"):
            plan_extension(snap, create_req)


class TestMergedFilesAndPlanPayload:
    def test_generalized_preservation(self, tmp_curio, installed_demo):
        snap = snapshot_installed_package("guest", "ai.test.demo@1")
        request = parse_build_request(_extend_payload(installed_demo, snap.base_digest))
        merged = merged_files(snap, request)
        # Every untouched base file rides forward byte-identical…
        assert merged["starters/demo-kind/Default.py"] == snap.files[
            "starters/demo-kind/Default.py"]
        assert merged["starters/other-kind/Default.py"] == snap.files[
            "starters/other-kind/Default.py"]
        # …the draft's additions land…
        assert merged["sources/note-kind.tsx"] == b"export const note = 1\n"
        # …and builder-owned files never ride the merge.
        assert "manifest.json" not in merged
        assert "integrity.json" not in merged

    def test_plan_payload_shape_and_digest_stability(self, tmp_curio, installed_demo):
        snap = snapshot_installed_package("guest", "ai.test.demo@1")
        request = parse_build_request(_extend_payload(installed_demo, snap.base_digest))
        plan_a = plan_extension(snap, request)
        plan_b = plan_extension(snap, request)
        assert plan_a.to_payload() == plan_b.to_payload()
        assert plan_a.plan_digest() == plan_b.plan_digest()
        payload = plan_a.to_payload()
        assert set(payload) == {"mode", "target", "baseDigest", "files", "templates", "warnings"}
        json.dumps(payload)  # JSON-safe for the review card and apply check

    def test_plan_create_all_added(self):
        request = parse_build_request({
            "mode": "create", "target": "ai.test.fresh@1",
            "manifest": {"id": "ai.test.fresh", "compatibility": {"major": 1},
                         "templates": [{"id": "note-kind"}]},
            "files": {"sources/note.tsx": {"text": "x"}},
        })
        plan = plan_create(request)
        assert plan.mode == "create" and plan.base_digest is None
        assert plan.files_added == ("sources/note.tsx",)
        assert plan.files_preserved == () and plan.files_modified == ()
        assert plan.templates_added == ("note-kind",)


class TestStaleVerification:
    def test_verify_base_unchanged(self, tmp_curio, installed_demo):
        snap = snapshot_installed_package("guest", "ai.test.demo@1")
        assert verify_base_unchanged("guest", "ai.test.demo@1", snap.base_digest) is True
        # Any on-disk mutation flips the digest — the 409-stale path.
        target = package_dir("guest", "ai.test.demo@1")
        (target / "starters" / "demo-kind" / "Default.py").write_text(
            "def run():\n    return {'mutated': True}\n")
        assert verify_base_unchanged("guest", "ai.test.demo@1", snap.base_digest) is False

    def test_missing_package_digest_is_none(self, tmp_curio):
        assert installed_package_digest("guest", "ai.test.ghost@1") is None
        assert verify_base_unchanged("guest", "ai.test.ghost@1", "f" * 64) is False
