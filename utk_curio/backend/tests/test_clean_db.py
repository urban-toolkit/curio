"""The e2e harness's own reset path, at the call site (#357).

``test_clear_test_stores.py`` covers ``clear_test_stores()`` against a synthetic
tree. It does not go through ``_clean_db`` in ``test_frontend/fixtures.py`` --
the autouse fixture that actually runs between e2e tests, and the place #308 was
fixed. Revert that one call and every test there still passes; the only thing
that notices is a full ``test_walkthrough_baselines.py`` run, whose failure is a
pixel diff two scenes later. That is the expensive, hard-to-attribute signal
#308 was filed about in the first place.

These tests drive ``_clean_db`` itself. No browser and no server: the local
branch touches one sqlite file and the ``.curio/test`` tree, both of which
``tmp_path`` can supply.
"""
from __future__ import annotations

import sqlite3
import types

import pytest

# fixtures.py imports ``playwright.sync_api`` for a type annotation. The module
# is a declared dev dep and no browser binary is needed, but skip rather than
# error on a minimal env.
pytest.importorskip("playwright.sync_api")

from utk_curio.backend.tests.test_frontend.fixtures import (  # noqa: E402
    _SHARED_SESSION_CLASSES,
    _clean_db,
)


def _request(cls_name: str | None = None, fixturenames: tuple = ()):
    """The two attributes ``_clean_db`` reads off a pytest request."""
    cls = type(cls_name, (), {}) if cls_name else None
    return types.SimpleNamespace(cls=cls, fixturenames=list(fixturenames))


@pytest.fixture()
def populated(tmp_path, monkeypatch):
    """A per-user store plus a DB holding rows, as a finished e2e test leaves them."""
    monkeypatch.setenv("CURIO_TESTING", "1")
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))
    monkeypatch.delenv("CURIO_STATE_DIR", raising=False)
    # Unset so _clean_db takes the local branch instead of POSTing to a backend
    # that is not running here.
    monkeypatch.delenv("CURIO_E2E_USE_EXISTING", raising=False)

    store = tmp_path / ".curio" / "test" / "users" / "1"
    store.mkdir(parents=True)
    (store / "imported-agents.json").write_text('["agent.chat"]')

    db_path = tmp_path / "curio.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE user (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO user (name) VALUES ('stub')")
    conn.commit()
    conn.close()

    return types.SimpleNamespace(
        root=tmp_path,
        store=store,
        db_paths={"sqla": str(db_path), "dir": str(tmp_path)},
    )


def _user_rows(db_path: str) -> int:
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute("SELECT COUNT(*) FROM user").fetchone()[0]
    finally:
        conn.close()


def test_the_local_reset_clears_the_per_user_store(populated):
    """#308's fix, asserted where it lives. Truncating ``user`` frees ids that
    SQLite reissues from 1, so a store left behind is handed to the next
    account a test creates."""
    assert populated.store.exists()

    _clean_db(_request(), populated.db_paths)

    assert not populated.store.exists(), (
        "_clean_db truncated SQL but left .curio/test/users/ behind - the "
        "exact #308 leak"
    )
    assert not (populated.root / ".curio" / "test" / "users").exists()


def test_the_local_reset_still_truncates_sql(populated):
    """The store clear rides alongside the truncate; it does not replace it."""
    assert _user_rows(populated.db_paths["sqla"]) == 1

    _clean_db(_request(), populated.db_paths)

    assert _user_rows(populated.db_paths["sqla"]) == 0


@pytest.mark.parametrize("cls_name", _SHARED_SESSION_CLASSES)
def test_a_shared_session_class_is_left_alone(populated, cls_name):
    """These hold one class-scoped browser session; a reset between methods
    invalidates the token the browser is still holding."""
    _clean_db(_request(cls_name=cls_name), populated.db_paths)

    assert populated.store.exists()
    assert _user_rows(populated.db_paths["sqla"]) == 1


@pytest.mark.parametrize("fixture", ["loaded_workflow", "workflow_page"])
def test_a_class_scoped_canvas_fixture_is_left_alone(populated, fixture):
    _clean_db(_request(fixturenames=(fixture,)), populated.db_paths)

    assert populated.store.exists()
    assert _user_rows(populated.db_paths["sqla"]) == 1


def test_a_store_that_cannot_be_cleared_does_not_fail_the_test(
        populated, monkeypatch):
    """Best-effort by design: the next boot rewrites the store anyway, and a
    reset that raises would fail the test that was about to run, not the one
    that dirtied it."""
    import utk_curio.backend.app.common.user_storage as user_storage

    def boom():
        raise OSError("device busy")

    monkeypatch.setattr(user_storage, "clear_test_stores", boom)

    _clean_db(_request(), populated.db_paths)  # must not raise

    assert _user_rows(populated.db_paths["sqla"]) == 0
