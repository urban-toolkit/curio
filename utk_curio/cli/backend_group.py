"""Several backend processes behind nginx (tmp/sharded-backend prototype).

``curio.py start --backend-processes N`` with N over 1 (or 1 with
``CURIO_BACKEND_ROUTER`` set, so a measurement at 1 goes through nginx as the
others do): the launcher prepares the database once, starts process 0 (home)
on an internal port of 127.0.0.1 and waits for it, since it alone does the
startup work, then the others, each with ``CURIO_SHARD``, ``CURIO_SHARDS``,
``CURIO_SHARD_PORTS`` and one ``CURIO_BOOT_ID``; then nginx on the backend's
public host and port, which sends each request and socket to the process that
owns its dataflow (``utk_curio/common/shards.py``). If any of them exits, every
server stops. The boot time, from the launcher's start to all of them
answering, is logged as a ``[backend-group]`` line.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import uuid

from utk_curio.cli import lifecycle
from utk_curio.cli.lifecycle import clean_shutdown, shutdown_flag, stream_output
from utk_curio.cli.logs import COLOR_BACKEND, log_error, log_info
from utk_curio.cli.services import _kill_port, prepare_backend_database
from utk_curio.common.shards import shard_of

#: Set, it puts nginx in front of one process too.
FORCE_ROUTER = "CURIO_BACKEND_ROUTER"
#: The first internal port is the public one plus this, unless
#: ``CURIO_SHARD_BASE_PORT`` names it.
PORT_OFFSET = 1000
#: How long one process, or nginx, may take to answer ``/health``.
BOOT_TIMEOUT_S = 900.0

_IMPORTED_AT = time.time()

_TEMPLATE = """\
# Written by curio.py start --backend-processes (tmp/sharded-backend prototype):
# each request and socket goes to the backend process that owns its dataflow.
daemon off;
master_process on;
@USER@worker_processes 4;
worker_rlimit_nofile 65536;
pid @FOLDER@/nginx.pid;
error_log stderr warn;

events {
    worker_connections 16384;
}

http {
    access_log off;
    client_body_temp_path @FOLDER@/client_body;
    proxy_temp_path @FOLDER@/proxy;
    fastcgi_temp_path @FOLDER@/fastcgi;
    uwsgi_temp_path @FOLDER@/uwsgi;
    scgi_temp_path @FOLDER@/scgi;

    client_max_body_size 0;
    client_header_timeout 60s;
    client_body_timeout 3600s;
    send_timeout 3600s;
    keepalive_timeout 75s;
    keepalive_requests 100000;
    large_client_header_buffers 8 64k;

    proxy_http_version 1.1;
    proxy_buffering off;
    proxy_request_buffering off;
    proxy_connect_timeout 30s;
    proxy_read_timeout 3600s;
    proxy_send_timeout 3600s;
    proxy_set_header Host $http_host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection $curio_connection;

    map $http_upgrade $curio_connection {
        default upgrade;
        "" "";
    }

    # The route key: the X-Curio-Dataflow header, else the dataflow query
    # argument (a socket's handshake), else a uuid after /projects/ or
    # /dataflows/ in the path. Its first two hex digits pick the process
    # (shard_of in utk_curio/common/shards.py); no key goes to home.
    map $http_x_curio_dataflow $curio_key {
        "~^(?<curio_by_header>[0-9a-fA-F]{2})" $curio_by_header;
        default $curio_key_by_query;
    }
    map $arg_dataflow $curio_key_by_query {
        "~^(?<curio_by_query>[0-9a-fA-F]{2})" $curio_by_query;
        default $curio_key_by_path;
    }
    map $uri $curio_key_by_path {
        "~/(?:projects|dataflows)/(?<curio_by_path>[0-9a-fA-F]{2})[0-9a-fA-F]{6}-[0-9a-fA-F]{4}-" $curio_by_path;
        default "";
    }
    map $curio_key $curio_upstream {
        default curio_shard_0;
@PREFIXES@
    }

@UPSTREAMS@

    server {
        listen @LISTEN@ backlog=4096;
        location / {
            proxy_pass http://$curio_upstream;
        }
    }
}
"""


def wanted(processes) -> bool:
    """Whether this start puts nginx in front of its backend processes."""
    return int(processes or 1) > 1 or bool(os.environ.get(FORCE_ROUTER))


def nginx_config(listen_host: str, listen_port: int, ports: list, folder: str, *, run_as_root: bool) -> str:
    """nginx's config: every two-hex-digit prefix of a dataflow id to the
    upstream of the process :func:`shard_of` names, each process's upstream
    on its internal port, and the public listener."""
    count = len(ports)
    prefixes = "\n".join(
        f"        {prefix:02x} curio_shard_{shard_of(f'{prefix:02x}000000-0000-4000-8000-000000000000', count)};"
        for prefix in range(256)
    )
    upstreams = "\n".join(
        f"    upstream curio_shard_{shard} {{\n"
        f"        server 127.0.0.1:{port};\n"
        f"        keepalive 32;\n"
        f"        keepalive_timeout 20s;\n"
        f"        keepalive_requests 100000;\n"
        f"    }}"
        for shard, port in enumerate(ports)
    )
    return (_TEMPLATE
            .replace("@USER@", "user root root;\n" if run_as_root else "")
            .replace("@FOLDER@", folder)
            .replace("@PREFIXES@", prefixes)
            .replace("@UPSTREAMS@", upstreams)
            .replace("@LISTEN@", f"{listen_host}:{listen_port}"))


def _state_dir() -> str:
    launch = os.environ.get("CURIO_LAUNCH_CWD") or os.getcwd()
    return os.environ.get("CURIO_STATE_DIR") or os.path.join(launch, ".curio")


def _launcher_started() -> float:
    try:
        import psutil

        return psutil.Process(os.getpid()).create_time()
    except Exception:  # noqa: BLE001 - the import time is near enough
        return _IMPORTED_AT


def start_backend_group(host: str, port, processes) -> None:
    """Start the backend processes and nginx in front of them, on a thread of
    their own: the sandbox and the page server start meanwhile, as they do
    beside one backend."""
    count = max(1, int(processes or 1))
    port = int(port)
    nginx = shutil.which("nginx") or ("/usr/sbin/nginx" if os.path.exists("/usr/sbin/nginx") else None)
    if nginx is None:
        log_error("[Backend] --backend-processes over 1 needs nginx, which is not installed here.")
        clean_shutdown()
        return
    base = int(os.environ.get("CURIO_SHARD_BASE_PORT") or port + PORT_OFFSET)
    ports = [base + shard for shard in range(count)]
    _kill_port(port)
    for internal in ports:
        _kill_port(internal)
    log_info(f"Starting {count} backend process(es) on 127.0.0.1:{ports[0]}-{ports[-1]} behind nginx "
             f"on {host}:{port}...", COLOR_BACKEND, 0)
    # Once, before any process starts: under --testing it deletes the database.
    prepare_backend_database()
    threading.Thread(target=_boot, args=(host, port, ports, nginx), name="backend-group", daemon=True).start()


def _spawn(shard: int, ports: list, boot_id: str) -> subprocess.Popen:
    script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    project_root = os.path.abspath(os.path.join(script_dir, ".."))
    env = dict(os.environ)
    env["PYTHONPATH"] = project_root + os.pathsep + env.get("PYTHONPATH", "")
    env.update({
        "CURIO_SHARD": str(shard),
        "CURIO_SHARDS": str(len(ports)),
        "CURIO_SHARD_PORTS": ",".join(str(port) for port in ports),
        "CURIO_BOOT_ID": boot_id,
        "FLASK_BACKEND_HOST": "127.0.0.1",
        "FLASK_BACKEND_PORT": str(ports[shard]),
        # nginx adds the visitor's address to X-Forwarded-For: the limits per
        # address read the same address as without it.
        "CURIO_PROXY_HOPS": str(int(env.get("CURIO_PROXY_HOPS") or 0) + 1),
    })
    process = subprocess.Popen(
        [sys.executable, "-u", "-m", "backend.server"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=script_dir, env=env,
    )
    lifecycle.processes.append(process)
    threading.Thread(target=stream_output, args=(process, f"Backend {shard}", COLOR_BACKEND), daemon=True).start()
    return process


def _healthy(host: str, port: int, process: subprocess.Popen) -> bool:
    """Whether *process* came to answer ``/health`` on *host*:*port* in
    :data:`BOOT_TIMEOUT_S`; False as soon as it exits."""
    deadline = time.time() + BOOT_TIMEOUT_S
    while time.time() < deadline and not shutdown_flag.is_set():
        if process.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(f"http://{host}:{port}/health", timeout=5) as answer:
                if answer.status == 200:
                    return True
        except OSError:
            pass  # not up yet
        time.sleep(0.5)
    return False


def _watch(watched: list) -> None:
    """Stop every server as soon as one of *watched* exits."""
    while not shutdown_flag.is_set():
        for name, process in list(watched):
            code = process.poll()
            if code is not None and not shutdown_flag.is_set():
                log_error(f"[{name}] exited with code {code}: stopping every server")
                clean_shutdown()
                return
        time.sleep(1)


def _stop(why: str) -> None:
    log_error(f"[backend-group] {why}: stopping every server")
    clean_shutdown()


def _boot(host: str, port: int, ports: list, nginx: str) -> None:
    started = _launcher_started()
    boot_id = str(uuid.uuid4())
    watched: list = []
    threading.Thread(target=_watch, args=(watched,), name="backend-group-watch", daemon=True).start()
    try:
        home = _spawn(0, ports, boot_id)
        watched.append(("Backend 0", home))
        if not _healthy("127.0.0.1", ports[0], home):
            return _stop("home (process 0) never answered /health")
        home_at = time.time()
        others = []
        for shard in range(1, len(ports)):
            process = _spawn(shard, ports, boot_id)
            watched.append((f"Backend {shard}", process))
            others.append((shard, process))
        for shard, process in others:
            if not _healthy("127.0.0.1", ports[shard], process):
                return _stop(f"process {shard} never answered /health")
        all_at = time.time()
        folder = os.path.join(_state_dir(), "nginx")
        for name in ("", "client_body", "proxy", "fastcgi", "uwsgi", "scgi"):
            os.makedirs(os.path.join(folder, name), exist_ok=True)
        config = os.path.join(folder, "nginx.conf")
        run_as_root = hasattr(os, "geteuid") and os.geteuid() == 0
        with open(config, "w", encoding="utf-8") as out:
            out.write(nginx_config(host, port, ports, folder, run_as_root=run_as_root))
        check = subprocess.run([nginx, "-t", "-c", config, "-e", "stderr"], capture_output=True, text=True)
        for line in (check.stdout + check.stderr).splitlines():
            log_info(f"[nginx -t] {line}", COLOR_BACKEND, 0)
        if check.returncode != 0:
            return _stop(f"nginx refused its config, {config}")
        proxy = subprocess.Popen([nginx, "-c", config, "-e", "stderr"],
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        lifecycle.processes.append(proxy)
        threading.Thread(target=stream_output, args=(proxy, "nginx", COLOR_BACKEND), daemon=True).start()
        watched.append(("nginx", proxy))
        probe_host = "127.0.0.1" if host in ("0.0.0.0", "", "::") else host
        if not _healthy(probe_host, port, proxy):
            return _stop("nginx never answered /health")
        done = time.time()
        log_info(
            f"[backend-group] {len(ports)} backend process(es) behind nginx answer /health "
            f"{done - started:.1f} s after the launcher started (home at {home_at - started:.1f} s, "
            f"all processes at {all_at - started:.1f} s); ports {ports}, boot id {boot_id}",
            COLOR_BACKEND, 0,
        )
    except Exception as exc:  # noqa: BLE001 - a launcher that cannot boot stops everything
        _stop(f"the backend processes could not start: {type(exc).__name__}: {exc}")
