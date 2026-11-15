"""The nginx config the launcher writes at each start of several backend
processes (``utk_curio/cli/backend_group.nginx_config``).

nginx sends each request and socket to the process that owns its dataflow, by
the rule the owner guard checks (``backend_processes.shard_of``): the key is
the ``X-Curio-Dataflow`` header, else the ``dataflow`` query argument (a
socket's handshake), else a dataflow id after ``/projects/`` or
``/dataflows/`` in the path; its first two hex digits name the process, and a
request with no key goes to the home process. It keeps the flows the backend
serves today: no cap on a body, nothing buffered either way, an hour for an
event stream or a run's keepalive, WebSocket upgrades, the 60 s deadline for
a request's head, and the address it was reached from added to
``X-Forwarded-For``. Calls between the backends never go through it.

What the config says is read here as text, and real nginx checks each count's
config (``nginx -t``): the CI image installs nginx (Dockerfile), and the
backend suite runs inside it. How requests travel through it is
``test_backend_router_nginx.py``. The launcher's module is imported inside
each test, so a checkout without it fails each test on its own.
"""
from __future__ import annotations

import importlib
import re
import shutil
import socket
import subprocess
from pathlib import Path

import pytest

#: Every two-hex-digit start of a dataflow id.
PREFIXES = [f"{lead:02x}" for lead in range(256)]
#: One line of the map from a key's first two hex digits to a process.
_MAP_LINE = re.compile(r'^\s*"~\*\^\(\?:([0-9a-f|]+)\)"\s+curio_backend_(\d+);\s*$', re.M)


def _backend_group():
    return importlib.import_module("utk_curio.cli.backend_group")


def _config(processes: int, folder: Path, *, host: str = "127.0.0.1", port: int = 5999):
    """The config of a start of *processes*, its processes on ports 7000 and
    up, and the ports."""
    ports = [7000 + number for number in range(processes)]
    folder.mkdir(parents=True, exist_ok=True)
    return _backend_group().nginx_config(host=host, port=port, ports=ports, folder=folder), ports


def _block(text: str, opening: str) -> str:
    """The block of *text* that starts at the line *opening*, braces matched."""
    at = text.index(opening)
    depth = 0
    for index in range(text.index("{", at), len(text)):
        depth += {"{": 1, "}": -1}.get(text[index], 0)
        if depth == 0:
            return text[at:index + 1]
    raise AssertionError(f"the block {opening!r} never closes")


@pytest.mark.parametrize("processes", [1, 2, 4, 8])
def test_every_two_digit_prefix_goes_to_the_process_shard_of_names(processes, tmp_path):
    from utk_curio.common.backend_processes import shard_of

    text, ports = _config(processes, tmp_path)

    routed: dict[str, int] = {}
    for prefixes, number in _MAP_LINE.findall(_block(text, "map $curio_key $curio_backend")):
        for prefix in prefixes.split("|"):
            assert prefix not in routed, f"the prefix {prefix} is mapped twice"
            routed[prefix] = int(number)
    expected = {prefix: shard_of(f"{prefix}000000-0000-4000-8000-000000000000", processes) for prefix in PREFIXES}
    assert routed == expected, "the router and the owner guard disagree on which process owns a dataflow"
    # A key whose first two characters are not hex digits, and no key, is home's.
    assert re.search(r"map \$curio_key \$curio_backend \{\s*default curio_backend_0;", text), (
        "a request with no dataflow must go to the home process"
    )
    for number, port in enumerate(ports):
        upstream = _block(text, f"upstream curio_backend_{number} ")
        assert f"server 127.0.0.1:{port};" in upstream
    assert "upstream curio_backend_" + str(processes) + " " not in text


def test_the_key_is_the_header_else_the_query_else_a_dataflow_id_in_the_path(tmp_path):
    text, _ = _config(2, tmp_path)

    header = _block(text, "map $http_x_curio_dataflow $curio_key")
    query = _block(text, "map $arg_dataflow $curio_key_from_query")
    path = _block(text, "map $uri $curio_key_from_path")
    # A request that sends the header is routed by it; one that sends none
    # falls to the query, and one with neither to the path.
    assert re.search(r'^\s*""\s+\$curio_key_from_query;', header, re.M), header
    assert re.search(r"^\s*default\s+\$http_x_curio_dataflow;", header, re.M), header
    assert re.search(r'^\s*""\s+\$curio_key_from_path;', query, re.M), query
    assert re.search(r"^\s*default\s+\$arg_dataflow;", query, re.M), query
    assert re.search(r'^\s*default\s+"";', path, re.M), path
    # Only a whole dataflow id after /projects/ or /dataflows/ names one:
    # /api/projects/defaults starts with two hex digits too.
    assert "projects|dataflows" in path and "{8}-" in path and "{12}" in path, path


def test_the_router_keeps_the_flows_the_backend_serves_today(tmp_path):
    from utk_curio.common.request_deadline import REQUEST_START_TIMEOUT_S

    folder = tmp_path / "backend-router"
    text, ports = _config(4, folder)

    for line, why in (
        ("client_max_body_size 0;", "dataset imports and 2 GiB model packages have no cap"),
        ("proxy_request_buffering off;", "an upload reaches the backend as it comes"),
        ("proxy_buffering off;", "turn and run event streams reach the page as they come"),
        ("proxy_read_timeout 3600s;", "a run's stream and /processPythonCode's keepalive spaces"),
        ("proxy_send_timeout 3600s;", "a long upload to a backend that reads it as it goes"),
        ("send_timeout 3600s;", "a long download or stream to a slow page"),
        ("client_body_timeout 3600s;", "a long upload from a slow page"),
        (f"client_header_timeout {REQUEST_START_TIMEOUT_S}s;",
         "a connection that sends no request head goes at the backend's own deadline"),
        ("worker_rlimit_nofile 65536;", "nginx holds two open files a connection"),
        ("proxy_http_version 1.1;", "WebSockets and kept upstream connections"),
        ("proxy_set_header Upgrade $http_upgrade;", "a socket's WebSocket upgrade"),
        ("proxy_set_header Connection $curio_connection;", "a socket's WebSocket upgrade"),
        ("proxy_set_header Host $http_host;", "the backend sees the host the page asked for"),
        ("proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;", "the limits per visitor address"),
        ("daemon off;", "the launcher holds nginx as one of its servers"),
    ):
        assert line in text, f"the config lacks {line!r}: {why}"
    for number in range(4):
        upstream = _block(text, f"upstream curio_backend_{number} ")
        assert re.search(r"^\s*keepalive \d+;", upstream, re.M), f"no kept connections to process {number}"
        kept = re.search(r"^\s*keepalive_timeout (\d+)s;", upstream, re.M)
        # A kept connection nginx reuses after the backend closed it fails its
        # request: nginx lets go first.
        assert kept and int(kept.group(1)) < REQUEST_START_TIMEOUT_S, upstream
    # Every file nginx writes is in the router's own folder, whose path is
    # quoted: a state folder's path may hold a space.
    for directive in ("pid", "client_body_temp_path", "proxy_temp_path", "fastcgi_temp_path",
                      "uwsgi_temp_path", "scgi_temp_path"):
        found = re.search(rf'^\s*{directive} "([^"]+)";', text, re.M)
        assert found and Path(found.group(1)).parent == folder, f"{directive} is not in {folder}"
    assert "listen 127.0.0.1:5999" in text


def test_the_backends_calls_to_each_other_never_go_through_nginx(tmp_path):
    text, _ = _config(2, tmp_path)
    internal = _block(text, "location ^~ /internal/")
    assert re.search(r"^\s*return 404;", internal, re.M), internal
    assert "proxy_pass" not in internal, "nginx proxies /internal, the backends' route to each other"


@pytest.mark.parametrize("host, listen", [("0.0.0.0", "listen 0.0.0.0:5999"), ("::", "listen [::]:5999"),
                                          ("localhost", "listen localhost:5999")])
def test_nginx_listens_where_the_backend_would(tmp_path, host, listen):
    text, _ = _config(2, tmp_path, host=host)
    assert listen in text


def test_the_router_folder_is_in_the_state_folder():
    backend_group = _backend_group()
    assert backend_group.router_folder({"CURIO_STATE_DIR": "/state"}) == Path("/state/backend-router")
    assert backend_group.router_folder({"CURIO_LAUNCH_CWD": "/app"}) == Path("/app/.curio/backend-router")


def _a_free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.mark.parametrize("processes, state", [(1, "state"), (2, "state"), (4, "state"), (8, "state"),
                                               (2, "a state folder")])
def test_nginx_takes_the_config(processes, state, tmp_path):
    nginx = shutil.which("nginx")
    assert nginx, "nginx is not on PATH; the Docker image installs it, and the backend suite runs in that image"
    folder = tmp_path / state / "backend-router"
    text, _ = _config(processes, folder, port=_a_free_port())
    config = folder / "nginx.conf"
    config.write_text(text, encoding="utf-8")

    checked = subprocess.run([nginx, "-t", "-c", str(config), "-e", "stderr"],
                             capture_output=True, text=True, timeout=60)

    assert checked.returncode == 0, f"nginx refused the config of {processes} process(es):\n{checked.stderr}\n{text}"
