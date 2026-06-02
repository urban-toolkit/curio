"""Shared fixtures for the dataset catalog tests."""
from __future__ import annotations

import os
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
def app(tmp_path):
    # Wire a fresh temp workspace so every test gets its own isolated
    # file-system sandbox (shared data dir, user store, etc.).
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

    # Restore env vars so parallel/sequential tests don't interfere.
    if prev_cwd is not None:
        os.environ["CURIO_LAUNCH_CWD"] = prev_cwd
    else:
        os.environ.pop("CURIO_LAUNCH_CWD", None)
    if prev_shared is not None:
        os.environ["CURIO_SHARED_DATA"] = prev_shared
    else:
        os.environ.pop("CURIO_SHARED_DATA", None)


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

