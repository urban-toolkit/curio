"""The Package Builder on the wire: capabilities, build, install, and the developer-only publish to the catalog.

Presentation layer of the packages package (memo dev/143, B4): handlers parse (``schemas.requests``),
call the use case and serialize (``schemas.responses``); every exception is mapped once by
``_map_package_errors``. Registered on ``packages_bp`` and imported by ``routes/__init__.py``.
"""

from __future__ import annotations

from flask import Response, jsonify, request

from utk_curio.backend.app.users.dependencies import require_auth
from utk_curio.backend.app.packages.application import (
    factory_install as packages_factory_install,
    publishing as packages_publishing,
)
from utk_curio.backend.app.packages.routes import common as routes_common
from utk_curio.backend.app.packages.routes.common import _map_package_errors, packages_bp, user_key
from utk_curio.backend.app.packages.routes.store import _installed_payload
from utk_curio.backend.app.packages.schemas import requests
from utk_curio.backend.app.packages.schemas.responses import package_payload


@packages_bp.route("/factory/capabilities", methods=["GET"])
@require_auth
@_map_package_errors
def factory_capabilities():
    """Which factory features are usable (controlled by deployment env)."""
    return jsonify({"catalogPublish": routes_common.CURIO_ALLOW_FACTORY_CATALOG_PUBLISH}), 200


@packages_bp.route("/factory/publish-catalog", methods=["POST"])
@require_auth
@_map_package_errors
def factory_publish_catalog():
    """Build a draft and publish into ``<repo_root>/packages/`` - **developers only**.

    Allowed by default; set ``CURIO_ALLOW_FACTORY_CATALOG_PUBLISH`` to ``0``,
    ``false``, ``no``, or ``off`` to disable. Writes the same directory layout
    Sideload installs use; may trigger hot reload of the Flask process when
    watchers observe the catalog.
    """
    if not routes_common.CURIO_ALLOW_FACTORY_CATALOG_PUBLISH:
        return routes_common.catalog_publish_disabled()
    body = dict(request.get_json(silent=True) or {})
    replace = bool(body.pop("replace", False))
    built, result, catalog_path = packages_publishing.publish_draft_to_catalog(
        user_key(), body, replace=replace,
    )
    return jsonify({
        "package": package_payload(result.manifest, package_mtime_path=catalog_path),
        "integrity": result.integrity,
        "replacedExisting": result.replaced_existing,
        "filename": built.filename,
        "catalogDir": str(catalog_path),
    }), 201


@packages_bp.route("/factory/build", methods=["POST"])
@require_auth
@_map_package_errors
def factory_build():
    """Validate a draft and return the produced ``.curio.zip`` bytes."""
    result = packages_factory_install.build_draft(user_key(), request.get_json(silent=True) or {})
    response = Response(result.archive, mimetype="application/zip")
    response.headers["Content-Disposition"] = f'attachment; filename="{result.filename}"'
    response.headers["X-Curio-Package-Dir"] = result.manifest.dir_name
    response.headers["X-Curio-Package-Version"] = result.manifest.version
    return response


@packages_bp.route("/factory/install", methods=["POST"])
@require_auth
@_map_package_errors
def factory_install():
    """Build a draft and immediately install it for the current user — the
    wizard's "Save and install", dependency step included."""
    key = user_key()
    draft = request.get_json(silent=True) or {}
    built, result = packages_factory_install.install_draft(key, draft, replace=requests.replace_flag(draft))
    return jsonify({**_installed_payload(key, result), "filename": built.filename}), 201
