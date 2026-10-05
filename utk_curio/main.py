#!/usr/bin/env python3
"""curio.py's entry point: the argument parser and the start sequence.

The pieces it calls live in utk_curio/cli/.
"""

import argparse
import os
import signal
import sys
import threading
import time

from utk_curio.cli import lifecycle, logs
from utk_curio.cli.arguments import backend_url_arg, base_path_arg, get_command_prefix
from utk_curio.cli.dependencies import (
    _skip_dep_install,
    install_framework_requirements,
    install_manifest_dependencies,
    seed_duckdb_extensions,
)
from utk_curio.cli.environment import set_environment_variables
from utk_curio.cli.frontend_build import _require_supported_node
from utk_curio.cli.lifecycle import clean_shutdown, shutdown_flag, signal_handler
from utk_curio.cli.logs import COLOR_FRONTEND, log_always, log_info, logger, setup_logging
from utk_curio.cli.services import start_backend, start_frontend, start_sandbox
from utk_curio.cli.test_runner import run_tests


def main():
    # Local, like every backend and sandbox import in the launcher: it must
    # stay importable without the sandbox stack. Needed here so --help can
    # quote the floor rather than restate it.
    from utk_curio.sandbox.isolation import supervisor

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
        "--base-path", type=base_path_arg, default="", metavar="PATH",
        help=(
            "URL path the web app is served under, such as /app behind a "
            "reverse proxy (default: the root of the host). Not with --dev."
        ),
    )
    parser.add_argument(
        "--backend-url", type=backend_url_arg, default=None, metavar="URL",
        help=(
            "Address the browser reaches the backend at, such as "
            "https://example.org/app/api behind a reverse proxy (default: "
            "http://<backend-host>:<backend-port>)."
        ),
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
        "--testing", action="store_true",
        help=(
            "Run against the dedicated test database under .curio/test/ and "
            "mount the test-only /api/testing routes (sets CURIO_TESTING=1). "
            "Also the one exemption to --deploy requiring isolated execution: "
            "a rig that creates its own accounts on one machine may run them "
            "unisolated. Not for a real instance: the testing routes reset the "
            "database and sign in as any user without a password."
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
            "Wall-clock allowance per isolated node, in seconds (sets "
            "CURIO_EXEC_TIMEOUT, default 300); its CPU time may reach this "
            "times the CPUs the sandbox can use. Keep it below the backend's "
            "600s deadline so a slow node reports a clear message."
        ),
    )
    parser.add_argument(
        "--exec-parallelism", type=int, default=None,
        help=(
            "How many isolated nodes may run at once (sets "
            "CURIO_EXEC_PARALLELISM). Defaults to half the host's cores, "
            "capped at 8, with a floor of 2: the ceiling is memory, roughly "
            "this times --exec-memory-mb."
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
        "--discovery-max-download-mb", type=int, default=None, metavar="MB",
        help=(
            "The largest file the Discovery Catalog downloads or adds from a bucket, "
            "in megabytes (sets CURIO_DISCOVERY_MAX_DOWNLOAD_MB, default 1024). A "
            "source's manifest may set a lower limit for itself."
        ),
    )
    parser.add_argument(
        "--discovery-root", default=None, metavar="PATH",
        help=(
            "Directory the shipped Discovery Catalog sources are read from "
            "(sets CURIO_DISCOVERY_ROOT). Defaults to <repo_root>/discovery/. "
            "An operator's own sources stay under .curio/discovery/."
        ),
    )
    parser.add_argument(
        "--models-root", default=None, metavar="PATH",
        help=(
            "Directory the shipped Model Catalog models are read from (sets "
            "CURIO_MODELS_ROOT). Defaults to <repo_root>/models/. Models a "
            "user adds stay in that user's own store."
        ),
    )
    parser.add_argument(
        "--save-node-outputs", action=argparse.BooleanOptionalAction, default=None,
        help=(
            "Whether a new node's 'Save output dataset' toggle starts on (sets "
            "CURIO_DEFAULT_SAVE_NODE_OUTPUT). Default: off. Users can still "
            "flip it on each node."
        ),
    )
    parser.add_argument(
        "--llm-provider", default=None, choices=["openai_compatible", "anthropic", "gemini"],
        help=(
            "Provider kind of this Curio's own LLM endpoint (sets "
            "CURIO_DEFAULT_LLM_API_TYPE, default openai_compatible)."
        ),
    )
    parser.add_argument(
        "--llm-base-url", default=None, metavar="URL",
        help=(
            "Base URL of this Curio's own OpenAI-compatible endpoint (sets "
            "CURIO_DEFAULT_LLM_BASE_URL). Curio ships NO default endpoint. "
            "With this or CURIO_DEFAULT_LLM_API_KEY set, users can add an LLM "
            "configuration on it ('This Curio install' in API Settings)."
        ),
    )
    parser.add_argument(
        "--llm-model", default=None, metavar="NAME",
        help=(
            "Model of the Deployment default, the LLM configuration that "
            "answers a user who has not chosen a default of their own (sets "
            "CURIO_DEFAULT_LLM_MODEL). No default: without it there is no "
            "Deployment default."
        ),
    )
    # There is deliberately no --llm-api-key. A key passed as an argument is
    # visible in the process list to every user on the host; set
    # CURIO_DEFAULT_LLM_API_KEY in the environment instead.
    parser.add_argument(
        "--guest-llm-api-key", default=None, metavar="KEY",
        help=(
            "API key of the guest configuration, which guests answer with "
            "(sets GUEST_LLM_API_KEY). It otherwise takes "
            "CURIO_DEFAULT_LLM_API_KEY, and with neither, guests get no AI. "
            "The guest configuration takes the deployment's provider, URL "
            "and model unless GUEST_LLM_API_TYPE / _BASE_URL / _MODEL "
            "(env only) say otherwise."
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
        "--solve-max-attempts", type=int, default=None, metavar="N",
        help=(
            "How many times Solve may try one node, counting the first "
            "generation (sets CURIO_SOLVE_MAX_ATTEMPTS, default 40)."
        ),
    )
    parser.add_argument(
        "--solve-node-budget", type=int, default=None, metavar="SECONDS",
        help=(
            "Wall-clock budget of Solve's repair of one node, in seconds (sets "
            "CURIO_SOLVE_NODE_BUDGET, default 900)."
        ),
    )
    parser.add_argument(
        "--solve-session-deadline", type=int, default=None, metavar="SECONDS",
        help=(
            "How long one Solve session keeps managing the dataflow, in "
            "seconds; it also caps each node's budget (sets "
            "CURIO_SOLVE_SESSION_DEADLINE, default 900)."
        ),
    )
    parser.add_argument(
        "--solve-batch-deadline", type=int, default=None, metavar="SECONDS",
        help=(
            "Outer bound on a Solve batch, in seconds (sets "
            "CURIO_SOLVE_BATCH_DEADLINE, default 2700)."
        ),
    )
    parser.add_argument(
        "--validation-exec-timeout", type=int, default=None, metavar="SECONDS",
        help=(
            "Per-node timeout of the runs an agent makes to validate code, in "
            "seconds (sets CURIO_VALIDATION_EXEC_TIMEOUT, default 300)."
        ),
    )
    parser.add_argument(
        "--validation-node-limit", type=int, default=None, metavar="N",
        help=(
            "How many nodes one agent validation run may execute; ancestors "
            "that reuse an earlier output do not count (sets "
            "CURIO_VALIDATION_NODE_LIMIT, default 25)."
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
    if args.base_path and os.environ["CURIO_DEV"] == "1":
        parser.error("--base-path applies to the built frontend, not to the --dev server")

    setup_logging(args.server)
    logs.verbosity = int(args.verbose)

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
        testing=args.testing,
        collab=args.collab,
        catalog_root=args.catalog_root,
        exec_memory_mb=args.exec_memory_mb,
        exec_timeout=args.exec_timeout,
        exec_parallelism=args.exec_parallelism,
        llm_provider=args.llm_provider,
        llm_base_url=args.llm_base_url,
        llm_model=args.llm_model,
        guest_llm_api_key=args.guest_llm_api_key,
        agent_search_url=args.agent_search_url,
        backend_url=args.backend_url,
        discovery_root=args.discovery_root,
        models_root=args.models_root,
        save_node_outputs=args.save_node_outputs,
        solve_max_attempts=args.solve_max_attempts,
        solve_node_budget=args.solve_node_budget,
        solve_session_deadline=args.solve_session_deadline,
        solve_batch_deadline=args.solve_batch_deadline,
        validation_exec_timeout=args.validation_exec_timeout,
        validation_node_limit=args.validation_node_limit,
        discovery_max_download_mb=args.discovery_max_download_mb,
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
            lifecycle.processes = [
                start_backend(args.backend_host, args.backend_port),
                start_sandbox(args.sandbox_host, args.sandbox_port),
                start_frontend(args.frontend_host, int(args.frontend_port), force_rebuild=args.force_rebuild, base_path=args.base_path)
            ]
        else:
            if args.server == "backend":
                lifecycle.processes.append(start_backend(args.backend_host, args.backend_port))
            elif args.server == "sandbox":
                lifecycle.processes.append(start_sandbox(args.sandbox_host, args.sandbox_port))
            elif args.server == "frontend":
                lifecycle.processes.append(start_frontend(args.frontend_host, int(args.frontend_port), force_rebuild=args.force_rebuild, base_path=args.base_path))

        # Monitor the threads
        logging_thread = threading.Thread(target=logger, daemon=True)
        logging_thread.start()

        try:
            while not shutdown_flag.is_set():
                time.sleep(1)
        except KeyboardInterrupt:
            clean_shutdown(lifecycle.processes)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
