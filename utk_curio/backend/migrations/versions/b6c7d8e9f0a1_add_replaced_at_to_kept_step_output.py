"""Add when a later run of the same step replaced a kept output.

A kept output that a later run of its node replaces, under the same key, by
the same maker for the same reader, is marked replaced with the time: it
serves every read it served until the first sweep an hour on drops it
(``runs/kept.py``). Empty for an entry kept before: none is replaced.

Revision ID: b6c7d8e9f0a1
Revises: a5b6c7d8e9f0
Create Date: 2026-11-23 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "b6c7d8e9f0a1"
down_revision = "a5b6c7d8e9f0"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("kept_step_output", schema=None) as batch_op:
        batch_op.add_column(sa.Column("replaced_at", sa.DateTime(), nullable=True))
