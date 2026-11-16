"""Routes the home process serves whatever dataflow a request names
(``utk_curio/cli/backend_group.nginx_config``).

nginx sends a request to the process that owns the dataflow it names
(``test_backend_router_nginx.py``). A few route families hold state of the
home process's instead, and go there first, whatever dataflow header, query
argument or path id they carry:

* ``/api/discovery/``: Discovery's searches and its rate limits per account
  and source, place search and its one request a second to OpenStreetMap's
  geocoder, the scans of storage sources, and the jobs downloads and caches
  run as, which the page polls by id;
* ``/api/monitor``: the monitor, whose numbers the home process holds;
* ``/api/packages/factory/``: the package factory's builds and installs.

A route that writes a dataflow, such as a package installed into one
(``/api/packages/projects/<id>/install``), keeps following its dataflow: its
owner alone may write it.

Each request goes through a real nginx with the config the launcher writes,
in front of stand-ins for 4 backend processes that each say which process
they are. The CI image installs nginx (Dockerfile) and the backend suite runs
inside it; without nginx or the launcher's module these fail, never skip.
"""
from __future__ import annotations

import importlib
import json
import re
import shutil
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pytest
from werkzeug.serving import make_server

#: The backend processes of the start nginx fronts here.
PROCESSES = 4
#: How long a step may wait on another before the test fails.
PATIENCE_S = 20.0
#: A dataflow id each process owns: its first two hex digits, 0x40 and up,
#: modulo the process count.
OWNED = {number: f"{0x40 + number:02x}3a5c1e-0b4d-4c8e-9a7f-2d6b8e1c5a90" for number in range(PROCESSES)}

#: A request of each route family the home process serves, by method and path.
HOMES = (
    ("GET", "/api/discovery/search?q=parks"),
    ("GET", "/api/discovery/sources/nyc-open-data/search?q=parks"),
    ("GET", "/api/discovery/places?q=Chicago"),
    ("GET", "/api/discovery/sources/nyc-open-data/resources/abcd-1234"),
    ("POST", "/api/discovery/sources/nyc-open-data/resources/abcd-1234/acquire"),
    ("GET", "/api/discovery/sources/street-images/files/all"),
    ("GET", "/api/discovery/jobs/0f1e2d3c4b5a"),
    ("DELETE", "/api/discovery/jobs/0f1e2d3c4b5a"),
    ("POST", "/api/discovery/collections/street-images/cache"),
    ("GET", "/api/discovery/catalog"),
    ("GET", "/api/monitor"),
    ("GET", "/api/monitor/open-files"),
    ("POST", "/api/monitor/errors/client"),
    ("POST", "/api/packages/factory/build"),
    ("POST", "/api/packages/factory/install"),
    ("GET", "/api/packages/factory/capabilities"),
)

#: Never through a proxy the environment names: nginx is on 127.0.0.1.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _backend_group():
    return importlib.import_module("utk_curio.cli.backend_group")


def _stand_in(number: int):
    """A backend process that answers every request with its number."""

    def answer(environ, start_response):
        length = int(environ.get("CONTENT_LENGTH") or 0)
        if length:
            environ["wsgi.input"].read(length)
        body = json.dumps({"process": number, "path": environ.get("PATH_INFO")}).encode()
        start_response("200 OK", [("Content-Type", "application/json"), ("Content-Length", str(len(body)))])
        return [body]

    server = make_server("127.0.0.1", 0, answer, threaded=True)
    threading.Thread(target=server.serve_forever, name=f"backend-process-{number}", daemon=True).start()
    return server


def _a_free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture(scope="module")
def router(tmp_path_factory):
    nginx = shutil.which("nginx")
    if not nginx:
        pytest.fail("nginx is not on PATH; the Docker image installs it, and the backend suite runs in that image")
    stand_ins = [_stand_in(number) for number in range(PROCESSES)]
    folder = tmp_path_factory.mktemp("state") / "backend-router"
    folder.mkdir()
    port = _a_free_port()
    config = folder / "nginx.conf"
    config.write_text(_backend_group().nginx_config(
        host="127.0.0.1", port=port, ports=[server.server_port for server in stand_ins], folder=folder,
    ), encoding="utf-8")
    log = folder / "nginx.log"
    with open(log, "wb") as out:
        proxy = subprocess.Popen([nginx, "-c", str(config), "-e", "stderr"], stdout=out, stderr=subprocess.STDOUT)
    try:
        deadline = time.monotonic() + PATIENCE_S
        while True:
            if proxy.poll() is not None:
                pytest.fail(f"nginx exited with code {proxy.returncode}:\n{log.read_text(errors='replace')}")
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=1):
                    break
            except OSError:
                if time.monotonic() > deadline:
                    pytest.fail(f"nginx never listened on {port}:\n{log.read_text(errors='replace')}")
                time.sleep(0.05)
        yield SimpleNamespace(port=port, config=config.read_text(encoding="utf-8"))
    finally:
        proxy.terminate()
        try:
            proxy.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proxy.kill()
            proxy.wait()
        for server in stand_ins:
            server.shutdown()
            server.server_close()


def _reached(router, method: str, path: str, headers=None) -> int:
    asked = urllib.request.Request(f"http://127.0.0.1:{router.port}{path}", method=method, headers=headers or {},
                                   data=b"{}" if method == "POST" else None)
    try:
        with _OPENER.open(asked, timeout=PATIENCE_S) as answer:
            body = answer.read()
    except urllib.error.HTTPError as refused:
        pytest.fail(f"{method} {path} {headers}: {refused.code} {refused.read()[:300]!r}")
    return json.loads(body)["process"]


def _with_query(path: str, name: str, value: str) -> str:
    return f"{path}{'&' if '?' in path else '?'}{name}={value}"


def _with_a_path_id(path: str, dataflow: str) -> str:
    """*path* with a dataflow id after ``/dataflows/`` in it, before its query."""
    bare, mark, query = path.partition("?")
    return f"{bare}/dataflows/{dataflow}{mark}{query}"


@pytest.mark.parametrize("method, path", HOMES, ids=[f"{method} {path}" for method, path in HOMES])
def test_a_route_of_the_home_process_reaches_it_whatever_dataflow_it_names(router, method, path):
    named = {
        "a dataflow header": (path, {"X-Curio-Dataflow": OWNED[1]}),
        "a dataflow query": (_with_query(path, "dataflow", OWNED[2]), {}),
        "a dataflow id in its path": (_with_a_path_id(path, OWNED[3]), {}),
        "all three": (_with_a_path_id(_with_query(path, "dataflow", OWNED[2]), OWNED[3]),
                      {"X-Curio-Dataflow": OWNED[1]}),
        "none": (path, {}),
    }
    reached = {why: _reached(router, method, asked, headers) for why, (asked, headers) in named.items()}
    assert reached == {why: 0 for why in named}, (
        f"{method} {path} must reach the home process, process 0, whatever dataflow it names: {reached}"
    )


def test_a_route_that_writes_a_dataflow_keeps_following_it(router):
    """Its owner alone may write it: anywhere else the guard refuses with 421."""
    from utk_curio.common.backend_processes import shard_of

    assert [shard_of(OWNED[number], PROCESSES) for number in range(PROCESSES)] == list(range(PROCESSES))
    for method, path, headers, owner in (
        ("POST", f"/api/packages/projects/{OWNED[3]}/install", {}, 3),
        ("POST", f"/api/packages/projects/{OWNED[3]}/install", {"X-Curio-Dataflow": OWNED[3]}, 3),
        ("DELETE", f"/api/packages/projects/{OWNED[2]}/curio.package-a", {}, 2),
        ("GET", f"/api/packages/dataflows/{OWNED[1]}", {}, 1),
        ("GET", "/api/datasets/street-images/media/f1", {"X-Curio-Dataflow": OWNED[1]}, 1),
        ("GET", "/api/discoveries", {"X-Curio-Dataflow": OWNED[2]}, 2),
        ("GET", "/api/monitoring", {"X-Curio-Dataflow": OWNED[3]}, 3),
    ):
        reached = _reached(router, method, path, headers)
        assert reached == owner, f"{method} {path} {headers} reached process {reached}, not {owner}"


def test_the_config_sends_each_home_route_family_to_the_home_process():
    """As the config reads: each family's location goes to process 0's
    upstream itself, never through the dataflow's."""
    text = _backend_group().nginx_config(host="127.0.0.1", port=5999, ports=[7000, 7001, 7002, 7003],
                                         folder=Path("/state/backend-router"))
    for prefix in ("/api/discovery/", "/api/monitor", "/api/packages/factory/"):
        found = re.search(rf"location (?:\^~|=) {re.escape(prefix)}\S*\s*\{{([^}}]*)\}}", text)
        assert found, f"no location sends {prefix} to the home process"
        assert re.search(r"proxy_pass http://curio_backend_0;", found.group(1)), found.group(0)
