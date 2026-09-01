"""The test-only blueprint needs two factors, not one.

``/api/testing/stub-login`` hands out a valid session for any username with no
password. That is fine for a test rig and catastrophic anywhere else, so what
gates it matters more than for any other route in Curio.

It used to be gated on ``_is_dev()`` alone. ``CURIO_ENV`` defaults to ``"dev"``
(``backend/config.py``), so an operator who never set it had the routes mounted
on a real deployment. The second factor, ``CURIO_TESTING``, is the deliberate
"this process is a test rig" signal that no ordinary ``curio.py start`` sets.

These tests also pin the two capabilities that were removed from the stubs:
``stub-login`` no longer rewrites an existing account's password hash, and
``reset-db`` no longer truncates whatever table the request body names.
"""

from __future__ import annotations

import json

import pytest

from utk_curio.backend.app import create_app
from utk_curio.backend.app.testing import routes as testing_routes
from utk_curio.backend.extensions import db as _db
from utk_curio.backend.tests._unit_fixtures import TestConfig


@pytest.fixture()
def app(monkeypatch):
    application = create_app(TestConfig)
    with application.app_context():
        _db.create_all()
        yield application
        _db.session.remove()
        _db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


def _post(client, path, data=None):
    return client.post(
        path, data=json.dumps(data or {}), content_type="application/json"
    )


class TestTheGateNeedsBothFactors:
    def test_available_in_a_test_run(self, client):
        resp = _post(client, "/api/testing/stub-login", {"username": "alice"})
        assert resp.status_code == 200

    def test_refused_when_curio_testing_is_unset(self, client, monkeypatch):
        # The real-world shape of the hole: a deployment left on the default
        # CURIO_ENV, with nothing declaring itself a test run.
        monkeypatch.setattr(testing_routes, "_is_testing", lambda: False)
        resp = _post(client, "/api/testing/stub-login", {"username": "alice"})
        assert resp.status_code == 404

    def test_refused_in_production(self, client, monkeypatch):
        monkeypatch.setattr(testing_routes, "_is_dev", lambda: False)
        resp = _post(client, "/api/testing/stub-login", {"username": "alice"})
        assert resp.status_code == 404

    @pytest.mark.parametrize(
        "path", ["/api/testing/stub-login", "/api/testing/reset-db", "/api/testing/stub-project"]
    )
    def test_every_stub_route_is_gated(self, client, monkeypatch, path):
        monkeypatch.setattr(testing_routes, "_is_testing", lambda: False)
        assert _post(client, path, {"username": "alice"}).status_code == 404


class TestStubLoginDoesNotRewriteCredentials:
    def test_an_existing_account_keeps_its_password(self, client):
        signup = _post(
            client,
            "/api/auth/signup",
            {"name": "Alice", "username": "alice", "password": "original-password"},
        )
        assert signup.status_code == 201

        # The takeover attempt: same username, attacker-chosen password.
        stub = _post(
            client,
            "/api/testing/stub-login",
            {"username": "alice", "password": "attacker-password"},
        )
        assert stub.status_code == 200
        assert stub.get_json()["created"] is False

        # The original credential still works and the injected one does not.
        assert (
            _post(
                client,
                "/api/auth/signin",
                {"identifier": "alice", "password": "original-password"},
            ).status_code
            == 200
        )
        assert (
            _post(
                client,
                "/api/auth/signin",
                {"identifier": "alice", "password": "attacker-password"},
            ).status_code
            != 200
        )

    def test_a_password_still_seeds_a_new_account(self, client):
        """Creating with a password is the legitimate use, and still works."""
        stub = _post(
            client,
            "/api/testing/stub-login",
            {"username": "bob", "name": "Bob", "password": "seeded-password"},
        )
        assert stub.status_code == 200
        assert stub.get_json()["created"] is True
        assert (
            _post(
                client,
                "/api/auth/signin",
                {"identifier": "bob", "password": "seeded-password"},
            ).status_code
            == 200
        )


class TestResetDbOnlyTouchesKnownTables:
    def test_defaults_to_the_mutable_set(self, client):
        resp = _post(client, "/api/testing/reset-db")
        assert resp.status_code == 200
        assert set(resp.get_json()["truncated"]) == set(testing_routes._RESETTABLE_TABLES)

    def test_a_subset_is_honoured(self, client):
        resp = _post(client, "/api/testing/reset-db", {"tables": ["project"]})
        assert resp.status_code == 200
        assert resp.get_json()["truncated"] == ["project"]

    def test_an_unlisted_table_is_refused_rather_than_executed(self, client):
        resp = _post(client, "/api/testing/reset-db", {"tables": ["alembic_version"]})
        assert resp.status_code == 400
        assert "not resettable" in resp.get_json()["error"]

    def test_tables_must_be_a_list(self, client):
        resp = _post(client, "/api/testing/reset-db", {"tables": "project"})
        assert resp.status_code == 400
