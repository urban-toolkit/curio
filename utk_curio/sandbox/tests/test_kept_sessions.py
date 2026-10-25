"""What a kept run makes is described and forgotten by session.

A run whose outputs are kept, a dashboard viewer's among them, tags each
step's artifacts with a session of its own (``common/kept_sessions.py``). The
backend keeps the output for a while, then asks the sandbox to forget the
session:

- ``/artifact-sessions/describe`` names each artifact the session made and
  counts the bytes they hold, the files the store wrote them to included;
- ``/artifact-sessions/forget`` deletes their rows and those files, and
  nothing of any other session;
- both refuse a session that is not a kept run's, so no call reaches a
  sign-in's artifacts;
- a kept step reads what other kept steps made, which the backend hands it
  (its run's earlier steps, the outputs kept from earlier runs), and no
  sign-in's artifacts, which never read theirs either.
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
    from utk_curio.common.kept_sessions import new_session_id as make

    return make()


class KeptSessionsTestCase(unittest.TestCase):
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

    def test_a_session_id_has_the_kept_shape(self):
        from utk_curio.common.kept_sessions import is_kept_session

        session = new_session_id()
        self.assertTrue(is_kept_session(session))
        self.assertNotEqual(session, new_session_id())
        old_shape = "dashboard-" + session[len("kept-"):]
        for other in ("kept-", "kept-xyz", old_shape, "Bearer-token", None, 7, f"{session}x"):
            self.assertFalse(is_kept_session(other), other)

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

    def test_a_kept_step_reads_what_another_kept_step_made(self):
        """Each step of a kept run has a session of its own, and reads its
        run's earlier steps and the outputs kept from earlier runs: in process,
        as a preview, and staged for an isolated child."""
        from utk_curio.sandbox.util import staging

        made = parsers.save_to_duckdb(pd.DataFrame({"count": [3, 7, 5]}), session_id=new_session_id())
        step = new_session_id()

        self.assertEqual(parsers.load_artifact(made, session_id=step)["count"].tolist(), [3, 7, 5])
        _preview, total = parsers.load_tabular_preview_from_duckdb(made, 2, session_id=step)
        self.assertEqual(total, 3)
        with TemporaryDirectory() as scratch:
            staged = staging.stage_input(made, scratch, session_id=step)
            self.assertEqual(staged["kind"], "dataframe")
            self.assertTrue((Path(scratch) / staged["file"]).exists())

    def test_a_kept_step_and_a_sign_in_never_read_each_others_artifacts(self):
        from utk_curio.sandbox.util import staging

        kept_made = parsers.save_to_duckdb(pd.DataFrame({"a": [1]}), session_id=new_session_id())
        signed_in_made = parsers.save_to_duckdb(pd.DataFrame({"b": [2]}), session_id="a-sign-in-token")

        for art_id, session in ((kept_made, "a-sign-in-token"), (signed_in_made, new_session_id())):
            with self.assertRaises(KeyError):
                parsers.load_artifact(art_id, session_id=session)
            with self.assertRaises(KeyError):
                parsers.load_tabular_preview_from_duckdb(art_id, 2, session_id=session)
            with TemporaryDirectory() as scratch, self.assertRaises(KeyError):
                staging.stage_input(art_id, scratch, session_id=session)

    def test_store_keeps_a_pages_result_in_a_kept_session(self):
        """What a viewer's page made of a step only a browser runs is written
        as it came, an artifact of the kept session named."""
        session = new_session_id()
        layer = {"dataType": "geodataframe", "data": {"type": "FeatureCollection", "features": []}, "layerName": "a"}

        response = self.client.post("/artifact-sessions/store", json={"sessionId": session, "value": layer})

        self.assertEqual(response.status_code, 200, response.data)
        output = response.get_json()["output"]
        self.assertEqual(output["dataType"], "dict")
        self.assertEqual(parsers.load_artifact(output["path"], session_id=session), layer)
        described = self.client.post("/artifact-sessions/describe", json={"sessionIds": [session]})
        self.assertEqual(described.get_json()["sessions"][session]["ids"], [output["path"]])

    def test_store_refuses_a_sign_in_and_a_value_that_is_not_an_object(self):
        for body in (
            {"sessionId": "a-sign-in-token", "value": {"dataType": "geodataframe", "data": {}}},
            {"sessionId": new_session_id(), "value": [1, 2]},
            {},
        ):
            response = self.client.post("/artifact-sessions/store", json=body)
            self.assertEqual(response.status_code, 400, (body, response.data))

    def test_a_session_that_is_not_a_kept_runs_is_refused(self):
        signed_in = parsers.save_to_duckdb(pd.DataFrame({"a": [1]}), session_id="a-sign-in-token")
        for route in ("/artifact-sessions/describe", "/artifact-sessions/forget"):
            for body in ({"sessionIds": ["a-sign-in-token"]}, {"sessionIds": "kept-x"}, {}):
                response = self.client.post(route, json=body)
                self.assertEqual(response.status_code, 400, (route, body, response.data))
        self.assertEqual(parsers.load_from_duckdb(signed_in, session_id="a-sign-in-token")["a"].tolist(), [1])


if __name__ == "__main__":
    unittest.main()
