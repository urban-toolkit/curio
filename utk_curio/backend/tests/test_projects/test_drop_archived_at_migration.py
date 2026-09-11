"""The Archive purge migration deletes rows, files and cache entries — and only those.

``f6a7b8c9d0e1`` is the one migration in this repo that destroys user data: for
every project with ``archived_at`` set it removes the row, its ``exec_cache_entry``
children and its on-disk tree, and ``downgrade()`` restores none of it. It runs
automatically on the next ``flask db upgrade``, so a mistake here is unrecoverable
for anyone who used Archive as a holding area (#261).

The suite builds its schema with ``db.create_all()``, so no other test executes
this revision. These run it against a scratch SQLite database and a scratch store,
following the pattern in ``test_datasets/test_dataset_index_migration.py``.

Deleting the *files* rather than only the rows is deliberate and is asserted here:
``services.reconcile_guest_projects()`` re-imports any folder under the guest tree
that has no ``Project`` row, so a rows-only purge would resurrect archived guest
projects on the next boot — as active ones.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa

REVISION = "f6a7b8c9d0e1"

# The schema as of e5f6a7b8c9d0, i.e. the shape the migration expects to find.
# Written out rather than reflected from the models, because the models no longer
# have ``archived_at`` — that is the whole point of the revision.
_PRE_SCHEMA = (
    """
    CREATE TABLE "user" (
        id INTEGER NOT NULL PRIMARY KEY,
        username VARCHAR(80) NOT NULL,
        is_guest BOOLEAN NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE project (
        id VARCHAR(36) NOT NULL PRIMARY KEY,
        user_id INTEGER,
        name TEXT,
        archived_at DATETIME,
        last_opened_at DATETIME
    )
    """,
    """
    CREATE TABLE exec_cache_entry (
        id INTEGER NOT NULL PRIMARY KEY,
        project_id VARCHAR(36) NOT NULL,
        activity_name TEXT NOT NULL,
        content_key VARCHAR(64) NOT NULL,
        output_filename TEXT NOT NULL
    )
    """,
    "CREATE INDEX ix_project_user_archived_opened "
    "ON project (user_id, archived_at, last_opened_at DESC)",
)


def _load_revision():
    versions = Path(__file__).resolve().parents[2] / "migrations" / "versions"
    matches = list(versions.glob(f"{REVISION}_*.py"))
    assert len(matches) == 1, f"expected one {REVISION} revision, found {matches}"
    spec = importlib.util.spec_from_file_location(f"_rev_{REVISION}", matches[0])
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _run(module, engine, func="upgrade") -> None:
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    with engine.begin() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            getattr(module, func)()


@pytest.fixture()
def store(tmp_path, monkeypatch):
    """Point the storage helpers at a scratch tree.

    ``CURIO_STATE_DIR`` relocates the whole ``.curio`` root, and ``users_base()``
    reads it at call time, which is what lets the migration's ``_project_dir``
    land here instead of on the developer's real store.
    """
    monkeypatch.setenv("CURIO_STATE_DIR", str(tmp_path / ".curio"))
    monkeypatch.delenv("CURIO_TESTING", raising=False)

    from utk_curio.backend.app.common import user_storage

    base = user_storage.users_base()
    base.mkdir(parents=True, exist_ok=True)
    return base


@pytest.fixture()
def engine():
    eng = sa.create_engine("sqlite://")
    with eng.begin() as conn:
        for stmt in _PRE_SCHEMA:
            conn.execute(sa.text(stmt))
    return eng


def _seed(engine, store, rows):
    """Insert *rows* and create each project's folder with one file inside.

    Each row is ``(project_id, user_id, is_guest, username, archived)``.
    """
    from utk_curio.backend.app.common.user_storage import GUEST_KEY
    from utk_curio.backend.config import CURIO_SHARED_GUEST_USERNAME

    with engine.begin() as conn:
        seen_users = set()
        for pid, uid, is_guest, username, archived in rows:
            if uid not in seen_users:
                conn.execute(
                    sa.text(
                        'INSERT INTO "user" (id, username, is_guest) '
                        "VALUES (:id, :u, :g)"
                    ),
                    {"id": uid, "u": username, "g": 1 if is_guest else 0},
                )
                seen_users.add(uid)
            conn.execute(
                sa.text(
                    "INSERT INTO project (id, user_id, name, archived_at) "
                    "VALUES (:id, :uid, :n, :a)"
                ),
                {
                    "id": pid,
                    "uid": uid,
                    "n": pid,
                    "a": "2026-09-01 00:00:00" if archived else None,
                },
            )
            conn.execute(
                sa.text(
                    "INSERT INTO exec_cache_entry "
                    "(project_id, activity_name, content_key, output_filename) "
                    "VALUES (:pid, 'a', 'k', 'o')"
                ),
                {"pid": pid},
            )

    dirs = {}
    for pid, uid, is_guest, username, _archived in rows:
        key = (
            GUEST_KEY
            if is_guest and username == CURIO_SHARED_GUEST_USERNAME
            else str(uid)
        )
        tree = store / key / "projects" / pid
        tree.mkdir(parents=True, exist_ok=True)
        (tree / "spec.json").write_text("{}", encoding="utf-8")
        dirs[pid] = tree
    return dirs


def _guest_username() -> str:
    from utk_curio.backend.config import CURIO_SHARED_GUEST_USERNAME

    return CURIO_SHARED_GUEST_USERNAME


def test_purges_archived_rows_files_and_cache_for_guest_and_owner(engine, store):
    """The destructive half: everything archived goes, for both owner kinds."""
    rows = [
        ("arch-guest", 1, True, _guest_username(), True),
        ("live-guest", 1, True, _guest_username(), False),
        ("arch-owner", 2, False, "alice", True),
        ("live-owner", 2, False, "alice", False),
    ]
    dirs = _seed(engine, store, rows)

    _run(_load_revision(), engine)

    with engine.begin() as conn:
        ids = {r[0] for r in conn.execute(sa.text("SELECT id FROM project"))}
        cached = {
            r[0]
            for r in conn.execute(sa.text("SELECT project_id FROM exec_cache_entry"))
        }

    assert ids == {"live-guest", "live-owner"}
    assert cached == {"live-guest", "live-owner"}, "orphaned exec cache rows"

    assert not dirs["arch-guest"].exists()
    assert not dirs["arch-owner"].exists()
    assert (dirs["live-guest"] / "spec.json").exists(), "purge touched a live project"
    assert (dirs["live-owner"] / "spec.json").exists(), "purge touched a live project"


def test_leaves_no_guest_folder_a_reboot_would_re_import(engine, store):
    """A rows-only purge would resurrect archived guest projects as active ones.

    This is the reason the migration deletes files, so it is asserted directly:
    after the upgrade, no folder under the guest tree lacks a ``project`` row.
    """
    from utk_curio.backend.app.common.user_storage import GUEST_KEY

    rows = [
        ("arch-guest", 1, True, _guest_username(), True),
        ("live-guest", 1, True, _guest_username(), False),
    ]
    _seed(engine, store, rows)

    _run(_load_revision(), engine)

    with engine.begin() as conn:
        ids = {r[0] for r in conn.execute(sa.text("SELECT id FROM project"))}

    on_disk = {p.name for p in (store / GUEST_KEY / "projects").iterdir()}
    assert on_disk == ids, f"folders with no row would be re-imported: {on_disk - ids}"


def test_a_project_whose_owner_row_is_gone_is_still_purged(engine, store):
    """The migration LEFT JOINs, so an orphaned project must not survive."""
    rows = [("arch-owner", 2, False, "alice", True)]
    dirs = _seed(engine, store, rows)
    with engine.begin() as conn:
        conn.execute(sa.text('DELETE FROM "user" WHERE id = 2'))

    _run(_load_revision(), engine)

    with engine.begin() as conn:
        remaining = conn.execute(sa.text("SELECT COUNT(*) FROM project")).scalar()
    assert remaining == 0
    assert not dirs["arch-owner"].exists()


def test_an_undeletable_tree_does_not_abort_the_migration(engine, store, monkeypatch):
    """A locked file must not leave the schema half-migrated.

    The row still goes and the column is still dropped; the folder is reported
    and left for manual cleanup. Worth pinning, because the alternative — an
    exception here — would abort ``flask db upgrade`` and leave the deployment
    unable to start.
    """
    rows = [
        ("arch-owner", 2, False, "alice", True),
        ("live-owner", 2, False, "alice", False),
    ]
    _seed(engine, store, rows)

    module = _load_revision()

    def _boom(path):
        raise OSError("file is in use by another process")

    monkeypatch.setattr(module.shutil, "rmtree", _boom)

    _run(module, engine)

    with engine.begin() as conn:
        ids = {r[0] for r in conn.execute(sa.text("SELECT id FROM project"))}
        cols = {
            r[1] for r in conn.execute(sa.text("PRAGMA table_info(project)")).fetchall()
        }

    assert ids == {"live-owner"}
    assert "archived_at" not in cols, "schema change was skipped after the file error"


def test_drops_the_column_and_replaces_the_index(engine, store):
    """The composite index led with user_id, so it must be replaced, not just dropped."""
    _seed(engine, store, [("live-owner", 2, False, "alice", False)])

    _run(_load_revision(), engine)

    with engine.begin() as conn:
        cols = {r[1] for r in conn.execute(sa.text("PRAGMA table_info(project)"))}
        indexes = {r[1] for r in conn.execute(sa.text("PRAGMA index_list(project)"))}

    assert "archived_at" not in cols
    assert "ix_project_user_archived_opened" not in indexes
    assert "ix_project_user_opened" in indexes, (
        "dropping the composite index without replacing it leaves lookups by "
        "user_id unindexed"
    )


def test_downgrade_restores_the_shape_but_not_the_data(engine, store):
    """Stated in the revision's own docstring; pinned so nobody assumes otherwise."""
    _seed(
        engine,
        store,
        [
            ("arch-owner", 2, False, "alice", True),
            ("live-owner", 2, False, "alice", False),
        ],
    )
    module = _load_revision()

    _run(module, engine)
    _run(module, engine, "downgrade")

    with engine.begin() as conn:
        cols = {r[1] for r in conn.execute(sa.text("PRAGMA table_info(project)"))}
        ids = {r[0] for r in conn.execute(sa.text("SELECT id FROM project"))}
        indexes = {r[1] for r in conn.execute(sa.text("PRAGMA index_list(project)"))}

    assert "archived_at" in cols
    assert "ix_project_user_archived_opened" in indexes
    assert ids == {"live-owner"}, "downgrade must not appear to restore purged rows"
