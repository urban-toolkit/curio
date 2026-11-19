import os

from werkzeug.serving import WSGIRequestHandler, is_running_from_reloader

from utk_curio.backend import thread_stacks
from utk_curio.backend.app import create_app
from utk_curio.backend.app.collaboration import owner_guard
from utk_curio.backend.config import CURIO_SEED_EXAMPLES
from utk_curio.common import backend_processes
from utk_curio.common.request_deadline import RequestHeadDeadline


def _uses_reloader():
    """Whether Werkzeug's reloader runs the backend: ``FLASK_USE_RELOADER``,
    on unless it is "0"."""
    return os.getenv('FLASK_USE_RELOADER', '1') != '0'


#: Whether this process does the startup work: the home process
#: (``common/backend_processes.py``), when it serves. Under the reloader the
#: process the launcher started only watches the files, and the process it
#: starts serves and does the work.
DOES_STARTUP_WORK = backend_processes.is_home() and (
    not _uses_reloader() or is_running_from_reloader()
)


# Shared with sandbox/server.py; see utk_curio/backend/reloader.py.
from utk_curio.backend.reloader import (  # noqa: E402,F401  (re-exported)
    DEFAULT_RELOADER_TYPE,
    RELOADER_EXCLUDE_PATTERNS,
)


def _seed_the_shared_guest():
    """The shared guest at a start: its row, its hosted guests' copies
    dropped, its projects read back from the files, the agents every account
    has, the packages ``--guest-packages`` names, and with ``--with-examples``
    the examples and their datasets put back. Startup work
    (``DOES_STARTUP_WORK``)."""
    with app.app_context():
        try:
            from utk_curio.backend.app.users.services import _shared_guest_user
            from utk_curio.backend.app.projects.services import (
                _user_dir_key,
                reconcile_guest_projects,
                seed_default_agents,
            )
            guest = _shared_guest_user()
            # The hosted guests' copies go, as their examples are put back.
            from utk_curio.backend.app.projects import visitor_copies
            dropped = visitor_copies.drop_all()
            if dropped:
                app.logger.info("Dropped %d hosted guest copy(ies) of dataflows", dropped)
            n = reconcile_guest_projects(guest)
            if n:
                app.logger.info("Reconciled %d guest project(s) from filesystem", n)
            # The agents every account has by default, before the examples are put
            # back, so each example gets them, and every guest's copy of one too.
            seed_default_agents(guest)
            # The catalog packages every hosted guest has, put in the account as
            # an add puts them there; what the flag no longer names is taken off.
            # A failure here leaves the examples to be put back all the same.
            try:
                from utk_curio.backend.app.packages.service import add_guest_packages

                given = add_guest_packages(_user_dir_key(guest))
                if given:
                    app.logger.info("Hosted guests have the package(s) %s", ", ".join(given))
            except Exception:
                app.logger.warning("Could not give hosted guests the --guest-packages packages", exc_info=True)
            if CURIO_SEED_EXAMPLES:
                from utk_curio.backend.app.projects.seed import seed_example_projects
                s = seed_example_projects(guest)
                app.logger.info("Seeded %d example project(s)", s)
                # After the projects exist, provision the datasets their
                # ``dataflow.datasets`` refs declare - the dataset counterpart to
                # the node-package seeding in ``app/__init__.py``. Without the
                # store copy the refs still resolve for execution (the hub row wins
                # the catalog dedupe) but the Data palette has no title, format or
                # count to show.
                from utk_curio.backend.app.datasets.seed import seed_example_datasets
                d = seed_example_datasets(_user_dir_key(guest))
                if d:
                    app.logger.info(
                        "Provisioned %d example dataset(s): %s", len(d), ", ".join(d)
                    )
        except Exception:
            app.logger.warning("Could not ensure guest user on startup", exc_info=True)


# In a start of several processes the launcher starts the others once this
# one serves, so while it does the startup work it owns every dataflow, then
# keeps no doc of one another process owns (owner_guard.py).
with owner_guard.before_the_others_serve(DOES_STARTUP_WORK):
    app = create_app(startup_work=DOES_STARTUP_WORK)
    if DOES_STARTUP_WORK:
        _seed_the_shared_guest()


@app.route('/health', methods=['GET'])
def health():
    return 'OK', 200

def _run_kwargs():
    """The arguments both server flavours share, resolved from the environment.

    A function rather than two literal argument lists because ``debug`` has to
    be the same on both paths and neither path can be exercised by a test that
    starts a server. ``CURIO_BACKEND_DEBUG`` is read here rather than left to
    Flask's own ``FLASK_DEBUG``: the explicit ``debug=`` argument to ``run()``
    overrides that variable, and socketio.run has to be handed the value
    regardless, so honouring FLASK_DEBUG would mean reimplementing its parsing
    in two places.

    Note that ``use_reloader`` is separate and unchanged, so turning debug off
    does not turn auto-reload off with it.
    """
    from utk_curio.backend.config import CURIO_BACKEND_DEBUG

    return {
        'host': os.getenv('FLASK_BACKEND_HOST', '127.0.0.1'),
        'port': int(os.getenv('FLASK_BACKEND_PORT', 5002)),
        'debug': CURIO_BACKEND_DEBUG,
        'use_reloader': _uses_reloader(),
    }


class RequestHandler(RequestHeadDeadline, WSGIRequestHandler):
    """Werkzeug's request handler, which closes a connection that sends no
    request within ``request_start_timeout`` seconds (``RequestHeadDeadline``)."""


def _socketio_run_kwargs():
    """What ``socketio.run`` is handed: ``_run_kwargs``, the reloader's
    exclusions, which Flask-SocketIO passes on to Werkzeug's reloader only as
    ``reloader_options``, and the request handler. Without the exclusions a
    package install, which writes under ``.curio/`` and ``site-packages/``,
    restarts a dev backend mid-request.

    The Werkzeug server is the one Flask-SocketIO's threading mode runs on (a
    thread per request and per WebSocket); ``allow_unsafe_werkzeug`` lets it
    start without a terminal, as the launcher and the Docker image start it.
    Flask-SocketIO hands ``request_handler`` on to Werkzeug's ``run_simple``.
    """
    return {
        'allow_unsafe_werkzeug': True,
        'reloader_options': {
            'exclude_patterns': RELOADER_EXCLUDE_PATTERNS,
            'reloader_type': DEFAULT_RELOADER_TYPE,
        },
        'request_handler': RequestHandler,
        **_run_kwargs(),
    }


def _bucket_mount_proxy_host(run_kwargs):
    """Where the bucket mount service's proxy listens: where the backend
    listens, the launcher's ``--backend-host``. In a start of several
    processes that is where nginx listens (``ROUTER_HOST_VARIABLE``), not
    this process's own 127.0.0.1, which the service's container cannot
    reach."""
    return os.getenv(backend_processes.ROUTER_HOST_VARIABLE) or run_kwargs["host"]


def serve():
    """Serve the backend, Socket.IO included, until it is stopped."""
    # SIGUSR1 writes every thread's stack to a file (thread_stacks.py), which
    # the stress jobs ask for after a tier with failures.
    thread_stacks.register()

    # The connection DuckDB 1.x's import opens holds a thread per core and
    # serves nothing here (2.0 opens it on first use only). Imported now, so a
    # later import opens no pool of its own.
    from utk_curio.sandbox.util.duckdb_threads import release_default_connection
    release_default_connection(
        "[backend]", "so its threads stay idle in this process", import_first=True,
    )

    run_kwargs = _socketio_run_kwargs()
    # The hourly sample of this process's open files, from now: in the home
    # process when it serves (DOES_STARTUP_WORK), the sandbox's with it, and
    # in every other process of a start of several. Under the reloader this
    # function also runs in the process that only watches the files, which
    # serves nothing.
    from utk_curio.backend.app.monitor import open_files as monitor_open_files

    if monitor_open_files.sampler_starts_here(DOES_STARTUP_WORK):
        monitor_open_files.start_sampler(app)
    if DOES_STARTUP_WORK:
        from utk_curio.backend.app.discovery import service as discovery_service

        # When --bucket-mounts-dir and --bucket-mount-socket name a bucket
        # mount service: its one way out, a proxy where the backend listens,
        # then its self-test, once; /monitor shows how it went.
        discovery_service.start_bucket_mount_proxy(_bucket_mount_proxy_host(run_kwargs))
        discovery_service.start_bucket_mount_check()

    # The app's own SocketIO server (extensions.init_socketio), which
    # Flask-SocketIO keeps on the app.
    app.extensions["socketio"].run(app, **run_kwargs)


if __name__ == '__main__':
    serve()

