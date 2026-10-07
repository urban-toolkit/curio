"""curio.py arguments to environment variables, and the isolation decision."""

import os
import secrets

from pathlib import Path

from utk_curio.cli.logs import log_always, log_warning


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
    """Why this host cannot isolate node execution."""
    if blockers:
        return "this host is missing " + ", ".join(blockers)
    return (
        f"no execution user is configured (no {DEFAULT_EXEC_USER!r} account, "
        "or Curio is not running as root)"
    )


def _refuse_unisolated_deploy(exec_user, blockers):
    """Stop a ``--deploy`` that cannot isolate, rather than serving anyway.

    There are two shapes, and this is what keeps it to two: a deployment,
    which has accounts AND isolates, or a local run, which has neither. The
    third shape -- accounts without isolation -- is the one where every user's
    node code shares one interpreter, so one person's ``pip install`` changes
    what another person's nodes import and node-authoring rights are shell
    access for everybody. It used to boot with a warning and a gate on
    installs; the warning was easy to miss and the gate was a rule nobody
    could see from the command they typed.

    ``CURIO_TESTING`` is exempt: the e2e and stress rigs run accounts without
    isolation deliberately, on one machine, with users they create themselves.
    """
    raise SystemExit(
        "Refusing to start: --deploy needs isolated node execution, and "
        f"{_why_not_isolated(exec_user, blockers)}.\n"
        "\n"
        "Without isolation every account's node code runs in one interpreter, "
        "so one user's library install changes what everybody's nodes import. "
        "Run Curio where it can isolate (the Docker image does: Linux, fork, "
        "setrlimit, pyseccomp and the curio-exec account), or drop --deploy "
        "and run it as the single-user tool it then is."
    )

def set_state_dir(state_dir=None):
    """``--state-dir`` to CURIO_STATE_DIR, where the ``.curio`` state lives.

    Apart from set_environment_variables because the launcher writes its own
    log there, and main() opens that log before it sets the rest. Resolved
    like ``--catalog-root``, since the servers run from another directory.
    """
    if state_dir:
        os.environ["CURIO_STATE_DIR"] = str(Path(state_dir).expanduser().resolve())


def set_environment_variables(backend_host, backend_port, sandbox_host, sandbox_port, no_project=False, deploy=False, with_examples=False, reseed=False, allow_publish=True, testing=False, collab=False, catalog_root=None, exec_memory_mb=None, exec_timeout=None, exec_parallelism=None, llm_provider=None, llm_base_url=None, llm_model=None, guest_llm_api_key=None, agent_search_url=None, backend_url=None, discovery_root=None, models_root=None, save_node_outputs=None, solve_max_attempts=None, solve_node_budget=None, solve_session_deadline=None, solve_batch_deadline=None, validation_exec_timeout=None, validation_node_limit=None, discovery_max_download_mb=None, guest_llm_provider=None, guest_llm_base_url=None, guest_llm_model=None, media_cache_max_gb=None, db_pool_size=None, db_pool_overflow=None, db_pool_timeout=None, package_workers=None, js_parallelism=None, js_registry_url=None, js_block_unpinned=None, shared_guest_name=None, shared_guest_username=None, collab_origins=None, collab_namespace=None, log_to_stdout=None, packages_root=None):
    """Sets the environment variables for Backend and Sandbox."""
    os.environ["FLASK_BACKEND_HOST"] = backend_host
    os.environ["FLASK_BACKEND_PORT"] = str(backend_port)
    os.environ["FLASK_SANDBOX_HOST"] = sandbox_host
    os.environ["FLASK_SANDBOX_PORT"] = str(sandbox_port)
    # The address the browser reaches the backend at: --backend-url, or the
    # same --backend-host/--backend-port the backend itself is started with, so
    # the two cannot disagree. The frontend server writes it into the page
    # (run_spa_static_server), and the webpack dev server compiles it in
    # (dotenv-webpack, ``systemvars: true``, reads this variable).
    #
    # 127.0.0.1 is normalized to localhost because the browser's origin is
    # localhost by default, and the two are distinct origins to CORS.
    browser_host = "localhost" if backend_host in ("127.0.0.1", "0.0.0.0") else backend_host
    os.environ["BACKEND_URL"] = backend_url or f"http://{browser_host}:{backend_port}"
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
    # Seeds the per-node "Save output dataset" toggle, which every user can
    # still flip in the UI.
    if save_node_outputs is not None:
        os.environ["CURIO_DEFAULT_SAVE_NODE_OUTPUT"] = "1" if save_node_outputs else "0"
    os.environ["CURIO_DEFAULT_SAVE_NODE_OUTPUT"] = os.environ.get(
        "CURIO_DEFAULT_SAVE_NODE_OUTPUT", "0"
    )
    if catalog_root:
        os.environ["CURIO_CATALOG_ROOT"] = str(Path(catalog_root).expanduser().resolve())
    if discovery_root:
        os.environ["CURIO_DISCOVERY_ROOT"] = str(Path(discovery_root).expanduser().resolve())
    if models_root:
        os.environ["CURIO_MODELS_ROOT"] = str(Path(models_root).expanduser().resolve())
    if packages_root:
        os.environ["CURIO_PACKAGES_ROOT"] = str(Path(packages_root).expanduser().resolve())
    # Respect an already-set CURIO_LAUNCH_CWD / CURIO_SHARED_DATA so the test
    # harness can point the backend at a dedicated workspace (see
    # utk_curio/backend/tests/conftest.py). Only fall back to cwd otherwise.
    os.environ["CURIO_LAUNCH_CWD"] = os.environ.get(
        "CURIO_LAUNCH_CWD"
    ) or os.getcwd()
    os.environ["CURIO_SHARED_DATA"] = os.environ.get(
        "CURIO_SHARED_DATA"
    ) or str(Path("./.curio/data").resolve())

    # Set before anything reads it: the database URL, the testing routes and
    # the isolation exemption below all key off this one value. A pre-set env
    # var still wins, because the pytest rig has no command line to pass a
    # flag on -- it imports the app in-process.
    if testing:
        os.environ["CURIO_TESTING"] = "1"

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
            if deploy and not _is_testing():
                _refuse_unisolated_deploy(exec_user, blockers)

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

    # Solve's budgets (agents/application/solve/budgets.py) and the per-node
    # timeout of an agent's validation run (execution/runner.py).
    for env_name, value in (
        ("CURIO_SOLVE_MAX_ATTEMPTS", solve_max_attempts),
        ("CURIO_SOLVE_NODE_BUDGET", solve_node_budget),
        ("CURIO_SOLVE_SESSION_DEADLINE", solve_session_deadline),
        ("CURIO_SOLVE_BATCH_DEADLINE", solve_batch_deadline),
        ("CURIO_VALIDATION_EXEC_TIMEOUT", validation_exec_timeout),
        ("CURIO_VALIDATION_NODE_LIMIT", validation_node_limit),
    ):
        if value:
            os.environ[env_name] = str(value)

    # The Discovery Catalog's download ceiling (discovery/domain/limits.py).
    if discovery_max_download_mb is not None:
        if int(discovery_max_download_mb) <= 0:
            raise ValueError("--discovery-max-download-mb must be a positive number of megabytes")
        os.environ["CURIO_DISCOVERY_MAX_DOWNLOAD_MB"] = str(int(discovery_max_download_mb))

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

    # The agents' web-search tool. Unset, it uses DuckDuckGo's keyless Instant
    # Answer API (DEFAULT_SEARCH_URL in agents/application/tools.py).
    if agent_search_url:
        os.environ["CURIO_SEARCH_URL"] = str(agent_search_url)

    # Operator settings the servers read (backend/config.py, the package
    # builder and runtime, the sandbox worker, the media cache). Each is written
    # only when its flag is passed; 0 and an empty value are values an operator
    # can mean (no pool overflow, the provider's own endpoint).
    for env_name, value in (
        ("GUEST_LLM_API_TYPE", guest_llm_provider),
        ("GUEST_LLM_BASE_URL", guest_llm_base_url),
        ("GUEST_LLM_MODEL", guest_llm_model),
        ("CURIO_DB_POOL_SIZE", db_pool_size),
        ("CURIO_DB_POOL_OVERFLOW", db_pool_overflow),
        ("CURIO_DB_POOL_TIMEOUT", db_pool_timeout),
        ("CURIO_PACKAGE_WORKERS", package_workers),
        ("CURIO_JS_PARALLELISM", js_parallelism),
        ("CURIO_JS_REGISTRY_URL", js_registry_url),
        ("CURIO_SHARED_GUEST_NAME", shared_guest_name),
        ("CURIO_SHARED_GUEST_USERNAME", shared_guest_username),
        ("COLLAB_CORS_ORIGINS", collab_origins),
        ("COLLAB_NAMESPACE", collab_namespace),
    ):
        if value is not None:
            os.environ[env_name] = str(value)
    if media_cache_max_gb is not None:
        os.environ["CURIO_MEDIA_CACHE_MAX_GB"] = f"{media_cache_max_gb:g}"
    if js_block_unpinned is not None:
        os.environ["CURIO_JS_BLOCK_UNPINNED"] = "1" if js_block_unpinned else "0"
    if log_to_stdout is not None:
        # Both servers take any non-empty value as on, and their .flaskenv
        # turns an unset one on, so off is the empty value.
        os.environ["LOG_TO_STDOUT"] = "1" if log_to_stdout else ""

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
    log_always(f"CURIO_DEFAULT_SAVE_NODE_OUTPUT={os.environ['CURIO_DEFAULT_SAVE_NODE_OUTPUT']}")
    log_always(f"CURIO_ISOLATION={os.environ['CURIO_ISOLATION']}")
    # The token itself is deliberately not logged.
    log_always("CURIO_SANDBOX_TOKEN=<set>")
    if os.environ.get("CURIO_STATE_DIR"):
        log_always(f"CURIO_STATE_DIR={os.environ['CURIO_STATE_DIR']}")
    if catalog_root:
        log_always(f"CURIO_CATALOG_ROOT={os.environ['CURIO_CATALOG_ROOT']}")
    if discovery_root:
        log_always(f"CURIO_DISCOVERY_ROOT={os.environ['CURIO_DISCOVERY_ROOT']}")
    if models_root:
        log_always(f"CURIO_MODELS_ROOT={os.environ['CURIO_MODELS_ROOT']}")
    if packages_root:
        log_always(f"CURIO_PACKAGES_ROOT={os.environ['CURIO_PACKAGES_ROOT']}")
    log_always(f"ENABLE_COLLAB={os.environ['ENABLE_COLLAB']}")


def _is_testing() -> bool:
    return os.environ.get("CURIO_TESTING", "").lower() in ("1", "true", "yes")
