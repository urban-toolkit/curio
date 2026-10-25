"""A run that is not kept reads its dataflow's kept outputs under the sessions that made them.

The owner's runs of a saved dataflow are kept, each in a kept session of its
own (``common/kept_sessions.py``), and a sign-in's session cannot read a kept
artifact. A run that is not kept can still name one as its input: a tab's
play below a step only the browser makes reads that step's layers, stored
under the tab's sign-in, beside an output the owner's run on the server kept.
The backend names, for each such input, the kept session that made it
(``backend/app/execution/node_exec.resolve_kept_inputs``), handed over in
``saved_paths`` as ``{"session"}`` and taken only when it is a kept session
(``parsers.shape_saved_paths``). These pin that both execution paths read it
there: in-process (``/exec``, ``parsers.load_artifact``) and isolated
(``staging.stage_input``, which stages inputs for a forked child).
"""

import os
import textwrap
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import pandas as pd

from utk_curio.common.kept_sessions import new_session_id
from utk_curio.sandbox.app import app
from utk_curio.sandbox.util import parsers, staging
from utk_curio.sandbox.util.db import init_db, release_connection


class ExecReadsKeptInputTestCase(unittest.TestCase):
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
        self.frame = pd.DataFrame({"n": [1, 2, 3], "label": ["a", "b", "c"]})

    def exec_on(self, file_path, data_type, code, saved_paths=None):
        response = self.client.post("/exec", json={
            "code": textwrap.indent(code, "    "),
            "file_path": file_path,
            "nodeType": "DATA_TRANSFORMATION",
            "dataType": data_type,
            "session_id": "the-tabs-sign-in",
            "saved_paths": saved_paths or {},
        })
        self.assertEqual(response.status_code, 200, response.data)
        return response.get_json()

    def kept_output(self, value=None):
        """An output a kept run made: its artifact id and its session."""
        session = new_session_id()
        art_id = parsers.save_to_duckdb(self.frame if value is None else value, node_id="a", session_id=session)
        return art_id, session

    def test_a_granted_kept_output_is_an_input(self):
        art_id, session = self.kept_output()

        body = self.exec_on(art_id, "dataframe", "return int(input_0['n'].sum())\n",
                            {art_id: {"session": session}})

        self.assertEqual(body["stderr"], "")
        self.assertEqual(parsers.load_from_duckdb(body["output"]["path"]), 6)

    def test_without_the_grant_a_kept_output_is_not_an_input(self):
        art_id, _session = self.kept_output()

        body = self.exec_on(art_id, "dataframe", "return int(input_0['n'].sum())\n")

        self.assertIn("No artifact with id", body["stderr"])
        self.assertFalse(body["output"]["path"])

    def test_a_grant_that_names_no_kept_session_is_dropped(self):
        """Only a kept session is taken: one that names another sign-in's
        session reads nothing of that sign-in's."""
        art_id = parsers.save_to_duckdb(self.frame, node_id="a", session_id="someone-elses-sign-in")
        grant = {art_id: {"session": "someone-elses-sign-in"}}

        body = self.exec_on(art_id, "dataframe", "return int(input_0['n'].sum())\n", grant)

        self.assertEqual(parsers.shape_saved_paths(grant), {})
        self.assertIn("No artifact with id", body["stderr"])

    def test_the_shape_keeps_a_saved_file_and_a_kept_session(self):
        session = new_session_id()

        shaped = parsers.shape_saved_paths({
            "saved": {"path": "/store/saved.parquet", "dataType": "dataframe"},
            "kept": {"session": session},
            "neither": {"dataType": "dataframe"},
        })

        self.assertEqual(shaped, {
            "saved": {"path": "/store/saved.parquet", "dataType": "dataframe"},
            "kept": {"session": session, "dataType": ""},
        })

    def test_a_node_with_several_inputs_reads_its_own_and_a_granted_one(self):
        """As below a step only the browser makes: one input the tab's own
        session made, one the owner's run kept."""
        theirs, session = self.kept_output()
        mine = parsers.save_to_duckdb(self.frame, node_id="layers", session_id="the-tabs-sign-in")

        body = self.exec_on(
            [{"path": mine, "dataType": "dataframe"}, {"path": theirs, "dataType": "dataframe"}],
            "outputs", "return int(input_0['n'].sum() + input_1['n'].sum())\n",
            {theirs: {"session": session}},
        )

        self.assertEqual(body["stderr"], "")
        self.assertEqual(parsers.load_from_duckdb(body["output"]["path"]), 12)

    def test_staging_for_an_isolated_child_reads_under_the_grant(self):
        art_id, session = self.kept_output()
        scratch = Path(self._tmp.name) / "scratch"
        scratch.mkdir()

        spec = staging.stage_input(art_id, scratch, session_id="the-tabs-sign-in",
                                   saved_paths={art_id: {"session": session, "dataType": ""}})

        self.assertEqual(spec["kind"], "dataframe")
        self.assertEqual(int(pd.read_parquet(scratch / spec["file"])["n"].sum()), 6)

    def test_staging_a_granted_tuple_stages_its_parts_under_the_grant(self):
        art_id, session = self.kept_output((self.frame, self.frame.head(1)))
        scratch = Path(self._tmp.name) / "scratch"
        scratch.mkdir()

        spec = staging.stage_input(art_id, scratch, session_id="the-tabs-sign-in",
                                   saved_paths={art_id: {"session": session, "dataType": ""}})

        self.assertEqual(spec["kind"], "sequence")
        sums = [int(pd.read_parquet(scratch / item["file"])["n"].sum()) for item in spec["items"]]
        self.assertEqual(sums, [6, 1])

    def test_staging_without_the_grant_reads_nothing_of_a_kept_run(self):
        art_id, _session = self.kept_output()
        scratch = Path(self._tmp.name) / "scratch"
        scratch.mkdir()

        with self.assertRaises(KeyError):
            staging.stage_input(art_id, scratch, session_id="the-tabs-sign-in")


if __name__ == "__main__":
    unittest.main()
