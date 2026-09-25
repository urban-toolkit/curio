"""``/api/users/me/connection-keys`` — save, list and remove the API keys a
data-loading node reaches as ``curio_secret("<name>")`` (memo dev/116).

Responses never carry a value: the browser writes a key once through a masked
field and only ever reads back its ref (name, host, delivery, timestamps).
"""

from __future__ import annotations

from flask import Blueprint, g, jsonify, request

from utk_curio.backend.app.users.connection_keys import (
    ConnectionKeyError,
    default_store,
    storage_key_for,
    suggest_name,
)
from utk_curio.backend.app.users.dependencies import require_auth

connection_keys_bp = Blueprint(
    "connection_keys", __name__, url_prefix="/api/users/me/connection-keys"
)


@connection_keys_bp.route("/<path:path>", methods=["OPTIONS"])
@connection_keys_bp.route("/", methods=["OPTIONS"], defaults={"path": ""})
@connection_keys_bp.route("", methods=["OPTIONS"], defaults={"path": ""})
def connection_keys_preflight(path):
    return "", 204


def _error(exc: ConnectionKeyError):
    return jsonify({"error": str(exc)}), exc.status


@connection_keys_bp.route("", methods=["GET"], strict_slashes=False)
@require_auth
def list_connection_keys():
    try:
        user_key = storage_key_for(g.user)
        refs = default_store().list(user_key)
    except ConnectionKeyError as exc:
        return _error(exc)
    return jsonify({"keys": [ref.to_payload() for ref in refs]})


@connection_keys_bp.route("/suggest-name", methods=["GET"])
@require_auth
def suggest_connection_key_name():
    """A name for the form, from a host the remedy named."""
    return jsonify({"name": suggest_name(request.args.get("host", ""))})


@connection_keys_bp.route("/<name>", methods=["PUT"])
@require_auth
def put_connection_key(name: str):
    body = request.get_json(silent=True) or {}
    try:
        user_key = storage_key_for(g.user)
        ref, created = default_store().put(
            user_key,
            name,
            body.get("host"),
            body.get("value"),
            body.get("delivery", "code"),
            replace=bool(body.get("replace", False)),
        )
    except ConnectionKeyError as exc:
        return _error(exc)
    return jsonify({"key": ref.to_payload()}), (201 if created else 200)


@connection_keys_bp.route("/<name>", methods=["DELETE"])
@require_auth
def delete_connection_key(name: str):
    try:
        user_key = storage_key_for(g.user)
        removed = default_store().delete(user_key, name)
    except ConnectionKeyError as exc:
        return _error(exc)
    if not removed:
        return jsonify({"error": f"no connection key named {name!r}"}), 404
    return jsonify({"deleted": name})
