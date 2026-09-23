"""Fixtures for the monitor suite.

Reuses the shared unit fixtures. The sandbox is stubbed by default: these tests
are about this process's payload, and a real sandbox round trip would make them
slow and dependent on a second process being up.
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
def app():
    application = create_app(TestConfig)
    with application.app_context():
        _db.create_all()
        yield application
        _db.session.remove()
        _db.drop_all()


@pytest.fixture(autouse=True)
def clean_monitor_state():
    """Counters and error windows are module globals, so they leak across tests."""
    from utk_curio.backend.app.monitor import counters, errors, routes

    counters.reset()
    errors.reset()
    routes.reset_rate_limit()
    yield
    counters.reset()
    errors.reset()
    routes.reset_rate_limit()


# Captured at import, before any test has had a chance to stub it, so
# `real_sandbox_monitor` can hand back the genuine proxy rather than whatever
# the autouse stub last installed.
from utk_curio.backend.app.monitor import routes as _monitor_routes  # noqa: E402

_REAL_SANDBOX_MONITOR = _monitor_routes._sandbox_monitor


@pytest.fixture(autouse=True)
def stub_sandbox(monkeypatch):
    """Default: an unreachable sandbox, which every route must tolerate."""
    monkeypatch.setattr(_monitor_routes, "_sandbox_monitor", lambda: None)


@pytest.fixture()
def real_sandbox_monitor(stub_sandbox, monkeypatch):
    """Undo the stub so the proxy's own error handling is what runs.

    Depends on `stub_sandbox` so it is applied after it, not before.
    """
    monkeypatch.setattr(_monitor_routes, "_sandbox_monitor", _REAL_SANDBOX_MONITOR)
