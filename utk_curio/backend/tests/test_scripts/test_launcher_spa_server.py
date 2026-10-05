"""``run_spa_static_server``: index.html fallback for client-side routes.

This function serves the built frontend in every non-dev launch — the shipped
container sets ``CURIO_DEV=0`` (Dockerfile) — and had no test at all, which is
how it shipped refusing to serve the very deep links it exists for.

The bug it now guards: the fallback used to be gated on
``not os.path.splitext(candidate)[1]``, i.e. "this path has no file extension".
Dataset ids are dotted, so ``splitext`` reads
``/catalog/data/data.utk.acs-neighborhood-profile`` as having the extension
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

import argparse
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from utk_curio.cli.arguments import backend_url_arg, base_path_arg
from utk_curio.cli.static_server import run_spa_static_server

INDEX_BODY = "<!doctype html><title>curio</title><div id=root></div>"
ASSET_BODY = "console.log('real bundle');"

HTML_ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
ANY_ACCEPT = "*/*"


def _start(dist, base_path: str = "", backend_url: str = "") -> str:
    """A real server on an ephemeral port, in a daemon thread; returns its URL."""
    # Bind :0 first so the port is known before the server thread starts, and
    # the test never races a fixed port another run might hold.
    probe = ThreadingHTTPServer(("127.0.0.1", 0), None.__class__)  # type: ignore[arg-type]
    port = probe.server_address[1]
    probe.server_close()

    thread = threading.Thread(
        target=run_spa_static_server, args=(str(dist), port, base_path, backend_url), daemon=True
    )
    thread.start()

    url = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            urllib.request.urlopen(f"{url}/index.html", timeout=1).read()
            return url
        except OSError:
            threading.Event().wait(0.05)
    pytest.fail("run_spa_static_server never came up")


@pytest.fixture(scope="module")
def spa_server(tmp_path_factory):
    """The server at the root of the host, serving a two-file dist tree."""
    dist = tmp_path_factory.mktemp("dist")
    (dist / "index.html").write_text(INDEX_BODY, encoding="utf-8")
    (dist / "bundle.js").write_text(ASSET_BODY, encoding="utf-8")
    return _start(dist)


def _get(base: str, path: str, accept: str = HTML_ACCEPT):
    request = urllib.request.Request(f"{base}{path}", headers={"Accept": accept})
    with urllib.request.urlopen(request, timeout=5) as response:
        return response.status, response.read().decode("utf-8")


@pytest.mark.parametrize(
    "path",
    [
        # The regression: every id in the bundled catalog is dotted.
        "/catalog/data/data.utk.acs-neighborhood-profile",
        "/catalog/data/data.cityofchicago.red-light-violations",
        "/catalog/data/data.utk.chicago-boundary",
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


# The index.html webpack writes: its <base> is "/" and the bundle is relative.
BUILT_INDEX = (
    '<!doctype html><html><head><base href="/">'
    '<script defer="defer" src="bundle.js"></script></head>'
    "<body><div id=root></div></body></html>"
)
UNDER_APP = BUILT_INDEX.replace('<base href="/">', '<base href="/app/">')


@pytest.fixture(scope="module")
def app_server(tmp_path_factory):
    """The server with ``--base-path /app``."""
    dist = tmp_path_factory.mktemp("dist-app")
    (dist / "index.html").write_text(BUILT_INDEX, encoding="utf-8")
    (dist / "bundle.js").write_text(ASSET_BODY, encoding="utf-8")
    return _start(dist, "/app")


@pytest.mark.parametrize(
    "path",
    [
        "/app/",
        "/app",
        "/app/dataflow/97af666e-e32f-40a0-bc06-021fc3c22acf",
        "/app/catalog/data/data.utk.chicago-boundary",
        # What the server sees behind a proxy that strips the prefix.
        "/",
        "/dataflow/97af666e-e32f-40a0-bc06-021fc3c22acf",
    ],
)
def test_base_path_points_the_page_at_the_prefix(app_server, path):
    status, body = _get(app_server, path)
    assert status == 200
    assert body == UNDER_APP


@pytest.mark.parametrize("path", ["/app/bundle.js", "/bundle.js"])
def test_base_path_serves_assets_with_or_without_the_prefix(app_server, path):
    status, body = _get(app_server, path, accept=ANY_ACCEPT)
    assert status == 200
    assert body == ASSET_BODY


def test_base_path_missing_asset_still_404s(app_server):
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        _get(app_server, "/app/does-not-exist.js", accept=ANY_ACCEPT)
    assert excinfo.value.code == 404


def test_head_reports_the_page_it_would_send(app_server):
    request = urllib.request.Request(f"{app_server}/app/projects", method="HEAD", headers={"Accept": HTML_ACCEPT})
    with urllib.request.urlopen(request, timeout=5) as response:
        assert response.status == 200
        assert int(response.headers["Content-Length"]) == len(UNDER_APP.encode("utf-8"))


@pytest.mark.parametrize(
    ("value", "expected"),
    [("/", ""), ("", ""), ("/app", "/app"), ("/app/", "/app"), ("app", "/app"), ("/lab/curio/", "/lab/curio")],
)
def test_base_path_arg_normalizes(value, expected):
    assert base_path_arg(value) == expected


@pytest.mark.parametrize("value", ["/a b", "/../x", '/"x', "/a//b", "/<script>", "/app?x=1"])
def test_base_path_arg_refuses_what_is_not_a_path_prefix(value):
    with pytest.raises(argparse.ArgumentTypeError):
        base_path_arg(value)


BACKEND_META = '<meta name="curio-backend-url" content="https://curio.example.org/app/api">'


@pytest.fixture(scope="module")
def hosted_server(tmp_path_factory):
    """``--base-path /app --backend-url https://curio.example.org/app/api``."""
    dist = tmp_path_factory.mktemp("dist-hosted")
    (dist / "index.html").write_text(BUILT_INDEX, encoding="utf-8")
    (dist / "bundle.js").write_text(ASSET_BODY, encoding="utf-8")
    return _start(dist, "/app", "https://curio.example.org/app/api")


@pytest.mark.parametrize("path", ["/app/", "/app/projects", "/projects"])
def test_the_page_names_the_backend_it_was_started_with(hosted_server, path):
    status, body = _get(hosted_server, path)
    assert status == 200
    assert body == BUILT_INDEX.replace('<base href="/">', '<base href="/app/">' + BACKEND_META)


def test_at_the_root_the_page_still_names_its_backend(tmp_path):
    (tmp_path / "index.html").write_text(BUILT_INDEX, encoding="utf-8")
    url = _start(tmp_path, "", "http://localhost:5102")
    status, body = _get(url, "/catalog/nodes")
    assert status == 200
    assert '<base href="/"><meta name="curio-backend-url" content="http://localhost:5102">' in body


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("https://curio.urbantk.org/app/api/", "https://curio.urbantk.org/app/api"),
        ("http://localhost:5002", "http://localhost:5002"),
        ("/app/api", "/app/api"),
    ],
)
def test_backend_url_arg_normalizes(value, expected):
    assert backend_url_arg(value) == expected


@pytest.mark.parametrize(
    "value",
    ["", "/", "ftp://example.org", "https://example.org/a b", 'https://example.org/"x', "https://example.org/?q=1", "javascript:alert(1)"],
)
def test_backend_url_arg_refuses_what_is_not_an_address(value):
    with pytest.raises(argparse.ArgumentTypeError):
        backend_url_arg(value)
