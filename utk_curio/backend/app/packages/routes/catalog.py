"""The shared catalog on the wire: the catalog scan, install-from-catalog, and the developer-only unpublish.

Presentation layer of the packages package (memo dev/143, B4): handlers parse (``schemas.requests``),
call the use case and serialize (``schemas.responses``); every exception is mapped once by
``_map_package_errors``. Registered on ``packages_bp`` and imported by ``routes/__init__.py``.
"""

from __future__ import annotations

from flask import jsonify, request

from utk_curio.backend.app.users.dependencies import require_auth
from utk_curio.backend.app.packages.application import (
    catalog as packages_catalog,
    publishing as packages_publishing,
    seeding as packages_seeding,
    store_install as packages_store_install,
)
from utk_curio.backend.app.packages.routes import common as routes_common
from utk_curio.backend.app.packages.routes.common import _map_package_errors, packages_bp, user_key
from utk_curio.backend.app.packages.routes.store import _installed_payload
from utk_curio.backend.app.packages.schemas import requests


@packages_bp.route("/catalog", methods=["GET"])
@require_auth
@_map_package_errors
def list_catalog_packages():
    """The catalog scan from ``<repo_root>/packages/``: rows in the installed-list
    shape plus ``installed`` and ``publishable``, with ``families`` and
    ``catalogCollisions``."""
    key = user_key()
    packages_seeding.ensure_user_seeded(key)
    return jsonify(packages_catalog.catalog_listing(key)), 200


@packages_bp.route("/catalog/install", methods=["POST"])
@require_auth
@_map_package_errors
def install_from_catalog():
    """Install a catalog package by ``dirName`` — the drawer's "Reload from catalog";
    its declared python deps are installed and probed as well."""
    key = user_key()
    body = request.get_json(silent=True) or {}
    result = packages_store_install.install_from_catalog(
        key, requests.catalog_dir_name(body), replace=requests.replace_flag(body),
    )
    return jsonify(_installed_payload(key, result)), 201


@packages_bp.route("/catalog/<dir_name>", methods=["DELETE"])
@require_auth
@_map_package_errors
def unpublish_from_catalog(dir_name: str):
    """Remove a package directory from ``<repo_root>/packages/`` (developer catalog only).

    Does **not** uninstall from the user's package store - use
    ``DELETE /api/packages/<dir_name>`` for that. Gated by the same env flag as
    ``factory/publish-catalog``; only the publisher may withdraw it.
    """
    if not routes_common.CURIO_ALLOW_FACTORY_CATALOG_PUBLISH:
        return routes_common.catalog_publish_disabled()
    packages_publishing.unpublish_from_catalog(dir_name=dir_name, user_key=user_key())
    return "", 204
