"""Mirror a dataset's collection block in the index.

A collection dataset is an index of files referenced where they are, and its
manifest says which lake source and resource those files belong to. The
dataset index rebuilds every manifest a listing shows from its row, so a
manifest field the index does not carry disappears from every catalog surface;
this column is what keeps the block visible.

Revision ID: c0d1e2f3a4b5
Revises: c9d0e1f2a3b4
Create Date: 2026-09-27 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "c0d1e2f3a4b5"
down_revision = "c9d0e1f2a3b4"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("dataset_index_entry", schema=None) as batch_op:
        batch_op.add_column(sa.Column("collection_json", sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table("dataset_index_entry", schema=None) as batch_op:
        batch_op.drop_column("collection_json")
