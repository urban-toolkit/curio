"""Business logic for project save / load / list / delete."""
from __future__ import annotations

import logging
import shutil
from typing import List, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)

from utk_curio.backend.extensions import db
from utk_curio.backend.app.projects import repositories as repo
from utk_curio.backend.app.projects import storage
from utk_curio.backend.app.projects.schemas import (
    OutputRef,
    ProjectCreate,
    ProjectDetail,
    ProjectSummary,
    ProjectUpdate,
    _slugify,
)
from utk_curio.backend.config import (
    CURIO_SHARED_GUEST_USERNAME,
)


class ProjectError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _is_shared_guest(user) -> bool:
    return bool(user and user.is_guest and user.username == CURIO_SHARED_GUEST_USERNAME)


def _user_dir_key(user) -> str:
    return storage._GUEST_KEY if _is_shared_guest(user) else str(user.id)


def _owner_user_dir_key(project) -> str:
    """Resolve the on-disk user key for a project's owner."""
    from utk_curio.backend.app.users.models import User as UserModel

    owner = db.session.get(UserModel, project.user_id)
    if owner and owner.is_guest and owner.username == CURIO_SHARED_GUEST_USERNAME:
        return storage._GUEST_KEY
    return str(project.user_id)


def _assert_guest_can_save(user) -> None:
    if user.is_guest and not _is_shared_guest(user):
        raise ProjectError("Guest users cannot save projects", 403)


def _extract_graph_preview(spec: Optional[dict]) -> Optional[dict]:
    if not spec:
        return None
    dataflow = spec.get("dataflow") if isinstance(spec, dict) else None
    if not dataflow:
        return None
    raw_nodes = dataflow.get("nodes") or []
    raw_edges = dataflow.get("edges") or []
    nodes = [
        {
            "id": n.get("id", ""),
            "type": n.get("type", ""),
            "x": n.get("x", 0),
            "y": n.get("y", 0),
            "w": n.get("width"),
            "h": n.get("height"),
        }
        for n in raw_nodes
        if isinstance(n, dict)
    ]
    edges = [
        {"source": e.get("source", ""), "target": e.get("target", "")}
        for e in raw_edges
        if isinstance(e, dict)
    ]
    return {"nodes": nodes, "edges": edges}


def _to_summary(p, graph_preview=None) -> ProjectSummary:
    return ProjectSummary(
        id=p.id,
        name=p.name,
        slug=p.slug,
        description=p.description,
        thumbnail_accent=p.thumbnail_accent or "peach",
        spec_revision=p.spec_revision,
        last_opened_at=p.last_opened_at.isoformat() if p.last_opened_at else None,
        created_at=p.created_at.isoformat() if p.created_at else "",
        updated_at=p.updated_at.isoformat() if p.updated_at else "",
        archived_at=p.archived_at.isoformat() if p.archived_at else None,
        graph_preview=graph_preview,
    )


def _to_detail(p, spec=None, outputs=None) -> ProjectDetail:
    return ProjectDetail(
        id=p.id,
        name=p.name,
        slug=p.slug,
        description=p.description,
        thumbnail_accent=p.thumbnail_accent or "peach",
        spec_revision=p.spec_revision,
        last_opened_at=p.last_opened_at.isoformat() if p.last_opened_at else None,
        created_at=p.created_at.isoformat() if p.created_at else "",
        updated_at=p.updated_at.isoformat() if p.updated_at else "",
        archived_at=p.archived_at.isoformat() if p.archived_at else None,
        folder_path=p.folder_path,
        spec=spec,
        outputs=outputs or [],
    )


def _output_refs_from_manifest(manifest: Optional[dict]) -> List[OutputRef]:
    if not manifest:
        return []
    return [
        OutputRef(node_id=o["node_id"], filename=o["filename"])
        for o in manifest.get("outputs", [])
    ]


# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------

def save_project(user, data: ProjectCreate) -> ProjectDetail:
    _assert_guest_can_save(user)

    project_id = str(uuid4())
    ukey = _user_dir_key(user)
    folder = str(storage.project_dir(ukey, project_id))

    project = repo.upsert_project(
        user_id=user.id,
        name=data.name,
        folder_path=folder,
        description=data.description,
        thumbnail_accent=data.thumbnail_accent,
    )
    project_id = project.id

    storage.write_spec(ukey, project_id, data.spec)
    copied = storage.copy_outputs(ukey, project_id, data.outputs)
    storage.write_manifest(ukey, project_id, project.spec_revision, copied,
        name=data.name,
        description=data.description,
        thumbnail_accent=data.thumbnail_accent or "peach",
    )

    db.session.commit()
    return _to_detail(project, spec=data.spec, outputs=copied)


def update_project(user, project_id: str, data: ProjectUpdate) -> ProjectDetail:
    _assert_guest_can_save(user)
    project = repo.get_for_user(project_id, user.id)
    ukey = _user_dir_key(user)
    existing_spec = storage.read_spec(ukey, project_id)
    existing_manifest = storage.read_manifest(ukey, project_id)

    folder = str(storage.project_dir(ukey, project_id))
    project = repo.upsert_project(
        user_id=user.id,
        name=data.name or project.name,
        folder_path=folder,
        description=data.description if data.description is not None else project.description,
        thumbnail_accent=data.thumbnail_accent or project.thumbnail_accent,
        project_id=project_id,
    )

    effective_spec = data.spec if data.spec is not None else existing_spec
    if data.spec is not None:
        storage.write_spec(ukey, project_id, data.spec)

    if data.outputs is not None:
        output_refs = storage.copy_outputs(ukey, project_id, data.outputs)
    else:
        output_refs = _output_refs_from_manifest(existing_manifest)

    storage.write_manifest(ukey, project_id, project.spec_revision, output_refs,
        name=project.name,
        description=project.description,
        thumbnail_accent=project.thumbnail_accent or "peach",
    )

    db.session.commit()
    return _to_detail(project, spec=effective_spec, outputs=output_refs)


# ---------------------------------------------------------------------------
# Load (hydration)
# ---------------------------------------------------------------------------

def load_project(user, project_id: str) -> dict:
    project = repo.get_for_user(project_id, user.id)
    repo.touch_last_opened(project_id, user.id)

    ukey = _user_dir_key(user)
    spec = storage.read_spec(ukey, project_id)
    manifest = storage.read_manifest(ukey, project_id)

    output_refs: List[OutputRef] = []
    if manifest and "outputs" in manifest:
        output_refs = [
            OutputRef(node_id=o["node_id"], filename=o["filename"])
            for o in manifest["outputs"]
        ]

    hydrated = storage.hydrate_outputs(ukey, project_id, output_refs)

    db.session.commit()
    return {
        "project": _to_detail(project, spec=spec, outputs=hydrated),
        "spec": spec,
        "outputs": [{"node_id": r.node_id, "filename": r.filename} for r in hydrated],
    }


# ---------------------------------------------------------------------------
# Shared (public-by-URL) load — no ownership check
# ---------------------------------------------------------------------------

def load_shared_project(project_id: str) -> dict:
    """Hydrate a project for any caller, regardless of ownership.

    Used by the unauthenticated ``GET /api/projects/<id>/shared`` route to
    power link-based sharing. Archived projects are treated as missing so a
    deleted/archived link 404s instead of leaking a stale spec.
    """
    from utk_curio.backend.app.projects.models import Project

    project = db.session.get(Project, project_id)
    if project is None or project.archived_at is not None:
        raise repo.NotFoundError(f"Project {project_id} not found")

    ukey = _owner_user_dir_key(project)
    spec = storage.read_spec(ukey, project_id)
    if spec is None:
        raise repo.NotFoundError(f"Project {project_id} not found")

    manifest = storage.read_manifest(ukey, project_id)
    output_refs: List[OutputRef] = []
    if manifest and "outputs" in manifest:
        output_refs = [
            OutputRef(node_id=o["node_id"], filename=o["filename"])
            for o in manifest["outputs"]
        ]

    hydrated = storage.hydrate_outputs(ukey, project_id, output_refs)

    detail = _to_detail(project, spec=spec, outputs=hydrated)
    # Don't leak server filesystem layout to shared-link visitors.
    detail.folder_path = ""

    return {
        "project": detail,
        "spec": spec,
        "outputs": [{"node_id": r.node_id, "filename": r.filename} for r in hydrated],
    }


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------

def list_projects(
    user, scope: str = "mine", sort: str = "last_opened"
) -> List[ProjectSummary]:
    projects = repo.list_for_user(user.id, scope=scope, sort=sort)
    ukey = _user_dir_key(user)
    summaries = []
    purged = False
    for p in projects:
        spec = storage.read_spec(ukey, p.id)
        if spec is None:
            # Spec file is gone — remove the stale DB row so the list stays
            # in sync with the filesystem (files are the source of truth).
            repo.purge_project(p.id, user.id)
            purged = True
            continue
        summaries.append(_to_summary(p, graph_preview=_extract_graph_preview(spec)))
    if purged:
        db.session.commit()
    return summaries


# ---------------------------------------------------------------------------
# Rename
# ---------------------------------------------------------------------------

def rename_project(user, project_id: str, new_name: str) -> ProjectSummary:
    project = repo.get_for_user(project_id, user.id)
    project.name = new_name
    project.slug = repo._unique_slug(user.id, _slugify(new_name), exclude_id=project_id)
    db.session.commit()
    return _to_summary(project)


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

def delete_project(user, project_id: str, purge: bool = False) -> None:
    if purge:
        project = repo.get_for_user(project_id, user.id)
        storage.delete_tree(_user_dir_key(user), project_id)
        repo.purge_project(project_id, user.id)
    else:
        repo.soft_delete(project_id, user.id)
    db.session.commit()


# ---------------------------------------------------------------------------
# Guest reconciliation
# ---------------------------------------------------------------------------

def reconcile_guest_projects(user) -> int:
    """Re-import guest projects from the filesystem that are missing from the DB.

    Called at server startup so a DB wipe doesn't orphan existing project files.
    Also migrates projects from orphaned numeric user directories (created before
    the guest-key change) into the guest directory.
    Returns the number of projects re-imported.
    """
    from utk_curio.backend.app.projects.models import Project
    from utk_curio.backend.app.users.models import User as UserModel

    ukey = _user_dir_key(user)
    users_base = storage._users_base()

    # Migrate projects from orphaned numeric user dirs into the guest dir.
    # A numeric dir is "orphaned" when no User row with that id exists anymore
    # (e.g. after a DB wipe). We move the project subdirectories so the main
    # reconcile pass below can find and import them.
    guest_projects_dir = users_base / ukey / "projects"
    if users_base.exists():
        for user_dir in users_base.iterdir():
            if not user_dir.is_dir() or not user_dir.name.isdigit():
                continue
            if db.session.get(UserModel, int(user_dir.name)) is not None:
                continue  # user still exists — leave their files alone
            old_projects = user_dir / "projects"
            if not old_projects.exists():
                continue
            guest_projects_dir.mkdir(parents=True, exist_ok=True)
            for proj_entry in old_projects.iterdir():
                dest = guest_projects_dir / proj_entry.name
                if not dest.exists():
                    try:
                        shutil.move(str(proj_entry), str(dest))
                    except Exception:
                        logger.exception(
                            "Failed to migrate project %s from %s",
                            proj_entry.name, user_dir.name,
                        )

    projects_dir = users_base / ukey / "projects"
    if not projects_dir.exists():
        return 0

    imported = 0
    for entry in projects_dir.iterdir():
        if not entry.is_dir():
            continue
        project_id = entry.name
        try:
            with db.session.begin_nested():  # savepoint: one failure won't abort the rest
                if db.session.get(Project, project_id):
                    continue
                manifest = storage.read_manifest(ukey, project_id)
                if not manifest:
                    continue
                if storage.read_spec(ukey, project_id) is None:
                    continue

                name = manifest.get("name") or "Recovered Project"
                description = manifest.get("description")
                thumbnail_accent = manifest.get("thumbnail_accent") or "peach"
                spec_revision = manifest.get("spec_revision", 1)
                slug = repo._unique_slug(user.id, _slugify(name))
                project = Project(
                    id=project_id,
                    user_id=user.id,
                    name=name,
                    slug=slug,
                    description=description,
                    folder_path=str(entry),
                    thumbnail_accent=thumbnail_accent,
                    spec_revision=spec_revision,
                )
                db.session.add(project)
                imported += 1
        except Exception:
            logger.exception("Failed to reconcile project %s", project_id)

    if imported:
        db.session.commit()
    return imported


# ---------------------------------------------------------------------------
# Duplicate
# ---------------------------------------------------------------------------

def duplicate_project(user, project_id: str) -> ProjectDetail:
    src = repo.get_for_user(project_id, user.id)
    ukey = _user_dir_key(user)
    spec = storage.read_spec(ukey, project_id)
    manifest = storage.read_manifest(ukey, project_id)

    output_refs: List[OutputRef] = []
    if manifest and "outputs" in manifest:
        output_refs = [
            OutputRef(node_id=o["node_id"], filename=o["filename"])
            for o in manifest["outputs"]
        ]

    new_name = f"{src.name} (copy)"
    create_data = ProjectCreate(
        name=new_name,
        spec=spec or {},
        outputs=output_refs,
        description=src.description,
        thumbnail_accent=src.thumbnail_accent or "peach",
    )
    return save_project(user, create_data)
