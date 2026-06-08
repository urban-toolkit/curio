"""Auth blueprint: /api/auth/* endpoints and /api/config/public."""

from __future__ import annotations

import os

from flask import Blueprint, g, jsonify, request

from utk_curio.backend.config import (
    ALLOW_GUEST_LOGIN,
    CURIO_NO_AUTH,
    CURIO_NO_PROJECT,
    CURIO_DEFAULT_SAVE_NODE_OUTPUT,
    CURIO_ENV,
    CURIO_SHARED_GUEST_USERNAME,
    ENABLE_COLLAB,
)
from utk_curio.backend.app.users.dependencies import get_current_token, require_auth
from utk_curio.backend.app.users.schemas import SignInIn, SignUpIn, UserPatchIn
from utk_curio.backend.app.users.services import (
    AuthError,
    get_me,
    patch_me,
    signin_shared_guest,
    signin_google,
    signin_guest,
    signin_password,
    signout,
    signup,
)
from utk_curio.backend.app.users import rate_limit

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")
config_bp = Blueprint("config_public", __name__, url_prefix="/api/config")


@auth_bp.route("/<path:path>", methods=["OPTIONS"])
@auth_bp.route("/", methods=["OPTIONS"], defaults={"path": ""})
def auth_preflight(path):
    return "", 204


@config_bp.route("/<path:path>", methods=["OPTIONS"])
@config_bp.route("/", methods=["OPTIONS"], defaults={"path": ""})
def config_preflight(path):
    return "", 204


def _ip() -> str:
    return request.remote_addr or "0.0.0.0"


def _auth_disabled_response():
    return jsonify({"error": "User auth is disabled."}), 403


@auth_bp.route("/signup", methods=["POST"])
def signup_route():
    if CURIO_NO_AUTH:
        return _auth_disabled_response()
    body = request.get_json(silent=True) or {}
    data = SignUpIn(
        name=body.get("name", ""),
        username=body.get("username", ""),
        password=body.get("password", ""),
        email=body.get("email"),
    )
    try:
        result = signup(data)
        return jsonify(result.to_dict()), 201
    except AuthError as e:
        return jsonify({"error": e.message}), e.status


@auth_bp.route("/signin", methods=["POST"])
def signin_route():
    if CURIO_NO_AUTH:
        return _auth_disabled_response()
    body = request.get_json(silent=True) or {}
    identifier = body.get("identifier", "")
    password = body.get("password", "")

    if not rate_limit.can_attempt(_ip(), identifier):
        return jsonify({"error": "Too many attempts. Try again later."}), 429

    data = SignInIn(identifier=identifier, password=password)
    try:
        result = signin_password(data)
        rate_limit.record_attempt(_ip(), identifier, success=True)
        return jsonify(result.to_dict()), 200
    except AuthError as e:
        rate_limit.record_attempt(_ip(), identifier, success=False)
        return jsonify({"error": e.message}), e.status


@auth_bp.route("/signin/google", methods=["POST"])
def signin_google_route():
    if CURIO_NO_AUTH:
        return _auth_disabled_response()
    body = request.get_json(silent=True) or {}
    code = body.get("code", "")
    if not code:
        return jsonify({"error": "Authorization code is required."}), 400
    try:
        result = signin_google(code)
        return jsonify(result.to_dict()), 200
    except AuthError as e:
        return jsonify({"error": e.message}), e.status


@auth_bp.route("/signin/guest", methods=["POST"])
def signin_guest_route():
    if CURIO_NO_AUTH:
        return _auth_disabled_response()
    try:
        result = signin_guest(
            ALLOW_GUEST_LOGIN, existing_token=get_current_token()
        )
        return jsonify(result.to_dict()), 200
    except AuthError as e:
        return jsonify({"error": e.message}), e.status


@auth_bp.route("/signin/auto-guest", methods=["POST"])
def signin_auto_guest_route():
    if not CURIO_NO_AUTH:
        return jsonify({"error": "Auto guest signin is unavailable."}), 403
    try:
        result = signin_shared_guest(existing_token=get_current_token())
        return jsonify(result.to_dict()), 200
    except AuthError as e:
        return jsonify({"error": e.message}), e.status


@auth_bp.route("/signout", methods=["POST"])
@require_auth
def signout_route():
    if CURIO_NO_AUTH:
        return jsonify({"error": "Sign out is disabled while user auth is off."}), 403
    auth_header = request.headers.get("Authorization", "")
    token = auth_header[7:] if auth_header.startswith("Bearer ") else auth_header
    signout(token)
    return jsonify({"message": "Signed out."}), 200


@auth_bp.route("/me", methods=["GET"])
@require_auth
def me_get_route():
    user_out = get_me(g.user)
    return jsonify(user_out.to_dict()), 200


@auth_bp.route("/me", methods=["PATCH"])
@require_auth
def me_patch_route():
    body = request.get_json(silent=True) or {}
    data = UserPatchIn(
        name=body.get("name"),
        email=body.get("email"),
        type=body.get("type"),
        llm_api_type=body.get("llm_api_type"),
        llm_base_url=body.get("llm_base_url"),
        llm_api_key=body.get("llm_api_key"),
        llm_model=body.get("llm_model"),
    )
    try:
        user_out = patch_me(g.user, data)
        return jsonify(user_out.to_dict()), 200
    except AuthError as e:
        return jsonify({"error": e.message}), e.status


@config_bp.route("/public", methods=["GET"])
def public_config_route():
    return jsonify(
        {
            "allow_guest_login": ALLOW_GUEST_LOGIN,
            "curio_no_auth": CURIO_NO_AUTH,
            "curio_no_project": CURIO_NO_PROJECT,
            "skip_project_page": CURIO_NO_PROJECT,
            "google_client_id": os.environ.get("CLIENT_ID", ""),
            "curio_env": CURIO_ENV,
            "shared_guest_username": CURIO_SHARED_GUEST_USERNAME,
            "enable_collab": ENABLE_COLLAB,
            "default_save_node_output": CURIO_DEFAULT_SAVE_NODE_OUTPUT,
        }
    ), 200
