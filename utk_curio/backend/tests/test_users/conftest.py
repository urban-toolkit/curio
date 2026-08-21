"""Shared fixtures for auth tests.

Reuses the common ``TestConfig``/``client``/``db`` fixtures from
``utk_curio.backend.tests._unit_fixtures``. Auth tests run on a bare in-memory
DB with no temp workspace, so ``app`` is defined locally here.
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
