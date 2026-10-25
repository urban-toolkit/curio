"""``/artifacts/readable`` says which artifacts each session may read.

The backend asks before it reads or installs an output a request names: a
save, or the Data Catalog's live outputs (``backend/app/runs/kept.readable_by``).
The rule is the one every read here follows (``parsers.session_may_read``): a
session reads its own artifacts and those from before rows carried a session,
and a kept run's session also reads what other kept runs made. A read that
names no session, which reads any row elsewhere, is refused here.
"""

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import pandas as pd

from utk_curio.common.kept_sessions import new_session_id
from utk_curio.sandbox.app import app
from utk_curio.sandbox.app.api import MAX_SESSIONS_PER_CALL
from utk_curio.sandbox.util.db import init_db, release_connection
from utk_curio.sandbox.util.parsers import save_to_duckdb

ALICE, BOB = "alice-token", "bob-token"


def _table(session=None):
    return save_to_duckdb(pd.DataFrame({"n": [1, 2]}), node_id="n", session_id=session)


class ArtifactsReadableTestCase(unittest.TestCase):
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
        (Path(self._tmp.name) / ".curio" / "data").mkdir(parents=True, exist_ok=True)
        release_connection()
        self.addCleanup(release_connection)
        init_db()

    def ask(self, reads):
        return self.client.post("/artifacts/readable", json={"reads": reads})

    def readable(self, reads):
        response = self.ask(reads)
        self.assertEqual(response.status_code, 200, response.data)
        return set(response.get_json()["readable"])

    def test_a_sign_in_reads_its_own_artifacts_and_untagged_ones_only(self):
        mine, theirs, untagged = _table(ALICE), _table(BOB), _table()

        self.assertEqual(self.readable({mine: ALICE, theirs: ALICE, untagged: ALICE}), {mine, untagged})
        self.assertEqual(self.readable({theirs: BOB}), {theirs})

    def test_a_kept_runs_session_reads_what_kept_runs_made_and_no_sign_ins(self):
        kept, signed_in = _table(new_session_id()), _table(ALICE)
        another_kept_run = new_session_id()

        self.assertEqual(self.readable({kept: another_kept_run, signed_in: another_kept_run}), {kept})
        self.assertEqual(self.readable({kept: ALICE}), set())

    def test_an_artifact_with_no_row_is_not_readable(self):
        self.assertEqual(self.readable({"1700000000000_deadbeef": ALICE}), set())

    def test_every_read_names_an_artifact_and_a_session(self):
        untagged = _table()

        for reads in ({untagged: ""}, {untagged: None}, {"": ALICE}, [untagged], untagged, None):
            with self.subTest(reads=reads):
                self.assertEqual(self.ask(reads).status_code, 400)

    def test_a_call_names_at_most_its_bound_of_artifacts(self):
        reads = {f"1700000000000_{index:08x}": ALICE for index in range(MAX_SESSIONS_PER_CALL + 1)}

        self.assertEqual(self.ask(reads).status_code, 400)


if __name__ == "__main__":
    unittest.main()
