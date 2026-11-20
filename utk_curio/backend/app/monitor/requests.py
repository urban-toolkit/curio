"""Each request the backend answers, timed for the monitor's Usage tab: the
``request`` measure of ``usage.py``.

:func:`install`, which ``create_app`` calls before it registers anything else,
stamps a request before it is handled (the app's first ``before_request``) and
counts it once its response is made (its last ``after_request``): its time
from the stamp to the response, failed when the response is a 5xx, the
catch-all's 500 for an error a route raised among them. A request no stamp
reached, one an earlier ``before_request`` answered, is not counted.

LEFT OUT, so the measure is the time people wait for Curio's own work:

- a preflight, ``OPTIONS``;
- the monitor's own routes, ``/api/monitor`` and those below it, which its
  page polls;
- ``/version``, which every page's badge polls, and the probes that say the
  backend is up: ``/health``, which Docker's health check asks every 30 s, and
  ``/live``;
- ``/internal/``, the start's backend processes asking each other, and
  ``/api/testing/``, the test harness's;
- Socket.IO, which never reaches the app: Flask-SocketIO wraps the app's WSGI
  callable in Engine.IO's, which answers ``/socket.io/`` itself (the prefix is
  left out here all the same);
- a streamed response (``Response.is_streamed``), whose body is sent as it is
  made, so its time to the response is not its time: an event stream (a
  run's, a turn's, a Solve's), an artifact relayed as the sandbox sends it
  (``/get``, ``/get-preview``, ``/raster``) and a file sent from disk.

Never raises: a request never fails over its bookkeeping.
"""

from __future__ import annotations

import time

from flask import request

from utk_curio.backend.app.monitor import usage

#: Where a request keeps the time it was stamped.
_STARTED = "curio.monitor.request_started"
#: The paths left out, as a whole.
_PATHS = frozenset({"/api/monitor", "/version", "/health", "/live"})
#: The paths left out, by their start.
_PREFIXES = ("/api/monitor/", "/internal/", "/api/testing/", "/socket.io/")


def install(app) -> None:
    """Time each request *app* answers. Called before anything else
    registers a hook, so the stamp comes first and the count last."""
    app.before_request(_stamp)
    app.after_request(_count)


def counted(method: str, path: str) -> bool:
    """Whether a request of *method* to *path* is one the measure counts."""
    return method != "OPTIONS" and path not in _PATHS and not path.startswith(_PREFIXES)


def _stamp() -> None:
    try:
        request.environ[_STARTED] = time.perf_counter()
    except Exception:  # noqa: BLE001
        # An unstamped request is not counted.
        return


def _count(response):
    try:
        started = request.environ.get(_STARTED)
        if started is not None and counted(request.method, request.path) and not response.is_streamed:
            usage.record("request", ms=(time.perf_counter() - started) * 1000.0,
                         failed=response.status_code >= 500)
    except Exception:  # noqa: BLE001
        # A response never fails over its bookkeeping.
        return response
    return response
