"""What every agents route shares: the blueprint, the one error mapping, the shared helpers.

Presentation layer of the agents package (memo dev/142, B4-1; re-derived on enh/agent-catalog): the handlers
of ``routes.py`` by resource, bodies verbatim, registered on the one ``agents_bp`` from ``routes/common.py``.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass
from flask import Blueprint
from flask import g
from flask import jsonify

from utk_curio.backend.app.agents import service as agents_services
from utk_curio.backend.app.agents.infrastructure.provider_config import ProviderConfigError
from utk_curio.backend.app.agents.service import AgentServiceError
from utk_curio.backend.app.agents.infrastructure import provider_config as agents_provider_config
from utk_curio.backend.app.projects import access
from utk_curio.backend.app.projects import visitor_copies
from utk_curio.backend.app.projects.models import Project
from utk_curio.backend.app.projects.repositories import NotFoundError
from utk_curio.backend.app.projects.services import _owner_user_dir_key
from utk_curio.backend.extensions import db


agents_bp = Blueprint("agents_api", __name__, url_prefix="/api/agents")


def _error(message: str, status: int = 400):
    return jsonify({"error": message}), status


@dataclass(frozen=True)
class Dataflow:
    """The dataflow a request's agents work on, and who drives them."""

    #: The dataflow the agents work on: the one the route names, or a hosted
    #: guest's own copy of it (``projects/visitor_copies.py``).
    project_id: str
    #: Its owner's storage key: where the dataflow, its attachments and their
    #: chats are kept, and whose models, settings and skills its agents run on.
    key: str
    #: ``owner`` or ``editor`` (``access.agents_role``).
    role: str
    #: Its owner by name, as what waits for the owner says.
    owner_name: str
    #: Whether its owner is a guest, for the LLM configuration that answers.
    guest: bool

    @property
    def editor(self) -> bool:
        """An editor the owner invited drives the agents."""
        return self.role == access.EDITOR


def _dataflow(project_id: str, *, make: bool = True) -> Dataflow:
    """The dataflow *project_id* names, for the request's account to drive
    its agents: its owner, a hosted guest on the examples the guest account
    owns among them, or an editor the owner invited (``access.agents_role``).
    Anyone else is refused with a 403, a hosted guest on another account's
    dataflow among them, and a dataflow that does not exist is not found. A
    hosted guest's agents work on its own copy of the dataflow, made when
    *make* and there is none: a route that writes makes it, one that only
    reads does not."""
    project = db.session.get(Project, project_id)
    if project is None:
        raise NotFoundError(f"Project {project_id} not found")
    role = access.agents_role(g.user, project)
    if role not in access.EDIT_ROLES:
        raise AgentServiceError(access.AGENTS_WATCHER_REFUSAL, 403)
    owner = project.owner
    return Dataflow(
        project_id=visitor_copies.for_request(g.user, project_id, make=make),
        key=_owner_user_dir_key(project),
        role=role,
        owner_name=(owner.name or owner.username) if owner is not None else "the owner",
        guest=bool(getattr(owner, "is_guest", False)),
    )


def _driven_dataflow_key(project_id: str | None) -> str | None:
    """The storage key of the dataflow *project_id* names, its owner's, when
    the request's account drives its agents; None when no dataflow is named,
    or for one the account does not drive. A listing that marks what is in a
    dataflow reads it there."""
    if not project_id:
        return None
    try:
        return _dataflow(project_id, make=False).key
    except (NotFoundError, AgentServiceError):
        return None


def _provider_error(exc: ProviderConfigError):
    """No LLM configuration answers: a 400 whose remedy opens API Settings."""
    return jsonify({"error": str(exc), "remedy": exc.remedy}), 400


def _llm_for_attachment(flow: Dataflow, attachment_id: str):
    """The LLM configuration a run of this attachment's agent answers with:
    the one the dataflow owner's API Settings give the agent, whoever drives
    it."""

    return agents_provider_config.resolve_llm(
        flow.key, agents_services.attachment_agent_id(flow.key, flow.project_id, attachment_id),
        guest=flow.guest,
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
