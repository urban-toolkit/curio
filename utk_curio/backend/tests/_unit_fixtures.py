"""Shared pytest fixtures for the backend *unit* test suites.

Several test packages (``test_datasets``, ``test_projects``, ``test_packages``,
``test_users``) each spin up an isolated in-memory Flask app with the same
``TestConfig``, ``client``/``db`` accessors, and an ``alice`` user. They used to
copy these verbatim. Define them once here; each package's ``conftest.py``
imports the pieces it needs (and keeps only its genuine specializations — e.g.
``test_datasets`` wires ``CURIO_SHARED_DATA`` + releases the DuckDB connection,
``test_packages`` stubs pip).

Import fixtures into a ``conftest.py`` to register them, e.g.::

    from utk_curio.backend.tests._unit_fixtures import (  # noqa: F401
        TestConfig, tmp_curio, app, client, db, user_and_token,
    )

``client``/``db``/``user_and_token`` resolve the ``app`` fixture *by name*, so a
package that defines its own ``app`` (different workspace wiring) still works
with the shared accessors.
"""
from __future__ import annotations

import pytest

from utk_curio.backend.app import create_app
from utk_curio.backend.extensions import db as _db


class TestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = "test-secret"
    WTF_CSRF_ENABLED = False


@pytest.fixture()
def tmp_curio(tmp_path, monkeypatch):
    """Isolated workspace: a fresh ``.curio/data`` dir + ``CURIO_LAUNCH_CWD``.

    Uses ``monkeypatch`` so the session-level ``CURIO_LAUNCH_CWD`` (set in the
    root conftest) is *restored* on teardown rather than deleted — a bare
    ``os.environ.pop`` here would clobber it for every later test that reads it.
    """
    data_dir = tmp_path / ".curio" / "data"
    data_dir.mkdir(parents=True)
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))
    yield tmp_path


@pytest.fixture()
def app(tmp_curio):
    """Function-scoped app on a fresh in-memory DB + isolated ``tmp_curio``."""
    application = create_app(TestConfig)
    with application.app_context():
        _db.create_all()
        yield application
        _db.session.remove()
        _db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def db(app):
    return _db


@pytest.fixture()
def user_and_token(app, db):
    """Create a regular test user and return ``(user, token)``."""
    from utk_curio.backend.app.users.models import User, UserSession

    u = User(username="alice", name="Alice", email="alice@test.com")
    db.session.add(u)
    db.session.flush()
    s = UserSession(user_id=u.id, token="alice-token-123")
    db.session.add(s)
    db.session.commit()
    return u, "alice-token-123"


@pytest.fixture()
def guest_user_and_token(app, db):
    """Create a guest user and return ``(user, token)``."""
    from utk_curio.backend.app.users.models import User, UserSession

    u = User(username="guest_abc", name="Guest", is_guest=True)
    db.session.add(u)
    db.session.flush()
    s = UserSession(user_id=u.id, token="guest-token-456")
    db.session.add(s)
    db.session.commit()
    return u, "guest-token-456"
