"""``/artifacts/readable`` says which artifacts each session may read.

The backend asks before it reads or installs an output a request names: a
save, or the Data Catalog's live outputs (``backend/app/runs/kept.readable_by``),
and, for a reader with no sign-in, an output its account vouches for
(``kept.readable_by_account``): a name may be read under several sessions, and
a call may name sessions every name is read under, the account's sign-ins.
The rule is the one every read here follows (``parsers.session_may_read``): a
session reads its own artifacts and those from before rows carried a session,
and a kept run's session also reads what other kept runs made. A read that
names no session, which reads any row elsewhere, reads only a row from before
rows carried one.
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

    def ask(self, reads, sessions=None):
        body = {"reads": reads}
        if sessions is not None:
            body["sessions"] = sessions
        return self.client.post("/artifacts/readable", json=body)

    def readable(self, reads, sessions=None):
        response = self.ask(reads, sessions)
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

    def test_a_name_reads_under_any_of_the_sessions_it_names(self):
        earlier = "alice-earlier-token"
        mine, mine_before, theirs, untagged = _table(ALICE), _table(earlier), _table(BOB), _table()

        self.assertEqual(
            self.readable({mine: [ALICE, earlier], mine_before: [ALICE, earlier], theirs: [ALICE, earlier],
                           untagged: [ALICE]}),
            {mine, mine_before, untagged},
        )

    def test_the_sessions_a_call_names_read_every_name(self):
        earlier = "alice-earlier-token"
        mine, mine_before, theirs, untagged = _table(ALICE), _table(earlier), _table(BOB), _table()
        kept = _table(new_session_id())

        self.assertEqual(
            self.readable({mine: [], mine_before: [], theirs: [], untagged: [], kept: []}, sessions=[ALICE, earlier]),
            {mine, mine_before, untagged},
        )

    def test_a_name_read_under_no_session_reads_only_a_row_from_before_sessions(self):
        mine, untagged, kept = _table(ALICE), _table(), _table(new_session_id())

        self.assertEqual(self.readable({mine: [], untagged: [], kept: []}), {untagged})

    def test_a_kept_runs_session_reads_only_the_name_it_is_named_for(self):
        """It would read what every kept run made, so it may not read every
        name of a call."""
        first_run, second_run = new_session_id(), new_session_id()
        first, second = _table(first_run), _table(second_run)

        self.assertEqual(self.readable({first: [first_run], second: []}), {first})
        self.assertEqual(self.ask({first: [], second: []}, sessions=[first_run]).status_code, 400)

    def test_every_session_a_call_names_is_one(self):
        untagged = _table()

        for reads, sessions in (
            ({untagged: [""]}, None), ({untagged: [None]}, None), ({untagged: [ALICE, 7]}, None),
            ({untagged: []}, ALICE), ({untagged: []}, [""]), ({untagged: []}, [None]),
        ):
            with self.subTest(reads=reads, sessions=sessions):
                self.assertEqual(self.ask(reads, sessions).status_code, 400)

    def test_a_call_names_at_most_its_bound_of_sessions(self):
        from utk_curio.sandbox.app import api

        bound = api.MAX_READ_SESSIONS_PER_CALL
        untagged = _table()
        many = [f"token-{index}" for index in range(bound + 1)]

        self.assertEqual(self.readable({untagged: []}, sessions=many[:bound]), {untagged})
        self.assertEqual(self.ask({untagged: []}, sessions=many).status_code, 400)
        self.assertEqual(self.ask({untagged: many}).status_code, 400)
        self.assertEqual(self.ask({untagged: many[:1]}, sessions=many[1:]).status_code, 400)


if __name__ == "__main__":
    unittest.main()
