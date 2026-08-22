"""The per-user dataset index and its disk reconciliation.

The index mirrors the account store's manifests so catalog reads don't parse
every ``manifest.json``. It is a derived cache: reconcile refreshes it from disk,
and nothing it does may hide or invent a dataset.
"""

from __future__ import annotations

import json
import types

import pytest

from utk_curio.backend.app.datasets.repositories import index as index_repo


def _stub_user(user_id: int = 1):
    return types.SimpleNamespace(id=user_id, is_guest=False, username="alice")


@pytest.fixture()
def store(app, tmp_path, monkeypatch):
    """A user store rooted in this test's workspace, with the DB available."""
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))
    return tmp_path


def _install_imported(user_key="1", name="cities.csv", body=b"a,b\n1,2\n"):
    from utk_curio.backend.app.datasets.install.installer import install_imported_file

    return install_imported_file(user_key, body, name, "csv")


# ── upsert / get / forget ───────────────────────────────────────────────────

def test_upsert_get_forget_roundtrip(store):
    result = _install_imported()

    row = index_repo.upsert_from_dir("1", result.dest)
    assert row is not None
    assert row.dataset_id == result.manifest.id
    assert row.origin == "imported"
    assert row.format == "csv"
    assert row.data_file == result.manifest.data_file
    assert row.manifest_mtime_ns is not None

    fetched = index_repo.get("1", result.manifest.id)
    assert fetched is not None and fetched.id == row.id

    assert index_repo.forget("1", result.manifest.dir_name) is True
    assert index_repo.get("1", result.manifest.id) is None
    # Idempotent.
    assert index_repo.forget("1", result.manifest.dir_name) is False


def test_row_rebuilds_the_manifest_faithfully(store):
    """A row must rebuild the manifest it mirrors, so an indexed catalog item is
    identical to a scanned one (both go through ``item_from_manifest``)."""
    from utk_curio.backend.app.datasets.install.installer import (
        install_computed_file_for_node,
    )

    result = install_computed_file_for_node(
        "1", b'{"x": 1}', "out.json", "json",
        node_id="n-1", dataflow_id="flow-1", node_type="PYTHON",
        dataflow_name="My Flow",
        upstream_inputs=[{"nodeId": "up-1", "nodeType": "LOAD"}],
        title="Friendly Name",
    )
    row = index_repo.upsert_from_dir("1", result.dest)
    rebuilt = index_repo.manifest_from_row(row)
    original = result.manifest

    for field in (
        "id", "name", "version", "format", "description", "publisher", "license",
        "tags", "data_file", "major", "created_at", "updated_at",
        "source_updated_at", "feature_count", "row_count", "schema",
        "source_label", "group_id", "layer_name", "producer_node_id",
        "producer_node_type", "producer_dataflow_id", "producer_dataflow_name",
        "upstream_inputs",
    ):
        assert getattr(rebuilt, field) == getattr(original, field), field


def test_unindexable_dirs_get_no_row(store):
    """Only imported./computed. store dirs are indexed, and never one whose
    manifest the catalog itself would refuse to read."""
    from utk_curio.backend.app.datasets.infrastructure.storage import user_datasets_dir

    base = user_datasets_dir("1")
    base.mkdir(parents=True, exist_ok=True)

    # No manifest at all.
    no_manifest = base / "imported.xdeadbeef@1"
    no_manifest.mkdir()
    assert index_repo.upsert_from_dir("1", no_manifest) is None

    # Manifest present but invalid JSON.
    bad_json = base / "imported.xbadjson0@1"
    bad_json.mkdir()
    (bad_json / "manifest.json").write_text("{not json", encoding="utf-8")
    assert index_repo.upsert_from_dir("1", bad_json) is None

    # Valid JSON whose id doesn't match the dir name (load_dataset_manifest rejects).
    mismatched = base / "imported.xmismatch@1"
    mismatched.mkdir()
    (mismatched / "manifest.json").write_text(
        json.dumps({
            "id": "imported.xsomethingelse", "name": "X", "version": "1.0.0",
            "format": "csv", "dataFile": "data/x.csv", "compatibility": {"major": 1},
        }),
        encoding="utf-8",
    )
    assert index_repo.upsert_from_dir("1", mismatched) is None

    # A hub-style dir is not an account-level asset -> not indexed.
    hub_like = base / "data.city.blocks@1"
    hub_like.mkdir()
    assert index_repo.upsert_from_dir("1", hub_like) is None

    assert index_repo.list_for_user("1") == []


# ── reconcile ──────────────────────────────────────────────────────────────

def test_reconcile_adds_dir_the_writethrough_missed(store):
    """The self-healing case: a store dir with no row — a hand copy, a git
    checkout, or an upsert that failed at install time."""
    result = _install_imported()
    # Simulate the row never having been written (the installer's write-through
    # is best-effort, so this is the state a DB hiccup leaves behind).
    index_repo.forget("1", result.manifest.dir_name)
    assert index_repo.list_for_user("1") == []

    stats = index_repo.reconcile("1")

    assert stats["added"] == 1
    assert index_repo.get("1", result.manifest.id) is not None


def test_installers_write_through_immediately(store):
    """A freshly installed dataset is queryable without waiting for reconcile."""
    result = _install_imported()

    row = index_repo.get("1", result.manifest.id)
    assert row is not None
    assert row.dir_name == result.manifest.dir_name
    assert row.origin == "imported"


def test_reconcile_drops_row_for_deleted_dir(store):
    import shutil

    result = _install_imported()
    index_repo.upsert_from_dir("1", result.dest)
    shutil.rmtree(result.dest)

    stats = index_repo.reconcile("1")

    assert stats["removed"] == 1
    assert index_repo.get("1", result.manifest.id) is None


def test_reconcile_refreshes_a_rewritten_manifest(store):
    """A manifest edited on disk (e.g. patch_manifest_file writing counts) is
    picked up via the stat pair, with no explicit write-through."""
    from utk_curio.backend.app.datasets.infrastructure.file_meta import (
        patch_manifest_file,
    )

    result = _install_imported()
    index_repo.upsert_from_dir("1", result.dest)
    assert index_repo.get("1", result.manifest.id).row_count is None

    patch_manifest_file(result.dest / "manifest.json", 42, None)
    stats = index_repo.reconcile("1")

    assert stats["updated"] == 1
    assert index_repo.get("1", result.manifest.id).row_count == 42


def test_reconcile_is_a_noop_when_nothing_changed(store, monkeypatch):
    """An unchanged store must not re-parse manifests or write to the DB — the
    read path calls this on every listing."""
    result = _install_imported()
    index_repo.reconcile("1")

    from utk_curio.backend.app.datasets.repositories import index as mod

    parses = {"n": 0}
    real_load = mod.load_dataset_manifest

    def counting_load(root):
        parses["n"] += 1
        return real_load(root)

    monkeypatch.setattr(mod, "load_dataset_manifest", counting_load)
    commits = {"n": 0}
    real_commit = mod.db.session.commit
    monkeypatch.setattr(
        mod.db.session, "commit",
        lambda: (commits.__setitem__("n", commits["n"] + 1), real_commit())[1],
    )

    stats = index_repo.reconcile("1")

    assert stats == {"added": 0, "updated": 0, "removed": 0}
    assert parses["n"] == 0, "an unchanged store must not parse any manifest"
    assert commits["n"] == 0, "an unchanged store must not write to the DB"
    assert index_repo.get("1", result.manifest.id) is not None


def test_reconcile_drops_row_that_became_unreadable(store):
    """A dir whose manifest is corrupted must lose its row, matching the
    listing's treatment of it as absent."""
    result = _install_imported()
    index_repo.upsert_from_dir("1", result.dest)

    (result.dest / "manifest.json").write_text("{broken", encoding="utf-8")
    stats = index_repo.reconcile("1")

    assert stats["removed"] == 1
    assert index_repo.get("1", result.manifest.id) is None


def test_rows_are_scoped_per_user_key(store):
    """Numeric user keys and the shared guest store never see each other's rows."""
    mine = _install_imported(user_key="1", name="mine.csv")
    guest = _install_imported(user_key="guest", name="guest.csv")

    index_repo.reconcile("1")
    index_repo.reconcile("guest")

    assert [r.dataset_id for r in index_repo.list_for_user("1")] == [mine.manifest.id]
    assert [r.dataset_id for r in index_repo.list_for_user("guest")] == [guest.manifest.id]
    assert index_repo.get("guest", mine.manifest.id) is None


def test_list_dataflow_computed_matches_only_that_dataflow(store):
    from utk_curio.backend.app.datasets.install.installer import (
        install_computed_file_for_node,
    )

    a = install_computed_file_for_node(
        "1", b"{}", "a.json", "json", node_id="n-1", dataflow_id="flow-a"
    )
    install_computed_file_for_node(
        "1", b"{}", "b.json", "json", node_id="n-2", dataflow_id="flow-b"
    )
    index_repo.reconcile("1")

    rows = index_repo.list_dataflow_computed("1", "flow-a")

    assert [r.dataset_id for r in rows] == [a.manifest.id]


# ── degradation ────────────────────────────────────────────────────────────

def test_safe_wrappers_never_raise_without_a_db(tmp_path, monkeypatch):
    """No app context (so no db.session): indexing must degrade to a no-op
    rather than break the dataset write or the listing that triggered it."""
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))
    result = _install_imported()

    # None of these run inside an app context — they must all be silent no-ops.
    index_repo.safe_upsert_from_dir("1", result.dest)
    index_repo.safe_forget("1", result.manifest.dir_name)
    index_repo.safe_reconcile("1")


def test_safe_wrappers_ignore_missing_user_key(store):
    index_repo.safe_upsert_from_dir(None, store)
    index_repo.safe_forget(None, "imported.x1@1")
    index_repo.safe_reconcile(None)
