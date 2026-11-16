"""Several backend processes behind nginx: ``curio.py start --backend-processes N``
with N above 1.

Each dataflow belongs to one backend process (``common/backend_processes.py``,
``backend/app/collaboration/owner_guard.py``), which keeps everything live for
it. The launcher prepares the database once, then, on a thread of its own so
the sandbox and the page server start meanwhile, as beside one backend:

1. starts the home process, number 0, on a port of 127.0.0.1 of its own, and
   waits until it answers ``/health``: it does the startup work before it
   serves, and owns every dataflow while it does;
2. starts the others, each on a port of 127.0.0.1 of its own, and waits until
   each answers;
3. writes nginx's config (:func:`nginx_config`) in the router's folder of the
   state folder (:func:`router_folder`), has nginx check it, and starts nginx
   on the backend's host and port, where the sandbox, the page server, the
   site's proxy and the browser reach the backend;
4. watches them all: when any exits, it stops every server and the launcher
   exits with an error, so Docker starts the container again (:func:`watch`).

Each backend is told its number, how many there are, the start's one boot id,
every process's port, and a secret made at this start, which the backends
show each other on their calls between them (``collaboration/owner_calls.py``).
The secret is in their environments alone: never in the launcher's own, which
the sandbox and the page server start from, nor on disk, nor in a log line.
Each backend runs without Werkzeug's reloader, under which it would make a
boot id of its own, and counts nginx as one more proxy in front of it
(``--proxy-hops``). Each writes its own lines into the launcher's log, under
its number, and its own thread-stack file (``backend_processes.own_file``).

nginx sends each request and socket to the process that owns its dataflow, by
the rule the owner guard checks (``backend_processes.shard_of``). The key is
the ``X-Curio-Dataflow`` header, else the ``dataflow`` query argument (a
socket's handshake), else a dataflow id after ``/projects/`` or
``/dataflows/`` in the path; its first two hex digits name the process, and a
request with no key reaches the home process. The route families of
:data:`HOME_ROUTES` reach the home process whatever dataflow they name. The
backends' calls to each other (``/internal``) never go through nginx.
"""

from __future__ import annotations

import os
import secrets
import shutil
import socket
import subprocess
import threading
import time
import urllib.request
import uuid
from pathlib import Path
from typing import Mapping, Optional, Sequence

from utk_curio.cli import lifecycle, services
from utk_curio.cli.lifecycle import clean_shutdown, shutdown_flag, stream_output
from utk_curio.cli.logs import COLOR_BACKEND, log_error, log_info
from utk_curio.common import backend_processes
from utk_curio.common.llm_endpoint import without_backend_only
from utk_curio.common.request_deadline import REQUEST_START_TIMEOUT_S

#: The most backend processes a start runs: a dataflow id's first two hex
#: digits name its process.
MAX_PROCESSES = 256
#: The header the canvas and the dashboard name their dataflow in, and the
#: query argument of a socket's handshake that does.
ROUTE_HEADER = backend_processes.ROUTE_HEADER
ROUTE_QUERY = backend_processes.ROUTE_QUERY
#: nginx's variables of the two: a request header's is ``$http_`` and its name
#: in lower case with ``-`` as ``_``, a query argument's ``$arg_`` and its name.
_HEADER_VARIABLE = "$http_" + ROUTE_HEADER.lower().replace("-", "_")
_QUERY_VARIABLE = "$arg_" + ROUTE_QUERY
#: The router's folder in the state folder: its config, its pid and the
#: folders nginx makes.
ROUTER_FOLDER = "backend-router"
CONFIG_FILE = "nginx.conf"
#: How long one server may take to answer ``/health``: the home process does
#: the startup work first, the examples and their datasets put back among it.
BOOT_TIMEOUT_S = 1800.0
#: How long nginx keeps an idle connection to a backend: less than the
#: backend's own deadline for a request's head (``common/request_deadline.py``),
#: so nginx never sends a request on a connection the backend is closing.
UPSTREAM_IDLE_S = 20

#: The route families the home process serves whatever dataflow a request
#: names, each holding state there, and none writing a dataflow:
#: ``(nginx location, what it holds)``.
#:
#: * Discovery: its searches and their rate limits per account and source,
#:   place search's one request a second to OpenStreetMap's geocoder, the
#:   storage sources' scans, and the download and cache jobs the page polls
#:   by id;
#: * the monitor, whose numbers the home process holds;
#: * the package factory's builds, and its installs into the account's store.
HOME_ROUTES = (
    ("^~ /api/discovery/", "Discovery's searches, limits, scans and jobs"),
    ("= /api/monitor", "The monitor"),
    ("^~ /api/monitor/", "The monitor"),
    ("^~ /api/packages/factory/", "The package factory's builds and installs"),
)

#: Never through a proxy the environment names: every server here is local.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def nginx_path() -> Optional[str]:
    """nginx on ``PATH``, or None."""
    return shutil.which("nginx")


def refuse_without_nginx(processes: int) -> None:
    """Stop a start of *processes* backend processes, more than one, on a host
    with no nginx on ``PATH``."""
    if processes > 1 and nginx_path() is None:
        raise SystemExit(
            f"Refusing to start: --backend-processes {processes} runs the backend processes behind "
            "nginx, and nginx is not on PATH. Install nginx (the Docker image has it), or start one "
            "backend process."
        )


def router_folder(environ: Mapping[str, str] | None = None) -> Path:
    """The router's folder: in ``CURIO_STATE_DIR``, else in ``.curio`` of the
    folder Curio starts from, as every server's state."""
    environ = os.environ if environ is None else environ
    launch = environ.get("CURIO_LAUNCH_CWD") or os.getcwd()
    state = environ.get("CURIO_STATE_DIR")
    return (Path(launch, state) if state else Path(launch, ".curio")) / ROUTER_FOLDER


def internal_ports(count: int) -> list[int]:
    """*count* ports of 127.0.0.1 no server holds now, one for each backend
    process, which the kernel picks."""
    held: list[socket.socket] = []
    try:
        for _ in range(count):
            probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            held.append(probe)
            probe.bind(("127.0.0.1", 0))
        return [probe.getsockname()[1] for probe in held]
    finally:
        for probe in held:
            probe.close()


def _listen(host: str, port: int) -> str:
    if ":" in host:
        # IPv4 too, as the backend serves on such a host.
        return f"listen [{host}]:{port} ipv6only=off backlog=4096;"
    return f"listen {host}:{port} backlog=4096;"


def nginx_config(*, host: str, port: int, ports: Sequence[int], folder) -> str:
    """nginx's config for the backend processes serving at *ports* on
    127.0.0.1, by number, behind nginx on *host*:*port*, its files in
    *folder*. Every two-hex-digit start of a dataflow id goes to the process
    ``shard_of`` names."""
    count = len(ports)
    folder = Path(folder)
    leads: dict[int, list[str]] = {number: [] for number in range(count)}
    for lead in range(256):
        prefix = f"{lead:02x}"
        leads[backend_processes.shard_of(f"{prefix}000000-0000-4000-8000-000000000000", count)].append(prefix)
    owners = "\n".join(
        f'        "~*^(?:{"|".join(prefixes)})" curio_backend_{number};'
        for number, prefixes in leads.items() if prefixes
    )
    upstreams = "\n\n".join(
        f"    upstream curio_backend_{number} {{\n"
        f"        server 127.0.0.1:{backend_port};\n"
        f"        keepalive 32;\n"
        f"        keepalive_timeout {UPSTREAM_IDLE_S}s;\n"
        f"        keepalive_requests 10000;\n"
        f"    }}"
        for number, backend_port in enumerate(ports)
    )
    homes = "\n".join(
        f"        # {why}.\n"
        f"        location {location} {{\n"
        f"            proxy_pass http://curio_backend_0;\n"
        f"        }}"
        for location, why in HOME_ROUTES
    )
    return f"""\
# The router of a start of {count} backend process(es), written by
# curio.py start --backend-processes at each start (utk_curio/cli/backend_group.py):
# each request and socket goes to the backend process that owns its dataflow.
daemon off;
master_process on;
worker_processes 4;
worker_rlimit_nofile 65536;
pid "{folder / 'nginx.pid'}";
error_log stderr warn;

events {{
    worker_connections 16384;
}}

http {{
    access_log off;
    server_tokens off;
    client_body_temp_path "{folder / 'client_body'}";
    proxy_temp_path "{folder / 'proxy'}";
    fastcgi_temp_path "{folder / 'fastcgi'}";
    uwsgi_temp_path "{folder / 'uwsgi'}";
    scgi_temp_path "{folder / 'scgi'}";

    # No cap on a body: dataset imports, and model packages of 2 GiB.
    client_max_body_size 0;
    # A connection that sends no request head goes at the backend's own deadline.
    client_header_timeout {REQUEST_START_TIMEOUT_S}s;
    # An hour between two reads or writes: long uploads and downloads, turn
    # and run event streams, and /processPythonCode's keepalive spaces.
    client_body_timeout 3600s;
    send_timeout 3600s;
    large_client_header_buffers 8 64k;

    # Nothing held either way: an upload reaches its backend as it comes, and
    # each event of a stream reaches the page as it comes.
    proxy_http_version 1.1;
    proxy_buffering off;
    proxy_request_buffering off;
    proxy_read_timeout 3600s;
    proxy_send_timeout 3600s;
    proxy_set_header Host $http_host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection $curio_connection;

    map $http_upgrade $curio_connection {{
        default upgrade;
        "" "";
    }}

    # The route key: the dataflow the {ROUTE_HEADER} header names, else the
    # {ROUTE_QUERY} query argument (a socket's handshake), else a dataflow id
    # after /projects/ or /dataflows/ in the path.
    map {_HEADER_VARIABLE} $curio_key {{
        "" $curio_key_from_query;
        default {_HEADER_VARIABLE};
    }}
    map {_QUERY_VARIABLE} $curio_key_from_query {{
        "" $curio_key_from_path;
        default {_QUERY_VARIABLE};
    }}
    map $uri $curio_key_from_path {{
        "~/(?:projects|dataflows)/(?<curio_path_id>[0-9A-Fa-f]{{8}}-[0-9A-Fa-f]{{4}}-[0-9A-Fa-f]{{4}}-[0-9A-Fa-f]{{4}}-[0-9A-Fa-f]{{12}})(?:/|$)" $curio_path_id;
        default "";
    }}
    # The key's first two hex digits name its process (backend_processes.shard_of);
    # any other key, and none, the home process.
    map $curio_key $curio_backend {{
        default curio_backend_0;
{owners}
    }}

{upstreams}

    server {{
        {_listen(host, port)}

        # The backends' calls to each other (collaboration/owner_calls.py)
        # never come through here.
        location ^~ /internal/ {{
            return 404;
        }}

        # Route families the home process serves whatever dataflow they name:
{homes}

        location / {{
            proxy_pass http://$curio_backend;
        }}
    }}
}}
"""


def backend_environment(*, process: int, ports: Sequence[int], boot_id: str, token: str, proxy_hops: int,
                        environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """The environment backend process *process* of a start of several
    starts with: the launcher's own, its number, the count, the start's boot
    id, every process's port and the start's secret, its own port on
    127.0.0.1, no reloader, and *proxy_hops* proxies in front of it."""
    environ = os.environ if environ is None else environ
    env = dict(environ)
    env.update(backend_processes.environment(
        process=process, processes=len(ports), boot_id=boot_id, ports=ports, token=token,
    ))
    env.update({
        "FLASK_BACKEND_HOST": "127.0.0.1",
        "FLASK_BACKEND_PORT": str(ports[process]),
        "FLASK_USE_RELOADER": "0",
        "CURIO_PROXY_HOPS": str(proxy_hops),
    })
    return env


def start_backend_group(host, port, processes: int) -> None:
    """Start *processes* backend processes and nginx in front of them on
    *host*:*port*, on a thread of their own, after freeing that port and
    preparing the database once."""
    nginx = nginx_path()
    if nginx is None:
        refuse_without_nginx(processes)
    port = int(port)
    services._kill_port(port)
    # Once, before any process starts: under --testing it empties the database.
    services.prepare_backend_database()
    threading.Thread(target=_run, args=(host, port, processes, nginx), name="backend-group", daemon=True).start()


def _run(host: str, port: int, processes: int, nginx: str) -> None:
    started = boot(host, port, processes, nginx=nginx)
    if started:
        watch(started)


def _proxy_hops() -> int:
    """The proxies in front of the backend that add the visitor's address to
    ``X-Forwarded-For`` (``--proxy-hops``)."""
    return max(0, int(os.environ.get("CURIO_PROXY_HOPS") or 0))


def _reach(host: str) -> str:
    """Where this machine reaches a server listening on *host*."""
    return "127.0.0.1" if host in ("", "0.0.0.0", "::") else host


def _answers(name: str, host: str, port: int, process) -> bool:
    """Whether the server *name*, *process*, comes to answer ``/health`` on
    *host*:*port* within :data:`BOOT_TIMEOUT_S`; False as soon as it exits, or
    when the launcher stops."""
    address = f"[{host}]" if ":" in host else host
    deadline = time.monotonic() + BOOT_TIMEOUT_S
    while time.monotonic() < deadline and not shutdown_flag.is_set():
        if process.poll() is not None:
            return False
        try:
            with _OPENER.open(f"http://{address}:{port}/health", timeout=5) as answer:
                if answer.status == 200:
                    return True
        except OSError:
            pass  # not serving yet: asked again below
        time.sleep(0.5)
    return False


def _stop(why: str) -> None:
    log_error(f"[backend-group] {why}: stopping every server")
    clean_shutdown(1)


def _kept(process):
    """Keep *process* among the servers the launcher stops, and stop it at
    once when the launcher began to stop meanwhile."""
    lifecycle.processes.append(process)
    if shutdown_flag.is_set():
        process.terminate()
    return process


def boot(host: str, port: int, processes: int, *, nginx: str):
    """Start the home process and wait until it answers, then the others and
    wait for them, then nginx in front of them on *host*:*port*, with the
    config written in :func:`router_folder`. ``[(name, process)]`` of every
    server it started, in that order; None when one never answered or nginx
    refused its config, after stopping every server."""
    port = int(port)
    ports = internal_ports(processes)
    boot_id = str(uuid.uuid4())
    token = secrets.token_urlsafe(32)
    hops = _proxy_hops() + 1
    log_info(f"[backend-group] Starting {processes} backend processes on 127.0.0.1 ports "
             f"{', '.join(str(p) for p in ports)}, behind nginx on {host}:{port}...", COLOR_BACKEND, 0)
    started: list = []

    def start(number: int):
        name = f"Backend {number}"
        env = backend_environment(process=number, ports=ports, boot_id=boot_id, token=token, proxy_hops=hops)
        process = _kept(services.spawn_backend(env, name))
        started.append((name, process))
        return number, name, process

    _, name, home = start(0)
    if not _answers(name, "127.0.0.1", ports[0], home):
        _stop("the home process, backend process 0, never answered /health")
        return None
    others = [start(number) for number in range(1, processes)]
    for number, name, process in others:
        if not _answers(name, "127.0.0.1", ports[number], process):
            _stop(f"backend process {number} never answered /health")
            return None

    folder = router_folder()
    folder.mkdir(parents=True, exist_ok=True)
    # nginx's workers reach the folders it makes here, and list nothing.
    os.chmod(folder, 0o711)
    config = folder / CONFIG_FILE
    config.write_text(nginx_config(host=host, port=port, ports=ports, folder=folder), encoding="utf-8")
    # nginx holds none of the backends' secrets.
    env = without_backend_only(os.environ)
    checked = subprocess.run([nginx, "-t", "-c", str(config), "-e", "stderr"],
                             capture_output=True, text=True, env=env)
    if checked.returncode != 0:
        for line in f"{checked.stdout}{checked.stderr}".splitlines():
            log_error(f"[nginx -t] {line}")
        _stop(f"nginx refused its config, {config}")
        return None
    proxy = _kept(subprocess.Popen([nginx, "-c", str(config), "-e", "stderr"],
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env))
    threading.Thread(target=stream_output, args=(proxy, "nginx", COLOR_BACKEND), daemon=True).start()
    started.append(("nginx", proxy))
    if not _answers("nginx", _reach(host), port, proxy):
        _stop("nginx never answered /health")
        return None
    log_info(f"[backend-group] {processes} backend processes answer behind nginx on {host}:{port} "
             f"(boot id {boot_id}, config {config})", COLOR_BACKEND, 0)
    return started


def watch(started) -> None:
    """Stop every server, and the launcher with an error, as soon as one of
    *started*, ``[(name, process)]``, exits while the launcher is not
    stopping."""
    while not shutdown_flag.is_set():
        for name, process in started:
            code = process.poll()
            if code is not None:
                if not shutdown_flag.is_set():
                    _stop(f"{name} exited with code {code}")
                return
        time.sleep(1)
