"""Add llm config fields to user.

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-04-26 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "c3d4e5f6a7b8"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("user", schema=None) as batch_op:
        batch_op.add_column(sa.Column("llm_api_type", sa.String(50), nullable=True))
        batch_op.add_column(sa.Column("llm_base_url", sa.String(500), nullable=True))
        batch_op.add_column(sa.Column("llm_api_key", sa.String(255), nullable=True))
        batch_op.add_column(sa.Column("llm_model", sa.String(100), nullable=True))
