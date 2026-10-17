"""A scenario drop restores the outputs it copied under the target's spec lock (#941).

``POST .../copy`` copies each saved output the drop brings to its copy in the
target, then puts it where the canvas reads outputs (``restore_outputs``), as
opening the project does. A project load reads its saved outputs under the
project's spec lock, so it never meets an output a save is installing again
(``services._saved_outputs``). The drop read them without it.

A save of the target is paused right after it removes the folder of an output
it installs again, holding the target's spec lock; the drop starts then, and
the pause ends once the drop has waited on that lock for a moment. The
database is a file, as on a server, so each thread has its own connection
(``file_db_app``).

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_scenario_catalog/test_copy_under_spec_lock.py -v
"""
from __future__ import annotations

import contextlib
import threading
import time

from utk_curio.backend.app.datasets.infrastructure.storage import dataset_dir
from utk_curio.backend.app.datasets.install.installer import computed_dataset_id
from utk_curio.backend.app.projects import storage
from utk_curio.backend.tests.test_datasets.test_reads_under_spec_lock import (  # noqa: F401
    TOKEN,
    WAIT_SECONDS,
    _pause_after_rmtree,
    owner_id,
)
from utk_curio.backend.tests.test_datasets.test_save_lock_order import (
    STEP_SECONDS,
    _release_and_join,
    _start,
)
from utk_curio.backend.tests.test_scenario_catalog.test_copy import (
    _copy,
    _save_outputs,
    _shared,
    _source_and_target,
)


def _signal_at_lock_of(monkeypatch, thread_name: str, project_id: str) -> threading.Event:
    """An event set when *thread_name* asks for *project_id*'s spec lock."""
    asked = threading.Event()
    real = storage.spec_write_lock

    @contextlib.contextmanager
    def observed(user_key, locked_id):
        if threading.current_thread().name == thread_name and locked_id == project_id:
            asked.set()
        with real(user_key, locked_id):
            yield

    monkeypatch.setattr(storage, "spec_write_lock", observed)
    return asked


def _answer(outcome: dict) -> str:
    if "error" in outcome:
        return f"it raised {outcome['error']!r}"
    resp = outcome["value"]
    return f"it answered {resp.status_code}: {resp.get_data(as_text=True)}"


def test_a_drop_during_a_save_of_its_target_restores_once_the_save_is_done(
    file_db_app, owner_id, monkeypatch,  # noqa: F811
):
    """The drop waits for the save of the target that holds its spec lock,
    then restores the loader's copy from the target's own saved output."""
    client = file_db_app.test_client()
    source, target = _source_and_target(client, TOKEN)
    saved = _save_outputs(client, TOKEN, source, {"load": "id,height\n1,10\n", "a": "id,sunlight\n1,0.5\n"})
    _save_outputs(client, TOKEN, target, {"mine": "id\n2\n"})
    # Only the copy in the target is left to restore the loader's output from.
    (_shared() / saved["load"]).unlink()
    mine = dataset_dir(str(owner_id), f"{computed_dataset_id('mine', target)}@1")
    reached, release = _pause_after_rmtree(monkeypatch, "save", mine)
    asked = _signal_at_lock_of(monkeypatch, "drop", target)

    threads: list = []
    waited = False
    try:
        save = _start(threads, "save", lambda: _save_outputs(
            file_db_app.test_client(), TOKEN, target, {"mine": "id\n3\n"}, run=2,
        ))
        assert reached.wait(STEP_SECONDS), "the save never removed the saved output it installs again"
        drop = _start(threads, "drop", lambda: _copy(
            file_db_app.test_client(), TOKEN, source, target, [{"source": "load", "node": "loader-1"}],
        ))
        waited = asked.wait(STEP_SECONDS)
        if waited:
            time.sleep(WAIT_SECONDS)
    finally:
        released_at = _release_and_join(threads, release)

    assert "error" not in save, repr(save.get("error"))
    assert waited, (
        "the drop restored its outputs while a save of the target held the target's "
        "spec lock, without waiting for it; " + _answer(drop)
    )
    assert drop["done_at"] > released_at, "the drop answered before the save was done"
    assert "error" not in drop, _answer(drop)
    resp = drop["value"]
    assert resp.status_code == 200, resp.get_data(as_text=True)
    restored = [(o["node_id"], o["filename"]) for o in resp.get_json()["outputs"]]
    assert restored == [("loader-1", saved["load"])], restored
    assert (_shared() / saved["load"]).read_text(encoding="utf-8") == "id,height\n1,10\n"
