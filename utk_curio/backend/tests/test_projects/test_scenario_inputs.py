"""A Vega-Lite chart that reads its inputs stacked as ``inputs`` (#662).

- ``stack_inputs`` (``utk_curio/sandbox/util/scenario_stack.py``), which an
  exported notebook calls, gives exactly the rows or the refusal of each case
  in ``stackedInputs.cases.json``, the file the browser's twin
  (``src/utils/scenarios/stackedInputs.ts``) is pinned to in Jest.
- Its rows are JSON, as a notebook hands them to Vega-Lite.

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
