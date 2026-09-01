"""Hardening of the computed-id migration (#171).

The lazy read-path migration used to (a) mark the user migrated BEFORE running,
so a failed/partial run was never retried, and (b) move the dir with a
non-atomic ``shutil.move`` + manifest rewrite, so a crash could leave a renamed
dir whose stale-id manifest the strict loader rejects — the dataset vanished.

These tests pin the fixed behavior: success-only flagging with a filesystem
marker, retry-on-failure, marker short-circuit, deferred marker while
unattributable legacy dirs remain, crash-window self-healing, and preservation
of the source ``@<major>``.
"""
from __future__ import annotations

import json
from pathlib import Path

from utk_curio.backend.app.datasets.application import migrations
from utk_curio.backend.app.datasets.domain.manifest import (
    load_dataset_manifest,
    load_dataset_manifest_from_dir,
)
from utk_curio.backend.app.datasets.infrastructure.storage import dataset_dir
from utk_curio.backend.app.datasets.install.installer import computed_dataset_id
from utk_curio.backend.app.projects.services import _user_dir_key
from utk_curio.backend.tests.test_datasets.computed_test_helpers import (
    create_project,
    write_legacy_computed_dir,
)


def _write_owning_spec(app, user, project_id, legacy_id, node_id):
    from utk_curio.backend.app.projects import storage as project_storage

    with app.app_context():
        user_key = _user_dir_key(user)
        spec = {
            "dataflow": {
                "name": "Owner",
                "nodes": [{"id": node_id, "type": "PYTHON_COMPUTATION", "x": 0, "y": 0}],
                "edges": [],
                "datasets": [{
                    "datasetId": legacy_id,
                    "dirName": f"{legacy_id}@1",
                    "origin": "computed",
                    "producerNodeId": node_id,
                }],
            }
        }
        project_storage.write_spec(user_key, project_id, spec)


def test_marker_written_only_after_successful_complete_run(app, client, user_and_token):
    user, token = user_and_token
    with app.app_context():
        user_key = _user_dir_key(user)
    project_id = create_project(client, token, name="Marker owner")
    legacy_id = write_legacy_computed_dir(user_key, "marker-node")
    _write_owning_spec(app, user, project_id, legacy_id, "marker-node")

    with app.app_context():
        migrations.ensure_computed_ids_migrated(user_key)

        new_id = computed_dataset_id("marker-node", project_id)
        assert (dataset_dir(user_key, f"{new_id}@1") / "manifest.json").is_file()
        assert migrations._marker_path(user_key).is_file()
        assert user_key in migrations._migrated_users


def test_failed_run_is_not_flagged_and_retries(app, user_and_token, monkeypatch):
    user, _ = user_and_token
    with app.app_context():
        user_key = _user_dir_key(user)

        calls = []

        def _boom(key):
            calls.append(key)
            raise RuntimeError("disk hiccup")

        monkeypatch.setattr(migrations, "migrate_computed_dataset_ids", _boom)
        migrations.ensure_computed_ids_migrated(user_key)
        assert calls == [user_key]
        assert user_key not in migrations._migrated_users
        assert not migrations._marker_path(user_key).is_file()

        # The next listing retries.
        monkeypatch.setattr(migrations, "migrate_computed_dataset_ids", lambda k: calls.append(k) or 0)
        migrations.ensure_computed_ids_migrated(user_key)
        assert len(calls) == 2
        assert user_key in migrations._migrated_users


def test_marker_short_circuits_future_processes(app, user_and_token, monkeypatch):
    user, _ = user_and_token
    with app.app_context():
        user_key = _user_dir_key(user)
        marker = migrations._marker_path(user_key)
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("done\n", encoding="utf-8")

        calls = []
        monkeypatch.setattr(migrations, "migrate_computed_dataset_ids", lambda k: calls.append(k) or 0)
        migrations.ensure_computed_ids_migrated(user_key)
        assert calls == []
        assert user_key in migrations._migrated_users


def test_unattributable_dir_defers_marker_but_not_process_flag(app, user_and_token, monkeypatch):
    user, _ = user_and_token
    with app.app_context():
        user_key = _user_dir_key(user)
        write_legacy_computed_dir(user_key, "orphan-node")

        migrations.ensure_computed_ids_migrated(user_key)
        # Unattributable dir stays; no on-disk marker so a future process retries…
        assert (dataset_dir(user_key, "computed.orphan-node@1") / "manifest.json").is_file()
        assert not migrations._marker_path(user_key).is_file()
        # …but this process does not re-scan on every listing.
        assert user_key in migrations._migrated_users
        calls = []
        monkeypatch.setattr(migrations, "migrate_computed_dataset_ids", lambda k: calls.append(k) or 0)
        migrations.ensure_computed_ids_migrated(user_key)
        assert calls == []

        # Simulated new process: the guard is empty again → re-attempt happens.
        migrations._migrated_users.clear()
        migrations.ensure_computed_ids_migrated(user_key)
        assert calls == [user_key]


def test_rename_failure_leaves_legacy_dir_loadable(app, client, user_and_token, monkeypatch):
    user, token = user_and_token
    with app.app_context():
        user_key = _user_dir_key(user)
    project_id = create_project(client, token, name="Rename failure owner")
    legacy_id = write_legacy_computed_dir(user_key, "rf-node")
    _write_owning_spec(app, user, project_id, legacy_id, "rf-node")

    def _boom(src, dst):
        raise OSError("simulated rename failure")

    monkeypatch.setattr(migrations.os, "rename", _boom)
    with app.app_context():
        assert migrations.migrate_computed_dataset_ids(user_key) == 0

        legacy_dir = dataset_dir(user_key, f"{legacy_id}@1")
        # Intact and loadable, and no staged sidecar left behind.
        manifest = load_dataset_manifest(legacy_dir)
        assert manifest.id == legacy_id
        assert not (legacy_dir / migrations._MANIFEST_SIDECAR).exists()


def test_crashed_rename_self_heals_on_next_run(app, client, user_and_token):
    """Crash window: dir renamed, manifest swap missed. The dir carries the OLD
    manifest (stale id → strict loader rejects it) plus the staged sidecar; the
    next run must complete the swap and repoint the spec ref."""
    user, token = user_and_token
    with app.app_context():
        user_key = _user_dir_key(user)
    project_id = create_project(client, token, name="Self-heal owner")

    node_id = "heal-node"
    legacy_id = write_legacy_computed_dir(user_key, node_id)
    _write_owning_spec(app, user, project_id, legacy_id, node_id)

    with app.app_context():
        new_id = computed_dataset_id(node_id, project_id)
        legacy_dir = dataset_dir(user_key, f"{legacy_id}@1")
        dest = dataset_dir(user_key, f"{new_id}@1")

        # Hand-construct the crash state: renamed dir, stale manifest, sidecar.
        old_manifest_raw = json.loads((legacy_dir / "manifest.json").read_text(encoding="utf-8"))
        new_manifest_raw = dict(old_manifest_raw)
        new_manifest_raw["id"] = new_id
        new_manifest_raw["producerDataflowId"] = project_id
        legacy_dir.rename(dest)
        (dest / migrations._MANIFEST_SIDECAR).write_text(
            json.dumps(new_manifest_raw), encoding="utf-8"
        )

        healed = migrations.migrate_computed_dataset_ids(user_key)
        assert healed == 1

        manifest = load_dataset_manifest(dest)
        assert manifest.id == new_id
        assert manifest.producer_dataflow_id == project_id
        assert not (dest / migrations._MANIFEST_SIDECAR).exists()

        from utk_curio.backend.app.projects import storage as project_storage
        spec = project_storage.read_spec(user_key, project_id)
        ref = spec["dataflow"]["datasets"][0]
        assert ref["datasetId"] == new_id
        assert ref["dirName"] == f"{new_id}@1"


def test_sidecar_in_still_legacy_dir_is_discarded(app, user_and_token):
    """Crash BEFORE the rename: the staged sidecar is removed and the dir is
    treated as an ordinary legacy dir again."""
    user, _ = user_and_token
    with app.app_context():
        user_key = _user_dir_key(user)
        legacy_id = write_legacy_computed_dir(user_key, "presidecar-node")
        legacy_dir = dataset_dir(user_key, f"{legacy_id}@1")
        (legacy_dir / migrations._MANIFEST_SIDECAR).write_text("{}", encoding="utf-8")

        # No owning dataflow → the dir is skipped, but the sidecar must be gone.
        migrations.migrate_computed_dataset_ids(user_key)
        assert not (legacy_dir / migrations._MANIFEST_SIDECAR).exists()
        assert (legacy_dir / "manifest.json").is_file()


def test_migration_preserves_source_major(app, client, user_and_token):
    user, token = user_and_token
    with app.app_context():
        user_key = _user_dir_key(user)
    project_id = create_project(client, token, name="Major owner")
    node_id = "major-node"
    legacy_id = write_legacy_computed_dir(user_key, node_id, major=2)
    _write_owning_spec(app, user, project_id, legacy_id, node_id)
    # The spec ref points at the @2 dir.
    from utk_curio.backend.app.projects import storage as project_storage
    with app.app_context():
        spec = project_storage.read_spec(user_key, project_id)
        spec["dataflow"]["datasets"][0]["dirName"] = f"{legacy_id}@2"
        project_storage.write_spec(user_key, project_id, spec)

        assert migrations.migrate_computed_dataset_ids(user_key) == 1

        new_id = computed_dataset_id(node_id, project_id)
        dest = dataset_dir(user_key, f"{new_id}@2")
        manifest = load_dataset_manifest_from_dir(dest)
        assert manifest.id == new_id
        assert manifest.major == 2

        updated = project_storage.read_spec(user_key, project_id)
        ref = updated["dataflow"]["datasets"][0]
        assert ref["dirName"] == f"{new_id}@2"
