"""Dependency resolution on the wire: the resolve probe and a dataflow's declared package dependencies (check + install).

Presentation layer of the packages package (memo dev/143, B4): handlers parse (``schemas.requests``),
call the use case and serialize (``schemas.responses``); every exception is mapped once by
``_map_package_errors``. Registered on ``packages_bp`` and imported by ``routes/__init__.py``.
"""

from __future__ import annotations

from flask import jsonify, request

from utk_curio.backend.app.users.dependencies import require_auth
from utk_curio.backend.app.packages.application import (
    resolution as packages_resolution,
    workflow_deps as packages_workflow_deps,
)
from utk_curio.backend.app.packages.routes.common import _map_package_errors, packages_bp, user_key
from utk_curio.backend.app.packages.schemas import requests
from utk_curio.backend.app.packages.schemas.responses import resolve_payload


@packages_bp.route("/resolve", methods=["POST"])
@require_auth
@_map_package_errors
def resolve_deps():
    """Resolve the dep graph for a set of package directory names.

    * 200 - fully resolved; returns ``{lockfile, conflicts: []}``.
    * 409 - at least one Python (or JS) range conflict across packages;
      returns ``{lockfile, conflicts: [{package, ranges: [{packageDir, range}, ...]}, ...]}``.
    * 400 - malformed body, cycle, missing package dep.
    """
    body = request.get_json(silent=True) or {}
    result = packages_resolution.resolve_snapshot(user_key(), requests.package_names(body))
    return jsonify(resolve_payload(result)), (409 if result.conflicts else 200)


# A dataflow declares the catalog packages it depends on in its
# ``dataflow.packages`` lockfile. When the canvas loads one, the frontend
# posts that lockfile to /check to learn which declared packages aren't ready
# (not installed, or installed-but-with-a-missing-dep), warns the user, and
# auto-installs them via /install. Installing the package provisions both its
# nodes and its declared python libraries - a dataflow depends on packages,
# and the libraries follow.


@packages_bp.route("/workflow-deps/check", methods=["POST"])
@require_auth
@_map_package_errors
def check_workflow_deps():
    """Which of a dataflow's declared packages aren't ready: ``{"packages", "deferred", "broken"}``."""
    body = request.get_json(silent=True) or {}
    return jsonify(packages_workflow_deps.check_workflow_deps(user_key(), requests.declared_packages(body))), 200


@packages_bp.route("/workflow-deps/install", methods=["POST"])
@require_auth
@_map_package_errors
def install_workflow_deps():
    """Install the catalog packages a dataflow declares: ``{"installedPackages", "importErrors"}``."""
    body = request.get_json(silent=True) or {}
    return jsonify(packages_workflow_deps.install_workflow_deps(user_key(), requests.packages_to_install(body))), 200
