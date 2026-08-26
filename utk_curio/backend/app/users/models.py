from datetime import datetime, timedelta, timezone
from uuid import uuid4

from utk_curio.backend.extensions import db


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=True)
    name = db.Column(db.String(100), nullable=False)
    password_hash = db.Column(db.String(255), nullable=True)
    profile_image = db.Column(db.String(200), nullable=True)
    type = db.Column(db.String(100), nullable=True)
    provider = db.Column(db.String(50), nullable=True)
    provider_uid = db.Column(db.String(200), nullable=True)
    is_guest = db.Column(db.Boolean, default=False, nullable=False)
    llm_api_type = db.Column(db.String(50), nullable=True)
    llm_base_url = db.Column(db.String(500), nullable=True)
    llm_api_key = db.Column(db.String(255), nullable=True)
    llm_model = db.Column(db.String(100), nullable=True)
    # Gated-model access on HuggingFace is a per-person entitlement (you
    # accept a model's licence with your own account), so this is an
    # account setting rather than one shared deployment secret.
    huggingface_token = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self):
        return f"<User {self.username!r}>"


SESSION_LIFETIME_DAYS = 30


class UserSession(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    token = db.Column(
        db.String(36), unique=True, default=lambda: str(uuid4()), nullable=False
    )
    active = db.Column(db.Boolean, default=True, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=True)
    last_seen_at = db.Column(db.DateTime, nullable=True)

    user = db.relationship("User", backref=db.backref("sessions", lazy=True))

    @property
    def is_expired(self):
        if self.expires_at is None:
            return False
        return datetime.now(timezone.utc) > self.expires_at.replace(
            tzinfo=timezone.utc
        )

    def __repr__(self):
        return f"<UserSession {self.token!r}>"


class AuthAttempt(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    ip = db.Column(db.String(45), nullable=False)
    identifier = db.Column(db.String(200), nullable=False)
    success = db.Column(db.Boolean, nullable=False)
    created_at = db.Column(
        db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )

    # Mirrors migration a1b2c3d4e5f6 so model-vs-DB autogen stays clean.
    __table_args__ = (
        db.Index("ix_auth_attempt_ip_created", "ip", "created_at"),
        db.Index("ix_auth_attempt_ident_created", "identifier", "created_at"),
    )
