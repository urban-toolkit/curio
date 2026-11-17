"""Add the folders a kept output's rows may name to the kept outputs.

A dashboard viewer's step writes the files it derives in a folder of its own,
and the rows of a later step's output can name them too. The folder goes
when no kept output that names it is left (``runs/kept.py``). Empty for an
entry kept before: it names its own folder alone.

Revision ID: a5b6c7d8e9f0
Revises: f4a5b6c7d8e9
Create Date: 2026-11-17 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "a5b6c7d8e9f0"
down_revision = "f4a5b6c7d8e9"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("kept_step_output", schema=None) as batch_op:
        batch_op.add_column(sa.Column("media_folders", sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table("kept_step_output", schema=None) as batch_op:
        batch_op.drop_column("media_folders")
