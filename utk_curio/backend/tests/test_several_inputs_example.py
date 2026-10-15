"""Example 26 feeds one node from several others, in every kind of node that
takes several inputs (#819).

Each test runs the example's own Python code as the sandbox runs a node: its
chips resolved by ``resolve_references``, and its inputs bound to ``input_k``
by circle (``call_as_node``). It reads the shipped datasets through stand-ins
for ``curio_data_path`` and ``curio_load_data``, and pins what the
walkthrough, ``docs/examples/26-several-inputs.md``, says each node gives.
``test_frontend/test_workflows.py`` runs the whole example in the browser.
"""
from __future__ import annotations

import json
import textwrap
from functools import lru_cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLE = REPO_ROOT / "docs" / "examples" / "26-several-inputs.json"

#: The example's nodes.
READINGS = "several-readings"
STATIONS = "several-stations"
ZIPS = "several-zips"
SUMMARY = "several-summary"
JOIN = "several-join"
TRANSFORM = "several-transform"
JS = "several-js"
CHART = "several-chart"
MAP = "several-map"
POOL = "several-pool"

STATION_NAMES = ["Clark and Madison", "Michigan and Adams", "State and Lake"]


def _dataflow() -> dict:
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))["dataflow"]


def _circle(handle) -> int:
    return 0 if handle in (None, "in") else int(str(handle).split("_")[1])


def _inputs(node_id: str) -> list:
    """``(circle, source node)`` for each edge into *node_id*, in circle order."""
    edges = [e for e in _dataflow()["edges"] if e["target"] == node_id]
    return sorted((_circle(e.get("targetHandle")), e["source"]) for e in edges)


def _dataset(dataset_id: str) -> tuple:
    folder = REPO_ROOT / "datasets" / f"{dataset_id}@1"
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    return str(folder / manifest["dataFile"]), manifest.get("format")


def _data_path(dataset_id: str) -> str:
    return _dataset(dataset_id)[0]


def _load_data(dataset_id: str):
    from utk_curio.sandbox.util.catalog_helpers import read_dataset

    return read_dataset(*_dataset(dataset_id))


@lru_cache(maxsize=None)
def _output(node_id: str):
    """What a Python node of the example returns, run on its own code."""
    from utk_curio.backend.app.execution.code_references import resolve_references
    from utk_curio.sandbox.util.input_names import call_as_node

    node = next(n for n in _dataflow()["nodes"] if n["id"] == node_id)
    inputs = _inputs(node_id)
    slots = [circle for circle, _source in inputs]
    code, problems = resolve_references(
        node["content"], language="python", inputs=[{"slot": slot} for slot in slots]
    )
    assert not problems, f"{node_id}: {problems}"
    values = [_output(source) for _circle, source in inputs]
    value = values[0] if len(values) == 1 else (values or None)
    scope = {"curio_data_path": _data_path, "curio_load_data": _load_data}
    return call_as_node(textwrap.indent(code, "    "), scope, value, slots or None)


def test_each_node_takes_its_inputs_on_the_circles_the_walkthrough_names():
    assert _inputs(SUMMARY) == [(0, READINGS)]
    assert _inputs(JOIN) == [(0, STATIONS), (1, SUMMARY), (2, ZIPS)]
    assert _inputs(TRANSFORM) == [(0, READINGS), (1, JOIN)]
    assert _inputs(JS) == [(0, ZIPS), (1, JOIN)]
    assert _inputs(CHART) == [(0, TRANSFORM), (1, JOIN)]
    assert _inputs(MAP) == [(0, ZIPS), (1, JOIN)]
    assert _inputs(POOL) == [(0, JOIN), (1, TRANSFORM)]


def test_one_input_gives_a_tuple_of_two_tables():
    """Summarize reads its one input as input_0 and returns each sensor's mean
    PM2.5 and its peak, together, as a tuple."""
    out = _output(SUMMARY)
    assert isinstance(out, tuple) and len(out) == 2, type(out)
    means, peaks = out
    assert list(means.columns) == ["sensor", "pm25_mean"]
    assert list(peaks.columns) == ["sensor", "pm25_peak"]
    assert sorted(means["sensor"]) == sorted(peaks["sensor"]) == ["sensor_A", "sensor_B", "sensor_C"]


def test_three_inputs_join_each_station_to_its_summaries_and_its_zip_code():
    """The tuple arrives whole on circle 1. Clark and Madison is in 60603
    (mean 8.0), State and Lake in 60601 (10.0) and Michigan and Adams in
    60604 (12.0)."""
    joined = _output(JOIN)
    assert {"pm25_mean", "pm25_peak", "zip"} <= set(joined.columns)
    assert "index_right" not in joined.columns
    rows = sorted((r["name"], r["zip"], round(r["pm25_mean"], 1)) for r in joined.to_dict("records"))
    assert rows == [
        ("Clark and Madison", "60603", 8.0),
        ("Michigan and Adams", "60604", 12.0),
        ("State and Lake", "60601", 10.0),
    ]


def test_two_inputs_name_every_reading_after_its_station():
    named = _output(TRANSFORM)
    assert len(named) == len(_output(READINGS))
    assert named["name"].notna().all()
    assert sorted(named["name"].unique()) == STATION_NAMES
