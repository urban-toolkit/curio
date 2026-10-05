"""Add the missing library and the install warnings to a run's steps.

A step whose code could not import a library records the reply's
``missingModule``, so a canvas opened after the run offers its install as the
canvas that ran it does. A step whose output could not be installed in the
Data Catalog records the warnings a save would have answered with.

Revision ID: a9b0c1d2e3f4
Revises: f7a8b9c0d1e2
Create Date: 2026-10-04 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "a9b0c1d2e3f4"
down_revision = "f7a8b9c0d1e2"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("dataflow_run_step", schema=None) as batch_op:
        batch_op.add_column(sa.Column("missing_module", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("install_warnings", sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table("dataflow_run_step", schema=None) as batch_op:
        batch_op.drop_column("install_warnings")
        batch_op.drop_column("missing_module")
