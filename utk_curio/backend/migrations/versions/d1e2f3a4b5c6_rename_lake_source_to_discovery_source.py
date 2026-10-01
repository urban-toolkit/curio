"""Rename the index's provenance column for the Discovery Catalog.

The block a downloaded dataset carries is ``discoverySource`` now, with
``sourceId`` and ``sourceName`` in it. A manifest written before the rename
still says ``lakeSource``, which nothing reads, so the old values are cleared
here as well: the index and the manifests on disk then agree that those
datasets carry no provenance, and their files are untouched.

Revision ID: d1e2f3a4b5c6
Revises: c0d1e2f3a4b5
Create Date: 2026-10-01 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "d1e2f3a4b5c6"
down_revision = "c0d1e2f3a4b5"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("dataset_index_entry", schema=None) as batch_op:
        batch_op.alter_column(
            "lake_source_json",
            new_column_name="discovery_source_json",
            existing_type=sa.Text(),
            existing_nullable=True,
        )
    op.execute("UPDATE dataset_index_entry SET discovery_source_json = NULL")


def downgrade():
    with op.batch_alter_table("dataset_index_entry", schema=None) as batch_op:
        batch_op.alter_column(
            "discovery_source_json",
            new_column_name="lake_source_json",
            existing_type=sa.Text(),
            existing_nullable=True,
        )
