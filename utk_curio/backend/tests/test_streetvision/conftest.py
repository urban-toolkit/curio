"""Fixtures for the Street Vision route tests.

Mirrors ``test_users/conftest.py``: a bare in-memory DB and a function-scoped
``app``, because these tests need real users and sessions to prove that the
overlay route scopes its cache lookup to the *caller*.
"""
import pytest

from utk_curio.backend.app import create_app
from utk_curio.backend.extensions import db as _db
from utk_curio.backend.tests._unit_fixtures import (  # noqa: F401
    TestConfig,
    client,
    db,
)


@pytest.fixture()
def app(tmp_path, monkeypatch):
    # Anchor ``.curio/`` under the temp dir so the per-user cache helpers write
    # somewhere disposable.
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))
    application = create_app(TestConfig)
    with application.app_context():
        _db.create_all()
        yield application
        _db.session.remove()
        _db.drop_all()
