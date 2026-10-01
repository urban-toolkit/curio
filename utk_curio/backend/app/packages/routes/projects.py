"""A project's package lockfile on the wire: read, install, uninstall (memo dev/101).

Presentation layer of the packages package (memo dev/143, B4): handlers parse (``schemas.requests``),
call the use case and serialize (``schemas.responses``); every exception is mapped once by
``_map_package_errors``. Registered on ``packages_bp`` and imported by ``routes/__init__.py``.
"""

from __future__ import annotations

from flask import jsonify, request

from utk_curio.backend.app.users.dependencies import require_auth
from utk_curio.backend.app.packages.application import project_packages as packages_project_packages
from utk_curio.backend.app.packages.routes.common import _map_package_errors, packages_bp, require_project, user_key
from utk_curio.backend.app.packages.schemas import requests

# The drawer in the canvas uses these; the `/catalog` page uses `/defaults`.


@packages_bp.route("/projects/<project_id>", methods=["GET"])
@require_auth
@_map_package_errors
def get_project_packages(project_id: str):
    """``{"packages": [...dirNames]}`` for the project's lockfile."""
    require_project(project_id)
    dirs = packages_project_packages.get_project_lockfile(user_key(), project_id)
    return jsonify({"packages": sorted(dirs)}), 200


@packages_bp.route("/projects/<project_id>/install", methods=["POST"])
@require_auth
@_map_package_errors
def install_to_project_route(project_id: str):
    """Install a catalog package into one project's lockfile. The payload carries
    ``importErrors``: the install itself answers whether the libraries work."""
    dir_name = requests.dir_name(request.get_json(silent=True) or {})
    require_project(project_id)
    return jsonify(packages_project_packages.install_to_project(user_key(), project_id, dir_name)), 201


@packages_bp.route("/projects/<project_id>/<dir_name>", methods=["DELETE"])
@require_auth
@_map_package_errors
def uninstall_from_project_route(project_id: str, dir_name: str):
    """Drop a package from one project's lockfile; auto-prune the user store."""
    require_project(project_id)
    return jsonify(packages_project_packages.uninstall_from_project(user_key(), project_id, dir_name)), 200
