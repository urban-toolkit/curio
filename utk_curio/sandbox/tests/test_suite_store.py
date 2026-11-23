"""The sandbox suite writes its outputs to a store of its own.

A checkout's ``.curio/data/`` holds the store of the Curio a developer starts
from it (``cli/environment.py`` sets ``CURIO_SHARED_DATA`` to it). The sandbox
resolves its store from ``CURIO_SHARED_DATA``, relative to
``CURIO_LAUNCH_CWD`` (``util/db.py``, ``util/parsers.py``), and falls back to
that same ``./.curio/data/`` when nothing sets it. The backend suite sets it to
``.curio/test/data`` (``backend/tests/conftest.py``); the sandbox suite must
not fall back to the developer's store either. There it writes test outputs
into the developer's store, and after the developer's sandbox ran one node and
so holds the store's write lock, every test that opens the store fails with
DuckDB's "Could not set lock on file".
"""

import os
from pathlib import Path

from utk_curio.sandbox.util import db, parsers

from .conftest import SUITE_STORE_SET, suite_store

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _developer_stores():
    """The folders a Curio started from this checkout keeps its store in."""
    launch_dir = Path(os.environ.get("CURIO_LAUNCH_CWD", os.getcwd())).resolve()
    return {
        (launch_dir / ".curio" / "data").resolve(),
        (_REPO_ROOT / ".curio" / "data").resolve(),
    }


def test_the_suite_writes_to_a_store_of_its_own():
    store = Path(db.get_db_path()).parent
    assert store not in _developer_stores(), (
        f"the sandbox suite writes to the developer's store {store}"
    )


def test_both_readers_of_the_store_folder_agree():
    assert parsers._shared_data_dir() == Path(db.get_db_path()).parent


def test_this_process_has_the_store_the_suite_gives_it():
    """Under ``-n``, each worker's store, not the controller's it inherited.

    When the caller gave the store, the conftest set no store of its own, so
    the caller's stays.
    """
    if os.environ.get("CURIO_SHARED_DATA") != os.environ.get(SUITE_STORE_SET):
        assert SUITE_STORE_SET not in os.environ, (
            f"the conftest set the store {os.environ[SUITE_STORE_SET]}, but this "
            f"process has {os.environ.get('CURIO_SHARED_DATA')}"
        )
    else:
        assert Path(db.get_db_path()).parent == Path(suite_store())


def test_each_xdist_worker_gets_a_store_of_its_own():
    stores = {
        suite_store({}),
        suite_store({"PYTEST_XDIST_WORKER": "gw0"}),
        suite_store({"PYTEST_XDIST_WORKER": "gw1"}),
    }
    assert len(stores) == 3
    assert all(os.path.isabs(store) for store in stores)


def test_the_store_moves_with_the_state_folder(tmp_path):
    store = Path(suite_store({"CURIO_STATE_DIR": str(tmp_path)}))
    assert store.is_relative_to(tmp_path / "test")
