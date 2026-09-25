"""The Arrow artifact response: what it carries and what it refuses.

The canvas is about to start asking for this format, so the parts the JSON
body carries inline have to arrive in headers, and the one part the client
cannot yet decode -- WKB geometry -- has to be refused rather than served.
"""

import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import pandas as pd

from utk_curio.sandbox.app import app
from utk_curio.sandbox.app.api import ARROW_IPC_MIME, ARROW_RESPONSE_HEADERS
from utk_curio.sandbox.util import parsers
from utk_curio.sandbox.util.db import init_db, release_connection


class ArrowRouteTestCase(unittest.TestCase):
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

    def get(self, art_id, *, arrow=True, geometry=False):
        headers = {}
        if arrow:
            headers["Accept"] = ARROW_IPC_MIME
        if geometry:
            headers["X-Curio-Accept-Geometry"] = "wkb"
        return self.client.get(
            "/get", query_string={"fileName": art_id}, headers=headers
        )

    def frame(self):
        return pd.DataFrame({
            "n": [1, 2, 3],
            "label": ["a", "b", "c"],
            "value": [1.5, 2.5, 3.5],
        })


class SchemaHeaderTest(ArrowRouteTestCase):
    def test_the_schema_matches_what_the_json_path_sends(self):
        """Same dtypes, same spelling. vegaBehavior reads this to pick a spec."""
        art_id = parsers.save_to_duckdb(self.frame(), "node-1")

        json_body = self.get(art_id, arrow=False).get_json()
        arrow_headers = self.get(art_id).headers

        self.assertEqual(
            json.loads(arrow_headers["X-Curio-Schema"]), json_body["schema"]
        )

    def test_the_schema_survives_an_object_column(self):
        art_id = parsers.save_to_duckdb(
            pd.DataFrame({"n": [1], "tags": [{"a": 1}]}), "node-1"
        )
        schema = json.loads(self.get(art_id).headers["X-Curio-Schema"])
        self.assertEqual(set(schema), {"n", "tags"})


class SchemaMatchesAcrossDtypesTest(ArrowRouteTestCase):
    """Every dtype, both writers, compared against what the JSON path sends.

    The two paths reach parquet differently -- a DataFrame through DuckDB's
    COPY, a GeoDataFrame through pandas to_parquet -- and only one of them
    records pandas metadata, so the schema is derived from Arrow types in the
    common case. A mistake there is silent and per-column, which is what this
    exists to prevent.
    """

    def test_a_dataframes_dtypes_match_the_json_path(self):
        import numpy as np

        frame = pd.DataFrame({
            "i64": np.array([1, 2], dtype="int64"),
            "i32": np.array([1, 2], dtype="int32"),
            "f64": np.array([1.5, 2.5], dtype="float64"),
            "f32": np.array([1.5, 2.5], dtype="float32"),
            "b": [True, False],
            "s": ["x", "y"],
            "ts": pd.to_datetime(["2020-01-01", "2021-01-01"]),
        })
        art_id = parsers.save_to_duckdb(frame, "node-1")

        json_schema = self.get(art_id, arrow=False).get_json()["schema"]
        arrow_schema = json.loads(self.get(art_id).headers["X-Curio-Schema"])

        self.assertEqual(arrow_schema, json_schema)

    def test_a_geodataframes_dtypes_match_the_json_path(self):
        gpd = __import__("pytest").importorskip("geopandas")
        from shapely.geometry import Point

        gdf = gpd.GeoDataFrame({
            "n": [1, 2],
            "value": [1.5, 2.5],
            "label": ["a", "b"],
            "geometry": [Point(0, 0), Point(1, 1)],
        }, crs="EPSG:4326")
        art_id = parsers.save_to_duckdb(gdf, "node-1")

        json_schema = self.get(art_id, arrow=False).get_json()["schema"]
        arrow_schema = json.loads(
            self.get(art_id, geometry=True).headers["X-Curio-Schema"]
        )

        # Including the geometry column: GeoParquet stores it as WKB binary,
        # but both paths report geopandas' ``geometry`` dtype, because what a
        # consumer wants to know is what the column means.
        self.assertEqual(arrow_schema, json_schema)


class GeometryOptInTest(ArrowRouteTestCase):
    def geo_frame(self):
        gpd = __import__("pytest").importorskip("geopandas")
        from shapely.geometry import Point

        return gpd.GeoDataFrame(
            {"n": [1, 2], "geometry": [Point(0, 0), Point(1, 1)]}, crs="EPSG:4326"
        )

    def test_a_geodataframe_is_refused_without_the_opt_in(self):
        """WKB where the client expects GeoJSON renders nothing, silently."""
        art_id = parsers.save_to_duckdb(self.geo_frame(), "node-1")
        response = self.get(art_id)
        self.assertEqual(response.status_code, 415)
        self.assertIn("X-Curio-Accept-Geometry", response.get_json()["message"])

    def test_the_opt_in_serves_it(self):
        art_id = parsers.save_to_duckdb(self.geo_frame(), "node-1")
        response = self.get(art_id, geometry=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["X-Curio-Kind"], "geodataframe")

    def test_the_json_path_is_unaffected_by_the_gate(self):
        """The fallback every client has today must keep working."""
        art_id = parsers.save_to_duckdb(self.geo_frame(), "node-1")
        body = self.get(art_id, arrow=False).get_json()
        self.assertEqual(body["dataType"], "geodataframe")
        self.assertEqual(body["data"]["type"], "FeatureCollection")

    def test_a_dataframe_needs_no_opt_in(self):
        art_id = parsers.save_to_duckdb(self.frame(), "node-1")
        self.assertEqual(self.get(art_id).status_code, 200)


class ExposedHeadersTest(unittest.TestCase):
    """A header the browser cannot read may as well not have been sent.

    The canvas runs on a different origin from the backend, so every name the
    Arrow route can emit has to be in Access-Control-Expose-Headers. Without
    this test, adding a header to the route would go unreadable in the browser
    and the envelope would quietly lose a field.
    """

    def test_every_arrow_header_is_exposed_cross_origin(self):
        from utk_curio.backend.app import CORS_HEADERS

        exposed = {
            name.strip().lower()
            for name in CORS_HEADERS["Access-Control-Expose-Headers"].split(",")
        }
        missing = [h for h in ARROW_RESPONSE_HEADERS if h.lower() not in exposed]
        self.assertEqual(missing, [], f"not exposed cross-origin: {missing}")


if __name__ == "__main__":
    unittest.main()
