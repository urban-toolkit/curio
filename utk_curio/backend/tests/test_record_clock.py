"""The clock catalog records are stamped with, and the test-only route that sets it.

``common/record_clock.py`` is the system clock until an e2e test that
photographs catalog ages sets it, through ``/api/testing/clock``, to the date
its browser runs on. These pin both halves: what the clock reads once set, and
that the route sets it, refuses a time it cannot place, and gives the system
clock back, as ``reset-db`` does between tests.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from utk_curio.backend.app import create_app
from utk_curio.backend.extensions import db as _db
from utk_curio.backend.tests._unit_fixtures import TestConfig

CALENDAR = datetime(2026, 10, 7, 6, 0, tzinfo=timezone.utc)
SOON = timedelta(seconds=5)


@pytest.fixture()
def record_clock():
    from utk_curio.backend.app.common import record_clock as clock  # main has no record clock

    yield clock
    clock.set_now(None)


@pytest.fixture()
def client():
    application = create_app(TestConfig)
    with application.app_context():
        _db.create_all()
        yield application.test_client()
        _db.session.remove()
        _db.drop_all()


def _read(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00"))


def _on_the_system_clock(clock) -> bool:
    return abs(clock.utc_now() - datetime.now(timezone.utc)) < SOON


class TestTheRecordClock:
    def test_it_is_the_system_clock_until_set(self, record_clock):
        assert _on_the_system_clock(record_clock)

    def test_once_set_it_runs_on_from_that_moment(self, record_clock):
        record_clock.set_now(CALENDAR)
        first = record_clock.utc_now()
        assert CALENDAR <= first < CALENDAR + SOON
        assert record_clock.utc_now() >= first
        record_clock.set_now(None)
        assert _on_the_system_clock(record_clock)

    def test_catalog_stamps_read_it(self, record_clock):
        from utk_curio.backend.app.datasets.infrastructure.catalog_utils import iso_from_timestamp

        record_clock.set_now(CALENDAR)
        assert CALENDAR <= _read(iso_from_timestamp()) < CALENDAR + SOON
        # A time the caller gives (a file's, a source's) stays that time.
        assert iso_from_timestamp(0) == "1970-01-01T00:00:00Z"


class TestTheTestingRoute:
    def test_it_sets_the_clock_to_the_given_time(self, client, record_clock):
        resp = client.post(
            "/api/testing/clock",
            data=json.dumps({"now": "2026-10-07T06:00:00Z"}),
            content_type="application/json",
        )
        assert resp.status_code == 200, resp.get_data(as_text=True)
        assert CALENDAR <= _read(resp.get_json()["now"]) < CALENDAR + SOON
        assert CALENDAR <= record_clock.utc_now() < CALENDAR + SOON

    @pytest.mark.parametrize("give_back", ["delete", "reset-db"])
    def test_delete_and_reset_db_give_the_system_clock_back(self, client, record_clock, give_back):
        record_clock.set_now(CALENDAR)
        if give_back == "delete":
            resp = client.delete("/api/testing/clock")
        else:
            resp = client.post(
                "/api/testing/reset-db", data=json.dumps({}), content_type="application/json"
            )
        assert resp.status_code == 200, resp.get_data(as_text=True)
        assert _on_the_system_clock(record_clock)

    @pytest.mark.parametrize("body", [{}, {"now": "yesterday"}, {"now": "2026-10-07T06:00:00"}])
    def test_a_time_it_cannot_place_is_refused(self, client, record_clock, body):
        resp = client.post(
            "/api/testing/clock", data=json.dumps(body), content_type="application/json"
        )
        assert resp.status_code == 400
        assert _on_the_system_clock(record_clock)
