"""Clearing the per-user stores a truncate would orphan (#308).

``user.id`` is a bare sqlite rowid alias, so emptying the ``user`` table frees
ids that the next account takes — and the store path contains that id. Leaving
``.curio/test/users/<id>/`` behind therefore hands one test's imported agents,
packages and datasets to the next test's "fresh" account.

``/api/testing/reset-db`` has always cleared them; the e2e harness's own
truncate path (a plain ``pytest`` run, where the fixture boots the stack) did
not, which is what made two walkthrough baselines fail only in a full run.
Both now call this one helper, so they cannot drift apart again.
"""
from __future__ import annotations

import pytest

from utk_curio.backend.app.common.user_storage import clear_test_stores


@pytest.fixture()
def curio_tree(tmp_path, monkeypatch):
    """A ``.curio`` tree with a populated test subtree and a dev one beside it."""
    monkeypatch.setenv("CURIO_TESTING", "1")
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))
    monkeypatch.delenv("CURIO_STATE_DIR", raising=False)

    test_root = tmp_path / ".curio" / "test"
    (test_root / "users" / "1").mkdir(parents=True)
    (test_root / "users" / "1" / "imported-agents.json").write_text('["agent.chat"]')
    (test_root / "agents-catalog" / "agent.mine@1").mkdir(parents=True)
    (test_root / "data").mkdir()
    (test_root / "data" / "keep.duckdb").write_text("artifacts")

    dev_users = tmp_path / ".curio" / "users" / "7"
    dev_users.mkdir(parents=True)
    (dev_users / "imported-agents.json").write_text('["do not touch"]')
    return tmp_path


def test_removes_the_stores_a_freed_id_would_inherit(curio_tree):
    cleared = clear_test_stores()

    assert sorted(cleared) == ["agents-catalog", "users"]
    assert not (curio_tree / ".curio" / "test" / "users").exists()
    assert not (curio_tree / ".curio" / "test" / "agents-catalog").exists()


def test_leaves_the_rest_of_the_test_tree_alone(curio_tree):
    clear_test_stores()

    # The DuckDB artifacts a running stack holds open are not ours to delete.
    assert (curio_tree / ".curio" / "test" / "data" / "keep.duckdb").is_file()


def test_never_touches_a_developers_real_store(curio_tree, monkeypatch):
    # Without CURIO_TESTING the root is `.curio/`, where a dev `curio.py start`
    # keeps real work. The helper refuses rather than trusting its caller.
    monkeypatch.delenv("CURIO_TESTING", raising=False)
    monkeypatch.setenv("CURIO_ENV", "dev")

    assert clear_test_stores() == []
    assert (curio_tree / ".curio" / "users" / "7" / "imported-agents.json").is_file()


def test_is_idempotent(curio_tree):
    clear_test_stores()
    assert clear_test_stores() == []
