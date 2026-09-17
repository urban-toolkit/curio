"""Value <-> bytes conversion, independent of the artifact store.

``codec.py`` was split out of ``parsers.py`` so a process can convert node
values without any access to DuckDB or ``.curio/data``. These tests pin two
things:

1. The conversion round-trips every kind ``detect_kind`` can return, including
   the two ordering traps the implementation depends on.
2. The module stays store-free. If someone reintroduces an import of
   ``util.db`` or an artifact-path helper, ``test_codec_does_not_reach_the_store``
   fails, because that property is what lets an isolated child import it.
"""

import json

import duckdb
import math
import sys
import unittest

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Point

from utk_curio.sandbox.util import codec


class TestDetectKind(unittest.TestCase):
    """Kind detection is a pure type dispatch with two order-sensitive cases."""

    def test_scalar_and_container_kinds(self):
        cases = [
            (None, "null"),
            ("hello", "str"),
            (1.5, "float"),
            ([1, 2], "list"),
            ({"a": 1}, "dict"),
            ((1, 2), "outputs"),
            (object(), "unknown"),
        ]
        for value, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(codec.detect_kind(value), expected)

    def test_bool_is_checked_before_int(self):
        """bool subclasses int, so the order in detect_kind is load-bearing.

        If the int check ran first, True would be stored as an integer and come
        back as 1 rather than True.
        """
        self.assertEqual(codec.detect_kind(True), "bool")
        self.assertEqual(codec.detect_kind(False), "bool")
        self.assertEqual(codec.detect_kind(1), "int")
        self.assertEqual(codec.detect_kind(0), "int")

    def test_geodataframe_is_checked_before_dataframe(self):
        """GeoDataFrame subclasses DataFrame; the order preserves geometry."""
        gdf = gpd.GeoDataFrame({"a": [1]}, geometry=[Point(0, 0)], crs="EPSG:4326")
        self.assertEqual(codec.detect_kind(gdf), "geodataframe")
        self.assertEqual(codec.detect_kind(pd.DataFrame({"a": [1]})), "dataframe")

    def test_raster_only_when_rasterio_is_imported(self):
        """The raster branch is guarded on 'rasterio' in sys.modules."""
        if "rasterio" not in sys.modules:
            self.assertEqual(codec.detect_kind(object()), "unknown")


class TestJsonSafeValue(unittest.TestCase):
    """NaN and Infinity are not valid JSON and must not reach an artifact."""

    def test_non_finite_floats_become_none(self):
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value):
                self.assertIsNone(codec._json_safe_value(value))

    def test_finite_floats_are_untouched(self):
        for value in (0.0, -1.5, 1e300):
            self.assertEqual(codec._json_safe_value(value), value)

    def test_numpy_floats_are_handled(self):
        self.assertIsNone(codec._json_safe_value(np.float32("nan")))
        self.assertIsNone(codec._json_safe_value(np.float64("inf")))
        self.assertEqual(codec._json_safe_value(np.float64(2.5)), 2.5)

    def test_scrubbing_is_recursive(self):
        scrubbed = codec._json_safe_value(
            {"a": [1.0, float("nan")], "b": {"c": float("inf")}}
        )
        self.assertEqual(scrubbed, {"a": [1.0, None], "b": {"c": None}})
        # The whole point: the result must survive a strict JSON encoder.
        json.dumps(scrubbed, allow_nan=False)

    def test_scrubbed_output_is_strict_json(self):
        with self.assertRaises(ValueError):
            json.dumps({"x": float("nan")}, allow_nan=False)


class TestObjectColumnEncoding(unittest.TestCase):
    """Object columns holding real objects are JSON-encoded for parquet."""

    def test_plain_string_column_is_not_encoded(self):
        frame = pd.DataFrame({"s": ["a", "b"]})
        prepared, encoded = codec._prepare_frame_for_parquet(frame)
        self.assertEqual(encoded, [])
        # Untouched means not even copied.
        self.assertIs(prepared, frame)

    def test_object_column_round_trips(self):
        frame = pd.DataFrame({"payload": [{"k": 1}, [1, 2, 3]]})
        prepared, encoded = codec._prepare_frame_for_parquet(frame)
        self.assertEqual(encoded, ["payload"])
        self.assertTrue(all(isinstance(v, str) for v in prepared["payload"]))

        restored = codec._restore_frame_from_parquet(prepared.copy(), encoded)
        self.assertEqual(restored["payload"].tolist(), [{"k": 1}, [1, 2, 3]])

    def test_preparing_does_not_mutate_the_caller_s_frame(self):
        frame = pd.DataFrame({"payload": [{"k": 1}]})
        codec._prepare_frame_for_parquet(frame)
        self.assertEqual(frame["payload"].iloc[0], {"k": 1})

    def test_missing_values_survive_as_none(self):
        self.assertIsNone(codec._encode_object_cell_for_parquet(None))
        self.assertIsNone(codec._encode_object_cell_for_parquet(float("nan")))
        self.assertIsNone(codec._decode_object_cell_from_parquet(None))

    def test_numpy_types_are_made_serializable(self):
        encoded = codec._encode_object_cell_for_parquet(
            {"i": np.int64(3), "f": np.float64(1.5), "b": np.bool_(True),
             "arr": np.array([1, 2])}
        )
        self.assertEqual(
            json.loads(encoded), {"i": 3, "f": 1.5, "b": True, "arr": [1, 2]}
        )

    def test_geometry_column_is_never_encoded(self):
        gdf = gpd.GeoDataFrame(
            {"a": [1]}, geometry=[Point(0, 0)], crs="EPSG:4326"
        )
        _prepared, encoded = codec._prepare_frame_for_parquet(
            gdf, geometry_col="geometry"
        )
        self.assertNotIn("geometry", encoded)


class TestParquetMeta(unittest.TestCase):

    def test_round_trip(self):
        meta = codec._serialize_parquet_meta({"title": "x"}, ["col"])
        frame_metadata, encoded = codec._parse_parquet_meta(meta)
        self.assertEqual(frame_metadata, {"title": "x"})
        self.assertEqual(encoded, ["col"])

    def test_empty_meta_serializes_to_none(self):
        self.assertIsNone(codec._serialize_parquet_meta(None, []))
        self.assertEqual(codec._parse_parquet_meta(None), (None, []))

    def test_malformed_meta_does_not_raise(self):
        self.assertEqual(codec._parse_parquet_meta("{not json"), (None, []))

    def test_legacy_payload_is_treated_as_frame_metadata(self):
        """Older geodataframe rows stored only gdf.metadata, with no wrapper."""
        frame_metadata, encoded = codec._parse_parquet_meta(json.dumps({"title": "old"}))
        self.assertEqual(frame_metadata, {"title": "old"})
        self.assertEqual(encoded, [])


class TestParquetWriting(unittest.TestCase):
    """_write_dataframe_parquet uses an in-memory DuckDB, not the shared store."""

    def test_dataframe_round_trips_through_a_file(self):
        import tempfile
        from pathlib import Path

        frame = pd.DataFrame({"a": [1, 2], "b": ["x", "y"]})
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.parquet"
            codec._write_dataframe_parquet(frame, path)
            self.assertTrue(path.exists())
            pd.testing.assert_frame_equal(pd.read_parquet(path), frame)

    def test_geodataframe_geometry_and_crs_survive(self):
        import tempfile
        from pathlib import Path

        gdf = gpd.GeoDataFrame(
            {"a": [1, 2]},
            geometry=[Point(0, 0), Point(1, 1)],
            crs="EPSG:4326",
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.parquet"
            gdf.to_parquet(path)
            restored = gpd.read_parquet(path)
        self.assertEqual(restored.crs, gdf.crs)
        self.assertTrue(restored.geometry.equals(gdf.geometry))

    def test_empty_frame_round_trips(self):
        import tempfile
        from pathlib import Path

        frame = pd.DataFrame({"a": pd.Series(dtype="int64")})
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "empty.parquet"
            codec._write_dataframe_parquet(frame, path)
            self.assertEqual(len(pd.read_parquet(path)), 0)


class TestParquetWriterFootprint(unittest.TestCase):
    """The writer runs inside an address-space-capped child (#334).

    ``child._apply_rlimits`` caps RLIMIT_AS at the interpreter's footprint plus
    the operator's budget, and serialization happens inside that cap. DuckDB's
    defaults are sized for owning the machine: ``threads`` follows the host's
    core count and ``memory_limit`` is ~80% of system RAM, so writing three
    integers on a 64-core runner reserved enough address space to fail with
    ``OutOfMemoryException: Failed to allocate block of 32768 bytes``. Measured
    locally on 8 cores: default 7040 KB of peak RSS for one write, against
    496 KB constrained — and a runner has far more cores than that.

    Nothing here needs parallelism: it is one COPY of one frame.
    """

    def _captured_config(self, frame=None):
        import tempfile
        from pathlib import Path
        from unittest import mock

        seen = {}
        real_connect = duckdb.connect

        def spy(*args, **kwargs):
            seen.update(kwargs.get("config") or {})
            return real_connect(*args, **kwargs)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.parquet"
            with mock.patch.object(duckdb, "connect", spy):
                codec._write_dataframe_parquet(
                    frame if frame is not None else pd.DataFrame({"a": [1, 2, 3]}), path
                )
            self.assertTrue(path.exists())
        return seen

    def test_the_writer_runs_single_threaded(self):
        self.assertEqual(self._captured_config().get("threads"), 1)

    def test_the_writer_declares_a_bounded_memory_limit(self):
        limit = self._captured_config().get("memory_limit")
        self.assertIsNotNone(limit, "no memory_limit: DuckDB would size itself from host RAM")
        # A number plus a unit, and not gigabytes of it.
        self.assertRegex(str(limit), r"^\d+\s*(MB|MiB)$")

    def test_a_large_frame_still_writes_under_that_limit(self):
        # The bound must not turn a big output into a failure: `register` is
        # zero-copy and COPY streams row groups, so the limit is not a ceiling
        # on the frame. 150 MB of frame through a 256 MB limit, locally 0.5 s.
        import numpy as np

        rows = 2_000_000
        frame = pd.DataFrame({"a": np.arange(rows), "b": np.random.rand(rows)})
        config = self._captured_config(frame)
        self.assertEqual(config.get("threads"), 1)


class TestStoreIndependence(unittest.TestCase):
    """The property that makes codec.py usable from an isolated process."""

    def test_codec_does_not_reach_the_store(self):
        source = __import__("pathlib").Path(codec.__file__).read_text(encoding="utf-8")
        # Strip the module docstring, which legitimately mentions util/db.py.
        body = source.split('"""', 2)[-1]
        for forbidden in ("util.db", "get_connection", "get_read_connection",
                          "init_db", "_shared_data_dir",
                          "_resolve_stored_artifact_path"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, body)

    def test_importing_codec_does_not_import_db(self):
        """A fresh interpreter, so a previously-imported db cannot mask this."""
        import subprocess

        result = subprocess.run(
            [sys.executable, "-c",
             "import sys; import utk_curio.sandbox.util.codec; "
             "print('utk_curio.sandbox.util.db' in sys.modules)"],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "False", result.stdout)


class TestParsersReExports(unittest.TestCase):
    """parsers.py must keep exposing every moved name.

    worker.py imports detect_kind from parsers and seeds it into every node's
    namespace; test_sandbox_namespace.py pins that. The re-export shim is what
    keeps the split invisible to callers.
    """

    MOVED = (
        "PARQUET_DECODE_SIDECAR_SUFFIX", "_decode_object_cell_from_parquet",
        "_encode_object_cell_for_parquet", "_is_missing_value",
        "_json_safe_value", "_make_serializable",
        "_object_column_needs_json_encoding", "_parse_parquet_meta",
        "_prepare_frame_for_parquet", "_restore_frame_from_parquet",
        "_serialize_parquet_meta", "_write_dataframe_parquet",
        "detect_kind", "make_json_safe", "safe_json_loads",
    )

    def test_every_moved_name_is_still_importable_from_parsers(self):
        from utk_curio.sandbox.util import parsers

        for name in self.MOVED:
            with self.subTest(name=name):
                self.assertTrue(hasattr(parsers, name), name)

    def test_re_exports_are_the_same_objects(self):
        from utk_curio.sandbox.util import parsers

        for name in self.MOVED:
            if name.isupper():
                continue
            with self.subTest(name=name):
                self.assertIs(getattr(parsers, name), getattr(codec, name))


if __name__ == "__main__":
    unittest.main()


# ── shapely geometry in an ordinary cell ───────────────────────────────────

def test_make_serializable_converts_a_shapely_geometry_to_geojson():
    from shapely.geometry import Point

    result = codec._make_serializable(Point(0.5, 1.5))

    assert result == {"type": "Point", "coordinates": [0.5, 1.5]}


def test_make_serializable_uses_lists_not_tuples_for_coordinates():
    """shapely hands back tuples; JSON has no tuple, and callers compare
    against lists. The conversion has to happen here, not at dump time."""
    from shapely.geometry import Polygon

    result = codec._make_serializable(
        Polygon([(0, 0), (0, 1), (1, 1), (0, 0)])
    )

    assert result["type"] == "Polygon"
    assert isinstance(result["coordinates"], list)
    assert all(isinstance(ring, list) for ring in result["coordinates"])
    assert result["coordinates"][0][0] == [0.0, 0.0]


def test_make_serializable_handles_nested_geometry():
    from shapely.geometry import Point

    result = codec._make_serializable({"where": Point(1, 2), "n": 3})

    assert result == {"where": {"type": "Point", "coordinates": [1.0, 2.0]}, "n": 3}


def test_a_plain_dataframe_holding_shapely_survives_normalization():
    """D2: a plain DataFrame carrying shapely objects.

    `pd.DataFrame(gdf)` produces exactly this, and it used to emit the raw
    shapely object and die at `jsonify`.
    """
    import pandas as pd
    from shapely.geometry import Point

    from utk_curio.sandbox.util.parsers import normalize_dataframe_for_json, parseOutput

    df = pd.DataFrame({"name": ["A"], "where": [Point(1, 2)]})

    normalized = normalize_dataframe_for_json(df)
    assert normalized["where"].iloc[0] == {"type": "Point", "coordinates": [1.0, 2.0]}

    out = parseOutput(df)
    assert out["dataType"] == "dataframe"
    assert out["data"]["where"][0]["type"] == "Point"


def test_existing_containers_are_untouched_by_the_geometry_branch():
    """The geometry branch sits ahead of the dict/list cases; ordinary
    containers must reach them unchanged."""
    import numpy as np

    assert codec._make_serializable({"a": [1, 2]}) == {"a": [1, 2]}
    assert codec._make_serializable([{"b": (1, 2)}]) == [{"b": [1, 2]}]
    assert codec._make_serializable(np.array([1, 2])) == [1, 2]
