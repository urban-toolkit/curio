"""A refusal must not arrive as a crash.

``create_app`` registers one ``@app.errorhandler(Exception)``. Flask's handler
lookup walks the exception MRO, so werkzeug's own ``NotFound``,
``MethodNotAllowed`` and ``Forbidden`` land in it too - and it overwrites
``status_code`` with 500 unconditionally, discarding the code the exception
carried. Every routing error and every ``abort()`` in the app therefore reached
the client as a server fault (#279).

The path-traversal guard on ``/file/<path>`` is the sharpest case: an attempt to
escape ``CURIO_LAUNCH_CWD`` was reported as "the server broke" rather than "no".

These tests pin the four codes that matter, that a genuine unhandled exception
is still a 500, and that CORS headers survive the trip - without them a
cross-origin 404 reads to the browser as an opaque network error, which is how
this behaviour hid for so long.
"""

from __future__ import annotations

import pytest

from utk_curio.backend.app import create_app
from utk_curio.backend.extensions import db as _db
from utk_curio.backend.tests._unit_fixtures import TestConfig


@pytest.fixture()
def app():
    application = create_app(TestConfig)
    with application.app_context():
        _db.create_all()
        yield application
        _db.session.remove()
        _db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


class TestRoutingErrorsKeepTheirCode:
    def test_an_unknown_route_is_a_404(self, client):
        assert client.get("/no-such-route-anywhere").status_code == 404

    def test_the_wrong_verb_is_a_405(self, client):
        # /live is GET-only (api/routes.py). werkzeug raises MethodNotAllowed.
        assert client.post("/live").status_code == 405

    def test_the_route_is_reachable_with_the_right_verb(self, client):
        # Guards the test above: a 405 must mean "wrong verb", not "no route".
        assert client.get("/live").status_code == 200


class TestAbortKeepsItsCode:
    def test_the_root_route_refuses_with_403(self, client):
        assert client.get("/").status_code == 403

    def test_a_path_traversal_attempt_is_refused_not_crashed(self, client):
        # The guard calls abort(403). Reported as 500, an attack looked like a
        # bug in Curio; reported as 403 it is a refusal the logs can count.
        assert client.get("/file/../../etc/passwd").status_code == 403


class TestGenuineFaultsAreStill500:
    def test_an_unhandled_exception_is_a_500(self, app):
        # TESTING=True turns on PROPAGATE_EXCEPTIONS, which re-raises non-HTTP
        # exceptions before the handler sees them. Turn it off so this exercises
        # the same path a real deployment takes.
        app.config["PROPAGATE_EXCEPTIONS"] = False

        @app.route("/boom-for-the-test")
        def _boom():
            raise RuntimeError("boom")

        resp = app.test_client().get("/boom-for-the-test")
        assert resp.status_code == 500
        assert resp.get_json()["error"]


class TestTheBodyAndHeadersSurvive:
    def test_a_404_still_carries_cors_headers(self, client):
        resp = client.get("/no-such-route-anywhere")
        assert resp.headers.get("Access-Control-Allow-Origin") is not None

    def test_a_refusal_carries_a_json_error_body(self, client):
        resp = client.get("/")
        assert resp.status_code == 403
        assert resp.get_json()["error"]
