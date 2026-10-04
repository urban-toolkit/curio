"""Fixtures for the Scenario Catalog tests.

The common ``client``/``db``/``user_and_token`` fixtures, on the dataset
tests' ``app``, which wires ``CURIO_SHARED_DATA`` so a project save can record
its outputs in the Data Catalog.
"""
from __future__ import annotations

import pytest

from utk_curio.backend.tests._unit_fixtures import (  # noqa: F401
    client,
    db,
    user_and_token,
)
from utk_curio.backend.tests.test_datasets.conftest import app  # noqa: F401


@pytest.fixture()
def other_user_and_token(app, db):  # noqa: F811
    """A second account, ``(user, token)``."""
    from utk_curio.backend.app.users.models import User, UserSession

    u = User(username="bob", name="Bob", email="bob@test.com")
    db.session.add(u)
    db.session.flush()
    db.session.add(UserSession(user_id=u.id, token="bob-token-789"))
    db.session.commit()
    return u, "bob-token-789"
