"""A scenario drop copies saved outputs under the projects' spec locks (#941).

``POST .../copy`` reads each saved output the drop brings in the scenario's
project, the source, copies it to its copy in the target, then puts it where
the canvas reads outputs, as opening the project does. A save installs every
output it sends again under its project's spec lock, and installing one
replaces its folder. A project load reads its saved outputs under that lock,
so it never meets an output a save is installing again
(``services._saved_outputs``). The drop must read the source under the
source's lock and write the target under the target's, one lock at a time: the
source may be the target, and two drops each way between two projects at once
must both finish.

A test that races a save pauses it right after it installs an output again,
still holding its project's spec lock; the drop starts then, and the pause
ends once the drop has waited on that lock for a moment.
The database is a file, as on a server, so each thread has its own connection
(``file_db_app``).

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_scenario_catalog/test_copy_under_spec_lock.py -v
"""
from __future__ import annotations

import contextlib
import errno
import shutil
import threading
import time
from pathlib import Path

import pytest

from utk_curio.backend.app.datasets.domain.manifest import ManifestError
from utk_curio.backend.app.datasets.infrastructure.storage import dataset_dir, user_datasets_dir
from utk_curio.backend.app.datasets.install import copy as dataset_copy
from utk_curio.backend.app.datasets.install.installer import computed_dataset_id
from utk_curio.backend.app.projects import storage
from utk_curio.backend.app.scenario_catalog.service import ScenarioCatalogService
from utk_curio.backend.tests.test_datasets.test_reads_under_spec_lock import (  # noqa: F401
    TOKEN,
    WAIT_SECONDS,
    _pause_after_install,
    owner_id,
)
from utk_curio.backend.tests.test_datasets.test_save_lock_order import (
    HOLD_SECONDS,
    STEP_SECONDS,
    _release_and_join,
    _start,
)
from utk_curio.backend.tests.test_scenario_catalog.test_copy import (
    BASELINE,
    _copied_data,
    _copy,
    _create,
    _save_outputs,
    _shared,
    _source_and_target,
    _spec,
)

#: What the source saved first, and what a later save of it installs.
FIRST_RUN = {"load": "id,height\n1,10\n", "a": "id,sunlight\n1,0.5\n"}
SECOND_RUN = {"load": "id,height\n1,99\n", "a": "id,sunlight\n1,0.9\n"}
#: The drop: the loader's saved output and the outcome's, each to a fresh node.
BOTH = [{"source": "load", "node": "loader-1"}, {"source": "a", "node": "a-copy"}]
#: How long two drops wait for each other at their copies.
MEET_SECONDS = 2


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
    if "value" not in outcome:
        return "it has not answered"
    resp = outcome["value"]
    return f"it answered {resp.status_code}: {resp.get_data(as_text=True)}"


def _hold_after_plan(monkeypatch, thread_name: str):
    """Hold *thread_name*'s drop once it has its plan, before it copies
    anything. Returns the (planned, go) events."""
    planned, go = threading.Event(), threading.Event()
    real = ScenarioCatalogService._copies

    def copies(outputs, allowed, taken):
        if threading.current_thread().name == thread_name:
            planned.set()
            go.wait(timeout=HOLD_SECONDS)
        return real(outputs, allowed, taken)

    monkeypatch.setattr(ScenarioCatalogService, "_copies", staticmethod(copies))
    return planned, go


def _meet_at_copy(monkeypatch, names: set) -> None:
    """Hold each thread in *names* at its first folder copy until every one
    of them is copying, for up to ``MEET_SECONDS``."""
    meeting = threading.Barrier(len(names), timeout=MEET_SECONDS)
    met: set = set()
    real = shutil.copytree

    def copytree(src, dst, *args, **kwargs):
        name = threading.current_thread().name
        if name in names and name not in met:
            met.add(name)
            with contextlib.suppress(threading.BrokenBarrierError):
                meeting.wait()
        return real(src, dst, *args, **kwargs)

    monkeypatch.setattr(shutil, "copytree", copytree)


def _still_running(threads: list, seconds: float) -> list:
    """Wait up to *seconds* for *threads*; the names of those still running."""
    deadline = time.monotonic() + seconds
    for thread in threads:
        thread.join(timeout=max(0.0, deadline - time.monotonic()))
    return [thread.name for thread in threads if thread.is_alive()]


def _assert_copied_the_second_run(drop: dict, released_at: float, user_key: str, target: str, saved: dict) -> None:
    """The drop answered once the save was done, and copied and restored the
    outputs that save installed, whole."""
    assert drop["done_at"] > released_at, "the drop answered before the save was done"
    assert "error" not in drop, _answer(drop)
    resp = drop["value"]
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert _copied_data(user_key, "loader-1", target) == SECOND_RUN["load"]
    assert _copied_data(user_key, "a-copy", target) == SECOND_RUN["a"]
    restored = sorted((o["node_id"], o["filename"]) for o in resp.get_json()["outputs"])
    assert restored == [("a-copy", saved["a"]), ("loader-1", saved["load"])], restored


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
    reached, release = _pause_after_install(monkeypatch, "save", mine)
    asked = _signal_at_lock_of(monkeypatch, "drop", target)

    threads: list = []
    waited = False
    try:
        save = _start(threads, "save", lambda: _save_outputs(
            file_db_app.test_client(), TOKEN, target, {"mine": "id\n3\n"}, run=2,
        ))
        assert reached.wait(STEP_SECONDS), "the save never installed the new output"
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
    held = storage.saved_output_file(str(owner_id), target, saved["load"])
    assert held is not None and held.path.read_text(encoding="utf-8") == "id,height\n1,10\n"


def test_a_drop_during_a_save_of_its_source_copies_what_the_save_installed(
    file_db_app, owner_id, monkeypatch,  # noqa: F811
):
    """A save of the source holds the source's spec lock and has just
    installed the loader's new output, before it records the outputs, when
    the drop asks what it copies. The drop waits for the save, then copies the
    outputs it installed and recorded, whole."""
    client = file_db_app.test_client()
    source, target = _source_and_target(client, TOKEN)
    _save_outputs(client, TOKEN, source, FIRST_RUN)
    load = dataset_dir(str(owner_id), f"{computed_dataset_id('load', source)}@1")
    reached, release = _pause_after_install(monkeypatch, "save", load)
    asked = _signal_at_lock_of(monkeypatch, "drop", source)

    threads: list = []
    waited = False
    try:
        save = _start(threads, "save", lambda: _save_outputs(
            file_db_app.test_client(), TOKEN, source, SECOND_RUN, run=2,
        ))
        assert reached.wait(STEP_SECONDS), "the save never installed the loader's new output"
        drop = _start(threads, "drop", lambda: _copy(file_db_app.test_client(), TOKEN, source, target, BOTH))
        waited = asked.wait(STEP_SECONDS)
        if waited:
            time.sleep(WAIT_SECONDS)
    finally:
        released_at = _release_and_join(threads, release)

    assert "error" not in save, repr(save.get("error"))
    assert waited, (
        "the drop read the source's saved outputs while a save of the source held the "
        "source's spec lock, without waiting for it; " + _answer(drop)
    )
    _assert_copied_the_second_run(drop, released_at, str(owner_id), target, save["value"])


def test_a_save_of_the_source_between_the_plan_and_the_copy_is_waited_for(
    file_db_app, owner_id, monkeypatch,  # noqa: F811
):
    """The drop has its plan when a save of the source starts installing its
    outputs again and installs the loader's. The copy waits for that save,
    then copies what it installed, rather than the outputs of two runs."""
    client = file_db_app.test_client()
    source, target = _source_and_target(client, TOKEN)
    _save_outputs(client, TOKEN, source, FIRST_RUN)
    load = dataset_dir(str(owner_id), f"{computed_dataset_id('load', source)}@1")
    planned, go = _hold_after_plan(monkeypatch, "drop")
    reached, release = _pause_after_install(monkeypatch, "save", load)

    threads: list = []
    waited = False
    try:
        drop = _start(threads, "drop", lambda: _copy(file_db_app.test_client(), TOKEN, source, target, BOTH))
        assert planned.wait(STEP_SECONDS), "the drop never had its plan; " + _answer(drop)
        save = _start(threads, "save", lambda: _save_outputs(
            file_db_app.test_client(), TOKEN, source, SECOND_RUN, run=2,
        ))
        assert reached.wait(STEP_SECONDS), "the save never installed the loader's new output"
        # Only what the drop asks for from here on counts: the copy's reads.
        asked = _signal_at_lock_of(monkeypatch, "drop", source)
        go.set()
        waited = asked.wait(STEP_SECONDS)
        if waited:
            time.sleep(WAIT_SECONDS)
    finally:
        go.set()
        released_at = _release_and_join(threads, release)

    assert "error" not in save, repr(save.get("error"))
    assert waited, (
        "the drop copied the source's saved outputs while a save of the source held the "
        "source's spec lock, without waiting for it; " + _answer(drop)
    )
    _assert_copied_the_second_run(drop, released_at, str(owner_id), target, save["value"])


def test_a_scenario_dropped_into_its_own_project_is_copied(file_db_app, owner_id):  # noqa: F811
    """The source is the target, so the drop reads and writes under one spec
    lock. It never asks for that lock while it holds it, which would wait for
    itself for ever."""
    client = file_db_app.test_client()
    project = _create(client, TOKEN, "Shadows", _spec("Shadows", [BASELINE]))
    saved = _save_outputs(client, TOKEN, project, FIRST_RUN)

    threads: list = []
    drop = _start(threads, "drop", lambda: _copy(file_db_app.test_client(), TOKEN, project, project, BOTH))
    hung = _still_running(threads, STEP_SECONDS)

    assert not hung, f"the drop into its own project was still running after {STEP_SECONDS} s"
    assert "error" not in drop, _answer(drop)
    resp = drop["value"]
    assert resp.status_code == 200, resp.get_data(as_text=True)
    user_key = str(owner_id)
    assert _copied_data(user_key, "loader-1", project) == FIRST_RUN["load"]
    assert _copied_data(user_key, "a-copy", project) == FIRST_RUN["a"]
    # The project's own saved outputs stay as they were.
    assert _copied_data(user_key, "load", project) == FIRST_RUN["load"]
    assert _copied_data(user_key, "a", project) == FIRST_RUN["a"]
    restored = sorted((o["node_id"], o["filename"]) for o in resp.get_json()["outputs"])
    assert restored == [("a-copy", saved["a"]), ("loader-1", saved["load"])], restored


def test_two_drops_each_way_between_two_projects_both_finish(file_db_app, owner_id, monkeypatch):  # noqa: F811
    """Shadows' scenario is dropped into Sunlight while Sunlight's is dropped
    into Shadows. Each drop is held at its copy until the other is copying
    too, so each is reading its own source when both go on: a drop that held
    its source's lock while it asked for its target's would wait for the
    other for ever."""
    client = file_db_app.test_client()
    shadows = _create(client, TOKEN, "Shadows", _spec("Shadows", [BASELINE]))
    sunlight = _create(client, TOKEN, "Sunlight", _spec("Sunlight", [BASELINE]))
    _save_outputs(client, TOKEN, shadows, {"load": "id,height\n1,10\n"})
    _save_outputs(client, TOKEN, sunlight, {"load": "id,height\n2,20\n"})
    _meet_at_copy(monkeypatch, {"there", "back"})

    threads: list = []
    there = _start(threads, "there", lambda: _copy(
        file_db_app.test_client(), TOKEN, shadows, sunlight, [{"source": "load", "node": "from-shadows"}],
    ))
    back = _start(threads, "back", lambda: _copy(
        file_db_app.test_client(), TOKEN, sunlight, shadows, [{"source": "load", "node": "from-sunlight"}],
    ))
    hung = _still_running(threads, STEP_SECONDS)

    assert not hung, f"still running after {STEP_SECONDS} s, each waiting for the other: {hung}"
    for outcome in (there, back):
        assert "error" not in outcome, _answer(outcome)
        assert outcome["value"].status_code == 200, _answer(outcome)
    assert _copied_data(str(owner_id), "from-shadows", sunlight) == "id,height\n1,10\n"
    assert _copied_data(str(owner_id), "from-sunlight", shadows) == "id,height\n2,20\n"


@pytest.mark.parametrize("failure", ["unreadable", "disk full"])
def test_a_copy_that_fails_says_to_try_again_and_leaves_the_store_as_it_was(
    file_db_app, owner_id, monkeypatch, failure,  # noqa: F811
):
    """The saved output cannot be read as it is copied, or the disk fills up
    during the copy. The drop answers 409 and says to try again, naming the
    node and its project and no path on the server, and leaves nothing
    half-copied in the account's store."""
    client = file_db_app.test_client()
    source, target = _source_and_target(client, TOKEN)
    _save_outputs(client, TOKEN, source, {"load": "id,height\n1,10\n"})
    load = dataset_dir(str(owner_id), f"{computed_dataset_id('load', source)}@1")
    store = user_datasets_dir(str(owner_id))
    folders = sorted(entry.name for entry in store.iterdir() if entry.is_dir())
    if failure == "unreadable":
        def unreadable(dataset_root):
            raise ManifestError(f"manifest.json is not valid JSON in {dataset_root}")

        monkeypatch.setattr(dataset_copy, "load_dataset_manifest", unreadable)
    else:
        real_copytree = shutil.copytree

        def disk_full(src, dst, *args, **kwargs):
            if Path(src).name == load.name:
                raise OSError(errno.ENOSPC, "No space left on device", str(dst))
            return real_copytree(src, dst, *args, **kwargs)

        monkeypatch.setattr(shutil, "copytree", disk_full)

    resp = _copy(client, TOKEN, source, target, [{"source": "load", "node": "loader-1"}])

    assert resp.status_code == 409, resp.get_data(as_text=True)
    error = resp.get_json()["error"]
    assert "load" in error and "Shadows" in error and "try again" in error.lower(), error
    assert load.name not in error and str(store) not in error, error
    assert sorted(entry.name for entry in store.iterdir() if entry.is_dir()) == folders
