"""The account's always-installed set on the wire: read, install, detach.

Presentation layer of the packages package (memo dev/143, B4): handlers parse (``schemas.requests``),
call the use case and serialize (``schemas.responses``); every exception is mapped once by
``_map_package_errors``. Registered on ``packages_bp`` and imported by ``routes/__init__.py``.
"""

from __future__ import annotations

from flask import g, jsonify, request

from utk_curio.backend.app.users.dependencies import require_auth
from utk_curio.backend.app.packages.application import (
    defaults_install as packages_defaults_install,
    seeding as packages_seeding,
)
from utk_curio.backend.app.packages.repositories import defaults as defaults_io
from utk_curio.backend.app.packages.routes.common import _map_package_errors, packages_bp, user_key
from utk_curio.backend.app.packages.schemas import requests

# There is deliberately no `DELETE /defaults/<dir>` that touches projects — the
# only way a package leaves every lockfile is `prune_unreferenced_packages`,
# which fires when the last project drops a dep.


@packages_bp.route("/defaults", methods=["GET"])
@require_auth
@_map_package_errors
def get_defaults_route():
    """``{"packages": [...dirNames]}`` for the user's defaults list."""
    key = user_key()
    # /catalog fetches `/api/packages/defaults` in parallel with `/catalog` and
    # `/api/packages`. If this endpoint resolves before either of those has
    # seeded the user, the page renders with an empty defaults set and the
    # built-in package shows as "available but not installed" until the next
    # refresh. Seed eagerly here too - idempotent on the seeded path.
    packages_seeding.ensure_user_seeded(key)
    return jsonify({"packages": sorted(defaults_io.load_defaults(key))}), 200


@packages_bp.route("/defaults/<path:dir_name>", methods=["DELETE"])
@require_auth
@_map_package_errors
def uninstall_from_defaults_route(dir_name: str):
    """Stop seeding a package into new projects — detach only; existing
    projects and the user store are untouched."""
    return jsonify(packages_defaults_install.uninstall_from_defaults(g.user, dir_name)), 200


@packages_bp.route("/defaults", methods=["POST"])
@require_auth
@_map_package_errors
def install_to_defaults_route():
    """Install a catalog package for every existing project + future ones."""
    dir_name = requests.dir_name(request.get_json(silent=True) or {})
    return jsonify(packages_defaults_install.install_to_defaults(g.user, dir_name)), 201
