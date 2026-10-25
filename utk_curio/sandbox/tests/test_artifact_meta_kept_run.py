"""``/artifact-meta`` says whether a kept run made an artifact, never its session.

The backend asks before it hands a dataflow's saved output name to a kept
session (``backend/app/execution/node_exec._kept_run``): the sandbox lets a
kept session read every kept run's artifacts, so a name another kept run made
must not reach one.
"""

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import pandas as pd

from utk_curio.common.kept_sessions import new_session_id
from utk_curio.sandbox.app import app
from utk_curio.sandbox.util.db import init_db, release_connection
from utk_curio.sandbox.util.parsers import save_to_duckdb


class ArtifactMetaKeptRunTestCase(unittest.TestCase):
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

    def meta(self, art_id):
        response = self.client.get("/artifact-meta", query_string={"fileName": art_id})
        self.assertEqual(response.status_code, 200, response.data)
        return response.get_json()

    def test_a_kept_runs_artifact_says_so_and_no_other_does(self):
        session = new_session_id()
        kept = save_to_duckdb(pd.DataFrame({"n": [1]}), node_id="n", session_id=session)
        signed_in = save_to_duckdb(pd.DataFrame({"n": [1]}), node_id="n", session_id="alice-token")
        untagged = save_to_duckdb(pd.DataFrame({"n": [1]}), node_id="n")

        self.assertIs(self.meta(kept)["keptRun"], True)
        self.assertIs(self.meta(signed_in)["keptRun"], False)
        self.assertIs(self.meta(untagged)["keptRun"], False)
        self.assertNotIn(session, str(self.meta(kept)))
        self.assertNotIn("alice-token", str(self.meta(signed_in)))


if __name__ == "__main__":
    unittest.main()
