"""The fixed date that catalog captures run on.

The catalogs show how long ago each item was made ("2d ago", "Updated 141d
ago"), measured against the browser's clock. Shipped items carry fixed dates,
so on the real clock those ages grow by a day every day, and so does every
frame that shows one. A test marked ``catalog_calendar`` (conftest.py) runs
its browser on :data:`CATALOG_CALENDAR` through Playwright's clock, and the
backend stamps the records the test makes on the same date
(``/api/testing/clock``), so they still read "1m ago". Both clocks run on from
that date at the real pace.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from urllib.request import Request, urlopen

#: Two days after the newest shipped catalog item (SCOUT's, dated 2026-10-05),
#: so every shipped age reads in days, and at 06:00 UTC, six hours or more from
#: the hour at which a shipped age rounds up to the next day.
#: ``test_catalog_calendar_e2e.py`` fails when an item dated later ships: move
#: this date past it, then re-mint the frames of the tests marked
#: ``catalog_calendar``.
CATALOG_CALENDAR = datetime(2026, 10, 7, 6, 0, tzinfo=timezone.utc)


def _set_record_clock(backend_url: str, method: str, body: dict | None = None) -> dict:
    request = Request(
        f"{backend_url}/api/testing/clock",
        data=json.dumps(body or {}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method=method,
    )
    with urlopen(request, timeout=10) as response:  # noqa: S310 - the test's own backend
        return json.loads(response.read().decode("utf-8"))


def start_catalog_calendar(context, backend_url: str) -> None:
    """Run *context*'s pages, and the backend's record clock, on the calendar.

    The page clock is set first, so the backend's never runs ahead of it: what
    the test makes is never newer than the page's "now".
    """
    context.clock.set_system_time(CATALOG_CALENDAR)
    _set_record_clock(backend_url, "POST", {"now": CATALOG_CALENDAR.isoformat()})


def stop_catalog_calendar(backend_url: str) -> None:
    """Put the backend's record clock back on the system clock."""
    _set_record_clock(backend_url, "DELETE")
