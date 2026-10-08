"""The monitor routes.

All four are public and unauthenticated, like ``/version`` and
``/api/config/public``, and all four exist on every instance. There is no
deploy gate: a laptop benefits from the error log as much as a server does, and
a page that only appears in one posture is a page nobody remembers exists.

Read ``errors.py``'s module docstring before changing what the errors route
returns. It is deliberately exempt from the anonymity rule the other two GETs
are tested against.
"""

from __future__ import annotations

import os
import platform
import threading
import time

from flask import Blueprint, jsonify, request

from utk_curio.backend.app.common.token_bucket import TokenBucket
from utk_curio.backend.app.monitor import counters, errors, hardware, stats, storage

monitor_bp = Blueprint("monitor", __name__, url_prefix="/api/monitor")

# Shorter than the version badge's 5s. The page polls every 5s, so a deadline
# at or above the poll interval would let requests stack up against a hung
# sandbox instead of failing fast and rendering "unreachable".
SANDBOX_MONITOR_TIMEOUT = 3

# A browser error report is a few hundred bytes. Anything approaching this is
# either a bug or an attempt to fill the window with one request.
MAX_CLIENT_REPORT_BYTES = 16 * 1024
MAX_CLIENT_MESSAGE_CHARS = 2000
MAX_CLIENT_STACK_CHARS = 8000

_PER_IP_PER_MINUTE = 10
_GLOBAL_PER_MINUTE = 100
_MINUTE = 60.0


def _sandbox_monitor():
    """The sandbox's counters, or None when it cannot be reached.

    Degrades rather than failing, for the same reason ``/version`` does: a
    monitor page that 502s because the sandbox is the thing being monitored is
    the exact failure mode to avoid.

    A sandbox that is merely DOWN is an expected outcome and returns None
    quietly. ``_sandbox_call`` signals that by returning a Flask
    ``(response, status)`` TUPLE rather than a ``requests.Response``, so the
    isinstance check below is how "down" is recognised. Without it a tuple
    still degrades, but only by raising AttributeError into the catch-all,
    which would make an ordinary restart indistinguishable from a bug in this
    function. Anything that reaches the catch-all is therefore genuinely
    unexpected, and is logged so it is not silent. (The log dedups, so a
    persistent fault on a 5s poll collapses to one entry with a count.)
    """
    from utk_curio.backend.app.api.routes import _sandbox_call

    try:
        response = _sandbox_call(
            "get", "/monitor",
            label="/api/monitor", timeout=SANDBOX_MONITOR_TIMEOUT,
        )
        if isinstance(response, tuple):
            return None
        if response.status_code != 200:
            return None
        payload = response.json()
        return payload if isinstance(payload, dict) else None
    except ValueError:
        # A 200 whose body is not JSON. Odd but not actionable, and not a
        # fault in this process.
        return None
    except Exception as exc:  # noqa: BLE001 - a monitor never fails over its subject
        errors.record(
            "backend",
            summary=f"Monitor could not read the sandbox: {type(exc).__name__}",
            detail=str(exc),
        )
        return None


def _unreachable_sandbox() -> dict:
    return {
        "reachable": False,
        "isolation": None, "isolationActive": None, "zygoteRunning": None,
        "parallelism": None, "slotsInUse": None,
        "memoryLimitMb": None, "cpuSecondsLimit": None,
        "wallTimeoutSeconds": None,
        "total": None, "isolated": None, "inProcess": None,
        "childDeaths": None, "execLock": None,
    }


def _sandbox_section(payload) -> dict:
    if not payload:
        return _unreachable_sandbox()
    return {
        "reachable": True,
        "isolation": payload.get("isolation"),
        "isolationActive": payload.get("isolation_active"),
        "zygoteRunning": payload.get("zygote_running"),
        "parallelism": payload.get("parallelism"),
        "slotsInUse": payload.get("slotsInUse"),
        "memoryLimitMb": payload.get("memory_limit_mb"),
        "cpuSecondsLimit": payload.get("cpu_seconds_limit"),
        "wallTimeoutSeconds": payload.get("wall_timeout_seconds"),
        "total": payload.get("total"),
        "isolated": payload.get("isolated"),
        "inProcess": payload.get("inProcess"),
        "childDeaths": payload.get("childDeaths") or {},
        # Per-call-site wait and hold time on the sandbox's process-wide
        # execution lock. Cumulative since the sandbox started: the stress
        # harness diffs two readings to get one tier's contention.
        "execLock": payload.get("exec_lock"),
    }


def _deployment_llm_configured() -> bool:
    from utk_curio.backend.app.agents.infrastructure.provider_config import deployment_config

    return deployment_config("", guest=False) is not None


def _deployment(sandbox) -> dict:
    """Configuration facts. Booleans and closed vocabularies only.

    Every setting that has a value a person chose (the exec account name, the
    LLM base URL, model and key) is reported as "configured: true/false". The
    question an operator has is whether it is set, and the value itself would
    be the leak.
    """
    from utk_curio import __version__
    from utk_curio.backend import config
    from utk_curio.backend.app.packages.routes import common as packages_routes_common

    return {
        "version": __version__,
        "isolation": (sandbox or {}).get("isolation") or "unknown",
        "isolationActive": (sandbox or {}).get("isolation_active") or "unknown",
        "execUserConfigured": bool(os.environ.get("CURIO_EXEC_USER", "").strip()),
        "authEnabled": not config.CURIO_NO_AUTH,
        "projectsEnabled": not config.CURIO_NO_PROJECT,
        "guestLoginAllowed": bool(config.ALLOW_GUEST_LOGIN),
        "collabEnabled": bool(config.ENABLE_COLLAB),
        # The switch the package and dataset catalog routes obey.
        "factoryPublishAllowed": bool(packages_routes_common.CURIO_ALLOW_FACTORY_CATALOG_PUBLISH),
        "saveNodeOutputDefault": bool(config.CURIO_DEFAULT_SAVE_NODE_OUTPUT),
        # The Deployment default a signed-in user falls back to: the operator's
        # endpoint with a model (``provider_config.deployment_config``).
        "llmProviderConfigured": _deployment_llm_configured(),
        # Whether the operator named a search provider (--agent-search-url);
        # web.search reads the same variable and has a keyless default.
        "searchToolConfigured": bool(os.environ.get("CURIO_SEARCH_URL", "").strip()),
        "env": config.CURIO_ENV,
        "platform": platform.platform(),
        "pythonVersion": platform.python_version(),
    }


@monitor_bp.route("", methods=["GET"])
@monitor_bp.route("/", methods=["GET"])
def monitor_route():
    """Deployment config, execution health, accounts and content. Aggregates."""
    sandbox = _sandbox_monitor()
    return jsonify({
        "generatedAt": _iso_now(),
        "uptimeSeconds": counters.uptime_seconds(),
        "deployment": _deployment(sandbox),
        "hardware": hardware.snapshot(
            sandbox_rss=(sandbox or {}).get("rss_bytes"),
        ),
        "execution": {
            "backend": counters.snapshot(),
            "sandbox": _sandbox_section(sandbox),
        },
        "accounts": stats.accounts(),
        "content": stats.content(),
    })


@monitor_bp.route("/storage", methods=["GET"])
def monitor_storage_route():
    """Disk usage across the state tree, from a cached walk. Aggregates."""
    return jsonify(storage.snapshot())


@monitor_bp.route("/errors", methods=["GET"])
def monitor_errors_route():
    """Recent failures, RAW. See errors.py for what this exposes and why."""
    sandbox = _sandbox_monitor()
    payload = errors.snapshot(
        sandbox_entries=(sandbox or {}).get("errors") if sandbox else None,
    )
    payload["generatedAt"] = _iso_now()
    payload["sandboxWindow"] = (sandbox or {}).get("errorWindow")
    return jsonify(payload)


@monitor_bp.route("/errors/client", methods=["POST"])
def monitor_client_error_route():
    """Accept one browser error report.

    Always answers 204, whatever happens. This endpoint is called from a
    window error handler, so any status a caller might retry on, or any body a
    caller might parse, risks turning one broken render into a request loop.
    A refused report is counted, not reported.
    """
    if request.content_length and request.content_length > MAX_CLIENT_REPORT_BYTES:
        errors.record_dropped_client()
        return "", 204

    if not _allow_client_report(request.remote_addr or "unknown"):
        errors.record_dropped_client()
        return "", 204

    try:
        body = request.get_json(silent=True) or {}
        message = str(body.get("message") or "").strip()[:MAX_CLIENT_MESSAGE_CHARS]
        stack = str(body.get("stack") or "")[:MAX_CLIENT_STACK_CHARS]
        page = str(body.get("url") or "")[:500]
        agent = str(body.get("userAgent") or "")[:300]
        if not message and not stack:
            errors.record_dropped_client()
            return "", 204
        errors.record(
            "client",
            summary=message or "Browser error",
            detail=stack,
            context={"url": page, "userAgent": agent},
        )
    except Exception:  # noqa: BLE001
        errors.record_dropped_client()
    return "", 204


def _allow_client_report(key: str) -> bool:
    """Token bucket per address plus a global ceiling. In-process, no store.

    Both buckets matter: the per-address one stops a single browser in a render
    loop, the global one stops a spread-out flood from filling the window.
    """
    try:
        return _client_reports.allow(key, time.monotonic())
    except Exception:  # noqa: BLE001
        return False


class _ClientReportBuckets:
    """The buckets behind :func:`_allow_client_report`.

    A report spends a token from both buckets or from neither, so the refused
    reports of a browser in a loop leave the global allowance to everyone else.
    A bucket left alone for a minute is full again, the same as a new one, so
    once a minute those are dropped and the table holds only recent addresses.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        with self._lock:
            self.overall: TokenBucket | None = None
            self.per_address: dict[str, TokenBucket] = {}
            self.swept_at: float | None = None

    def allow(self, key: str, now: float) -> bool:
        with self._lock:
            self._forget_full_buckets(now)
            if self.overall is None:
                self.overall = TokenBucket(
                    _GLOBAL_PER_MINUTE, _GLOBAL_PER_MINUTE / _MINUTE, now)
            if self.overall.refill(now) < 1.0:
                return False
            bucket = self.per_address.get(key)
            if bucket is None:
                bucket = TokenBucket(_PER_IP_PER_MINUTE, _PER_IP_PER_MINUTE / _MINUTE, now)
                self.per_address[key] = bucket
            if not bucket.take(now):
                return False
            self.overall.take(now)
            return True

    def _forget_full_buckets(self, now: float) -> None:
        if self.swept_at is not None and now - self.swept_at < _MINUTE:
            return
        self.swept_at = now
        self.per_address = {
            key: bucket for key, bucket in self.per_address.items()
            if bucket.refill(now) < bucket.capacity
        }


_client_reports = _ClientReportBuckets()


def reset_rate_limit() -> None:
    """For tests only."""
    _client_reports.reset()


def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
