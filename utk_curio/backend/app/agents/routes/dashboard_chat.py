"""The dashboard agent on the wire: one turn that may set the dashboard's widgets and run it.

Presentation layer of the agents package. ``application/dashboard_chat.py``
holds the prompt, the reply and the checks; this handler resolves the
requester's own LLM and maps the refusals.
"""

from __future__ import annotations

from flask import g
from flask import jsonify
from flask import request

from utk_curio.backend.app.agents.application import dashboard_chat
from utk_curio.backend.app.agents.infrastructure import provider_config as agents_provider_config
from utk_curio.backend.app.agents.routes.common import _error
from utk_curio.backend.app.agents.routes.common import _map_agent_errors
from utk_curio.backend.app.agents.routes.common import agents_bp
from utk_curio.backend.app.projects.services import _user_dir_key
from utk_curio.backend.app.users.dependencies import require_auth


@agents_bp.route("/dashboard-chat", methods=["POST"])
@require_auth
@_map_agent_errors
def dashboard_chat_turn():
    """``{message, history?, controls, scenarios?, canRun?}`` → ``{reply,
    changes: [{id, value}], rejected: [{id, problem}], run, needsClarification}``.
    With no LLM configuration for this account, a 400 whose remedy opens API Settings."""

    user_key = _user_dir_key(g.user)
    config = dashboard_chat.resolve_config(user_key, guest=bool(getattr(g.user, "is_guest", False)))
    try:
        answer = dashboard_chat.respond(user_key, config, request.get_json(silent=True))
    except dashboard_chat.DashboardChatError as exc:
        return _error(str(exc), 400)
    except Exception as exc:  # noqa: BLE001 - a provider failure is the model's, not the request's
        return _error(
            "The LLM did not answer: " + agents_provider_config.redact_error(exc, config), 502
        )
    return jsonify(answer), 200
