"""Create project table and exec_cache_entry scaffold.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-04-20 22:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "b2c3d4e5f6a7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "project",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("slug", sa.String(240), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("folder_path", sa.String(512), nullable=False),
        sa.Column("thumbnail_accent", sa.String(16), server_default="peach"),
        sa.Column("spec_revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("last_opened_at", sa.DateTime(), nullable=True),
        sa.Column("archived_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
    )

    op.create_index(
        "ix_project_user_archived_opened",
        "project",
        ["user_id", "archived_at", sa.text("last_opened_at DESC")],
    )

    op.create_table(
        "exec_cache_entry",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("project.id"), nullable=False),
        sa.Column("activity_name", sa.Text(), nullable=False),
        sa.Column("content_key", sa.String(64), nullable=False),
        sa.Column("output_filename", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
    )

    op.create_index(
        "ix_exec_cache_project_key",
        "exec_cache_entry",
        ["project_id", "content_key"],
    )
