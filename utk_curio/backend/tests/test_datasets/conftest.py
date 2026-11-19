"""Shared fixtures for the dataset catalog tests.

Reuses the common ``TestConfig``/``client``/``db``/``user_and_token`` fixtures
from ``utk_curio.backend.tests._unit_fixtures`` and overrides only ``app`` —
dataset tests additionally wire ``CURIO_SHARED_DATA`` and bracket the test with
``release_connection()`` so the sandbox DuckDB handle never leaks across tests.
"""
from __future__ import annotations

import pytest

from utk_curio.backend.app import create_app
from utk_curio.backend.extensions import db as _db
from utk_curio.backend.tests._unit_fixtures import (  # noqa: F401
    TestConfig,
    client,
    db,
    user_and_token,
)


@pytest.fixture()
def app(tmp_path, monkeypatch):
    # Wire a fresh temp workspace so every test gets its own isolated
    # file-system sandbox (shared data dir, user store, etc.).
    from utk_curio.sandbox.util.db import release_connection

    release_connection()
    shared_data = tmp_path / ".curio" / "data"
    shared_data.mkdir(parents=True)
    # Through monkeypatch, as tmp_curio sets its folder: a test that moves
    # either again through monkeypatch gets both back as they were before the
    # test. Put back by hand here, they were put back before monkeypatch undid
    # the test's moves, which wrote this test's folders back for every later
    # test of the process (test_output_paths.py).
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))
    monkeypatch.setenv("CURIO_SHARED_DATA", str(shared_data))

    application = create_app(TestConfig)
    with application.app_context():
        _db.create_all()
        yield application
        _db.session.remove()
        _db.drop_all()

    release_connection()


@pytest.fixture()
def file_db_app(app, tmp_path):
    """The app on a SQLite file, so each thread gets its own connection.

    A server opens one connection per thread. The in-memory engine the other
    tests use hands every thread the same connection, which SQLite does not let
    two threads use at once. ``app`` still wires the workspace this one uses.
    """
    class FileTestConfig(TestConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'index.db'}"

    application = create_app(FileTestConfig)
    with application.app_context():
        _db.create_all()
        yield application
        _db.session.remove()
        _db.drop_all()
        _db.engine.dispose()

