"""Starting the frontend, backend and sandbox servers, the database they use,
and freeing their ports."""

import os
import platform
import subprocess
import sys
import threading
import time

from utk_curio.cli.dependencies import _ensure_root_node_modules, _skip_dep_install
from utk_curio.cli.environment import _is_testing
from utk_curio.cli.frontend_build import (
    _frontend_dir,
    _frontend_is_built,
    _frontend_needs_build,
    _frontend_tree_is_stale,
    check_install_build,
)
from utk_curio.cli.lifecycle import clean_shutdown, shell_required, stream_output
from utk_curio.cli.logs import (
    COLOR_BACKEND,
    COLOR_FRONTEND,
    COLOR_SANDBOX,
    log_error,
    log_info,
    log_warning,
    logger,
)


def start_frontend(host="localhost", port=8080, force_rebuild=False, no_server=False, base_path=""):
    log_info(f"Starting frontend on {host}:{port}...", COLOR_FRONTEND, 0)

    _kill_port(int(port))

    # Build from source when something needs it: --dev compiles through
    # webpack-dev-server, --force-rebuild was asked for, and a checkout with no
    # dist/ has nothing for the static server to serve. A pip install and the
    # shipped container both arrive with dist/ already built, so neither runs npm.
    original_dir = os.getcwd()
    if (
        os.getenv("CURIO_DEV") == "1"
        or force_rebuild
        or _frontend_needs_build()
        or _frontend_tree_is_stale()
    ):
        check_install_build("frontend/urban-workflows/", force_rebuild=force_rebuild)
        os.chdir(original_dir)

    # If we're not starting the server, just exit here
    if no_server:
        log_info(f"[Frontend] Build completed with --force-rebuild, server not started.", COLOR_FRONTEND, 0)
        return None

    dir = "frontend/urban-workflows/"
    script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    project_root = os.path.abspath(os.path.join(script_dir, ".."))
    abs_dir = os.path.abspath(dir) if os.path.isabs(dir) else os.path.join(script_dir, dir)
    os.chdir(abs_dir)
    log_info(f"[Frontend] Current working directory: {os.getcwd()}", COLOR_FRONTEND, 0)

    try:

        if os.environ.get("CURIO_DEV") == "1":

            # --port pins the requested port; otherwise webpack-dev-server
            # auto-bumps to the next free port when ours is held.
            start_cmd = ["npm", "run", "start", "--", "--port", str(port)]
            if os.environ.get("CURIO_NO_OPEN"):
                start_cmd.append("--no-open")
            process = subprocess.Popen(
                start_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                shell=shell_required,
                env={**os.environ}
            )
            threading.Thread(target=stream_output, args=(process, "Frontend", COLOR_FRONTEND), daemon=True).start()

            # Check if process exited unexpectedly
            if process.poll() is not None:
                log_error(f"[Frontend] Error: Server exited with code {process.returncode}")
                log_error(f"[Frontend] Error Output:\n{process.stderr.read()}")
                clean_shutdown()

        else:
            if not _frontend_is_built():
                # Without this the static server answers 404 to every request
                # and the browser shows a blank page with no explanation.
                log_error(
                    "[Frontend] Nothing built to serve at "
                    f"{os.path.join(_frontend_dir(), 'dist')}. Build it with "
                    "'python curio.py --force-rebuild', or run with --dev to "
                    "compile through the webpack dev server."
                )
                clean_shutdown()
                return None

            env = os.environ.copy()
            env = {
                **env,
                "PYTHONPATH": project_root + os.pathsep + env.get("PYTHONPATH", ""),
            }
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-u",
                    "-c",
                    (
                        "from utk_curio.cli.static_server import run_spa_static_server; "
                        f"run_spa_static_server('dist', {port}, {base_path!r}, "
                        f"{os.environ.get('BACKEND_URL', '')!r})"
                    ),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                shell=shell_required,
                env=env,
            )
            threading.Thread(
                target=stream_output,
                args=(process, "Frontend", COLOR_FRONTEND),
                daemon=True,
            ).start()
            log_info(
                f"[Frontend] Serving static files with SPA fallback.",
                COLOR_FRONTEND,
                0,
            )

    except subprocess.CalledProcessError as e:
        log_error(f"[Frontend] Exit Code: {e.returncode}")
        log_error(f"[Frontend] Output:\n{e.output}")
        log_error(f"[Frontend] Error Output:\n{e.stderr}")
    except subprocess.TimeoutExpired:
        log_error(f"[Frontend] Error: Server took too long to start.")
        clean_shutdown()
    except Exception as e:
        log_error(f"[Frontend] Unexpected Error: {str(e)}")
        clean_shutdown()

    log_info(f"[Frontend] Frontend server started successfully on {host}:{port}.", COLOR_FRONTEND, 0)
    os.chdir(original_dir)
    return process


def prepare_backend_database():
    project_root = os.path.abspath(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".."))

    testing = _is_testing()
    launch_dir = os.environ.get("CURIO_LAUNCH_CWD") or os.getcwd()
    # Must agree with config._resolve_database_uri, or the wipe below hits a
    # file the backend never opens.
    state_dir = os.environ.get("CURIO_STATE_DIR") or os.path.join(launch_dir, ".curio")
    db_dir = os.path.join(state_dir, "test") if testing else state_dir

    if not os.path.exists(db_dir):
        os.makedirs(db_dir)

    log_info(f"[Backend] Preparing backend database...", COLOR_BACKEND, 0)
    try:
        env = {
            **os.environ,
            "FLASK_APP": "utk_curio.backend.app:create_app",
            "PYTHONPATH": project_root + os.pathsep + os.environ.get("PYTHONPATH", ""),
        }
        # Make sure the `flask db upgrade` subprocess targets the test
        # sqlite file (not the dev one). backend/config._resolve_database_uri
        # already prefers DATABASE_URL_TEST when CURIO_TESTING is set, but
        # we set both explicitly so intent is obvious in the child env.
        if testing:
            test_sqla = os.path.join(db_dir, "urban_workflow_test.db")
            test_url = os.environ.get(
                "DATABASE_URL_TEST", f"sqlite:///{test_sqla}"
            )
            env["CURIO_TESTING"] = "1"
            env["CURIO_LAUNCH_CWD"] = launch_dir
            env["DATABASE_URL_TEST"] = test_url
            env["DATABASE_URL"] = test_url
            # Testing wipes the SQLA file so every `curio start` lands on
            # an empty-but-migrated DB, like Django's TEST_RUNNER.
            # WAL sidecars too: a stale -wal next to a fresh file is ignored by
            # SQLite but confuses anyone reading the directory.
            for suffix in ("", "-wal", "-shm"):
                try:
                    os.remove(test_sqla + suffix)
                except FileNotFoundError:
                    pass

        # `flask db upgrade` is idempotent — alembic skips already-applied
        # revisions. Running it on every startup avoids the "schema is
        # stale" class of deploy bug.
        result = subprocess.run(
            ["flask", "db", "upgrade", "--directory", "utk_curio/backend/migrations"],
            check=True, cwd=project_root, env=env,
            capture_output=True, text=True,
        )
        if result.stdout.strip():
            log_info(result.stdout.strip(), COLOR_BACKEND, 2)
        if result.stderr.strip():
            log_info(result.stderr.strip(), COLOR_BACKEND, 2)
        log_info(f"[Backend] Database initialized successfully.", COLOR_BACKEND, 0)
    except subprocess.CalledProcessError as e:
        log_error(f"[Backend] Database migration failed (exit code {e.returncode}).")
        if e.stdout.strip():
            log_error(e.stdout.strip())
        if e.stderr.strip():
            log_error(e.stderr.strip())
        clean_shutdown()
    except Exception as e:
        log_error(f"[Backend] Failed to initialize the database: {e}")
        clean_shutdown()
    

def _kill_port(port: int) -> None:
    """Kill any process occupying `port` so the backend can bind (cross-platform)."""
    if os.environ.get("PYTEST_CURRENT_TEST"):
        raise RuntimeError("INTERCEPT PROOF: the real _kill_port ran inside a test")
    import re, signal as _signal
    try:
        if platform.system() == "Windows":
            out = subprocess.check_output(
                ["netstat", "-ano"], text=True, stderr=subprocess.DEVNULL
            )
            for line in out.splitlines():
                if f":{port} " in line and "LISTENING" in line:
                    m = re.search(r"\s+(\d+)\s*$", line)
                    if m:
                        pid = int(m.group(1))
                        log_warning(f"[Backend] Port {port} in use by PID {pid}. Terminating stale process.")
                        subprocess.run(
                            ["taskkill", "/F", "/PID", str(pid)],
                            capture_output=True,
                        )
        else:
            out = subprocess.check_output(
                ["lsof", "-t", f"-i:{port}"], text=True, stderr=subprocess.DEVNULL
            )
            pids = []
            for pid_str in out.strip().splitlines():
                pid = int(pid_str.strip())
                if pid:
                    log_warning(f"[Backend] Port {port} in use by PID {pid}. Terminating stale process.")
                    try:
                        os.kill(pid, _signal.SIGTERM)
                        pids.append(pid)
                    except ProcessLookupError:
                        # PID exited between lsof and SIGTERM; nothing to wait for.
                        logger.debug(
                            "PID %s exited before SIGTERM on port %s; skipping wait list",
                            pid,
                            port,
                            exc_info=True,
                        )

            # Wait up to 3 s for the processes to exit; escalate to SIGKILL if needed.
            if pids:
                deadline = time.time() + 3.0
                remaining = list(pids)
                while remaining and time.time() < deadline:
                    time.sleep(0.1)
                    still_alive = []
                    for pid in remaining:
                        try:
                            os.kill(pid, 0)   # 0 = probe only
                            still_alive.append(pid)
                        except ProcessLookupError:
                            # PID exited between checks; treat as no longer alive.
                            logger.debug(
                                "PID %s no longer alive while waiting for port %s",
                                pid,
                                port,
                                exc_info=True,
                            )
                    remaining = still_alive
                for pid in remaining:
                    try:
                        log_warning(f"[Backend] PID {pid} still alive after SIGTERM; sending SIGKILL.")
                        os.kill(pid, _signal.SIGKILL)
                    except ProcessLookupError:
                        logger.debug(
                            "PID %s exited before SIGKILL on port %s",
                            pid,
                            port,
                            exc_info=True,
                        )
                # Brief pause to let the kernel release the port after SIGKILL.
                time.sleep(0.2)
    except subprocess.CalledProcessError:
        pass
    except Exception as e:
        log_warning(f"[Backend] Could not check port {port}: {e}")


def start_backend(host, port, no_server=False):
    _kill_port(int(port))
    log_info(f"Starting backend on {host}:{port}...", COLOR_BACKEND, 0)

    prepare_backend_database()

    # If we're only initializing the database, skip starting the server
    if no_server:
        log_info(f"[Backend] Database initialization completed with --force-db-init, server not started.", COLOR_BACKEND, 0)
        return None

    script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    project_root = os.path.abspath(os.path.join(script_dir, ".."))
    # backend_server = os.path.join(script_dir, "backend", "server.py")
    env = os.environ.copy()
    env = {**os.environ, "PYTHONPATH": project_root + os.pathsep + env.get("PYTHONPATH", "")}

    process = subprocess.Popen(
        [sys.executable, "-u", "-m", "backend.server"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        cwd=script_dir,
        env=env
    )
    threading.Thread(target=stream_output, args=(process, "Backend", COLOR_BACKEND), daemon=True).start()
    return process


def start_sandbox(host, port):
    _kill_port(int(port))
    log_info(f"Starting sandbox on {host}:{port}...", COLOR_SANDBOX, 0)

    script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    project_root = os.path.abspath(os.path.join(script_dir, ".."))
    if not _skip_dep_install():
        _ensure_root_node_modules(project_root)
    # sandbox_server = os.path.join(script_dir, "sandbox", "server.py")
    env = os.environ.copy()
    env = {**os.environ, "PYTHONPATH": project_root + os.pathsep + env.get("PYTHONPATH", "")}

    process = subprocess.Popen(
        [sys.executable, "-u", "-m", "sandbox.server"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        cwd=script_dir,
        env=env
    )
    threading.Thread(target=stream_output, args=(process, "Sandbox", COLOR_SANDBOX), daemon=True).start()
    return process
