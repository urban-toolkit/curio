"""Where the repo and the stack's state live, the stack's flags and public
config, the tests that need a mode, and the debug log.
"""

import os
import json
import time
from urllib.request import urlopen, Request
from urllib.error import URLError

import pytest


# Repo root is 5 levels up: utils -> test_frontend -> tests -> backend -> utk_curio -> curio-main
REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "..")
)


def state_root() -> str:
    """``.curio/`` for this stack -- ``CURIO_STATE_DIR`` when set.

    Per-shard under xdist (backend/tests/shards.py), so the Playwright scratch
    artifacts below never interleave across workers. Mirrors
    ``user_storage.curio_root`` minus the ``/test`` suffix.
    """
    return os.environ.get("CURIO_STATE_DIR") or os.path.join(REPO_ROOT, ".curio")

_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}


def env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in _TRUE_VALUES:
        return True
    if value in _FALSE_VALUES:
        return False
    return default


def _backend_base_url_for_config() -> str:
    """Resolve the backend URL for fetching ``/api/config/public``.

    When attaching to an already-running stack (``CURIO_E2E_USE_EXISTING=1``)
    or running the fixture-spawned subprocess, the backend's actual state
    is the single source of truth for the auth/guest/project flags — the
    pytest process env alone cannot reproduce it, because the ``curio start``
    subprocess overrides these vars from its CLI flags.
    """
    host = os.environ.get("CURIO_E2E_HOST", "localhost")
    port = os.environ.get("CURIO_E2E_BACKEND_PORT") or os.environ.get(
        "BACKEND_PORT", "5002"
    )
    return f"http://{host}:{port}"


_PUBLIC_CONFIG_CACHE: dict | None = None


def _fetch_public_config() -> dict | None:
    """Return the cached ``/api/config/public`` body, or ``None`` if offline.

    Result is memoised for the pytest session because a Curio backend does
    not change its auth flags at runtime (they're read from the process env
    at import time). Callers treat ``None`` as "backend unreachable, fall
    back to env inspection".
    """
    global _PUBLIC_CONFIG_CACHE
    if _PUBLIC_CONFIG_CACHE is not None:
        return _PUBLIC_CONFIG_CACHE
    url = f"{_backend_base_url_for_config()}/api/config/public"
    try:
        req = Request(url, method="GET")
        with urlopen(req, timeout=5) as resp:
            if resp.getcode() != 200:
                return None
            body = resp.read().decode("utf-8") or "{}"
            _PUBLIC_CONFIG_CACHE = json.loads(body)
            return _PUBLIC_CONFIG_CACHE
    except (URLError, OSError, ValueError):
        return None


def auth_enabled_env() -> bool:
    """True when the running backend has user auth enabled.

    Prefers the live backend's ``/api/config/public`` response so the pytest
    process never disagrees with the backend subprocess (whose ``CURIO_NO_AUTH``
    is set by ``curio.py start`` CLI flags, not inherited from pytest env).
    Falls back to env vars when the backend is not yet reachable (e.g. fixture
    setup phase before the port is bound).
    """
    cfg = _fetch_public_config()
    if cfg is not None:
        if cfg.get("curio_no_project") or cfg.get("skip_project_page"):
            return False
        return not bool(cfg.get("curio_no_auth"))
    if env_flag("CURIO_NO_PROJECT", False):
        return False
    return not env_flag("CURIO_NO_AUTH", False)


def allow_guest_login_env() -> bool:
    """True when guest login is enabled on the running backend.

    Like :func:`auth_enabled_env`, prefers the live ``/api/config/public``
    response and only falls back to pytest-process env vars when the backend
    is unreachable.
    """
    cfg = _fetch_public_config()
    if cfg is not None:
        return bool(cfg.get("allow_guest_login"))
    if "ALLOW_GUEST_LOGIN" in os.environ:
        return env_flag("ALLOW_GUEST_LOGIN", False)
    return os.environ.get("CURIO_ENV", "dev") != "prod"


def skip_project_page_env() -> bool:
    """True when the running backend hides the ``/projects`` page.

    Mirrors :func:`auth_enabled_env`: prefer the live backend's view (via
    ``/api/config/public``) over pytest-process env inspection, since the
    ``curio start`` subprocess sets ``CURIO_NO_PROJECT`` from its CLI flags
    and pytest does not inherit that.
    """
    cfg = _fetch_public_config()
    if cfg is not None:
        return bool(cfg.get("skip_project_page") or cfg.get("curio_no_project"))
    return env_flag("CURIO_NO_PROJECT", False)


def require_user_auth() -> None:
    if not auth_enabled_env():
        pytest.skip("This test requires CURIO_NO_AUTH=0")


def require_project_page() -> None:
    """Skip the current test when Curio is running in ``--no-project`` mode.

    Tests that drive the ``/projects`` list page or the per-user save/load
    File-menu entries should call this so they're skipped (rather than
    timing out on missing UI) when the backend reports
    ``curio_no_project=true``.
    """
    if skip_project_page_env():
        pytest.skip("This test requires CURIO_NO_PROJECT=0")


def require_no_project_mode() -> None:
    """Skip the current test unless Curio is running in ``--no-project`` mode.

    Inverse of :func:`require_project_page`: tests that specifically assert
    the no-project UI (e.g. that the File menu hides project-backed entries)
    only make sense when the backend reports ``curio_no_project=true``.
    """
    if not skip_project_page_env():
        pytest.skip("This test requires CURIO_NO_PROJECT=1")


def debug_log(location: str, message: str, data: dict = None, hypothesis_id: str = ""):
    """Write a single NDJSON debug entry to ``.curio/playwright.log``."""
    try:
        log_path = os.path.join(state_root(), "playwright.log")
        entry = {
            "timestamp": int(time.time() * 1000),
            "location": location,
            "message": message,
            "data": data or {},
            "hypothesisId": hypothesis_id,
        }
        with open(log_path, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass
