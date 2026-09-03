"""Database access layer for projects."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from utk_curio.backend.extensions import db
from utk_curio.backend.app.projects.models import Project
from utk_curio.backend.app.projects.schemas import _slugify


class NotFoundError(Exception):
    pass


def get_for_user(project_id: str, user_id: int) -> Project:
    project = db.session.get(Project, project_id)
    if project is None or project.user_id != user_id:
        raise NotFoundError(f"Project {project_id} not found")
    return project


def list_for_user(
    user_id: int,
    scope: str = "mine",
    sort: str = "last_opened",
) -> List[Project]:
    # ``scope`` selects nothing any more. Archive was removed (#261), and the
    # archived filter was the only thing the scopes ever differed by — "recent"
    # and "mine" already returned identical sets. Kept in the signature because
    # the route and the projects page still pass it; collapsing the "Recent"
    # tab is a UX decision, not part of removing Archive.
    q = Project.query.filter_by(user_id=user_id)

    if sort == "name":
        q = q.order_by(Project.name.asc())
    elif sort == "created":
        q = q.order_by(Project.created_at.desc())
    else:
        q = q.order_by(Project.last_opened_at.desc().nullslast(), Project.created_at.desc())

    return q.all()


def _unique_slug(user_id: int, base_slug: str, exclude_id: Optional[str] = None) -> str:
    slug = base_slug
    counter = 2
    while True:
        q = Project.query.filter_by(user_id=user_id, slug=slug)
        if exclude_id:
            q = q.filter(Project.id != exclude_id)
        if q.first() is None:
            return slug
        slug = f"{base_slug}-{counter}"
        counter += 1


def upsert_project(
    user_id: int,
    name: str,
    folder_path: str,
    description: Optional[str] = None,
    thumbnail_accent: str = "peach",
    project_id: Optional[str] = None,
) -> Project:
    """Insert a new project or update an existing one (bumps spec_revision)."""
    if project_id:
        project = get_for_user(project_id, user_id)
        if name:
            project.name = name
            project.slug = _unique_slug(user_id, _slugify(name), exclude_id=project_id)
        if description is not None:
            project.description = description
        if thumbnail_accent:
            project.thumbnail_accent = thumbnail_accent
        project.folder_path = folder_path
        project.spec_revision = (project.spec_revision or 0) + 1
        project.updated_at = datetime.now(timezone.utc)
    else:
        slug = _unique_slug(user_id, _slugify(name))
        project = Project(
            user_id=user_id,
            name=name,
            slug=slug,
            description=description,
            folder_path=folder_path,
            thumbnail_accent=thumbnail_accent,
        )
        db.session.add(project)

    db.session.flush()
    return project


def purge_project(project_id: str, user_id: int) -> Project:
    project = get_for_user(project_id, user_id)
    db.session.delete(project)
    db.session.flush()
    return project


def touch_last_opened(project_id: str, user_id: int) -> Project:
    project = get_for_user(project_id, user_id)
    project.last_opened_at = datetime.now(timezone.utc)
    db.session.flush()
    return project
