"""``/get`` reads a dataflow's saved output in place, from its owner's store.

The DuckDB artifact store is session-tagged: a row written by one sign-in is
invisible to the next (``parsers.load_from_duckdb``), and rows are pruned. That
is fine for a scratch artifact and wrong for a saved output, which the project
owns and a dashboard has to render for whoever opens the link. For a name the
dataflow saved, the backend names the file its owner's Data Catalog keeps
(``backend/app/projects/storage.saved_output_file``, sent as ``savedPath``);
these tests cover ``/get`` serving that file when the store cannot. Nothing is
copied into the shared data directory, and a copy found there is not read.

The names are the ones a save installs under: a dataset parquet keeps its
generated ``<ms>_<hex>_output.parquet`` name, while a computed dataset
installed from a JSON or parquet artifact may carry the bare artifact id, no
extension to go on. So the loader sniffs content rather than trusting the
name, and the tests pin both spellings.
"""

import json
import os
import shutil
import unittest
import zlib
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

from utk_curio.sandbox.app import app
from utk_curio.sandbox.util import parsers
from utk_curio.sandbox.util.db import init_db, release_connection


class SavedOutputInPlaceTestCase(unittest.TestCase):
    """Each test gets its own launch dir, so nothing leaks between them."""

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
        # A node's computed dataset in its owner's Data Catalog.
        self.dataset = Path(self._tmp.name) / ".curio" / "users" / "1" / "datasets" / "computed.df.n@1" / "data"
        self.dataset.mkdir(parents=True)
        # The DuckDB connection and its "schema is initialised" flag are module
        # globals keyed on one path. Drop them around each test so a fresh
        # launch dir really is fresh, and so the next test file does not inherit
        # a connection to a directory this one deleted.
        release_connection()
        self.addCleanup(release_connection)

    def init_store(self):
        """Create the artifacts table in this test's database."""
        init_db()

    def get(self, file_name, saved=None, **params):
        query = {"fileName": file_name, **params}
        if saved is not None:
            query["savedPath"] = str(saved)
        return self.client.get("/get", query_string=query)

    def installed(self, generated):
        """The run's dataset file *generated* and what is read beside it,
        moved into the node's computed dataset as a save installs them."""
        for made in self.data_dir.glob(generated + "*"):
            shutil.move(str(made), str(self.dataset / made.name))
        return self.dataset / generated

    # -- parquet -----------------------------------------------------------

    def test_a_dataset_parquet_is_served_with_its_object_columns_restored(self):
        frame = pd.DataFrame({"n": [1, 2], "tags": [{"a": 1}, {"b": 2}]})
        name = parsers.save_dataset_parquet(frame, "dataframe")
        self.assertIsNotNone(name, "save_dataset_parquet wrote nothing to save")
        saved = self.installed(name)

        response = self.get(name, saved)

        self.assertEqual(response.status_code, 200, response.data)
        body = response.get_json()
        self.assertEqual(body["dataType"], "dataframe")
        # The decode sidecar is what turns these back into objects; without it
        # they arrive as JSON strings and every consumer downstream sees text.
        self.assertEqual(body["data"]["tags"], [{"a": 1}, {"b": 2}])
        self.assertEqual(body["filename"], name)

    def test_a_geoparquet_output_is_served_as_a_geodataframe(self):
        frame = gpd.GeoDataFrame(
            {"name": ["a"]}, geometry=[Point(-87.63, 41.88)], crs="EPSG:4326",
        )
        name = parsers.save_dataset_parquet(frame, "geodataframe")

        body = self.get(name, self.installed(name)).get_json()

        self.assertEqual(body["dataType"], "geodataframe")
        self.assertEqual(body["data"]["type"], "FeatureCollection")

    def test_a_saved_frames_columns_come_in_the_order_its_code_wrote_them(self):
        # Another account reads a shared dataflow's saved outputs here, as
        # JSON, and a table shows its columns in the order of these keys.
        frame = pd.DataFrame({"Day": ["Winter solstice"], "From": ["8:46 AM"], "To": ["3:01 PM"], "Added": [25.6]})
        name = parsers.save_dataset_parquet(frame, "dataframe")

        body = self.get(name, self.installed(name)).get_json()

        self.assertEqual(list(body["data"]), ["Day", "From", "To", "Added"])

    def test_a_saved_features_properties_come_in_the_order_its_code_wrote_them(self):
        frame = gpd.GeoDataFrame(
            {"Without": [1.0], "With": [2.0], "Added": [1.0]},
            geometry=[Point(-73.95, 40.67)], crs="EPSG:4326",
        )
        name = parsers.save_dataset_parquet(frame, "geodataframe")

        body = self.get(name, self.installed(name)).get_json()

        self.assertEqual(list(body["data"]["features"][0]["properties"]), ["Without", "With", "Added"])

    def test_parquet_bytes_under_a_bare_artifact_id_are_detected_by_magic(self):
        # A computed dataset installed from an artifact can carry its id, with
        # no extension to go on.
        frame = pd.DataFrame({"n": [1, 2, 3]})
        generated = parsers.save_dataset_parquet(frame, "dataframe")
        art_id = "1700000000000_abcd1234"
        (self.dataset / art_id).write_bytes((self.data_dir / generated).read_bytes())

        body = self.get(art_id, self.dataset / art_id).get_json()

        self.assertEqual(body["dataType"], "dataframe")
        self.assertEqual(body["data"]["n"], [1, 2, 3])

    # -- json --------------------------------------------------------------

    def test_a_zlib_json_artifact_file_is_decompressed(self):
        art_id = "1700000000001_beef0001"
        payload = {"rows": [1, 2], "label": "naive"}
        (self.dataset / art_id).write_bytes(
            zlib.compress(json.dumps(payload).encode("utf-8"))
        )

        body = self.get(art_id, self.dataset / art_id).get_json()

        self.assertEqual(body["dataType"], "dict")
        self.assertEqual(body["data"], payload)

    def test_a_dicts_keys_come_in_the_order_its_code_wrote_them(self):
        art_id = "1700000000006_beef0006"
        (self.dataset / art_id).write_text(json.dumps({"zone": 1, "area": 2, "mean": 3}), encoding="utf-8")

        body = self.get(art_id, self.dataset / art_id).get_json()

        self.assertEqual(list(body["data"]), ["zone", "area", "mean"])

    def test_plain_json_bytes_are_served(self):
        art_id = "1700000000002_beef0002"
        (self.dataset / art_id).write_text(json.dumps([1, 2, 3]), encoding="utf-8")

        body = self.get(art_id, self.dataset / art_id).get_json()

        self.assertEqual(body["dataType"], "list")
        self.assertEqual([entry["data"] for entry in body["data"]], [1, 2, 3])

    # -- preview -----------------------------------------------------------

    def test_max_rows_previews_a_saved_frame(self):
        frame = pd.DataFrame({"n": list(range(10))})
        name = parsers.save_dataset_parquet(frame, "dataframe")

        body = self.get(name, self.installed(name), maxRows=2).get_json()

        self.assertTrue(body["preview"])
        self.assertEqual(body["previewRows"], 2)
        self.assertEqual(body["totalRows"], 10)
        self.assertEqual(len(body["data"]["n"]), 2)

    def test_a_frames_preview_keeps_the_order_its_code_wrote_its_columns_in(self):
        # A Data Pool shows its rows from this preview of the store's frame.
        self.init_store()
        frame = pd.DataFrame({"zone": ["a", "b", "c"], "area": [1.0, 2.0, 3.0], "mean": [4, 5, 6]})
        art_id = parsers.save_to_duckdb(frame, node_id="t")

        body = self.get(art_id, maxRows=2).get_json()

        self.assertTrue(body["preview"])
        self.assertEqual(list(body["data"]), ["zone", "area", "mean"])

    # -- precedence and refusals -------------------------------------------

    def test_a_duckdb_row_still_wins_over_the_saved_file(self):
        self.init_store()
        art_id = parsers.save_to_duckdb(pd.DataFrame({"n": [1]}), node_id="t")
        (self.dataset / art_id).write_text(json.dumps({"from": "file"}), encoding="utf-8")

        body = self.get(art_id, self.dataset / art_id).get_json()

        self.assertEqual(body["dataType"], "dataframe", "the saved file shadowed the store")

    def test_a_row_this_session_may_not_read_falls_back_to_the_saved_file(self):
        # The case the dashboard lives on: the artifact exists but belongs to
        # the session that produced it, and the caller is someone else.
        self.init_store()
        art_id = parsers.save_to_duckdb(
            pd.DataFrame({"n": [1]}), node_id="t", session_id="owner-token",
        )
        (self.dataset / art_id).write_text(json.dumps({"from": "file"}), encoding="utf-8")

        body = self.get(art_id, self.dataset / art_id, sessionId="another-token").get_json()

        self.assertEqual(body["data"], {"from": "file"})

    def test_a_copy_in_the_shared_data_directory_is_not_served(self):
        # What a project load once copied there under the output's name. With
        # no file named by the backend, the store's answer stands.
        self.init_store()
        art_id = parsers.save_to_duckdb(
            pd.DataFrame({"n": [1]}), node_id="t", session_id="owner-token",
        )
        (self.data_dir / art_id).write_text(json.dumps({"from": "a copy"}), encoding="utf-8")

        response = self.get(art_id, sessionId="another-token")

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.get_json()["error"], "KeyError")
        self.assertNotIn("a copy", response.get_data(as_text=True))

    def test_names_that_are_not_one_safe_component_read_nothing_off_disk(self):
        outside = Path(self._tmp.name) / "secret.json"
        outside.write_text(json.dumps({"tell": "no-one"}), encoding="utf-8")

        for name in ("../secret.json", "a/b", ".", "..", "sub/../secret.json"):
            with self.subTest(name=name):
                response = self.get(name)
                self.assertEqual(response.status_code, 500, name)
                # The error echoes the name it was given; what must never
                # appear is the file's contents.
                self.assertNotIn("no-one", response.get_data(as_text=True))

    def test_a_name_with_no_row_and_no_file_reports_what_the_store_said(self):
        # The saved file must not rewrite the store's diagnosis. With a
        # database present and no such row that is the KeyError this route has
        # always returned; with no database at all it is the IO error, which
        # would otherwise be replaced by a misleading "no artifact with id".
        self.init_store()
        parsers.save_to_duckdb(pd.DataFrame({"n": [1]}), node_id="t")

        response = self.get("1700000000003_beef0003", self.dataset / "1700000000003_beef0003")

        self.assertEqual(response.status_code, 500)
        body = response.get_json()
        self.assertEqual(body["error"], "KeyError")
        self.assertIn("No artifact with id", body["message"])

    def test_a_saved_file_is_served_when_there_is_no_database_at_all(self):
        # A viewer's first read in a fresh container: nothing has executed, so
        # the DuckDB file does not exist yet and connecting raises rather than
        # missing a row.
        art_id = "1700000000005_beef0005"
        (self.dataset / art_id).write_text(json.dumps({"from": "file"}), encoding="utf-8")
        self.assertFalse((self.data_dir / "curio_data.duckdb").exists())

        body = self.get(art_id, self.dataset / art_id).get_json()

        self.assertEqual(body["data"], {"from": "file"})

    def test_bytes_that_decode_as_nothing_are_reported_missing(self):
        self.init_store()
        art_id = "1700000000004_beef0004"
        (self.dataset / art_id).write_bytes(b"\x00\x01 not json, not parquet")

        response = self.get(art_id, self.dataset / art_id)

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.get_json()["error"], "KeyError")


if __name__ == "__main__":
    unittest.main()
