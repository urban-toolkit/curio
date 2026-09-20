#!/usr/bin/env python3

import subprocess
import json
import os
import re
import sys
import time
import threading
import queue
import argparse
import secrets
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

# The Node.js major the project targets: the frontend build, Jest, and the
# sandbox's Node subprocess. Keep in step with the Dockerfile, .nvmrc,
# .node-version and both package.json "engines" fields --
# test_launcher_node_version.py fails when they drift.
NODE_MAJOR = 26

# Recorded inside node_modules by the Node major that installed it; a tree from
# another major (or with no stamp, i.e. any checkout from before Node 26) is
# reinstalled once. ``npm install`` alone does not heal it: it never re-runs an
# install script, and webpack's cache under node_modules/.cache is not keyed on
# the Node version.
NODE_STAMP = ".curio-node-major"

shutdown_flag = threading.Event()
processes = []
file_logger = None
verbosity = 1
logger = logging.getLogger(__name__)


def setup_logging(server: str = "all"):
    # CURIO_STATE_DIR relocates every per-stack file (backend/app/common/
    # user_storage.py); the log follows so two stacks in one checkout do not
    # truncate each other's -- ``filemode="w"`` below wipes the first
    # launcher's log the moment a second one starts. A single-server start
    # gets its own file for the same reason: an e2e shard is two launchers.
    log_dir = Path(os.environ.get("CURIO_STATE_DIR") or ".curio")
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / ("messages.log" if server == "all" else f"messages-{server}.log")

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

#: The unprivileged account isolated node code runs as. The Docker image
#: creates it (see the Dockerfile's curio-exec note), which is what lets a
#: deployment isolate without anyone naming it on the command line.
DEFAULT_EXEC_USER = "curio-exec"


def _discover_exec_user():
    """The account isolated node code runs as, or None.

    ``CURIO_EXEC_USER`` when the environment already names one - an empty value
    means "none, deliberately", which is how a test stack asks for the
    no-execution-user shape on a host that has the account. Otherwise the
    conventional account the image creates.

    Only meaningful as root: setuid is how the boundary is applied, so an
    unprivileged launch has nothing to drop to. ``pwd`` is POSIX-only, which is
    also what makes this return None on Windows.
    """
    if "CURIO_EXEC_USER" in os.environ:
        return os.environ["CURIO_EXEC_USER"].strip() or None
    if not hasattr(os, "geteuid") or os.geteuid() != 0:
        return None
    try:
        import pwd

        pwd.getpwnam(DEFAULT_EXEC_USER)
    except (ImportError, KeyError):
        return None
    return DEFAULT_EXEC_USER


def _why_not_isolated(exec_user, blockers):
    """Why a --deploy launch is running node code in-process after all."""
    if blockers:
        reason = "this host is missing " + ", ".join(blockers)
    else:
        reason = (
            f"no execution user is configured (no {DEFAULT_EXEC_USER!r} account, "
            "or Curio is not running as root)"
        )
    return (
        "Node execution is NOT isolated on this deployment: "
        f"{reason}. Node code runs in-process with the sandbox's full "
        "privileges, so treat node-authoring rights as shell access. The "
        "version badge in the UI reports this too."
    )


def set_environment_variables(backend_host, backend_port, sandbox_host, sandbox_port, no_project=False, deploy=False, with_examples=False, reseed=False, allow_publish=True, allow_shared_installs=False, collab=False, save_node_outputs=False, catalog_root=None, exec_memory_mb=None, exec_timeout=None, exec_parallelism=None, llm_provider=None, llm_base_url=None, llm_model=None, guest_llm_api_key=None, agent_search_url=None, huggingface_token=None):
    """Sets the environment variables for Backend and Sandbox."""
    os.environ["FLASK_BACKEND_HOST"] = backend_host
    os.environ["FLASK_BACKEND_PORT"] = str(backend_port)
    os.environ["FLASK_SANDBOX_HOST"] = sandbox_host
    os.environ["FLASK_SANDBOX_PORT"] = str(sandbox_port)
    # The frontend bundle's DEFAULT backend address is baked in at BUILD time
    # (webpack substitutes ``process.env.BACKEND_URL`` through dotenv-webpack).
    # Derive it from the same --backend-host/--backend-port the backend itself
    # is started with, so the two cannot disagree. It is only the default:
    # ``src/utils/backendUrl.ts`` prefers ``window.__CURIO_BACKEND_URL__`` when
    # the page sets it, which is how one build serves several backends (the
    # parallel e2e harness injects it per browser context).
    #
    # This used to come only from a hand-maintained
    # ``frontend/urban-workflows/.env``, which meant every port change was two
    # edits and a rebuild, and forgetting either produced a UI that silently
    # talked to whichever OTHER Curio owned the default port. dotenv-webpack is
    # configured with ``systemvars: true``, and a real environment variable wins
    # over the file, so setting it here is enough. An explicit BACKEND_URL from
    # the caller still wins over both.
    #
    # 127.0.0.1 is normalized to localhost because the browser's origin is
    # localhost by default, and the two are distinct origins to CORS.
    browser_host = "localhost" if backend_host in ("127.0.0.1", "0.0.0.0") else backend_host
    os.environ.setdefault("BACKEND_URL", f"http://{browser_host}:{backend_port}")
    # Shared secret proving to the sandbox that a caller is this backend. The
    # sandbox runs arbitrary user code, so its /exec, /execJs, /get and
    # /install routes require it (utk_curio/sandbox/app/auth.py). Minted per
    # launch and inherited by both children; a hosted instance refuses to boot
    # without one. Respect a pre-set value so an operator running the two
    # processes separately can pair them by hand.
    os.environ["CURIO_SANDBOX_TOKEN"] = (
        os.environ.get("CURIO_SANDBOX_TOKEN") or secrets.token_urlsafe(32)
    )
    # NOT implied by --deploy. The e2e harness boots --deploy to get the login
    # page, and two suites exist to cover multi-user WITHOUT examples
    # (test_examples_for_registered_users_e2e.py), so seeding has to be asked
    # for. docker-compose.deploy.yml passes --with-examples explicitly.
    os.environ["CURIO_SEED_EXAMPLES"] = "1" if with_examples else "0"
    os.environ["CURIO_RESEED_PACKAGES"] = "1" if reseed else "0"
    os.environ["CURIO_ALLOW_FACTORY_CATALOG_PUBLISH"] = "1" if allow_publish else "0"
    # A pre-set value wins over the CLI default, the way CURIO_SANDBOX_TOKEN and
    # CURIO_ISOLATION already do. Assigning unconditionally made the documented
    # env var a no-op for anything started through curio.py, so an operator who
    # set it in a compose ``environment:`` block next to CURIO_ISOLATION got
    # silence. The flag still wins when passed.
    os.environ["CURIO_ALLOW_SHARED_INSTALLS"] = (
        "1"
        if allow_shared_installs
        else os.environ.get("CURIO_ALLOW_SHARED_INSTALLS", "0")
    )
    os.environ["CURIO_DEFAULT_SAVE_NODE_OUTPUT"] = "1" if save_node_outputs else "0"
    if catalog_root:
        os.environ["CURIO_CATALOG_ROOT"] = str(Path(catalog_root).expanduser().resolve())
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
        os.environ["CURIO_NO_AUTH"] = "1"
        os.environ["CURIO_NO_PROJECT"] = "1" if no_project else "0"

    hosted = os.environ["CURIO_NO_AUTH"] == "0"

    # Node-execution isolation (utk_curio/sandbox/isolation/).
    #
    # A deployment is the multi-tenant shape, so it isolates by default: node
    # libraries then land in the caller's own overlay instead of the one
    # interpreter every user's nodes import from. Anything else is a local
    # launch, where one user owns the interpreter already.
    #
    # Conditional on actually being able to, because a DEFAULT must never be
    # the reason an instance will not boot: --deploy has to work on Windows and
    # macOS too, where there is no fork isolation to be had. A pre-set
    # CURIO_ISOLATION is a request rather than a default, so `fork` there still
    # fails closed. The version badge reports whichever way this went, so a
    # deployment that quietly declined is visible rather than assumed.
    #
    # RESOLVED here, not passed through. 'auto' is a request, not an answer,
    # and it used to be decided inside the sandbox - which left every other
    # reader holding a value that does not say what will actually happen.
    # ``resolve_mode`` is pure and ``capabilities()`` reads only sys.platform
    # plus importable modules, so the launcher and the sandbox it spawns reach
    # the same verdict.
    from utk_curio.sandbox.isolation import mode as isolation_mode

    exec_user = _discover_exec_user()
    requested = os.environ.get("CURIO_ISOLATION", "").strip()
    if not requested:
        blockers = isolation_mode.missing_requirements(
            isolation_mode.capabilities(), hosted=hosted,
        )
        if deploy and exec_user and not blockers:
            requested = isolation_mode.FORK
        else:
            requested = isolation_mode.AUTO
            if deploy:
                log_warning(_why_not_isolated(exec_user, blockers))

    isolation_resolved, isolation_reason = isolation_mode.resolve_mode(
        requested, hosted=hosted,
    )
    os.environ["CURIO_ISOLATION"] = isolation_resolved
    if isolation_reason:
        log_warning(isolation_reason)
    # Always exported, including empty: a discovered account has to reach the
    # sandbox, and an explicit empty value has to survive as "none, deliberately".
    os.environ["CURIO_EXEC_USER"] = exec_user or ""
    # ``is not None``, unlike the flags around it: 0 is a value an operator can
    # type, and it has to hit the clamp rather than fall through to the default.
    if exec_memory_mb is not None:
        from utk_curio.sandbox.isolation.supervisor import MIN_EXEC_MEMORY_MB

        # Clamped, not just warned about, because the number is spent by code
        # that cannot see it: codec.py sizes DuckDB's memory_limit against this
        # budget, and that write happens inside the child's RLIMIT_AS cap.
        # Below the floor there is nothing left to size against, and a writer
        # reserving address space the child does not have is #334 all over
        # again. The floor is on the headroom, not on the child's total -
        # child._apply_rlimits adds the interpreter's own footprint on top.
        if int(exec_memory_mb) < MIN_EXEC_MEMORY_MB:
            log_warning(
                f"--exec-memory-mb {exec_memory_mb} is below the "
                f"{MIN_EXEC_MEMORY_MB}MB floor and was raised to it. Node code "
                "needs room to allocate beyond the interpreter the child starts "
                "with. To fit more concurrent nodes on a small host, lower "
                "--exec-parallelism instead."
            )
            exec_memory_mb = MIN_EXEC_MEMORY_MB
        os.environ["CURIO_EXEC_MEMORY_MB"] = str(exec_memory_mb)
    if exec_parallelism:
        os.environ["CURIO_EXEC_PARALLELISM"] = str(exec_parallelism)
    if exec_timeout:
        # Must stay under the backend's SANDBOX_EXEC_TIMEOUT (600s), or the
        # browser gives up before the sandbox can report the real reason.
        if int(exec_timeout) >= 600:
            log_warning(
                f"--exec-timeout {exec_timeout}s is at or above the backend's "
                "600s sandbox deadline. A node hitting it will surface as a "
                "generic gateway timeout instead of a clear per-node message."
            )
        os.environ["CURIO_EXEC_TIMEOUT"] = str(exec_timeout)

    # AI provider. Curio ships no endpoint of its own (see backend/config.py):
    # an instance whose operator configures nothing resolves no provider, and
    # the agent surfaces say so rather than reaching a third party nobody chose.
    if llm_provider:
        os.environ["CURIO_DEFAULT_LLM_API_TYPE"] = str(llm_provider)
    if llm_base_url:
        os.environ["CURIO_DEFAULT_LLM_BASE_URL"] = str(llm_base_url)
    if llm_model:
        os.environ["CURIO_DEFAULT_LLM_MODEL"] = str(llm_model)
    if guest_llm_api_key:
        os.environ["GUEST_LLM_API_KEY"] = str(guest_llm_api_key)

    # The agents' web-search tool. Unset, the tool is unavailable: an agent
    # never reaches an endpoint the operator did not name.
    if agent_search_url:
        os.environ["CURIO_SEARCH_URL"] = str(agent_search_url)

    # HuggingFace, for the Street Vision node's gated models. A user's own
    # token in AI Settings wins over this; it is the fallback for everyone who
    # has not set one.
    if huggingface_token:
        os.environ["CURIO_DEFAULT_HUGGINGFACE_TOKEN"] = str(huggingface_token)

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
    log_always(f"CURIO_ALLOW_SHARED_INSTALLS={os.environ['CURIO_ALLOW_SHARED_INSTALLS']}")
    log_always(f"CURIO_DEFAULT_SAVE_NODE_OUTPUT={os.environ['CURIO_DEFAULT_SAVE_NODE_OUTPUT']}")
    log_always(f"CURIO_ISOLATION={os.environ['CURIO_ISOLATION']}")
    # The token itself is deliberately not logged.
    log_always("CURIO_SANDBOX_TOKEN=<set>")
    if catalog_root:
        log_always(f"CURIO_CATALOG_ROOT={os.environ['CURIO_CATALOG_ROOT']}")
    log_always(f"ENABLE_COLLAB={os.environ['ENABLE_COLLAB']}")

def seed_duckdb_extensions():
    """Put Curio's copy of DuckDB's spatial extension where duckdb-wasm looks.

    autk-db's ``init()`` runs ``INSTALL spatial; LOAD spatial;``. In Node,
    duckdb-wasm keeps installed extensions under
    ``~/.duckdb/extensions/<repository>/<version>/<platform>/`` and only
    downloads one that is not there — so seeding that directory from
    ``vendor/duckdb-extensions/`` means a node never reaches
    extensions.duckdb.org: no 23 MB download on a cold container, nothing to
    flake (#318), and an offline install still runs Autark nodes.

    Copies only what is missing, and never fails a launch: without it the
    extension is downloaded exactly as before.
    """
    import shutil
    from pathlib import Path

    source_root = Path(__file__).resolve().parent.parent / "vendor" / "duckdb-extensions"
    if not source_root.is_dir():
        return
    target_root = Path.home() / ".duckdb" / "extensions" / "extensions.duckdb.org"
    seeded = []
    try:
        for source in source_root.rglob("*.wasm"):
            target = target_root / source.relative_to(source_root)
            if target.is_file() and target.stat().st_size == source.stat().st_size:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            seeded.append(str(target.relative_to(target_root)))
    except OSError as exc:
        log_warning(f"[DuckDB] could not seed the spatial extension ({exc}); "
                    f"it will be downloaded on demand instead")
        return
    if seeded:
        log_always(f"[DuckDB] seeded extension(s) into {target_root}: {', '.join(seeded)}")


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
        # The 1.0 default closes the socket after every response, so one page
        # load opens hundreds of connections. Safe: every response here carries
        # a Content-Length.
        protocol_version = "HTTP/1.1"

        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=dist_dir, **kwargs)

        def do_GET(self):
            request_path = self.path.split("?", 1)[0].split("#", 1)[0]
            candidate = request_path.lstrip("/")
            fs_path = os.path.join(dist_dir, candidate)
            # Fall back on what the client asked for, not on whether the path
            # looks like it has a file extension. ``splitext`` reads a dotted
            # dataset id - ``data.urbanlab.acs-neighborhood-profile`` - as the
            # extension ``.acs-neighborhood-profile``, so an extension test
            # refuses exactly the deep links this fallback exists to serve. A
            # browser navigation sends ``Accept: text/html``; a missing bundle
            # fetched with ``Accept: */*`` still gets its 404.
            accepts_html = "text/html" in (self.headers.get("Accept") or "")
            if (
                request_path not in ("", "/")
                and not os.path.exists(fs_path)
                and accepts_html
            ):
                self.path = "/index.html"
            return super().do_GET()

    with ThreadingHTTPServer(("0.0.0.0", port), SpaStaticHandler) as httpd:
        httpd.serve_forever()

def _read_node_version():
    """``(raw, major)`` for the ``node`` on PATH; ``(None, 0)`` when unreadable."""
    try:
        raw = subprocess.check_output(
            ["node", "--version"], text=True, shell=shell_required,
        ).strip()
    except Exception as e:
        log_error(f"Could not determine Node.js version: {e}")
        return None, 0
    major = 0
    if raw.startswith("v"):
        try:
            major = int(raw[1:].split(".", 1)[0])
        except ValueError:
            pass
    return raw, major


def _node_tree_is_stale(root, major):
    """True when ``root``'s node_modules was installed by a different Node major.

    See ``NODE_STAMP``. A missing tree is not stale -- there is nothing to wipe
    and the install that follows is a fresh one.
    """
    node_modules = os.path.join(root, "node_modules")
    if not os.path.isdir(node_modules):
        return False
    try:
        with open(os.path.join(node_modules, NODE_STAMP), encoding="utf-8") as fh:
            return fh.read().strip() != str(major)
    except OSError:
        return True


def _require_supported_node():
    """Refuse to start on a Node older than the project targets.

    Serving a prebuilt bundle would survive it, but the sandbox runs autk-db in
    this Node, where Autark data nodes die mid-download (the undici regression
    nodejs/undici#5360), and every npm script fails against it. That is a broken
    install rather than a degraded one, and the failures it produces read as
    bugs in Curio. No Node at all is a different case: nothing to be wrong, and
    a Python-only session still works.

    Exits non-zero rather than through clean_shutdown, whose 0 would tell a
    script that the stack came up. Nothing is running yet to shut down.
    """
    if shutil.which("node") is None:
        return
    raw, major = _read_node_version()
    if raw is None or major >= NODE_MAJOR:
        return
    log_error(
        f"Node.js {raw} detected; Curio requires Node.js {NODE_MAJOR} or newer. "
        f"Upgrade with 'conda install -c conda-forge nodejs={NODE_MAJOR}' or "
        f"from https://nodejs.org, then retry."
    )
    sys.exit(1)


def _frontend_tree_is_stale():
    """node_modules belongs to another Node major, and Node is here to tell.

    Nothing to check without a tree (the container and pip ship none) or
    without Node on PATH. A *missing* tree is not stale: it fails obviously,
    one npm install away, and conjuring 1.6 GB nobody asked for would undo a
    deliberate delete.
    """
    if shutil.which("npm") is None or shutil.which("node") is None:
        return False
    if not os.path.isfile(os.path.join(_frontend_dir(), "package.json")):
        return False  # nothing to reinstall from, so nothing to report
    _, major = _read_node_version()
    return bool(major) and _node_tree_is_stale(_frontend_dir(), major)


def _write_node_stamp(root, major):
    """Record the Node major that installed ``root``'s node_modules.

    Called after a successful install only, so a failed one does not leave a
    stamp claiming the tree is current.
    """
    node_modules = os.path.join(root, "node_modules")
    try:
        os.makedirs(node_modules, exist_ok=True)
        with open(os.path.join(node_modules, NODE_STAMP), "w", encoding="utf-8") as fh:
            fh.write(str(major))
    except OSError as exc:
        # Unstamped counts as stale, so the only cost is one extra reinstall.
        log_warning(f"Could not record the installing Node.js major: {exc}")


def check_install_build(dir, force_rebuild=False):
    # Determine the absolute path whether it is provided as relative or absolute
    script_dir = os.path.dirname(os.path.abspath(__file__))
    abs_dir = os.path.abspath(dir) if os.path.isabs(dir) else os.path.join(script_dir, dir)
    
    if not os.path.exists(abs_dir):
        raise FileNotFoundError(f"[Error] The directory '{abs_dir}' does not exist.")
    
    os.chdir(abs_dir)
    log_info(f"[Frontend] Current working directory for npm commands: {os.getcwd()}", COLOR_FRONTEND, 0)
    
    if shutil.which("npm") is None:
        log_error(f"[Frontend] npm not found in PATH. Install Node.js {NODE_MAJOR} from https://nodejs.org, or via conda ('conda install -c conda-forge nodejs={NODE_MAJOR}'), and make sure 'npm' is available in your terminal, then retry.")
        clean_shutdown()
        return

    if shutil.which("node") is None:
        log_error(f"[Frontend] node not found in PATH. Install Node.js {NODE_MAJOR} from https://nodejs.org, or via conda ('conda install -c conda-forge nodejs={NODE_MAJOR}'), and make sure 'node' is available in your terminal, then retry.")
        clean_shutdown()
        return
    node_version_raw, node_major = _read_node_version()
    if node_version_raw is None:
        clean_shutdown()
        return
    if node_major < NODE_MAJOR:
        log_error(
            f"[Frontend] Node.js {node_version_raw} detected; requires Node.js {NODE_MAJOR} or newer. "
            f"Upgrade with 'conda install -c conda-forge nodejs={NODE_MAJOR}' or from https://nodejs.org, then retry."
        )
        clean_shutdown()
        return

    # A tree from another Node major is reinstalled (see NODE_STAMP), and only
    # the tree: which Node ran webpack does not change the JavaScript it emits,
    # so the bundle is judged by its own stamp below and usually survives.
    if not force_rebuild and _node_tree_is_stale(abs_dir, node_major):
        log_info(
            f"[Frontend] node_modules was installed by a different Node.js major; "
            f"reinstalling for Node.js {node_major}...",
            COLOR_FRONTEND, 0,
        )
        shutil.rmtree(os.path.join(abs_dir, "node_modules"), ignore_errors=True)

    if force_rebuild:
        log_info(f"[Frontend] Force rebuilding in {dir}...", COLOR_FRONTEND)
        for subdir in ("node_modules", "dist", "build"):
            full_path = os.path.join(abs_dir, subdir)
            if os.path.exists(full_path):
                shutil.rmtree(full_path)

    # Run npm install unconditionally. It's idempotent and fast (~1 s) when
    # the lockfile is already satisfied, and it self-heals when package.json
    # gains a new dep that node_modules/ doesn't have yet — gating on
    # ``node_modules`` existing would skip the install and leave the new dep
    # missing, failing the webpack build with "Module not found".
    log_info(f"[Frontend] Ensuring npm deps are installed...", COLOR_FRONTEND, 0)
    try:
        subprocess.run(["npm", "install"], check=True, shell=shell_required)
    except subprocess.CalledProcessError as e:
        log_error(f"[Frontend] 'npm install' failed (exit code {e.returncode}). Check the output above for details.")
        clean_shutdown()
    except Exception as e:
        log_error(f"[Frontend] Failed to run 'npm install': {e}")
        clean_shutdown()
    else:
        _write_node_stamp(abs_dir, node_major)

    # The only output there is: webpack writes it and start_frontend serves it by
    # name. A ``"dist" if exists else "build"`` fallback used to stamp a build/
    # this function created itself, which then stood in for a deleted dist and
    # skipped the build (test_leftover_build_dir_does_not_suppress_the_build).
    # Same check start_frontend gates on, so the two never disagree about
    # whether the existing build is reusable.
    reason = _build_stamp_reason(abs_dir)

    if reason is not None:
        log_info(f"[Frontend] Running npm run build ({reason})...", COLOR_FRONTEND, 0)
        try:
            subprocess.run(["npm", "run", "build"], check=True, shell=shell_required)
        except subprocess.CalledProcessError as e:
            log_error(f"[Frontend] 'npm run build' failed (exit code {e.returncode}). Check the output above for details.")
            clean_shutdown()
        except Exception as e:
            log_error(f"[Frontend] Failed to run 'npm run build': {e}")
            clean_shutdown()
        else:
            # Written after a successful build only, so a failed one does not
            # leave a stamp claiming the bundle matches.
            _write_build_stamp(abs_dir)
    else:
        log_info(
            f"[Frontend] dist is current for "
            f"{os.environ.get('BACKEND_URL', '') or 'the .env default'}. "
            f"Skipping npm run build.",
            COLOR_FRONTEND, 0,
        )

def force_rebuild_frontend():
    log_info(f"[Frontend] Force rebuild requested.", COLOR_FRONTEND, 0)
    check_install_build("frontend/urban-workflows/", force_rebuild=True)
    log_info(f"[Frontend] Force rebuild complete.", COLOR_FRONTEND, 0)

def _frontend_dir() -> str:
    return os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "frontend", "urban-workflows"
    )


def _frontend_is_built(root: str = "") -> bool:
    return os.path.isfile(os.path.join(root or _frontend_dir(), "dist", "index.html"))


def _frontend_build_mode(root: str = "") -> str:
    """The webpack mode ``npm run build`` uses, read from package.json.

    Read rather than pinned so the stamp follows the script: flip the script
    between development and production and the next start rebuilds by itself.
    """
    try:
        pkg = os.path.join(root or _frontend_dir(), "package.json")
        with open(pkg, encoding="utf-8") as fh:
            script = json.load(fh).get("scripts", {}).get("build", "")
    except (OSError, ValueError):
        return "unknown"
    found = re.search(r"--mode\s+(\S+)", script)
    return found.group(1) if found else "unknown"


def _build_stamp_reason(root: str = "") -> str | None:
    """Why the built frontend cannot be reused, or None when it can.

    ``BACKEND_URL`` is substituted into the bundle at BUILD time, so an existing
    build is only reusable if it was built for the backend we are about to
    start. Without this, changing --backend-port reused the old bundle and the
    UI kept calling the previous port -- which, when another Curio owns it,
    means a session quietly driving someone else's backend. The webpack mode is
    stamped beside it: every checkout built before the move to a production
    build carries a development bundle, three times the size, and nothing else
    would ever notice.
    """
    dist = os.path.join(root or _frontend_dir(), "dist")
    if not _frontend_is_built(root):
        return "dist directory not found"

    wanted_url = os.environ.get("BACKEND_URL", "")
    wanted_mode = _frontend_build_mode(root)
    built_mode = built_url = None
    try:
        with open(os.path.join(dist, ".curio-backend-url"), encoding="utf-8") as fh:
            # Two lines: mode, then URL. A one-line stamp is the old format,
            # which only a development-mode build ever wrote, so it rebuilds.
            lines = fh.read().splitlines()
        if len(lines) >= 2:
            built_mode, built_url = lines[0].strip(), lines[1].strip()
    except OSError:
        pass

    if built_mode != wanted_mode:
        return f"built in {built_mode or 'an unrecorded'} mode, need {wanted_mode}"
    if built_url != wanted_url:
        return (
            f"built for {built_url or 'an unrecorded backend'}, "
            f"need {wanted_url or 'the .env default'}"
        )
    return None


def _write_build_stamp(root: str = "") -> None:
    dist = os.path.join(root or _frontend_dir(), "dist")
    try:
        os.makedirs(dist, exist_ok=True)
        with open(os.path.join(dist, ".curio-backend-url"), "w", encoding="utf-8") as fh:
            fh.write(f"{_frontend_build_mode(root)}\n{os.environ.get('BACKEND_URL', '')}\n")
    except OSError as exc:
        log_info(
            f"[Frontend] Could not record what the build was made for ({exc}); "
            f"the next start will rebuild.",
            COLOR_FRONTEND, 0,
        )


def _frontend_needs_build() -> bool:
    """The built frontend is missing or stale, and the source to fix it is here.

    Checked before npm is: a checkout whose dist/ is current must start without
    needing a toolchain, and only the build itself requires one.
    """
    if not os.path.isfile(os.path.join(_frontend_dir(), "package.json")):
        return False
    return _build_stamp_reason() is not None


def start_frontend(host="localhost", port=8080, force_rebuild=False, no_server=False):
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


def _skip_dep_install() -> bool:
    """``CURIO_SKIP_DEP_INSTALL=1``: trust the environment as it is.

    The parallel e2e driver starts several backend+sandbox pairs from one
    checkout. Without this every launcher would run ``pip install`` into the
    same interpreter and ``npm install`` into the same ``node_modules`` at the
    same time. The driver does one warm-up (``curio.py setup`` and a root
    ``npm install``) before the first pair starts.
    """
    return os.environ.get("CURIO_SKIP_DEP_INSTALL", "").strip().lower() in ("1", "true", "yes", "on")


def _ensure_root_node_modules(project_root: str) -> None:
    """Install the repo-root node_modules used by the sandbox's Node.js
    subprocess. ``@urban-toolkit/autk-db`` is declared in the root
    ``package.json``; the Autark grammar's data section is compiled to
    autk-db JavaScript and executed server-side (see
    ``utk_curio/sandbox/app/worker.py`` ``execute_js_code``). ``check_install_build``
    only manages the *frontend* node_modules under
    ``utk_curio/frontend/urban-workflows/``, so without this step a fresh
    checkout fails Autark data nodes with ``ERR_MODULE_NOT_FOUND``.
    """
    if shutil.which("npm") is None:
        log_warning(
            "[Sandbox] npm not found in PATH; skipping root npm install. "
            "Autark grammar data nodes will fail with ERR_MODULE_NOT_FOUND "
            "until 'npm install' is run at the repo root."
        )
        return

    # An unreadable version leaves the tree alone rather than wiping it on a
    # guess. An out-of-date one never reaches here: _require_supported_node
    # stops the launch before any server starts.
    node_version_raw, node_major = _read_node_version()
    if node_version_raw and _node_tree_is_stale(project_root, node_major):
        log_info(
            f"[Sandbox] Root node_modules was installed by a different Node.js "
            f"major; reinstalling for Node.js {node_major}...",
            COLOR_SANDBOX, 0,
        )
        shutil.rmtree(os.path.join(project_root, "node_modules"), ignore_errors=True)

    # Run npm install unconditionally (mirrors the frontend's check_install_build):
    # it's idempotent and fast when the lockfile is already satisfied, and it
    # self-heals when the root package.json bumps @urban-toolkit/autk-db. Gating
    # on the autk-db directory merely *existing* (the previous behavior) skipped
    # the update and left the sandbox on a stale version whose API differs —
    # e.g. 2.0.1 exports AutkSpatialDb and lacks loadGeojson, while 2.1.2 exports
    # AutkDb — silently breaking server-side data loading.
    log_info(
        "[Sandbox] Ensuring root node_modules (@urban-toolkit/autk-db) at "
        f"{project_root}...",
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
            f"Autark data nodes will fail; install manually at {project_root}."
        )
    except Exception as e:
        log_error(f"[Sandbox] Failed to run root 'npm install': {e}")
    else:
        if node_major:
            _write_node_stamp(project_root, node_major)


def start_sandbox(host, port):
    _kill_port(int(port))
    log_info(f"Starting sandbox on {host}:{port}...", COLOR_SANDBOX, 0)

    script_dir = os.path.dirname(os.path.abspath(__file__))
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
    Data-ops libs (pandas, geopandas, …) live in each node
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


def _install_user_node_deps_at_boot(user_key: str, entries) -> None:
    """Provision one user's node libraries into their own tree (#332).

    Best-effort per user, unlike the host install below, which exits non-zero.
    One account's unsatisfiable manifest must not stop an instance booting for
    everybody else - the failure belongs to whoever installed that package, and
    they get a plain ImportError naming it the first time a node runs.
    """
    from utk_curio.backend.app.packages import backend_runtime
    from utk_curio.backend.app.packages.resolver import merge_python_deps
    from utk_curio.backend.app.packages.pip_runner import (
        PipInstallError, install_python_deps_to_target,
    )

    merged, conflicts = merge_python_deps(entries)
    for c in conflicts:
        log_warning(
            f"Dependency range conflict for {c.package} (user {user_key}): "
            + ", ".join(f"{dn}={rng}" for dn, rng in c.ranges)
        )
    if not merged:
        return
    overlay = backend_runtime.user_node_overlay_dir(user_key)
    overlay.mkdir(parents=True, exist_ok=True)
    log_info(
        f"[Setup] Installing node deps for user {user_key}: "
        + ", ".join(sorted(merged)),
        COLOR_BACKEND, 0,
    )
    try:
        install_python_deps_to_target(
            merged, str(overlay),
            on_line=lambda line: log_info(f"[pip] {line}", COLOR_BACKEND, 2),
        )
    except PipInstallError as exc:
        log_error(f"[Setup] Node dep install failed for user {user_key}: {exc}")


def install_manifest_dependencies(*, block_on_verify: bool = False) -> None:
    """Walk every installed package manifest — catalog source-of-truth at
    ``<repo>/packages/`` PLUS every user store under
    ``$CURIO_LAUNCH_CWD/.curio/users/<u>/packages/`` — collect their
    ``dependencies.python`` maps, merge into a single conflict-aware
    union via ``resolver.merge_python_deps``, and pip-install the result
    through ``pip_runner.install_python_deps``.

    Why this lives in the launcher: the sandbox process imports
    ``pandas`` / ``geopandas`` at module load (``sandbox/app/api.py``
    triggers ``worker.py::_worker_init``), so those libs must already be
    present in the shared interpreter before the sandbox's ``Popen``
    lands. Running here — synchronously, sequenced before
    ``start_sandbox`` — is the simplest race-free order. (rasterio is
    optional: provided by raster-capable packages like curio.weather and
    imported lazily by the sandbox's raster code paths.)

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
    from utk_curio.backend.app.packages.seed import example_dep_package_ids
    from utk_curio.backend.app.packages import backend_runtime
    from utk_curio.backend.app.packages.backend_runtime import dep_destinations
    from utk_curio.backend.app.common.user_storage import users_base

    repo_root = Path(__file__).resolve().parent.parent
    catalog = repo_root / "packages"
    # Asked of the backend rather than spelled out again: under CURIO_TESTING
    # the per-user tree is ``.curio/test/users/``, and this walk feeding off a
    # different root than the one the backend seeds into is a boot that
    # installs no dependencies at all while looking like it worked.
    users = users_base()

    per_pkg: list[tuple[str, dict[str, str]]] = []
    seen: set[str] = set()  # dir_name dedupe across users

    # Catalog walk is scoped to ``curio.builtin@*`` by default — the
    # catalog lists every *available* package, but only the built-in is
    # auto-seeded for every user. Other catalog entries (UHVI,
    # weather, streetvision, …) are opt-in via the /catalog drawer;
    # their deps come along when the user installs them, via the
    # per-user-store walk below. When example seeding is on
    # (--with-examples => CURIO_SEED_EXAMPLES=1), also walk the
    # packages the bundled examples declare as dependencies — derived from
    # their dataflow.packages lockfiles (see example_dep_package_ids in
    # backend/app/packages/seed.py), NOT a full catalog walk. This
    # first-boot walk matters because it runs BEFORE the backend seeds those
    # packages into the user store; on later starts the user-store walk
    # below covers them.
    catalog_globs = ["curio.builtin@*"]
    if os.environ.get("CURIO_SEED_EXAMPLES") == "1":
        catalog_globs += [f"{pid}@*" for pid in example_dep_package_ids()]
    if catalog.is_dir():
        for pattern in catalog_globs:
            for pkg_dir in sorted(catalog.glob(pattern)):
                try:
                    m = load_packageage_manifest(pkg_dir)
                except ManifestError:
                    continue
                if m.dir_name in seen:
                    continue
                seen.add(m.dir_name)
                if m.python_deps:
                    per_pkg.append((m.dir_name, dict(m.python_deps)))

    # Per-user store walk — every package any user has actually installed.
    #
    # Routed, not unioned. ``dep_destinations`` is the one rule deciding where a
    # package's deps belong (backend_runtime, dev/97): "overlay" means a
    # backend-bearing package whose handlers read a private overlay and whose
    # promotion deliberately left the shared interpreter alone. Host-installing
    # those here at every boot silently undoes that boundary, and a version pin
    # in one user's manifest can then move a library every other user's nodes
    # depend on — merge_python_deps only warns, pip has the last word. Only
    # "host" and "both" name the shared interpreter as a destination.
    #
    # The glob is narrowed to the package-store layout for the same reason it is
    # walked at all: rglob would also match manifests nested inside a package's
    # own payload, which are not installed packages.
    #
    # #332: under fork isolation a node's libraries live in the calling
    # user's own tree, so this walk stops being one merged host install and
    # becomes one install per user. The dedupe below has to go with it: two
    # users who both installed curio.weather each need rasterio, in two
    # different directories, and ``seen`` would have given it to whichever of
    # them the glob reached first.
    per_user: dict[str, list[tuple[str, dict]]] = {}
    scoped = backend_runtime.per_user_node_envs()
    if users.is_dir():
        for mf in sorted(users.glob("*/packages/*/manifest.json")):
            try:
                m = load_packageage_manifest(mf.parent)
            except ManifestError:
                continue
            if not scoped and m.dir_name in seen:
                continue
            seen.add(m.dir_name)
            destination, why = dep_destinations(m)
            if destination not in ("host", "both"):
                log_info(
                    f"[Setup] Skipping {m.dir_name} deps: {why}",
                    COLOR_BACKEND, 2,
                )
                continue
            if not m.python_deps:
                continue
            if scoped:
                user_key = mf.parent.parent.parent.name
                per_user.setdefault(user_key, []).append(
                    (m.dir_name, dict(m.python_deps))
                )
            else:
                per_pkg.append((m.dir_name, dict(m.python_deps)))

    for user_key, entries in sorted(per_user.items()):
        _install_user_node_deps_at_boot(user_key, entries)

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

    _report_unimportable_deps(merged, block=block_on_verify)


def _report_unimportable_deps(merged, *, block: bool) -> None:
    """Warn about deps that installed cleanly but cannot be imported.

    pip exiting 0 is not the same as the library working. A wheel whose native
    extension cannot load - the ordinary GDAL/CUDA case, and what a broken
    ``rasterio`` looks like on Windows - records a perfectly good version, so
    pip reports "already satisfied" and changes nothing on every subsequent
    start. This is the drifted env the caller above says it exists to catch, and
    without this check the first sign of it is a raw ``ImportError`` from
    whichever node happens to run first, long after a setup that looked clean.

    A warning, never a fatal: the stack is still useful and the nodes that avoid
    the library work normally. The fix is usually outside pip - a matching GDAL,
    a conda-forge build - so the decision is the operator's, and this line is
    what lets them make it.

    ``block=False`` runs the probe on a daemon thread, because it costs real
    time: importing the twelve builtin data-ops libraries in one subprocess
    takes ~19 s on a developer machine, which is too much to add to every
    ``start``. The warning then lands while the servers are coming up, which is
    early enough to be read. ``curio setup`` passes ``block=True``: it exits as
    soon as it returns, so a background thread would be killed before it
    reported, and waiting is the point of running setup explicitly.
    """
    def _probe() -> None:
        # Imported here, not at module scope: this file is the launcher and
        # keeps backend imports lazy, and resolving the attribute at call time
        # is also what lets a test stand in for the probe.
        from utk_curio.backend.app.packages import pip_runner

        try:
            broken = pip_runner.import_failures(merged)
        except Exception as exc:  # noqa: BLE001 - never stop a boot over a probe
            log_warning(f"[Setup] Could not verify manifest deps import: {exc}")
            return
        for name, reason in sorted(broken.items()):
            log_warning(
                f"[Setup] {name} is installed but cannot be imported: {reason}. "
                f"Nodes that need it will fail when run."
            )

    if block:
        _probe()
    else:
        threading.Thread(target=_probe, name="dep-import-probe", daemon=True).start()


TEST_SUITES = ["all", "unit", "backend", "sandbox", "jest", "e2e"]


def _parse_test_args(argv, command_prefix="curio"):
    """Parse ``curio test``'s own flags, which have nothing in common with
    ``start``/``setup``'s (hence its own parser rather than more options on
    the main one)."""
    parser = argparse.ArgumentParser(
        prog=f"{command_prefix} test",
        description="Run Curio's test suite. Delegates to scripts/test.sh.",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=f"""
    Examples:
        {command_prefix} test                       # clean, boot servers, run every suite
        {command_prefix} test unit                  # backend + sandbox + jest, no E2E
        {command_prefix} test backend               # one suite on its own
        {command_prefix} test e2e --use-existing    # E2E against servers already running
        {command_prefix} test e2e --headed --workflows Vega.json,Regression.json
        {command_prefix} test e2e --parallel 4     # 4 xdist workers, one backend+sandbox pair each
    """,
    )
    parser.add_argument(
        "suite", nargs="?", default="all", choices=TEST_SUITES,
        help=(
            "all (default) | unit = backend + sandbox + jest | "
            "backend | sandbox | jest | e2e = that suite alone"
        ),
    )
    parser.add_argument(
        "--use-existing", "-e", action="store_true",
        help="Test the servers already running; skip clean, npm install and start",
    )
    parser.add_argument(
        "--headed", action="store_true",
        help="Open a visible browser window during E2E tests",
    )
    parser.add_argument(
        "--workflows", default=None, metavar="A.json,B.json",
        help="Run only the named E2E workflow files",
    )
    parser.add_argument(
        "--allure-dir", default=None, metavar="DIR",
        help="Write the E2E run's Allure results to DIR",
    )
    parser.add_argument(
        "--parallel", default=None, metavar="N",
        help=(
            "Run the E2E suite on N pytest-xdist workers, each against its own "
            "backend+sandbox pair behind one shared frontend; 'auto' = min(4, cores/4)"
        ),
    )
    return parser.parse_args(argv)


def _test_script_flags(args) -> list[str]:
    """Translate parsed ``curio test`` args into ``scripts/test.sh`` flags."""
    flags = []
    if args.suite != "all":
        flags.append(f"--{args.suite}-only")
    if args.use_existing:
        flags.append("--use-existing")
    if args.headed:
        flags.append("--headed")
    if args.workflows:
        flags += ["--workflows", args.workflows]
    if args.allure_dir:
        flags += ["--allure-dir", args.allure_dir]
    if args.parallel:
        flags += ["--parallel", args.parallel]
    return flags


def run_tests(argv, command_prefix="curio") -> None:
    """Run the test suite and exit with its status.

    ``scripts/test.sh`` stays the single source of truth for how each
    suite is booted, and is what CI calls directly. This is a
    discoverable front door onto it (``curio test --help`` lists the
    suites) so the flag spellings do not have to be memorised.
    Never returns.
    """
    args = _parse_test_args(argv, command_prefix)

    script = Path(__file__).resolve().parent.parent / "scripts" / "test.sh"
    if not script.is_file():
        # Only shipped in a source checkout, not in the pip wheel.
        print(
            f"[ERROR] {script} not found. 'test' needs a git checkout of Curio.",
            file=sys.stderr,
        )
        sys.exit(1)

    bash = shutil.which("bash")
    if bash is None:
        print(
            "[ERROR] scripts/test.sh needs 'bash' on PATH "
            "(on Windows, run from Git Bash).",
            file=sys.stderr,
        )
        sys.exit(1)

    cmd = [bash, str(script), *_test_script_flags(args)]
    print(f"==> {' '.join(cmd)}")
    # Not log_info: setup_logging() has not run, and clean.sh wipes .curio/.
    sys.exit(subprocess.call(cmd, cwd=str(script.parent.parent)))


def main():
    # Local, like every other utk_curio import in this file: the launcher must
    # stay importable without the sandbox stack. Needed here so --help can
    # quote the floor rather than restate it.
    from utk_curio.sandbox.isolation import supervisor

    global processes
    global verbosity

    # Capture Docker shutdown (SIGINT and SIGTERM)
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    command_prefix = get_command_prefix()

    # 'test' has its own flag set; keep it out of the start/setup parser.
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        run_tests(sys.argv[2:], command_prefix)

    parser = argparse.ArgumentParser(
        description="Curio's multi-server management tool.",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=f"""
    Examples:
        {command_prefix} start                       # Start all servers (backend, sandbox, frontend)
        {command_prefix} start backend               # Start only the backend (localhost:5002)
        {command_prefix} start sandbox               # Start only the sandbox (localhost:2000)
        {command_prefix} test                        # Run the test suite ('test --help' for suites)
        {command_prefix} --verbose                   # Verbosity level (e.g., 0=silent, 1=normal, 2=debug)
        {command_prefix} --force-rebuild             # Re-build the frontend (if dev mode)
        {command_prefix} --force-db-init             # Re-initialize the backend database (if dev mode)
    """
    )
    
    parser.add_argument(
        "command",
        nargs="?",
        choices=["start", "setup", "test"],
        help=(
            "Command to execute "
            "(start: launch the servers, automatically running setup first; "
            "setup: install framework + manifest python deps for this "
            "interpreter and exit, no servers; "
            "test: run the test suite, see 'test --help')"
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
        "--no-project", action="store_true", default=False,
        help=(
            "Skip login and projects pages "
            "(sets CURIO_NO_AUTH=1, CURIO_NO_PROJECT=1). "
            "Default: off (CURIO_NO_PROJECT=0)"
        )
    )
    parser.add_argument(
        "--deploy", action="store_true", default=False,
        help=(
            "Run as a multi-user instance: enable authentication and projects "
            "(sets CURIO_NO_AUTH=0, CURIO_NO_PROJECT=0). This is the only way "
            "to turn auth on, so use it locally too when you need the login "
            "page. Also isolates node execution where the host supports it."
        ),
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
        "--allow-shared-installs", action=argparse.BooleanOptionalAction,
        default=False,
        help=(
            "Permit package and library installs on a --deploy instance that "
            "cannot scope them to one user (sets CURIO_ALLOW_SHARED_INSTALLS=1). "
            "Off by default: where node execution is not isolated, every "
            "install lands in the one interpreter that runs everybody's node "
            "code, so one user's library can change what another user's nodes "
            "import (#332, #309). Turn it on only where you would trust every "
            "account with that, e.g. a small team on a host that cannot "
            "isolate. No effect on a local run, which has one user by "
            "definition and is never gated."
        ),
    )
    parser.add_argument(
        "--exec-memory-mb", type=int, default=None,
        help=(
            "Memory a node may allocate, in MB, on top of the interpreter the "
            "isolated child starts with (sets CURIO_EXEC_MEMORY_MB, default "
            f"4096, floor {supervisor.MIN_EXEC_MEMORY_MB}). Note the real host "
            "ceiling is this times --exec-parallelism."
        ),
    )
    parser.add_argument(
        "--exec-timeout", type=int, default=None,
        help=(
            "Wall-clock and CPU allowance per isolated node, in seconds (sets "
            "CURIO_EXEC_TIMEOUT, default 300). Keep it below the backend's "
            "600s deadline so a slow node reports a clear message."
        ),
    )
    parser.add_argument(
        "--exec-parallelism", type=int, default=None,
        help=(
            "How many isolated nodes may run at once (sets "
            "CURIO_EXEC_PARALLELISM, default 2)."
        ),
    )
    parser.add_argument(
        "--save-node-outputs", action=argparse.BooleanOptionalAction, default=False,
        help=(
            "Persist every node run's output as a Computed dataset in the "
            "account Data Catalog (sets CURIO_DEFAULT_SAVE_NODE_OUTPUT=1). "
            "Saving is opt-in per node by default (via each node's Save output "
            "toggle); pass this to turn it on for every node instead."
        ),
    )
    parser.add_argument(
        "--catalog-root", default=None, metavar="PATH",
        help=(
            "Directory for the shared Data Catalog (hub read + publish "
            "target; sets CURIO_CATALOG_ROOT). Defaults to "
            "<repo_root>/datasets/. Point it at a writable, persistent path "
            "for pip/Docker deployments."
        ),
    )
    parser.add_argument(
        "--llm-provider", default=None, choices=["openai_compatible", "anthropic", "gemini"],
        help=(
            "Default AI provider for agents, node authoring and chat when a "
            "user has not configured their own (sets "
            "CURIO_DEFAULT_LLM_API_TYPE, default openai_compatible)."
        ),
    )
    parser.add_argument(
        "--llm-base-url", default=None, metavar="URL",
        help=(
            "Base URL of the default OpenAI-compatible endpoint (sets "
            "CURIO_DEFAULT_LLM_BASE_URL). Curio ships NO default endpoint: "
            "without this, an unconfigured instance resolves no provider and "
            "says so, rather than sending prompts somewhere nobody chose."
        ),
    )
    parser.add_argument(
        "--llm-model", default=None, metavar="NAME",
        help="Default model name (sets CURIO_DEFAULT_LLM_MODEL). No default.",
    )
    # There is deliberately no --llm-api-key. A key passed as an argument is
    # visible in the process list to every user on the host; set
    # CURIO_DEFAULT_LLM_API_KEY (or AICONN_API_KEY) in the environment instead.
    parser.add_argument(
        "--guest-llm-api-key", default=None, metavar="KEY",
        help=(
            "API key that enables AI features for guest users (sets "
            "GUEST_LLM_API_KEY). Without one, guests are refused. Guests "
            "otherwise inherit the default provider; GUEST_LLM_API_TYPE / "
            "_BASE_URL / _MODEL remain env-only overrides for the rare "
            "deployment that wants guests on a different model."
        ),
    )
    parser.add_argument(
        "--agent-search-url", default=None, metavar="TEMPLATE",
        help=(
            "URL template for the agents' web-search tool, with {q} for the "
            "query (sets CURIO_SEARCH_URL). Defaults to DuckDuckGo's "
            "keyless Instant Answer API. Point it at a local SearXNG, "
            "SerpAPI, or Google Programmable Search for ranked web results."
        ),
    )
    parser.add_argument(
        "--huggingface-token", default=None, metavar="TOKEN",
        help=(
            "Deployment-wide HuggingFace token for the Street Vision node's "
            "gated models (sets CURIO_DEFAULT_HUGGINGFACE_TOKEN). Each user "
            "can set their own in AI Settings, which wins over this; gated "
            "access is a per-account entitlement. Public models need no token."
        ),
    )
    parser.add_argument(
        "--collab", action="store_true", default=False,
        help=(
            "Enable real-time collaborative editing (sets ENABLE_COLLAB=1). "
            "Experimental, LAN-only. Default: off"
        ),
    )
    parser.add_argument(
        "--dev", action="store_true", default=False,
        help=(
            "Serve the frontend from the webpack dev server, with hot reload "
            "and a development bundle (sets CURIO_DEV=1). Default: off -- the "
            "built bundle in dist/ is served instead, which loads far faster."
        ),
    )
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

    # CURIO_DEV stays the mechanism every other launcher already sets -- the
    # Dockerfile pins it to 0, scripts/test.sh and the e2e fixtures to 1 -- so an
    # inherited value still applies when the flag is absent. The flag wins.
    if args.dev:
        os.environ["CURIO_DEV"] = "1"
    else:
        os.environ.setdefault("CURIO_DEV", "0")

    setup_logging(args.server)
    verbosity = int(args.verbose)

    set_environment_variables(
        backend_host=args.backend_host,
        backend_port=args.backend_port,
        sandbox_host=args.sandbox_host,
        sandbox_port=args.sandbox_port,
        no_project=args.no_project,
        deploy=args.deploy,
        with_examples=args.with_examples,
        reseed=args.reseed,
        allow_publish=args.allow_publish,
        allow_shared_installs=args.allow_shared_installs,
        collab=args.collab,
        save_node_outputs=args.save_node_outputs,
        catalog_root=args.catalog_root,
        exec_memory_mb=args.exec_memory_mb,
        exec_timeout=args.exec_timeout,
        exec_parallelism=args.exec_parallelism,
        llm_provider=args.llm_provider,
        llm_base_url=args.llm_base_url,
        llm_model=args.llm_model,
        guest_llm_api_key=args.guest_llm_api_key,
        agent_search_url=args.agent_search_url,
        huggingface_token=args.huggingface_token,
    )

    # Handle standalone rebuild or db init without starting servers. Neither
    # depends on --dev: --force-rebuild rebuilds the dist/ the default mode
    # serves, so it matters most when --dev is off.
    if not args.command:
        if args.force_rebuild:
            log_info("Rebuilding frontend...", COLOR_FRONTEND, 0)
            start_frontend(args.frontend_host, int(args.frontend_port), force_rebuild=True, no_server=True)
        if args.force_db_init:
            log_info("Re-initializing backend database...", COLOR_FRONTEND, 0)
            start_backend(args.backend_host, args.backend_port, no_server=True)
        sys.exit(0)

    if args.command == "setup":
        install_framework_requirements()
        # Blocking: this command exits on the next line, and reporting a broken
        # install is most of the value of running setup on its own.
        install_manifest_dependencies(block_on_verify=True)
        sys.exit(0)

    if args.command == "start":
        _require_supported_node()
        # Mirror the ``shutil.which("npm")`` check at the top of
        # ``start_frontend``: catch drifted Python envs at launch instead
        # of crashing the sandbox/backend on its first module-level import.
        # Framework first (gives us Flask + manifest-parsing deps), then
        # the manifest walk (covers builtin's data-ops libs + every other
        # installed package's declared python deps).
        if args.server in ("all", "backend", "sandbox") and not _skip_dep_install():
            install_framework_requirements()
            install_manifest_dependencies()

        # Autark's data path runs autk-db in the sandbox's Node, which installs
        # DuckDB's spatial extension. Seed it from the copy Curio ships so that
        # never becomes a download (#318).
        if args.server in ("all", "sandbox"):
            seed_duckdb_extensions()

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
