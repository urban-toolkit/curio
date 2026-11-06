"""Rows a node made in the browser are kept as a frame artifact (#1333).

A node that hands on rows as they are, ``{data, dataType}``, reaches a chart,
which reads them in the browser, but never a Python or JavaScript node, whose
run reads only a stored output. ``/artifacts/store`` keeps such rows as a
run keeps its output, under the sign-in's session:

- a dataframe in either encoding a node hands on (column arrays, as Curio
  writes a frame, or a row map), each column with its own type;
- a geodataframe, a FeatureCollection, in the coordinate system it names;
- read back as ``input_0`` in process and staged for an isolated child.
"""

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from utk_curio.sandbox.app import app
from utk_curio.sandbox.util import parsers
from utk_curio.sandbox.util.db import init_db, release_connection

SESSION = "a-sign-in-token"

COLUMNS = {"name": ["Alpha", "Bravo", "Charlie", "Foxtrot"], "height": [30, 24, 18, 18]}
ROW_MAP = {"name": {"0": "Alpha", "3": "Delta"}, "height": {"0": 30, "3": 12}}
SQUARE = {
    "type": "FeatureCollection",
    "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::3395"}},
    "features": [{
        "type": "Feature",
        "properties": {"zone": "square", "name": "inside"},
        "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]},
    }],
}

READ_CODE = (
    "    return f\"{type(input_0).__name__} {len(input_0)} {input_0['height'].dtype.kind} "
    "{sorted(input_0['name'])}\"\n"
)


class StoredRowsTestCase(unittest.TestCase):
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

    def _store(self, value, session=SESSION):
        response = self.client.post("/artifacts/store", json={
            "sessionId": session, "value": value, "nodeType": "curio.builtin/spatial-join",
        })
        self.assertEqual(response.status_code, 200, response.data)
        return response.get_json()["output"]

    def test_column_arrays_are_kept_as_a_frame_with_its_column_types(self):
        output = self._store({"dataType": "dataframe", "data": COLUMNS})

        self.assertEqual(output["dataType"], "dataframe")
        frame = parsers.load_artifact(output["path"], session_id=SESSION)
        self.assertEqual(frame.to_dict(orient="list"), COLUMNS)
        self.assertEqual(frame["height"].dtype.kind, "i", frame.dtypes)

    def test_a_row_map_is_kept_with_its_rows(self):
        output = self._store({"dataType": "dataframe", "data": ROW_MAP})

        frame = parsers.load_artifact(output["path"], session_id=SESSION)
        self.assertEqual(frame["name"].tolist(), ["Alpha", "Delta"])
        self.assertEqual(frame["height"].tolist(), [30, 12])

    def test_a_feature_collection_is_kept_as_a_geodataframe_in_its_coordinate_system(self):
        import geopandas as gpd

        output = self._store({"dataType": "geodataframe", "data": SQUARE})

        self.assertEqual(output["dataType"], "geodataframe")
        frame = parsers.load_artifact(output["path"], session_id=SESSION)
        self.assertIsInstance(frame, gpd.GeoDataFrame)
        self.assertEqual(frame["zone"].tolist(), ["square"])
        self.assertEqual(frame.crs.to_epsg(), 3395)

    def test_the_rows_are_the_sign_ins_own(self):
        output = self._store({"dataType": "dataframe", "data": COLUMNS})

        with self.assertRaises(KeyError):
            parsers.load_artifact(output["path"], session_id="another-sign-in")

    def test_what_is_not_rows_is_refused(self):
        from utk_curio.common.kept_sessions import new_session_id

        for body in (
            {"sessionId": SESSION, "value": {"dataType": "dict", "data": {"a": 1}}},
            {"sessionId": SESSION, "value": {"dataType": "outputs", "data": []}},
            {"sessionId": SESSION, "value": {"dataType": "geodataframe", "data": {"rows": []}}},
            {"sessionId": SESSION, "value": [1, 2]},
            {"sessionId": "", "value": {"dataType": "dataframe", "data": COLUMNS}},
            {"value": {"dataType": "dataframe", "data": COLUMNS}},
            {"sessionId": new_session_id(), "value": {"dataType": "dataframe", "data": COLUMNS}},
        ):
            response = self.client.post("/artifacts/store", json=body)
            self.assertEqual(response.status_code, 400, (body, response.data))

    def test_a_viewers_page_result_of_unnamed_rows_is_kept_as_a_frame(self):
        """A dashboard viewer's run keeps what the page made of a Spatial Join
        in a kept session (``/artifact-sessions/store``): a frame, as above,
        so a Python step after it reads a GeoDataFrame and not the envelope.
        An Autark layer, which its envelope names, is kept as it came
        (``test_kept_sessions.py``)."""
        import geopandas as gpd
        from utk_curio.common.kept_sessions import new_session_id

        session = new_session_id()
        response = self.client.post("/artifact-sessions/store", json={
            "sessionId": session, "value": {"dataType": "geodataframe", "data": SQUARE},
        })

        self.assertEqual(response.status_code, 200, response.data)
        output = response.get_json()["output"]
        self.assertEqual(output["dataType"], "geodataframe")
        frame = parsers.load_artifact(output["path"], session_id=session)
        self.assertIsInstance(frame, gpd.GeoDataFrame)
        self.assertEqual(frame["zone"].tolist(), ["square"])

    def test_a_python_node_reads_the_rows_as_input_0_in_process(self):
        from utk_curio.sandbox.app.worker import _worker_init, execute_code

        _worker_init()
        output = self._store({"dataType": "dataframe", "data": COLUMNS})

        result = execute_code(READ_CODE, output["path"], "curio.builtin/python-computation",
                              output["dataType"], session_id=SESSION, save_dataset=False, input_slots=[0])

        self.assertEqual(result["stderr"], "")
        self.assertEqual(
            parsers.load_from_duckdb(result["output"]["path"]),
            "DataFrame 4 i ['Alpha', 'Bravo', 'Charlie', 'Foxtrot']",
        )

    def test_a_python_node_reads_the_rows_as_input_0_in_an_isolated_child(self):
        from utk_curio.sandbox.isolation import child, runner, zygote

        output = self._store({"dataType": "dataframe", "data": COLUMNS})
        scratch = Path(self._tmp.name) / "scratch"
        scratch.mkdir()

        spec = runner._build_input_spec(output["path"], output["dataType"], str(scratch), SESSION)
        result = child.run_node({
            "code": READ_CODE, "node_type": "curio.builtin/python-computation", "data_type": output["dataType"],
            "scratch_dir": str(scratch), "input": spec, "input_slots": [0], "session_imports": [], "limits": {},
        }, zygote.build_namespace_template)

        self.assertTrue(result["ok"], result["stderr"])
        self.assertEqual(result["output"]["value"], "DataFrame 4 i ['Alpha', 'Bravo', 'Charlie', 'Foxtrot']")
