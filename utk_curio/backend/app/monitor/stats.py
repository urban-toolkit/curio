"""Aggregate counts from the database, for the monitor page.

Everything here is a ``COUNT``, a ``SUM`` or a ``MAX``. No query in this module
selects a name, an email, an IP, a title or a path, because everything it
returns is published on a public route. ``AuthAttempt.ip`` appears exactly once,
inside ``count(distinct(...))``, which yields a number of distinct sources and
never a source.

TIMEZONE TRAP
-------------
``created_at``, ``last_seen_at`` and ``expires_at`` are ``db.DateTime`` with no
``timezone=True``, written from ``datetime.now(timezone.utc)``. SQLAlchemy's
SQLite DATETIME stores the naive rendering, so comparing them against an aware
``datetime`` compares a naive column to an aware bound and silently matches
nothing. ``UserSession.is_expired`` already works around this by re-attaching
``timezone.utc`` on the way out. Every cutoff here is therefore built with
``_cutoff()``, which strips the tzinfo after doing the arithmetic in UTC. A
test seeds rows at 30 minutes, 90 minutes and 25 hours to pin it.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import distinct, func

from utk_curio.backend.extensions import db

SIGN_IN_WINDOW_MINUTES = 60


def _cutoff(**kwargs) -> datetime:
    """A naive-UTC bound, matching how the columns are stored. See module doc."""
    return (datetime.now(timezone.utc) - timedelta(**kwargs)).replace(tzinfo=None)


def _now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def accounts() -> dict:
    from utk_curio.backend.app.users.models import AuthAttempt, User, UserSession

    total = db.session.query(func.count(User.id)).scalar() or 0
    guest = (
        db.session.query(func.count(User.id))
        .filter(User.is_guest.is_(True))
        .scalar()
    ) or 0
    created_24h = (
        db.session.query(func.count(User.id))
        .filter(User.created_at >= _cutoff(hours=24))
        .scalar()
    ) or 0

    now = _now_naive()
    active_sessions = (
        db.session.query(func.count(UserSession.id))
        .filter(
            UserSession.active.is_(True),
            db.or_(UserSession.expires_at.is_(None), UserSession.expires_at > now),
        )
        .scalar()
    ) or 0
    seen_5m = (
        db.session.query(func.count(UserSession.id))
        .filter(UserSession.last_seen_at >= _cutoff(minutes=5))
        .scalar()
    ) or 0
    seen_1h = (
        db.session.query(func.count(UserSession.id))
        .filter(UserSession.last_seen_at >= _cutoff(hours=1))
        .scalar()
    ) or 0

    sign_in_cutoff = _cutoff(minutes=SIGN_IN_WINDOW_MINUTES)
    success = (
        db.session.query(func.count(AuthAttempt.id))
        .filter(AuthAttempt.created_at >= sign_in_cutoff,
                AuthAttempt.success.is_(True))
        .scalar()
    ) or 0
    failure = (
        db.session.query(func.count(AuthAttempt.id))
        .filter(AuthAttempt.created_at >= sign_in_cutoff,
                AuthAttempt.success.is_(False))
        .scalar()
    ) or 0
    # The only use of .ip anywhere in this module, and it is inside a COUNT.
    distinct_sources = (
        db.session.query(func.count(distinct(AuthAttempt.ip)))
        .filter(AuthAttempt.created_at >= sign_in_cutoff)
        .scalar()
    ) or 0

    return {
        "total": int(total),
        "registered": int(total) - int(guest),
        "guest": int(guest),
        "createdLast24h": int(created_24h),
        "sessions": {
            "active": int(active_sessions),
            "seenLast5m": int(seen_5m),
            "seenLast1h": int(seen_1h),
        },
        "signIn": {
            "windowMinutes": SIGN_IN_WINDOW_MINUTES,
            "success": int(success),
            "failure": int(failure),
            "distinctSources": int(distinct_sources),
        },
    }


def content() -> dict:
    from utk_curio.backend.app.datasets.models import DatasetIndexEntry
    from utk_curio.backend.app.projects.models import ExecCacheEntry, Project

    projects_total = db.session.query(func.count(Project.id)).scalar() or 0
    projects_created = (
        db.session.query(func.count(Project.id))
        .filter(Project.created_at >= _cutoff(hours=24))
        .scalar()
    ) or 0
    projects_opened = (
        db.session.query(func.count(Project.id))
        .filter(Project.last_opened_at >= _cutoff(hours=24))
        .scalar()
    ) or 0
    stores_with_projects = (
        db.session.query(func.count(distinct(Project.user_id))).scalar()
    ) or 0

    datasets_total = db.session.query(func.count(DatasetIndexEntry.id)).scalar() or 0
    by_origin = dict(
        db.session.query(DatasetIndexEntry.origin, func.count(DatasetIndexEntry.id))
        .group_by(DatasetIndexEntry.origin)
        .all()
    )
    dataset_stores = (
        db.session.query(func.count(distinct(DatasetIndexEntry.user_key))).scalar()
    ) or 0
    total_bytes = db.session.query(func.sum(DatasetIndexEntry.size_bytes)).scalar() or 0
    largest_bytes = db.session.query(func.max(DatasetIndexEntry.size_bytes)).scalar() or 0

    exec_cache = db.session.query(func.count(ExecCacheEntry.id)).scalar() or 0

    return {
        "projects": {
            "total": int(projects_total),
            "createdLast24h": int(projects_created),
            "openedLast24h": int(projects_opened),
            "storesWithProjects": int(stores_with_projects),
        },
        "datasets": {
            "total": int(datasets_total),
            "imported": int(by_origin.get("imported", 0)),
            "computed": int(by_origin.get("computed", 0)),
            "stores": int(dataset_stores),
            "totalBytes": int(total_bytes),
            "largestBytes": int(largest_bytes),
            "medianBytes": _median_dataset_bytes(int(datasets_total)),
        },
        "execCacheEntries": int(exec_cache),
    }


def _median_dataset_bytes(total: int):
    """One indexed row at the midpoint, rather than pulling every size back."""
    from utk_curio.backend.app.datasets.models import DatasetIndexEntry

    if not total:
        return 0
    row = (
        db.session.query(DatasetIndexEntry.size_bytes)
        .filter(DatasetIndexEntry.size_bytes.isnot(None))
        .order_by(DatasetIndexEntry.size_bytes)
        .offset(total // 2)
        .limit(1)
        .first()
    )
    return int(row[0]) if row and row[0] is not None else 0
