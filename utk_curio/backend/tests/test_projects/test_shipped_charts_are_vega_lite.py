"""The scenario charts are built-in Vega-Lite nodes (#1270).

Every shipped dataflow opens with its charts as Vega-Lite nodes, which Curio
draws with no package: none holds a Scout chart node, and Scout keeps its two
raster nodes. Example 06's mean sunlight, a bar per scenario, is one, and the
dataflow needs no package for it.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_projects/test_shipped_charts_are_vega_lite.py -v
"""
from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]

#: Scout's own nodes, which stay in its package.
RASTER_NODES = {"curio.scout/raster-calculator", "curio.scout/rasterize-buildings"}


def _template(node: dict) -> str:
    return str(node.get("type") or "").split("@", 1)[0]


def _shipped() -> dict[str, dict]:
    found: dict[str, dict] = {}
    for folder in ("docs/examples", "docs/examples/dataflows"):
        for path in sorted((REPO_ROOT / folder).glob("*.json")):
            dataflow = json.loads(path.read_text(encoding="utf-8")).get("dataflow")
            if isinstance(dataflow, dict):
                found[path.relative_to(REPO_ROOT).as_posix()] = dataflow
    return found


def test_no_shipped_dataflow_opens_with_a_scout_chart_node():
    charts = [
        (rel, node["id"], node.get("type"))
        for rel, dataflow in _shipped().items()
        for node in dataflow.get("nodes") or []
        if isinstance(node, dict) and _template(node).startswith("curio.scout/") and _template(node) not in RASTER_NODES
    ]
    assert charts == []


def test_example_06_draws_its_mean_sunlight_with_the_vega_lite_node_and_needs_no_package():
    dataflow = _shipped()["docs/examples/06-back-bay-road-sunlight.json"]
    [chart] = [node for node in dataflow["nodes"] if node.get("title") == "Mean sunlight"]
    assert _template(chart) == "curio.builtin/vis-vega", chart.get("type")
    assert dataflow.get("packages") == []
