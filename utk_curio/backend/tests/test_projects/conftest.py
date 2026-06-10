"""Shared fixtures for project tests."""
import os
import pytest
import tempfile

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
    data_dir = tmp_path / ".curio" / "data"
    data_dir.mkdir(parents=True)
    # Use monkeypatch so the session-level CURIO_LAUNCH_CWD (set in the root
    # conftest) is *restored* on teardown rather than deleted — a bare
    # ``os.environ.pop`` here clobbers it for every later test that reads it
    # (e.g. test_routes::test_file_route_serves_relative_to_launch_cwd).
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))
    yield tmp_path


@pytest.fixture()
def app(tmp_curio):
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
    """Create a regular user and return (user, token)."""
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
    """Create a guest user and return (user, token)."""
    from utk_curio.backend.app.users.models import User, UserSession
    u = User(username="guest_abc", name="Guest", is_guest=True)
    db.session.add(u)
    db.session.flush()
    s = UserSession(user_id=u.id, token="guest-token-456")
    db.session.add(s)
    db.session.commit()
    return u, "guest-token-456"
