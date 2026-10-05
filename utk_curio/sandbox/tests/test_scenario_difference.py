"""The Compare Scenarios node's difference step (#662), ``curio_difference_scenarios``.

In Difference the node compares two inputs, a reference (input 0) and a
comparison (input 1), and every number it gives is comparison minus reference.

- Two layers or two tables are joined on a stable id (``osm_id`` or
  ``building_id``, or a key the node names): rows on both sides hold the
  differences and ``changed`` or ``unchanged``; rows on one side only are
  ``removed`` or ``added``.
- Two rasters come back from the node's code as a request, which the sandbox
  completes in its own Node process: autk-db loads both, Curio's Autark
  adapter (``utils/raster/rasterArithmetic.ts``) subtracts the band arrays
  ``getRaster`` exports, and the result is a raster envelope. Grids that differ
  are refused, naming both. The raster tests run that Node process for real.

Every test imports the module itself, so a checkout without it fails test by
test rather than at collection.
"""
from __future__ import annotations

import base64
import json
import math
import re
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import Point

REPO = Path(__file__).resolve().parents[3]
FIXTURE = REPO / "utk_curio" / "backend" / "tests" / "test_frontend" / "data" / "autark_raster_utm16n.tif"
RASTER_LOAD_TS = REPO / "utk_curio" / "frontend" / "urban-workflows" / "src" / "utils" / "raster" / "rasterLoad.ts"
COMPARE = "curio.builtin/compare-scenarios"


def difference():
    from utk_curio.sandbox.util import scenario_difference as module

    return module


def _diff(reference, comparison, key=None):
    return difference().difference_scenarios(
        [("s-base", "Baseline", reference), ("s-tall", "Twice as tall", comparison)], key=key,
    )


def _roads(ids, sunlight, names=None, crs="EPSG:4326"):
    return gpd.GeoDataFrame(
        {"osm_id": ids, "sunlight": sunlight, "name": names or [f"road {i}" for i in ids]},
        geometry=[Point(i, i) for i in ids],
        crs=crs,
    )


def _numbers(series):
    return [None if pd.isna(v) else float(v) for v in series]


@pytest.fixture
def store(tmp_path, monkeypatch):
    """A sandbox with its own launch directory, store and artifacts."""
    from utk_curio.sandbox.util.db import init_db, release_connection

    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))
    monkeypatch.setenv("CURIO_SHARED_DATA", "./.curio/data/")
    (tmp_path / ".curio" / "data").mkdir(parents=True, exist_ok=True)
    release_connection()
    init_db()
    yield tmp_path
    release_connection()


def _raster(path, values, *, transform=None, crs="EPSG:32616", nodata=-9999.0):
    """A one-band float32 GeoTIFF of *values* (rows north to south)."""
    import rasterio
    from affine import Affine

    values = np.asarray(values, dtype="float32")
    with rasterio.open(
        path, "w", driver="GTiff", width=values.shape[1], height=values.shape[0], count=1,
        dtype="float32", crs=crs, nodata=nodata,
        transform=transform or Affine(100.0, 0.0, 447000.0, 0.0, -100.0, 4637000.0),
    ) as target:
        target.write(values, 1)
    return rasterio.open(path)


def _band(envelope, band="band_1"):
    """An envelope's band as rows north to south, NaN for nodata."""
    grid = envelope["data"]["grid"]
    properties = envelope["data"]["features"][0]["properties"]
    values = np.frombuffer(base64.b64decode(properties[band]["float32le"]), dtype="<f4")
    return values.reshape(grid["height"], grid["width"])[::-1]


def _as_lists(array):
    return [[None if math.isnan(v) else float(v) for v in row] for row in np.asarray(array).tolist()]


# ---------------------------------------------------------------------------
# Layers and tables
# ---------------------------------------------------------------------------

class TestLayersJoinedOnAStableId:
    def test_rows_on_both_sides_hold_comparison_minus_reference(self):
        out = _diff(_roads([1, 2, 3], [5.0, 6.0, 7.0]), _roads([1, 2, 3], [5.0, 3.0, 7.5]))
        assert list(out.columns) == ["osm_id", "change", "sunlight", "name", "geometry"]
        assert out["osm_id"].tolist() == [1, 2, 3]
        assert _numbers(out["sunlight"]) == [0.0, -3.0, 0.5]
        assert out["change"].tolist() == ["unchanged", "changed", "changed"]

    def test_a_row_only_in_the_reference_is_removed_and_one_only_in_the_comparison_added(self):
        out = _diff(_roads([1, 2, 3], [5.0, 6.0, 7.0]), _roads([2, 3, 4], [6.0, 3.5, 1.0]))
        # The reference's rows in its order, then the rows only the comparison has.
        assert out["osm_id"].tolist() == [1, 2, 3, 4]
        assert out["change"].tolist() == ["removed", "unchanged", "changed", "added"]
        # A row on one side only has no difference to give.
        assert _numbers(out["sunlight"]) == [None, 0.0, -3.5, None]

    def test_other_columns_and_the_geometry_are_the_comparisons_and_a_removed_rows_the_references(self):
        reference = _roads([1, 2], [5.0, 6.0], names=["Main St", "Oak Ave"])
        comparison = _roads([2, 3], [6.0, 1.0], names=["Oak Avenue", "New Rd"])
        comparison.loc[0, "geometry"] = Point(20, 20)
        out = _diff(reference, comparison)
        assert out["name"].tolist() == ["Main St", "Oak Avenue", "New Rd"]
        assert [(g.x, g.y) for g in out.geometry] == [(1.0, 1.0), (20.0, 20.0), (3.0, 3.0)]
        # The name changed, so the row did, though its number did not.
        assert out["change"].tolist() == ["removed", "changed", "added"]

    def test_the_difference_is_a_layer_in_the_inputs_coordinate_system(self):
        out = _diff(_roads([1], [5.0], crs="EPSG:3857"), _roads([1], [4.0], crs="EPSG:3857"))
        assert isinstance(out, gpd.GeoDataFrame)
        assert out.crs.to_epsg() == 3857
        assert out.geometry.name == "geometry"

    def test_a_layer_with_no_coordinate_system_takes_the_others(self, capsys):
        out = _diff(_roads([1], [5.0], crs=None), _roads([1], [4.0], crs="EPSG:4326"))
        assert out.crs.to_epsg() == 4326
        assert "input 0 (Baseline) names no coordinate system" in capsys.readouterr().out

    def test_buildings_are_joined_on_building_id(self):
        reference = gpd.GeoDataFrame({"building_id": [10, 11], "height": [9.0, 12.0]}, geometry=[Point(0, 0), Point(1, 1)])
        comparison = gpd.GeoDataFrame({"building_id": [10, 11], "height": [18.0, 24.0]}, geometry=[Point(0, 0), Point(1, 1)])
        out = _diff(reference, comparison)
        assert list(out.columns)[:2] == ["building_id", "change"]
        assert _numbers(out["height"]) == [9.0, 12.0]

    def test_osm_id_comes_first_when_both_ids_are_there(self):
        reference = _roads([1, 2], [5.0, 6.0]).assign(building_id=[7, 7])
        out = _diff(reference, _roads([1, 2], [5.0, 6.0]).assign(building_id=[7, 7]))
        assert list(out.columns)[0] == "osm_id"

    def test_the_key_the_node_names_wins(self):
        reference = pd.DataFrame({"segment": ["r1", "r2"], "osm_id": [1, 2], "sunlight": [6.0, 5.0]})
        comparison = pd.DataFrame({"segment": ["r2", "r1"], "osm_id": [9, 8], "sunlight": [2.5, 3.0]})
        out = _diff(reference, comparison, key="segment")
        assert out["segment"].tolist() == ["r1", "r2"]
        assert _numbers(out["sunlight"]) == [-3.0, -2.5]
        # The ids it was not joined on differ, as numbers do.
        assert _numbers(out["osm_id"]) == [7.0, 7.0]

    def test_two_tables_give_a_table(self):
        reference = pd.DataFrame({"osm_id": [1, 2], "sunlight": [6.0, 5.0], "lit": [True, False]})
        comparison = pd.DataFrame({"osm_id": [1, 2], "sunlight": [3.0, 5.0], "lit": [True, True]})
        out = _diff(reference, comparison)
        assert type(out) is pd.DataFrame
        assert _numbers(out["sunlight"]) == [-3.0, 0.0]
        # A true or false is not a number to subtract: it is the comparison's.
        assert out["lit"].tolist() == [True, True]
        assert out["change"].tolist() == ["changed", "changed"]

    def test_a_column_only_one_side_has_is_kept_from_that_side(self):
        reference = pd.DataFrame({"osm_id": [1, 2], "sunlight": [6.0, 5.0], "old": ["a", "b"]})
        comparison = pd.DataFrame({"osm_id": [2, 3], "sunlight": [5.0, 1.0], "new": ["x", "y"]})
        out = _diff(reference, comparison)
        assert list(out.columns) == ["osm_id", "change", "sunlight", "old", "new"]
        assert [None if pd.isna(v) else v for v in out["old"]] == ["a", "b", None]
        assert [None if pd.isna(v) else v for v in out["new"]] == [None, "x", "y"]

    def test_empty_cells_on_both_sides_are_the_same(self):
        reference = pd.DataFrame({"osm_id": [1, 2], "sunlight": [np.nan, 5.0], "name": [None, "b"]})
        comparison = pd.DataFrame({"osm_id": [1, 2], "sunlight": [np.nan, np.nan], "name": [None, "b"]})
        out = _diff(reference, comparison)
        assert out["change"].tolist() == ["unchanged", "changed"]

    def test_a_layer_an_autark_node_hands_on_is_read_as_a_layer(self):
        envelope = {
            "dataType": "geodataframe",
            "layerName": "roads",
            "data": {
                "type": "FeatureCollection",
                "features": [
                    {"type": "Feature", "properties": {"osm_id": i, "sunlight": s}, "geometry": {"type": "Point", "coordinates": [i, i]}}
                    for i, s in ((1, 5.0), (2, 6.0))
                ],
            },
        }
        out = _diff(envelope, _roads([1, 2], [4.0, 6.0]))
        assert isinstance(out, gpd.GeoDataFrame)
        assert out["osm_id"].tolist() == [1, 2]
        assert _numbers(out["sunlight"]) == [-1.0, 0.0]

    def test_the_inputs_are_left_as_they_were(self):
        reference = _roads([1, 2], [5.0, 6.0])
        comparison = _roads([2, 3], [1.0, 2.0])
        before = (reference.copy(), comparison.copy())
        _diff(reference, comparison)
        pd.testing.assert_frame_equal(reference, before[0])
        pd.testing.assert_frame_equal(comparison, before[1])


class TestWhatTheJoinRefuses:
    def test_anything_but_two_inputs(self):
        with pytest.raises(ValueError, match=r"compares two inputs, a reference and a comparison, and it has 3"):
            difference().difference_scenarios([("a", "A", 1), ("b", "B", 2), ("c", "C", 3)])
        with pytest.raises(ValueError, match="and it has 1"):
            difference().difference_scenarios([("a", "A", _roads([1], [1.0]))])

    def test_a_layer_beside_a_table_names_both(self):
        table = pd.DataFrame({"osm_id": [1], "sunlight": [1.0]})
        with pytest.raises(ValueError, match=r"input 0 \(Baseline\) is a layer while input 1 \(Twice as tall\) is a table"):
            _diff(_roads([1], [1.0]), table)

    def test_a_raster_beside_a_layer_names_both(self, tmp_path):
        raster = _raster(tmp_path / "r.tif", [[1.0]])
        with pytest.raises(ValueError, match=r"input 0 \(Baseline\) is a raster while input 1 \(Twice as tall\) is a layer"):
            _diff(raster, _roads([1], [1.0]))

    def test_no_stable_id_names_the_columns_both_have(self):
        reference = pd.DataFrame({"segment": ["r1"], "sunlight": [1.0]})
        comparison = pd.DataFrame({"segment": ["r1"], "sunlight": [2.0]})
        with pytest.raises(ValueError, match=r"they do not both have osm_id or building_id\. Pick a key both have: segment, sunlight\."):
            _diff(reference, comparison)

    def test_a_key_one_input_lacks(self):
        reference = pd.DataFrame({"segment": ["r1"], "sunlight": [1.0]})
        comparison = pd.DataFrame({"part": ["r1"], "sunlight": [2.0]})
        with pytest.raises(ValueError, match=r"input 1 \(Twice as tall\) has no column segment to join on"):
            _diff(reference, comparison, key="segment")

    def test_a_key_that_repeats_names_the_input_and_the_id(self):
        with pytest.raises(ValueError, match=r"input 1 \(Twice as tall\) has 2 rows with osm_id 7"):
            _diff(_roads([1, 7], [1.0, 2.0]), _roads([7, 7], [1.0, 2.0]))

    def test_rows_with_no_key(self):
        reference = pd.DataFrame({"osm_id": [1.0, np.nan], "sunlight": [1.0, 2.0]})
        with pytest.raises(ValueError, match=r"input 0 \(Baseline\) has 1 row with no osm_id"):
            _diff(reference, pd.DataFrame({"osm_id": [1.0], "sunlight": [1.0]}))

    def test_two_coordinate_systems(self):
        with pytest.raises(ValueError, match="different coordinate systems"):
            _diff(_roads([1], [1.0], crs="EPSG:4326"), _roads([1], [1.0], crs="EPSG:3857"))

    def test_a_column_the_difference_adds_itself(self):
        reference = pd.DataFrame({"osm_id": [1], "change": ["x"]})
        with pytest.raises(ValueError, match=r"input 0 \(Baseline\) already has a column named change"):
            _diff(reference, pd.DataFrame({"osm_id": [1]}))

    def test_an_input_with_no_value(self):
        with pytest.raises(ValueError, match=r"input 1 \(Twice as tall\) has no value"):
            _diff(_roads([1], [1.0]), None)

    def test_an_entry_that_is_not_scenario_name_and_input(self):
        with pytest.raises(TypeError, match="entry 1 is not"):
            difference().difference_scenarios([("a", "A", 1), ("b", 2)])


# ---------------------------------------------------------------------------
# Rasters: the request the node's code returns
# ---------------------------------------------------------------------------

class TestTheRasterRequest:
    def test_two_rasters_come_back_as_a_request_of_json_alone(self, tmp_path):
        import rasterio
        from rasterio.io import MemoryFile

        reference = rasterio.open(FIXTURE)
        comparison = _raster(tmp_path / "c.tif", reference.read(1) + 1)
        request = _diff(reference, comparison)
        assert difference().is_raster_request(request)
        # It crosses the isolation protocol and the store as plain JSON.
        assert json.loads(json.dumps(request, allow_nan=False)) == request
        side = request["reference"]
        assert (side["scenario"], side["name"], side["label"]) == ("s-base", "Baseline", "input 0 (Baseline)")
        assert request["comparison"]["label"] == "input 1 (Twice as tall)"
        # The description the raster route serves, which the browser loads by.
        assert side["meta"]["crs"] == "EPSG:32616"
        assert side["meta"]["transform"] == [100.0, 0.0, 447000.0, 0.0, -100.0, 4637000.0]
        with MemoryFile(base64.b64decode(side["geotiff"])) as memory, memory.open() as copy:
            assert (copy.width, copy.height) == (reference.width, reference.height)
            assert copy.read(1).tolist() == reference.read(1).tolist()

    def test_a_raster_larger_than_an_autark_map_loads_is_refused_before_it_is_written(self, tmp_path):
        import rasterio
        from affine import Affine

        path = tmp_path / "large.tif"
        with rasterio.open(
            path, "w", driver="GTiff", width=2049, height=2048, count=1, dtype="uint8",
            crs="EPSG:32616", transform=Affine(1, 0, 0, 0, -1, 0), compress="DEFLATE",
        ) as target:
            target.write(np.zeros((2048, 2049), dtype="uint8"), 1)
        large = rasterio.open(path)
        with pytest.raises(ValueError, match=r"input 1 \(Twice as tall\) is 2049 by 2048 cells, more than an Autark map loads"):
            _diff(rasterio.open(FIXTURE), large)

    def test_the_size_it_refuses_is_the_size_an_autark_map_refuses(self):
        text = RASTER_LOAD_TS.read_text(encoding="utf-8")
        cells = re.search(r"export const RASTER_MAX_CELLS = (\d+) \* (\d+);", text)
        side = re.search(r"export const RASTER_MAX_SIDE = (\d+);", text)
        assert cells and side
        assert difference().MAX_CELLS == int(cells.group(1)) * int(cells.group(2))
        assert difference().MAX_SIDE == int(side.group(1))

    def test_only_a_request_is_one(self):
        assert not difference().is_raster_request({"dataType": "raster-difference"})
        assert not difference().is_raster_request({"dataType": "dict", "reference": {}, "comparison": {}})
        assert not difference().is_raster_request([1, 2])


# ---------------------------------------------------------------------------
# Rasters: subtracted through Autark, in the sandbox's Node process
# ---------------------------------------------------------------------------

class TestRastersSubtractedThroughAutark:
    """The request run for real: autk-db loads both rasters in Node, and Curio's
    Autark adapter subtracts what ``getRaster`` exports."""

    def _subtract(self, reference, comparison, tmp_path):
        request = _diff(reference, comparison)
        return difference().subtract_in_autark(request, cwd=str(tmp_path))

    def test_the_difference_is_comparison_minus_reference_cell_by_cell(self, tmp_path):
        import rasterio

        reference = rasterio.open(FIXTURE)
        doubled = reference.read(1, masked=True) * 2
        comparison = _raster(tmp_path / "doubled.tif", doubled.filled(reference.nodata))
        envelope = self._subtract(reference, comparison, tmp_path)
        assert envelope["dataType"] == "raster"
        assert envelope["data"]["grid"] == {
            "crs": "EPSG:32616", "width": 40, "height": 30,
            "originX": 447000, "originY": 4637000, "resX": 100, "resY": -100,
        }
        expected = reference.read(1, masked=True).astype("float32").filled(np.nan)
        assert _as_lists(_band(envelope)) == _as_lists(expected)
        # Nodata on either side is nodata in the difference.
        assert int(np.isnan(_band(envelope)).sum()) == int(np.ma.getmaskarray(reference.read(1, masked=True)).sum()) > 0

    def test_the_sign_follows_which_input_is_the_reference(self, tmp_path):
        a = _raster(tmp_path / "a.tif", [[1.0, 2.0], [3.0, 4.0]])
        b = _raster(tmp_path / "b.tif", [[11.0, 12.0], [13.0, -9999.0]])
        assert _as_lists(_band(self._subtract(a, b, tmp_path))) == [[10.0, 10.0], [10.0, None]]
        assert _as_lists(_band(self._subtract(b, a, tmp_path))) == [[-10.0, -10.0], [-10.0, None]]

    def test_grids_that_differ_in_size_are_refused_naming_both(self, tmp_path):
        import rasterio

        reference = rasterio.open(FIXTURE)
        cropped = _raster(tmp_path / "crop.tif", reference.read(1)[:, :20])
        with pytest.raises(difference().RasterDifferenceFailed) as refused:
            self._subtract(reference, cropped, tmp_path)
        message = str(refused.value)
        assert "input 1 (Twice as tall) minus input 0 (Baseline) cannot be computed: their grids differ in size." in message
        assert "input 0 (Baseline) is 40 by 30 cells" in message
        assert "input 1 (Twice as tall) is 20 by 30 cells" in message

    def test_grids_that_differ_in_origin_resolution_and_crs_are_refused_naming_each(self, tmp_path):
        from affine import Affine

        a = _raster(tmp_path / "a.tif", [[1.0, 2.0], [3.0, 4.0]])
        moved = _raster(tmp_path / "moved.tif", [[1.0, 2.0], [3.0, 4.0]],
                        transform=Affine(50.0, 0.0, 447100.0, 0.0, -50.0, 4637000.0))
        with pytest.raises(difference().RasterDifferenceFailed, match="their grids differ in origin, resolution"):
            self._subtract(a, moved, tmp_path)
        other_crs = _raster(tmp_path / "crs.tif", [[1.0, 2.0], [3.0, 4.0]], crs="EPSG:32617")
        with pytest.raises(difference().RasterDifferenceFailed, match="their grids differ in CRS"):
            self._subtract(a, other_crs, tmp_path)

    def test_a_raster_with_no_crs_is_refused_as_an_autark_map_refuses_it(self, tmp_path):
        a = _raster(tmp_path / "a.tif", [[1.0]])
        bare = _raster(tmp_path / "bare.tif", [[1.0]], crs=None)
        with pytest.raises(difference().RasterDifferenceFailed, match=r"input 1 \(Twice as tall\) has no CRS, so Autark cannot place it"):
            self._subtract(a, bare, tmp_path)


# ---------------------------------------------------------------------------
# The sandbox completes the request, whichever path ran the node's code
# ---------------------------------------------------------------------------

#: A Compare Scenarios node in Difference whose two inputs are rasters: the
#: committed GeoTIFF and the same raster doubled, which it writes itself.
NODE_CODE = (
    "    import rasterio\n"
    "    reference = rasterio.open({fixture!r})\n"
    "    band = reference.read(1, masked=True) * 2\n"
    "    with rasterio.open({doubled!r}, 'w', **reference.profile) as target:\n"
    "        target.write(band.filled(reference.nodata).astype('float32'), 1)\n"
    "    return curio_difference_scenarios([\n"
    "        ('s-base', 'Baseline', reference),\n"
    "        ('s-tall', 'Twice as tall', rasterio.open({doubled!r})),\n"
    "    ])\n"
)


def _expected_difference():
    import rasterio

    with rasterio.open(FIXTURE) as reference:
        return _as_lists(reference.read(1, masked=True).astype("float32").filled(np.nan))


class TestTheSandboxCompletesTheRequest:
    def test_in_process(self, store):
        from utk_curio.sandbox.app.worker import _worker_init, execute_code
        from utk_curio.sandbox.util.parsers import load_artifact

        _worker_init()
        code = NODE_CODE.format(fixture=str(FIXTURE), doubled=str(store / "doubled.tif"))
        result = execute_code(code, "", COMPARE, "", save_dataset=False)
        assert result["stderr"] == ""
        # The node's code hands back the request; the sandbox subtracts.
        assert difference().is_raster_request(load_artifact(result["output"]["path"]))
        completed = difference().complete_raster_difference(result, node_type=COMPARE, launch_dir=str(store))
        assert completed["output"]["dataType"] == "dict"
        envelope = load_artifact(completed["output"]["path"])
        assert envelope["dataType"] == "raster"
        assert _as_lists(_band(envelope)) == _expected_difference()

    def test_the_exec_route_completes_it(self, store):
        from utk_curio.sandbox.app import app
        from utk_curio.sandbox.util.parsers import load_artifact

        code = NODE_CODE.format(fixture=str(FIXTURE), doubled=str(store / "doubled.tif"))
        response = app.test_client().post("/exec", json={
            "code": code, "file_path": "", "nodeType": COMPARE, "dataType": "",
            "session_id": None, "save_dataset": False,
        })
        assert response.status_code == 200
        reply = response.get_json()
        assert reply["stderr"] == "", reply["stderr"]
        envelope = load_artifact(reply["output"]["path"])
        assert envelope["dataType"] == "raster"
        assert _as_lists(_band(envelope)) == _expected_difference()

    def test_in_an_isolated_child(self, store, tmp_path):
        """The child, which may not start Node, returns the request as JSON;
        the parent stores it as it stores any output, and completes it."""
        from utk_curio.sandbox.isolation import child, runner, supervisor, zygote
        from utk_curio.sandbox.util.parsers import load_artifact

        scratch = tmp_path / "scratch"
        scratch.mkdir()
        request = {
            "code": NODE_CODE.format(fixture=str(FIXTURE), doubled=str(scratch / "doubled.tif")),
            "node_type": COMPARE, "data_type": "",
            "scratch_dir": str(scratch), "input": {"kind": "none"},
            "session_imports": [], "limits": {},
        }
        manifest = child.run_node(request, zygote.build_namespace_template)
        assert manifest["ok"], manifest["stderr"]
        # What the parent reads back from the child, and files away.
        child.write_result(manifest, str(scratch))
        descriptor = supervisor.read_child_manifest(str(scratch))["output"]
        assert descriptor["kind"] == "dict"
        art_id, _dataset = runner._persist_output(
            descriptor, node_type=COMPARE, session_id=None, save_dataset=False,
        )
        completed = difference().complete_raster_difference(
            {"stdout": [], "stderr": "", "output": {"path": art_id, "dataType": "dict"}},
            node_type=COMPARE, launch_dir=str(store),
        )
        envelope = load_artifact(completed["output"]["path"])
        assert _as_lists(_band(envelope)) == _expected_difference()

    def test_a_refusal_is_the_nodes_error(self, store, tmp_path):
        from utk_curio.sandbox.util.parsers import save_to_duckdb

        a = _raster(tmp_path / "a.tif", [[1.0, 2.0]])
        b = _raster(tmp_path / "b.tif", [[1.0, 2.0, 3.0]])
        art_id = save_to_duckdb(_diff(a, b), COMPARE)
        completed = difference().complete_raster_difference(
            {"stdout": [], "stderr": "", "output": {"path": art_id, "dataType": "dict"}},
            node_type=COMPARE, launch_dir=str(store),
        )
        assert completed["output"] == {"path": "", "dataType": "str"}
        assert completed["stderr"].startswith(
            "Compare Scenarios: input 1 (Twice as tall) minus input 0 (Baseline) cannot be computed"
        )

    def test_any_other_output_is_left_as_it_came(self, store):
        from utk_curio.sandbox.util.parsers import save_to_duckdb

        art_id = save_to_duckdb({"dataType": "raster", "note": "not a request"}, COMPARE)
        result = {"stdout": [], "stderr": "", "output": {"path": art_id, "dataType": "dict"}}
        assert difference().complete_raster_difference(result, node_type=COMPARE, launch_dir=str(store)) is result
        table = {"stdout": [], "stderr": "", "output": {"path": "x", "dataType": "dataframe"}}
        assert difference().complete_raster_difference(table, node_type=COMPARE) is table


class TestNodeCodeReachesIt:
    """The node's code calls it by name, in process and under isolation."""

    def test_an_in_process_node(self):
        from utk_curio.sandbox.app import worker

        worker._worker_init()
        assert worker._globals_cache["curio_difference_scenarios"] is difference().difference_scenarios

    def test_an_isolated_node(self):
        from utk_curio.sandbox.isolation import zygote

        assert zygote.build_namespace_template()["curio_difference_scenarios"] is difference().difference_scenarios
