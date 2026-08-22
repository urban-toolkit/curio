"""Create the per-user dataset index table.

A queryable mirror of the account dataset store's manifests, so catalog reads
are keyed lookups instead of a full manifest scan. The table is a derived cache
(rebuilt from disk by ``datasets.repositories.index.reconcile``), so dropping it
loses no user data — the next listing re-populates it.

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-08-22 14:10:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "d4e5f6a7b8c9"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "dataset_index_entry",
        sa.Column("id", sa.Integer(), primary_key=True),
        # Store owner: a user id as a string, or the literal "guest" for the
        # shared guest store. Not a FK — "guest" is not a user.id value.
        sa.Column("user_key", sa.String(64), nullable=False),
        sa.Column("dataset_id", sa.String(255), nullable=False),
        sa.Column("dir_name", sa.String(255), nullable=False),
        sa.Column("major", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("origin", sa.String(32), nullable=False),
        sa.Column("title", sa.Text(), nullable=False, server_default=""),
        sa.Column("version", sa.String(32), nullable=True),
        sa.Column("format", sa.String(32), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("publisher", sa.Text(), nullable=True),
        sa.Column("license", sa.Text(), nullable=True),
        sa.Column("tags_json", sa.Text(), nullable=True),
        sa.Column("schema_json", sa.Text(), nullable=True),
        sa.Column("data_file", sa.Text(), nullable=False),
        sa.Column("source_label", sa.Text(), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=True),
        sa.Column("feature_count", sa.Integer(), nullable=True),
        sa.Column("group_id", sa.String(255), nullable=True),
        sa.Column("layer_name", sa.String(255), nullable=True),
        sa.Column("created_at_iso", sa.String(40), nullable=True),
        sa.Column("updated_at_iso", sa.String(40), nullable=True),
        sa.Column("source_updated_at_iso", sa.String(40), nullable=True),
        sa.Column("producer_node_id", sa.String(255), nullable=True),
        sa.Column("producer_node_type", sa.String(255), nullable=True),
        sa.Column("producer_dataflow_id", sa.String(64), nullable=True),
        sa.Column("producer_dataflow_name", sa.Text(), nullable=True),
        sa.Column("upstream_inputs_json", sa.Text(), nullable=True),
        sa.Column("manifest_mtime_ns", sa.BigInteger(), nullable=True),
        sa.Column("manifest_size", sa.Integer(), nullable=True),
        sa.Column(
            "indexed_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("user_key", "dataset_id", name="uq_dataset_index_user_id"),
        sa.UniqueConstraint("user_key", "dir_name", name="uq_dataset_index_user_dir"),
    )

    op.create_index(
        "ix_dataset_index_user_origin",
        "dataset_index_entry",
        ["user_key", "origin"],
    )


def downgrade():
    op.drop_index("ix_dataset_index_user_origin", table_name="dataset_index_entry")
    op.drop_table("dataset_index_entry")
