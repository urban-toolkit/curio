"""The sandbox shared secret, in one place.

``main.py::set_environment_variables`` mints ``CURIO_SANDBOX_TOKEN`` per launch
and both processes inherit it; the sandbox's guarded routes (``/exec``,
``/execJs``, ``/get``, ``/install`` — see ``utk_curio/sandbox/app/auth.py``)
refuse any caller that does not present it. Every backend→sandbox call must
therefore attach :func:`sandbox_headers` — the API bridge (``api/routes.py``)
and the headless validation runner (``execution/runner.py``) alike. The
runner used to send nothing: fine under the unit suites (no token) and fatal
under ``curio start``, where every verified Solve round answered 401
(dev/115 live re-test, 2026-09-08).

Absent (a bare ``python -m backend.server``), nothing is sent and the sandbox
runs in its unauthenticated local-dev mode.
"""

from __future__ import annotations

import os

TOKEN_ENV = "CURIO_SANDBOX_TOKEN"
SANDBOX_TOKEN_HEADER = "X-Curio-Sandbox-Token"


def sandbox_token() -> str:
    """The configured secret, or ``""`` when the deployment did not set one."""
    return os.environ.get(TOKEN_ENV, "").strip()


def sandbox_headers(existing: dict | None = None) -> dict | None:
    """Merge the shared secret into a caller's headers without clobbering them.
    Returns *existing* unchanged (possibly ``None``) when no token is set."""
    token = sandbox_token()
    if not token:
        return existing
    headers = dict(existing or {})
    headers[SANDBOX_TOKEN_HEADER] = token
    return headers
