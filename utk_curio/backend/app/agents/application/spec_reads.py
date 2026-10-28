"""Shared readers over a project's saved spec: the 404-raising loaders, the acting user, and the small lookups every use case needs.

Application layer of the agents package (memo dev/142, B2; re-derived on enh/agent-catalog): cut from
``services.py`` by responsibility; every function keeps its name and body. Sibling modules are reached
module-qualified (``agents_<module>.name``) so a test that patches the owner is seen by every caller,
and import order between siblings cannot matter.
"""

from __future__ import annotations

import hashlib
import json as _json

from utk_curio.backend.app.agents.application import attachments
from utk_curio.backend.app.agents.application import catalog as agents_catalog
from utk_curio.backend.app.agents.application.errors import AgentServiceError
from utk_curio.backend.app.agents.domain import builtin
from utk_curio.backend.app.agents.domain.manifest import AgentManifest
from utk_curio.backend.app.agents.repositories import project_agents as agents_project_agents
from utk_curio.backend.app.collaboration import dataflow_docs
from utk_curio.backend.app.projects import storage as projects_storage


# ── attachments (private agent instances in the project graph) ───────────────
def _read_spec_or_404(user_key: str, project_id: str) -> dict:
    spec = projects_storage.read_spec(user_key, project_id)
    if spec is None:
        raise AgentServiceError(f"project {project_id!r} has no spec", 404)
    return spec


def _live_spec_or_404(user_key: str, project_id: str) -> dataflow_docs.Live:
    """The dataflow as it is now, for a use case that writes it: the spec it
    changes and hands to ``dataflow_docs.write``, which applies only what it
    changed. It holds no history."""
    spec = dataflow_docs.live(user_key, project_id)
    if spec is None:
        raise AgentServiceError(f"project {project_id!r} has no spec", 404)
    return spec


def _agent_actor(user_key: str, spec: dict | None, attachment_id: str | None, what: str) -> dataflow_docs.Actor:
    """Who a change an attachment's agent writes is by: the agent the
    attachment binds, asked by the account (the origin of its transaction on
    the dataflow's doc)."""
    record = attachments.get_attachment(spec, attachment_id) if spec and attachment_id else None
    return dataflow_docs.by_agent(str((record or {}).get("coord") or "") or None, user_key, what)


def _person(user_key: str, what: str) -> dataflow_docs.Actor:
    """Who a change the account makes itself, through the agents' panels, is by."""
    return dataflow_docs.person(user_key, what)


def _record_or_404(spec: dict, attachment_id: str) -> dict:
    record = attachments.get_attachment(spec, attachment_id)
    if record is None:
        raise AgentServiceError(f"attachment {attachment_id!r} not found", 404)
    return record


def attachment_agent_id(user_key: str, project_id: str, attachment_id: str) -> str | None:
    """The agent id (the coordinate before ``@``) an attachment binds, or None
    when the project or the attachment is not there (the run that follows says
    so itself)."""
    spec = projects_storage.read_spec(user_key, project_id)
    record = attachments.get_attachment(spec, attachment_id) if spec else None
    coord = str((record or {}).get("coord") or "")
    return coord.split("@", 1)[0] or None


def _graph_shape_digest(spec: dict) -> str:
    """The whole-graph revision basis for plan proposals (dev/52): sha256 of
    the saved dataflow's sorted node-id and edge-id sets. Content edits do
    NOT change it — deliberate: they don't invalidate an additive plan."""

    dataflow = spec.get("dataflow") or {}
    node_ids = sorted(
        str(n.get("id")) for n in (dataflow.get("nodes") or []) if isinstance(n, dict)
    )
    edge_ids = sorted(
        str(e.get("id", f"{e.get('source')}->{e.get('target')}"))
        for e in (dataflow.get("edges") or [])
        if isinstance(e, dict)
    )
    basis = _json.dumps([node_ids, edge_ids])
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def _installed_project_coord(spec: dict, agent_id: str) -> str | None:
    """The project lockfile's coord for *agent_id*, or None when absent."""

    return next(
        (
            c for c in agents_project_agents.project_agents(spec)
            if c.split("@", 1)[0] == agent_id
        ),
        None,
    )


def _node_attachment_of(spec: dict, agent_id: str, node_id: str) -> dict | None:
    """An existing attachment of *agent_id* on node *node_id*, or None."""
    for existing in attachments.list_attachments(spec):
        target = existing.get("target") or {}
        if (
            existing.get("coord", "").split("@", 1)[0] == agent_id
            and target.get("kind") == "node"
            and target.get("targetId") == node_id
        ):
            return existing
    return None


# ── agents by what they declare ──────────────────────────────────────────────
# An agent is found by the capabilities its manifest declares, never by its
# id, so a user's own agent that declares what a shipped one does is picked
# where the shipped one would be.


def _definition(user_key: str | None, coord: str) -> AgentManifest | None:
    """The definition behind *coord*: the account's, resolved as everywhere
    else (``catalog._resolve_definition``), or the shipped roster's when no
    account is known."""
    if not coord:
        return None
    if not user_key:
        return builtin.get_builtin_manifest(coord)
    try:
        return agents_catalog._resolve_definition(user_key, coord)
    except Exception:  # noqa: BLE001 - an unreadable definition declares nothing
        return None


def _declares(user_key: str | None, coord: str, capability: str) -> bool:
    """Whether the agent at *coord* declares *capability*."""
    manifest = _definition(user_key, coord)
    return manifest is not None and capability in manifest.capability_ids


def _node_attachment_declaring(
    spec: dict | None, capability: str, node_id: str, *, user_key: str | None = None
) -> dict | None:
    """The attachment on node *node_id* whose agent declares *capability*,
    the first in the spec's order, or None."""
    for existing in attachments.list_attachments(spec):
        target = existing.get("target") or {}
        if (
            target.get("kind") == "node"
            and target.get("targetId") == node_id
            and _declares(user_key, str(existing.get("coord") or ""), capability)
        ):
            return existing
    return None


def _installed_coord_declaring(
    spec: dict | None, capability: str, *, user_key: str | None = None
) -> str | None:
    """The first coord of the project's lockfile, in sorted order, whose agent
    declares *capability*, or None."""
    return next(
        (
            coord for coord in sorted(agents_project_agents.project_agents(spec))
            if _declares(user_key, coord, capability)
        ),
        None,
    )


def _agent_name(user_key: str | None, coord: str) -> str | None:
    """The name the manifest at *coord* gives its agent, or None."""
    return getattr(_definition(user_key, coord), "name", None)


def _attachment_agent_name(user_key: str, project_id: str, attachment_id: str | None) -> str | None:
    """The name of the agent attachment *attachment_id* binds, or None."""
    if not attachment_id:
        return None
    spec = projects_storage.read_spec(user_key, project_id)
    record = attachments.get_attachment(spec, attachment_id) if spec else None
    return _agent_name(user_key, str((record or {}).get("coord") or ""))


def _shipped_name_declaring(capability: str) -> str | None:
    """The name of the shipped card that declares *capability*: what a message
    calls the agent for a job when no agent of the dataflow's does it yet."""
    return next(
        (
            m.name for m in builtin.list_builtin_manifests()
            if capability in m.capability_ids and not builtin.is_internal(m.dir_name)
        ),
        None,
    )


def _acting_user():
    """The user object the request is acting as, or None — captured at a job's
    ENTRY so the detached thread can still reach the datasets domain (which is
    user-object keyed, unlike the key-based agents store)."""
    try:
        from flask import g, has_request_context

        return getattr(g, "user", None) if has_request_context() else None
    except Exception:  # noqa: BLE001 — not under Flask
        return None


def _acting_token():
    """The request's sign-in token, or None, captured at a run's entry like
    :func:`_acting_user`. The sandbox tags every artifact the run makes with
    it, as it does on Play, so only that session can read them back."""
    try:
        from flask import has_request_context

        from utk_curio.backend.app.users.dependencies import get_current_token

        return get_current_token() if has_request_context() else None
    except Exception:  # noqa: BLE001 - not under Flask
        return None
