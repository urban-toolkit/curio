"""Shared fixtures for the dataset catalog tests.

Reuses the common ``TestConfig``/``client``/``db``/``user_and_token`` fixtures
from ``utk_curio.backend.tests._unit_fixtures`` and overrides only ``app`` —
dataset tests additionally wire ``CURIO_SHARED_DATA`` and bracket the test with
``release_connection()`` so the sandbox DuckDB handle never leaks across tests.
"""
from __future__ import annotations

import os
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
def app(tmp_path):
    # Wire a fresh temp workspace so every test gets its own isolated
    # file-system sandbox (shared data dir, user store, etc.).
    from utk_curio.sandbox.util.db import release_connection

    release_connection()
    shared_data = tmp_path / ".curio" / "data"
    shared_data.mkdir(parents=True)
    prev_cwd = os.environ.get("CURIO_LAUNCH_CWD")
    prev_shared = os.environ.get("CURIO_SHARED_DATA")
    os.environ["CURIO_LAUNCH_CWD"] = str(tmp_path)
    os.environ["CURIO_SHARED_DATA"] = str(shared_data)

    application = create_app(TestConfig)
    with application.app_context():
        _db.create_all()
        yield application
        _db.session.remove()
        _db.drop_all()

    release_connection()
    # Restore env vars so parallel/sequential tests don't interfere.
    if prev_cwd is not None:
        os.environ["CURIO_LAUNCH_CWD"] = prev_cwd
    else:
        os.environ.pop("CURIO_LAUNCH_CWD", None)
    if prev_shared is not None:
        os.environ["CURIO_SHARED_DATA"] = prev_shared
    else:
        os.environ.pop("CURIO_SHARED_DATA", None)

