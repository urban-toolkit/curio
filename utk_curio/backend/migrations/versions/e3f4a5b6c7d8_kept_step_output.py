"""Keep the outputs of any kept run, an owner's or a dashboard viewer's.

The table a dashboard viewer's runs kept their outputs in becomes the one every
kept run keeps them in (``runs/kept.py``), with ``made_by`` saying whose run
made each one: the dataflow's owner's or a viewer's, each with a budget of its
own. Its sessions take a new shape (``common/kept_sessions.py``), so the table
starts empty: a kept output is scratch for seven days, and the next run that
needs one makes it again. ``downgrade()`` puts the empty viewer's table back.

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
Create Date: 2026-10-25 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "e3f4a5b6c7d8"
down_revision = "d2e3f4a5b6c7"
branch_labels = None
depends_on = None

_COLUMNS = (
    ("id", lambda: sa.Column("id", sa.String(36), primary_key=True)),
    ("project_id", lambda: sa.Column("project_id", sa.String(36), sa.ForeignKey("project.id"), nullable=False)),
    ("node_id", lambda: sa.Column("node_id", sa.String(255), nullable=False)),
    ("step_key", lambda: sa.Column("step_key", sa.String(64), nullable=False)),
    ("session_id", lambda: sa.Column("session_id", sa.String(64), nullable=False)),
    ("output", lambda: sa.Column("output", sa.Text(), nullable=False)),
    ("output_path", lambda: sa.Column("output_path", sa.String(255), nullable=False)),
    ("artifact_ids", lambda: sa.Column("artifact_ids", sa.Text(), nullable=False, server_default="[]")),
    ("size_bytes", lambda: sa.Column("size_bytes", sa.BigInteger(), nullable=False, server_default="0")),
    ("private_to", lambda: sa.Column("private_to", sa.String(64), nullable=True)),
)


def _create(table: str, *extra) -> None:
    op.create_table(
        table,
        *(make() for _name, make in _COLUMNS),
        *extra,
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=False),
    )
    op.create_index(f"ix_{table}_key", table, ["project_id", "step_key"])
    op.create_index(f"ix_{table}_path", table, ["project_id", "output_path"])
    op.create_index(f"ix_{table}_created", table, ["created_at"])


def _drop(table: str) -> None:
    op.drop_index(f"ix_{table}_created", table_name=table)
    op.drop_index(f"ix_{table}_path", table_name=table)
    op.drop_index(f"ix_{table}_key", table_name=table)
    op.drop_table(table)


def upgrade():
    _drop("dashboard_step_output")
    _create("kept_step_output", sa.Column("made_by", sa.String(16), nullable=False, server_default="viewer"))


def downgrade():
    _drop("kept_step_output")
    _create("dashboard_step_output")
