"""Agents catalog / lifecycle service layer.

Sits over the filesystem stores (``storage`` = definition artifacts, ``imports``
= account "My Imports", ``project_agents`` = per-project lockfile) and mirrors
``app/packages/services.py``: the route layer stays thin, this layer owns the
rules, and the project lockfile is read/written through ``projects.storage``.

Import and Install are separate explicit commands and never chain (DEC-029).
User-facing overview: ``docs/AGENTS.md``.
"""

from __future__ import annotations

import uuid

from utk_curio.backend.app.agents import (
    attachments,
    builtin,
    imports,
    project_agents,
    publications,
    storage,
)
from utk_curio.backend.app.agents.attachments import AttachmentError
from utk_curio.backend.app.agents.manifest import AgentManifest
from utk_curio.backend.app.projects import storage as projects_storage


class AgentServiceError(Exception):
    """Service-layer error carrying an HTTP status for the route layer."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _manifest_to_card(
    m: AgentManifest,
    *,
    scope: str,
    imported: bool,
    installed_in_project: bool,
    published: bool = False,
    publishable: bool = False,
) -> dict:
    """Serialize a definition to the camelCase card the drawer consumes."""
    return {
        "id": m.agent_id,
        "version": m.version,
        "dirName": m.dir_name,
        "name": m.name,
        "category": m.category,
        "purpose": m.purpose,
        "capabilities": m.capability_ids,
        "hooks": [t.kind for t in m.compatible_targets],
        "provenance": {"publisher": m.provenance.publisher, "trust": m.provenance.trust},
        "imported": imported,
        "installedInProject": installed_in_project,
        "published": published,
        "publishable": publishable,
        "scope": scope,
    }


def _resolve_definition(user_key: str, coord: str) -> AgentManifest | None:
    """Resolve a coordinate — user store, then the built-in roster, then published catalog."""
    m = storage.load_installed_agent_definition(user_key, coord)
    if m is None:
        m = builtin.get_builtin_manifest(coord)
    if m is None:
        m = publications.get_published_manifest(coord)
    return m


def _require_definition(user_key: str, coord: str) -> AgentManifest:
    m = _resolve_definition(user_key, coord)
    if m is None:
        raise AgentServiceError(f"no agent definition {coord!r} available", 404)
    return m


# ── read ────────────────────────────────────────────────────────────────────
def list_global_catalog(user_key: str, project_id: str | None = None) -> list[dict]:
    """The Global Catalog: the built-in agent definitions available to import/install."""
    imported = imports.load_imported_agents(user_key)
    installed: set[str] = set()
    if project_id:
        spec = projects_storage.read_spec(user_key, project_id)
        if spec is not None:
            installed = set(project_agents.project_agents(spec))
    # Global Catalog = built-in roster ∪ published definitions (published wins on dupes).
    by_dir: dict[str, tuple[AgentManifest, bool]] = {}
    for m in builtin.list_builtin_manifests():
        by_dir[m.dir_name] = (m, False)
    for m in publications.list_published():
        by_dir[m.dir_name] = (m, True)
    return [
        _manifest_to_card(
            m,
            scope="global",
            imported=dir_name in imported,
            installed_in_project=dir_name in installed,
            published=published,
        )
        for dir_name, (m, published) in sorted(by_dir.items())
    ]


def list_my_imports(user_key: str) -> list[dict]:
    """Account "My Imports": each imported coordinate whose definition resolves."""
    imported = imports.load_imported_agents(user_key)
    out: list[dict] = []
    for coord in sorted(imported):
        m = _resolve_definition(user_key, coord)
        if m is None:
            continue
        # Publishable only when it is an owned, store-backed definition (not a built-in).
        store_backed = storage.load_installed_agent_definition(user_key, coord) is not None
        out.append(
            _manifest_to_card(
                m,
                scope="my-imports",
                imported=True,
                installed_in_project=False,
                published=publications.is_published(coord),
                publishable=store_backed,
            )
        )
    return out


def list_installed_in_project(user_key: str, project_id: str) -> list[dict]:
    """The project's installed templates from its ``dataflow.agents`` lockfile."""
    spec = projects_storage.read_spec(user_key, project_id)
    if spec is None:
        raise AgentServiceError(f"project {project_id!r} has no spec", 404)
    imported = imports.load_imported_agents(user_key)
    out: list[dict] = []
    for coord in project_agents.project_agents(spec):
        m = _resolve_definition(user_key, coord)
        if m is None:
            continue
        out.append(
            _manifest_to_card(
                m, scope="installed", imported=coord in imported, installed_in_project=True
            )
        )
    return out


# ── lifecycle commands (explicit, non-chaining) ──────────────────────────────
def import_agent(user_key: str, coord: str) -> dict:
    """Record *coord* in the account's My Imports (does not install into a project)."""
    _require_definition(user_key, coord)
    imports.add_imported_agent(user_key, coord)
    return {"coord": coord, "imported": True}


def remove_import(user_key: str, coord: str) -> dict:
    """Drop *coord* from My Imports (does not touch project installs)."""
    imports.remove_imported_agent(user_key, coord)
    return {"coord": coord, "imported": False}


def install_in_project(user_key: str, project_id: str, coord: str) -> dict:
    """Add *coord* to the project's lockfile (explicit; never auto-imports)."""
    _require_definition(user_key, coord)
    spec = projects_storage.read_spec(user_key, project_id)
    if spec is None:
        raise AgentServiceError(f"project {project_id!r} has no spec", 404)
    current = project_agents.project_agents(spec)
    if coord not in current:
        project_agents.set_project_agents(spec, current + [coord])
        projects_storage.write_spec(user_key, project_id, spec)
    return {"agents": project_agents.project_agents(spec)}


def uninstall_from_project(user_key: str, project_id: str, coord: str) -> dict:
    """Remove *coord* from the project's lockfile."""
    spec = projects_storage.read_spec(user_key, project_id)
    if spec is None:
        raise AgentServiceError(f"project {project_id!r} has no spec", 404)
    current = project_agents.project_agents(spec)
    if coord in current:
        project_agents.set_project_agents(spec, [c for c in current if c != coord])
        projects_storage.write_spec(user_key, project_id, spec)
    return {"agents": project_agents.project_agents(spec)}


def publish_agent(user_key: str, coord: str) -> dict:
    """Publish an owned, store-backed imported definition to the Global Catalog.

    Imported-only (`DEC-030`): the coordinate must resolve to a definition in the
    user's own store (not a built-in / global / absent one) and be in My Imports.
    Built-ins are not store-backed, so they are rejected here.
    """
    m = storage.load_installed_agent_definition(user_key, coord)
    if m is None:
        raise AgentServiceError(
            "only an owned, imported definition can be published; built-in, global, or "
            "absent definitions cannot",
            400,
        )
    if coord not in imports.load_imported_agents(user_key):
        raise AgentServiceError("import the definition before publishing it", 400)
    publications.publish_from_dir(storage.agent_definition_dir(user_key, coord), coord)
    return {"coord": coord, "published": True}


def unpublish_agent(user_key: str, coord: str) -> dict:
    """Remove an owned definition from the Global Catalog (only its owner may)."""
    if storage.load_installed_agent_definition(user_key, coord) is None:
        raise AgentServiceError("only the owning account can unpublish this definition", 403)
    publications.unpublish(coord)
    return {"coord": coord, "published": False}


# ── attachments (private agent instances in the project graph) ───────────────
def _read_spec_or_404(user_key: str, project_id: str) -> dict:
    spec = projects_storage.read_spec(user_key, project_id)
    if spec is None:
        raise AgentServiceError(f"project {project_id!r} has no spec", 404)
    return spec


def _attachment_card(spec: dict, record: dict, user_key: str) -> dict:
    """Attachment record + a resolved name/hooks for its source template (best-effort)."""
    coord = record.get("coord", "")
    m = _resolve_definition(user_key, coord)
    return {
        "attachmentId": record.get("attachmentId"),
        "coord": coord,
        "target": record.get("target"),
        "sessionId": record.get("sessionId"),
        "revision": record.get("revision", 1),
        "name": m.name if m else coord,
        "category": m.category if m else None,
        "hooks": [t.kind for t in m.compatible_targets] if m else [],
    }


def list_project_attachments(user_key: str, project_id: str) -> list[dict]:
    spec = _read_spec_or_404(user_key, project_id)
    return [_attachment_card(spec, r, user_key) for r in attachments.list_attachments(spec)]


def attach_agent(user_key: str, project_id: str, coord: str, target: object) -> dict:
    """Attach an installed template to a target. Requires the template installed
    in this project (no auto-install), and a valid target."""
    spec = _read_spec_or_404(user_key, project_id)
    if coord not in project_agents.project_agents(spec):
        raise AgentServiceError(
            "install the agent in this project before attaching it", 400
        )
    try:
        record = attachments.attach(
            spec, coord, target, attachment_id=uuid.uuid4().hex, session_id=uuid.uuid4().hex
        )
    except AttachmentError as exc:
        raise AgentServiceError(str(exc), 400) from exc
    projects_storage.write_spec(user_key, project_id, spec)
    return _attachment_card(spec, record, user_key)


def detach_agent(user_key: str, project_id: str, attachment_id: str) -> dict:
    spec = _read_spec_or_404(user_key, project_id)
    removed = attachments.detach(spec, attachment_id)
    if removed:
        projects_storage.write_spec(user_key, project_id, spec)
    return {"attachmentId": attachment_id, "detached": removed}
