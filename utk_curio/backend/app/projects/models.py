from datetime import datetime, timezone
from uuid import uuid4

from utk_curio.backend.extensions import db


def _uuid() -> str:
    return str(uuid4())


def _now():
    return datetime.now(timezone.utc)


class Project(db.Model):
    id = db.Column(db.String(36), primary_key=True, default=_uuid)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    slug = db.Column(db.String(240), nullable=False)
    description = db.Column(db.Text, nullable=True)
    folder_path = db.Column(db.String(512), nullable=False)
    thumbnail_accent = db.Column(db.String(16), default="peach")
    spec_revision = db.Column(db.Integer, default=1, nullable=False)
    last_opened_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=_now, onupdate=_now, nullable=False)

    owner = db.relationship("User", backref=db.backref("projects", lazy="dynamic"))

    # Mirrors migration f6a7b8c9d0e1. Leading column is user_id, so single-
    # column lookups by user_id use this index too — no separate ix_project_user_id needed.
    __table_args__ = (
        db.Index(
            "ix_project_user_opened",
            "user_id",
            db.text("last_opened_at DESC"),
        ),
    )

    def __repr__(self):
        return f"<Project {self.id!r} {self.name!r}>"


class ProjectEditor(db.Model):
    """An account the owner invited to edit a dataflow (``projects/access.py``).

    Everyone else who opens the dataflow's link watches it. Deleting the
    project deletes its editors: the backref cascades through the ORM, as a
    project's runs do, because SQLite does not enforce foreign keys here.
    """

    __tablename__ = "project_editor"

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.String(36), db.ForeignKey("project.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    added_by = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    added_at = db.Column(db.DateTime, default=_now, nullable=False)

    project = db.relationship(
        "Project",
        backref=db.backref("editors", cascade="all, delete-orphan"),
    )
    user = db.relationship("User", foreign_keys=[user_id])

    # Mirrors migration f4a5b6c7d8e9. The unique pair's own index serves
    # lookups by project; this one serves a user's.
    __table_args__ = (
        db.UniqueConstraint("project_id", "user_id", name="uq_project_editor_project_user"),
        db.Index("ix_project_editor_user", "user_id"),
    )

    def __repr__(self):
        return f"<ProjectEditor {self.project_id!r} {self.user_id!r}>"


class ExecCacheEntry(db.Model):
    __tablename__ = "exec_cache_entry"

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(
        db.String(36), db.ForeignKey("project.id"), nullable=False
    )
    activity_name = db.Column(db.Text, nullable=False)
    content_key = db.Column(db.String(64), nullable=False)
    output_filename = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=_now, nullable=False)

    __table_args__ = (
        db.Index("ix_exec_cache_project_key", "project_id", "content_key"),
    )
