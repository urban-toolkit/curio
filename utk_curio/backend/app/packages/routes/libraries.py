"""The per-user standalone libraries on the wire: list (with package-declared ones), add, remove.

Presentation layer of the packages package (memo dev/143, B4): handlers parse (``schemas.requests``),
call the use case and serialize (``schemas.responses``); every exception is mapped once by
``_map_package_errors``. Registered on ``packages_bp`` and imported by ``routes/__init__.py``.
"""

from __future__ import annotations

from flask import g, jsonify, request

from utk_curio.backend.app.users.capabilities import library_install_refusal
from utk_curio.backend.app.users.dependencies import require_auth
from utk_curio.backend.app.packages.application import (
    libraries as packages_libraries,
    seeding as packages_seeding,
)
from utk_curio.backend.app.packages.routes.common import _error, _map_package_errors, packages_bp, user_key
from utk_curio.backend.app.packages.schemas import requests
from utk_curio.backend.app.packages.schemas.responses import libraries_payload


@packages_bp.route("/libraries", methods=["GET"])
@require_auth
@_map_package_errors
def list_libraries_route():
    """The user's standalone library list plus every library a currently-installed
    node package declares — one flat list with a ``source`` column."""
    key = user_key()
    packages_seeding.ensure_user_seeded(key)
    return jsonify(libraries_payload(packages_libraries.aggregate(key), library_install_refusal(g.user))), 200


def _library_install_refused():
    """The 403 for a caller who may not change a node environment, or None."""
    refusal = library_install_refusal(g.user)
    if refusal is None:
        return None
    return jsonify({"error": refusal, "code": "library_install_disabled"}), 403


@packages_bp.route("/libraries", methods=["POST"])
@require_auth
@_map_package_errors
def add_library_route():
    """Append a standalone library to the user's list and pip-install it.
    Body: ``{"kind": "python"|"js", "spec": "<name><version>"}``."""
    kind, spec = requests.library_spec(request.get_json(silent=True) or {})
    if kind == "js":
        # No JS install runner yet - the modal will still accept the
        # entry as a declaration, but won't actually `npm install`. This
        # keeps the data path consistent for a future js_runner module.
        return _error("JS library install is not yet supported; declare in a node package's manifest instead", 501)
    refused = _library_install_refused()
    if refused:
        return refused
    return jsonify(packages_libraries.add_standalone_library(user_key(), kind, spec)), 201


@packages_bp.route("/libraries/<kind>/<path:spec>", methods=["DELETE"])
@require_auth
@_map_package_errors
def remove_library_route(kind: str, spec: str):
    """Drop a standalone library and pip-uninstall it unless an installed package still declares it."""
    requests.library_kind(kind)
    if kind == "js":
        return _error("JS library uninstall is not yet supported", 501)
    refused = _library_install_refused()
    if refused:
        return refused
    return jsonify(packages_libraries.remove_standalone_library(user_key(), kind, spec)), 200
