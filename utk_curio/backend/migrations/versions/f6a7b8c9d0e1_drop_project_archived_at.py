"""Remove the Archive feature: purge archived projects, drop archived_at.

Archiving was a one-way door - ``archived_at`` was stamped and nothing in the
product ever cleared it. There was no restore route and no unarchive action, so
it was a second permanent state that merely read as the cautious one (#261).

This revision does the purge and the schema change **together, deliberately**.
``dataset_usage(..., include_archived=True)`` is what stopped dataset delete and
imported-store uninstall from removing a store folder an archived project still
referenced (#176). Dropping that widening is only safe once nothing is archived,
because then the "all" and "mine" scopes are the same set. Split these into two
revisions and there is a window where that gate is blind.

The purge deletes each project's **files as well as its row**.
``services.reconcile_guest_projects()`` runs at every boot and re-imports any
folder under ``.curio/users/<guest>/projects/`` that has no ``Project`` row, so a
rows-only purge would resurrect every archived *guest* project on the next start
- as an active one. For numeric-id owners the row would stay gone but the folder
would leak indefinitely.

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-09-03 10:00:00.000000
"""
import shutil

from alembic import op
import sqlalchemy as sa

revision = "f6a7b8c9d0e1"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def _project_dir(user_key: str, project_id: str):
    """The on-disk tree for a project, resolved the way the app resolves it.

    Mirrors ``projects/storage.project_dir``; imported rather than reimplemented
    so a change to the layout reaches here too. ``users_base`` honours
    ``CURIO_LAUNCH_CWD`` and ``CURIO_TESTING``, both of which ``main.py`` passes
    into the ``flask db upgrade`` subprocess, so this lands on the same tree the
    backend uses - including ``.curio/test/`` under a test rig.
    """
    from utk_curio.backend.app.common.user_storage import user_key_segment, users_base

    return users_base() / user_key_segment(user_key) / "projects" / project_id


def _user_key(user_id, is_guest, username) -> str:
    """Mirrors ``projects/services._owner_user_dir_key``."""
    from utk_curio.backend.app.common.user_storage import GUEST_KEY
    from utk_curio.backend.config import CURIO_SHARED_GUEST_USERNAME

    if is_guest and username == CURIO_SHARED_GUEST_USERNAME:
        return GUEST_KEY
    return str(user_id)


def upgrade():
    conn = op.get_bind()

    # LEFT JOIN, not JOIN: a project whose owner row is gone must still be
    # purged rather than silently surviving the column drop.
    archived = conn.execute(
        sa.text(
            'SELECT p.id, p.user_id, u.is_guest, u.username '
            'FROM project p LEFT JOIN "user" u ON u.id = p.user_id '
            "WHERE p.archived_at IS NOT NULL"
        )
    ).fetchall()

    for project_id, user_id, is_guest, username in archived:
        try:
            tree = _project_dir(_user_key(user_id, is_guest, username), project_id)
        except ValueError:
            # user_key_segment rejected the key; leave the files alone rather
            # than guessing at a path.
            print(f"  ! could not resolve storage path for project {project_id}")
            continue
        if not tree.exists():
            continue
        try:
            shutil.rmtree(tree)
        except OSError as exc:
            # A locked or mmapped file must not abort the migration. The row
            # still goes; the folder is safe to remove by hand afterwards.
            print(f"  ! could not delete {tree}: {exc}")

    for project_id, *_ in archived:
        # exec_cache_entry holds the only FK to project.id, and SQLite does not
        # enforce it - delete the children explicitly or they orphan.
        conn.execute(
            sa.text("DELETE FROM exec_cache_entry WHERE project_id = :pid"),
            {"pid": project_id},
        )

    conn.execute(sa.text("DELETE FROM project WHERE archived_at IS NOT NULL"))
    if archived:
        print(f"  Purged {len(archived)} archived project(s)")

    # Drop the index BEFORE the batch: batch_alter_table reflects the table it
    # copies, and a reflected index over a column this batch removes cannot be
    # recreated on the new table.
    op.drop_index("ix_project_user_archived_opened", table_name="project")

    with op.batch_alter_table("project") as batch_op:
        batch_op.drop_column("archived_at")

    # Not optional. The dropped composite index led with user_id, which is why
    # there has never been a separate ix_project_user_id - plain lookups by
    # user_id used it too. See the comment in projects/models.py.
    op.create_index(
        "ix_project_user_opened",
        "project",
        ["user_id", sa.text("last_opened_at DESC")],
    )


def downgrade():
    """Restore the column and the old index.

    Purged projects do NOT come back: their rows, their exec-cache entries and
    their on-disk trees were deleted, not marked. This restores the shape of the
    schema, nothing else.
    """
    op.drop_index("ix_project_user_opened", table_name="project")

    with op.batch_alter_table("project") as batch_op:
        batch_op.add_column(sa.Column("archived_at", sa.DateTime(), nullable=True))

    op.create_index(
        "ix_project_user_archived_opened",
        "project",
        ["user_id", "archived_at", sa.text("last_opened_at DESC")],
    )
