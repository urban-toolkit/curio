"""Skills in the Agent Catalog: the skills an account sees, one skill's text, an agent's skills and the account's changes to them, a chat's skills, and an account's own skills, imported, exported, published and removed.

Presentation layer of the agents package: the handlers of
``application/skill_catalog.py`` and ``application/skill_lifecycle.py``,
registered on the one ``agents_bp`` from ``routes/common.py``. Reads are open
to any signed-in account; a change belongs to the account that makes it, and a
hosted guest, whose account every guest shares, may make none
(``users.capabilities.agent_skills_refusal`` for an agent's skills, and the
agents' own ``lifecycle.refuse_hosted_guest`` for an import, a removal, a
publication and an unpublication). Publishing follows the operator's switch,
as an agent's does.

An upload (``imports/check`` and ``imports``) is a multipart form: ``files``,
the skill's files, with ``paths``, a JSON list of their paths in the folder
that was picked, in the same order; or one ``.zip``. ``name`` keeps the skill
under another name, and ``agents``, a JSON list of agents' coordinates, gives
it to them.
"""

from __future__ import annotations

import io
import json

from flask import g
from flask import jsonify
from flask import request
from flask import send_file

from utk_curio.backend.app.agents import service as agents_services
from utk_curio.backend.app.agents.routes.common import _error
from utk_curio.backend.app.agents.routes.common import _map_agent_errors
from utk_curio.backend.app.agents.routes.common import agents_bp
from utk_curio.backend.app.agents.service import AgentServiceError
from utk_curio.backend.app.packages.routes import common as packages_routes_common
from utk_curio.backend.app.projects import repositories as projects_repo
from utk_curio.backend.app.projects.services import _user_dir_key
from utk_curio.backend.app.users.capabilities import agent_skills_refusal
from utk_curio.backend.app.users.dependencies import require_auth


def _agent_skills_payload(rows: dict) -> dict:
    """An agent's skills, with whether this account may change them and why not."""
    return {**rows, "reason": agent_skills_refusal(g.user)}


def _upload_parts() -> list[tuple[str, bytes]]:
    """The files of a skill's upload, each its path and its bytes, each read
    no further than an upload may hold."""
    files = request.files.getlist("files")
    try:
        paths = json.loads(request.form.get("paths") or "[]")
    except ValueError:
        paths = None
    if not (isinstance(paths, list) and len(paths) == len(files) and all(isinstance(p, str) for p in paths)):
        paths = [upload.filename or "" for upload in files]
    limit = agents_services.SKILL_UPLOAD.total_bytes
    parts: list[tuple[str, bytes]] = []
    for path, upload in zip(paths, files):
        data = upload.read(limit + 1)
        if len(data) > limit:
            raise AgentServiceError(f"{path or 'a file'} holds more than an upload may", 413)
        parts.append((path, data))
    return parts


def _upload_name() -> str | None:
    name = (request.form.get("name") or "").strip()
    return name or None


@agents_bp.route("/skills", methods=["GET"])
@require_auth
@_map_agent_errors
def list_skills():
    """Every skill the account sees, each with what it serves, whose it is
    and the agents that use it."""
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
    return jsonify(agents_services.skill_text(_user_dir_key(g.user), name)), 200


@agents_bp.route("/skills/<name>/export", methods=["GET"])
@require_auth
@_map_agent_errors
def export_skill(name: str):
    """One skill as a zip of its folder, which agentskills.io's tools read."""
    filename, data = agents_services.export_skill(_user_dir_key(g.user), name)
    return send_file(io.BytesIO(data), mimetype="application/zip", as_attachment=True,
                     download_name=filename, max_age=0)


@agents_bp.route("/skills/<name>", methods=["DELETE"])
@require_auth
@_map_agent_errors
def remove_own_skill(name: str):
    """Delete a skill the account holds, and take it off every agent's list."""
    return jsonify(agents_services.remove_own_skill(g.user, _user_dir_key(g.user), name)), 200


@agents_bp.route("/skills/imports/check", methods=["POST"])
@require_auth
@_map_agent_errors
def check_skill_import():
    """What the import review shows of an upload; nothing is kept."""
    return jsonify(agents_services.check_import(
        g.user, _user_dir_key(g.user), _upload_parts(), name=_upload_name(),
    )), 200


@agents_bp.route("/skills/imports", methods=["POST"])
@require_auth
@_map_agent_errors
def import_skill():
    """Keep an upload as the account's skill, and give it to the agents it names."""
    try:
        agents = json.loads(request.form.get("agents") or "[]")
    except ValueError:
        return _error("'agents' must be a JSON list of agents' coordinates")
    return jsonify(agents_services.import_skill(
        g.user, _user_dir_key(g.user), _upload_parts(), name=_upload_name(), agents=agents,
    )), 201


@agents_bp.route("/skills/publications", methods=["POST"])
@require_auth
@_map_agent_errors
def publish_skill():
    """Publish one of the account's own skills to the shared catalog: ``{name}``."""
    if not packages_routes_common.CURIO_ALLOW_FACTORY_CATALOG_PUBLISH:
        return packages_routes_common.catalog_publish_disabled()
    body = request.get_json(silent=True) or {}
    if not isinstance(body.get("name"), str):
        return _error("body must include 'name'")
    return jsonify(agents_services.publish_skill(g.user, _user_dir_key(g.user), body["name"])), 201


@agents_bp.route("/skills/publications/<name>", methods=["DELETE"])
@require_auth
@_map_agent_errors
def unpublish_skill(name: str):
    """Take a skill out of the shared catalog: only its publisher may."""
    if not packages_routes_common.CURIO_ALLOW_FACTORY_CATALOG_PUBLISH:
        return packages_routes_common.catalog_publish_disabled()
    return jsonify(agents_services.unpublish_skill(g.user, _user_dir_key(g.user), name)), 200


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
