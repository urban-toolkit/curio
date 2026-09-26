"""Mirror a dataset's lakeSource block in the index.

The dataset index exists so a catalog listing costs one stat per directory
instead of a JSON parse: the listing rebuilds each manifest from its row. A
manifest field the index does not carry therefore disappears from every catalog
surface, however correct the file on disk is.

``lakeSource`` records which portal resource a downloaded dataset came from,
and one of the things that reads it is the check that answers "do I already
hold this?" - so without this column the same file downloads twice, once per
click, and the Data Catalog fills up with duplicates.

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-09-24 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "b8c9d0e1f2a3"
down_revision = "a7b8c9d0e1f2"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("dataset_index_entry", schema=None) as batch_op:
        batch_op.add_column(sa.Column("lake_source_json", sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table("dataset_index_entry", schema=None) as batch_op:
        batch_op.drop_column("lake_source_json")
