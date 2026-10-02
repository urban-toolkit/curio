"""What every agents route shares: the blueprint, the one error mapping, the shared helpers.

Presentation layer of the agents package (memo dev/142, B4-1; re-derived on enh/agent-catalog): the handlers
of ``routes.py`` by resource, bodies verbatim, registered on the one ``agents_bp`` from ``routes/common.py``.
"""

from __future__ import annotations

import functools
from flask import Blueprint
from flask import g
from flask import jsonify

from utk_curio.backend.app.agents import service as agents_services
from utk_curio.backend.app.agents.infrastructure.provider_config import ProviderConfigError
from utk_curio.backend.app.agents.service import AgentServiceError
from utk_curio.backend.app.agents.infrastructure import provider_config as agents_provider_config
from utk_curio.backend.app.projects.repositories import NotFoundError
from utk_curio.backend.app.projects.services import _user_dir_key


agents_bp = Blueprint("agents_api", __name__, url_prefix="/api/agents")


def _error(message: str, status: int = 400):
    return jsonify({"error": message}), status


def _provider_error(exc: ProviderConfigError):
    """No LLM configuration answers: a 400 whose remedy opens API Settings."""
    return jsonify({"error": str(exc), "remedy": exc.remedy}), 400


def _llm_for_attachment(project_id: str, attachment_id: str):
    """The LLM configuration a run of this attachment's agent answers with."""

    user_key = _user_dir_key(g.user)
    return agents_provider_config.resolve_llm(
        user_key, agents_services.attachment_agent_id(user_key, project_id, attachment_id),
        guest=bool(getattr(g.user, "is_guest", False)),
    )


def _svc_error(exc: AgentServiceError):
    """One place decides what an AgentServiceError looks like on the wire.

    Kept as the explicit form the handlers already call so the mapping has a
    single definition without rewriting 32 call sites; :func:`_map_agent_errors`
    below reuses it for anything that escapes a handler.
    """
    return _error(str(exc), getattr(exc, "status", 400))


def _map_agent_errors(fn):
    """Catch the service-layer exceptions a handler does not catch itself.

    The Data Catalog's ``datasets/routes.py::_map_catalog_errors`` is the model:
    applied BELOW ``require_auth`` so auth failures are not swallowed, mapping
    a missing dataflow to 404 and an unconfigured provider to a 400 that names
    API Settings.

    Deliberately additive rather than a replacement for the per-handler
    ``try/except AgentServiceError``. Those 32 blocks work and are covered;
    collapsing them into this decorator is a mechanical dedent across handlers
    with differing shapes (several carry a second ``except``), which is churn
    this phase does not need. The decorator still gives one place to add a new
    mapping, and it widens the guard to a handler's prelude and tail, which the
    inner ``try`` never covered.
    """

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except AgentServiceError as exc:
            return _svc_error(exc)
        except ProviderConfigError as exc:
            # Curio ships no built-in provider; say where to configure one
            # rather than surfacing a bare 500 from deep in a provider SDK.
            return _provider_error(exc)
        except NotFoundError:
            return _error("Dataflow not found", 404)

    return wrapper
