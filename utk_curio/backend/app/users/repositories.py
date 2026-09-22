"""Data-access layer for User and UserSession."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import or_

from utk_curio.backend.extensions import commit_with_retry, db
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
    def _apply() -> User:
        user = User(**kwargs)
        db.session.add(user)
        return user

    # Every write below goes through commit_with_retry for the same reason:
    # the request has already read (the username check, the session lookup)
    # before it writes, and SQLite fails that write outright when another
    # writer committed in between. See extensions.commit_with_retry.
    return commit_with_retry(_apply)


def create_session(user_id: int) -> UserSession:
    def _apply() -> UserSession:
        now = datetime.now(timezone.utc)
        session = UserSession(
            user_id=user_id,
            token=new_session_token(),
            expires_at=now + timedelta(days=SESSION_LIFETIME_DAYS),
            last_seen_at=now,
        )
        db.session.add(session)
        return session

    return commit_with_retry(_apply)


def invalidate_session(token: str) -> bool:
    def _apply() -> bool:
        session = UserSession.query.filter_by(token=token, active=True).first()
        if not session:
            return False
        session.active = False
        return True

    return commit_with_retry(_apply)


def session_by_token(token: str) -> Optional[UserSession]:
    return UserSession.query.filter_by(token=token, active=True).first()


#: How stale ``last_seen_at`` may get before a request refreshes it.
#:
#: It used to be written on every authenticated request, which made the
#: busiest write in the system a field nothing reads: session expiry is
#: decided by ``expires_at``, fixed when the session is created. On one
#: SQLite file with a hundred users that write became the dominant source of
#: lock contention -- every ``database is locked`` failure left in the
#: 100-user stress run was this statement, on requests that were otherwise
#: only reading.
#:
#: A minute of slack keeps the field's meaning (roughly when this session was
#: last active) and removes almost all of the writes.
SESSION_TOUCH_INTERVAL = timedelta(minutes=1)


def touch_session(session: UserSession) -> None:
    """Refresh the session's liveness stamp, at most once per interval."""
    now = datetime.now(timezone.utc)
    previous = session.last_seen_at
    if previous is not None:
        # Stored naive, in UTC.
        if previous.tzinfo is None:
            previous = previous.replace(tzinfo=timezone.utc)
        if now - previous < SESSION_TOUCH_INTERVAL:
            return

    def _apply() -> None:
        session.last_seen_at = now

    commit_with_retry(_apply)
