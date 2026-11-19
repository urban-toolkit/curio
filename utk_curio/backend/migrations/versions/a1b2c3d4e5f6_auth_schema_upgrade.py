"""Auth schema upgrade: username, password_hash, nullable email, is_guest,
timestamps on User; expires_at/last_seen_at on UserSession; AuthAttempt table.

Revision ID: a1b2c3d4e5f6
Revises: 13c00188213d
Create Date: 2026-04-20 18:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision = "a1b2c3d4e5f6"
down_revision = "62a73b08f79f"
branch_labels = None
depends_on = None


def upgrade():
    # --- User table additions ---
    with op.batch_alter_table("user", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("username", sa.String(length=64), nullable=True)
        )
        batch_op.add_column(
            sa.Column("password_hash", sa.String(length=255), nullable=True)
        )
        batch_op.add_column(
            sa.Column("is_guest", sa.Boolean(), server_default="0", nullable=False)
        )
        batch_op.add_column(
            sa.Column(
                "created_at",
                sa.DateTime(),
                server_default=sa.func.now(),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "updated_at",
                sa.DateTime(),
                server_default=sa.func.now(),
                nullable=True,
            )
        )
        batch_op.alter_column("email", existing_type=sa.String(120), nullable=True)

    # Backfill username from email local-part (or "user_<id>" when email is null)
    conn = op.get_bind()
    users = conn.execute(
        text("SELECT id, email FROM user WHERE username IS NULL")
    ).fetchall()

    seen: dict[str, int] = {}
    for uid, email in users:
        if email:
            base = email.split("@")[0]
        else:
            base = f"user_{uid}"
        candidate = base
        counter = 2
        while candidate in seen:
            candidate = f"{base}_{counter}"
            counter += 1
        seen[candidate] = uid
        conn.execute(
            text("UPDATE user SET username = :uname WHERE id = :uid"),
            {"uname": candidate, "uid": uid},
        )

    with op.batch_alter_table("user", schema=None) as batch_op:
        batch_op.alter_column("username", existing_type=sa.String(64), nullable=False)
        batch_op.create_unique_constraint("uq_user_username", ["username"])

    # --- UserSession additions ---
    with op.batch_alter_table("user_session", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("expires_at", sa.DateTime(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("last_seen_at", sa.DateTime(), nullable=True)
        )

    # --- AuthAttempt table ---
    op.create_table(
        "auth_attempt",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ip", sa.String(length=45), nullable=False),
        sa.Column("identifier", sa.String(length=200), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_auth_attempt_ip_created", "auth_attempt", ["ip", "created_at"])
    op.create_index(
        "ix_auth_attempt_ident_created",
        "auth_attempt",
        ["identifier", "created_at"],
    )
