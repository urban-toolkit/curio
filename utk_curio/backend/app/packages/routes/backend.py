"""The package backend sandbox on the wire: one declared handler invocation (memo dev/91).

Presentation layer of the packages package (memo dev/143, B4): handlers parse (``schemas.requests``),
call the use case and serialize (``schemas.responses``); every exception is mapped once by
``_map_package_errors``. Registered on ``packages_bp`` and imported by ``routes/__init__.py``.
"""

from __future__ import annotations

from flask import jsonify, request

from utk_curio.backend.app.users.dependencies import require_auth
from utk_curio.backend.app.packages.application import backend_invoke as packages_backend_invoke
from utk_curio.backend.app.packages.routes.common import _map_package_errors, packages_bp, user_key
from utk_curio.backend.app.packages.schemas import requests


@packages_bp.route("/<dir_name>/backend/<handler>", methods=["POST"])
@require_auth
@_map_package_errors
def invoke_package_backend(dir_name: str, handler: str):
    """Invoke one declared backend handler (memo dev/91 §3) — the ONLY caller
    surface for package server code. Body: ``{"payload": <JSON>}``.

    The memo's §6 status matrix: 404 unknown package/backend/handler, 403 is
    impossible here by construction (an undeclared-permission backend cannot
    install — the manifest loader refuses it), 409 digest drift, 413/422
    payload bounds, 503 no worker slot, 507 data dir over cap, 502 honest
    sanitized worker/contract failure. A well-formed ``ok: false`` reply
    (handler-error) returns 200 — the envelope IS the diagnosis."""
    payload = requests.invoke_payload(request.content_length, request.get_json(silent=True))
    return jsonify(packages_backend_invoke.invoke_backend_handler(user_key(), dir_name, handler, payload)), 200
