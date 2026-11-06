"""The monitor's hourly histories (``monitor/history.py``).

A history covers the running process: its rows live in the process, each
change rewrites its file whole, the backend's start writes it anew over what an
earlier process left, and it holds at most its days of hours, the oldest going
first. The LLM tokens are one (``test_monitor_llm_tokens.py``). The histories
here are each test's own, in a registry that goes with the test, and their
files are in the test's own folder (``conftest.py``).
"""

import json
from datetime import datetime, timedelta, timezone

import pytest

from utk_curio.backend.app.monitor import history

#: The real folder, taken before any test points it at a folder of its own.
REAL_FOLDER = history._folder
H = datetime(2026, 11, 6, 15, tzinfo=timezone.utc)


def _hour(hours_before: int) -> str:
    return (H - timedelta(hours=hours_before)).strftime(history.HOUR)


def _adding(*rows):
    def change(held: list) -> None:
        held.extend(dict(row) for row in rows)
    return change


def _file(each: history.History) -> dict:
    return json.loads(each.path().read_text(encoding="utf-8"))


@pytest.fixture()
def histories(monkeypatch):
    """A registry of this test's own: the histories it makes go with it."""
    monkeypatch.setattr(history, "_histories", dict(history._histories))
    return history


def test_the_files_are_in_the_monitor_folder_of_the_state_tree(state_root):
    from utk_curio.backend.app.common import user_storage

    assert REAL_FOLDER() == user_storage.curio_root() / "monitor" == state_root / "monitor"


def test_each_change_rewrites_the_file_with_every_row(histories):
    samples = histories.History("samples")
    samples.update(_adding({"hour": _hour(1), "server": "backend", "value": 12}))
    samples.update(_adding({"hour": _hour(0), "server": "backend", "value": 15}))

    assert samples.path() == history._folder() / "samples.json"
    doc = _file(samples)
    assert doc["name"] == "samples"
    assert doc["rows"] == samples.rows() == [
        {"hour": _hour(1), "server": "backend", "value": 12},
        {"hour": _hour(0), "server": "backend", "value": 15},
    ]
    assert not [path.name for path in history._folder().iterdir() if path.name.endswith(".tmp")]


def test_the_oldest_hours_go_once_the_rows_span_more_than_its_days(histories):
    """Counted back from the newest row's hour: one day holds it and the 23 before it."""
    day = histories.History("one-day", max_days=1)
    day.update(_adding(*({"hour": _hour(hours), "value": hours} for hours in (30, 24, 23, 1))))
    assert [row["value"] for row in day.rows()] == [24, 23, 1]

    day.update(_adding({"hour": _hour(-10), "value": -10}))
    assert [row["value"] for row in day.rows()] == [1, -10]
    assert [row["value"] for row in _file(day)["rows"]] == [1, -10]


def test_a_history_holds_90_days_by_default(histories):
    ninety = histories.History("ninety")
    ninety.update(_adding(*({"hour": _hour(hours), "value": hours} for hours in (2160, 2159, 0))))
    assert [row["value"] for row in ninety.rows()] == [2159, 0]


def test_a_row_without_an_hour_is_left_out(histories):
    odd = histories.History("odd")
    odd.update(_adding({"value": 1}, {"hour": "yesterday", "value": 2}, {"hour": _hour(0), "value": 3}))
    assert odd.rows() == [{"hour": _hour(0), "value": 3}]


def test_rows_hands_out_copies(histories):
    samples = histories.History("samples")
    samples.update(_adding({"hour": _hour(0), "value": 1}))
    samples.rows()[0]["value"] = 99
    assert samples.rows() == [{"hour": _hour(0), "value": 1}]


def test_a_backend_start_writes_every_history_anew(histories):
    from utk_curio.backend.app import create_app
    from utk_curio.backend.tests._unit_fixtures import TestConfig

    samples = histories.History("samples")
    samples.update(_adding({"hour": _hour(0), "value": 1}))
    left = histories.History("left-over")
    # What an earlier process left in the file.
    left.path().write_text(json.dumps({"name": "left-over", "rows": [{"hour": _hour(5), "value": 9}]}),
                           encoding="utf-8")

    create_app(TestConfig)

    for each in (samples, left):
        assert each.rows() == [], each.name
        doc = _file(each)
        assert (doc["name"], doc["rows"]) == (each.name, [])
        datetime.strptime(doc["startedAt"], history.STAMP)


def test_a_history_that_cannot_write_its_file_keeps_its_rows_and_never_raises(histories, tmp_path, monkeypatch):
    blocked = tmp_path / "a-file"
    blocked.write_text("not a folder", encoding="utf-8")
    monkeypatch.setattr(history, "_folder", lambda: blocked / "monitor")
    samples = histories.History("samples")

    samples.update(_adding({"hour": _hour(0), "value": 1}))
    assert samples.rows() == [{"hour": _hour(0), "value": 1}]
    histories.start()
    assert samples.rows() == []


def test_a_change_that_raises_never_raises(histories):
    samples = histories.History("samples")
    samples.update(_adding({"hour": _hour(0), "value": 1}))

    def broken(rows):
        raise RuntimeError("a change that fails")

    samples.update(broken)
    assert samples.rows() == [{"hour": _hour(0), "value": 1}]
