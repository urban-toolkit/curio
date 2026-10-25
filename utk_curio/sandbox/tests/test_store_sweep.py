"""The store keeps every run's output seven days, then sweeps it.

``parsers.forget_made_before``, behind ``/artifacts/sweep``, deletes what the
store made before a time that no kept run holds: an artifact with its row, a
part of a tuple, list or dict output by its whole output's age, and only files
under ``artifacts/``. A file a remaining row names stays, and a file the Data
Catalog linked keeps its other name. It also removes what earlier versions
left at the top of the shared data directory, once that is old too.

Artifacts are written through the real ``save_to_duckdb``, with the time in
their ids set by hand. A file's age is the later of its own time and the
change of its entry, and a test can set only the first, so these tests sweep
at a time an hour ahead: every file is older than that unless its own time is
set past it. The route's test sweeps a week back, as the backend does.
"""

import contextlib
import itertools
import json
import os
import secrets
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import pandas as pd

from utk_curio.common.kept_sessions import new_session_id
from utk_curio.sandbox.app import app
from utk_curio.sandbox.util import parsers
from utk_curio.sandbox.util.db import get_connection, init_db, release_connection

DAY_MS = 24 * 3600 * 1000
NOW_MS = int(time.time() * 1000)
#: The time the tests sweep at, a day before it, and a day after it.
CUTOFF = NOW_MS + 3600 * 1000
OLD = CUTOFF - DAY_MS
NEW = CUTOFF + DAY_MS


@contextlib.contextmanager
def made_at(*times):
    """Artifacts minted in this block are dated *times*, in turn; the last
    one for the rest."""
    stamps = itertools.chain(times, itertools.repeat(times[-1]))
    with mock.patch.object(parsers, "_make_id", lambda: f"{next(stamps):013d}_{secrets.token_hex(4)}"):
        yield


def used_at(path: Path, ms: int) -> Path:
    os.utime(path, (ms / 1000, ms / 1000))
    return path


class TheStoreSweepTestCase(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        env = mock.patch.dict(os.environ, {
            "CURIO_LAUNCH_CWD": self._tmp.name,
            "CURIO_SHARED_DATA": "./.curio/data/",
        })
        env.start()
        self.addCleanup(env.stop)
        self.data = Path(self._tmp.name) / ".curio" / "data"
        self.artifacts = self.data / "artifacts"
        self.artifacts.mkdir(parents=True, exist_ok=True)
        release_connection()
        self.addCleanup(release_connection)
        init_db()
        self.frame = pd.DataFrame({"n": [1, 2, 3]})

    def store(self, value, *times, session_id=None):
        with made_at(*times):
            return parsers.save_to_duckdb(value, node_id="n", session_id=session_id)

    def raster_row(self, made, path: Path, session_id=None) -> str:
        """A raster artifact naming *path*, as ``save_to_duckdb`` stores one."""
        art_id = f"{made:013d}_{secrets.token_hex(4)}"
        get_connection().execute(
            "INSERT INTO artifacts (id, node_id, kind, session_id, value_str) VALUES (?, 'n', 'raster', ?, ?)",
            [art_id, session_id, str(path)],
        )
        return art_id

    def ids(self):
        return {row[0] for row in get_connection().execute("SELECT id FROM artifacts").fetchall()}

    def stored(self, art_id):
        return self.artifacts / f"{art_id}.parquet"

    def parts(self, parent):
        row = get_connection().execute("SELECT value_json FROM artifacts WHERE id = ?", [parent]).fetchone()
        return list(json.loads(row[0]))

    def test_an_output_made_before_the_time_goes_with_its_file(self):
        old = self.store(self.frame, OLD)
        new = self.store(self.frame, NEW)

        self.assertEqual(parsers.forget_made_before(CUTOFF), 1)

        self.assertEqual(self.ids(), {new})
        self.assertFalse(self.stored(old).exists())
        self.assertTrue(self.stored(new).is_file())

    def test_a_kept_runs_output_is_left_to_its_entry(self):
        kept = self.store(self.frame, OLD, session_id=new_session_id())

        self.assertEqual(parsers.forget_made_before(CUTOFF), 0)

        self.assertEqual(self.ids(), {kept})
        self.assertTrue(self.stored(kept).is_file())

    def test_a_kept_runs_output_goes_a_day_after_any_entry_would_have(self):
        """No entry outlives the cutoff, so a kept row a day older still is
        one whose entry was never written, or whose forget failed."""
        orphaned = self.store(self.frame, OLD - DAY_MS, session_id=new_session_id())
        kept = self.store(self.frame, OLD, session_id=new_session_id())

        self.assertEqual(parsers.forget_made_before(CUTOFF), 1)

        self.assertEqual(self.ids(), {kept})
        self.assertFalse(self.stored(orphaned).exists())

    def test_a_tuple_goes_whole_by_its_own_age(self):
        """Its id is minted before its parts'."""
        recent = self.store((self.frame, self.frame), NEW, OLD)
        old = self.store((self.frame, self.frame), OLD, NEW)
        recent_parts, old_parts = self.parts(recent), self.parts(old)

        self.assertEqual(parsers.forget_made_before(CUTOFF), 3)

        self.assertEqual(self.ids(), {recent, *recent_parts})
        self.assertTrue(all(self.stored(part).is_file() for part in recent_parts))
        self.assertFalse(any(self.stored(part).exists() for part in old_parts))

    def test_a_saved_outputs_linked_file_keeps_its_table(self):
        old = self.store(self.frame, OLD)
        saved = Path(self._tmp.name) / "catalog.parquet"
        os.link(self.stored(old), saved)

        parsers.forget_made_before(CUTOFF)

        self.assertFalse(self.stored(old).exists())
        pd.testing.assert_frame_equal(pd.read_parquet(saved), self.frame)

    def test_only_a_rasters_file_under_artifacts_goes(self):
        inside = self.artifacts / "made-by-a-node.tif"
        outside = Path(self._tmp.name) / "docs-raster.tif"
        for path in (inside, outside):
            path.write_bytes(b"II*\x00")
        self.raster_row(OLD, inside)
        self.raster_row(OLD, outside)

        self.assertEqual(parsers.forget_made_before(CUTOFF), 2)

        self.assertFalse(inside.exists())
        self.assertTrue(outside.is_file())

    def test_a_raster_a_newer_row_returned_too_stays(self):
        """An in-process run writes a raster it rebuilds once, by its content,
        and every row that returns it names that one file."""
        shared = self.artifacts / "autark-raster-shared.tif"
        shared.write_bytes(b"II*\x00")
        self.raster_row(OLD, shared)
        newer = self.raster_row(NEW, shared)

        self.assertEqual(parsers.forget_made_before(CUTOFF), 1)

        self.assertEqual(self.ids(), {newer})
        self.assertTrue(shared.is_file())

    def test_a_raster_a_kept_run_returned_too_stays(self):
        shared = self.artifacts / "autark-raster-kept.tif"
        shared.write_bytes(b"II*\x00")
        self.raster_row(OLD, shared)
        kept = self.raster_row(OLD, shared, session_id=new_session_id())

        self.assertEqual(parsers.forget_made_before(CUTOFF), 1)

        self.assertEqual(self.ids(), {kept})
        self.assertTrue(shared.is_file())

    def test_a_file_under_artifacts_no_row_names_goes_once_nothing_used_it(self):
        unused = self.artifacts / "autark-raster-unused.tif"
        used = self.artifacts / "autark-raster-used.tif"
        for path in (unused, used):
            path.write_bytes(b"II*\x00")
        used_at(used, NEW)
        new = self.store(self.frame, NEW)
        used_at(self.stored(new), OLD)

        parsers.forget_made_before(CUTOFF)

        self.assertFalse(unused.exists())
        self.assertTrue(used.is_file())
        self.assertTrue(self.stored(new).is_file(), "a file its row names stays, whatever its time")

    def test_what_earlier_versions_left_at_the_top_goes_once_old(self):
        stamp = f"{OLD:013d}_0123abcd"
        left = [
            self.data / f"{stamp}_output.parquet",
            self.data / f"{stamp}_output.parquet.decode.json",
            self.data / f"{stamp}_output.parquet.meta.json",
            self.data / stamp,
        ]
        recent = self.data / f"{NEW:013d}_4567cdef_output.parquet"
        other = self.data / "notes.txt"
        for path in (*left, recent, other):
            path.write_bytes(b"x")
        used_at(recent, NEW)
        bundle = self.data / "bundles" / stamp
        bundle.mkdir(parents=True)
        (bundle / "00_dataframe.parquet").write_bytes(b"x")

        parsers.forget_made_before(CUTOFF)

        self.assertEqual([path for path in left if path.exists()], [])
        self.assertFalse((self.data / "bundles").exists())
        self.assertTrue(recent.is_file())
        self.assertTrue(other.is_file())
        self.assertTrue((self.data / "curio_data.duckdb").is_file())

    def test_the_route_sweeps_a_week_back_and_never_the_last_day(self):
        week_ago = NOW_MS - 7 * DAY_MS
        old = self.store(self.frame, week_ago - DAY_MS)
        recent = self.store(self.frame, NOW_MS - 3600 * 1000)

        for refused in ({"madeBefore": NOW_MS}, {"madeBefore": "soon"}, {"madeBefore": True}, {}):
            response = self.client.post("/artifacts/sweep", json=refused)
            self.assertEqual(response.status_code, 400, refused)
        self.assertEqual(self.ids(), {old, recent})

        response = self.client.post("/artifacts/sweep", json={"madeBefore": week_ago})

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.get_json(), {"forgotten": 1})
        self.assertEqual(self.ids(), {recent})


if __name__ == "__main__":
    unittest.main()
