"""The stacking a Vega-Lite chart's ``inputs`` dataset reads (#662),
``stack_inputs`` in ``util/scenario_stack.py``.

It takes one ``(scenario id, scenario name, input)`` entry per input circle
and stacks the inputs' rows into one table, each row under ``__input__``,
``scenario`` and ``scenario_name``; inputs it cannot stack into one table are
refused with a message naming the input. ``stackedInputs.cases.json`` pins its
rows and refusals beside the browser's twin; these are the rules that file
cannot hold, and the rows of the kinds of input a node hands on.

Every test imports the module itself, so a checkout without it fails test by
test rather than at collection.
"""
from __future__ import annotations

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Point


def _stack(entries):
    from utk_curio.sandbox.util.scenario_stack import stack_inputs

    return stack_inputs(entries)


def _frame(values, **columns):
    return pd.DataFrame({"segment": [f"r{i}" for i in range(len(values))], "sunlight": values, **columns})


class TestStacking:
    def test_each_input_is_stacked_under_its_scenario(self):
        rows = _stack([
            ("s-base", "Baseline", _frame([5.0, 6.0])),
            ("s-tall", "Twice as tall", _frame([3.0, 4.0])),
        ])
        assert [list(row) for row in rows] == [["__input__", "scenario", "scenario_name", "segment", "sunlight"]] * 4
        assert [(row["scenario"], row["scenario_name"]) for row in rows] == [
            ("s-base", "Baseline"), ("s-base", "Baseline"),
            ("s-tall", "Twice as tall"), ("s-tall", "Twice as tall"),
        ]
        assert [row["sunlight"] for row in rows] == [5.0, 6.0, 3.0, 4.0]
        assert [row["__input__"] for row in rows] == [0, 0, 1, 1]

    def test_the_inputs_are_left_as_they_were(self):
        base = _frame([5.0])
        _stack([("s-base", "Baseline", base)])
        assert list(base.columns) == ["segment", "sunlight"]

    def test_a_column_one_input_lacks_is_empty_in_its_rows_and_the_run_says_so(self, capsys):
        rows = _stack([
            ("s-base", "Baseline", _frame([5.0])),
            ("s-tall", "Twice as tall", _frame([3.0], shade=[0.5])),
        ])
        assert list(rows[0]) == ["__input__", "scenario", "scenario_name", "segment", "sunlight", "shade"]
        assert rows[0]["shade"] is None and rows[1]["shade"] == 0.5
        assert 'The dataset "inputs": input_0 (Baseline) has no shade' in capsys.readouterr().out

    def test_values_are_one_row_each_under_value(self):
        assert _stack([("s-base", "Baseline", 5), ("s-tall", "Twice as tall", 3.5)]) == [
            {"__input__": 0, "scenario": "s-base", "scenario_name": "Baseline", "value": 5},
            {"__input__": 1, "scenario": "s-tall", "scenario_name": "Twice as tall", "value": 3.5},
        ]

    def test_a_list_of_values_is_a_row_per_value(self):
        rows = _stack([("s-base", "Baseline", [1, 2]), ("s-tall", "Tall", [3])])
        assert [row["value"] for row in rows] == [1, 2, 3]

    def test_a_dict_of_values_is_one_row_and_a_dict_of_lists_is_columns(self):
        rows = _stack([("s-base", "B", {"mean": 1.5, "max": 3}), ("s-tall", "T", {"mean": 1.0, "max": 2})])
        assert [[row["scenario_name"], row["mean"], row["max"]] for row in rows] == [["B", 1.5, 3], ["T", 1.0, 2]]
        columns = _stack([("s-base", "B", {"x": [1, 2], "y": [3, 4]})])
        assert [[row["x"], row["y"]] for row in columns] == [[1, 3], [2, 4]]

    def test_records_are_rows(self):
        rows = _stack([("s-base", "B", [{"x": 1}, {"x": 2}])])
        assert [row["x"] for row in rows] == [1, 2]

    def test_an_input_in_no_scenario_is_named_by_its_node(self):
        rows = _stack([("s-base", "Baseline", 1), (None, "Python Computation", 2)])
        assert [row["scenario"] for row in rows] == ["s-base", None]
        assert [row["scenario_name"] for row in rows] == ["Baseline", "Python Computation"]

    def test_a_layer_an_autark_node_hands_on_is_read_as_its_rows(self):
        layer = {
            "dataType": "geodataframe",
            "layerName": "roads",
            "data": {
                "type": "FeatureCollection",
                "features": [{"type": "Feature", "properties": {"v": 9}, "geometry": {"type": "Point", "coordinates": [0, 0]}}],
            },
        }
        b = gpd.GeoDataFrame({"v": [2]}, geometry=[Point(1, 1)], crs="EPSG:4326")
        rows = _stack([("s-base", "B", layer), ("s-tall", "T", b)])
        assert [row["v"] for row in rows] == [9, 2]
        assert all("geometry" not in row for row in rows)

    def test_an_empty_input_adds_no_rows(self):
        assert _stack([("s-base", "B", []), ("s-tall", "T", 4)]) == [
            {"__input__": 1, "scenario": "s-tall", "scenario_name": "T", "value": 4},
        ]


class TestRefusals:
    def test_a_table_beside_a_value_names_both(self):
        with pytest.raises(ValueError) as caught:
            _stack([("s-base", "Baseline", _frame([1.0])), ("s-tall", "Twice as tall", 3.5)])
        assert str(caught.value) == (
            'The dataset "inputs" stacks inputs of one kind, and these differ: input_0 (Baseline) is a table, '
            "input_1 (Twice as tall) is a value. Connect outcomes of the same kind."
        )

    def test_an_input_with_no_value(self):
        with pytest.raises(ValueError, match=r"input_1 \(T\) has no value. Run the node that feeds it"):
            _stack([("s-base", "B", 1), ("s-tall", "T", None)])

    def test_an_input_that_carries_several_tables(self):
        with pytest.raises(ValueError, match=r"input_0 \(B\) carries 2 tables"):
            _stack([("s-base", "B", (_frame([1.0]), _frame([2.0])))])

    def test_an_autark_nodes_several_layers_are_listed(self):
        with pytest.raises(
            ValueError,
            match=r"input_0 \(B\) carries 2 layers \(table_osm_buildings, table_osm_roads\)\. "
                  r"Connect a node that hands on one layer\.",
        ):
            _stack([("s-base", "B", autark_layers([5.0]))])

    def test_a_raster(self):
        class Raster:
            crs = None
            transform = None

            def read(self):
                return None

        with pytest.raises(ValueError, match=r"input_0 \(B\) is a raster"):
            _stack([("s-base", "B", Raster())])

    def test_a_column_the_stacked_table_adds_itself(self):
        with pytest.raises(ValueError, match="already has a column named scenario_name"):
            _stack([("s-base", "B", pd.DataFrame({"scenario_name": ["x"]}))])

    def test_an_entry_that_is_not_scenario_name_and_input(self):
        with pytest.raises(TypeError, match="entry 0 is not"):
            _stack([("s-base", _frame([1.0]))])


def autark_layers(sunlight):
    """What an Autark compute step hands on: every layer of its workspace, in
    one ``outputs`` envelope, each under its ``layerName``."""

    def layer(name, rows):
        return {
            "dataType": "geodataframe",
            "layerName": name,
            "data": {
                "type": "FeatureCollection",
                # Autark names its workspace's coordinate system on each layer.
                "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::3395"}},
                "features": [
                    {"type": "Feature", "properties": properties, "geometry": {"type": "Point", "coordinates": [i, i]}}
                    for i, properties in enumerate(rows)
                ],
            },
        }

    return {
        "dataType": "outputs",
        "data": [
            layer("table_osm_buildings", [{"height": 12.0}]),
            layer("table_osm_roads", [{"name": f"road {i}", "sunlight": value} for i, value in enumerate(sunlight)]),
        ],
    }
