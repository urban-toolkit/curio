"""The browser's view of a collection's files.

``GET /api/datasets/<id>/media/<file_id>`` serves a thumbnail, a video's
poster or the file itself to a signed-in caller, who fetches it with their
token (the way Simple View already fetches every ``/api/`` image).
``<video>`` and ``<audio>`` cannot send a token, so
``POST .../link`` hands back a short-lived signed URL for one file, and
``GET /api/media/<token>`` serves it, with Range, to whoever holds it.
"""

from __future__ import annotations

from flask import Blueprint, g, jsonify, request, send_file, url_for

from utk_curio.backend.app.datalakes.application import media
from utk_curio.backend.app.datalakes.routes import _map_lake_errors, _service
from utk_curio.backend.app.users.dependencies import require_auth

media_bp = Blueprint("collection_media", __name__, url_prefix="/api")

_VARIANTS = ("thumb", "poster", "original")


def _served(path, mimetype: str, *, cache_seconds: int = 3600):
    response = send_file(path, mimetype=mimetype, conditional=True, max_age=cache_seconds)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Content-Disposition"] = "inline"
    response.headers["Cross-Origin-Resource-Policy"] = "same-site"
    return response


def _serve(service, dataset_id: str, file_id: str, variant: str):
    found = media.locate(service, dataset_id, file_id)
    if variant == "original":
        path, mimetype = media.original(found)
        return _served(path, mimetype)
    return _served(media.thumbnail(service, found, variant=variant), "image/jpeg")


@media_bp.route("/datasets/<dataset_id>/media/<file_id>", methods=["GET"])
@require_auth
@_map_lake_errors
def collection_media(dataset_id: str, file_id: str):
    variant = request.args.get("variant") or "thumb"
    if variant not in _VARIANTS:
        return jsonify({"error": f"variant must be one of {', '.join(_VARIANTS)}"}), 400
    return _serve(_service(), dataset_id, file_id, variant)


@media_bp.route("/datasets/<dataset_id>/media/<file_id>/link", methods=["POST"])
@require_auth
@_map_lake_errors
def collection_media_link(dataset_id: str, file_id: str):
    """A URL a ``<video>`` or ``<audio>`` element can play, valid for ten minutes."""
    service = _service()
    media.original(media.locate(service, dataset_id, file_id))
    user = getattr(g, "user", None)
    token = media.sign(getattr(user, "id", None), service.user_key, dataset_id, file_id)
    return jsonify({
        "url": url_for("collection_media.signed_media", token=token),
        "expiresIn": media.LINK_TTL_SECONDS,
    }), 200


@media_bp.route("/media/<token>", methods=["GET"])
@_map_lake_errors
def signed_media(token: str):
    """One file, to whoever holds a link minted by its owner in the last ten minutes."""
    from utk_curio.backend.app.datalakes.service import DataLakeService, _user_by_id

    claims = media.verify(token)
    user = _user_by_id(claims.get("u")) if claims.get("u") is not None else None
    service = DataLakeService(claims["k"], user=user)
    found = media.locate(service, claims["d"], claims["f"])
    path, mimetype = media.original(found)
    return _served(path, mimetype, cache_seconds=0)
