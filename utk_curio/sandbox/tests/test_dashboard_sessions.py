"""What a dashboard viewer's run makes is described and forgotten by session.

A run a dashboard's viewer starts tags each step's artifacts with a session of
its own (``common/dashboard_sessions.py``). The backend keeps the output for a
while, then asks the sandbox to forget the session:

- ``/artifact-sessions/describe`` names each artifact the session made and
  counts the bytes they hold, the files the store wrote them to included;
- ``/artifact-sessions/forget`` deletes their rows and those files, and
  nothing of any other session;
- both refuse a session that is not a dashboard's, so no call reaches a
  sign-in's artifacts.
"""

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import pandas as pd

from utk_curio.sandbox.app import app
from utk_curio.sandbox.util import parsers
from utk_curio.sandbox.util.db import init_db, release_connection


def new_session_id():
    # Imported here, so a checkout without the module fails each test on its own.
    from utk_curio.common.dashboard_sessions import new_session_id as make

    return make()


class DashboardSessionsTestCase(unittest.TestCase):
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
        self.data_dir = Path(self._tmp.name) / ".curio" / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        release_connection()
        self.addCleanup(release_connection)
        init_db()

    def _parquet(self, art_id):
        return self.data_dir / "artifacts" / f"{art_id}.parquet"

    def test_a_session_id_has_the_dashboard_shape(self):
        from utk_curio.common.dashboard_sessions import is_dashboard_session

        session = new_session_id()
        self.assertTrue(is_dashboard_session(session))
        self.assertNotEqual(session, new_session_id())
        for other in ("dashboard-", "dashboard-xyz", "Bearer-token", None, 7, f"{session}x"):
            self.assertFalse(is_dashboard_session(other), other)

    def test_describe_names_each_artifact_and_counts_its_file(self):
        session = new_session_id()
        frame = parsers.save_to_duckdb(pd.DataFrame({"a": list(range(200))}), session_id=session)
        pair = parsers.save_to_duckdb((1, "two"), session_id=session)
        elsewhere = parsers.save_to_duckdb(pd.DataFrame({"b": [1]}), session_id=new_session_id())

        response = self.client.post("/artifact-sessions/describe", json={"sessionIds": [session]})

        self.assertEqual(response.status_code, 200, response.data)
        described = response.get_json()["sessions"][session]
        self.assertIn(frame, described["ids"])
        self.assertIn(pair, described["ids"])
        # The pair's two values are artifacts of their own, of the same session.
        self.assertEqual(len(described["ids"]), 4)
        self.assertNotIn(elsewhere, described["ids"])
        self.assertGreaterEqual(described["bytes"], self._parquet(frame).stat().st_size)

    def test_forget_deletes_the_rows_and_files_of_those_sessions_only(self):
        session = new_session_id()
        kept_session = new_session_id()
        frame = parsers.save_to_duckdb(pd.DataFrame({"a": [1, 2, 3]}), session_id=session)
        listed = parsers.save_to_duckdb([1, 2, 3], session_id=session)
        kept = parsers.save_to_duckdb(pd.DataFrame({"b": [1]}), session_id=kept_session)
        self.assertTrue(self._parquet(frame).exists())

        response = self.client.post("/artifact-sessions/forget", json={"sessionIds": [session]})

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.get_json()["forgotten"], 2)
        self.assertFalse(self._parquet(frame).exists())
        self.assertFalse((self.data_dir / "artifacts" / f"{listed}.json.zlib").exists())
        with self.assertRaises(KeyError):
            parsers.load_from_duckdb(frame)
        self.assertEqual(parsers.load_from_duckdb(kept, session_id=kept_session)["b"].tolist(), [1])

    def test_a_session_that_is_not_a_dashboards_is_refused(self):
        signed_in = parsers.save_to_duckdb(pd.DataFrame({"a": [1]}), session_id="a-sign-in-token")
        for route in ("/artifact-sessions/describe", "/artifact-sessions/forget"):
            for body in ({"sessionIds": ["a-sign-in-token"]}, {"sessionIds": "dashboard-x"}, {}):
                response = self.client.post(route, json=body)
                self.assertEqual(response.status_code, 400, (route, body, response.data))
        self.assertEqual(parsers.load_from_duckdb(signed_in, session_id="a-sign-in-token")["a"].tolist(), [1])


if __name__ == "__main__":
    unittest.main()
