"""Drop the account's Data source keys from user.

An account's Data source keys live in an owner-only file beside its other
per-user stores (``users/source_keys.py``), keyed by the secret id a source
manifest declares, so the four key columns are gone. Nothing is carried over:
the file starts empty and each user enters their keys again in API Settings.

Revision ID: c1d2e3f4a5b6
Revises: b0c1d2e3f4a5
Create Date: 2026-10-18 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "c1d2e3f4a5b6"
down_revision = "b0c1d2e3f4a5"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("user", schema=None) as batch_op:
        batch_op.drop_column("mapillary_access_token")
        batch_op.drop_column("google_maps_api_key")
        batch_op.drop_column("socrata_app_token")
        batch_op.drop_column("huggingface_token")


def downgrade():
    with op.batch_alter_table("user", schema=None) as batch_op:
        batch_op.add_column(sa.Column("huggingface_token", sa.String(255), nullable=True))
        batch_op.add_column(sa.Column("socrata_app_token", sa.String(255), nullable=True))
        batch_op.add_column(sa.Column("google_maps_api_key", sa.String(255), nullable=True))
        batch_op.add_column(sa.Column("mapillary_access_token", sa.String(255), nullable=True))
