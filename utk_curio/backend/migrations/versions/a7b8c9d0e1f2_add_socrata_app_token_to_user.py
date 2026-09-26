"""Add a per-account Socrata app token to user.

The Data Lake Catalog reaches Socrata portals (Chicago's among them). Those
accept an app token, which is optional but raises the caller's rate limit
sharply - and the token is issued to a person, not to a deployment, so one
shared secret would mean every user of an install spending the same allowance
and being throttled together.

Stored the way ``huggingface_token`` is, and for the same reason: a per-person
entitlement belongs on the account. Reported to clients as a boolean only, and
edited in the account settings modal beside the other credentials.

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-09-24 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "a7b8c9d0e1f2"
down_revision = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("user", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("socrata_app_token", sa.String(255), nullable=True)
        )


def downgrade():
    with op.batch_alter_table("user", schema=None) as batch_op:
        batch_op.drop_column("socrata_app_token")
