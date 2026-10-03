"""Helpers shared by the agent route tests (test_agents/test_routes_*.py)
and by the agent tests that build on them."""

from __future__ import annotations

import json

from utk_curio.backend.app.agents.repositories import storage
from utk_curio.backend.app.projects.services import _user_dir_key


def _auth(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _block_closure_repair(monkeypatch):
    """dev/126 (``DEC-080``): stand in for the one state the repair cannot fix
    — a required agent that is visible nowhere, where ``install_in_project``
    refuses with 409 and writes nothing. The reviewed ``project.install`` lane
    still carries the state, which is what these tests are about.

    Returns ``release()``: the user's own Apply of that reviewed install goes
    through the same function, so a test that walks the migration path lifts
    the block before clicking Apply."""
    from utk_curio.backend.app.agents.application import errors
    from utk_curio.backend.app.agents.application import lifecycle

    real = lifecycle.install_in_project
    blocked = [True]

    def _refuse(*a, **k):
        if not blocked[0]:
            return real(*a, **k)
        raise errors.AgentServiceError(
            "requires agent.ghost, which is not available in the catalog or your "
            "imports — nothing was installed", 409,
        )

    monkeypatch.setattr(
        'utk_curio.backend.app.agents.application.lifecycle.install_in_project', _refuse
    )

    def release():
        blocked[0] = False

    return release


def _drop_from_lockfile(user, project_id, coord):
    """Simulate a pre-dev/106 project: remove *coord* from ``dataflow.agents``
    directly (the API refuses uninstalling a required dependency)."""
    from utk_curio.backend.app.agents.repositories import project_agents
    from utk_curio.backend.app.projects import storage as projects_storage

    key = _user_dir_key(user)
    spec = projects_storage.read_spec(key, project_id)
    project_agents.set_project_agents(
        spec, [c for c in project_agents.project_agents(spec) if c != coord]
    )
    projects_storage.write_spec(key, project_id, spec)


def _write_def(user, agent_id="agent.my-explainer", version="1.0.0"):
    """Materialize a valid agent definition in the user's FS store."""
    user_key = _user_dir_key(user)
    d = storage.user_agents_dir(user_key) / f"{agent_id}@{version}"
    d.mkdir(parents=True, exist_ok=True)
    (d / "manifest.json").write_text(
        json.dumps(
            {
                "id": agent_id,
                "name": "My Explainer",
                "category": "node",
                "version": version,
                "capabilities": [{"id": "node.explain", "contractVersion": "1"}],
                "compatibleTargets": [{"kind": "node", "requires": []}],
                # These helper-written defs represent user-authored/owned imports.
                "provenance": {"publisher": "curio", "trust": "imported"},
            }
        ),
        encoding="utf-8",
    )
    return f"{agent_id}@{version}"


def db_user(client, user):
    """Re-fetch the ORM user in the current app context (route fixtures hand
    back a detached instance)."""
    from utk_curio.backend.app.users.models import User

    return User.query.get(user.id)
