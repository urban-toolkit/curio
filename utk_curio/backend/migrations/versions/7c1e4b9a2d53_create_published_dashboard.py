"""Create the published dashboard table.

One row per dataflow its owner has published: the link token, who may run it,
and the snapshot of the saved dataflow that its runs execute. A new table only:
nothing existing is read or changed, and ``downgrade()`` drops it.

Revision ID: 7c1e4b9a2d53
Revises: a9b0c1d2e3f4
Create Date: 2026-10-12 13:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "7c1e4b9a2d53"
down_revision = "a9b0c1d2e3f4"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "published_dashboard",
        sa.Column("project_id", sa.String(36), sa.ForeignKey("project.id"), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("token", sa.String(64), nullable=False),
        sa.Column("access", sa.String(16), nullable=False, server_default="link"),
        sa.Column("spec_json", sa.Text(), nullable=False),
        sa.Column("spec_revision", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_published_dashboard_token", "published_dashboard", ["token"], unique=True)


def downgrade():
    op.drop_index("ix_published_dashboard_token", table_name="published_dashboard")
    op.drop_table("published_dashboard")
