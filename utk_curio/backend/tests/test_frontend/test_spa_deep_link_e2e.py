"""A dotted deep link reaches the app on the *production* static server.

``test_scripts/test_launcher_spa_server.py`` pins the fallback rule itself — it
asks the handler for a dotted route and checks it gets index.html back. This
test covers the half that one cannot: that a real browser, given the real built
bundle, then boots the SPA and lets React Router resolve the dotted path
client-side. A fallback that returns index.html to a router that refuses to
match the URL would pass there and fail here.

Why a separate server rather than the suite's own frontend: the e2e stack runs
with ``CURIO_DEV=1`` and is served by webpack-dev-server, whose dot rule is a
different mechanism with a different fix (``disableDotRule`` in
``webpack.config.js``). The shipped container sets ``CURIO_DEV=0``
(``Dockerfile``) and takes ``run_spa_static_server`` instead, so that is the path
a deployed Curio actually uses and the one nothing exercised end to end.

The bug both fixes address: dataset ids are dotted, so
``/catalog/data/data.urbanlab.acs-neighborhood-profile`` has a "file extension"
as far as ``os.path.splitext`` is concerned. The old guard read that as a
request for an asset, skipped the rewrite, and the deployed app answered a bare
404 to every bookmarked or shared dataset link.
"""
from __future__ import annotations

import os
import threading
from http.server import ThreadingHTTPServer

import pytest
from playwright.sync_api import expect

from .utils import REPO_ROOT

DIST = os.path.join(REPO_ROOT, "utk_curio", "frontend", "urban-workflows", "dist")

#: A dotted id from the committed catalog — the shape that used to 404.
DOTTED_DATASET = "data.urbanlab.acs-neighborhood-profile"

DEEP_LINKS = [
    f"/catalog/data/{DOTTED_DATASET}",
    f"/data-hub/{DOTTED_DATASET}",
    # Undotted routes, which always worked and must keep working.
    "/catalog/data",
    "/projects",
]


@pytest.fixture(scope="module")
def spa_server():
    """The production static server, on the real built bundle.

    A missing ``dist/`` is a **failure**, not a skip. This is the only test
    covering the server a deployed Curio actually runs, and the bug it guards
    shipped in exactly that server: quietly skipping would restore the silence
    that let it ship. The same argument the suite already makes for
    ``require_owner_view`` - the environment being wrong is a setup bug, so it
    is loud - applies with more force here, because a skip on the deep-link test
    reads as "deep links are fine".
    """
    index = os.path.join(DIST, "index.html")
    if not os.path.isfile(index):
        pytest.fail(
            "no built frontend at utk_curio/frontend/urban-workflows/dist." + chr(10)
            + "This test covers the production static server - the one the "
            "shipped container runs (CURIO_DEV=0) - so without a build there "
            "is nothing to serve and the deep-link regression would go "
            "unnoticed." + chr(10)
            + "Build it once with:" + chr(10)
            + "    cd utk_curio/frontend/urban-workflows && npm run build"
        )

    from utk_curio.main import run_spa_static_server

    # Bind :0 to learn a free port, then hand it to the server thread — a fixed
    # port would collide with the suite's own stack.
    probe = ThreadingHTTPServer(("127.0.0.1", 0), None.__class__)  # type: ignore[arg-type]
    port = probe.server_address[1]
    probe.server_close()

    threading.Thread(
        target=run_spa_static_server, args=(DIST, port), daemon=True
    ).start()
    return f"http://127.0.0.1:{port}"


@pytest.mark.parametrize("route", DEEP_LINKS)
def test_deep_link_boots_the_app(page, spa_server, route):
    """A hard load of the route renders the SPA, not a server error page."""
    response = page.goto(f"{spa_server}{route}", wait_until="domcontentloaded")
    assert response is not None
    assert response.status == 200, (
        f"{route} answered HTTP {response.status} instead of the app"
    )

    body = page.locator("body")
    # The dev server's refusal renders literally this; http.server's renders an
    # "Error response" page. Neither is ever the app.
    expect(body).not_to_contain_text("Cannot GET")
    expect(body).not_to_contain_text("Error response")

    # index.html arriving is not enough — React has to mount and the router has
    # to accept the path. #root stays empty if either fails.
    page.wait_for_function(
        "() => document.getElementById('root')?.children.length > 0",
        timeout=30000,
    )


def test_a_missing_asset_still_404s(page, spa_server):
    """The fallback must not swallow a genuinely missing bundle.

    Keyed off the Accept header rather than the path's extension precisely so
    this stays a 404: a mistyped asset answering 200-with-HTML surfaces as a
    confusing parse error instead of the missing file it is.
    """
    response = page.request.get(
        f"{spa_server}/does-not-exist.js", headers={"Accept": "*/*"}
    )
    assert response.status == 404
