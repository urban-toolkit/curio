"""``/exec`` reads an upstream output the way ``/get`` does (#408, #407).

A saved dataflow restores each node's output by name, and a project load copies
the durable file behind each one into the shared data directory
(``backend/app/projects/storage.hydrate_outputs``). ``/get`` already serves
those files when the session-tagged store cannot (``test_get_shared_file_fallback``).
``/exec`` did not: its input load asked the store only, so after a reopen under
a new sign-in, running a downstream node failed with "No artifact with id" for
an upstream output the canvas was showing as done. The only way through was to
re-run the whole chain, which is the memory pressure #408 describes.

These pin the same rule for the two execution paths: in-process (``/exec``)
and isolated (``staging.stage_input``, which stages inputs for a forked child).
"""

import os
import textwrap
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import pandas as pd

from utk_curio.sandbox.app import app
from utk_curio.sandbox.util import parsers, staging
from utk_curio.sandbox.util.db import init_db, release_connection

class ExecReadsHydratedInputTestCase(unittest.TestCase):
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
        self.data_dir = Path(self._tmp.name) / ".curio" / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        release_connection()
        self.addCleanup(release_connection)
        init_db()
        self.frame = pd.DataFrame({"n": [1, 2, 3], "label": ["a", "b", "c"]})

    def exec_on(self, file_path, session_id):
        response = self.client.post("/exec", json={
            "code": textwrap.indent("return int(input_0['n'].sum())\n", "    "),
            "file_path": file_path,
            "nodeType": "DATA_TRANSFORMATION",
            "dataType": "dataframe",
            "session_id": session_id,
        })
        self.assertEqual(response.status_code, 200, response.data)
        return response.get_json()

    def hydrated_copy_of_another_sessions_output(self):
        """An output a previous sign-in produced, hydrated by a project load."""
        art_id = parsers.save_to_duckdb(self.frame, node_id="loader", session_id="old-session")
        generated = parsers.save_dataset_parquet(self.frame, "dataframe")
        (self.data_dir / art_id).write_bytes((self.data_dir / generated).read_bytes())
        return art_id

    def test_a_hydrated_dataset_parquet_is_an_input(self):
        name = parsers.save_dataset_parquet(self.frame, "dataframe")

        body = self.exec_on(name, "next-session")

        self.assertEqual(body["stderr"], "")
        self.assertTrue(body["output"]["path"])

    def test_another_sessions_output_is_read_from_its_hydrated_copy(self):
        art_id = self.hydrated_copy_of_another_sessions_output()

        body = self.exec_on(art_id, "next-session")

        self.assertEqual(body["stderr"], "")
        self.assertEqual(parsers.load_from_duckdb(body["output"]["path"]), 6)

    def test_the_owning_session_still_reads_the_store(self):
        art_id = parsers.save_to_duckdb(self.frame, node_id="loader", session_id="s1")

        body = self.exec_on(art_id, "s1")

        self.assertEqual(body["stderr"], "")
        self.assertEqual(parsers.load_from_duckdb(body["output"]["path"]), 6)

    def test_a_name_that_is_nowhere_is_still_an_error(self):
        body = self.exec_on("1700000000000_deadbeef", "next-session")

        self.assertIn("No artifact with id", body["stderr"])
        self.assertFalse(body["output"]["path"])

    def test_staging_for_an_isolated_child_uses_the_hydrated_copy(self):
        art_id = self.hydrated_copy_of_another_sessions_output()
        scratch = Path(self._tmp.name) / "scratch"
        scratch.mkdir()

        spec = staging.stage_input(art_id, scratch, session_id="next-session")

        self.assertEqual(spec["kind"], "dataframe")
        staged = pd.read_parquet(scratch / spec["file"])
        self.assertEqual(int(staged["n"].sum()), 6)
