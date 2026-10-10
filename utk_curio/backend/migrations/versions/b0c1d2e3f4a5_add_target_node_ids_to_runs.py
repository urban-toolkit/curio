"""Add the nodes a run of several nodes ran.

An automatic run after a widget or Parameter change (#845) runs the nodes the
change touched and those below them. The run keeps their ids, so it says what
it ran and Run again runs the same nodes.

Revision ID: b0c1d2e3f4a5
Revises: a9b0c1d2e3f4
Create Date: 2026-10-10 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "b0c1d2e3f4a5"
down_revision = "a9b0c1d2e3f4"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("dataflow_run", schema=None) as batch_op:
        batch_op.add_column(sa.Column("target_node_ids", sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table("dataflow_run", schema=None) as batch_op:
        batch_op.drop_column("target_node_ids")
