"""Create the dataflow run tables.

One row per run of a dataflow on the server (``dataflow_run``) and one per node
the run touched (``dataflow_run_step``). New tables only: nothing existing is
read or changed, and ``downgrade()`` drops both.

Revision ID: f7a8b9c0d1e2
Revises: e2f3a4b5c6d7
Create Date: 2026-10-03 23:30:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "f7a8b9c0d1e2"
down_revision = "e2f3a4b5c6d7"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "dataflow_run",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("project.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("trigger", sa.String(16), nullable=False),
        sa.Column("target_node_id", sa.String(255), nullable=True),
        sa.Column("rerun_of", sa.String(36), nullable=True),
        sa.Column("spec_revision", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("ok_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("waiting_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("boot_id", sa.String(36), nullable=True),
    )
    op.create_index(
        "ix_dataflow_run_project_created", "dataflow_run", ["project_id", "created_at"],
    )
    op.create_index(
        "ix_dataflow_run_user_created", "dataflow_run", ["user_id", "created_at"],
    )

    op.create_table(
        "dataflow_run_step",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("dataflow_run.id"), nullable=False),
        sa.Column("node_id", sa.String(255), nullable=False),
        sa.Column("label", sa.Text(), nullable=True),
        sa.Column("node_type", sa.String(255), nullable=True),
        sa.Column("level", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("role", sa.String(16), nullable=False, server_default="run"),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("output_path", sa.Text(), nullable=True),
        sa.Column("output_type", sa.String(64), nullable=True),
        sa.Column("installed_dataset_id", sa.String(255), nullable=True),
        sa.Column("code_sha256", sa.String(64), nullable=True),
        sa.Column("stdout_tail", sa.Text(), nullable=True),
        sa.Column("stderr_tail", sa.Text(), nullable=True),
        sa.Column("skip_reason", sa.Text(), nullable=True),
        sa.UniqueConstraint("run_id", "node_id", name="uq_dataflow_run_step_node"),
    )


def downgrade():
    op.drop_table("dataflow_run_step")
    op.drop_index("ix_dataflow_run_user_created", table_name="dataflow_run")
    op.drop_index("ix_dataflow_run_project_created", table_name="dataflow_run")
    op.drop_table("dataflow_run")
