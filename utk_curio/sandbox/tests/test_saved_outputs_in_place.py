"""A dataflow's saved output is read in place, from the file its owner's
Data Catalog keeps.

The store is session-tagged, so after a reopen under a new sign-in it cannot
serve a saved output. The backend then names the file the owner's store holds
for it (``projects/storage.saved_output_file``): ``savedPath`` on ``/get`` and
``/raster``, ``saved_paths`` on ``/exec``. These pin that the sandbox reads that
file where it is, with no copy in the shared data directory, in process and
for an isolated child, whose staging links the file and adds no store row.

Each test builds a Data Catalog folder as the installer lays one out
(``computed.<dataflow>.<node>@1/data/``) and leaves the shared data directory
holding nothing of the output.
"""

import json
import os
import shutil
import textwrap
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import pandas as pd

from utk_curio.sandbox.app import app
from utk_curio.sandbox.util import parsers, staging
from utk_curio.sandbox.util.db import get_read_connection, init_db, release_connection

REPO = Path(__file__).resolve().parents[3]
RASTER = REPO / "utk_curio" / "backend" / "tests" / "test_frontend" / "data" / "autark_raster_utm16n.tif"
NAME = "1700000000010_cafe0010"


class SavedOutputTestCase(unittest.TestCase):
    """A launch directory of its own, a store, and an empty shared data dir."""

    def setUp(self):
        self.client = app.test_client()
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        env = mock.patch.dict(os.environ, {
            "CURIO_LAUNCH_CWD": self._tmp.name,
            "CURIO_SHARED_DATA": "./.curio/data/",
            "CURIO_ISOLATION": "off",
        })
        env.start()
        self.addCleanup(env.stop)
        self.data_dir = self.root / ".curio" / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.dataset = self.root / ".curio" / "users" / "1" / "datasets" / "computed.df.node@1" / "data"
        self.dataset.mkdir(parents=True)
        release_connection()
        self.addCleanup(release_connection)

    def saved_frame(self, frame, kind="dataframe"):
        """A frame saved as a node run saves it, moved into the dataset folder
        with its ``.decode.json``: the shared data directory keeps nothing."""
        written = parsers.save_dataset_parquet(frame, kind)
        self.assertIsNotNone(written)
        for name in (written, written + ".decode.json"):
            if (self.data_dir / name).is_file():
                os.replace(self.data_dir / name, self.dataset / name)
        return self.dataset / written

    def assert_no_copy_in_the_shared_data_directory(self):
        top = [p.name for p in self.data_dir.iterdir() if p.is_file() and not p.name.startswith("curio_data.duckdb")]
        self.assertEqual(top, [], "a read copied the saved output into the shared data directory")

    def get(self, saved_path, **params):
        return self.client.get("/get", query_string={
            "fileName": NAME, "sessionId": "new-sign-in", "savedPath": str(saved_path), **params,
        })

    def store_rows(self):
        con = get_read_connection()
        try:
            return con.execute("SELECT count(*) FROM artifacts").fetchone()[0]
        finally:
            con.close()


class TheGetRouteTest(SavedOutputTestCase):
    def test_a_saved_table_is_served_from_its_dataset_with_its_object_columns(self):
        path = self.saved_frame(pd.DataFrame({"n": [1, 2], "tags": [{"a": 1}, {"b": 2}]}))

        response = self.get(path)

        self.assertEqual(response.status_code, 200, response.data[:300])
        body = response.get_json()
        self.assertEqual(body["dataType"], "dataframe")
        self.assertEqual(body["data"]["tags"], [{"a": 1}, {"b": 2}])
        self.assertEqual(body["filename"], NAME)
        self.assert_no_copy_in_the_shared_data_directory()

    def test_a_preview_reads_the_saved_table_in_place(self):
        path = self.saved_frame(pd.DataFrame({"n": list(range(10))}))

        body = self.get(path, maxRows=2).get_json()

        self.assertEqual((body["previewRows"], body["totalRows"]), (2, 10))
        self.assertEqual(body["data"]["n"], [0, 1])

    def test_it_is_served_when_there_is_no_database_at_all(self):
        path = self.saved_frame(pd.DataFrame({"n": [5]}))
        self.assertFalse((self.data_dir / "curio_data.duckdb").exists())

        body = self.get(path).get_json()

        self.assertEqual(body["data"]["n"], [5])

    def test_the_owning_sessions_row_still_wins(self):
        init_db()
        art_id = parsers.save_to_duckdb(pd.DataFrame({"n": [1]}), node_id="t", session_id="owner")
        path = self.saved_frame(pd.DataFrame({"n": [99]}))

        body = self.client.get("/get", query_string={
            "fileName": art_id, "sessionId": "owner", "savedPath": str(path),
        }).get_json()

        self.assertEqual(body["data"]["n"], [1])

    def test_a_saved_bundle_is_served_as_its_tuple_from_its_dataset_folder(self):
        parts = self.dataset / "parts"
        parts.mkdir()
        shutil.move(str(self.saved_frame(pd.DataFrame({"n": [1, 2]}))), parts / "00_dataframe.parquet")
        (parts / "01_int.json").write_text(json.dumps({"value": 7}), encoding="utf-8")
        bundle = self.dataset / "bundle.json"
        bundle.write_text(json.dumps({
            "version": 1, "parentArtifactId": NAME, "container": "tuple",
            "parts": [
                {"index": 0, "kind": "dataframe", "format": "parquet", "file": "data/parts/00_dataframe.parquet"},
                {"index": 1, "kind": "int", "format": "json", "file": "data/parts/01_int.json"},
            ],
        }), encoding="utf-8")

        value = parsers.load_artifact(NAME, session_id="new-sign-in", saved_paths={NAME: {"path": str(bundle)}})

        self.assertIsInstance(value, tuple)
        self.assertEqual(value[0]["n"].tolist(), [1, 2])
        self.assertEqual(value[1], 7)
        self.assert_no_copy_in_the_shared_data_directory()

    def test_a_saved_path_that_is_gone_reads_as_missing(self):
        init_db()

        response = self.get(self.dataset / "gone.parquet")

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.get_json()["error"], "KeyError")


class TheRasterRouteTest(SavedOutputTestCase):
    def test_a_saved_raster_is_served_from_its_dataset(self):
        from rasterio.io import MemoryFile

        saved = self.dataset / "raster.tif"
        shutil.copyfile(RASTER, saved)

        response = self.client.get("/raster", query_string={
            "fileName": NAME, "sessionId": "new-sign-in", "savedPath": str(saved),
        })

        self.assertEqual(response.status_code, 200, response.get_data()[:300])
        meta = json.loads(response.headers["X-Curio-Raster"])
        self.assertEqual((meta["width"], meta["height"], meta["crs"]), (40, 30, "EPSG:32616"))
        with MemoryFile(response.get_data()) as memory, memory.open() as served:
            self.assertEqual((served.width, served.height), (40, 30))
        self.assert_no_copy_in_the_shared_data_directory()


class AnInputTest(SavedOutputTestCase):
    def setUp(self):
        super().setUp()
        init_db()
        self.frame = pd.DataFrame({"n": [1, 2, 3], "tags": [["a"], ["b"], ["c"]]})

    def test_a_node_in_process_reads_its_saved_input_in_place(self):
        path = self.saved_frame(self.frame)

        response = self.client.post("/exec", json={
            "code": textwrap.indent("return int(input_0['n'].sum()) + len(input_0['tags'][0])\n", "    "),
            "file_path": NAME,
            "nodeType": "DATA_TRANSFORMATION",
            "dataType": "dataframe",
            "session_id": "new-sign-in",
            "saved_paths": {NAME: {"path": str(path), "dataType": "dataframe"}},
        })

        body = response.get_json()
        self.assertEqual(body["stderr"], "")
        self.assertEqual(parsers.load_from_duckdb(body["output"]["path"]), 7)
        self.assert_no_copy_in_the_shared_data_directory()

    def test_staging_links_the_saved_file_and_adds_no_store_row(self):
        path = self.saved_frame(self.frame)
        scratch = self.root / "scratch"
        scratch.mkdir()
        rows = self.store_rows()

        spec = staging.stage_input(
            NAME, scratch, session_id="new-sign-in",
            saved_paths={NAME: {"path": str(path), "dataType": "dataframe"}},
        )

        self.assertEqual(self.store_rows(), rows, "staging stored the saved output again")
        self.assertEqual(spec["kind"], "dataframe")
        self.assertEqual(spec["encoded_object_columns"], ["tags"])
        self.assertTrue(os.path.samefile(scratch / spec["file"], path), "the input was copied, not linked")

    def test_staging_a_saved_bundle_links_each_part(self):
        parts = self.dataset / "parts"
        parts.mkdir()
        frame_part = parts / "00_dataframe.parquet"
        shutil.move(str(self.saved_frame(pd.DataFrame({"n": [1]}))), frame_part)
        (parts / "01_str.json").write_text(json.dumps({"value": "label"}), encoding="utf-8")
        bundle = self.dataset / "bundle.json"
        bundle.write_text(json.dumps({
            "version": 1, "parentArtifactId": NAME, "container": "list",
            "parts": [
                {"index": 0, "kind": "dataframe", "format": "parquet", "file": "data/parts/00_dataframe.parquet"},
                {"index": 1, "kind": "str", "format": "json", "file": "data/parts/01_str.json"},
            ],
        }), encoding="utf-8")
        scratch = self.root / "scratch"
        scratch.mkdir()
        rows = self.store_rows()

        spec = staging.stage_input(
            NAME, scratch, session_id="new-sign-in",
            saved_paths={NAME: {"path": str(bundle), "dataType": "outputs"}},
        )

        self.assertEqual(self.store_rows(), rows)
        self.assertEqual((spec["kind"], spec["container"]), ("sequence", "list"))
        self.assertTrue(os.path.samefile(scratch / spec["items"][0]["file"], frame_part))
        self.assertEqual(spec["items"][1], {"kind": "str", "value": "label"})


if __name__ == "__main__":
    unittest.main()
