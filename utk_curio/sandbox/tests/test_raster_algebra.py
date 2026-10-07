"""Curio's raster algebra (``util/raster_algebra.py``) and its raster helpers
(``util/rasters.py``): one implementation of operations over rasters.

- Compare Scenarios' Difference subtracts two Autark envelopes: the comparison
  minus the reference, cell by cell, on one grid, two grids that differ refused
  with both named. These are the cases ``rasterArithmetic.test.ts`` held when
  the subtraction was Curio's Autark adapter's.
- The Raster Calculator computes on rasterio datasets at their own number
  type, nodata as NaN; Raster Statistics gives numpy's numbers on a band.
- ``curio_load_data("<id>", bounds=...)`` reads the cells whose centres lie in
  the bounds, on the raster's own grid.
- Map tiles are laid side by side on their own grid.

Every test imports the module itself, so a checkout without it fails test by
test rather than at collection.
"""
from __future__ import annotations

import base64
import math
import os

import numpy as np
import pytest

GRID = {
    "crs": "EPSG:32616", "width": 3, "height": 2, "originX": 447000, "originY": 4637000, "resX": 30, "resY": -30,
}


def algebra():
    from utk_curio.sandbox.util import raster_algebra as module

    return module


def rasters():
    from utk_curio.sandbox.util import rasters as module

    return module


# ---------------------------------------------------------------------------
# Envelopes, as autk-db's getRaster exports them
# ---------------------------------------------------------------------------

def _envelope(values: dict, grid: dict = GRID) -> dict:
    properties = {
        "rasterResX": grid["width"],
        "rasterResY": grid["height"],
        "bands": [{"id": band, "label": band} for band in values],
    }
    for band, cells in values.items():
        array = np.array([np.nan if v is None else v for v in cells], dtype="<f4")
        properties[band] = {"float32le": base64.b64encode(array.tobytes()).decode("ascii")}
    return {
        "dataType": "raster",
        "data": {
            "type": "FeatureCollection",
            "bbox": [-9785700, 5110100, -9785610, 5110160],
            "grid": dict(grid),
            "features": [{"type": "Feature", "geometry": None, "properties": properties}],
        },
    }


def _cells(envelope: dict, band: str = "band_1") -> list:
    wire = envelope["data"]["features"][0]["properties"][band]["float32le"]
    return [None if math.isnan(v) else float(v) for v in np.frombuffer(base64.b64decode(wire), dtype="<f4")]


class TestSubtractEnvelopes:
    def test_the_result_is_the_comparison_minus_the_reference_positive_where_it_is_higher(self):
        result = algebra().subtract_envelopes(
            ("No NbS", _envelope({"band_1": [1, 2, 3, 4, 5, 6]})),
            ("NbS", _envelope({"band_1": [1, 5, 1, 4.5, 15, 0]})),
        )
        assert _cells(result) == [0, 3, -2, 0.5, 10, -6]

    def test_swapping_the_two_flips_every_sign(self):
        a = ("A", _envelope({"band_1": [1, 2, 3, 4, 5, 6]}))
        b = ("B", _envelope({"band_1": [6, 5, 4, 3, 2, 1]}))
        assert _cells(algebra().subtract_envelopes(a, b)) == [5, 3, 1, -1, -3, -5]
        assert _cells(algebra().subtract_envelopes(b, a)) == [-5, -3, -1, 1, 3, 5]

    def test_a_nodata_cell_on_either_side_is_nodata_in_the_result(self):
        result = algebra().subtract_envelopes(
            ("A", _envelope({"band_1": [None, 2, 3, 4, 5, 6]})),
            ("B", _envelope({"band_1": [1, 2, None, 4, 5, 6]})),
        )
        assert _cells(result) == [None, 0, None, 0, 0, 0]

    def test_every_band_is_subtracted_and_the_result_is_a_raster_collection_autk_map_draws(self):
        result = algebra().subtract_envelopes(
            ("A", _envelope({"band_1": [1] * 6, "band_2": [2] * 6})),
            ("B", _envelope({"band_1": [3] * 6, "band_2": [0] * 6})),
        )
        assert _cells(result, "band_1") == [2] * 6
        assert _cells(result, "band_2") == [-2] * 6
        # The shape autk-map's loadCollection({type: 'raster', property}) reads.
        assert result["dataType"] == "raster"
        collection = result["data"]
        assert collection["type"] == "FeatureCollection"
        assert len(collection["bbox"]) == 4
        assert collection["grid"] == GRID
        (feature,) = collection["features"]
        assert feature["geometry"] is None
        assert feature["properties"]["rasterResX"] == 3
        assert feature["properties"]["rasterResY"] == 2
        assert feature["properties"]["bands"] == [{"id": "band_1", "label": "band_1"}, {"id": "band_2", "label": "band_2"}]

    def test_the_difference_is_float32_of_the_exact_difference(self):
        """Each cell is the float32 nearest the difference of the two float32
        values, as a Float32Array holds a number."""
        a = np.float32(0.1)
        b = np.float32(16777217.0)
        result = algebra().subtract_envelopes(("A", _envelope({"band_1": [float(a)] * 6})),
                                              ("B", _envelope({"band_1": [float(b)] * 6})))
        assert _cells(result)[0] == float(np.float32(float(b) - float(a)))

    def test_it_keeps_the_references_properties_and_takes_the_comparisons_extent_and_grid(self):
        reference = _envelope({"band_1": [1] * 6})
        reference["data"]["features"][0]["properties"]["note"] = "from the reference"
        comparison = _envelope({"band_1": [2] * 6}, {**GRID, "originX": GRID["originX"] + 1e-7})
        comparison["data"]["bbox"] = [1, 2, 3, 4]
        result = algebra().subtract_envelopes(("A", reference), ("B", comparison))
        assert result["data"]["features"][0]["properties"]["note"] == "from the reference"
        assert result["data"]["bbox"] == [1, 2, 3, 4]
        assert result["data"]["grid"] == comparison["data"]["grid"]

    @pytest.mark.parametrize("what,change", [
        ("size", {"width": 2, "height": 3}),
        ("origin", {"originX": 447030}),
        ("resolution", {"resX": 10, "resY": -10}),
        ("CRS", {"crs": "EPSG:26916"}),
    ])
    def test_grids_that_differ_are_refused_naming_both(self, what, change):
        other = {**GRID, **change}
        with pytest.raises(algebra().RasterAlgebraError) as refused:
            algebra().subtract_envelopes(
                ("Reference depth", _envelope({"band_1": [1, 2, 3, 4, 5, 6]})),
                ("Comparison depth", _envelope({"band_1": [1, 2, 3, 4, 5, 6]}, other)),
            )
        describe = algebra().describe_grid
        assert str(refused.value) == (
            f"Comparison depth minus Reference depth cannot be computed: their grids differ in {what}. "
            f"Reference depth is {describe(GRID)}; Comparison depth is {describe(other)}. "
            "Put both on one grid first."
        )

    def test_bands_that_differ_are_refused_naming_both(self):
        with pytest.raises(algebra().RasterAlgebraError) as refused:
            algebra().subtract_envelopes(
                ("A", _envelope({"band_1": [1, 2, 3, 4, 5, 6]})),
                ("B", _envelope({"band_1": [1, 2, 3, 4, 5, 6], "band_2": [1, 2, 3, 4, 5, 6]})),
            )
        assert str(refused.value) == "B minus A cannot be computed: their bands differ. A has band_1; B has band_1, band_2."


class TestGrids:
    def test_the_same_grid_up_to_rounding_in_its_coordinates_differs_in_nothing(self):
        assert algebra().grid_differences(GRID, {**GRID, "originX": GRID["originX"] + 1e-7, "crs": "epsg:32616"}) == []

    def test_it_names_every_way_two_grids_differ(self):
        other = {**GRID, "width": 4, "originY": 0, "resY": -10, "crs": "EPSG:4326"}
        assert algebra().grid_differences(GRID, other) == ["size", "origin", "resolution", "CRS"]

    def test_a_grid_in_words(self):
        assert algebra().describe_grid(GRID) == "3 by 2 cells of 30 by 30 in EPSG:32616 from (447000, 4637000)"

    @pytest.mark.parametrize("value,text", [
        (30.0, "30"), (-0.0, "0"), (100, "100"), (1.5, "1.5"), (-2.5, "-2.5"),
        (0.1 + 0.2, "0.30000000000000004"), (1e-7, "1e-7"), (0.000001, "0.000001"),
        (-2.5e-8, "-2.5e-8"), (1e21, "1e+21"), (123456789012345680000.0, "123456789012345680000"),
        (0.00010133941049058334, "0.00010133941049058334"), (-90.4836, "-90.4836"),
    ])
    def test_numbers_are_written_as_javascript_writes_them(self, value, text):
        assert algebra().js_number(value) == text


# ---------------------------------------------------------------------------
# rasterio datasets
# ---------------------------------------------------------------------------

def _raster(path, values, *, dtype="float32", nodata=-9999.0, transform=None, crs="EPSG:32616",
            descriptions=None):
    """A GeoTIFF of *values*: rows north to south, one band or (bands, rows, columns)."""
    import rasterio
    from affine import Affine

    array = np.asarray(values, dtype=dtype)
    if array.ndim == 2:
        array = array[np.newaxis]
    with rasterio.open(
        path, "w", driver="GTiff", width=array.shape[2], height=array.shape[1], count=array.shape[0],
        dtype=dtype, crs=crs, transform=transform or Affine(30.0, 0.0, 447000.0, 0.0, -30.0, 4637000.0),
        nodata=nodata,
    ) as target:
        target.write(array)
        for index, description in enumerate(descriptions or (), start=1):
            target.set_band_description(index, description)
    return rasterio.open(path)


@pytest.fixture
def out(tmp_path):
    folder = tmp_path / "out"
    folder.mkdir()
    return lambda name: str(folder / name)


def _values(dataset, band=1):
    return [[None if math.isnan(v) else float(v) for v in row] for row in dataset.read(band)]


class TestCalculate:
    @pytest.mark.parametrize("operation,expected", [
        ("add", [[7.0, 9.0], [11.0, 13.0]]),
        ("subtract", [[5.0, 5.0], [5.0, 5.0]]),
        ("multiply", [[6.0, 14.0], [24.0, 36.0]]),
        ("divide", [[6.0, 3.5], [8.0 / 3.0, 2.25]]),
    ])
    def test_input_0_with_input_1(self, tmp_path, out, operation, expected):
        a = _raster(tmp_path / "a.tif", [[6.0, 7.0], [8.0, 9.0]])
        b = _raster(tmp_path / "b.tif", [[1.0, 2.0], [3.0, 4.0]])
        result = algebra().calculate(operation, [a, b], output_file=out)
        assert _values(result) == [[float(np.float32(v)) for v in row] for row in expected]

    def test_a_cell_divided_by_0_has_no_value(self, tmp_path, out):
        a = _raster(tmp_path / "a.tif", [[1.0, 2.0]])
        b = _raster(tmp_path / "b.tif", [[0.0, 4.0]])
        assert _values(algebra().calculate("divide", (a, b), output_file=out)) == [[None, 0.5]]

    def test_a_cell_with_no_value_in_an_input_has_none_in_the_result(self, tmp_path, out):
        a = _raster(tmp_path / "a.tif", [[-9999.0, 2.0, np.nan, 4.0]])
        b = _raster(tmp_path / "b.tif", [[1.0, -9999.0, 3.0, 1.0]])
        assert _values(algebra().calculate("add", [a, b], output_file=out)) == [[None, None, None, 5.0]]

    def test_choose_takes_input_1_where_the_class_is_one_of_the_codes_and_input_2_elsewhere(self, tmp_path, out):
        classes = _raster(tmp_path / "classes.tif", [[21, 31, 43, 0, 21]], dtype="uint8", nodata=0)
        nbs = _raster(tmp_path / "nbs.tif", [[1.0, 2.0, 3.0, 4.0, -9999.0]])
        no_nbs = _raster(tmp_path / "no_nbs.tif", [[10.0, 20.0, 30.0, 40.0, 50.0]])
        result = algebra().calculate("choose", [classes, nbs, no_nbs], codes=[21, 31], output_file=out)
        # 43 is not chosen; a nodata class is no class; a chosen cell with no
        # value has none in the result.
        assert _values(result) == [[1.0, 2.0, 30.0, 40.0, None]]
        assert _values(algebra().calculate("choose", [classes, nbs, no_nbs], codes=[], output_file=out)) == [
            [10.0, 20.0, 30.0, 40.0, 50.0]
        ]

    def test_a_float64_raster_keeps_every_digit(self, tmp_path, out):
        precise = [[5.788970947265625, 3.7056172688802085], [0.1 + 0.2, 7.083333333333334]]
        a = _raster(tmp_path / "a.tif", precise, dtype="float64")
        zero = _raster(tmp_path / "zero.tif", [[0.0, 0.0], [0.0, 0.0]], dtype="float64")
        result = algebra().calculate("add", [a, zero], output_file=out)
        assert result.dtypes[0] == "float64"
        assert _values(result) == precise

    def test_integer_rasters_are_computed_in_float32(self, tmp_path, out):
        a = _raster(tmp_path / "a.tif", [[200, 250]], dtype="uint8", nodata=None)
        b = _raster(tmp_path / "b.tif", [[100, 250]], dtype="uint8", nodata=None)
        result = algebra().calculate("add", [a, b], output_file=out)
        assert result.dtypes[0] == "float32"
        assert _values(result) == [[300.0, 500.0]]

    def test_the_result_is_a_raster_on_the_inputs_grid_named_after_its_content(self, tmp_path, out):
        from affine import Affine

        transform = Affine(0.5, 0.0, -90.0, 0.0, -0.5, 41.0)
        a = _raster(tmp_path / "a.tif", [[1.0, 2.0]], transform=transform, crs="EPSG:4326", descriptions=["depth"])
        b = _raster(tmp_path / "b.tif", [[1.0, 1.0]], transform=transform, crs="EPSG:4326")
        result = algebra().calculate("subtract", [a, b], output_file=out)
        assert tuple(result.transform)[:6] == tuple(transform)[:6]
        assert result.crs.to_epsg() == 4326
        assert math.isnan(result.nodata)
        assert result.descriptions == ("depth",)
        assert os.path.dirname(result.name) == os.path.dirname(out("x"))
        again = algebra().calculate("subtract", [a, b], output_file=out)
        assert again.name == result.name
        other = algebra().calculate("add", [a, b], output_file=out)
        assert other.name != result.name

    def test_every_band_is_computed_and_a_class_raster_of_one_band_applies_to_each(self, tmp_path, out):
        classes = _raster(tmp_path / "classes.tif", [[1, 2]], dtype="uint8", nodata=0)
        a = _raster(tmp_path / "a.tif", [[[1.0, 1.0]], [[2.0, 2.0]]])
        b = _raster(tmp_path / "b.tif", [[[5.0, 5.0]], [[6.0, 6.0]]])
        result = algebra().calculate("choose", [classes, a, b], codes=[1], output_file=out)
        assert result.count == 2
        assert _values(result, 1) == [[1.0, 5.0]]
        assert _values(result, 2) == [[2.0, 6.0]]

    def test_grids_that_differ_are_refused_naming_both(self, tmp_path, out):
        from affine import Affine

        a = _raster(tmp_path / "a.tif", [[1.0, 2.0]])
        b = _raster(tmp_path / "b.tif", [[1.0, 2.0]], transform=Affine(30.0, 0.0, 447030.0, 0.0, -30.0, 4637000.0))
        with pytest.raises(algebra().RasterAlgebraError) as refused:
            algebra().calculate("subtract", [a, b], output_file=out)
        assert str(refused.value) == (
            "subtract of input 0, input 1 cannot be computed: their grids differ in origin. "
            "input 0 is 2 by 1 cells of 30 by 30 in EPSG:32616 from (447000, 4637000); "
            "input 1 is 2 by 1 cells of 30 by 30 in EPSG:32616 from (447030, 4637000). Put both on one grid first."
        )

    @pytest.mark.parametrize("operation,count,codes,sentence", [
        ("power", 2, None, "The Raster Calculator has no operation 'power'. Its operations: add, subtract, multiply, divide, choose."),
        ("add", 3, None, "add reads 2 rasters, and the Raster Calculator has 3: connect one to each input circle."),
        ("choose", 2, [1], "choose reads 3 rasters, and the Raster Calculator has 2: connect one to each input circle."),
        ("choose", 3, None, "choose takes input 1 where input 0's class is one of codes, and input 2 elsewhere"),
        ("subtract", 2, [1], "Only choose reads codes; subtract takes none."),
        ("choose", 3, ["a"], "codes are numbers, such as [21, 31], not ['a']."),
    ])
    def test_what_it_cannot_compute_it_says_in_a_sentence(self, tmp_path, out, operation, count, codes, sentence):
        given = [_raster(tmp_path / f"r{i}.tif", [[1.0, 2.0]]) for i in range(count)]
        with pytest.raises(algebra().RasterAlgebraError) as refused:
            algebra().calculate(operation, given, codes=codes, output_file=out)
        assert sentence in str(refused.value)

    def test_an_input_that_is_not_a_raster_is_named(self, tmp_path, out):
        import pandas as pd

        a = _raster(tmp_path / "a.tif", [[1.0, 2.0]])
        with pytest.raises(algebra().RasterAlgebraError, match="input 1 is not a raster"):
            algebra().calculate("add", [a, pd.DataFrame({"x": [1]})], output_file=out)

    def test_bands_that_differ_are_refused(self, tmp_path, out):
        a = _raster(tmp_path / "a.tif", [[[1.0]], [[2.0]]])
        b = _raster(tmp_path / "b.tif", [[1.0]])
        with pytest.raises(algebra().RasterAlgebraError, match="their bands differ. input 0 has 2; input 1 has 1"):
            algebra().calculate("add", [a, b], output_file=out)


class TestStatistics:
    def test_mean_median_min_max_and_count_leave_nodata_out(self, tmp_path):
        a = _raster(tmp_path / "a.tif", [[1.0, 2.0, -9999.0], [np.nan, 4.0, 10.0]])
        table = algebra().statistics(a)
        assert list(table.columns) == ["mean", "median", "min", "max", "count"]
        assert len(table) == 1
        row = table.iloc[0]
        assert (row["mean"], row["median"], row["min"], row["max"], row["count"]) == (4.25, 3.0, 1.0, 10.0, 4)

    def test_the_numbers_are_numpys_on_the_bands_own_array(self, tmp_path):
        """np.nanmedian and np.nanmean on the band's 2-D float64 array, with
        nodata as NaN: the same numbers to the last bit."""
        rng = np.random.default_rng(662)
        cells = rng.random((97, 113)) * 10.0
        cells[rng.random(cells.shape) < 0.3] = np.nan
        a = _raster(tmp_path / "a.tif", cells, dtype="float64", nodata=None)
        row = algebra().statistics(a).iloc[0]
        assert row["median"] == np.nanmedian(cells)
        assert row["mean"] == np.nanmean(cells)
        assert row["count"] == int(np.count_nonzero(~np.isnan(cells)))

    def test_a_mask_keeps_the_cells_whose_value_is_one_of_mask_values(self, tmp_path):
        a = _raster(tmp_path / "a.tif", [[1.0, 2.0, 3.0, 4.0]])
        mask = _raster(tmp_path / "mask.tif", [[0, 0, 5, 255]], dtype="uint8", nodata=255)
        row = algebra().statistics(a, mask=mask, mask_values=[0]).iloc[0]
        assert (row["mean"], row["count"]) == (1.5, 2)
        # The mask may come on input 1, as the node's arg brings it.
        row = algebra().statistics([a, mask], mask_values=[0, 5]).iloc[0]
        assert (row["mean"], row["count"]) == (2.0, 3)

    def test_where_keeps_the_cells_that_meet_a_condition_on_the_raster_itself(self, tmp_path):
        a = _raster(tmp_path / "a.tif", [[0.5, 1.0, 1.08, 3.0, -9999.0]])
        row = algebra().statistics(a, where=lambda height: height < 1.08).iloc[0]
        assert (row["count"], row["max"]) == (2, 1.0)
        row = algebra().statistics(a, where=lambda v: (v >= 1.0) & (v < 5.0)).iloc[0]
        assert (row["count"], row["min"], row["max"]) == (3, 1.0, 3.0)

    def test_where_on_a_mask_tests_the_masks_values(self, tmp_path):
        """Deep Umbra's ground: the cells whose height is under 1.08 m count,
        and a cell with no height counts as none."""
        shadow = _raster(tmp_path / "shadow.tif", [[10.0, 20.0, 30.0, 40.0]])
        heights = _raster(tmp_path / "heights.tif", [[0.0, 1.07, 5.0, -9999.0]])
        seen = []

        def under(values):
            seen.append(values)
            return values < 1.08

        row = algebra().statistics([shadow, heights], where=under).iloc[0]
        assert (row["mean"], row["count"]) == (15.0, 2)
        assert seen[0].dtype == np.float64 and math.isnan(seen[0][0, 3])

    def test_a_raster_with_no_cell_left_counts_none(self, tmp_path):
        a = _raster(tmp_path / "a.tif", [[-9999.0, -9999.0]])
        row = algebra().statistics(a).iloc[0]
        assert row["count"] == 0
        assert all(math.isnan(row[name]) for name in ("mean", "median", "min", "max"))

    def test_another_band(self, tmp_path):
        a = _raster(tmp_path / "a.tif", [[[1.0, 1.0]], [[5.0, 7.0]]])
        assert algebra().statistics(a, band=2).iloc[0]["mean"] == 6.0

    def test_what_it_cannot_compute_it_says_in_a_sentence(self, tmp_path):
        from affine import Affine

        a = _raster(tmp_path / "a.tif", [[1.0, 2.0]])
        mask = _raster(tmp_path / "mask.tif", [[0, 0]], dtype="uint8", nodata=None)
        moved = _raster(tmp_path / "moved.tif", [[0, 0]], dtype="uint8", nodata=None,
                        transform=Affine(30.0, 0.0, 0.0, 0.0, -30.0, 0.0))
        cases = [
            (dict(raster=a, mask=mask), "give one of them, for example mask_values=[0] or where=lambda value"),
            (dict(raster=a, mask=mask, mask_values=[0], where=lambda v: v > 0), "give one of them"),
            (dict(raster=a, mask_values=[0]), "mask_values pick the cells of a mask raster on input 1, and there is none"),
            (dict(raster=a, where=0.5), "where is a condition such as lambda value: value < 1.08, not 0.5"),
            (dict(raster=a, where=lambda v: True), "where must give one answer per cell"),
            (dict(raster=a, mask=moved, mask_values=[0]), "their grids differ in origin"),
            (dict(raster=a, band=3), "input 0 has bands 1 to 1, so it has no band 3"),
            (dict(raster=[a, mask, mask]), "Raster Statistics reads one raster, and a mask on input 1, and it has 3"),
        ]
        for kwargs, sentence in cases:
            with pytest.raises(algebra().RasterAlgebraError) as refused:
                algebra().statistics(**kwargs)
            assert sentence in str(refused.value), kwargs


# ---------------------------------------------------------------------------
# A window of a raster
# ---------------------------------------------------------------------------

def _grid_raster(path, *, dtype="float64", count=1):
    """A 10 by 8 raster of cell numbers, 1 degree cells from (-100, 50)."""
    from affine import Affine

    values = np.arange(80, dtype=dtype).reshape(8, 10)
    stack = np.stack([values + 100 * band for band in range(count)])
    return _raster(path, stack, dtype=dtype, nodata=-1.0, crs="EPSG:4326",
                   transform=Affine(1.0, 0.0, -100.0, 0.0, -1.0, 50.0),
                   descriptions=[f"band {i}" for i in range(1, count + 1)])


class TestWindow:
    def test_the_window_holds_the_cells_whose_centres_lie_inside_the_bounds(self, tmp_path, out):
        from rasterio.windows import Window

        src = _grid_raster(tmp_path / "grid.tif")
        # Columns: -97.6 takes in the centre of column 2 (-97.5), -94.4 that of
        # column 5 (-94.5); rows: 47.6 takes in row 2's centre (47.5), 44.4 row 5's (44.5).
        window = rasters().window_of(src, (-97.6, 44.4, -94.4, 47.6), "grid")
        assert window == Window(2, 2, 4, 4)
        cut = rasters().read_window(src, (-97.6, 44.4, -94.4, 47.6), out, name="grid")
        assert cut.read(1).tolist() == src.read(1, window=window).tolist()
        assert cut.read(1)[0, 0] == 22.0
        # A centre just outside is left out: 47.4 leaves row 2's (47.5) out.
        assert rasters().window_of(src, (-97.6, 44.4, -94.4, 47.4), "grid") == Window(2, 3, 4, 3)

    def test_bounds_on_the_rasters_edges_read_it_whole(self, tmp_path, out):
        src = _grid_raster(tmp_path / "grid.tif")
        cut = rasters().read_window(src, tuple(src.bounds), out, name="grid")
        assert cut.read().tolist() == src.read().tolist()
        assert tuple(cut.transform) == tuple(src.transform)

    def test_the_window_keeps_the_grid_the_bands_their_number_type_and_nodata(self, tmp_path, out):
        src = _grid_raster(tmp_path / "grid.tif", count=2)
        cut = rasters().read_window(src, (-98.0, 45.0, -95.0, 48.0), out, name="grid")
        assert (cut.width, cut.height, cut.count) == (3, 3, 2)
        assert tuple(cut.transform)[:6] == (1.0, 0.0, -98.0, 0.0, -1.0, 48.0)
        assert cut.crs.to_epsg() == 4326
        assert cut.dtypes == ("float64", "float64")
        assert cut.nodata == -1.0
        assert cut.descriptions == ("band 1", "band 2")
        assert cut.read(2)[0, 0] == 122.0

    def test_where_the_bounds_lie_on_cell_edges_it_reads_what_rasterio_reads(self, tmp_path, out):
        from rasterio.windows import from_bounds

        src = _grid_raster(tmp_path / "grid.tif")
        bounds = (-97.0, 43.0, -92.0, 48.0)
        cut = rasters().read_window(src, bounds, out, name="grid")
        assert cut.read(1).tolist() == src.read(1, window=from_bounds(*bounds, transform=src.transform)).tolist()

    def test_the_same_window_is_written_once(self, tmp_path, out):
        src = _grid_raster(tmp_path / "grid.tif")
        first = rasters().read_window(src, (-98.0, 45.0, -95.0, 48.0), out, name="grid")
        mtime = os.path.getmtime(first.name)
        again = rasters().read_window(src, (-98.0, 45.0, -95.0, 48.0), out, name="grid")
        assert again.name == first.name and os.path.getmtime(again.name) == mtime
        other = rasters().read_window(src, (-99.0, 45.0, -95.0, 48.0), out, name="grid")
        assert other.name != first.name

    @pytest.mark.parametrize("bounds,sentence", [
        ((-101.0, 45.0, -95.0, 48.0), "reach past grid, which covers west -100.0, south 42.0, east -90.0 and north 50.0 in EPSG:4326"),
        ((-95.0, 45.0, -98.0, 48.0), "are not (west, south, east, north) with west less than east"),
        ((-98.0, 45.0, -95.0), "bounds are four numbers, (west, south, east, north), in grid's CRS"),
        ((-97.4, 45.0, -96.6, 48.0), "hold no cell centre of grid"),
    ])
    def test_bounds_it_cannot_read_say_why(self, tmp_path, out, bounds, sentence):
        src = _grid_raster(tmp_path / "grid.tif")
        with pytest.raises(ValueError) as refused:
            rasters().read_window(src, bounds, out, name="grid")
        assert sentence in str(refused.value)

    def test_a_rotated_raster_is_refused(self, tmp_path, out):
        from affine import Affine

        rotated = _raster(tmp_path / "rotated.tif", [[1.0, 2.0]], transform=Affine(1.0, 0.5, 0.0, 0.5, -1.0, 0.0))
        with pytest.raises(ValueError, match="rotated, so bounds cannot pick a window of it"):
            rasters().read_window(rotated, (0.0, -1.0, 1.0, 0.0), out, name="rotated")


class TestCurioLoadData:
    def _namespace(self, tmp_path, path, fmt):
        from utk_curio.sandbox.util.catalog_helpers import install_catalog_helpers

        namespace: dict = {}
        install_catalog_helpers(
            namespace, data_path={"data.x": str(path)}.__getitem__,
            formats={"data.x": {"format": fmt}}, collections=None, media_dir=str(tmp_path / "media"), models=None,
        )
        return namespace

    def test_bounds_read_a_window_of_a_geotiff_where_the_node_writes_its_files(self, tmp_path):
        src = _grid_raster(tmp_path / "grid.tif")
        namespace = self._namespace(tmp_path, src.name, "geotiff")
        cut = namespace["curio_load_data"]("data.x", bounds=(-98.0, 45.0, -95.0, 48.0))
        assert (cut.width, cut.height) == (3, 3)
        assert os.path.dirname(cut.name) == str(tmp_path / "media" / "outputs")
        whole = namespace["curio_load_data"]("data.x")
        assert (whole.width, whole.height) == (10, 8)
        assert namespace["curio_load_data"]("data.x", bounds=None).name == src.name

    def test_bounds_on_a_table_say_why(self, tmp_path):
        import pandas as pd

        path = tmp_path / "t.csv"
        pd.DataFrame({"a": [1]}).to_csv(path, index=False)
        namespace = self._namespace(tmp_path, path, "csv")
        with pytest.raises(ValueError, match=r"bounds read a window of a raster, and data.x is csv"):
            namespace["curio_load_data"]("data.x", bounds=(0, 0, 1, 1))

    def test_bounds_on_a_collection_say_why(self, tmp_path):
        namespace = self._namespace(tmp_path, tmp_path / "index.parquet", "collection")
        with pytest.raises(ValueError, match="data.x is a collection"):
            namespace["curio_load_data"]("data.x", bounds=(0, 0, 1, 1))

    def test_the_raster_nodes_steps_are_there_too(self, tmp_path):
        src = _grid_raster(tmp_path / "grid.tif")
        namespace = self._namespace(tmp_path, src.name, "geotiff")
        row = namespace["curio_raster_statistics"](src).iloc[0]
        assert row["count"] == 80
        doubled = namespace["curio_raster_calculate"]("add", [src, src])
        assert doubled.read(1)[0, 1] == 2.0
        assert os.path.dirname(doubled.name) == str(tmp_path / "media" / "outputs")


# ---------------------------------------------------------------------------
# Map tiles side by side
# ---------------------------------------------------------------------------

class TestTileMosaic:
    def test_a_tiles_bounds_are_its_corners_in_the_crs(self):
        from pyproj import Transformer

        west, south, east, north = rasters().tile_bounds(16814, 24355, 16)
        n = 2.0 ** 16
        lon_w, lon_e = 16814 / n * 360.0 - 180.0, 16815 / n * 360.0 - 180.0
        lat_n = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * 24355 / n))))
        lat_s = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * 24356 / n))))
        to_3395 = Transformer.from_crs(4326, 3395, always_xy=True)
        assert (west, north) == to_3395.transform(lon_w, lat_n)
        assert (east, south) == to_3395.transform(lon_e, lat_s)
        assert rasters().tile_bounds(16814, 24355, 16, "EPSG:4326") == pytest.approx((lon_w, lat_s, lon_e, lat_n))

    def test_files_are_laid_side_by_side_in_a_vrt_that_points_at_them(self, tmp_path):
        import rasterio
        from affine import Affine

        left = _raster(tmp_path / "left.tif", [[1.0, 2.0], [3.0, 4.0]], transform=Affine(1.0, 0.0, 0.0, 0.0, -1.0, 2.0))
        right = _raster(tmp_path / "right.tif", [[5.0, 6.0], [7.0, 8.0]], transform=Affine(1.0, 0.0, 2.0, 0.0, -1.0, 2.0))
        tiles = [{"transform": tuple(r.transform)[:6], "width": r.width, "height": r.height, "path": r.name}
                 for r in (left, right)]
        path = rasters().mosaic_rasters(tiles, str(tmp_path / "m.vrt"), crs="EPSG:32616", dtype="float32",
                                        nodata=-9999.0)
        with open(path, encoding="utf-8") as handle:
            assert str(tmp_path / "right.tif") in handle.read()
        with rasterio.open(path) as mosaic:
            assert mosaic.read(1).tolist() == [[1.0, 2.0, 5.0, 6.0], [3.0, 4.0, 7.0, 8.0]]
            assert tuple(mosaic.transform)[:6] == (1.0, 0.0, 0.0, 0.0, -1.0, 2.0)

    def test_cells_of_any_size_are_laid_where_their_corners_fall(self, tmp_path):
        import rasterio

        tiles = [
            {"transform": (1.0, 0.0, 0.0, 0.0, -1.0, 3.0), "width": 2, "height": 1, "cells": [[1.0, 1.0]]},
            {"transform": (1.0, 0.0, 1.0, 0.0, -1.0, 2.0), "width": 1, "height": 2, "cells": [[2.0], [2.0]]},
        ]
        path = rasters().mosaic_rasters(tiles, str(tmp_path / "m.tif"), crs="EPSG:32616", dtype="float32", fill=-1.0)
        with rasterio.open(path) as mosaic:
            assert mosaic.read(1).tolist() == [[1.0, 1.0], [-1.0, 2.0], [-1.0, 2.0]]

    def test_a_rotated_tile_or_a_mix_of_files_and_cells_is_refused(self, tmp_path):
        rotated = [{"transform": (1.0, 0.2, 0.0, 0.0, -1.0, 0.0), "width": 1, "height": 1, "cells": [[1.0]]}]
        with pytest.raises(ValueError, match="a tile is rotated; only north-up tiles make a mosaic"):
            rasters().mosaic_rasters(rotated, str(tmp_path / "r.tif"), crs="EPSG:32616", dtype="float32")
        mixed = [
            {"transform": (1.0, 0.0, 0.0, 0.0, -1.0, 1.0), "width": 1, "height": 1, "cells": [[1.0]]},
            {"transform": (1.0, 0.0, 1.0, 0.0, -1.0, 1.0), "width": 1, "height": 1, "path": "/x.tif"},
        ]
        with pytest.raises(ValueError, match="every tile of a mosaic names its file, or every tile holds its cells"):
            rasters().mosaic_rasters(mixed, str(tmp_path / "m.tif"), crs="EPSG:32616", dtype="float32")
