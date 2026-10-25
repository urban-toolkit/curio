"""``/artifacts/wraps`` names what a persisted wrapper names.

A run whose input is a stored ``{'dataType': 'outputs', 'data': [refs]}``
wrapper reads each output it names too (``worker._expand_outputs_wrapper``),
from the store, or, once the row is gone, from the saved output's own file
(``parsers.load_artifact``). The backend asks for those names before it
decides the run's session and the sessions it names for the run's inputs
(``backend/app/execution/node_exec``).
"""

import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import pandas as pd

from utk_curio.sandbox.app import app
from utk_curio.sandbox.util.db import init_db, release_connection
from utk_curio.sandbox.util.parsers import save_to_duckdb

A, B = "1700000000000_aaaaaaaa", "1700000000000_bbbbbbbb"
WRAPPER = {"dataType": "outputs", "data": [
    {"path": A, "dataType": "dataframe"},
    B,
    {"dataType": "geodataframe", "data": {"type": "FeatureCollection", "features": []}},
    {"path": A, "dataType": "dataframe"},
]}


class ArtifactsWrapsTestCase(unittest.TestCase):
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

    def wraps(self, art_id, **params):
        response = self.client.get("/artifacts/wraps", query_string={"fileName": art_id, **params})
        self.assertEqual(response.status_code, 200, response.data)
        return response.get_json()["wraps"]

    def saved_file(self, value):
        path = Path(self._tmp.name) / "saved.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        return str(path)

    def test_a_wrapper_names_the_outputs_it_holds_and_no_inline_value(self):
        wrapper = save_to_duckdb(WRAPPER, node_id="w", session_id="alice-token")

        self.assertEqual(self.wraps(wrapper), [A, B])

    def test_anything_else_names_nothing(self):
        table = save_to_duckdb(pd.DataFrame({"n": [1]}), node_id="n")
        a_dict = save_to_duckdb({"dataType": "dict", "data": [A]}, node_id="n")
        a_list = save_to_duckdb([A], node_id="n")

        for art_id in (table, a_dict, a_list, "1700000000000_cccccccc"):
            with self.subTest(art_id=art_id):
                self.assertEqual(self.wraps(art_id), [])

    def test_with_no_row_the_saved_file_a_run_reads_in_its_place_is_read(self):
        gone = "1700000000000_dddddddd"

        self.assertEqual(self.wraps(gone, savedPath=self.saved_file(WRAPPER)), [A, B])
        self.assertEqual(self.wraps(gone, savedPath=self.saved_file({"dataType": "dict", "data": [A]})), [])

    def test_a_call_names_an_artifact(self):
        self.assertEqual(self.client.get("/artifacts/wraps").status_code, 400)


if __name__ == "__main__":
    unittest.main()
