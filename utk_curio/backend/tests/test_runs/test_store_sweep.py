"""The six-hour sweep also empties the sandbox's store of what is past its days.

Every run's output is kept ``kept.KEPT_DAYS`` in the shared data directory,
saved or not, then goes (``kept.sweep_store``, the sandbox's
``/artifacts/sweep``). A saved output is the Data Catalog's file, which keeps
it. The sandbox's half is pinned in ``sandbox/tests/test_store_sweep.py``.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from utk_curio.backend.app.runs import kept


class _Answer:
    def __init__(self, body):
        self._body = body

    def json(self):
        return self._body


def test_the_store_is_asked_to_forget_what_it_made_before_the_kept_days(app, monkeypatch):
    sent = []

    def sandbox_request(method, path, **kwargs):
        sent.append((method, path, json.loads(kwargs["data"])))
        return _Answer({"forgotten": 4})

    monkeypatch.setattr(kept, "sandbox_request", sandbox_request)

    forgotten = kept.sweep_store(now=datetime(2026, 10, 25, 12, 0))

    week_before = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)
    assert sent == [("post", "/artifacts/sweep", {"madeBefore": int(week_before.timestamp() * 1000)})]
    assert kept.KEPT_DAYS == 7
    assert forgotten == 4


def test_the_six_hour_sweep_sweeps_the_store_after_the_kept_outputs(app, monkeypatch):
    done = []
    timers = []

    class Timer:
        def __init__(self, seconds, function):
            timers.append((seconds, function))
            self.daemon = False

        def start(self):
            pass

    monkeypatch.setattr(kept, "prune_quietly", lambda: done.append("kept outputs"))
    monkeypatch.setattr(kept, "sweep_store_quietly", lambda: done.append("store"))
    monkeypatch.setattr("utk_curio.backend.config._is_testing", lambda: False)
    monkeypatch.setattr(kept, "_prune_timer", None)
    monkeypatch.setattr(kept.threading, "Timer", Timer)

    kept.start_prune_scheduler(app)
    first_after, sweep = timers[0]
    sweep()

    assert first_after == 60
    assert done == ["kept outputs", "store"]
    assert timers[1][0] == kept.PRUNE_INTERVAL_HOURS * 3600


def test_a_sweep_the_sandbox_cannot_take_is_logged_and_left_to_the_next(app, monkeypatch, caplog):
    def unreachable(*_args, **_kwargs):
        raise ConnectionError("the sandbox is down")

    monkeypatch.setattr(kept, "sandbox_request", unreachable)

    with caplog.at_level("ERROR", logger=kept.log.name):
        kept.sweep_store_quietly()

    assert "could not sweep the store's artifacts" in caplog.text
