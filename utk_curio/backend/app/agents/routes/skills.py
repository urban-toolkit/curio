"""Skills in the Agent Catalog: the skills Curio ships, one skill's text, an agent's skills and the account's changes to them, and a chat's skills.

Presentation layer of the agents package: the handlers of ``application/skill_catalog.py``,
registered on the one ``agents_bp`` from ``routes/common.py``. Reads are open to any
signed-in account; a change belongs to the account that makes it, and a hosted guest,
whose account every guest shares, may make none (``users.capabilities.agent_skills_refusal``).
"""

from __future__ import annotations

from flask import g
from flask import jsonify
from flask import request

from utk_curio.backend.app.agents import service as agents_services
from utk_curio.backend.app.agents.routes.common import _error
from utk_curio.backend.app.agents.routes.common import _map_agent_errors
from utk_curio.backend.app.agents.routes.common import agents_bp
from utk_curio.backend.app.projects import repositories as projects_repo
from utk_curio.backend.app.projects.services import _user_dir_key
from utk_curio.backend.app.users.capabilities import agent_skills_refusal
from utk_curio.backend.app.users.dependencies import require_auth


def _agent_skills_payload(rows: dict) -> dict:
    """An agent's skills, with whether this account may change them and why not."""
    return {**rows, "reason": agent_skills_refusal(g.user)}


@agents_bp.route("/skills", methods=["GET"])
@require_auth
@_map_agent_errors
def list_skills():
    """Every skill Curio ships, each with what it serves and the agents that use it."""
    refusal = agent_skills_refusal(g.user)
    return jsonify({
        "skills": agents_services.skills_listing(_user_dir_key(g.user)),
        "editable": refusal is None,
        "reason": refusal,
    }), 200


@agents_bp.route("/skills/<name>", methods=["GET"])
@require_auth
@_map_agent_errors
def read_skill(name: str):
    """One skill's text as an agent reads it, and its other files."""
    return jsonify(agents_services.skill_text(name)), 200


@agents_bp.route("/definitions/<coord>/skills", methods=["GET"])
@require_auth
@_map_agent_errors
def list_agent_skills(coord: str):
    """The skills of one agent for this account, which of them it may remove,
    and which it may add."""
    rows = agents_services.agent_skill_rows(
        _user_dir_key(g.user), coord, editable=agent_skills_refusal(g.user) is None,
    )
    return jsonify(_agent_skills_payload(rows)), 200


@agents_bp.route("/definitions/<coord>/skills", methods=["POST"])
@require_auth
@_map_agent_errors
def add_agent_skill(coord: str):
    """Add a skill to an agent for this account: ``{skill}``, a skill's name."""
    refusal = agent_skills_refusal(g.user)
    if refusal:
        return _error(refusal, 403)
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or not isinstance(body.get("skill"), str):
        return _error("send {skill}, the name of a skill")
    rows = agents_services.add_skill(_user_dir_key(g.user), coord, body["skill"])
    return jsonify(_agent_skills_payload(rows)), 200


@agents_bp.route("/definitions/<coord>/skills/<name>", methods=["DELETE"])
@require_auth
@_map_agent_errors
def remove_agent_skill(coord: str, name: str):
    """Remove a skill from an agent for this account."""
    refusal = agent_skills_refusal(g.user)
    if refusal:
        return _error(refusal, 403)
    rows = agents_services.remove_skill(_user_dir_key(g.user), coord, name)
    return jsonify(_agent_skills_payload(rows)), 200


@agents_bp.route("/definitions/<coord>/skills", methods=["DELETE"])
@require_auth
@_map_agent_errors
def restore_agent_skills(coord: str):
    """Give an agent back the skills its manifest names, for this account."""
    refusal = agent_skills_refusal(g.user)
    if refusal:
        return _error(refusal, 403)
    rows = agents_services.restore_skills(_user_dir_key(g.user), coord)
    return jsonify(_agent_skills_payload(rows)), 200


@agents_bp.route("/projects/<project_id>/attachments/<attachment_id>/skills", methods=["GET"])
@require_auth
@_map_agent_errors
def list_attachment_skills(project_id: str, attachment_id: str):
    """The skills the attachment's next chat run lists: what ``/`` offers in its chat."""
    try:
        projects_repo.get_for_user(project_id, g.user.id)
    except projects_repo.NotFoundError:
        return _error("project not found", 404)
    return jsonify({
        "skills": agents_services.run_skills(_user_dir_key(g.user), project_id, attachment_id),
    }), 200
