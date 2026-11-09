"""The startup work runs once a start: in the home process, and only in the
process that serves.

With several backend processes, the launcher names each (``CURIO_BACKEND_PROCESS``
of ``CURIO_BACKEND_PROCESSES``), and process 0, home, alone does the startup
work: the shared guest, the hosted guests' copies dropped, the agents and the
examples put back, the monitor's histories started anew, the timers, the
open-files sampler and the bucket mount service's proxy and check. Under
Werkzeug's reloader the process the launcher started only watches the files
and starts the process that serves, which does that work.

The server module runs as the launcher runs it, ``python -m backend.server``,
up to the point where it would serve, with each piece of the startup work
replaced by a record of its call.
"""
from __future__ import annotations

import collections
import runpy
from types import SimpleNamespace

import pytest

#: Each piece of the startup work, by the name the server reaches it by, with
#: what the record of its call answers.
STARTUP_WORK = {
    # create_app
    "utk_curio.backend.app.monitor.history.start": None,
    "utk_curio.backend.app.packages.seed_dev_packages": [],
    "utk_curio.backend.app.projects.tasks.start_cleanup_scheduler": None,
    "utk_curio.backend.app.runs.kept.start_prune_scheduler": None,
    # server.py, before it serves
    "utk_curio.backend.app.users.services._shared_guest_user": SimpleNamespace(id=1, username="guest", is_guest=True),
    "utk_curio.backend.app.projects.visitor_copies.drop_all": 0,
    "utk_curio.backend.app.projects.services.reconcile_guest_projects": 0,
    "utk_curio.backend.app.projects.services.seed_default_agents": None,
    "utk_curio.backend.app.projects.seed.seed_example_projects": 0,
    "utk_curio.backend.app.datasets.seed.seed_example_datasets": [],
    # serve()
    "utk_curio.backend.app.monitor.open_files.start_sampler": None,
    "utk_curio.backend.app.discovery.service.start_bucket_mount_proxy": False,
    "utk_curio.backend.app.discovery.service.start_bucket_mount_check": False,
}

#: Every piece, once.
ONCE = {name: 1 for name in STARTUP_WORK}


def _record(done: list, name: str, answer):
    def recorded(*args, **kwargs):
        done.append(name)
        return answer

    return recorded


@pytest.fixture()
def start(monkeypatch):
    """Run the server module with the environment given (None unsets a
    variable); which pieces of the startup work it did, and how often."""
    from flask_socketio import SocketIO

    from utk_curio.backend import config

    done: list[str] = []
    for name, answer in STARTUP_WORK.items():
        monkeypatch.setattr(name, _record(done, name, answer))
    monkeypatch.setattr("utk_curio.backend.app.projects.services._user_dir_key", lambda user: "guest")
    # The examples are put back with --with-examples, and the dev packages on
    # a stack that is not production: both in scope.
    monkeypatch.setattr(config, "CURIO_SEED_EXAMPLES", True)
    monkeypatch.setattr("utk_curio.backend.app._is_dev", lambda: True)
    monkeypatch.setattr("utk_curio.backend.thread_stacks.register", lambda: True)
    monkeypatch.setattr("utk_curio.sandbox.util.duckdb_threads.release_default_connection",
                        lambda *args, **kwargs: None)
    monkeypatch.setattr(SocketIO, "run", lambda *args, **kwargs: None)

    def run(**environ) -> dict:
        for name, value in environ.items():
            if value is None:
                monkeypatch.delenv(name, raising=False)
            else:
                monkeypatch.setenv(name, value)
        done.clear()
        runpy.run_module("utk_curio.backend.server", run_name="__main__")
        return dict(collections.Counter(done))

    return run


def _differences(done: dict) -> str:
    missing = sorted(name for name in STARTUP_WORK if name not in done)
    twice = sorted(name for name, times in done.items() if times > 1)
    return f"missing {missing}, more than once {twice}"


def test_only_the_home_process_does_the_startup_work(start):
    home = start(CURIO_BACKEND_PROCESS=None, CURIO_BACKEND_PROCESSES=None,
                 FLASK_USE_RELOADER="0", WERKZEUG_RUN_MAIN=None)
    assert home == ONCE, f"the home process did not do each piece of the startup work once: {_differences(home)}"

    other = start(CURIO_BACKEND_PROCESS="1", CURIO_BACKEND_PROCESSES="2",
                  FLASK_USE_RELOADER="0", WERKZEUG_RUN_MAIN=None)
    assert other == {}, f"backend process 1 of 2 did startup work, which is the home process's: {sorted(other)}"


def test_under_the_reloader_only_the_process_that_serves_does_the_startup_work(start):
    serving = start(CURIO_BACKEND_PROCESS=None, CURIO_BACKEND_PROCESSES=None,
                    FLASK_USE_RELOADER="1", WERKZEUG_RUN_MAIN="true")
    assert serving == ONCE, (
        f"the process the reloader started did not do each piece of the startup work once: {_differences(serving)}"
    )

    watching = start(CURIO_BACKEND_PROCESS=None, CURIO_BACKEND_PROCESSES=None,
                     FLASK_USE_RELOADER="1", WERKZEUG_RUN_MAIN=None)
    assert watching == {}, (
        f"the reloader's watcher, which serves nothing, did startup work: {sorted(watching)}"
    )
