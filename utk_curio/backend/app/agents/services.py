"""Agents catalog / lifecycle service layer.

Sits over the filesystem stores (``storage`` = definition artifacts, ``imports``
= account "My Imports", ``project_agents`` = per-project lockfile) and mirrors
``app/packages/services.py``: the route layer stays thin, this layer owns the
rules, and the project lockfile is read/written through ``projects.storage``.

Import and Install are separate explicit commands and never chain (DEC-029).
User-facing overview: ``docs/AGENTS.md``.
"""

from __future__ import annotations

from utk_curio.backend.app.agents import imports, project_agents, storage
from utk_curio.backend.app.agents.manifest import AgentManifest
from utk_curio.backend.app.projects import storage as projects_storage


class AgentServiceError(Exception):
    """Service-layer error carrying an HTTP status for the route layer."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _manifest_to_card(
    m: AgentManifest, *, scope: str, imported: bool, installed_in_project: bool
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
        "scope": scope,
    }


def _require_definition(user_key: str, coord: str) -> AgentManifest:
    m = storage.load_installed_agent_definition(user_key, coord)
    if m is None:
        raise AgentServiceError(f"no agent definition {coord!r} available", 404)
    return m


# ── read ────────────────────────────────────────────────────────────────────
def list_my_imports(user_key: str) -> list[dict]:
    """Account "My Imports": each imported coordinate whose definition is present."""
    imported = imports.load_imported_agents(user_key)
    out: list[dict] = []
    for coord in sorted(imported):
        m = storage.load_installed_agent_definition(user_key, coord)
        if m is None:
            continue
        out.append(_manifest_to_card(m, scope="my-imports", imported=True, installed_in_project=False))
    return out


def list_installed_in_project(user_key: str, project_id: str) -> list[dict]:
    """The project's installed templates from its ``dataflow.agents`` lockfile."""
    spec = projects_storage.read_spec(user_key, project_id)
    if spec is None:
        raise AgentServiceError(f"project {project_id!r} has no spec", 404)
    imported = imports.load_imported_agents(user_key)
    out: list[dict] = []
    for coord in project_agents.project_agents(spec):
        m = storage.load_installed_agent_definition(user_key, coord)
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
