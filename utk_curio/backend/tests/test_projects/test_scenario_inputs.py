"""A Vega-Lite chart that reads its inputs stacked as ``inputs`` (#662).

- ``stack_inputs`` (``utk_curio/sandbox/util/scenario_stack.py``), which an
  exported notebook calls, gives exactly the rows or the refusal of each case
  in ``stackedInputs.cases.json``, the file the browser's twin
  (``src/utils/scenarios/stackedInputs.ts``) is pinned to in Jest, and
  ``input_rows`` each input's own rows.
- Their rows are JSON, as a notebook hands them to Vega-Lite.
- A chart whose channels on ``scenario_name`` are filled in from its
  scenarios' labels is valid Vega-Lite (``scenarioScales.cases.json``, which
  Jest pins ``scenarioScales.ts`` to).

Every file and module is read inside its test, so a checkout without them fails
test by test rather than at collection.
"""
from __future__ import annotations

import json
import math
import os

from utk_curio.backend.app.projects.seed import _repo_root

REPO_ROOT = str(_repo_root())
SCENARIOS_DIR = os.path.join(REPO_ROOT, "utk_curio", "frontend", "urban-workflows", "src", "utils", "scenarios")


def _read_json(name: str) -> dict:
    with open(os.path.join(SCENARIOS_DIR, name), encoding="utf-8") as fh:
        return json.load(fh)


def test_stack_inputs_gives_each_cases_rows_or_refusal_as_the_browser_does():
    from utk_curio.sandbox.util.scenario_stack import stack_inputs

    cases = _read_json("stackedInputs.cases.json")["cases"]
    assert len({case["name"] for case in cases}) == len(cases), "two cases share a name"
    wrong = {}
    for case in cases:
        entries = [(entry["scenario"], entry["name"], entry["value"]) for entry in case["inputs"]]
        try:
            got = {"rows": stack_inputs(entries)}
        except ValueError as refused:
            got = {"refusal": str(refused)}
        wanted = {"rows": case["rows"]} if "rows" in case else {"refusal": case["refusal"]}
        if got != wanted:
            wrong[case["name"]] = got
    assert wrong == {}


def test_input_rows_gives_each_inputs_own_rows_as_the_browser_does():
    from utk_curio.sandbox.util.scenario_stack import input_rows

    cases = _read_json("stackedInputs.cases.json")["inputRows"]
    wrong = {case["name"]: input_rows(case["value"]) for case in cases if input_rows(case["value"]) != case["rows"]}
    assert wrong == {}


def test_a_notebooks_input_rows_are_json_for_a_value_and_for_a_dataframe():
    """What a notebook's chart cell hands Vega-Lite as ``input_<k>``, whatever
    the input is."""
    import numpy as np
    import pandas as pd

    from utk_curio.sandbox.util.scenario_stack import input_rows

    frame = pd.DataFrame({"segment": ["r1", "r2"], "sunlight": [5.0, np.nan]})
    assert json.loads(json.dumps(input_rows(frame), allow_nan=False)) == [
        {"segment": "r1", "sunlight": 5.0}, {"segment": "r2", "sunlight": None},
    ]
    assert input_rows(np.float64(2.5)) == [{"value": 2.5}]
    assert input_rows([1, 2]) == [{"value": 1}, {"value": 2}]


def test_the_stacked_rows_are_json_a_missing_cell_none():
    """What a notebook's upstream cells hold: DataFrames, one of them with a
    column the other lacks and a number that is none."""
    import numpy as np
    import pandas as pd

    from utk_curio.sandbox.util.scenario_stack import stack_inputs

    base = pd.DataFrame({"segment": ["r1", "r2"], "sunlight": np.array([5, 6], dtype="int64")})
    tall = pd.DataFrame({"segment": ["r1"], "sunlight": [np.nan], "shade": [0.5]})
    rows = stack_inputs([("s-base", "Baseline", base), (None, "Shade", tall)])
    assert json.loads(json.dumps(rows, allow_nan=False)) == [
        {"__input__": 0, "scenario": "s-base", "scenario_name": "Baseline", "segment": "r1", "sunlight": 5, "shade": None},
        {"__input__": 0, "scenario": "s-base", "scenario_name": "Baseline", "segment": "r2", "sunlight": 6, "shade": None},
        {"__input__": 1, "scenario": None, "scenario_name": "Shade", "segment": "r1", "sunlight": None, "shade": 0.5},
    ]
    assert all(isinstance(row["__input__"], int) for row in rows)
    assert not any(isinstance(cell, float) and math.isnan(cell) for row in rows for cell in row.values())
    # The inputs are left as they were.
    assert list(base.columns) == ["segment", "sunlight"]


def _gdf(rows: list[dict], crs: str):
    """A GeoDataFrame of points, one per row, in *crs*."""
    import geopandas as gpd
    from shapely.geometry import Point

    return gpd.GeoDataFrame(rows, geometry=[Point(i, i) for i in range(len(rows))], crs=crs)


def test_a_list_of_tables_carries_them_and_is_refused_as_the_browser_refuses_it():
    """A Python node's list of DataFrames, which reaches the browser as a list
    of frame envelopes (stackedInputs.test.ts holds the same refusal)."""
    import pandas as pd
    import pytest

    from utk_curio.sandbox.util.scenario_stack import stack_inputs

    tables = [pd.DataFrame({"pop": [1]}), pd.DataFrame({"pop": [2]})]
    with pytest.raises(ValueError) as refused:
        stack_inputs([(None, "Tables", tables)])
    assert str(refused.value) == (
        'The dataset "inputs": input_0 (Tables) carries 2 tables. Connect a node that returns one table, '
        "or pick the table to compare in a node between them."
    )
    with pytest.raises(ValueError) as mixed:
        stack_inputs([(None, "Tables", [pd.DataFrame({"pop": [1]}), {"pop": 2}])])
    assert "is a list that mixes records and values" in str(mixed.value)


def test_a_dataframe_with_no_rows_is_a_table_beside_a_value_as_in_the_browser():
    import pandas as pd
    import pytest

    from utk_curio.sandbox.util.scenario_stack import stack_inputs

    with pytest.raises(ValueError) as refused:
        stack_inputs([("s-base", "Baseline", pd.DataFrame({"pop": []})), ("s-tall", "Twice as tall", 3)])
    assert str(refused.value) == (
        'The dataset "inputs" stacks inputs of one kind, and these differ: input_0 (Baseline) is a table, '
        "input_1 (Twice as tall) is a value. Connect outcomes of the same kind."
    )


def test_a_float_that_is_no_number_is_a_value_row_with_no_value_as_in_the_browser():
    """What the sandbox writes as null under ``float``: the browser stacks it
    as a value with none (vegaInput.test.ts holds the same rows)."""
    import numpy as np

    from utk_curio.sandbox.util.scenario_stack import input_rows, stack_inputs

    assert stack_inputs([("s-base", "Baseline", float("nan"))]) == [
        {"__input__": 0, "scenario": "s-base", "scenario_name": "Baseline", "value": None},
    ]
    assert [row["value"] for row in stack_inputs([("s-base", "Baseline", [1.5, np.nan])])] == [1.5, None]
    assert input_rows(float("nan")) == [{"value": None}]


def test_geodataframes_stack_beside_a_table_and_in_two_coordinate_systems_their_geometry_left_out():
    """The relaxation is the chart's alone: Compare Scenarios still refuses both."""
    import pandas as pd
    import pytest

    from utk_curio.sandbox.util.scenario_stack import stack_inputs, stack_scenarios

    roads = _gdf([{"zip": "a", "pop": 1}], "EPSG:4326")
    table = pd.DataFrame({"zip": ["b"], "pop": [2]})
    assert stack_inputs([("s-base", "Baseline", roads), ("s-tall", "Twice as tall", table)]) == [
        {"__input__": 0, "scenario": "s-base", "scenario_name": "Baseline", "zip": "a", "pop": 1},
        {"__input__": 1, "scenario": "s-tall", "scenario_name": "Twice as tall", "zip": "b", "pop": 2},
    ]
    projected = _gdf([{"zip": "c", "pop": 3}], "EPSG:3857")
    rows = stack_inputs([("s-base", "Baseline", roads), ("s-tall", "Twice as tall", projected)])
    assert [(row["scenario_name"], row["pop"]) for row in rows] == [("Baseline", 1), ("Twice as tall", 3)]
    assert all("geometry" not in row for row in rows)

    with pytest.raises(ValueError, match="stacks inputs of one kind"):
        stack_scenarios([("s-base", "Baseline", roads), ("s-tall", "Twice as tall", table)])
    with pytest.raises(ValueError, match="different coordinate systems"):
        stack_scenarios([("s-base", "Baseline", roads), ("s-tall", "Twice as tall", projected)])


def test_the_rows_of_inputs_never_carry_geometry_from_one_input_or_several():
    """As the browser's: a chart draws a map from ``input_<k>``, never from
    ``inputs``. Compare Scenarios keeps its stacked GeoDataFrame's geometry."""
    import geopandas as gpd

    from utk_curio.sandbox.util.scenario_stack import input_rows, stack_inputs, stack_scenarios

    roads = _gdf([{"pop": 1}, {"pop": 2}], "EPSG:4326")
    assert stack_inputs([("s-base", "Baseline", roads)]) == [
        {"__input__": 0, "scenario": "s-base", "scenario_name": "Baseline", "pop": 1},
        {"__input__": 0, "scenario": "s-base", "scenario_name": "Baseline", "pop": 2},
    ]
    assert input_rows(roads) == [{"pop": 1}, {"pop": 2}]
    assert list(roads.columns) == ["pop", "geometry"]

    compared = stack_scenarios([("s-base", "Baseline", roads)])
    assert isinstance(compared, gpd.GeoDataFrame)
    assert compared.geometry.name == "geometry"


def test_a_chart_with_its_scenarios_filled_in_is_valid_vega_lite():
    """Each chart a Vega-Lite node compiles, its channels on ``scenario_name``
    given the scenarios' names and colors, and each spec the fill leaves as
    written, goes through the validator agents' documents go through."""
    from utk_curio.backend.app.agents.domain.document_validation import STATUS_VALID, validate_vega_lite

    doc = _read_json("scenarioScales.cases.json")
    columns = ["scenario", "scenario_name"] + [column["name"] for column in doc["columns"]]
    specs = {case["name"]: case["filled"] for case in doc["cases"]}
    specs.update({case["name"]: case["spec"] for case in doc["untouched"]})
    assert len(specs) == len(doc["cases"]) + len(doc["untouched"]), "two cases share a name"
    results = {name: validate_vega_lite(json.dumps(spec), columns=columns) for name, spec in specs.items()}
    # "unchecked" (the schema could not be read) is not a pass.
    assert {name: r for name, r in results.items() if r.get("status") != STATUS_VALID} == {}
