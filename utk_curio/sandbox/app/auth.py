"""Shared-secret authentication for the sandbox HTTP API.

The sandbox executes arbitrary user code. Every route that can run code, install
packages, or read artifacts must therefore prove the caller is Curio's own
backend and not something else that reached the port.

The secret is generated once per launch by ``utk_curio/main.py``
(``set_environment_variables``) and handed to the backend and the sandbox
through ``CURIO_SANDBOX_TOKEN``. The backend attaches it in ``_sandbox_call``;
here we check it.

Three deliberate choices:

- **Unset means allow.** The sandbox is importable on its own (``app.test_client()``
  in the unit suites, a bare ``python -m sandbox.server`` while debugging), and
  those callers have no launcher to mint a token. An absent variable logs once
  and permits.
- **Except when hosted.** That convenience must never reach production, so
  ``require_startup_token`` refuses to boot when the launcher put this instance
  in a multi-user posture (``--auth`` / ``--deploy``, i.e. ``CURIO_NO_AUTH=0``)
  without a token.
- **JSON, not ``abort(401)``.** Flask's default 401 is an HTML page, which the
  backend would surface to the browser as "sandbox returned non-JSON" plus a
  500. A JSON body lets ``_sandbox_call`` report the real cause.
"""

import hmac
import os
import sys
from functools import wraps

from flask import jsonify, request

TOKEN_ENV = "CURIO_SANDBOX_TOKEN"
TOKEN_HEADER = "X-Curio-Sandbox-Token"

_warned = False


def hosted_mode() -> bool:
    """True when the launcher enabled user auth (``--auth`` or ``--deploy``).

    ``main.py::set_environment_variables`` writes ``CURIO_NO_AUTH=0`` for both,
    and the sandbox inherits it. Absent means a plain local launch.
    """
    return os.environ.get("CURIO_NO_AUTH", "1").strip().lower() in ("0", "false", "no", "off")


def get_expected_token():
    """The configured secret, or None when the deployment did not set one."""
    return os.environ.get(TOKEN_ENV, "").strip() or None


def require_startup_token() -> None:
    """Abort startup if a hosted instance has no sandbox token configured.

    Called from ``sandbox/server.py`` at boot rather than at import time, so
    unit suites that build the app with ``app.test_client()`` are unaffected.
    """
    if hosted_mode() and get_expected_token() is None:
        raise RuntimeError(
            f"{TOKEN_ENV} is not set but this instance runs with user auth "
            "enabled (--auth / --deploy). The sandbox executes arbitrary user "
            "code and refuses to start unguarded. Launch through "
            "'curio start', which generates the token, or set "
            f"{TOKEN_ENV} yourself on both the backend and the sandbox."
        )


def _warn_once() -> None:
    global _warned
    if _warned:
        return
    _warned = True
    print(
        f"[sandbox auth] {TOKEN_ENV} is not set - code execution routes are "
        "UNAUTHENTICATED. This is intended only for local development and the "
        "unit suites; a hosted instance refuses to start in this state.",
        file=sys.stderr,
        flush=True,
    )


def _unauthorized(reason: str):
    return jsonify({
        "error": "sandbox_unauthorized",
        "message": (
            "The sandbox rejected this request: " + reason + ". The caller must "
            f"present the shared secret in the {TOKEN_HEADER} header."
        ),
    }), 401


def require_sandbox_token(view):
    """Reject callers that cannot present the shared secret.

    Compared with :func:`hmac.compare_digest`, which is both constant-time and
    length-safe, so a wrong-length token is rejected like any other mismatch
    rather than raising.
    """

    @wraps(view)
    def wrapper(*args, **kwargs):
        expected = get_expected_token()
        if expected is None:
            _warn_once()
            return view(*args, **kwargs)

        presented = request.headers.get(TOKEN_HEADER, "")
        if not presented:
            return _unauthorized("no token was presented")
        if not hmac.compare_digest(presented, expected):
            return _unauthorized("the presented token did not match")
        return view(*args, **kwargs)

    return wrapper
