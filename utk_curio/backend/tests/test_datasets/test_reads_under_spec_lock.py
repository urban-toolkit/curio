"""A load or a dashboard reads a project's saved outputs under its spec lock (#941).

A save installs every output it sends into the account's Data Catalog, under
the project's spec lock, and installing one again deleted its folder first.
A dashboard, or a reload, read the manifest and copied each output where the
sandbox reads it without that lock. One that read while a save was rewriting
the folder found no saved copy and dropped the output without a word: the
dashboard showed an empty tile, or one over the size limit was built instead
of refused.

A new output now goes in beside the old one, so the folder is never empty,
but a reader must still wait for the save: the outputs it records are written
after they are installed. The save is paused right after it installs the new
output, still holding the spec lock; the reader starts then, and the pause
ends once the reader has waited on the spec lock for a moment. The database
is a file, as on a server, so each thread has its own connection
(``file_db_app``).
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import threading
import time
from pathlib import Path

import pytest

from utk_curio.backend.app.datasets.domain.manifest import load_dataset_manifest
from utk_curio.backend.app.datasets.install.installer import computed_dataset_id
from utk_curio.backend.app.datasets.repositories import index as index_repo
from utk_curio.backend.extensions import db
from utk_curio.backend.tests.test_datasets.computed_test_helpers import (
    auth_headers,
    store_sandbox_artifact,
)
from utk_curio.backend.tests.test_datasets.test_save_lock_order import (
    HOLD_SECONDS,
    STEP_SECONDS,
    _artifact,
    _release_and_join,
    _signal_at_spec_lock,
    _start,
)

TOKEN = "reads-under-lock-token"
PRODUCER = "rows"
CHART = "chart"
LABEL = "Rows"
# How long the reader waits on the save's spec lock before the save goes on.
WAIT_SECONDS = 0.2
# A dashboard page this small cannot carry the producer's rows.
LIMIT_BYTES = 1024
HEAVY_ENVELOPE = {"dataType": "dataframe", "data": {"note": ["x" * 2048]}, "schema": {"note": "object"}}


@pytest.fixture()
def owner_id(file_db_app):
    """Dana and her session token, in the file database."""
    from utk_curio.backend.app.users.models import User, UserSession

    user = User(username="dana", name="Dana", email="dana@test.com")
    db.session.add(user)
    db.session.flush()
    db.session.add(UserSession(user_id=user.id, token=TOKEN))
    db.session.commit()
    return user.id


def _spec() -> dict:
    """A producer feeding a chart pinned to the dashboard."""
    return {"dataflow": {"name": "Reads under lock", "nodes": [
        {"id": PRODUCER, "type": "curio.builtin/computation-analysis", "content": "return rows"},
        {"id": CHART, "type": "curio.builtin/vis-vega", "content": "{}", "dashboardPinned": True},
    ], "edges": [{"id": f"{PRODUCER}-{CHART}", "source": PRODUCER, "target": CHART}]}}


def _create_project(application) -> str:
    response = application.test_client().post(
        "/api/projects",
        data=json.dumps({"name": "Reads under lock", "spec": _spec(), "outputs": []}),
        headers=auth_headers(TOKEN),
    )
    assert response.status_code == 201, response.get_data(as_text=True)
    return response.get_json()["id"]


def _save(application, project_id: str, filename: str, *, data_type: str = "dict", node_name: str = LABEL):
    """The canvas's save: its spec and the producer's output."""
    response = application.test_client().put(
        f"/api/projects/{project_id}",
        data=json.dumps({
            "spec": _spec(),
            "outputs": [{
                "node_id": PRODUCER, "filename": filename,
                "data_type": data_type, "node_name": node_name,
            }],
        }),
        headers=auth_headers(TOKEN),
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    warnings = response.get_json().get("dataset_install_warnings")
    assert warnings == [], warnings
    return response


def _shared(filename: str) -> Path:
    """Where the canvas's copy of an output is, and where a load puts it."""
    return Path(os.environ["CURIO_SHARED_DATA"]) / filename


def _producer_folder(owner_id: int, project_id: str) -> Path:
    """The producer's saved output in the account's Data Catalog."""
    from utk_curio.backend.app.datasets.infrastructure.storage import dataset_dir

    return dataset_dir(str(owner_id), f"{computed_dataset_id(PRODUCER, project_id)}@1")


def _pause_after_install(monkeypatch, thread_name: str, folder: Path):
    """Hold *thread_name* right after it installs an output into *folder*, the
    first time, before its save records it. Returns the (reached, release)
    events."""
    from utk_curio.backend.app.datasets.install import installer

    reached, release = threading.Event(), threading.Event()
    real = installer._index

    def index(user_key, result):
        indexed = real(user_key, result)
        if (threading.current_thread().name == thread_name and result.dest.name == folder.name
                and not reached.is_set()):
            reached.set()
            release.wait(timeout=HOLD_SECONDS)
        return indexed

    monkeypatch.setattr(installer, "_index", index)
    return reached, release


def _removals_of(monkeypatch, folder: Path) -> list:
    """Every removal of *folder* from now on, by any thread."""
    removed: list = []
    real = shutil.rmtree

    def rmtree(path, *args, **kwargs):
        if Path(path).name == folder.name:
            removed.append(str(path))
        return real(path, *args, **kwargs)

    monkeypatch.setattr(shutil, "rmtree", rmtree)
    return removed


def _sandbox_get(filename: str) -> dict:
    """The sandbox's ``/get`` as a dashboard asks it, with no session id: it
    reads a saved output only from the shared data folder, where the load put
    it."""
    if not _shared(filename).is_file():
        raise KeyError(filename)
    return HEAVY_ENVELOPE


def _no_raster(filename, part):
    return {"status": 404, "meta": None, "message": "no raster here"}


def _dashboard(application, project_id: str) -> dict:
    """``GET /api/projects/<id>/dashboard`` with a small page limit."""
    from utk_curio.backend.app.projects.services import build_standalone_dashboard

    with application.app_context():
        return build_standalone_dashboard(
            project_id, limit_bytes=LIMIT_BYTES,
            fetch_envelope=_sandbox_get, fetch_raster=_no_raster, registry={},
        )


def _load(application, owner_id: int, project_id: str) -> dict:
    """The owner opening the project: ``GET /api/projects/<id>``."""
    from utk_curio.backend.app.projects.services import load_project
    from utk_curio.backend.app.users.models import User

    with application.app_context():
        return load_project(db.session.get(User, owner_id), project_id)


def _read_during_a_save(application, owner_id, monkeypatch, read) -> dict:
    """Save the producer's output, lose the canvas's copy of it, then save a new
    output and run *read* while that save has just installed it.

    Returns the outcomes: the save's, the reader's, whether the reader asked
    for the spec lock during the pause, and when the pause ended.
    """
    project_id = _create_project(application)
    first = _artifact(1790000000000, {"rows": 1})
    _save(application, project_id, first)
    # Only the saved copy in the Data Catalog is left to load the output from,
    # as for a visitor holding a dashboard link, or after a restart.
    _shared(first).unlink()
    second = _artifact(1790000000100, {"rows": 2})
    reached, release = _pause_after_install(monkeypatch, "save", _producer_folder(owner_id, project_id))
    asked = _signal_at_spec_lock(monkeypatch, "reader")

    threads: list = []
    waited = False
    try:
        save = _start(threads, "save", lambda: _save(application, project_id, second))
        assert reached.wait(STEP_SECONDS), "the save never installed the new output"
        reader = _start(threads, "reader", lambda: read(project_id))
        waited = asked.wait(STEP_SECONDS)
        if waited:
            time.sleep(WAIT_SECONDS)
    finally:
        released_at = _release_and_join(threads, release)

    assert "error" not in save, repr(save.get("error"))
    return {
        "reader": reader, "waited": waited, "released_at": released_at,
        "project_id": project_id, "second": second,
    }


def _outcome(outcome: dict) -> str:
    if "error" in outcome:
        return f"it raised {outcome['error']!r}"
    return f"it returned {outcome.get('value')!r}"


def test_a_dashboard_asked_for_during_a_save_waits_for_the_save(file_db_app, owner_id, monkeypatch):
    """The page asked for while a save rewrites the producer's output is built
    from the saved output once the save is done: here it is over the page's
    limit, so it is refused, naming the producer."""
    from utk_curio.backend.app.projects.dashboard_payload import DashboardTooLargeError

    run = _read_during_a_save(
        file_db_app, owner_id, monkeypatch,
        lambda project_id: _dashboard(file_db_app, project_id),
    )
    reader = run["reader"]

    assert run["waited"], (
        "the dashboard read the project while a save was rewriting its output, "
        "without waiting for the spec lock; " + _outcome(reader)
    )
    assert reader["done_at"] > run["released_at"], "the dashboard was built before the save was done"
    error = reader.get("error")
    assert isinstance(error, DashboardTooLargeError), (
        "the producer's rows are over the page's limit, so the dashboard must be "
        "refused; " + _outcome(reader)
    )
    assert [weight.node_id for weight in error.weights] == [PRODUCER]
    assert PRODUCER in error.describe()


def test_a_load_during_a_save_waits_for_the_save(file_db_app, owner_id, monkeypatch):
    """The owner opening the project while a save rewrites the producer's
    output gets the output that save recorded, not a node without one."""
    run = _read_during_a_save(
        file_db_app, owner_id, monkeypatch,
        lambda project_id: _load(file_db_app, owner_id, project_id),
    )
    reader = run["reader"]

    assert run["waited"], (
        "the load read the project while a save was rewriting its output, "
        "without waiting for the spec lock; " + _outcome(reader)
    )
    assert "error" not in reader, repr(reader.get("error"))
    assert reader["done_at"] > run["released_at"], "the load answered before the save was done"
    restored = [ref["filename"] for ref in reader["value"]["outputs"] if ref["node_id"] == PRODUCER]
    assert restored == [run["second"]], (
        f"the load restored {restored} for the producer; the save recorded {run['second']}"
    )
    assert _shared(run["second"]).is_file()


def _output(data_type: str) -> str:
    """One output of the producer, as its run writes it: a JSON file, or a
    tuple the store keeps as a bundle of parts."""
    if data_type == "outputs":
        return store_sandbox_artifact((1, "x"), node_id=PRODUCER)
    return _artifact(1790000000000, {"rows": 1})


def _index_row_matches(owner_id: int, folder: Path) -> bool:
    db.session.expire_all()
    row = index_repo.get_by_dir(str(owner_id), folder.name)
    return row is not None and row.manifest_mtime_ns == (folder / "manifest.json").stat().st_mtime_ns


@pytest.mark.parametrize("data_type", ["dict", "outputs"], ids=["one-file", "bundle"])
def test_an_output_sent_again_unchanged_is_not_installed_again(file_db_app, owner_id, monkeypatch, data_type):
    """A save sends the output of every node the canvas keeps, so most of what
    it installs is already in the Data Catalog. That copy stays where it is;
    a new name for the node only renames the dataset."""
    project_id = _create_project(file_db_app)
    output = _output(data_type)
    _save(file_db_app, project_id, output, data_type=data_type)
    folder = _producer_folder(owner_id, project_id)
    data_file = load_dataset_manifest(folder).data_file
    # Anything in the folder goes with it when the output is installed again.
    kept = folder / "kept.txt"
    kept.write_text("installed once", encoding="utf-8")
    removed = _removals_of(monkeypatch, folder)

    _save(file_db_app, project_id, output, data_type=data_type)
    _save(file_db_app, project_id, output, data_type=data_type, node_name="Rows, renamed")

    assert removed == [], "a save installed again the output the Data Catalog already holds"
    assert kept.is_file()
    manifest = load_dataset_manifest(folder)
    assert manifest.name == "Rows, renamed"
    assert manifest.data_file == data_file
    assert (folder / data_file).is_file()
    assert _index_row_matches(owner_id, folder), "the dataset index does not match the renamed dataset"


def test_a_changed_output_is_installed_again(file_db_app, owner_id):
    """A new output of the producer replaces the saved one."""
    project_id = _create_project(file_db_app)
    _save(file_db_app, project_id, _artifact(1790000000000, {"rows": 1}))
    folder = _producer_folder(owner_id, project_id)
    kept = folder / "kept.txt"
    kept.write_text("installed once", encoding="utf-8")
    newer = _artifact(1790000000100, {"rows": 2})

    _save(file_db_app, project_id, newer)

    assert not kept.exists()
    manifest = load_dataset_manifest(folder)
    assert manifest.data_file == f"data/{newer}"
    assert json.loads((folder / manifest.data_file).read_text(encoding="utf-8")) == {"rows": 2}
    assert _index_row_matches(owner_id, folder)


def test_a_dashboard_whose_saved_output_cannot_be_read_says_try_again(file_db_app, owner_id, caplog):
    """The manifest lists the producer's output, but no copy of it can be put
    where the sandbox reads it. The page is refused with "try again" instead
    of drawing the tile empty, as if the dataflow had never run, and the log
    says which output was left out."""
    from utk_curio.backend.app.projects.dashboard_payload import DashboardOutputUnreadableError

    caplog.set_level(logging.WARNING)
    project_id = _create_project(file_db_app)
    output = _artifact(1790000000000, {"rows": 1})
    _save(file_db_app, project_id, output)
    _shared(output).unlink()
    shutil.rmtree(_producer_folder(owner_id, project_id))

    with pytest.raises(DashboardOutputUnreadableError) as refused:
        _dashboard(file_db_app, project_id)

    assert refused.value.offenders == [PRODUCER]
    assert refused.value.name == "Reads under lock"
    assert "Try again" in refused.value.describe()
    assert PRODUCER in refused.value.describe()
    left_out = [
        record.getMessage() for record in caplog.records
        if record.levelno >= logging.WARNING and output in record.getMessage()
    ]
    assert left_out and PRODUCER in left_out[0], (
        "nothing in the log says the output was left out: "
        + "; ".join(record.getMessage() for record in caplog.records)
    )
