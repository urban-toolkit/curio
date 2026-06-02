#!/usr/bin/env python3

import subprocess
import os
import sys
import time
import threading
import queue
import argparse
import signal
import platform
import logging
import shutil

from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

output_queue = queue.Queue()
shell_required = platform.system() == "Windows"

# Ensure unbuffered output (immediate print)
os.environ["PYTHONUNBUFFERED"] = "1"
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

# ANSI color codes for clear distinction
COLOR_RESET = "\033[0m"
COLOR_FRONTEND = "\033[96m"  # Cyan
COLOR_BACKEND = "\033[92m"   # Green
COLOR_SANDBOX = "\033[93m"   # Yellow

shutdown_flag = threading.Event()
processes = []
file_logger = None
verbosity = 1

def setup_logging():
    log_dir = Path(".curio")
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / "messages.log"

    logging.basicConfig(
        filename=log_file,
        filemode="w",
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        level=logging.DEBUG  # Capture all log levels in file
    )

    # Create helper log function for non-terminal info
    file_logger = logging.getLogger("file_only")
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(logging.INFO)
    file_logger.addHandler(file_handler)
    file_logger.propagate = False

def log_always(message, verbose_level = 1):
    logging.info(message)
    if verbosity >= verbose_level or verbose_level == 0:
        print(f"{message}")

def log_info(message, color, verbose_level = 1):
    logging.info(message)
    if verbosity >= verbose_level or verbose_level == 0:
        print(f"{color}{message}{COLOR_RESET}")
            
def log_warning(message):
    """Logs a warning message to both the log file and terminal."""
    logging.warning(message)
    print(f"\033[93m[WARNING]\033[0m {message}", file=sys.stderr)

def log_error(message):
    """Logs an error message to both the log file and terminal."""
    logging.error(message)
    print(f"\033[91m[ERROR]\033[0m {message}", file=sys.stderr)

def stream_output(process, name, color):
    """Safely stream subprocess output."""
    try:
        while process.poll() is None and not shutdown_flag.is_set():
            # Read output line by line
            line = process.stdout.readline()
            if line:
                log_info(f"[{name}] {line.strip()}", color, 2)
        
        log_info(f"[{name}] has stopped. No more output.", color, 1)
    except ValueError:
        log_error(f"[{name}] Error: Output stream closed unexpectedly.")
    finally:
        # Ensure the output streams are properly closed
        if process.stdout:
            process.stdout.close()
        if process.stderr:
            process.stderr.close()

def set_environment_variables(backend_host, backend_port, sandbox_host, sandbox_port, auth=False, no_project=False, deploy=False, with_examples=False, reseed=False, allow_publish=True, collab=False):
    """Sets the environment variables for Backend and Sandbox."""
    os.environ["FLASK_BACKEND_HOST"] = backend_host
    os.environ["FLASK_BACKEND_PORT"] = str(backend_port)
    os.environ["FLASK_SANDBOX_HOST"] = sandbox_host
    os.environ["FLASK_SANDBOX_PORT"] = str(sandbox_port)
    os.environ["CURIO_SEED_EXAMPLES"] = "1" if (with_examples or deploy) else "0"
    os.environ["CURIO_RESEED_PACKAGES"] = "1" if reseed else "0"
    os.environ["CURIO_ALLOW_FACTORY_CATALOG_PUBLISH"] = "1" if allow_publish else "0"
    # Respect an already-set CURIO_LAUNCH_CWD / CURIO_SHARED_DATA so the test
    # harness can point the backend at a dedicated workspace (see
    # utk_curio/backend/tests/conftest.py). Only fall back to cwd otherwise.
    os.environ["CURIO_LAUNCH_CWD"] = os.environ.get(
        "CURIO_LAUNCH_CWD"
    ) or os.getcwd()
    os.environ["CURIO_SHARED_DATA"] = os.environ.get(
        "CURIO_SHARED_DATA"
    ) or str(Path("./.curio/data").resolve())

    if deploy:
        os.environ["CURIO_NO_AUTH"] = "0"
        os.environ["CURIO_NO_PROJECT"] = "0"
    else:
        os.environ["CURIO_NO_AUTH"] = (
            "1" if no_project else ("0" if auth else "1")
        )
        os.environ["CURIO_NO_PROJECT"] = "1" if no_project else "0"

    os.environ["ENABLE_COLLAB"] = "1" if collab else "0"

    log_always(f"Environment Variables Set:")
    log_always(f"FLASK_BACKEND_HOST={os.environ['FLASK_BACKEND_HOST']}")
    log_always(f"FLASK_BACKEND_PORT={os.environ['FLASK_BACKEND_PORT']}")
    log_always(f"FLASK_SANDBOX_HOST={os.environ['FLASK_SANDBOX_HOST']}")
    log_always(f"FLASK_SANDBOX_PORT={os.environ['FLASK_SANDBOX_PORT']}")
    log_always(f"CURIO_LAUNCH_CWD={os.environ['CURIO_LAUNCH_CWD']}")
    log_always(f"CURIO_SHARED_DATA={os.environ['CURIO_SHARED_DATA']}")
    log_always(f"CURIO_NO_AUTH={os.environ['CURIO_NO_AUTH']}")
    log_always(f"CURIO_NO_PROJECT={os.environ['CURIO_NO_PROJECT']}")
    log_always(f"CURIO_SEED_EXAMPLES={os.environ['CURIO_SEED_EXAMPLES']}")
    log_always(f"CURIO_RESEED_PACKAGES={os.environ['CURIO_RESEED_PACKAGES']}")
    log_always(f"CURIO_ALLOW_FACTORY_CATALOG_PUBLISH={os.environ['CURIO_ALLOW_FACTORY_CATALOG_PUBLISH']}")
    log_always(f"ENABLE_COLLAB={os.environ['ENABLE_COLLAB']}")

def logger():
    """
    Continuously reads from the queue and prints to the terminal.
    """
    while True:
        line = output_queue.get()
        if line is None:
            break
        log_always(line, 2)
        output_queue.task_done()


def run_spa_static_server(directory: str, port: int) -> None:
    """Serve a built SPA with index.html fallback for deep links.

    ``python -m http.server`` returns 404 for routes like ``/auth/signup`` or
    ``/workflow/<id>`` because those files do not exist on disk. Our frontend
    is a client-side router, so non-asset GETs should fall back to
    ``index.html`` instead.
    """

    dist_dir = os.path.abspath(directory)

    class SpaStaticHandler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=dist_dir, **kwargs)

        def do_GET(self):
            request_path = self.path.split("?", 1)[0].split("#", 1)[0]
            candidate = request_path.lstrip("/")
            fs_path = os.path.join(dist_dir, candidate)
            if (
                request_path not in ("", "/")
                and not os.path.exists(fs_path)
                and not os.path.splitext(candidate)[1]
            ):
                self.path = "/index.html"
            return super().do_GET()

    with ThreadingHTTPServer(("0.0.0.0", port), SpaStaticHandler) as httpd:
        httpd.serve_forever()

def check_install_build(dir, force_rebuild=False):
    # Determine the absolute path whether it is provided as relative or absolute
    script_dir = os.path.dirname(os.path.abspath(__file__))
    abs_dir = os.path.abspath(dir) if os.path.isabs(dir) else os.path.join(script_dir, dir)
    
    if not os.path.exists(abs_dir):
        raise FileNotFoundError(f"[Error] The directory '{abs_dir}' does not exist.")
    
    os.chdir(abs_dir)
    log_info(f"[Frontend] Current working directory for npm commands: {os.getcwd()}", COLOR_FRONTEND, 0)
    
    if force_rebuild:
        log_info(f"[Frontend] Force rebuilding in {dir}...", COLOR_FRONTEND)
        if os.path.exists("node_modules"):
            subprocess.run(["rm", "-rf", "node_modules"], check=True)
        if os.path.exists("dist"):
            subprocess.run(["rm", "-rf", "dist"], check=True)
        if os.path.exists("build"):
            subprocess.run(["rm", "-rf", "build"], check=True)
    
    if shutil.which("npm") is None:
        log_error("[Frontend] npm not found in PATH. Install Node.js 24 from https://nodejs.org, or via conda ('conda install -c conda-forge nodejs=24'), and make sure 'npm' is available in your terminal, then retry.")
        clean_shutdown()
        return

    if shutil.which("node") is None:
        log_error("[Frontend] node not found in PATH. Install Node.js 24 from https://nodejs.org, or via conda ('conda install -c conda-forge nodejs=24'), and make sure 'node' is available in your terminal, then retry.")
        clean_shutdown()
        return
    try:
        node_version_raw = subprocess.check_output(
            ["node", "--version"], text=True, shell=shell_required,
        ).strip()
    except Exception as e:
        log_error(f"[Frontend] Could not determine Node.js version: {e}")
        clean_shutdown()
        return
    node_major = 0
    if node_version_raw.startswith("v"):
        try:
            node_major = int(node_version_raw[1:].split(".", 1)[0])
        except ValueError:
            pass
    if node_major < 24:
        log_error(
            f"[Frontend] Node.js {node_version_raw} detected; requires Node.js 24 or newer. "
            f"Upgrade with 'conda install -c conda-forge nodejs=24' or from https://nodejs.org, then retry."
        )
        clean_shutdown()
        return

    # Check if node_modules exist, if not, run npm install
    if not os.path.exists("node_modules"):
        log_info(f"[Frontend] node_modules not found. Running npm install...", COLOR_FRONTEND, 0)
        try:
            subprocess.run(["npm", "install"], check=True, shell=shell_required)
        except subprocess.CalledProcessError as e:
            log_error(f"[Frontend] 'npm install' failed (exit code {e.returncode}). Check the output above for details.")
            clean_shutdown()
        except Exception as e:
            log_error(f"[Frontend] Failed to run 'npm install': {e}")
            clean_shutdown()
    else:
        log_info(f"[Frontend] node_modules directory already exists. Skipping npm install.", COLOR_FRONTEND, 0)

    # Check if dist/build directory exists (depending on your setup)
    build_dir = "dist" if os.path.exists("dist") else "build"
    if not os.path.exists(build_dir):
        log_info(f"[Frontend] {build_dir} directory not found. Running npm run build...", COLOR_FRONTEND, 0)
        try:
            subprocess.run(["npm", "run", "build"], check=True, shell=shell_required)
        except subprocess.CalledProcessError as e:
            log_error(f"[Frontend] 'npm run build' failed (exit code {e.returncode}). Check the output above for details.")
            clean_shutdown()
        except Exception as e:
            log_error(f"[Frontend] Failed to run 'npm run build': {e}")
            clean_shutdown()
    else:
        log_info(f"[Frontend] {build_dir} directory exists. Skipping npm run build.", COLOR_FRONTEND, 0)

def force_rebuild_frontend():
    log_info(f"[Frontend] Force rebuild requested.", COLOR_FRONTEND, 0)
    check_install_build("frontend/urban-workflows/", force_rebuild=True)
    log_info(f"[Frontend] Force rebuild complete.", COLOR_FRONTEND, 0)

def start_frontend(host="localhost", port=8080, force_rebuild=False, no_server=False):
    log_info(f"Starting frontend on {host}:{port}...", COLOR_FRONTEND, 0)

    _kill_port(int(port))

    # Only check if running dev mode
    original_dir = os.getcwd()
    if os.getenv("CURIO_DEV") == "1":
        check_install_build("frontend/urban-workflows/", force_rebuild=force_rebuild)
        os.chdir(original_dir)

    # If we're not starting the server, just exit here
    if no_server:
        log_info(f"[Frontend] Build completed with --force-rebuild, server not started.", COLOR_FRONTEND, 0)
        return None

    dir = "frontend/urban-workflows/"
    script_dir = os.path.dirname(os.path.abspath(__file__))
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
                        "from utk_curio.main import run_spa_static_server; "
                        f"run_spa_static_server('dist', {port})"
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




def _is_testing() -> bool:
    return os.environ.get("CURIO_TESTING", "").lower() in ("1", "true", "yes")


def prepare_backend_database():
    project_root = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

    testing = _is_testing()
    launch_dir = os.environ.get("CURIO_LAUNCH_CWD") or os.getcwd()
    db_dir = os.path.join(launch_dir, ".curio", "test") if testing else os.path.join(launch_dir, ".curio")

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
            try:
                os.remove(test_sqla)
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
                        pass

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
                            pass
                    remaining = still_alive
                for pid in remaining:
                    try:
                        log_warning(f"[Backend] PID {pid} still alive after SIGTERM; sending SIGKILL.")
                        os.kill(pid, _signal.SIGKILL)
                    except ProcessLookupError:
                        pass
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

    script_dir = os.path.dirname(os.path.abspath(__file__))
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


def _ensure_root_node_modules(project_root: str) -> None:
    """Install the repo-root node_modules used by the sandbox's Node.js
    subprocess. The Autark family (``@urban-toolkit/autk-db``,
    ``autk-compute``, ``autk-map``, ``autk-plot``) is declared in the root
    ``package.json``; AUTK_DB / AUTK_COMPUTE workflows import from this
    location at runtime via ESM. ``check_install_build`` only manages the
    *frontend* node_modules under ``utk_curio/frontend/urban-workflows/``,
    so without this step a fresh checkout fails AUTK examples with
    ``ERR_MODULE_NOT_FOUND``.
    """
    root_modules = os.path.join(project_root, "node_modules")
    if os.path.exists(root_modules):
        return
    if shutil.which("npm") is None:
        log_warning(
            "[Sandbox] npm not found in PATH; skipping root npm install. "
            "AUTK_DB / AUTK_COMPUTE workflows will fail with "
            "ERR_MODULE_NOT_FOUND until 'npm install' is run at the repo root."
        )
        return
    log_info(
        "[Sandbox] Root node_modules not found. Running 'npm install' at "
        f"{project_root} to provide @urban-toolkit/autk-* packages...",
        COLOR_SANDBOX, 0,
    )
    try:
        subprocess.run(
            ["npm", "install", "--no-audit", "--no-fund"],
            check=True, cwd=project_root, shell=shell_required,
        )
    except subprocess.CalledProcessError as e:
        log_error(
            f"[Sandbox] Root 'npm install' failed (exit code {e.returncode}). "
            f"AUTK examples will fail; install manually at {project_root}."
        )
    except Exception as e:
        log_error(f"[Sandbox] Failed to run root 'npm install': {e}")


def start_sandbox(host, port):
    _kill_port(int(port))
    log_info(f"Starting sandbox on {host}:{port}...", COLOR_SANDBOX, 0)

    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(script_dir, ".."))
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

def signal_handler(sig, frame):
    """Handle SIGINT and SIGTERM for clean shutdown."""
    log_always("\nReceived shutdown signal (SIGINT or SIGTERM). Cleaning up...")
    clean_shutdown()

def clean_shutdown():
    log_always("\nShutting down all servers...")
    shutdown_flag.set()  # Signal threads to stop

    for process in processes:
        log_always(f"Terminating {process.args[0]}...")
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            log_always(f"Force killing {process.args[0]}...")
            process.kill()

    log_always("All servers have been shut down.")
    # sys.stdout.flush()
    # sys.stderr.flush()
    sys.exit(0)  # Clean exit status (0)

def get_command_prefix():
    """Detects if the script is being run with 'python curio.py' or 'curio'."""
    if len(sys.argv) > 0:
        command = sys.argv[0]
        if command.endswith("curio.py"):
            return "python curio.py"
        elif command.endswith("curio"):
            return "curio"
    return "python curio.py"

def _run_pip(cmd: list[str], failure_label: str) -> None:
    """Stream ``pip``'s stdout+stderr line-by-line, gating each line on
    verbosity >= 2 via ``log_info``. The ``[Setup]`` banners around this
    call print unconditionally; pip's own chatter ("Requirement already
    satisfied", "Collecting …", "Successfully installed …") stays silent
    at the default verbosity. On non-zero exit, surface ``failure_label``
    via ``log_error`` and abort startup.
    """
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    if process.stdout is not None:
        for line in process.stdout:
            log_info(f"[pip] {line.rstrip()}", COLOR_BACKEND, 2)
    rc = process.wait()
    if rc != 0:
        log_error(f"{failure_label} (exit {rc}). Re-run with --verbose 2 to see pip's output.")
        sys.exit(1)


def install_framework_requirements() -> None:
    """``pip install -r requirements.txt`` for Curio's framework deps —
    the libraries the backend + sandbox Flask apps need at module load.
    Data-ops libs (pandas, geopandas, rasterio, …) live in each node
    package's manifest and get installed by
    ``install_manifest_dependencies`` below.

    Idempotent: pip exits in ~1 s when every line is already satisfied,
    so we run unconditionally at ``curio start``.
    """
    req = Path(__file__).resolve().parent.parent / "requirements.txt"
    if not req.is_file():
        return
    log_info(f"[Setup] Ensuring framework deps from {req.name}...", COLOR_BACKEND, 0)
    _run_pip(
        [sys.executable, "-m", "pip", "install", "-r", str(req)],
        f"[Setup] pip install -r {req.name} failed",
    )


def install_manifest_dependencies() -> None:
    """Walk every installed package manifest — catalog source-of-truth at
    ``<repo>/packages/`` PLUS every user store under
    ``$CURIO_LAUNCH_CWD/.curio/users/<u>/packages/`` — collect their
    ``dependencies.python`` maps, merge into a single conflict-aware
    union via ``resolver.merge_python_deps``, and pip-install the result
    through ``pip_runner.install_python_deps``.

    Why this lives in the launcher: the sandbox process imports
    ``pandas`` / ``geopandas`` / ``rasterio`` at module load
    (``sandbox/app/api.py``, ``worker.py::_worker_init``), so those libs
    must already be present in the shared interpreter before the
    sandbox's ``Popen`` lands. Running here — synchronously, sequenced
    before ``start_sandbox`` — is the simplest race-free order.

    All helpers are reused from the backend:
    - ``manifest.load_packageage_manifest`` to parse each
      ``manifest.json`` into a typed dataclass with ``.python_deps``.
    - ``resolver.merge_python_deps`` to surface incompatible ranges as
      warnings instead of silently last-write-wins.
    - ``pip_runner.install_python_deps`` to do the pip work
      (PEP 440 + ``^X.Y`` caret rewrite + already-satisfied skip + batched
      pip + stderr-tail surfacing on failure).
    """
    from utk_curio.backend.app.packages.manifest import (
        ManifestError,
        load_packageage_manifest,
    )
    from utk_curio.backend.app.packages.resolver import merge_python_deps
    from utk_curio.backend.app.packages.pip_runner import (
        PipInstallError,
        install_python_deps,
    )

    repo_root = Path(__file__).resolve().parent.parent
    launch_cwd = Path(os.environ.get("CURIO_LAUNCH_CWD") or os.getcwd())
    catalog = repo_root / "packages"
    users = launch_cwd / ".curio" / "users"

    per_pkg: list[tuple[str, dict[str, str]]] = []
    seen: set[str] = set()  # dir_name dedupe across users

    # Catalog walk is scoped to ``curio.builtin@*`` only — the catalog
    # lists every *available* package, but only the built-in is
    # auto-seeded for every user. Other catalog entries (UHVI,
    # milan-heat, streetvision, …) are opt-in via the /catalog drawer;
    # their deps come along when the user installs them, via the
    # per-user-store walk below.
    if catalog.is_dir():
        for pkg_dir in catalog.glob("curio.builtin@*"):
            try:
                m = load_packageage_manifest(pkg_dir)
            except ManifestError:
                continue
            seen.add(m.dir_name)
            if m.python_deps:
                per_pkg.append((m.dir_name, dict(m.python_deps)))

    # Per-user store walk — every package any user has actually installed.
    if users.is_dir():
        for mf in users.rglob("manifest.json"):
            try:
                m = load_packageage_manifest(mf.parent)
            except ManifestError:
                continue
            if m.dir_name in seen:
                continue
            seen.add(m.dir_name)
            if m.python_deps:
                per_pkg.append((m.dir_name, dict(m.python_deps)))

    if not per_pkg:
        return
    merged, conflicts = merge_python_deps(per_pkg)
    for c in conflicts:
        log_warning(
            f"Dependency range conflict for {c.package}: "
            + ", ".join(f"{dn}={rng}" for dn, rng in c.ranges)
        )
    if not merged:
        return
    log_info(
        f"[Setup] Installing manifest python deps for: {', '.join(sorted(merged))}",
        COLOR_BACKEND, 0,
    )
    try:
        install_python_deps(
            merged,
            on_line=lambda line: log_info(f"[pip] {line}", COLOR_BACKEND, 2),
        )
    except PipInstallError as exc:
        log_error(f"[Setup] Manifest dep install failed: {exc}")
        sys.exit(1)


def main():

    global processes
    global verbosity

    # Capture Docker shutdown (SIGINT and SIGTERM)
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    command_prefix = get_command_prefix()

    parser = argparse.ArgumentParser(
        description="Curio's multi-server management tool.",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=f"""
    Examples:
        {command_prefix} start                       # Start all servers (backend, sandbox, frontend)
        {command_prefix} start backend               # Start only the backend (localhost:5002)
        {command_prefix} start sandbox               # Start only the sandbox (localhost:2000)
        {command_prefix} --verbose                   # Verbosity level (e.g., 0=silent, 1=normal, 2=debug)
        {command_prefix} --force-rebuild             # Re-build the frontend (if dev mode)
        {command_prefix} --force-db-init             # Re-initialize the backend database (if dev mode)
    """
    )
    
    parser.add_argument(
        "command",
        nargs="?",
        choices=["start", "setup"],
        help=(
            "Command to execute "
            "(start: launch the servers — automatically runs setup first; "
            "setup: install framework + manifest python deps for this "
            "interpreter and exit, no servers)"
        ),
    )
    parser.add_argument(
        "server", nargs="?", default="all", choices=["all", "frontend", "backend", "sandbox"],
        help="Script to manage Curio's servers (all, frontend, backend, sandbox)"
    )
    parser.add_argument(
        "--backend-host", default="127.0.0.1", help="Host for the backend server (default: 127.0.0.1)"
    )
    parser.add_argument(
        "--backend-port", default="5002", help="Port for the backend server (default: 5002)"
    )
    parser.add_argument(
        "--sandbox-host", default="127.0.0.1", help="Host for the sandbox server (default: 127.0.0.1)"
    )
    parser.add_argument(
        "--sandbox-port", default="2000", help="Port for the sandbox server (default: 2000)"
    )
    parser.add_argument(
        "--frontend-host", default="localhost", help="Host for the frontend server (default: localhost)"
    )
    parser.add_argument(
        "--frontend-port", default="8080", help="Port for the frontend server (default: 8080)"
    )
    parser.add_argument(
        "--verbose", type=int, default=1, help="Verbosity level (e.g., 0=silent, 1=normal, 2=debug)"
    )
    parser.add_argument(
        "--auth", action="store_true", default=False,
        help="Enable authentication (sets CURIO_NO_AUTH=0). Default: off (CURIO_NO_AUTH=1)"
    )
    parser.add_argument(
        "--no-project", action="store_true", default=False,
        help=(
            "Skip login and projects pages "
            "(sets CURIO_NO_AUTH=1, CURIO_NO_PROJECT=1). "
            "Default: off (CURIO_NO_PROJECT=0)"
        )
    )
    parser.add_argument(
        "--deploy", action="store_true", default=False,
        help="Enable authentication and projects (sets CURIO_NO_AUTH=0, CURIO_NO_PROJECT=0)"
    )
    parser.add_argument(
        "--with-examples", action="store_true", default=False,
        help="Seed example projects from docs/examples/ on startup (sets CURIO_SEED_EXAMPLES=1)"
    )
    parser.add_argument(
        "--reseed", action="store_true", default=False,
        help=(
            "Force re-seeding of catalog packages into the guest user's package "
            "store on startup (sets CURIO_RESEED_PACKAGES=1)"
        ),
    )
    parser.add_argument(
        "--allow-publish", action=argparse.BooleanOptionalAction, default=True,
        help=(
            "Allow the catalog Publish/Unpublish actions (sets "
            "CURIO_ALLOW_FACTORY_CATALOG_PUBLISH=1, the previous default). "
            "Pass --no-allow-publish to lock these author actions down."
        ),
    )
    parser.add_argument(
        "--collab", action="store_true", default=False,
        help=(
            "Enable real-time collaborative editing (sets ENABLE_COLLAB=1). "
            "Experimental, LAN-only. Default: off"
        ),
    )
    if os.getenv("CURIO_DEV") == "1":
        parser.add_argument(
            "--force-rebuild", action="store_true",
            help="Force rebuild of the frontend"
        )
        parser.add_argument(
            "--force-db-init", action="store_true",
            help="Force re-initialization of the backend database"
        )

    # Display help if no arguments are given
    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(0)

    args = parser.parse_args()

    setup_logging()
    verbosity = int(args.verbose)

    set_environment_variables(
        backend_host=args.backend_host,
        backend_port=args.backend_port,
        sandbox_host=args.sandbox_host,
        sandbox_port=args.sandbox_port,
        auth=args.auth,
        no_project=args.no_project,
        deploy=args.deploy,
        with_examples=args.with_examples,
        reseed=args.reseed,
        allow_publish=args.allow_publish,
        collab=args.collab,
    )

    # if os.getenv("CURIO_DEV") != "1":
        # if args.force_rebuild or args.force_db_init:
            # print("Error: --force-rebuild and --force-db-init are not available when running Curio from pip. If you really need it, refer to the documentation to run Curio from curio.py.")
            # sys.exit(1)
    if os.getenv("CURIO_DEV") == "1":
        # Handle standalone rebuild or db init without starting servers
        if not args.command:
            if args.force_rebuild:
                log_info("Rebuilding frontend...", COLOR_FRONTEND, 0)
                start_frontend(args.frontend_host, int(args.frontend_port), force_rebuild=True, no_server=True)
            if args.force_db_init:
                log_info("Re-initializing backend database...", COLOR_FRONTEND, 0)
                start_backend(args.backend_host, args.backend_port, no_server=True)
            sys.exit(0)
    else:
        args.force_rebuild = False
        args.force_db_init = False

    if args.command == "test":
        if args.server == "frontend":
            run_frontend_tests()
        else:
            log_error(f"No tests available for '{args.server}'. Available: frontend")
            sys.exit(1)

    if args.command == "coverage":
        if args.server not in ("all", "backend"):
            log_error("coverage only runs backend tests; use: curio coverage  or  curio coverage backend")
            sys.exit(1)
        run_backend_coverage()

    if args.command == "setup":
        install_framework_requirements()
        install_manifest_dependencies()
        sys.exit(0)

    if args.command == "start":
        # Mirror the ``shutil.which("npm")`` check at the top of
        # ``start_frontend``: catch drifted Python envs at launch instead
        # of crashing the sandbox/backend on its first module-level import.
        # Framework first (gives us Flask + manifest-parsing deps), then
        # the manifest walk (covers builtin's data-ops libs + every other
        # installed package's declared python deps).
        if args.server in ("all", "backend", "sandbox"):
            install_framework_requirements()
            install_manifest_dependencies()

        if args.server == "all":
            log_always("Starting all servers (backend, sandbox, frontend)...")
            processes = [
                start_backend(args.backend_host, args.backend_port),
                start_sandbox(args.sandbox_host, args.sandbox_port),
                start_frontend(args.frontend_host, int(args.frontend_port), force_rebuild=args.force_rebuild)
            ]
        else:
            if args.server == "backend":
                processes.append(start_backend(args.backend_host, args.backend_port))
            elif args.server == "sandbox":
                processes.append(start_sandbox(args.sandbox_host, args.sandbox_port))
            elif args.server == "frontend":
                processes.append(start_frontend(args.frontend_host, int(args.frontend_port), force_rebuild=args.force_rebuild))

        # Monitor the threads
        logging_thread = threading.Thread(target=logger, daemon=True)
        logging_thread.start()

        try:
            while not shutdown_flag.is_set():
                time.sleep(1)
        except KeyboardInterrupt:
            clean_shutdown(processes)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
