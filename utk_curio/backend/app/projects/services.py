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


def _auto_install_computed_outputs(
    user_key: str,
    output_refs: List[OutputRef],
    spec: Optional[dict],
) -> Optional[dict]:
    """Install each newly computed output as ``computed.x{hash}@1/`` and add lean
    refs to *spec* so the catalog can resolve them without live_outputs.

    Returns the (possibly updated) spec dict, or the original spec unchanged if
    nothing new was installed.  Errors for individual files are swallowed so a
    single bad output never blocks the whole save.
    """
    if not output_refs or not spec:
        return spec

    from utk_curio.backend.app.datasets.installer import (
        install_computed_file_for_node,
    )
    from utk_curio.backend.app.datasets.output_paths import resolve_shared_output_path
    from utk_curio.backend.app.datasets.service import _computed_output_format
    from utk_curio.backend.app.datasets.storage import DATASET_DIR_RE

    dataflow = spec.get("dataflow") if isinstance(spec, dict) else None
    if not isinstance(dataflow, dict):
        return spec

    datasets_refs: list[dict] = list(dataflow.get("datasets") or [])

    changed = False
    from utk_curio.backend.app.datasets.service import _is_catalogable_output

    for ref in output_refs:
        filename = ref.filename
        node_id = ref.node_id
        data_type = getattr(ref, "data_type", None)
        if not _is_catalogable_output(data_type):
            continue

        src = resolve_shared_output_path(filename, data_type=data_type)
        if src is None:
            continue

        try:
            file_bytes = src.read_bytes()
        except OSError:
            continue

        fmt = _computed_output_format(src.name, data_type)
        store_name = src.name if src.suffix else filename

        try:
            result = install_computed_file_for_node(
                user_key, file_bytes, store_name, fmt, node_id=node_id
            )
        except Exception:  # noqa: BLE001 – best-effort; don't block save
            continue

        dataset_id = result.manifest.id   # "computed.<sanitized_node_id>"
        dir_name = result.manifest.dir_name  # "computed.<sanitized_node_id>@1"

        # Validate the generated dir_name before writing it to the spec – if
        # somehow it's invalid we'd rather skip than persist a broken ref.
        if not DATASET_DIR_RE.match(dir_name):
            continue

        # Replace any existing ref for this producer node or add a new one.
        updated = False
        for existing_ref in datasets_refs:
            if existing_ref.get("producerNodeId") == node_id:
                existing_ref.update({
                    "datasetId": dataset_id,
                    "dirName": dir_name,
                    "origin": "computed",
                })
                updated = True
                changed = True
                break
        if not updated:
            datasets_refs.append({
                "datasetId": dataset_id,
                "dirName": dir_name,
                "origin": "computed",
                "producerNodeId": node_id,
                "consumerNodeIds": [],
            })
            changed = True

    if not changed:
        return spec

    new_spec = dict(spec)
    new_spec["dataflow"] = {**dataflow, "datasets": datasets_refs}
    return new_spec


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


def _output_ref_dict(ref: OutputRef) -> dict:
    entry = {"node_id": ref.node_id, "filename": ref.filename}
    if ref.data_type:
        entry["data_type"] = ref.data_type
    return entry


def _output_refs_from_manifest(manifest: Optional[dict]) -> List[OutputRef]:
    if not manifest:
        return []
    return [
        OutputRef(
            node_id=o["node_id"],
            filename=o["filename"],
            data_type=o.get("data_type"),
        )
        for o in manifest.get("outputs", [])
    ]


# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------

def save_project(user, data: ProjectCreate) -> ProjectDetail:
    from utk_curio.backend.app.packages.services import (
        ensure_user_packages_initialized,
        seed_spec_with_defaults,
    )

    _assert_guest_can_save(user)

    project_id = str(uuid4())
    ukey = _user_dir_key(user)
    # First-time real users have no per-user package store yet; seed builtin
    # so the new dataflow's palette isn't empty.
    ensure_user_packages_initialized(ukey)
    folder = str(storage.project_dir(ukey, project_id))

    project = repo.upsert_project(
        user_id=user.id,
        name=data.name,
        folder_path=folder,
        description=data.description,
        thumbnail_accent=data.thumbnail_accent,
    )
    project_id = project.id

    # New project: merge per-user defaults into the spec's lockfile so the
    # package palette starts populated. Caller can override by passing a
    # spec that already declares packages.
    data.spec = seed_spec_with_defaults(ukey, data.spec)

    storage.write_spec(ukey, project_id, data.spec)
    output_refs = list(data.outputs)
    effective_spec = _auto_install_computed_outputs(ukey, output_refs, data.spec) or data.spec
    if effective_spec is not data.spec:
        storage.write_spec(ukey, project_id, effective_spec)
    storage.write_manifest(ukey, project_id, project.spec_revision, output_refs,
        name=data.name,
        description=data.description,
        thumbnail_accent=data.thumbnail_accent or "peach",
    )

    db.session.commit()
    return _to_detail(project, spec=effective_spec, outputs=output_refs)


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
    if data.outputs is not None:
        output_refs = list(data.outputs)
        # Install into users/<user>/datasets/ and register lean refs in the spec.
        # Do not copy artifacts into project/data/ — that folder is legacy-only.
        updated_spec = _auto_install_computed_outputs(ukey, output_refs, effective_spec)
        if updated_spec is not None and updated_spec is not effective_spec:
            effective_spec = updated_spec
            storage.write_spec(ukey, project_id, effective_spec)
    else:
        output_refs = _output_refs_from_manifest(existing_manifest)
    if data.spec is not None and effective_spec is not data.spec:
        # spec was already written above by auto_install; nothing to do.
        pass
    elif data.spec is not None:
        storage.write_spec(ukey, project_id, data.spec)

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
    from utk_curio.backend.app.packages.services import (
        ensure_user_packages_initialized,
    )

    project = repo.get_for_user(project_id, user.id)
    repo.touch_last_opened(project_id, user.id)

    ukey = _user_dir_key(user)
    # Defense in depth: a user who has projects from before the builtin-seed
    # fix still needs builtin in their store to render the palette.
    ensure_user_packages_initialized(ukey)
    spec = storage.read_spec(ukey, project_id)
    manifest = storage.read_manifest(ukey, project_id)

    output_refs: List[OutputRef] = []
    if manifest and "outputs" in manifest:
        output_refs = [
            OutputRef(
                node_id=o["node_id"],
                filename=o["filename"],
                data_type=o.get("data_type"),
            )
            for o in manifest["outputs"]
        ]

    hydrated = storage.hydrate_outputs(ukey, project_id, output_refs, spec=spec)

    db.session.commit()
    return {
        "project": _to_detail(project, spec=spec, outputs=hydrated),
        "spec": spec,
        "outputs": [_output_ref_dict(r) for r in hydrated],
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
            OutputRef(
                node_id=o["node_id"],
                filename=o["filename"],
                data_type=o.get("data_type"),
            )
            for o in manifest["outputs"]
        ]

    hydrated = storage.hydrate_outputs(ukey, project_id, output_refs, spec=spec)

    detail = _to_detail(project, spec=spec, outputs=hydrated)
    # Don't leak server filesystem layout to shared-link visitors.
    detail.folder_path = ""

    return {
        "project": detail,
        "spec": spec,
        "outputs": [_output_ref_dict(r) for r in hydrated],
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
            OutputRef(
                node_id=o["node_id"],
                filename=o["filename"],
                data_type=o.get("data_type"),
            )
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
