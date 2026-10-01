"""Add per-account Google Maps and Mapillary keys to user.

The Discovery Catalog's street-level imagery sources send them: Google Street
View bills each request to the key's owner, and Mapillary's token carries its
holder's rate limit. Stored the way ``socrata_app_token`` is, reported to
clients as booleans only, and edited in API Settings.

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-10-01 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "e2f3a4b5c6d7"
down_revision = "d1e2f3a4b5c6"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("user", schema=None) as batch_op:
        batch_op.add_column(sa.Column("google_maps_api_key", sa.String(255), nullable=True))
        batch_op.add_column(sa.Column("mapillary_access_token", sa.String(255), nullable=True))


def downgrade():
    with op.batch_alter_table("user", schema=None) as batch_op:
        batch_op.drop_column("mapillary_access_token")
        batch_op.drop_column("google_maps_api_key")
