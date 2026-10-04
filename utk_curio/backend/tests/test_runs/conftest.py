"""Shared fixtures for run tests: the common app/DB/auth fixtures, with the
database in a file.

A run writes from threads of its own. An in-memory SQLite database is one
connection that every thread shares, so one thread ending its session could
roll back another's write; a file gives each thread its own connection, as a
real deployment has.
"""

from __future__ import annotations

import pytest

from utk_curio.backend.tests._unit_fixtures import (  # noqa: F401
    TestConfig,
    client,
    db,
    guest_user_and_token,
    tmp_curio,
    user_and_token,
)


@pytest.fixture()
def app(tmp_curio, tmp_path):
    from utk_curio.backend.app import create_app
    from utk_curio.backend.extensions import db as _db

    class FileConfig(TestConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'runs.db'}"

    application = create_app(FileConfig)
    with application.app_context():
        _db.create_all()
        yield application
        _db.session.remove()
        _db.drop_all()
        _db.engine.dispose()
