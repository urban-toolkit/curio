"""Add when the output a run's step reused was made.

A step of a run on the server whose key holds an output its maker's runs
kept answers with that output and runs nothing, as a dashboard viewer's step
does (``runs/service.py``, ``runs/kept.py``'s ``kept_reply``). Its record
keeps when that output was made, so a tab that follows or reopens the run
says the result was reused. Empty for a step that ran, and for every step
recorded before.

Revision ID: c7d8e9f0a1b2
Revises: b6c7d8e9f0a1
Create Date: 2026-11-23 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "c7d8e9f0a1b2"
down_revision = "b6c7d8e9f0a1"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("dataflow_run_step", schema=None) as batch_op:
        batch_op.add_column(sa.Column("reused_made_at", sa.DateTime(), nullable=True))
