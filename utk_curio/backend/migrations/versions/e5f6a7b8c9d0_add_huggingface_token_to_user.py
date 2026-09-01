"""Add a per-account HuggingFace token to user.

The token used to be operator-only, read from a bare ``HUGGINGFACE_TOKEN``
environment variable. It gates access to *gated* HuggingFace models, which is a
per-person entitlement (you accept a model's licence with your own account), so
one shared deployment token could not represent what each user was allowed to
download. It is now an account setting, edited in AI Settings beside the LLM
provider, with the deployment value as the fallback.

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-08-26 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "e5f6a7b8c9d0"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("user", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("huggingface_token", sa.String(255), nullable=True)
        )


def downgrade():
    with op.batch_alter_table("user", schema=None) as batch_op:
        batch_op.drop_column("huggingface_token")
