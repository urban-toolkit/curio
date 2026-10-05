"""Explicit, non-chaining lifecycle commands: import/remove, seed, install with its requiresAgents closure, uninstall, publish/unpublish (DEC-029).

Application layer of the agents package (memo dev/142, B2; re-derived on enh/agent-catalog): cut from
``services.py`` by responsibility; every function keeps its name and body. Sibling modules are reached
module-qualified (``agents_<module>.name``) so a test that patches the owner is seen by every caller,
and import order between siblings cannot matter.
"""

from __future__ import annotations

import logging

from utk_curio.backend.app.agents.application import attachments
from utk_curio.backend.app.agents.application import delegation
from utk_curio.backend.app.agents.application.errors import AgentServiceError
from utk_curio.backend.app.agents.domain import builtin
from utk_curio.backend.app.agents.repositories import imports
from utk_curio.backend.app.agents.repositories import project_agents
from utk_curio.backend.app.agents.repositories import publications
from utk_curio.backend.app.agents.repositories import sessions
from utk_curio.backend.app.agents.repositories import storage
from utk_curio.backend.app.agents.application import catalog as agents_catalog
from utk_curio.backend.app.agents.repositories import project_agents as agents_project_agents
from utk_curio.backend.app.projects import storage as projects_storage

log = logging.getLogger(__name__)


# ── lifecycle commands (explicit, non-chaining) ──────────────────────────────
def _fan_out_imports(user, user_key: str, coord: str, *, install: bool) -> list[dict]:
    """Apply an account-level import decision to every project the user has.

    Recording a coordinate in My Imports writes no project lockfile, and the
    canvas agents palette reads the lockfile (``listProjectAgents`` ->
    ``dataflow.agents``). So an imported agent was reported as "In all projects"
    by the catalog while appearing in none of them - the catalog was describing
    the account, the palette was describing the project, and the label was
    simply false.

    This is the same eager walk ``packages.services.install_to_defaults`` does,
    for the same reason: nothing consults the account list when a project is
    opened, so only a walk at decision time can make the claim true.

    Best-effort per project - one project with a broken spec must not abort the
    rest, and never fails the import itself.
    """
    if user is None:
        return []
    from utk_curio.backend.app.projects import repositories as projects_repo

    results: list[dict] = []
    for project in projects_repo.list_for_user(user.id):
        try:
            if install:
                install_in_project(user_key, project.id, coord)
            else:
                uninstall_from_project(user_key, project.id, coord)
            results.append({"id": project.id, "ok": True})
        except Exception as exc:  # noqa: BLE001 - per-project failure is OK
            log.warning(
                "agent import fan-out (%s) failed for project %s: %s",
                "install" if install else "uninstall", project.id, exc,
            )
            results.append({"id": project.id, "ok": False, "error": str(exc)})
    return results


def _refuse_internal(coord: str) -> None:
    """An internal built-in runs only as a delegate of other agents: it is
    never imported, installed or attached."""
    if builtin.is_internal(coord):
        spec = builtin.get_builtin_spec(coord) or builtin.get_builtin_spec(
            f"{coord}@{builtin.BUILTIN_VERSION}"
        )
        name = spec.name if spec else coord
        raise AgentServiceError(
            f"{name} runs only as a delegate of other agents; it is not installed or attached",
            400,
        )


def import_agent(user_key: str, coord: str, *, user=None) -> dict:
    """Record *coord* in My Imports and install it into every project.

    ``user`` is optional so the many existing callers that only hold a
    ``user_key`` keep working unchanged; without it this records the coordinate
    and nothing else, exactly as before.
    """
    _refuse_internal(coord)
    agents_catalog._require_definition(user_key, coord)
    agents_catalog._materialize_definition(user_key, coord)
    imports.add_imported_agent(user_key, coord)
    projects = _fan_out_imports(user, user_key, coord, install=True)
    return {"coord": coord, "imported": True, "projects": projects}


def remove_import(user_key: str, coord: str, *, user=None) -> dict:
    """Drop *coord* from My Imports and uninstall it from every project."""
    imports.remove_imported_agent(user_key, coord)
    projects = _fan_out_imports(user, user_key, coord, install=False)
    return {"coord": coord, "imported": False, "projects": projects}


def seed_project_with_imported_agents(user_key: str, project_id: str) -> None:
    """Install the account's imported agents into a brand-new project.

    The "future" half of "all your projects, present and future"; the walk above
    is the "present" half. Best-effort: a stale import must degrade to "that
    agent is missing here", never to "the project could not be created".
    """
    try:
        coords = imports.load_imported_agents(user_key)
    except Exception:  # noqa: BLE001
        return
    for coord in sorted(coords):
        try:
            install_in_project(user_key, project_id, coord)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "seed imported agent %s into project %s failed: %s",
                coord, project_id, exc,
            )


def install_in_project(user_key: str, project_id: str, coord: str) -> dict:
    """Add *coord* AND its ``requiresAgents`` closure to the project's lockfile
    (explicit; never auto-imports).

    dev/106: the closure (``delegation.required_closure``) is resolved BEFORE
    anything is written — a dependency visible nowhere refuses with 409 and
    leaves the lockfile untouched. Every coord in the closure is materialized
    and recorded in ONE spec write. This runs at the user's explicit Install
    (drawer button or a reviewed ``project.install`` Apply), so `REQ-ORCH-001`
    — the orchestrator never installs silently — is untouched.

    Also materializes the project-agent-default record (memo dev/23) — an
    independent per-project profile the settings screens later edit. Idempotent:
    reinstalling never resets an existing record.

    Returns ``{"agents": lockfile, "installed": [coords newly added, root
    first], "required": [the closure's coords]}``.
    """
    _refuse_internal(coord)
    root = agents_catalog._require_definition(user_key, coord)
    required, missing = delegation.required_closure(user_key, root)
    if missing:
        raise AgentServiceError(
            f"{root.name} ({coord}) requires "
            + ", ".join(missing)
            + ", which " + ("is" if len(missing) == 1 else "are")
            + " not available in the catalog or your imports — nothing was installed",
            409,
        )
    spec = projects_storage.read_spec(user_key, project_id)
    if spec is None:
        raise AgentServiceError(f"project {project_id!r} has no spec", 404)
    for c in [coord, *required]:
        agents_catalog._materialize_definition(user_key, c)
    current = project_agents.project_agents(spec)
    added: list[str] = []
    for c in [coord, *required]:
        if c not in current and c not in added:
            added.append(c)
    dirty = False
    if added:
        project_agents.set_project_agents(spec, current + added)
        dirty = True
    if dirty:
        projects_storage.write_spec(user_key, project_id, spec)
    return {
        "agents": project_agents.project_agents(spec),
        "installed": added,
        "required": required,
    }


def _repair_required_closure(
    user_key: str, project_id: str, coord: str, *, attachment_id: str | None = None
) -> list[str]:
    """``DEC-080`` (memo dev/126): complete an installed agent's declared
    hard-dependency closure at the point the USER acts on the dependent.

    A project whose lockfile predates a ``requiresAgents`` declaration is
    missing an agent a SERVER path of the dependent invokes without model
    choice, and no amount of conversation can fix that: the run stalls on a
    reviewed install for something the user already consented to when they
    installed the dependent (that is what ``DEC-068`` made an install mean).
    So the closure is completed through the ONE install path
    (``install_in_project`` — same materialization, same single spec write,
    same 409 when a member is visible nowhere), bounded to ``requiresAgents``
    members, never a preferred delegate, and never a model decision:
    `REQ-ORCH-001` is untouched.

    Returns the coords added (empty when the closure was already complete, or
    when it could not be completed — a refusal is logged and disclosed by the
    caller's own fallback lane, never raised into the user's action).
    """

    try:
        manifest = agents_catalog._resolve_definition(user_key, coord)
        if manifest is None or not manifest.requires_agents:
            return []
        spec = projects_storage.read_spec(user_key, project_id)
        if spec is None:
            return []
        installed_ids = {
            c.split("@", 1)[0] for c in agents_project_agents.project_agents(spec)
        }
        required, missing = delegation.required_closure(user_key, manifest)
        if missing:
            log.warning(
                "Required agent(s) %s of %s are visible nowhere — project %s keeps the "
                "reviewed install lane", ", ".join(missing), coord, project_id,
            )
            return []
        if all(c.split("@", 1)[0] in installed_ids for c in required):
            return []
        added = install_in_project(user_key, project_id, coord).get("installed") or []
    except Exception:  # noqa: BLE001
        log.warning("Could not repair the required closure of %s in project %s",
                    coord, project_id, exc_info=True)
        return []
    if added and attachment_id:
        _disclose_closure_repair(user_key, project_id, attachment_id, coord, added)
    return added


def _disclose_closure_repair(
    user_key: str, project_id: str, attachment_id: str, coord: str, added: list[str]
) -> None:
    """Say in the transcript what the repair installed and why (dev/126) — an
    install the user did not click on this turn is never silent. Best-effort:
    the disclosure never fails the action it describes."""
    try:
        spec = projects_storage.read_spec(user_key, project_id)
        record = attachments.get_attachment(spec or {}, attachment_id) or {}
        session_id = record.get("sessionId")
        if not isinstance(session_id, str):
            return
        dependent = agents_catalog._resolve_definition(user_key, coord)
        dependent_name = getattr(dependent, "name", None) or coord
        names = []
        for c in added:
            m = agents_catalog._resolve_definition(user_key, c)
            names.append(getattr(m, "name", None) or c)
        sessions.append_turns(
            user_key, project_id, session_id, attachment_id,
            [sessions.make_turn(
                "agent",
                f"Added {', '.join(names)} — required by {dependent_name}.",
                content=[{
                    "type": "card",
                    "kind": "result",
                    "title": "Added required agents",
                    "lines": [c for c in added[:6]] + [f"required by {coord}"],
                }],
            )],
        )
    except Exception:  # noqa: BLE001
        log.warning("Could not disclose the closure repair for %s", coord, exc_info=True)


def uninstall_from_project(user_key: str, project_id: str, coord: str) -> dict:
    """Remove *coord* from the project's lockfile and drop its defaults record.

    dev/106: refused (409) while another INSTALLED template lists *coord*'s
    agent in ``requiresAgents`` — the dependents are named. No cascade."""
    spec = projects_storage.read_spec(user_key, project_id)
    if spec is None:
        raise AgentServiceError(f"project {project_id!r} has no spec", 404)
    current = project_agents.project_agents(spec)
    dependents = delegation.required_by(user_key, current, coord) if coord in current else []
    if dependents:
        names = []
        for d in dependents:
            dm = agents_catalog._resolve_definition(user_key, d)
            names.append(f"{dm.name} ({d})" if dm else d)
        raise AgentServiceError(
            f"{coord} is required by " + ", ".join(names)
            + " — uninstall " + ("that agent" if len(names) == 1 else "those agents") + " first",
            409,
        )
    dirty = False
    if coord in current:
        project_agents.set_project_agents(spec, [c for c in current if c != coord])
        dirty = True
    # ...and take its attachments with it. Without this the agent was removed
    # from the lockfile while its badges stayed on the nodes and it kept
    # running: `attach` is gated on the lockfile but `run_attachment` is not.
    detached = attachments.detach_all_for_coord(spec, coord)
    if detached:
        dirty = True
    if dirty:
        projects_storage.write_spec(user_key, project_id, spec)
    return {
        "agents": project_agents.project_agents(spec),
        "detached": [r.get("attachmentId") for r in detached],
    }


NOT_THE_PUBLISHER_MESSAGE = "only the owning account can unpublish this definition"
NOT_THE_PUBLISHER_REPLACE_MESSAGE = "only the account that published this definition can replace it"


def publish_agent(user_key: str, coord: str) -> dict:
    """Publish an owned imported definition to the Global Catalog.

    Imported-only (`DEC-030`): the coordinate must resolve to a store definition
    whose provenance trust is ``imported`` (a user-owned definition) and be in My
    Imports. Built-ins — even after their bytes are materialized into the store —
    carry trust ``built-in`` and are rejected here.
    """
    m = storage.load_installed_agent_definition(user_key, coord)
    if m is None or m.provenance.trust != "imported":
        raise AgentServiceError(
            "only an owned imported definition (trust=imported) can be published; built-in, "
            "global, or absent definitions cannot",
            400,
        )
    if coord not in imports.load_imported_agents(user_key):
        raise AgentServiceError("import the definition before publishing it", 400)
    # A republish replaces what is there, so it follows unpublish's rule.
    if publications.is_published(coord) and not publications.is_publisher(coord, user_key):
        raise AgentServiceError(NOT_THE_PUBLISHER_REPLACE_MESSAGE, 403)
    publications.publish_from_dir(storage.agent_definition_dir(user_key, coord), coord)
    publications.record_publisher(coord, user_key)
    return {"coord": coord, "published": True}


def unpublish_agent(user_key: str, coord: str) -> dict:
    """Remove a published definition from the Global Catalog (only its publisher may).

    The publisher record decides, not a store copy: every account that added
    the agent holds one (#438). A publication with no record (published before
    the record existed) fails closed, as a node package does.
    """
    if publications.is_published(coord) and not publications.is_publisher(coord, user_key):
        raise AgentServiceError(NOT_THE_PUBLISHER_MESSAGE, 403)
    publications.unpublish(coord)
    return {"coord": coord, "published": False}
