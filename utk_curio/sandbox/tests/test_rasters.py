"""Rasters between Python nodes and Autark nodes (#662, step 8).

An Autark node loads a Python node's raster from the bytes ``GET /raster``
serves for its artifact: a GeoTIFF GDAL writes, with its size, CRS and
transform in the ``X-Curio-Raster`` header, refused with its size when it is
larger than the caller can load. The other way, an Autark node hands a raster
on as autk-db's ``getRaster`` collection in an envelope, and a Python node
receives it as a rasterio dataset with the same bands, origin, resolution and
CRS, in process and in an isolated child alike.

The envelope and the GeoTIFF Curio's frontend writes from it are pinned by
``rasterWire.cases.json``, which the frontend's tests run too.

The module under test is imported inside each test, so a checkout without it
reports each test as failing rather than the whole suite as uncollectable.
"""
import base64
import json
import math
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

REPO = Path(__file__).resolve().parents[3]
CASES_FILE = REPO / "utk_curio" / "frontend" / "urban-workflows" / "src" / "utils" / "raster" / "rasterWire.cases.json"
FIXTURE = REPO / "utk_curio" / "backend" / "tests" / "test_frontend" / "data" / "autark_raster_utm16n.tif"


def cases():
    return json.loads(CASES_FILE.read_text(encoding="utf-8"))["cases"]


def rasters():
    from utk_curio.sandbox.util import rasters as module

    return module


def as_lists(array):
    """NaN-aware: nested lists with None for a nodata cell."""
    return [[None if math.isnan(v) else float(v) for v in row] for row in array.tolist()]


def transform_of(grid):
    from affine import Affine

    return Affine(grid["resX"], 0.0, grid["originX"], 0.0, grid["resY"], grid["originY"])


def why(response):
    """A response's body as text, for an assertion message: a served raster is
    bytes, not UTF-8, so it is decoded leniently."""
    return response.get_data().decode("utf-8", "replace")[:500]


class StoreTestCase(unittest.TestCase):
    """A sandbox with its own launch directory, store and artifacts."""

    def setUp(self):
        from utk_curio.sandbox.util.db import init_db, release_connection

        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        env = mock.patch.dict(os.environ, {
            "CURIO_LAUNCH_CWD": self._tmp.name,
            "CURIO_SHARED_DATA": "./.curio/data/",
        })
        env.start()
        self.addCleanup(env.stop)
        (self.root / ".curio" / "data").mkdir(parents=True, exist_ok=True)
        release_connection()
        self.addCleanup(release_connection)
        init_db()


class TheEnvelopeTest(unittest.TestCase):
    """The cases both sides run: what a Python node gets from an envelope."""

    def test_the_envelope_holds_each_band_north_to_south(self):
        for case in cases():
            with self.subTest(case=case["name"]):
                grid, ids, values = rasters().envelope_arrays(case["envelope"])
                self.assertEqual(grid, case["grid"])
                self.assertEqual(ids, list(case["bands"]))
                self.assertEqual(str(values.dtype), "float32")
                for index, band in enumerate(ids):
                    self.assertEqual(as_lists(values[index]), case["rows_north_to_south"][band])

    def test_a_python_node_gets_a_rasterio_dataset_on_the_same_grid(self):
        import rasterio

        for case in cases():
            with self.subTest(case=case["name"]), TemporaryDirectory() as folder:
                dataset = rasters().raster_from_envelope(case["envelope"], folder)
                try:
                    self.assertIsInstance(dataset, rasterio.io.DatasetReader)
                    grid = case["grid"]
                    self.assertEqual((dataset.width, dataset.height), (grid["width"], grid["height"]))
                    self.assertEqual(dataset.crs.to_epsg(), int(grid["crs"].split(":")[1]))
                    self.assertEqual(dataset.transform, transform_of(grid))
                    self.assertTrue(math.isnan(dataset.nodata))
                    self.assertEqual(list(dataset.descriptions), list(case["bands"]))
                    for index, band in enumerate(case["bands"], start=1):
                        self.assertEqual(as_lists(dataset.read(index)), case["rows_north_to_south"][band])
                    # A file of its own, beside the others, that a node can return.
                    self.assertEqual(Path(dataset.name).parent, Path(folder))
                finally:
                    dataset.close()

    def test_the_same_raster_is_written_once(self):
        case = cases()[0]
        with TemporaryDirectory() as folder:
            first = rasters().raster_from_envelope(case["envelope"], folder)
            second = rasters().raster_from_envelope(case["envelope"], folder)
            self.assertEqual(first.name, second.name)
            first.close()
            second.close()
            self.assertEqual(len(list(Path(folder).glob("*.tif"))), 1)

    def test_the_geotiff_the_frontend_writes_is_the_same_grid_to_gdal(self):
        """``writeGeoTiff`` (utils/raster/geotiffWriter.ts) is what autk-db
        loads a handed-on raster from. GDAL reads its bytes as the same grid."""
        from rasterio.io import MemoryFile

        for case in cases():
            with self.subTest(case=case["name"]):
                with MemoryFile(base64.b64decode(case["geotiff_base64"])) as memory, memory.open() as dataset:
                    grid = case["grid"]
                    self.assertEqual(dataset.driver, "GTiff")
                    self.assertEqual((dataset.width, dataset.height), (grid["width"], grid["height"]))
                    self.assertEqual(dataset.count, len(case["bands"]))
                    self.assertEqual(dataset.dtypes[0], "float32")
                    self.assertEqual(dataset.crs.to_epsg(), int(grid["crs"].split(":")[1]))
                    self.assertEqual(dataset.transform, transform_of(grid))
                    self.assertTrue(math.isnan(dataset.nodata))
                    for index, band in enumerate(case["bands"], start=1):
                        self.assertEqual(as_lists(dataset.read(index)), case["rows_north_to_south"][band])

    def test_only_an_envelope_with_a_collection_becomes_a_dataset(self):
        module = rasters()
        envelope = cases()[0]["envelope"]
        self.assertTrue(module.is_raster_envelope(envelope))
        self.assertFalse(module.is_raster_envelope({"dataType": "raster", "data": "/data/heat.tif"}))
        self.assertFalse(module.is_raster_envelope({"dataType": "dict", "data": {}}))

        with TemporaryDirectory() as folder:
            plain = {"a": 1}
            self.assertIs(module.rasters_for_python(plain, folder), plain)
            converted = module.rasters_for_python((envelope, plain), folder)
            self.assertIsInstance(converted, tuple)
            self.assertEqual(converted[0].width, 4)
            self.assertIs(converted[1], plain)
            converted[0].close()
            listed = module.rasters_for_python([plain, envelope], folder)
            self.assertIsInstance(listed, list)
            self.assertEqual(listed[1].height, 3)
            listed[1].close()

    def test_no_folder_is_asked_for_when_there_is_no_raster(self):
        asked = mock.Mock(side_effect=AssertionError("asked for a folder"))
        value = [{"a": 1}, 2]
        self.assertIs(rasters().rasters_for_python(value, asked), value)
        asked.assert_not_called()

    def test_parse_input_keeps_an_envelope_for_whoever_reads_it(self):
        """A JavaScript node gets the envelope as JSON; only a Python node's
        input is rebuilt as a dataset."""
        from utk_curio.sandbox.util.parsers import parseInput

        envelope = cases()[0]["envelope"]
        self.assertIs(parseInput(envelope), envelope)


class APythonNodeReceivesTheRasterTest(StoreTestCase):
    """End to end in the sandbox: an Autark node's envelope, stored as its
    output, is a rasterio dataset in the Python node it feeds."""

    CHECK = (
        "    import rasterio\n"
        "    assert isinstance(arg, rasterio.io.DatasetReader), type(arg)\n"
        "    band = arg.read(1)\n"
        "    return f'{arg.crs.to_epsg()}|{arg.width}x{arg.height}|{tuple(arg.transform)[:6]}|{float(band[2, 0])}'\n"
    )

    def test_in_process(self):
        from utk_curio.sandbox.app.worker import _worker_init, execute_code
        from utk_curio.sandbox.util.parsers import load_from_duckdb, save_to_duckdb

        _worker_init()
        case = cases()[0]
        art_id = save_to_duckdb(case["envelope"], "autark-node")
        result = execute_code(self.CHECK, art_id, "curio.builtin/computation-analysis", "dict",
                              save_dataset=False)
        self.assertEqual(result["stderr"], "")
        self.assertEqual(result["output"]["dataType"], "str")
        grid = case["grid"]
        self.assertEqual(
            load_from_duckdb(result["output"]["path"]),
            f"32616|4x3|{tuple(transform_of(grid))[:6]}|1.5",
        )

    def test_in_process_a_returned_raster_is_kept_and_served(self):
        """The rebuilt dataset is a real file: returned, it is the node's raster
        output, and the raster route serves it on the same grid."""
        from utk_curio.sandbox.app import app
        from utk_curio.sandbox.app.worker import _worker_init, execute_code
        from utk_curio.sandbox.util.parsers import save_to_duckdb

        _worker_init()
        case = cases()[0]
        art_id = save_to_duckdb(case["envelope"], "autark-node")
        result = execute_code("    return arg\n", art_id, "curio.builtin/computation-analysis", "dict",
                              save_dataset=False)
        self.assertEqual(result["stderr"], "")
        self.assertEqual(result["output"]["dataType"], "raster")
        response = app.test_client().get("/raster", query_string={"fileName": result["output"]["path"]})
        self.assertEqual(response.status_code, 200, why(response))
        meta = json.loads(response.headers["X-Curio-Raster"])
        self.assertEqual(meta["crs"], "EPSG:32616")
        self.assertEqual(meta["transform"], list(tuple(transform_of(case["grid"]))[:6]))

    def test_in_an_isolated_child(self):
        from utk_curio.sandbox.isolation import child

        case = cases()[0]
        with TemporaryDirectory() as scratch:
            Path(scratch, "in_0.json").write_text(json.dumps(case["envelope"]), encoding="utf-8")
            request = {
                "code": self.CHECK,
                "node_type": "curio.builtin/computation-analysis",
                "data_type": "dict",
                "scratch_dir": scratch,
                "input": {"kind": "json", "file": "in_0.json"},
                "dataset_paths": {},
                "session_imports": [],
                "limits": {},
            }
            result = child.run_node(request, lambda: {"__builtins__": __builtins__})
            self.assertTrue(result["ok"], result["stderr"])
            self.assertEqual(
                result["output"],
                {"kind": "str", "value": f"32616|4x3|{tuple(transform_of(case['grid']))[:6]}|1.5"},
            )
            # Written into the scratch directory, the one place the child writes.
            self.assertEqual(len(list(Path(scratch).glob("autark-raster-*.tif"))), 1)


class TheRasterRouteTest(StoreTestCase):
    """``GET /raster``: a raster artifact as GeoTIFF bytes, by its id."""

    def setUp(self):
        super().setUp()
        from utk_curio.sandbox.app import app

        self.client = app.test_client()

    def store_fixture(self):
        import rasterio

        from utk_curio.sandbox.util.parsers import save_to_duckdb

        dataset = rasterio.open(FIXTURE)
        self.addCleanup(dataset.close)
        return save_to_duckdb(dataset, "python-node")

    def get(self, art_id, **params):
        return self.client.get("/raster", query_string={"fileName": art_id, **params})

    def test_a_raster_is_served_as_a_geotiff_with_its_description(self):
        from rasterio.io import MemoryFile

        response = self.get(self.store_fixture())
        self.assertEqual(response.status_code, 200, why(response))
        self.assertEqual(response.mimetype, "image/tiff")
        meta = json.loads(response.headers["X-Curio-Raster"])
        self.assertEqual(meta, {
            "width": 40,
            "height": 30,
            "count": 1,
            "crs": "EPSG:32616",
            "crsWkt": None,
            "transform": [100.0, 0.0, 447000.0, 0.0, -100.0, 4637000.0],
            "nodata": -9999.0,
            "dtype": "float32",
        })
        import rasterio

        with MemoryFile(response.get_data()) as memory, memory.open() as served:
            self.assertEqual(served.driver, "GTiff")
            self.assertEqual((served.width, served.height), (40, 30))
            self.assertEqual(served.crs.to_epsg(), 32616)
            self.assertEqual(served.nodata, -9999.0)
            with rasterio.open(FIXTURE) as source:
                self.assertEqual(served.read(1).tolist(), source.read(1).tolist())

    def test_a_raster_larger_than_the_caller_loads_is_refused_with_its_size(self):
        response = self.get(self.store_fixture(), maxCells=1000, maxSide=8192)
        self.assertEqual(response.status_code, 413)
        body = response.get_json()
        self.assertEqual(body["error"], "too-large")
        self.assertEqual((body["meta"]["width"], body["meta"]["height"]), (40, 30))

        response = self.get(self.store_fixture(), maxCells=1_000_000, maxSide=39)
        self.assertEqual(response.status_code, 413)

    def test_a_raster_in_a_tuple_is_served_by_its_part(self):
        import pandas as pd
        import rasterio

        from utk_curio.sandbox.util.parsers import save_to_duckdb

        dataset = rasterio.open(FIXTURE)
        self.addCleanup(dataset.close)
        art_id = save_to_duckdb((pd.DataFrame({"a": [1]}), dataset), "python-node")
        self.assertEqual(self.get(art_id, part=1).status_code, 200)
        self.assertEqual(self.get(art_id, part=0).status_code, 422)
        self.assertEqual(self.get(art_id, part=5).status_code, 404)

    def test_a_virtual_raster_is_served_as_a_geotiff(self):
        """geotiff.js reads no VRT, which is what Mosaic Rasters returns."""
        import rasterio
        from rasterio.io import MemoryFile

        from utk_curio.sandbox.util.parsers import save_to_duckdb

        vrt = self.root / "mosaic.vrt"
        vrt.write_text(
            '<VRTDataset rasterXSize="40" rasterYSize="30">\n'
            "  <SRS>EPSG:32616</SRS>\n"
            "  <GeoTransform>447000, 100, 0, 4637000, 0, -100</GeoTransform>\n"
            '  <VRTRasterBand dataType="Float32" band="1">\n'
            "    <NoDataValue>-9999</NoDataValue>\n"
            "    <SimpleSource>\n"
            f'      <SourceFilename relativeToVRT="0">{FIXTURE}</SourceFilename>\n'
            "      <SourceBand>1</SourceBand>\n"
            "    </SimpleSource>\n"
            "  </VRTRasterBand>\n"
            "</VRTDataset>\n",
            encoding="utf-8",
        )
        dataset = rasterio.open(vrt)
        self.addCleanup(dataset.close)
        self.assertEqual(dataset.driver, "VRT")

        response = self.get(save_to_duckdb(dataset, "mosaic-node"))
        self.assertEqual(response.status_code, 200, why(response))
        with MemoryFile(response.get_data()) as memory, memory.open() as served:
            self.assertEqual(served.driver, "GTiff")
            self.assertEqual(served.crs.to_epsg(), 32616)
            with rasterio.open(FIXTURE) as source:
                self.assertEqual(served.read(1).tolist(), source.read(1).tolist())

    def test_what_is_not_a_raster_is_refused(self):
        import pandas as pd

        from utk_curio.sandbox.util.parsers import save_to_duckdb

        art_id = save_to_duckdb(pd.DataFrame({"a": [1]}), "python-node")
        response = self.get(art_id)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.get_json()["error"], "not-a-raster")
        self.assertEqual(self.get("no-such-artifact").status_code, 404)

    def test_the_header_is_one_the_browser_may_read(self):
        """The canvas is on another origin: the backend must expose the header."""
        from utk_curio.backend.app import CORS_HEADERS

        exposed = {
            name.strip().lower()
            for name in CORS_HEADERS["Access-Control-Expose-Headers"].split(",")
        }
        self.assertIn(rasters().RASTER_META_HEADER.lower(), exposed)


class ARasterOutputAfterAReopenTest(StoreTestCase):
    """A saved raster output, read again after a reopen under a new sign-in.

    The store's row carries the session that wrote it, so the next sign-in's
    reads are refused there and fall back to the copy a project load hydrated
    into the shared data directory under the artifact's id
    (``projects/storage.hydrate_outputs``). For a raster that copy is the
    raster's own file, a GeoTIFF or the VRT Mosaic Rasters writes, with no
    extension. The fallback read parquet and JSON only, so ``/raster`` answered
    404 and a Python node downstream failed with "No artifact with id".
    """

    def setUp(self):
        super().setUp()
        from utk_curio.sandbox.app import app

        self.client = app.test_client()
        self.data_dir = self.root / ".curio" / "data"

    def hydrated(self, raster_bytes, suffix=".tif"):
        """A raster an earlier sign-in returned, and the copy a project load
        hydrated for it. The file the store's row names is gone, as the scratch
        copy of an output is, so the hydrated copy is the only one."""
        import rasterio

        from utk_curio.sandbox.util.parsers import save_to_duckdb

        written = self.root / f"returned{suffix}"
        written.write_bytes(raster_bytes)
        with rasterio.open(written) as dataset:
            art_id = save_to_duckdb(dataset, "python-node", session_id="earlier-sign-in")
        (self.data_dir / art_id).write_bytes(raster_bytes)
        written.unlink()
        return art_id

    def assert_the_fixture(self, dataset):
        import rasterio

        with rasterio.open(FIXTURE) as source:
            self.assertEqual((dataset.width, dataset.height), (source.width, source.height))
            self.assertEqual(dataset.crs.to_epsg(), 32616)
            self.assertEqual(tuple(dataset.transform), tuple(source.transform))
            self.assertEqual(dataset.read(1).tolist(), source.read(1).tolist())

    def test_load_artifact_opens_the_hydrated_geotiff(self):
        import rasterio

        from utk_curio.sandbox.util.parsers import load_artifact

        art_id = self.hydrated(FIXTURE.read_bytes())
        dataset = load_artifact(art_id, session_id="new-sign-in")
        self.addCleanup(getattr(dataset, "close", lambda: None))
        self.assertIsInstance(dataset, rasterio.io.DatasetReader)
        self.assert_the_fixture(dataset)

    def test_the_raster_route_serves_the_hydrated_geotiff(self):
        from rasterio.io import MemoryFile

        art_id = self.hydrated(FIXTURE.read_bytes())
        response = self.client.get("/raster", query_string={"fileName": art_id, "sessionId": "new-sign-in"})
        self.assertEqual(response.status_code, 200, why(response))
        meta = json.loads(response.headers["X-Curio-Raster"])
        self.assertEqual((meta["width"], meta["height"], meta["crs"]), (40, 30, "EPSG:32616"))
        with MemoryFile(response.get_data()) as memory, memory.open() as served:
            self.assert_the_fixture(served)

    def test_the_raster_route_serves_a_hydrated_virtual_raster(self):
        """Mosaic Rasters returns a VRT; its hydrated copy is the VRT's XML."""
        from rasterio.io import MemoryFile

        vrt = (
            '<VRTDataset rasterXSize="40" rasterYSize="30">\n'
            "  <SRS>EPSG:32616</SRS>\n"
            "  <GeoTransform>447000, 100, 0, 4637000, 0, -100</GeoTransform>\n"
            '  <VRTRasterBand dataType="Float32" band="1">\n'
            "    <NoDataValue>-9999</NoDataValue>\n"
            "    <SimpleSource>\n"
            f'      <SourceFilename relativeToVRT="0">{FIXTURE}</SourceFilename>\n'
            "      <SourceBand>1</SourceBand>\n"
            "    </SimpleSource>\n"
            "  </VRTRasterBand>\n"
            "</VRTDataset>\n"
        )
        art_id = self.hydrated(vrt.encode("utf-8"), suffix=".vrt")
        response = self.client.get("/raster", query_string={"fileName": art_id, "sessionId": "new-sign-in"})
        self.assertEqual(response.status_code, 200, why(response))
        with MemoryFile(response.get_data()) as memory, memory.open() as served:
            self.assertEqual(served.driver, "GTiff")
            self.assert_the_fixture(served)

    def test_a_python_node_in_process_reads_it(self):
        import rasterio

        from utk_curio.sandbox.app.worker import _worker_init, execute_code
        from utk_curio.sandbox.util.parsers import load_from_duckdb

        _worker_init()
        art_id = self.hydrated(FIXTURE.read_bytes())
        result = execute_code(
            APythonNodeReceivesTheRasterTest.CHECK, art_id, "curio.builtin/computation-analysis", "raster",
            session_id="new-sign-in", save_dataset=False,
        )
        self.assertEqual(result["stderr"], "")
        with rasterio.open(FIXTURE) as source:
            expected = (
                f"{source.crs.to_epsg()}|{source.width}x{source.height}|"
                f"{tuple(source.transform)[:6]}|{float(source.read(1)[2, 0])}"
            )
        self.assertEqual(load_from_duckdb(result["output"]["path"]), expected)

    def test_an_isolated_python_node_has_it_staged(self):
        import rasterio

        from utk_curio.sandbox.util import staging

        art_id = self.hydrated(FIXTURE.read_bytes())
        scratch = self.root / "scratch"
        scratch.mkdir()
        spec = staging.stage_input(art_id, scratch, session_id="new-sign-in")
        self.assertEqual(spec["kind"], "raster")
        with rasterio.open(scratch / spec["file"]) as staged:
            self.assert_the_fixture(staged)

    def test_bytes_that_only_start_like_a_tiff_are_still_missing(self):
        """A file GDAL cannot read is no raster: a 404, as any missing one."""
        art_id = "1700000000006_beef0006"
        (self.data_dir / art_id).write_bytes(b"II*\x00" + b"\x00" * 60)
        response = self.client.get("/raster", query_string={"fileName": art_id, "sessionId": "new-sign-in"})
        self.assertEqual(response.status_code, 404, why(response))


if __name__ == "__main__":
    unittest.main()
