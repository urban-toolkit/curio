"""Datasets made in Curio are dated by the record clock (``common/record_clock.py``).

An e2e test that photographs dataset ages runs its browser on a fixed date and
sets the record clock to it (``/api/testing/clock``). A dataset the test
imports or computes must then carry that date, or the catalog would show it
as made after the page's own "now", beside the shipped datasets.
"""
from __future__ import annotations

import io
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from utk_curio.backend.tests.test_datasets.computed_test_helpers import (
    auth_headers,
    create_project,
    save_project_with_output,
)

CALENDAR = datetime(2026, 10, 7, 6, 0, tzinfo=timezone.utc)


@pytest.fixture()
def on_the_calendar():
    from utk_curio.backend.app.common import record_clock  # main has no record clock

    record_clock.set_now(CALENDAR)
    yield
    record_clock.set_now(None)


def _dated_on_the_calendar(stamp: str) -> bool:
    when = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    return CALENDAR <= when < CALENDAR + timedelta(minutes=1)


def test_an_import_is_dated_by_the_record_clock(
    client, user_and_token, tmp_path, monkeypatch, on_the_calendar
):
    _, token = user_and_token
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))
    resp = client.post(
        "/api/datasets/import",
        headers={"Authorization": f"Bearer {token}"},
        data={"file": (io.BytesIO(b"a,b\n1,2\n"), "cities.csv")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 201, resp.get_data(as_text=True)
    item = resp.get_json()
    assert _dated_on_the_calendar(item["createdAt"]), item["createdAt"]
    assert _dated_on_the_calendar(item["updatedAt"]), item["updatedAt"]


def test_a_saved_output_is_dated_by_the_record_clock(client, user_and_token, on_the_calendar):
    _, token = user_and_token
    project_id = create_project(client, token)
    shared = Path(os.environ["CURIO_SHARED_DATA"])
    (shared / "dated_output.csv").write_text("x,y\n1,2\n", encoding="utf-8")
    save_project_with_output(client, token, project_id, "dated_output.csv", node_id="node-dated")

    listing = client.get(
        f"/api/datasets/catalog?includeHub=false&dataflowId={project_id}",
        headers=auth_headers(token),
    ).get_json()
    computed = [item for item in listing["items"] if item["origin"] == "computed"]
    assert len(computed) == 1, listing["items"]
    assert _dated_on_the_calendar(computed[0]["updatedAt"]), computed[0]["updatedAt"]
