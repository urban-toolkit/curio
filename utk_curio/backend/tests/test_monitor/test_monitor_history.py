"""The monitor's histories (``monitor/history.py``).

A history is one file in the monitor folder, which every backend process
writes and nothing starts over: a tally is held in the process until a write,
a sample is written at once, and a write joins what the process holds into the
file's rows under the file's lock. Rows of the last 24 hours span 5 minutes
and then join their hour's row, every sum unchanged, and a history keeps the
last 90 days counted back from the current hour, written since or not. A write
that fails keeps what it took for the next, a file of another format is read
as empty, one that does not parse is set aside, and the folder is its owner's
alone. A process writes what it holds when SIGTERM stops it.

The histories here are each test's own, in a registry that goes with the
test, and their files are in the test's own folder (``conftest.py``). The
clock is the test's (``clock``), so no test crosses a 5-minute slot as it runs.
"""

import json
import logging
import os
import signal
import stat
import subprocess
import sys
import threading
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import utk_curio
from utk_curio.backend.app.monitor import history

#: The real folder, taken before any test points it at a folder of its own.
REAL_FOLDER = history._folder
#: The test's time, on a 5-minute slot.
T = datetime(2026, 11, 6, 15, 20, tzinfo=timezone.utc)


def _at(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:00Z")


def _file(each: history.History) -> dict:
    return json.loads(each.path().read_text(encoding="utf-8"))


def _tally(name: str = "usage") -> history.History:
    return history.History(name, identity=("key",))


def _totals(rows: list) -> dict:
    """Each key's count, milliseconds and buckets over *rows*."""
    totals: dict = {}
    for row in rows:
        held = totals.setdefault(row["key"], {"count": 0, "ms": 0, "buckets": [0, 0, 0]})
        held["count"] += row["count"]
        held["ms"] += row["ms"]
        held["buckets"] = [a + b for a, b in zip(held["buckets"], row["buckets"])]
    return totals


@pytest.fixture()
def histories(monkeypatch):
    """A registry of this test's own: the histories it makes go with it."""
    monkeypatch.setattr(history, "_histories", {})
    return history


@pytest.fixture()
def clock(monkeypatch):
    """The histories' clock, which a test moves with ``clock.at = ...``."""
    state = types.SimpleNamespace(at=T)
    monkeypatch.setattr(history, "_now", lambda: state.at)
    return state


def test_the_folder_is_the_one_curio_monitor_dir_names_else_monitor_in_the_state_tree(state_root, tmp_path,
                                                                                     monkeypatch):
    from utk_curio.backend.app.common import user_storage

    monkeypatch.delenv("CURIO_MONITOR_DIR", raising=False)
    assert REAL_FOLDER() == user_storage.curio_root() / "monitor" == state_root / "monitor"
    monkeypatch.setenv("CURIO_MONITOR_DIR", str(tmp_path / "kept"))
    assert REAL_FOLDER() == tmp_path / "kept"


def test_a_tally_is_held_in_the_process_until_it_is_written(histories, clock):
    usage = _tally()
    usage.add({"key": "node.python", "count": 1, "ms": 120})
    usage.add({"key": "node.python", "count": 1, "ms": 80})
    assert not usage.path().exists()
    assert usage.rows() == []

    assert usage.flush() is True
    doc = _file(usage)
    assert (doc["name"], doc["format"]) == ("usage", 2)
    assert doc["rows"] == usage.rows() == [
        {"at": _at(T), "span": "5m", "key": "node.python", "count": 2, "ms": 200},
    ]
    assert not [path.name for path in history._folder().iterdir() if path.name.endswith(".tmp")]


def test_rows_of_one_slot_and_identity_add_whole_numbers_and_lists_place_by_place(histories, clock):
    usage = _tally()
    usage.add({"key": "turn", "count": 1, "ms": 900, "buckets": [0, 1]})
    usage.add({"key": "turn", "count": 2, "ms": 300, "buckets": [2, 0, 1], "failed": 1}, at=T + timedelta(minutes=4))
    usage.add({"key": "run", "count": 1, "ms": 10, "buckets": [1]})
    usage.add({"key": "turn", "count": 1, "ms": 50, "buckets": [1]}, at=T + timedelta(minutes=5))
    assert usage.flush() is True

    assert usage.rows() == [
        {"at": _at(T), "span": "5m", "key": "turn", "count": 3, "ms": 1200, "buckets": [2, 1, 1], "failed": 1},
        {"at": _at(T), "span": "5m", "key": "run", "count": 1, "ms": 10, "buckets": [1]},
        {"at": _at(T + timedelta(minutes=5)), "span": "5m", "key": "turn", "count": 1, "ms": 50, "buckets": [1]},
    ]


def test_a_second_history_of_the_same_name_reads_the_rows_back_as_after_a_restart(histories, clock):
    first = _tally()
    first.add({"key": "turn", "count": 3})
    assert first.flush() is True

    again = _tally()  # the same history in the process a restart starts
    assert again.rows() == first.rows() == [{"at": _at(T), "span": "5m", "key": "turn", "count": 3}]
    again.add({"key": "turn", "count": 2})
    assert again.flush() is True
    assert again.rows() == [{"at": _at(T), "span": "5m", "key": "turn", "count": 5}]


def test_a_backend_start_leaves_the_files_as_they_are(histories, clock):
    from utk_curio.backend.app import create_app
    from utk_curio.backend.tests._unit_fixtures import TestConfig

    usage = _tally()
    usage.add({"key": "turn", "count": 3})
    assert usage.flush() is True
    before = usage.path().read_bytes()

    create_app(TestConfig)

    assert usage.path().read_bytes() == before
    assert usage.rows() == [{"at": _at(T), "span": "5m", "key": "turn", "count": 3}]


def test_two_processes_adding_at_once_sum_exactly(histories, clock, monkeypatch):
    """A forked process writes and stops after its read of the file, inside
    the file's lock; this process's write then waits for the lock, and reads
    what the other wrote. Without the lock, this one's write would land
    first and the other's, made from its stale read, over it."""
    from utk_curio.backend.tests._support.two_processes import Window, race

    usage = _tally()
    window = Window()
    read = history._read_to_write

    def _read_then_stop(each, path, now):
        rows = read(each, path, now)
        window.stop_here()
        return rows

    monkeypatch.setattr(history, "_read_to_write", _read_then_stop)

    def in_the_other_process():
        usage.add({"key": "request", "count": 2, "ms": 40, "buckets": [1, 1]})
        assert usage.flush() is True

    def here():
        usage.add({"key": "request", "count": 5, "ms": 100, "buckets": [3, 2]})
        return usage.flush()

    raced = race(window, in_the_other_process, here, monkeypatch)

    assert raced.child_exit == 0, raced.child_error
    assert raced.here is True
    assert usage.rows() == [
        {"at": _at(T), "span": "5m", "key": "request", "count": 7, "ms": 140, "buckets": [4, 3]},
    ]


def test_a_write_that_fails_keeps_its_rows_for_the_next_and_is_logged_once(histories, clock, tmp_path,
                                                                            monkeypatch, caplog):
    folder = history._folder()
    blocked = tmp_path / "a-file"
    blocked.write_text("not a folder", encoding="utf-8")
    monkeypatch.setattr(history, "_folder", lambda: blocked / "monitor")
    usage = _tally()

    with caplog.at_level(logging.WARNING, logger=history.log.name):
        usage.add({"key": "run", "count": 1})
        assert usage.flush() is False
        usage.add({"key": "run", "count": 2})
        assert usage.flush() is False
    logged = [record for record in caplog.records if "usage" in record.getMessage()]
    assert len(logged) == 1, [record.getMessage() for record in logged]

    monkeypatch.setattr(history, "_folder", lambda: folder)
    assert usage.flush() is True
    assert usage.rows() == [{"at": _at(T), "span": "5m", "key": "run", "count": 3}]
    # Nothing was held twice: the next write adds nothing.
    assert usage.flush() is True
    assert usage.rows() == [{"at": _at(T), "span": "5m", "key": "run", "count": 3}]


def test_a_write_that_fails_before_the_file_is_replaced_leaves_the_file_as_it_was(histories, clock, monkeypatch):
    usage = _tally()
    usage.add({"key": "run", "count": 1})
    assert usage.flush() is True
    before = usage.path().read_bytes()
    replace = history._replace

    def fails(path, document):
        raise OSError("the disk is full")

    monkeypatch.setattr(history, "_replace", fails)
    usage.add({"key": "run", "count": 2})
    assert usage.flush() is False
    assert usage.path().read_bytes() == before

    monkeypatch.setattr(history, "_replace", replace)
    assert usage.flush() is True
    assert usage.rows() == [{"at": _at(T), "span": "5m", "key": "run", "count": 3}]


def test_a_five_minute_row_joins_its_hour_once_it_is_24_hours_old_with_every_sum_unchanged(histories, clock):
    usage = _tally()
    for minutes, count in ((0, 1), (5, 2), (35, 3)):
        usage.add({"key": "node.python", "count": count, "ms": 100 * count, "buckets": [count, 0, 1]},
                  at=T + timedelta(minutes=minutes))
    usage.add({"key": "turn", "count": 4, "ms": 4000, "buckets": [0, 4, 0]}, at=T + timedelta(minutes=55))
    assert usage.flush() is True
    kept = usage.rows()
    assert [(row["at"], row["span"]) for row in kept] == [
        (_at(T), "5m"), (_at(T + timedelta(minutes=5)), "5m"),
        (_at(T + timedelta(minutes=35)), "5m"), (_at(T + timedelta(minutes=55)), "5m"),
    ]

    # The last 24 hours are the current 5-minute slot and the 287 before it.
    clock.at = T + timedelta(hours=23, minutes=55)
    assert usage.rows() == kept

    clock.at = T + timedelta(hours=24)
    rows = usage.rows()
    assert [(row["at"], row["span"], row["key"], row["count"]) for row in rows] == [
        ("2026-11-06T15:00:00Z", "1h", "node.python", 1),
        (_at(T + timedelta(minutes=5)), "5m", "node.python", 2),
        (_at(T + timedelta(minutes=35)), "5m", "node.python", 3),
        (_at(T + timedelta(minutes=55)), "5m", "turn", 4),
    ]
    assert _totals(rows) == _totals(kept)

    # A day and an hour later each row has joined its hour, in the file too.
    clock.at = T + timedelta(hours=25)
    usage.add({"key": "run", "count": 1, "ms": 1, "buckets": [1, 0, 0]})
    assert usage.flush() is True
    written = _file(usage)["rows"]
    assert [(row["at"], row["span"], row["key"]) for row in written] == [
        ("2026-11-06T15:00:00Z", "1h", "node.python"),
        ("2026-11-06T16:00:00Z", "1h", "turn"),
        (_at(T + timedelta(hours=25)), "5m", "run"),
    ]
    assert written[0] == {"at": "2026-11-06T15:00:00Z", "span": "1h", "key": "node.python",
                          "count": 6, "ms": 600, "buckets": [6, 0, 3]}
    assert {key: totals for key, totals in _totals(written).items() if key != "run"} == _totals(kept)
    assert usage.rows() == written


def test_a_row_leaves_once_the_current_hour_is_90_days_past_it_written_since_or_not(histories, clock):
    usage = _tally()
    usage.add({"key": "run", "count": 1}, at=T)
    usage.add({"key": "run", "count": 10}, at=T + timedelta(hours=1))
    assert usage.flush() is True

    # 90 days are the current hour and the 2,159 before it.
    clock.at = T + timedelta(hours=2159)
    assert [row["count"] for row in usage.rows()] == [1, 10]
    clock.at = T + timedelta(hours=2160)
    assert [row["count"] for row in usage.rows()] == [10]
    # Nothing was written since: the file still holds it, and a route does not show it.
    assert [row["count"] for row in _file(usage)["rows"]] == [1, 10]

    usage.add({"key": "run", "count": 100})
    assert usage.flush() is True
    assert [(row["span"], row["count"]) for row in _file(usage)["rows"]] == [("1h", 10), ("5m", 100)]


def test_a_history_of_fewer_days_keeps_fewer(histories, clock):
    day = history.History("one-day", identity=("key",), max_days=1)
    day.add({"key": "run", "count": 1})
    assert day.flush() is True
    clock.at = T + timedelta(hours=23)
    assert [row["count"] for row in day.rows()] == [1]
    clock.at = T + timedelta(hours=24)
    assert day.rows() == []


def test_samples_are_written_at_once_and_joined_by_their_rule(histories, clock):
    def larger(old: dict, new: dict) -> dict:
        return {**old, "count": max(old["count"], new["count"])}

    seen = history.History("seen", span=history.AN_HOUR, join=larger)
    assert seen.put({"count": 3}) is True
    assert _file(seen)["rows"] == [{"at": "2026-11-06T15:00:00Z", "span": "1h", "count": 3}]
    assert seen.put({"count": 2}, at=T + timedelta(minutes=10)) is True
    assert seen.put({"count": 5}, at=T + timedelta(minutes=20)) is True
    assert seen.put({"count": 1}, at=T + timedelta(hours=1)) is True
    assert seen.rows() == [
        {"at": "2026-11-06T15:00:00Z", "span": "1h", "count": 5},
        {"at": "2026-11-06T16:00:00Z", "span": "1h", "count": 1},
    ]


def test_an_unreadable_file_is_set_aside_named_in_the_errors_and_a_new_one_begun(histories, clock):
    from utk_curio.backend.app.monitor import errors

    usage = _tally()
    usage.path().parent.mkdir(parents=True, exist_ok=True)
    usage.path().write_text("{not a history", encoding="utf-8")
    # A read finds no rows and moves nothing.
    assert usage.rows() == []
    assert usage.path().read_text(encoding="utf-8") == "{not a history"

    usage.add({"key": "run", "count": 1})
    assert usage.flush() is True

    aside = usage.path().with_name("usage.json.unreadable-20261106T152000Z")
    assert aside.read_text(encoding="utf-8") == "{not a history"
    assert usage.rows() == [{"at": _at(T), "span": "5m", "key": "run", "count": 1}]
    entries = errors.snapshot()["errors"]
    assert [(entry["source"], entry["summary"]) for entry in entries] == [
        ("backend", "The monitor history usage could not be read"),
    ]
    assert aside.name in entries[0]["detail"]


def test_a_file_of_another_format_is_read_as_no_rows_and_replaced(histories, clock):
    usage = _tally()
    usage.path().parent.mkdir(parents=True, exist_ok=True)
    # What a version that started every history over at each start wrote.
    usage.path().write_text(json.dumps({"name": "usage", "startedAt": "2026-11-06T14:02:00Z", "rows": [
        {"hour": "2026-11-06T14:00:00Z", "key": "run", "count": 9},
    ]}), encoding="utf-8")
    assert usage.rows() == []

    usage.add({"key": "run", "count": 1})
    assert usage.flush() is True
    doc = _file(usage)
    assert (doc["format"], doc["rows"]) == (2, [{"at": _at(T), "span": "5m", "key": "run", "count": 1}])
    assert not list(usage.path().parent.glob("usage.json.unreadable-*"))


def test_a_history_that_names_its_format_reads_that_one_alone_and_writes_it(histories, clock):
    """A history whose rows changed shape names a new format, so no row of the
    old shape is ever joined with its own: a file of the default format reads
    as no rows, and the first write replaces it with the history's format."""
    old = _tally()
    old.add({"key": "run", "count": 9})
    assert old.flush() is True
    assert _file(old)["format"] == history.FORMAT == 2

    usage = history.History("usage", identity=("key",), file_format=3)
    assert usage.file_format == 3
    assert usage.rows() == []
    usage.add({"key": "run", "count": 1})
    assert usage.flush() is True
    doc = _file(usage)
    assert (doc["format"], doc["rows"]) == (3, [{"at": _at(T), "span": "5m", "key": "run", "count": 1}])
    assert not list(usage.path().parent.glob("usage.json.unreadable-*"))
    # The default format's history now reads the new file as no rows in turn.
    assert _tally().rows() == []


def test_a_row_that_is_not_one_is_left_out(histories, clock):
    usage = _tally()
    usage.path().parent.mkdir(parents=True, exist_ok=True)
    good = {"at": _at(T), "span": "5m", "key": "run", "count": 1}
    usage.path().write_text(json.dumps({"name": "usage", "format": 2, "rows": [
        good,
        {"at": _at(T), "key": "run", "count": 2},
        {"at": "yesterday", "span": "5m", "key": "run", "count": 3},
        {"at": "2026-11-06T15:21:00Z", "span": "5m", "key": "run", "count": 4},
        {"at": _at(T), "span": "1h", "key": "run", "count": 5},
        {"at": _at(T), "span": "5m", "key": {"a": 1}, "count": 6},
        "a row",
    ]}), encoding="utf-8")
    assert usage.rows() == [good]


def test_rows_hands_out_copies(histories, clock):
    usage = _tally()
    usage.add({"key": "run", "count": 1})
    assert usage.flush() is True
    usage.rows()[0]["count"] = 99
    assert usage.rows()[0]["count"] == 1


def test_a_row_that_cannot_be_held_never_raises(histories, clock):
    usage = _tally()
    usage.add({"key": ["not", "a", "plain", "value"], "count": 1})
    usage.add({"key": "run", "count": 1})
    assert usage.flush() is True
    assert usage.rows() == [{"at": _at(T), "span": "5m", "key": "run", "count": 1}]


def test_the_folder_is_its_owners_alone(histories, clock):
    folder = history._folder()
    usage = _tally()
    usage.add({"key": "run", "count": 1})
    assert usage.flush() is True
    assert stat.S_IMODE(folder.stat().st_mode) == 0o700

    # A folder someone opened to others is closed again at the next write.
    os.chmod(folder, 0o755)
    usage.add({"key": "run", "count": 1})
    assert usage.flush() is True
    assert stat.S_IMODE(folder.stat().st_mode) == 0o700


def test_rows_sum_by_hour_and_by_day(histories, clock):
    rows = [
        {"at": "2026-11-05T23:00:00Z", "span": "1h", "key": "run", "count": 1},
        {"at": "2026-11-06T15:00:00Z", "span": "1h", "key": "run", "count": 2},
        {"at": _at(T), "span": "5m", "key": "run", "count": 3},
        {"at": _at(T + timedelta(minutes=5)), "span": "5m", "key": "run", "count": 4},
        {"at": _at(T), "span": "5m", "key": "turn", "count": 5},
    ]
    assert history.sums_by(rows, "hour", ("key",)) == [
        {"at": "2026-11-05T23:00:00Z", "span": "1h", "key": "run", "count": 1},
        {"at": "2026-11-06T15:00:00Z", "span": "1h", "key": "run", "count": 9},
        {"at": "2026-11-06T15:00:00Z", "span": "1h", "key": "turn", "count": 5},
    ]
    assert history.sums_by(rows, "day", ("key",)) == [
        {"at": "2026-11-05T00:00:00Z", "span": "1d", "key": "run", "count": 1},
        {"at": "2026-11-06T00:00:00Z", "span": "1d", "key": "run", "count": 9},
        {"at": "2026-11-06T00:00:00Z", "span": "1d", "key": "turn", "count": 5},
    ]


def test_every_process_that_serves_writes_what_it_holds_every_minute(histories, clock, monkeypatch):
    from utk_curio.backend import config

    timers = []

    class Timer:
        """A timer that waits for the test to fire it."""

        def __init__(self, interval, function, args=()):
            self.interval, self.function, self.args, self.daemon = interval, function, args, False

        def start(self):
            timers.append(self)

        def fire(self):
            self.function(*self.args)

    monkeypatch.setattr(history.threading, "Timer", Timer)
    monkeypatch.setattr(history, "_timer", None)
    # Off under --testing, whose tests write the histories themselves.
    assert history.start_writer() is False and timers == []

    monkeypatch.setattr(config, "_is_testing", lambda: False)
    usage = _tally()
    assert history.start_writer() is True
    assert history.start_writer() is False  # a process writes on one timer
    assert [(timer.interval, timer.daemon) for timer in timers] == [(60, True)]

    usage.add({"key": "run", "count": 1})
    assert not usage.path().exists()
    timers[0].fire()
    assert usage.rows() == [{"at": _at(T), "span": "5m", "key": "run", "count": 1}]
    assert [(timer.interval, timer.daemon) for timer in timers] == [(60, True), (60, True)]


#: A process that holds a row, writes on stop as ``serve()`` has it do, says
#: so, and waits to be stopped.
_HOLDS_A_ROW = """
import time
from utk_curio.backend.app.monitor import history
usage = history.History("stopped", identity=("key",))
usage.add({"key": "turn", "count": 3})
print("handled" if history.write_on_stop() else "not handled", flush=True)
time.sleep(120)
"""


def test_sigterm_writes_what_the_process_holds_then_ends_it_as_sigterm_does(tmp_path):
    """The launcher stops each backend with SIGTERM. The process, started as
    a deploy starts it, without ``--testing`` and with ``--monitor-dir``,
    writes its held row into the folder, then ends by the signal."""
    environ = {name: value for name, value in os.environ.items() if name != "CURIO_TESTING"}
    environ["CURIO_MONITOR_DIR"] = str(tmp_path / "kept")
    process = subprocess.Popen(
        [sys.executable, "-c", _HOLDS_A_ROW], cwd=Path(utk_curio.__file__).resolve().parent.parent,
        env=environ, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    lines: list = []

    def read_until_it_says() -> None:
        for line in process.stdout:
            lines.append(line.strip())
            if lines[-1] in ("handled", "not handled"):
                return

    try:
        reader = threading.Thread(target=read_until_it_says, daemon=True)
        reader.start()
        reader.join(60)
        said = lines[-1] if lines else ""
        assert said == "handled", f"{said!r} within 60 s; {process.stderr.read() if process.poll() is not None else ''}"
        assert not (tmp_path / "kept" / "stopped.json").exists(), "the row was written before the process stopped"
        process.send_signal(signal.SIGTERM)
        process.wait(timeout=60)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
    errors = process.stderr.read()

    assert process.returncode == -signal.SIGTERM, errors
    doc = json.loads((tmp_path / "kept" / "stopped.json").read_text(encoding="utf-8"))
    assert [(row["key"], row["count"]) for row in doc["rows"]] == [("turn", 3)], errors
    assert stat.S_IMODE((tmp_path / "kept").stat().st_mode) == 0o700
