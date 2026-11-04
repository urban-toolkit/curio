"""A dataflow's editors: the accounts its owner invited to edit it with them.

Everyone else who opens the dataflow's link watches it
(``projects/access.py``). One row per dataflow and account.

Revision ID: f4a5b6c7d8e9
Revises: e3f4a5b6c7d8
Create Date: 2026-10-28 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "f4a5b6c7d8e9"
down_revision = "e3f4a5b6c7d8"
branch_labels = None
depends_on = None

TABLE = "project_editor"


def upgrade():
    op.create_table(
        TABLE,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("project.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("added_by", sa.Integer(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("added_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("project_id", "user_id", name="uq_project_editor_project_user"),
    )
    op.create_index("ix_project_editor_user", TABLE, ["user_id"])


def downgrade():
    op.drop_index("ix_project_editor_user", table_name=TABLE)
    op.drop_table(TABLE)
