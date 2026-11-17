"""Drop the account's single LLM configuration from user.

An account now holds named LLM configurations and a default, in an owner-only
file beside its other per-user stores (``agents/llm_configs.py``), so the four
columns ``c3d4e5f6a7b8`` added are gone. Nothing is carried over: the new
store starts empty and the deployment default answers until the user adds a
configuration.

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-09-27 00:00:00.000000
"""
from alembic import op

revision = "c9d0e1f2a3b4"
down_revision = "b8c9d0e1f2a3"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("user", schema=None) as batch_op:
        batch_op.drop_column("llm_model")
        batch_op.drop_column("llm_api_key")
        batch_op.drop_column("llm_base_url")
        batch_op.drop_column("llm_api_type")
