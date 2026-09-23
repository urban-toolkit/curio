"""The monitor must survive the thing it monitors being down.

A page that 502s because the sandbox is unreachable is useless at exactly the
moment someone opens it. These tests drive the shapes `_sandbox_call` actually
produces on failure, which is easy to get wrong: on a transport error it
returns a Flask `(response, status)` TUPLE, not a `requests.Response`, so a
handler that assumes the latter raises AttributeError and turns a degraded
sandbox into a 500.

They use the `real_sandbox_monitor` fixture, which undoes the suite's default
stub. Without it these would pass vacuously against the stub and prove nothing.
"""

import pytest
from flask import jsonify


class _FakeResponse:
    def __init__(self, status_code, payload=None, raises=False):
        self.status_code = status_code
        self._payload = payload
        self._raises = raises

    def json(self):
        if self._raises:
            raise ValueError("not JSON")
        return self._payload


FAILURES = {
    # What _sandbox_call returns when the sandbox refuses the connection or
    # times out. The tuple is the shape a naive handler gets wrong.
    "transport_error_tuple": lambda: (jsonify({"error": "unreachable"}), 502),
    "non_200": lambda: _FakeResponse(500, {}),
    "non_json_body": lambda: _FakeResponse(200, raises=True),
    "empty_json": lambda: _FakeResponse(200, None),
}


@pytest.fixture()
def failing_sandbox(real_sandbox_monitor, monkeypatch):
    def install(shape):
        import utk_curio.backend.app.api.routes as api_routes
        monkeypatch.setattr(api_routes, "_sandbox_call",
                            lambda *a, **k: FAILURES[shape]())
    return install


@pytest.mark.parametrize("shape", sorted(FAILURES))
def test_every_failure_shape_degrades_to_200(client, failing_sandbox, shape):
    failing_sandbox(shape)

    response = client.get("/api/monitor")
    assert response.status_code == 200, "a down sandbox must not 502 the monitor"
    sandbox = response.get_json()["execution"]["sandbox"]
    assert sandbox["reachable"] is False
    assert sandbox["childDeaths"] is None
    assert sandbox["parallelism"] is None


@pytest.mark.parametrize("shape", sorted(FAILURES))
def test_the_errors_route_degrades_the_same_way(client, failing_sandbox, shape):
    failing_sandbox(shape)

    response = client.get("/api/monitor/errors")
    assert response.status_code == 200
    assert response.get_json()["sandboxWindow"] is None


def test_local_errors_survive_a_down_sandbox(client, failing_sandbox):
    from utk_curio.backend.app.monitor import errors

    failing_sandbox("transport_error_tuple")
    errors.record("node", summary="a real node failure", detail="traceback")

    body = client.get("/api/monitor/errors").get_json()
    assert [e["summary"] for e in body["errors"]] == ["a real node failure"]


def test_a_down_sandbox_is_not_logged_as_a_fault(client, failing_sandbox):
    """A restart is an ordinary event, not something to fill the log with.

    This is what the isinstance-tuple branch buys. Without it the tuple raises
    AttributeError into the catch-all, which still degrades, but logs every
    poll against a stopped sandbox as a backend fault.
    """
    failing_sandbox("transport_error_tuple")
    client.get("/api/monitor")
    assert client.get("/api/monitor/errors").get_json()["errors"] == []


def test_an_unexpected_proxy_failure_is_logged_rather_than_swallowed(
    client, real_sandbox_monitor, monkeypatch,
):
    """The other half: a genuine bug here must not vanish silently."""
    import utk_curio.backend.app.api.routes as api_routes

    def explode(*a, **k):
        raise RuntimeError("something genuinely unexpected")

    monkeypatch.setattr(api_routes, "_sandbox_call", explode)

    response = client.get("/api/monitor")
    assert response.status_code == 200
    assert response.get_json()["execution"]["sandbox"]["reachable"] is False

    entries = client.get("/api/monitor/errors").get_json()["errors"]
    assert any("could not read the sandbox" in e["summary"] for e in entries)


def test_a_reachable_sandbox_is_read_through_the_real_proxy(client,
                                                            real_sandbox_monitor,
                                                            monkeypatch):
    """The positive control: the proxy does return data when the call works."""
    import utk_curio.backend.app.api.routes as api_routes

    monkeypatch.setattr(api_routes, "_sandbox_call",
                        lambda *a, **k: _FakeResponse(200, {
                            "isolation": "fork", "isolation_active": "fork",
                            "parallelism": 4, "childDeaths": {"oom": 1},
                        }))
    sandbox = client.get("/api/monitor").get_json()["execution"]["sandbox"]
    assert sandbox["reachable"] is True
    assert sandbox["parallelism"] == 4
    assert sandbox["childDeaths"] == {"oom": 1}
