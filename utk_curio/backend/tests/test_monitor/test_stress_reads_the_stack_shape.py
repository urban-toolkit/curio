"""The stress harness reads its stack's shape out of this payload.

``stress/run.py`` records execution parallelism in every report, because the
count is derived from the host and a tier measured against 8 slots is not the
same measurement as the same tier against 32. It gets the number from
``/api/monitor``, so the key path it walks belongs to this suite: a rename
inside the monitor payload would otherwise leave every future report saying
"unknown" and nothing would fail.
"""

from utk_curio.backend.tests.stress.run import read_stack_shape

SANDBOX_PAYLOAD = {
    "isolation": "fork",
    "isolation_active": True,
    "zygote_running": True,
    "parallelism": 32,
    "slotsInUse": 3,
    "memory_limit_mb": 4096,
    "wall_timeout_seconds": 300,
}


class _Response:
    """Enough of requests.Response for the harness's one call."""

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def _harness_reading(monkeypatch, client, path="/api/monitor"):
    """Run the harness's reader against this app's real monitor route."""
    from utk_curio.backend.tests.stress import run as stress_run

    def fake_get(url, timeout=None):
        return _Response(client.get(path).get_json())

    monkeypatch.setattr(stress_run.requests, "get", fake_get)
    return read_stack_shape("http://stack")


def test_the_harness_finds_the_numbers_it_records(monkeypatch, client):
    from utk_curio.backend.app.monitor import routes as monitor_routes

    monkeypatch.setattr(
        monitor_routes, "_sandbox_monitor", lambda: dict(SANDBOX_PAYLOAD)
    )
    assert _harness_reading(monkeypatch, client) == {
        "isolation": "fork",
        "exec_parallelism": 32,
        "exec_memory_mb": 4096,
        "exec_timeout_s": 300,
    }


def test_an_unreachable_sandbox_leaves_the_report_honest(monkeypatch, client):
    """No numbers beats invented ones: the report then says nothing."""
    # The suite's autouse stub already makes the sandbox unreachable.
    assert _harness_reading(monkeypatch, client) == {}
