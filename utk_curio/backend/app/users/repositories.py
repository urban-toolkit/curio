"""Data-access layer for User and UserSession."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import or_

from utk_curio.backend.extensions import db
from utk_curio.backend.app.users.models import (
    SESSION_LIFETIME_DAYS,
    User,
    UserSession,
)
from utk_curio.backend.app.users.security import new_session_token


def user_by_identifier(identifier: str) -> Optional[User]:
    return User.query.filter(
        or_(User.username == identifier, User.email == identifier)
    ).first()


def user_by_provider_uid(uid: str) -> Optional[User]:
    return User.query.filter_by(provider_uid=uid).first()


def user_by_username(username: str) -> Optional[User]:
    return User.query.filter_by(username=username).first()


def user_by_id(user_id: int) -> Optional[User]:
    # Session.get(), not the legacy Query.get(): same identity-map lookup by
    # primary key, but Query.get() emits a LegacyAPIWarning on every call and
    # this runs once per authenticated request.
    return db.session.get(User, user_id)


def create_user(**kwargs) -> User:
    user = User(**kwargs)
    db.session.add(user)
    db.session.commit()
    return user


def create_session(user_id: int) -> UserSession:
    now = datetime.now(timezone.utc)
    session = UserSession(
        user_id=user_id,
        token=new_session_token(),
        expires_at=now + timedelta(days=SESSION_LIFETIME_DAYS),
        last_seen_at=now,
    )
    db.session.add(session)
    db.session.commit()
    return session


def invalidate_session(token: str) -> bool:
    session = UserSession.query.filter_by(token=token, active=True).first()
    if not session:
        return False
    session.active = False
    db.session.commit()
    return True


def session_by_token(token: str) -> Optional[UserSession]:
    return UserSession.query.filter_by(token=token, active=True).first()


def touch_session(session: UserSession) -> None:
    session.last_seen_at = datetime.now(timezone.utc)
    db.session.commit()
