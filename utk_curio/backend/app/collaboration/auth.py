"""Bearer-token handshake for Socket.IO connections.

Identity is anchored in the existing ``UserSession`` table — never in
client-supplied payload fields. ``authenticate_handshake`` is the only
entry point; every event handler downstream reads its (user_id, username,
name, profile_image) from the per-sid session that this function stashes.
"""

from __future__ import annotations

from typing import Optional, Tuple

from flask import current_app
from flask_socketio import ConnectionRefusedError

from utk_curio.backend.app.users import repositories as repo
from utk_curio.backend.app.users.models import User, UserSession


def _extract_token(auth, environ) -> Optional[str]:
    """Return the Bearer token from any of the three accepted carriers.

    Preference order is the same one socket.io-client surfaces by default:
    the ``auth`` dict (preferred), then the HTTP ``Authorization`` header,
    then a ``?token=`` query string parameter (last-resort, for embeds).
    """
    if isinstance(auth, dict):
        tok = auth.get("token")
        if isinstance(tok, str) and tok.strip():
            return tok.strip()
    header = (environ or {}).get("HTTP_AUTHORIZATION", "") or ""
    if header.startswith("Bearer "):
        return header[7:].strip() or None
    if header.strip():
        return header.strip()
    qs = (environ or {}).get("QUERY_STRING", "") or ""
    for part in qs.split("&"):
        if part.startswith("token="):
            value = part[len("token="):]
            return value or None
    return None


def authenticate_handshake(auth, environ) -> Tuple[UserSession, User]:
    """Resolve a connecting socket to a (session, user) pair.

    Raises :class:`flask_socketio.ConnectionRefusedError` with a short
    reason on any failure; flask-socketio surfaces that as a clean
    rejection to the client.
    """
    token = _extract_token(auth, environ)
    if not token:
        raise ConnectionRefusedError("unauthorized: missing token")
    session = repo.session_by_token(token)
    if not session or session.is_expired:
        raise ConnectionRefusedError("unauthorized: invalid or expired session")
    user = repo.user_by_id(session.user_id)
    if not user:
        raise ConnectionRefusedError("unauthorized: user not found")
    try:
        repo.touch_session(session)
    except Exception:  # noqa: BLE001 — touch failure must not deny access
        current_app.logger.warning(
            "touch_session failed during socket handshake", exc_info=True,
        )
    return session, user
