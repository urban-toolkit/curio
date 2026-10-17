"""A save the page gave up on cannot land over the tab's next save.

Saves of a dataflow leave a tab one after another, through the save queue, and
the page stops waiting for one after 2 minutes and sends the next. Stopping the
wait does not stop the server: the save given up on may still be on its way, or
waiting for the project's spec lock, and land after the next one, putting the
older dataflow back. So a save names its tab and carries a number one higher
than the tab's last save, and the server refuses a number lower than one it has
already applied from that tab, before it writes anything.

The database is a file, as on a server, so each request thread has its own
connection (``file_db_app``).
"""
from __future__ import annotations

import contextlib
import json
import threading

import pytest

from utk_curio.backend.app.projects import storage
from utk_curio.backend.extensions import db
from utk_curio.backend.tests.test_datasets.computed_test_helpers import auth_headers
from utk_curio.backend.tests.test_datasets.test_save_lock_order import (
    HOLD_SECONDS,
    STEP_SECONDS,
    _artifact,
    _release_and_join,
    _start,
)

TOKEN = "save-order-token"
NODE_TYPE = "curio.builtin/computation-analysis"
TAB = "6f1c1d2e-9a7b-4c3d-8e5f-0a1b2c3d4e5f"
OTHER_TAB = "0b9e8d7c-6a5f-4e3d-9c2b-1a0f9e8d7c6b"


@pytest.fixture()
def owner_id(file_db_app):
    """Erin and her session token, in the file database."""
    from utk_curio.backend.app.users.models import User, UserSession

    user = User(username="erin", name="Erin", email="erin@test.com")
    db.session.add(user)
    db.session.flush()
    db.session.add(UserSession(user_id=user.id, token=TOKEN))
    db.session.commit()
    return user.id


def _spec(name: str, rows_code: str) -> dict:
    """Two nodes, rows and other, each with its Save toggle on; saves differ in
    rows's code and the name."""
    return {"dataflow": {"name": name, "nodes": [
        {"id": "rows", "type": NODE_TYPE, "content": rows_code, "saveOutputDataset": True},
        {"id": "other", "type": NODE_TYPE, "content": "return 2", "saveOutputDataset": True},
    ], "edges": []}}


def _create_project(application) -> tuple:
    """A new dataflow, and the revision a canvas then holds as its basis."""
    response = application.test_client().post(
        "/api/projects",
        data=json.dumps({
            "name": "Save order", "spec": _spec("Save order", "return 0"), "outputs": [],
        }),
        headers=auth_headers(TOKEN),
    )
    assert response.status_code == 201, response.get_data(as_text=True)
    body = response.get_json()
    return body["id"], body["spec_revision"]


def _save(application, project_id, *, name, rows_code, outputs=(), tab=None,
          number=None, basis=None):
    """The canvas's save: its spec, the outputs it holds, its basis, and where
    it falls among its tab's saves."""
    body = {
        "spec": _spec(name, rows_code),
        "name": name,
        "outputs": [
            {"node_id": node_id, "filename": filename, "data_type": "dict"}
            for node_id, filename in outputs
        ],
    }
    if basis is not None:
        body["baseRevision"] = basis
    if tab is not None:
        body["saveTab"] = tab
    if number is not None:
        body["saveNumber"] = number
    return application.test_client().put(
        f"/api/projects/{project_id}", data=json.dumps(body), headers=auth_headers(TOKEN),
    )


def _rows_code(owner_id: int, project_id: str) -> str:
    spec = storage.read_spec(str(owner_id), project_id)
    return next(n["content"] for n in spec["dataflow"]["nodes"] if n["id"] == "rows")


def _on_record(owner_id: int, project_id: str) -> dict:
    """Everything a save writes: the spec and its counter, the manifest, the
    project row, and the outputs installed in the account's Data Catalog."""
    from utk_curio.backend.app.datasets.infrastructure.storage import list_user_datasets
    from utk_curio.backend.app.projects.models import Project

    user_key = str(owner_id)
    db.session.expire_all()
    row = db.session.get(Project, project_id)
    return {
        "spec": storage.read_spec(user_key, project_id),
        "revision": storage.spec_revision(user_key, project_id),
        "manifest": storage.read_manifest(user_key, project_id),
        "row": (row.name, row.spec_revision, row.updated_at),
        "outputs": {
            folder.name: (folder / "manifest.json").read_text(encoding="utf-8")
            for folder in list_user_datasets(user_key)
            if folder.name.startswith("computed.")
        },
    }


def _hold_before_spec_lock(monkeypatch, thread_name: str):
    """Hold *thread_name* just before it takes the spec lock, as a save still
    on its way or waiting behind another writer is. Returns the (reached,
    release) events."""
    reached, release = threading.Event(), threading.Event()
    real = storage.spec_write_lock

    @contextlib.contextmanager
    def held(user_key, project_id):
        if threading.current_thread().name == thread_name and not reached.is_set():
            reached.set()
            release.wait(timeout=HOLD_SECONDS)
        with real(user_key, project_id):
            yield

    monkeypatch.setattr(storage, "spec_write_lock", held)
    return reached, release


def test_a_lower_save_number_from_the_same_tab_is_refused_and_changes_nothing(
    file_db_app, owner_id,
):
    project_id, basis = _create_project(file_db_app)
    newer = _save(
        file_db_app, project_id, name="Newer", rows_code="return 'newer'",
        outputs=[("rows", _artifact(1790000000200, {"v": "newer"}))],
        tab=TAB, number=2, basis=basis,
    )
    assert newer.status_code == 200, newer.get_data(as_text=True)
    before = _on_record(owner_id, project_id)
    assert len(before["outputs"]) == 1, before["outputs"]

    older = _save(
        file_db_app, project_id, name="Older", rows_code="return 'older'",
        outputs=[
            ("rows", _artifact(1790000000100, {"v": "older"})),
            ("other", _artifact(1790000000150, {"v": "other"})),
        ],
        tab=TAB, number=1, basis=basis,
    )

    assert older.status_code == 409, older.get_data(as_text=True)
    assert "newer save" in older.get_json()["error"]
    # Nothing was written: not the spec or its counter, not the manifest or
    # the row, and not the output of the node only the older save sent.
    assert _on_record(owner_id, project_id) == before


def test_a_higher_number_another_tab_or_an_unnumbered_save_goes_through(file_db_app, owner_id):
    project_id, _ = _create_project(file_db_app)

    for name, tab, number in [
        ("First", TAB, 1),
        ("Second", TAB, 2),
        # Another tab numbers its own saves: its 1 is not older than TAB's 2.
        ("Other tab", OTHER_TAB, 1),
        # The same number again is not a lower one.
        ("Second again", TAB, 2),
        # A save that names no tab is not checked: scripts, tests, and the
        # Projects page's rename send none.
        ("Unnumbered", None, None),
    ]:
        response = _save(
            file_db_app, project_id, name=name, rows_code=f"return {name!r}",
            tab=tab, number=number,
        )
        assert response.status_code == 200, (name, response.get_data(as_text=True))
        assert _rows_code(owner_id, project_id) == f"return {name!r}", name


def test_a_save_that_lands_after_the_tabs_next_save_is_refused(file_db_app, owner_id, monkeypatch):
    """The page gave up on save 1 and sent save 2, which landed while save 1
    was still on its way. Both carry the basis of the load, since save 1 never
    answered, and save 1 only edits code, so the stale-basis guard lets it by."""
    project_id, basis = _create_project(file_db_app)
    reached, release = _hold_before_spec_lock(monkeypatch, "timed-out save")

    threads: list = []
    try:
        late = _start(threads, "timed-out save", lambda: _save(
            file_db_app, project_id, name="Older", rows_code="return 'older'",
            outputs=[
                ("rows", _artifact(1790000000100, {"v": "older"})),
                ("other", _artifact(1790000000150, {"v": "other"})),
            ],
            tab=TAB, number=1, basis=basis,
        ))
        assert reached.wait(STEP_SECONDS), "the first save never reached the spec lock"
        newer = _save(
            file_db_app, project_id, name="Newer", rows_code="return 'newer'",
            outputs=[("rows", _artifact(1790000000200, {"v": "newer"}))],
            tab=TAB, number=2, basis=basis,
        )
        assert newer.status_code == 200, newer.get_data(as_text=True)
        before = _on_record(owner_id, project_id)
    finally:
        _release_and_join(threads, release)

    assert "error" not in late, repr(late.get("error"))
    assert late["value"].status_code == 409, late["value"].get_data(as_text=True)
    assert _on_record(owner_id, project_id) == before
    assert _rows_code(owner_id, project_id) == "return 'newer'"


def test_an_unreadable_record_refuses_nothing(file_db_app, owner_id):
    """A record that cannot be read is no record: the save goes through and
    writes a fresh one."""
    project_id, _ = _create_project(file_db_app)
    record = storage.project_dir(str(owner_id), project_id) / storage.SAVE_ORDER_FILE
    record.write_text("{not json", encoding="utf-8")

    response = _save(file_db_app, project_id, name="After", rows_code="return 1", tab=TAB, number=1)

    assert response.status_code == 200, response.get_data(as_text=True)
    assert storage.last_save_number(str(owner_id), project_id, TAB) == 1


def test_the_record_keeps_the_latest_tabs(file_db_app, owner_id):
    """One entry per tab, so it is bounded: past the limit the tab that saved
    longest ago is forgotten, and a save from a forgotten tab is unchecked."""
    project_id, _ = _create_project(file_db_app)
    user_key = str(owner_id)
    tabs = [f"tab-{i}" for i in range(storage.SAVE_ORDER_TABS + 1)]
    for number, tab in enumerate(tabs, start=1):
        storage.record_save_number(user_key, project_id, tab, number)
    # One tab too many forgot the first. It saves again and is the latest,
    # which forgets the second, now the one that saved longest ago.
    storage.record_save_number(user_key, project_id, tabs[0], 100)

    assert storage.last_save_number(user_key, project_id, tabs[0]) == 100
    assert storage.last_save_number(user_key, project_id, tabs[1]) is None
    assert storage.last_save_number(user_key, project_id, tabs[2]) == 3
    assert storage.last_save_number(user_key, project_id, tabs[-1]) == len(tabs)
    on_disk = json.loads(
        (storage.project_dir(user_key, project_id) / storage.SAVE_ORDER_FILE).read_text(encoding="utf-8")
    )
    assert len(on_disk) == storage.SAVE_ORDER_TABS
