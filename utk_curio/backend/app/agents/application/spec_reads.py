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
from utk_curio.backend.app.agents.application.errors import AgentServiceError
from utk_curio.backend.app.agents.repositories import project_agents as agents_project_agents
from utk_curio.backend.app.projects import storage as projects_storage


# ── attachments (private agent instances in the project graph) ───────────────
def _read_spec_or_404(user_key: str, project_id: str) -> dict:
    spec = projects_storage.read_spec(user_key, project_id)
    if spec is None:
        raise AgentServiceError(f"project {project_id!r} has no spec", 404)
    return spec


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
