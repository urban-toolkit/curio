"""A published dashboard: a dataflow its owner lets others run.

The owner publishes a snapshot of the saved dataflow (``spec_json`` at
``spec_revision``) under a secret link token. Whoever holds the link, signed in
or not as ``access`` says, runs that snapshot on the server with their own
values for the widgets of its pinned tiles; their runs save nothing
(``published/service.py``). Publishing again replaces the snapshot and keeps
the token; unpublishing deletes the row, so the link stops working.

The token is kept here, never in the spec: a dataflow's spec is readable by
anyone holding its share link (``/api/projects/<id>/shared``).
"""
from __future__ import annotations

from datetime import datetime, timezone

from utk_curio.backend.extensions import db

ACCESS_LEVELS = ("link", "signed-in")


def _now():
    return datetime.now(timezone.utc)


class PublishedDashboard(db.Model):
    __tablename__ = "published_dashboard"

    project_id = db.Column(db.String(36), db.ForeignKey("project.id"), primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    token = db.Column(db.String(64), nullable=False, unique=True, index=True)
    access = db.Column(db.String(16), nullable=False, default="link")
    spec_json = db.Column(db.Text, nullable=False)
    spec_revision = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=_now)
    updated_at = db.Column(db.DateTime, nullable=False, default=_now, onupdate=_now)

    # Deleting a project deletes its publication, as it deletes its runs:
    # through the ORM, since SQLite does not enforce foreign keys here.
    project = db.relationship(
        "Project",
        backref=db.backref("published_dashboard", cascade="all, delete-orphan", uselist=False),
    )

