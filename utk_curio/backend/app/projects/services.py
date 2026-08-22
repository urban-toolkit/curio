"""Business logic for project save / load / list / delete."""
from __future__ import annotations

import logging
import re
import shutil
from typing import Dict, List, Optional
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


# Visualization "sink" node types: they consume a dataframe to render and pass
# their INPUT straight through as their output, so they never produce a new
# dataset. A computed dataset ref keyed on such a node is always a duplicate of
# the upstream producer's output (same file, different node id) — pruned on save.
_SINK_NODE_TYPES = frozenset({
    "curio.builtin/vis-vega",
    "curio.builtin/vis-simple",
})


def _is_sink_node_type(node_type) -> bool:
    """Membership in ``_SINK_NODE_TYPES``, tolerant of the versioned canonical
    form palette-dragged nodes carry (``curio.builtin/vis-vega@1``) (#169)."""
    from utk_curio.backend.app.packages.spec_packages import unversioned_node_type

    return unversioned_node_type(node_type) in _SINK_NODE_TYPES


def _prune_sink_node_dataset_refs(spec: Optional[dict]) -> Optional[dict]:
    """Drop ``dataflow.datasets`` refs whose producer is a visualization/sink node.

    Returns *spec* unchanged when there's nothing to prune; otherwise a new spec
    dict with the offending refs removed. Only the REF is removed — the
    account-store folder is kept (#174): account-level datasets are shared
    across dataflows and this runs on every save/ref write, so deleting here
    destroyed shared assets (``duplicate_project`` copies refs verbatim, so an
    inherited sink ref pointed at the ORIGINAL project's dir). Folder removal is
    exclusively ``delete_dataset``'s job; ``_auto_install_computed_outputs``
    prevents new sink dirs from being created in the first place.
    """
    if not isinstance(spec, dict):
        return spec
    dataflow = spec.get("dataflow")
    if not isinstance(dataflow, dict):
        return spec
    refs = dataflow.get("datasets")
    if not isinstance(refs, list) or not refs:
        return spec

    node_types: Dict[str, Optional[str]] = {}
    for node in dataflow.get("nodes") or []:
        if isinstance(node, dict) and node.get("id"):
            node_types[node["id"]] = node.get("type")

    kept: List[dict] = []
    pruned: List[dict] = []
    for ref in refs:
        producer = ref.get("producerNodeId") if isinstance(ref, dict) else None
        if producer and _is_sink_node_type(node_types.get(producer)):
            pruned.append(ref)
        else:
            kept.append(ref)

    if not pruned:
        return spec

    new_spec = dict(spec)
    new_spec["dataflow"] = {**dataflow, "datasets": kept}
    return new_spec


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


def _humanize_node_type(node_type: Optional[str]) -> Optional[str]:
    """Friendly fallback title from a node type slug, e.g.
    ``curio.builtin/autk-grammar`` → ``Autk Grammar``. Returns ``None`` when no
    type is available."""
    if not node_type:
        return None
    base = str(node_type).rsplit("/", 1)[-1]
    cleaned = re.sub(r"[-_]+", " ", base).strip()
    return cleaned.title() if cleaned else None


def _computed_output_title(
    ref: OutputRef, dataflow: Optional[dict]
) -> Optional[str]:
    """Resolve the friendly title for a save-time computed output, never the raw
    generated filename:

      1. the producing node's client-resolved display label (``ref.node_name``);
      2. the node's custom label in the spec (``data.packageTemplateLabel``);
      3. a friendly name derived from the node type;
      4. ``None`` — the installer then derives a filename-based title, which the
         frontend renders as ``dirName`` via ``datasetDisplayTitle``.
    """
    explicit = (getattr(ref, "node_name", None) or "").strip()
    if explicit:
        return explicit

    nodes = dataflow.get("nodes") if isinstance(dataflow, dict) else None
    for node in nodes or []:
        if not isinstance(node, dict) or node.get("id") != ref.node_id:
            continue
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        label = (data.get("packageTemplateLabel") or "").strip()
        if label:
            return label
        return _humanize_node_type(node.get("type") or data.get("nodeType"))
    return None


def _computed_node_type(ref: OutputRef, dataflow: Optional[dict]) -> Optional[str]:
    """The producing node's type slug for lineage: the client-attached
    ``ref.node_type`` if present, else resolved from the spec node."""
    explicit = (getattr(ref, "node_type", None) or "").strip()
    if explicit:
        return explicit
    nodes = dataflow.get("nodes") if isinstance(dataflow, dict) else None
    for node in nodes or []:
        if isinstance(node, dict) and node.get("id") == ref.node_id:
            data = node.get("data") if isinstance(node.get("data"), dict) else {}
            return node.get("type") or data.get("nodeType")
    return None


def _auto_install_computed_outputs(
    user_key: str,
    output_refs: List[OutputRef],
    spec: Optional[dict],
    failures: Optional[list] = None,
    *,
    dataflow_id: Optional[str] = None,
    dataflow_name: Optional[str] = None,
) -> Optional[dict]:
    """Save each newly computed output to the account-level user store as
    ``computed.<dataflowId>.<nodeId>@1/`` with its producer/upstream lineage.

    Computed outputs are account-level assets by default: this NO LONGER
    installs them into the project (no ``dataflow.datasets`` ref is written).
    Attaching one to a project is now an explicit user action (Data Catalog
    ``Install``). The spec is therefore returned unchanged — the return type is
    kept (``Optional[dict]``) for call-site compatibility.

    Errors for individual files are swallowed (and logged) so a single bad
    output never blocks the whole save. When *failures* is provided, each output
    that could NOT be saved appends ``{"node_id", "filename", "reason"}`` so the
    caller can surface the silently-skipped dataset to the client.
    """
    if not output_refs or not spec:
        return spec

    def _record_failure(node_id, filename, reason):
        if failures is not None:
            failures.append({"node_id": node_id, "filename": filename, "reason": reason})

    # Defensive: both call sites pass the project id, but persisting without it
    # would mint legacy un-namespaced ``computed.<node>`` dirs (#166).
    if not dataflow_id:
        for ref in output_refs:
            _record_failure(
                ref.node_id, ref.filename,
                "computed persistence requires a dataflow id",
            )
        return spec

    from utk_curio.backend.app.datasets.install.bundle import install_node_output
    from utk_curio.backend.app.datasets.application.export import resolve_upstream_inputs

    dataflow = spec.get("dataflow") if isinstance(spec, dict) else None
    if not isinstance(dataflow, dict):
        return spec

    node_types: Dict[str, Optional[str]] = {
        node["id"]: node.get("type")
        for node in dataflow.get("nodes") or []
        if isinstance(node, dict) and node.get("id")
    }

    for ref in output_refs:
        filename = ref.filename
        node_id = ref.node_id
        data_type = getattr(ref, "data_type", None)

        # Sink/visualization nodes pass their input through — persisting their
        # output would create a duplicate of the upstream producer's dataset
        # that the ref prune then has to clean up. Never create it (#174).
        if _is_sink_node_type(node_types.get(node_id)):
            continue

        try:
            result = install_node_output(
                user_key,
                node_id=node_id,
                path_ref=filename,
                data_type=data_type,
                node_name=_computed_output_title(ref, dataflow),
                dataflow_id=dataflow_id,
                node_type=_computed_node_type(ref, dataflow),
                dataflow_name=dataflow_name,
                upstream_inputs=resolve_upstream_inputs(spec, node_id),
            )
        except Exception as exc:  # noqa: BLE001 – best-effort; don't block save
            # Swallowed so one bad output never blocks the whole save, but log it
            # AND record it so a silently-dropped dataset is surfaced to the user
            # instead of invisible.
            logger.exception(
                "Save of computed output failed for node %s (file %r); "
                "this dataset will not be persisted",
                node_id,
                filename,
            )
            _record_failure(node_id, filename, str(exc) or "install failed")
            continue
        if result is None:
            # The producing node ran, but its output artifact wasn't found in
            # shared storage at save time (or the bundle was empty) — the most
            # common "Play All didn't generate all datasets" cause. Surface it.
            _record_failure(node_id, filename, "output artifact not found at save time")
            continue

        # Saved to the account store only. Intentionally NO project-ref write:
        # the dataset lives in the user's Data Catalog and is installed into a
        # project only by an explicit user action.

    return spec


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


def _to_detail(p, spec=None, outputs=None, dataset_install_warnings=None) -> ProjectDetail:
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
        dataset_install_warnings=dataset_install_warnings or [],
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


def _persisted_output_refs(
    user_key: str,
    project_id: str,
    output_refs: List[OutputRef],
    spec: Optional[dict],
) -> List[OutputRef]:
    """Filter *output_refs* to those a reload can durably restore, logging drops.

    Thin wrapper over :func:`storage.persisted_output_refs` that logs every
    dropped ref. A drop means an output the client sent was not durably
    persisted (auto-install failed/returned None, or its dataset was pruned as a
    sink-node duplicate). We omit it from the manifest so the manifest never
    claims an output that would silently vanish on reload, and log it loudly so
    the dropped dataset is diagnosable instead of invisible (issue #144).
    """
    persisted = storage.persisted_output_refs(user_key, project_id, output_refs, spec=spec)
    if len(persisted) != len(output_refs):
        kept = {(r.node_id, r.filename) for r in persisted}
        for ref in output_refs:
            if (ref.node_id, ref.filename) not in kept:
                logger.warning(
                    "Output %r from node %s was not durably persisted (no "
                    "installed dataset or legacy copy); omitting it from the "
                    "project manifest so it isn't recorded as a phantom that "
                    "vanishes on reload.",
                    ref.filename,
                    ref.node_id,
                )
    return persisted


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
    install_warnings: list = []
    effective_spec = _auto_install_computed_outputs(
        ukey, output_refs, data.spec, install_warnings,
        dataflow_id=project_id, dataflow_name=data.name,
    ) or data.spec
    # Drop dataset refs keyed on visualization/sink nodes (passthrough duplicates).
    effective_spec = _prune_sink_node_dataset_refs(effective_spec)
    if effective_spec is not data.spec:
        storage.write_spec(ukey, project_id, effective_spec)
    # Record only outputs the reload path can restore from a durable source
    # (installed dataset / legacy copy). Writing the raw client list would let a
    # swallowed install error leave a phantom that vanishes on reload (#144).
    persisted_refs = _persisted_output_refs(ukey, project_id, output_refs, effective_spec)
    storage.write_manifest(ukey, project_id, project.spec_revision, persisted_refs,
        name=data.name,
        description=data.description,
        thumbnail_accent=data.thumbnail_accent or "peach",
    )

    db.session.commit()
    return _to_detail(project, spec=effective_spec, outputs=persisted_refs,
                      dataset_install_warnings=install_warnings)


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

    # Serialize the spec read-modify-write so a concurrent dataset auto-install
    # (merge_dataflow_dataset_ref) or Play-All can't clobber freshly-installed
    # refs. Re-read existing_spec INSIDE the lock so we merge/preserve against
    # the latest on-disk spec, not the snapshot read before the lock.
    install_warnings: list = []
    with storage.spec_write_lock(ukey, project_id):
        existing_spec = storage.read_spec(ukey, project_id)
        effective_spec = data.spec if data.spec is not None else existing_spec
        spec_dirty = False
        if data.outputs is not None:
            output_refs = list(data.outputs)
            # Install into users/<user>/datasets/ and register lean refs in the spec.
            # Do not copy artifacts into project/data/ — that folder is legacy-only.
            updated_spec = _auto_install_computed_outputs(
                ukey, output_refs, effective_spec, install_warnings,
                dataflow_id=project_id, dataflow_name=(data.name or project.name),
            )
            if updated_spec is not None and updated_spec is not effective_spec:
                effective_spec = updated_spec
                spec_dirty = True
        else:
            output_refs = _output_refs_from_manifest(existing_manifest)

        # NOTE: computed dataset refs are created ONLY by an explicit install
        # (the client tracks them in its own dataflow-datasets state and sends
        # them back on save), so there is no longer a "ref the client never
        # learned about" to carry forward. The old ``_preserve_persisted_computed_refs``
        # step re-added refs whenever the account-store dir existed, which — now
        # that uninstall keeps that dir — would resurrect an explicitly
        # uninstalled ref. It is intentionally gone.

        # Prune dataset refs keyed on visualization/sink nodes — their output is a
        # passthrough of their input, so the ref just duplicates the upstream
        # producer's dataset. Runs AFTER preserve so carried-forward stale refs
        # are cleaned too; may dirty the spec even on an outputs-only update.
        pruned_spec = _prune_sink_node_dataset_refs(effective_spec)
        if pruned_spec is not effective_spec:
            effective_spec = pruned_spec
            spec_dirty = True

        if data.spec is not None or spec_dirty:
            storage.write_spec(ukey, project_id, effective_spec)

    # Record only outputs the reload path can restore from a durable source so a
    # swallowed install error can't leave a phantom manifest entry (#144).
    persisted_refs = _persisted_output_refs(ukey, project_id, output_refs, effective_spec)
    storage.write_manifest(ukey, project_id, project.spec_revision, persisted_refs,
        name=project.name,
        description=project.description,
        thumbnail_accent=project.thumbnail_accent or "peach",
    )

    db.session.commit()
    return _to_detail(project, spec=effective_spec, outputs=persisted_refs,
                      dataset_install_warnings=install_warnings)


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
