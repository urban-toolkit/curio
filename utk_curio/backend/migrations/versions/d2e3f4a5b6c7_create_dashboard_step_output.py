"""Create the outputs a dashboard viewer's runs keep.

A viewer who changes a pinned control reruns the dataflow on the server, and
each step's output is kept under a key of what made it, so the next viewer who
picks the same values gets it with no run (``runs/viewer.py``). A new table
only: nothing existing is read or changed, and ``downgrade()`` drops it.

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
Create Date: 2026-10-24 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "d2e3f4a5b6c7"
down_revision = "c1d2e3f4a5b6"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "dashboard_step_output",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("project.id"), nullable=False),
        sa.Column("node_id", sa.String(255), nullable=False),
        sa.Column("step_key", sa.String(64), nullable=False),
        sa.Column("session_id", sa.String(64), nullable=False),
        sa.Column("output", sa.Text(), nullable=False),
        sa.Column("output_path", sa.String(255), nullable=False),
        sa.Column("artifact_ids", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("private_to", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_dashboard_step_output_key", "dashboard_step_output", ["project_id", "step_key"],
    )
    op.create_index(
        "ix_dashboard_step_output_path", "dashboard_step_output", ["project_id", "output_path"],
    )
    op.create_index(
        "ix_dashboard_step_output_created", "dashboard_step_output", ["created_at"],
    )


def downgrade():
    op.drop_index("ix_dashboard_step_output_created", table_name="dashboard_step_output")
    op.drop_index("ix_dashboard_step_output_path", table_name="dashboard_step_output")
    op.drop_index("ix_dashboard_step_output_key", table_name="dashboard_step_output")
    op.drop_table("dashboard_step_output")
