"""The Compare Scenarios node's stacking step (#662), ``curio_stack_scenarios``.

The node's code hands it one ``(scenario id, scenario name, input)`` entry per
input circle. It stacks them into one table under ``scenario`` and
``scenario_name``; inputs it cannot stack into one table are refused with a
message naming the input.

Every test imports the module itself, so a checkout without it fails test by
test rather than at collection.
"""
from __future__ import annotations

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Point


def _stack(entries):
    from utk_curio.sandbox.util.scenario_stack import stack_scenarios

    return stack_scenarios(entries)


def _frame(values, **columns):
    return pd.DataFrame({"segment": [f"r{i}" for i in range(len(values))], "sunlight": values, **columns})


class TestStacking:
    def test_each_input_is_stacked_under_its_scenario(self):
        out = _stack([
            ("s-base", "Baseline", _frame([5.0, 6.0])),
            ("s-tall", "Twice as tall", _frame([3.0, 4.0])),
        ])
        assert list(out.columns) == ["scenario", "scenario_name", "segment", "sunlight"]
        assert out[["scenario", "scenario_name"]].values.tolist() == [
            ["s-base", "Baseline"], ["s-base", "Baseline"],
            ["s-tall", "Twice as tall"], ["s-tall", "Twice as tall"],
        ]
        assert out["sunlight"].tolist() == [5.0, 6.0, 3.0, 4.0]
        assert list(out.index) == [0, 1, 2, 3]

    def test_the_inputs_are_left_as_they_were(self):
        base = _frame([5.0])
        _stack([("s-base", "Baseline", base)])
        assert list(base.columns) == ["segment", "sunlight"]

    def test_a_column_one_input_lacks_is_empty_in_its_rows_and_the_run_says_so(self, capsys):
        out = _stack([
            ("s-base", "Baseline", _frame([5.0])),
            ("s-tall", "Twice as tall", _frame([3.0], shade=[0.5])),
        ])
        assert list(out.columns) == ["scenario", "scenario_name", "segment", "sunlight", "shade"]
        assert pd.isna(out.loc[0, "shade"]) and out.loc[1, "shade"] == 0.5
        assert "input_0 (Baseline) has no shade" in capsys.readouterr().out

    def test_values_are_one_row_each_under_value(self):
        out = _stack([("s-base", "Baseline", 5), ("s-tall", "Twice as tall", 3.5)])
        assert out.to_dict("records") == [
            {"scenario": "s-base", "scenario_name": "Baseline", "value": 5},
            {"scenario": "s-tall", "scenario_name": "Twice as tall", "value": 3.5},
        ]

    def test_a_list_of_values_is_a_row_per_value(self):
        out = _stack([("s-base", "Baseline", [1, 2]), ("s-tall", "Tall", [3])])
        assert out["value"].tolist() == [1, 2, 3]

    def test_a_dict_of_values_is_one_row_and_a_dict_of_lists_is_columns(self):
        rows = _stack([("s-base", "B", {"mean": 1.5, "max": 3}), ("s-tall", "T", {"mean": 1.0, "max": 2})])
        assert rows[["scenario_name", "mean", "max"]].values.tolist() == [["B", 1.5, 3], ["T", 1.0, 2]]
        columns = _stack([("s-base", "B", {"x": [1, 2], "y": [3, 4]})])
        assert columns[["x", "y"]].values.tolist() == [[1, 3], [2, 4]]

    def test_records_are_rows(self):
        out = _stack([("s-base", "B", [{"x": 1}, {"x": 2}])])
        assert out["x"].tolist() == [1, 2]

    def test_an_input_in_no_scenario_is_named_by_its_node(self):
        out = _stack([("s-base", "Baseline", 1), (None, "Python Computation", 2)])
        assert out["scenario"].tolist() == ["s-base", None]
        assert out["scenario_name"].tolist() == ["Baseline", "Python Computation"]

    def test_geodataframes_stack_into_one_in_their_crs(self):
        a = gpd.GeoDataFrame({"v": [1]}, geometry=[Point(0, 0)], crs="EPSG:4326")
        b = gpd.GeoDataFrame({"v": [2]}, geometry=[Point(1, 1)], crs="EPSG:4326")
        out = _stack([("s-base", "B", a), ("s-tall", "T", b)])
        assert isinstance(out, gpd.GeoDataFrame)
        assert out.crs.to_string() == "EPSG:4326"
        assert out.geometry.name == "geometry"
        assert out["v"].tolist() == [1, 2]

    def test_a_layer_with_no_crs_takes_the_others(self, capsys):
        a = gpd.GeoDataFrame({"v": [1]}, geometry=[Point(0, 0)], crs="EPSG:4326")
        b = gpd.GeoDataFrame({"v": [2]}, geometry=[Point(1, 1)])
        out = _stack([("s-base", "B", a), ("s-tall", "T", b)])
        assert out.crs.to_string() == "EPSG:4326"
        assert "input_1 (T) names no coordinate system" in capsys.readouterr().out

    def test_a_layer_an_autark_node_hands_on_is_read_as_a_geodataframe(self):
        layer = {
            "dataType": "geodataframe",
            "layerName": "roads",
            "data": {
                "type": "FeatureCollection",
                "features": [{"type": "Feature", "properties": {"v": 9}, "geometry": {"type": "Point", "coordinates": [0, 0]}}],
            },
        }
        b = gpd.GeoDataFrame({"v": [2]}, geometry=[Point(1, 1)], crs="EPSG:4326")
        out = _stack([("s-base", "B", layer), ("s-tall", "T", b)])
        assert isinstance(out, gpd.GeoDataFrame)
        assert out["v"].tolist() == [9, 2]

    def test_an_empty_input_adds_no_rows(self):
        out = _stack([("s-base", "B", []), ("s-tall", "T", 4)])
        assert out.to_dict("records") == [{"scenario": "s-tall", "scenario_name": "T", "value": 4}]


class TestRefusals:
    def test_no_inputs(self):
        with pytest.raises(ValueError, match="has no inputs. Connect each scenario's outcome"):
            _stack([])

    def test_a_table_beside_a_value_names_both(self):
        with pytest.raises(ValueError) as caught:
            _stack([("s-base", "Baseline", _frame([1.0])), ("s-tall", "Twice as tall", 3.5)])
        assert str(caught.value) == (
            "Compare Scenarios stacks inputs of one kind, and these differ: input_0 (Baseline) is a table, "
            "input_1 (Twice as tall) is a value. Connect outcomes of the same kind."
        )

    def test_a_geodataframe_beside_a_plain_table(self):
        geo = gpd.GeoDataFrame({"v": [1]}, geometry=[Point(0, 0)], crs="EPSG:4326")
        with pytest.raises(ValueError, match=r"input_0 \(B\) is a GeoDataFrame, input_1 \(T\) is a table"):
            _stack([("s-base", "B", geo), ("s-tall", "T", _frame([1.0]))])

    def test_two_coordinate_systems(self):
        a = gpd.GeoDataFrame({"v": [1]}, geometry=[Point(0, 0)], crs="EPSG:4326")
        b = gpd.GeoDataFrame({"v": [2]}, geometry=[Point(1, 1)], crs="EPSG:3857")
        with pytest.raises(ValueError, match=r"input_0 \(B\) is in EPSG:4326, input_1 \(T\) is in EPSG:3857"):
            _stack([("s-base", "B", a), ("s-tall", "T", b)])

    def test_an_input_with_no_value(self):
        with pytest.raises(ValueError, match=r"input_1 \(T\) has no value. Run the node that feeds it"):
            _stack([("s-base", "B", 1), ("s-tall", "T", None)])

    def test_an_input_that_carries_several_tables(self):
        with pytest.raises(ValueError, match=r"input_0 \(B\) carries 2 tables"):
            _stack([("s-base", "B", (_frame([1.0]), _frame([2.0])))])

    def test_an_autark_nodes_layers_with_no_layer_named_are_listed(self):
        with pytest.raises(
            ValueError,
            match=r"input_0 \(B\) carries 2 layers \(table_osm_buildings, table_osm_roads\)\. "
                  r"Pick the one to compare in the node's Layer menu\.",
        ):
            _stack([("s-base", "B", autark_layers([5.0]))])

    def test_a_layer_the_input_does_not_have_names_the_ones_it_has(self):
        from utk_curio.sandbox.util.scenario_stack import stack_scenarios

        with pytest.raises(
            ValueError,
            match=r"input_0 \(B\) has no layer table_osm_water\. Its layers are table_osm_buildings, table_osm_roads\.",
        ):
            stack_scenarios([("s-base", "B", autark_layers([5.0]))], layer="table_osm_water")

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


class TestNodeCodeReachesIt:
    """The node's code calls it by name, in process and under isolation."""

    CODE = (
        "    return curio_stack_scenarios([\n"
        "        (\"s-base\", \"Baseline\", 5),\n"
        "        (\"s-tall\", \"Twice as tall\", 3),\n"
        "    ])\n"
    )

    def test_an_in_process_node(self):
        from utk_curio.sandbox.app.worker import _worker_init, execute_code
        from utk_curio.sandbox.util.db import init_db

        _worker_init()
        init_db()
        result = execute_code(self.CODE, "", "curio.builtin/compare-scenarios", "", save_dataset=False)
        assert result["stderr"] == ""
        assert result["output"]["dataType"] == "dataframe"

    def test_an_isolated_node(self, tmp_path):
        from utk_curio.sandbox.isolation import child, zygote

        scratch = tmp_path / "scratch"
        scratch.mkdir()
        code = (
            "    stacked = curio_stack_scenarios([(\"s-base\", \"Baseline\", 5), (\"s-tall\", \"Twice as tall\", 3)])\n"
            "    return ','.join(stacked['scenario_name'])\n"
        )
        request = {
            "code": code,
            "node_type": "curio.builtin/compare-scenarios", "data_type": "",
            "scratch_dir": str(scratch), "input": {"kind": "none"},
            "session_imports": [], "limits": {},
        }
        result = child.run_node(request, zygote.build_namespace_template)
        assert result["ok"], result["stderr"]
        assert result["output"]["value"] == "Baseline,Twice as tall"


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


class TestOneLayerOfAnAutarkNodes:
    def test_the_named_layer_is_stacked_and_the_others_are_not(self):
        from utk_curio.sandbox.util.scenario_stack import stack_scenarios

        out = stack_scenarios(
            [("s-base", "Baseline", autark_layers([5.0, 7.0])), ("s-tall", "Twice as tall", autark_layers([3.0, 7.0]))],
            layer="table_osm_roads",
        )
        assert isinstance(out, gpd.GeoDataFrame)
        assert out.crs.to_epsg() == 3395, "the layer's own coordinate system was lost"
        assert out["scenario_name"].tolist() == ["Baseline", "Baseline", "Twice as tall", "Twice as tall"]
        assert out["sunlight"].tolist() == [5.0, 7.0, 3.0, 7.0]
        assert "height" not in out.columns

    def test_a_layer_named_for_inputs_of_one_table_changes_nothing(self):
        from utk_curio.sandbox.util.scenario_stack import stack_scenarios

        out = stack_scenarios([("s-base", "B", _frame([1.0]))], layer="table_osm_roads")
        assert out["sunlight"].tolist() == [1.0]
