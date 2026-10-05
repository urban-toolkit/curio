"""What every packages route shares (memo dev/143, B4): the blueprint, the ONE
error mapping, the caller's user key and the project ownership check. The
resource modules import from here and register their handlers on
``packages_bp``; ``routes/__init__.py`` imports them.

``CURIO_ALLOW_FACTORY_CATALOG_PUBLISH`` is read from THIS module at call time
(``routes_common.CURIO_ALLOW_FACTORY_CATALOG_PUBLISH``) so the tests that
patch the operator flag patch one place and every gate sees it.
"""

from __future__ import annotations

import functools

from flask import Blueprint, Response, g, jsonify

from utk_curio.backend.app.projects import repositories as projects_repo
from utk_curio.backend.app.projects.repositories import NotFoundError
from utk_curio.backend.app.projects.services import _user_dir_key
from utk_curio.backend.config import CURIO_ALLOW_FACTORY_CATALOG_PUBLISH  # noqa: F401 — read through this module

from utk_curio.backend.app.packages.domain.errors import PackageServiceError
from utk_curio.backend.app.packages.builder.factory import FactoryError
from utk_curio.backend.app.packages.domain.package_id import PackageIdError
from utk_curio.backend.app.packages.domain.versions import ResolverError
from utk_curio.backend.app.packages.infrastructure.backend_runtime import BackendRuntimeError
from utk_curio.backend.app.packages.infrastructure.pip_runner import PipInstallError, PipSpecError
from utk_curio.backend.app.packages.repositories.archive import InstallerError

packages_bp = Blueprint("packages_api", __name__, url_prefix="/api/packages")

CATALOG_PUBLISH_DISABLED_MESSAGE = (
    "Catalog fixture publish is disabled on this server. "
    "Unset CURIO_ALLOW_FACTORY_CATALOG_PUBLISH or set it to 1, "
    "true, yes, or on to enable; restart the backend after changes."
)


def _error(message: str, status: int = 400) -> tuple[Response, int]:
    return jsonify({"error": message}), status


def _packages_error(exc: PackageServiceError):
    return jsonify({"error": str(exc)}), exc.status


def _map_package_errors(fn):
    """The ONE mapping from the layer's exceptions to JSON statuses (memo §3.2 rule 3).

    Applied BELOW ``require_auth`` so auth failures are not swallowed. A
    PackageServiceError carries its own status (the parsers in
    ``schemas.requests`` raise 400s with the body's complaint, the use cases
    their 404/409/403s); a malformed id, an archive, factory or resolver refusal
    and a malformed pip requirement are 400s with their own text; a pip failure
    is a 502 naming pip; a sandbox refusal carries the memo dev/91 status
    matrix; a project the caller does not own is "project not found" 404. Since
    B4 every handler is under it and none carries a try/except of its own — the
    two handlers whose statuses differed from this table (the archive download
    and the file server) decide theirs in ``application`` instead.
    """

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except PackageServiceError as exc:
            return _packages_error(exc)
        except (PackageIdError, InstallerError, FactoryError, ResolverError, PipSpecError) as exc:
            return _error(str(exc))
        except PipInstallError as exc:
            return _error(f"pip install failed: {exc}", 502)
        except BackendRuntimeError as exc:
            return _error(str(exc), exc.status)
        except NotFoundError:
            return _error("project not found", 404)

    return wrapper


def user_key() -> str:
    return _user_dir_key(g.user)


def require_project(project_id: str) -> None:
    """Ownership: the project must exist and belong to the caller; otherwise
    ``{"error": "project not found"}`` 404, which is what the handlers said."""
    try:
        projects_repo.get_for_user(project_id, g.user.id)
    except NotFoundError:
        raise PackageServiceError("project not found", 404) from None


def catalog_publish_disabled():
    """The 403 every developer-only catalog write answers when the operator flag is off."""
    return _error(CATALOG_PUBLISH_DISABLED_MESSAGE, 403)
