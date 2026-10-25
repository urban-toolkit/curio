"""A node's imports reach the nodes after it, whatever session tags its artifacts.

An upstream node's ``import numpy as np`` is remembered for the nodes after it
(#158). An owner's run of a saved dataflow tags each node's artifacts with a
kept session of its own (``backend/app/execution/node_exec._kept_run``), so
the backend names the session imports are remembered under apart, as
``imports_session``: the caller's own.
"""

import os
import textwrap
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from utk_curio.common.kept_sessions import new_session_id
from utk_curio.sandbox.app import app
from utk_curio.sandbox.util.db import init_db, release_connection
from utk_curio.sandbox.util.parsers import load_from_duckdb


class ImportsAcrossKeptSessionsTestCase(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        env = mock.patch.dict(os.environ, {
            "CURIO_LAUNCH_CWD": self._tmp.name,
            "CURIO_SHARED_DATA": "./.curio/data/",
            "CURIO_ISOLATION": "off",
        })
        env.start()
        self.addCleanup(env.stop)
        (Path(self._tmp.name) / ".curio" / "data").mkdir(parents=True, exist_ok=True)
        release_connection()
        self.addCleanup(release_connection)
        init_db()

    def run_node(self, code, session_id, imports_session):
        response = self.client.post("/exec", json={
            "code": textwrap.indent(code, "    "),
            "file_path": "",
            "nodeType": "DATA_TRANSFORMATION",
            "dataType": "",
            "session_id": session_id,
            "imports_session": imports_session,
        })
        self.assertEqual(response.status_code, 200, response.data)
        return response.get_json()

    def test_an_upstream_import_reaches_a_downstream_node_in_another_kept_session(self):
        upstream = self.run_node("import statistics as stats_158\nreturn 1\n", new_session_id(), "alice-token")
        self.assertFalse(upstream["stderr"], upstream["stderr"])

        downstream = self.run_node("return stats_158.mean([1, 2, 3])\n", new_session_id(), "alice-token")

        self.assertFalse(downstream["stderr"], downstream["stderr"])
        self.assertEqual(load_from_duckdb(downstream["output"]["path"]), 2)

    def test_another_callers_imports_do_not_reach_it(self):
        self.run_node("import statistics as stats_other\nreturn 1\n", new_session_id(), "alice-token")

        downstream = self.run_node("return stats_other.mean([1, 2, 3])\n", new_session_id(), "bob-token")

        self.assertIn("NameError", downstream["stderr"])


if __name__ == "__main__":
    unittest.main()
