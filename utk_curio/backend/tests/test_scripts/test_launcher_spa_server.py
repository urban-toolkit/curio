"""``run_spa_static_server``: index.html fallback for client-side routes.

This function serves the built frontend in every non-dev launch — the shipped
container sets ``CURIO_DEV=0`` (Dockerfile) — and had no test at all, which is
how it shipped refusing to serve the very deep links it exists for.

The bug it now guards: the fallback used to be gated on
``not os.path.splitext(candidate)[1]``, i.e. "this path has no file extension".
Dataset ids are dotted, so ``splitext`` reads
``/catalog/data/data.urbanlab.acs-neighborhood-profile`` as having the extension
``.acs-neighborhood-profile``, the guard went false, and the request 404'd
instead of reaching the router. The dev server had the same hole through a
different mechanism (connect-history-api-fallback's dot rule, now disabled in
``webpack.config.js``).

The replacement keys off the ``Accept`` header, so the two cases that must not
be conflated stay separate: a browser navigating to a route asks for
``text/html`` and gets the app; a bundle fetched with ``Accept: */*`` that is
genuinely missing still gets its 404 rather than a stray copy of index.html.
"""
from __future__ import annotations

import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from utk_curio.main import run_spa_static_server

INDEX_BODY = "<!doctype html><title>curio</title><div id=root></div>"
ASSET_BODY = "console.log('real bundle');"

HTML_ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
ANY_ACCEPT = "*/*"


@pytest.fixture(scope="module")
def spa_server(tmp_path_factory):
    """A real server on an ephemeral port, serving a two-file dist tree."""
    dist = tmp_path_factory.mktemp("dist")
    (dist / "index.html").write_text(INDEX_BODY, encoding="utf-8")
    (dist / "bundle.js").write_text(ASSET_BODY, encoding="utf-8")

    # Bind :0 first so the port is known before the server thread starts, and
    # the test never races a fixed port another run might hold.
    probe = ThreadingHTTPServer(("127.0.0.1", 0), None.__class__)  # type: ignore[arg-type]
    port = probe.server_address[1]
    probe.server_close()

    thread = threading.Thread(
        target=run_spa_static_server, args=(str(dist), port), daemon=True
    )
    thread.start()

    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            urllib.request.urlopen(f"{base}/index.html", timeout=1).read()
            break
        except OSError:
            threading.Event().wait(0.05)
    else:
        pytest.fail("run_spa_static_server never came up")
    return base


def _get(base: str, path: str, accept: str = HTML_ACCEPT):
    request = urllib.request.Request(f"{base}{path}", headers={"Accept": accept})
    with urllib.request.urlopen(request, timeout=5) as response:
        return response.status, response.read().decode("utf-8")


@pytest.mark.parametrize(
    "path",
    [
        # The regression: every id in the bundled catalog is dotted.
        "/catalog/data/data.urbanlab.acs-neighborhood-profile",
        "/catalog/data/data.cityofchicago.red-light-violations",
        "/data-hub/data.urbanlab.chicago-boundary",
        # Undotted routes, which worked before and must keep working.
        "/projects",
        "/catalog/nodes",
        "/dataflow/97af666e-e32f-40a0-bc06-021fc3c22acf",
        "/auth/signup",
    ],
)
def test_client_routes_fall_back_to_index(spa_server, path):
    status, body = _get(spa_server, path)
    assert status == 200
    assert body == INDEX_BODY, f"{path} did not reach the router"


def test_real_asset_is_served_verbatim(spa_server):
    status, body = _get(spa_server, "/bundle.js", accept=ANY_ACCEPT)
    assert status == 200
    assert body == ASSET_BODY


def test_root_serves_index(spa_server):
    status, body = _get(spa_server, "/")
    assert status == 200
    assert body == INDEX_BODY


def test_missing_asset_still_404s(spa_server):
    """A mistyped bundle must not come back as a 200 page of HTML.

    This is why the fallback keys off ``Accept`` rather than simply dropping the
    extension test: without it, every missing asset would answer index.html and
    the failure would surface as a confusing parse error instead of a 404.
    """
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        _get(spa_server, "/does-not-exist.js", accept=ANY_ACCEPT)
    assert excinfo.value.code == 404
