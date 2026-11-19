"""In a start of several backend processes, the home process does the startup
work while it owns every dataflow, and serves once the dataflows are their
owners' again (``collaboration/owner_guard.before_the_others_serve``).

The launcher starts the other processes only once home answers, so while home
does the startup work (the agents every account has and the examples put
back) no other process listens: a change it sent a dataflow's owner then would
reach no one. So home owns every dataflow until that work is done, then keeps
no doc of a dataflow another process owns
(``test_collaboration/test_home_at_startup.py``), and only then serves.

The server module runs as the launcher runs it, ``python -m backend.server``,
as process 0 of 2, up to the point where it would serve, with each piece of
the startup work replaced by a note of which process owned a dataflow of
process 1 when it ran.
"""
from __future__ import annotations

import runpy

from .test_backend_startup_once import STARTUP_WORK

#: A dataflow of process 1 of 2 (``backend_processes.shard_of``).
THEIRS = "413a5c1e-0b4d-4c8e-9a7f-2d6b8e1c5a90"

#: The pieces ``serve()`` starts, once the startup work before it is done.
_SERVE = {
    "utk_curio.backend.app.monitor.open_files.start_sampler",
    "utk_curio.backend.app.discovery.service.start_bucket_mount_proxy",
    "utk_curio.backend.app.discovery.service.start_bucket_mount_check",
}


def test_the_home_process_owns_every_dataflow_while_it_does_the_startup_work_then_serves_as_one_of_several(
        monkeypatch):
    from flask_socketio import SocketIO

    from utk_curio.backend import config
    from utk_curio.backend.app.collaboration import dataflow_docs, owner_guard
    from utk_curio.common.backend_processes import shard_of

    assert shard_of(THEIRS, 2) == 1
    seen: dict[str, object] = {}

    def noted(name, answer):
        def recorded(*args, **kwargs):
            seen.setdefault(name, owner_guard.elsewhere(THEIRS))
            return answer

        return recorded

    for name, answer in STARTUP_WORK.items():
        monkeypatch.setattr(name, noted(name, answer))
    monkeypatch.setattr("utk_curio.backend.app.projects.services._user_dir_key", lambda user: "guest")
    monkeypatch.setattr(config, "CURIO_SEED_EXAMPLES", True)
    monkeypatch.setattr("utk_curio.backend.app._is_dev", lambda: True)
    monkeypatch.setattr("utk_curio.backend.thread_stacks.register", lambda: True)
    monkeypatch.setattr("utk_curio.sandbox.util.duckdb_threads.release_default_connection",
                        lambda *args, **kwargs: None)
    monkeypatch.setattr(SocketIO, "run", noted("serve", None))
    # This test's own open docs: none another test left.
    monkeypatch.setattr(dataflow_docs, "_docs", {})
    for name, value in (("CURIO_BACKEND_PROCESS", "0"), ("CURIO_BACKEND_PROCESSES", "2"),
                        ("FLASK_USE_RELOADER", "0")):
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("WERKZEUG_RUN_MAIN", raising=False)

    runpy.run_module("utk_curio.backend.server", run_name="__main__")

    before = {name: owner for name, owner in seen.items() if name != "serve" and name not in _SERVE}
    assert before and set(before) == set(STARTUP_WORK) - _SERVE, f"the startup work ran in part: {sorted(seen)}"
    assert all(owner is None for owner in before.values()), (
        f"the home process sent a change to process 1, which does not listen yet, during the startup work: {before}"
    )
    after = {name: owner for name, owner in seen.items() if name == "serve" or name in _SERVE}
    assert after == {name: 1 for name in (*_SERVE, "serve")}, (
        f"the home process serves while it still owns the other processes' dataflows: {after}"
    )
