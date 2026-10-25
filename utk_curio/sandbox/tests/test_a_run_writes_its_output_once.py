"""A node's run writes its output once: its artifact in the store.

With Save on, a Python node's table used to be encoded a second time, as
``<ms>_<hex>_output.parquet`` at the top of the shared data directory, named in
the reply as ``dataset`` for the Data Catalog to link; an isolated run copied
the child's file there instead. The Data Catalog now links the artifact's own
file (``backend/app/datasets/install/bundle.install_node_output``), so a run
writes nothing else and its reply names only its artifact.

A JavaScript node's value is JSON in the store. With Save on, a table it
returns is stored once more as a frame artifact of its own, which the reply
names as ``dataset``: a Parquet the Data Catalog links as it links a Python
node's.
"""

import json
import os
import textwrap
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from utk_curio.sandbox.app import app
from utk_curio.sandbox.util.db import init_db, is_store_file, release_connection
from utk_curio.sandbox.util.parsers import load_from_duckdb


class ARunWritesItsOutputOnceTestCase(unittest.TestCase):
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

    def files_beside_the_store(self):
        """The files at the top of the shared data directory that are not the
        store's database: where a run's second copy used to go."""
        return sorted(
            path.name for path in self.data_dir.iterdir()
            if path.is_file() and not is_store_file(path.name)
        )

    def test_a_python_node_with_save_on_writes_only_its_artifact(self):
        response = self.client.post("/exec", json={
            "code": textwrap.indent(
                "import pandas as pd\n"
                "return pd.DataFrame({'n': [1, 2], 'tags': [['a'], ['b', 'c']]})\n",
                "    ",
            ),
            "file_path": "",
            "nodeType": "DATA_TRANSFORMATION",
            "dataType": "",
            "session_id": "session-a",
            "save_dataset": True,
        })
        self.assertEqual(response.status_code, 200, response.data)
        body = response.get_json()
        self.assertFalse(body["stderr"], body["stderr"])

        output = body["output"]
        self.assertEqual(set(output), {"path", "dataType"})
        self.assertTrue((self.data_dir / "artifacts" / f"{output['path']}.parquet").is_file())
        self.assertEqual(self.files_beside_the_store(), [])

    def test_a_javascript_nodes_saved_table_is_a_frame_artifact_of_its_own(self):
        """The value a JS node returns, here as Node.js would hand it back."""
        from utk_curio.sandbox.app import worker

        records = [{"name": "a", "n": 1, "tags": ["x"]}, {"name": "b", "n": 2, "tags": ["y", "z"]}]
        ran = (json.dumps({"success": True, "value": records, "logs": []}), [], [])
        with mock.patch.object(worker, "run_js_script", return_value=ran):
            result = worker.execute_js_code(
                "return rows;", "", "JS_COMPUTATION", "",
                launch_dir=self._tmp.name, session_id="session-a", save_dataset=True,
            )

        output = result["output"]
        self.assertEqual(load_from_duckdb(output["path"], session_id="session-a"), records)
        self.assertTrue((self.data_dir / "artifacts" / f"{output['dataset']}.parquet").is_file())
        stored = load_from_duckdb(output["dataset"], session_id="session-a")
        self.assertEqual(stored["name"].tolist(), ["a", "b"])
        self.assertEqual(stored["tags"].tolist(), [["x"], ["y", "z"]])
        self.assertEqual(self.files_beside_the_store(), [])


if __name__ == "__main__":
    unittest.main()
