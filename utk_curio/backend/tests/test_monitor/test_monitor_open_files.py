"""Each server's open files over time (``monitor/open_files.py``).

The backend samples its own open files and limit and the sandbox's, from the
sandbox's ``/monitor`` reply, every hour from its start, keeps the samples in
the monitor history ``open-files`` (``history.py``) and publishes them on
``GET /api/monitor/open-files``. A sample above 80% of a server's limit records
an error in the monitor's errors list, once until that server's count falls
below 70%.

The counts are the test's own: the backend's through ``common/open_files.py``'s
``in_use``, the sandbox's through the monitor's call of its ``/monitor``. The
clock is the test's too, and each test's history file is in a folder of its own
(``conftest.py``). The module is imported in a fixture, so a tree without it
fails each test here and runs the rest of its unit part.
"""

from __future__ import annotations

import json
import logging
import types
from datetime import datetime, timedelta, timezone

import pytest

from utk_curio.backend.app.monitor import errors
from utk_curio.backend.app.monitor import history as monitor_history

NOW = datetime(2026, 11, 6, 15, 20, 7, tzinfo=timezone.utc)


def _stamp(at: datetime) -> str:
    return at.strftime("%Y-%m-%dT%H:%M:%SZ")


def _hour(at: datetime) -> str:
    return at.strftime("%Y-%m-%dT%H:00:00Z")


@pytest.fixture()
def sampler(monkeypatch, stub_sandbox):
    """The sampler, started over, on the test's clock (``state.at``) and its
    counts: the backend's ``(open, limit)`` (``state.backend``) and the
    sandbox's ``/monitor`` reply (``state.sandbox``, None when it does not
    answer)."""
    from utk_curio.backend.app.monitor import open_files
    from utk_curio.backend.app.monitor import routes
    from utk_curio.common import open_files as common_open_files

    state = types.SimpleNamespace(
        at=NOW,
        backend=(212, 65536),
        sandbox={"rss_bytes": 1, "open_files": 96, "open_files_limit": 65536},
    )
    monkeypatch.setattr(open_files, "_now", lambda: state.at)
    monkeypatch.setattr(common_open_files, "in_use", lambda: state.backend)
    monkeypatch.setattr(routes, "_sandbox_monitor", lambda: state.sandbox)
    open_files.reset()
    yield types.SimpleNamespace(module=open_files, state=state)
    open_files.reset()


def _warnings() -> list[tuple]:
    """The errors list's entries, newest first: source, summary and count."""
    return [(entry["source"], entry["summary"], entry["count"]) for entry in errors.snapshot()["errors"]]


class TestTheSample:
    def test_the_sampler_samples_as_it_starts_then_every_hour(self, app, sampler, monkeypatch):
        from utk_curio.backend import config

        module = sampler.module
        timers = []

        class Timer:
            """A timer that waits for the test to fire it."""

            def __init__(self, interval, function, args=()):
                self.interval, self.function, self.args, self.daemon = interval, function, args, False

            def start(self):
                timers.append(self)

            def fire(self):
                self.function(*self.args)

        monkeypatch.setattr(module.threading, "Timer", Timer)
        monkeypatch.setattr(config, "_is_testing", lambda: False)
        monkeypatch.setattr(module, "_timer", None)

        module.start_sampler(app)
        module.start_sampler(app)  # a process samples on one timer
        assert [(timer.interval, timer.daemon) for timer in timers] == [(0, True)]

        timers[0].fire()
        sampler.state.at = NOW + timedelta(hours=1)
        sampler.state.backend = (230, 65536)
        sampler.state.sandbox = {"open_files": 101, "open_files_limit": 65536}
        timers[1].fire()

        assert [timer.interval for timer in timers] == [0, 3600, 3600]
        assert all(timer.daemon for timer in timers)
        assert module.HISTORY.rows() == [
            {"hour": _hour(NOW), "at": _stamp(NOW),
             "backend": {"open": 212, "limit": 65536}, "sandbox": {"open": 96, "limit": 65536}},
            {"hour": _hour(NOW + timedelta(hours=1)), "at": _stamp(NOW + timedelta(hours=1)),
             "backend": {"open": 230, "limit": 65536}, "sandbox": {"open": 101, "limit": 65536}},
        ]

    def test_the_first_sample_waits_for_the_sandbox_and_the_hourly_ones_do_not(self, sampler, monkeypatch):
        from utk_curio.backend.app.monitor import routes

        module = sampler.module
        answers = [None, None, {"open_files": 96, "open_files_limit": 65536}]
        asked, slept = [], []

        def sandbox():
            asked.append(len(asked))
            return answers[min(len(asked), len(answers)) - 1]

        monkeypatch.setattr(routes, "_sandbox_monitor", sandbox)
        monkeypatch.setattr(module, "_sleep", slept.append)

        row = module.sample(wait_for_sandbox=module.FIRST_SAMPLE_WAIT_SECONDS)
        assert row["sandbox"] == {"open": 96, "limit": 65536}
        assert (len(asked), slept) == (3, [5, 5])

        # A sandbox that never answers is asked for the whole minute, then left out.
        answers[:] = [None]
        asked.clear()
        slept.clear()
        row = module.sample(wait_for_sandbox=module.FIRST_SAMPLE_WAIT_SECONDS)
        assert row["sandbox"] is None
        assert row["backend"] == {"open": 212, "limit": 65536}
        assert (len(asked), sum(slept)) == (13, 60)

        # An hourly sample asks once.
        asked.clear()
        slept.clear()
        assert module.sample()["sandbox"] is None
        assert (len(asked), slept) == (1, [])

    def test_a_backend_start_writes_the_samples_anew(self, sampler):
        from utk_curio.backend.app import create_app
        from utk_curio.backend.tests._unit_fixtures import TestConfig

        module = sampler.module
        module.sample()
        path = module.HISTORY.path()
        assert path == monitor_history._folder() / "open-files.json"
        assert [row["at"] for row in json.loads(path.read_text(encoding="utf-8"))["rows"]] == [_stamp(NOW)]
        # What an earlier process left in the file.
        path.write_text(json.dumps({"name": "open-files", "rows": [
            {"hour": "2026-11-01T10:00:00Z", "at": "2026-11-01T10:12:00Z",
             "backend": {"open": 1000, "limit": 1024}, "sandbox": None},
        ]}), encoding="utf-8")

        create_app(TestConfig)

        doc = json.loads(path.read_text(encoding="utf-8"))
        assert (doc["name"], doc["rows"]) == ("open-files", [])
        assert module.HISTORY.rows() == []
        assert module.snapshot()["samples"] == []

    def test_a_sample_older_than_90_days_goes(self, sampler):
        """Counted back from the newest sample's hour: 90 days hold it and the
        2,159 hours before it, so a sample 2,160 hours older is gone."""
        module = sampler.module
        for hours in (90 * 24, 90 * 24 - 1, 0):
            sampler.state.at = NOW - timedelta(hours=hours)
            module.sample()

        kept = [_stamp(NOW - timedelta(hours=90 * 24 - 1)), _stamp(NOW)]
        assert [row["at"] for row in module.HISTORY.rows()] == kept
        doc = json.loads(module.HISTORY.path().read_text(encoding="utf-8"))
        assert [row["at"] for row in doc["rows"]] == kept

    def test_a_write_that_fails_is_logged_and_tried_again_the_next_hour(self, sampler, tmp_path, monkeypatch,
                                                                        caplog):
        module = sampler.module
        folder = monitor_history._folder()
        blocked = tmp_path / "a-file"
        blocked.write_text("not a folder", encoding="utf-8")
        monkeypatch.setattr(monitor_history, "_folder", lambda: blocked / "monitor")

        with caplog.at_level(logging.WARNING, logger=monitor_history.log.name):
            row = module.sample()
        logged = [record for record in caplog.records
                  if record.levelno >= logging.WARNING and "open-files" in record.getMessage()]
        assert logged, [record.getMessage() for record in caplog.records]
        # The sample is kept in the process all the same.
        assert [each["at"] for each in module.HISTORY.rows()] == [row["at"]]

        monkeypatch.setattr(monitor_history, "_folder", lambda: folder)
        sampler.state.at = NOW + timedelta(hours=1)
        module.sample()

        doc = json.loads((folder / "open-files.json").read_text(encoding="utf-8"))
        assert [each["at"] for each in doc["rows"]] == [_stamp(NOW), _stamp(NOW + timedelta(hours=1))]


class TestTheRoute:
    def test_the_route_returns_every_kept_sample(self, client, sampler):
        module = sampler.module
        module.sample()
        sampler.state.at = NOW + timedelta(hours=1)
        sampler.state.sandbox = None
        module.sample()
        sampler.state.at = NOW + timedelta(hours=2)
        # A platform that cannot count, and a sandbox from before the counts.
        sampler.state.backend = (None, None)
        sampler.state.sandbox = {"rss_bytes": 1}
        module.sample()

        response = client.get("/api/monitor/open-files")
        assert response.status_code == 200
        body = response.get_json()
        assert body["samples"] == [
            {"at": _stamp(NOW), "backend": {"open": 212, "limit": 65536},
             "sandbox": {"open": 96, "limit": 65536}},
            {"at": _stamp(NOW + timedelta(hours=1)), "backend": {"open": 212, "limit": 65536},
             "sandbox": None},
            {"at": _stamp(NOW + timedelta(hours=2)), "backend": {"open": None, "limit": None},
             "sandbox": {"open": None, "limit": None}},
        ]
        assert (body["maxDays"], body["intervalSeconds"], body["warnAbovePercent"],
                body["clearBelowPercent"]) == (90, 3600, 80, 70)
        assert body["computedAt"] == _stamp(NOW + timedelta(hours=2))
        datetime.strptime(body["startedAt"], "%Y-%m-%dT%H:%M:%SZ")

    def test_a_backend_with_no_sample_yet_returns_none(self, client, sampler):
        assert client.get("/api/monitor/open-files").get_json()["samples"] == []


class TestTheWarning:
    @staticmethod
    def _take(sampler, backend_open, sandbox_open=96, limit=1000):
        sampler.state.at += timedelta(hours=1)
        sampler.state.backend = (backend_open, limit)
        sampler.state.sandbox = {"open_files": sandbox_open, "open_files_limit": limit}
        return sampler.module.sample()

    def test_one_error_above_80_percent_and_another_only_after_a_fall_below_70(self, sampler):
        self._take(sampler, 800)  # 80%: not above it
        assert _warnings() == []

        row = self._take(sampler, 850)
        first = ("backend", "The backend has 850 open files, 85.0% of its limit of 1,000", 1)
        assert _warnings() == [first]
        detail = errors.snapshot()["errors"][0]["detail"]
        assert row["at"] in detail and "Too many open files" in detail

        self._take(sampler, 900)  # still above
        self._take(sampler, None)  # a sample with no count
        self._take(sampler, 750)  # between 70% and 80%: the warning stands
        self._take(sampler, 820)
        sampler.state.at += timedelta(hours=1)
        sampler.state.backend = (100, None)  # a limit unknown
        sampler.module.sample()
        self._take(sampler, 700)  # 70%: not below it
        self._take(sampler, 810)
        assert _warnings() == [first]

        self._take(sampler, 690)  # below 70%: the warning is cleared
        assert _warnings() == [first]
        self._take(sampler, 830)
        assert _warnings() == [
            ("backend", "The backend has 830 open files, 83.0% of its limit of 1,000", 1),
            first,
        ]

    def test_each_server_is_warned_of_on_its_own(self, sampler):
        self._take(sampler, 850, sandbox_open=100)
        self._take(sampler, 840, sandbox_open=950)
        self._take(sampler, 860, sandbox_open=960)
        both = [
            ("sandbox", "The sandbox has 950 open files, 95.0% of its limit of 1,000", 1),
            ("backend", "The backend has 850 open files, 85.0% of its limit of 1,000", 1),
        ]
        assert _warnings() == both

        # A sandbox that does not answer leaves its warning standing, and the
        # backend's fall below 70% clears the backend's alone.
        sampler.state.at += timedelta(hours=1)
        sampler.state.sandbox = None
        sampler.module.sample()
        self._take(sampler, 100, sandbox_open=970)
        self._take(sampler, 870, sandbox_open=980)
        assert _warnings() == [
            ("backend", "The backend has 870 open files, 87.0% of its limit of 1,000", 1),
            *both,
        ]
