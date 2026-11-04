"""The scenario charts are the Vega-Lite package's nodes (#1270).

Every shipped dataflow opens with its charts as nodes of the built-in
Vega-Lite node or of the Vega-Lite package (``curio.vega-lite@1``), which
carries no SCOUT tag: a chart is no SCOUT node. SCOUT's raster nodes are
Rasterization's (``curio.rasterization@1``), whose SCOUT tag a dataflow that
only charts does not get. Example 06's mean sunlight, a bar per scenario, is
the Vega-Lite package's Bars, and the dataflow lists that package alone.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_projects/test_shipped_charts_are_vega_lite.py -v
"""
from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
VEGA_LITE = "curio.vega-lite"
RASTERIZATION = "curio.rasterization"


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


def _manifests() -> dict[str, dict]:
    """Each shipped package's manifest, by its id."""
    manifests = (json.loads(p.read_text(encoding="utf-8")) for p in (REPO_ROOT / "packages").glob("*/manifest.json"))
    return {manifest["id"]: manifest for manifest in manifests}


def _charts() -> list[tuple[str, str, str]]:
    """``(dataflow, node id, template)`` of each shipped node whose template
    draws with Vega-Lite."""
    templates = {
        f"{package_id}/{template['id']}": template
        for package_id, manifest in _manifests().items()
        for template in manifest.get("templates") or []
    }
    return [
        (rel, node["id"], _template(node))
        for rel, dataflow in _shipped().items()
        for node in dataflow.get("nodes") or []
        if isinstance(node, dict) and (templates.get(_template(node)) or {}).get("grammarId") == "vega-lite"
    ]


def test_every_shipped_chart_is_the_vega_lite_nodes_or_the_vega_lite_packages():
    charts = _charts()
    assert len({rel for rel, _node, _template_id in charts}) >= 10, charts
    others = [chart for chart in charts if chart[2].split("/", 1)[0] not in ("curio.builtin", VEGA_LITE)]
    assert others == []
    packaged = sorted({template_id for _rel, _node, template_id in charts if template_id.startswith(f"{VEGA_LITE}/")})
    assert packaged == [f"{VEGA_LITE}/{chart}" for chart in (
        "bars", "bars-with-error-bars", "curves-by-group", "donuts", "dots-with-a-range", "ensemble-strips",
        "grouped-bars", "lines-with-band", "points", "stacked-bars-with-totals", "table", "weighted-matrix",
    )], packaged


def test_no_package_whose_charts_a_shipped_dataflow_holds_carries_the_scout_tag():
    """The Vega-Lite package declares no tag; Rasterization, whose nodes are
    SCOUT's, declares SCOUT and draws no chart."""
    manifests = _manifests()
    assert "dataflowCategories" not in manifests[VEGA_LITE]
    assert manifests[RASTERIZATION]["dataflowCategories"] == {"tags": ["SCOUT"]}
    assert not [t["id"] for t in manifests[RASTERIZATION]["templates"] if t.get("grammarId") == "vega-lite"]
    tagged = [
        chart for chart in _charts()
        if "SCOUT" in ((manifests[chart[2].split("/", 1)[0]].get("dataflowCategories") or {}).get("tags") or [])
    ]
    assert tagged == []


def test_a_dataflow_that_only_charts_is_not_tagged_scout_and_one_with_raster_nodes_is():
    from utk_curio.backend.app.projects.categories import DatasetKinds, derive

    kinds = DatasetKinds(None)
    shipped = _shipped()
    for rel in ("docs/examples/06-back-bay-road-sunlight.json", "docs/examples/dataflows/scenario-comparison-charts.json"):
        assert "SCOUT" not in derive({"dataflow": shipped[rel]}, kinds)["tags"], rel
    flood = shipped["docs/examples/dataflows/quad-cities-flood-vulnerability.json"]
    assert flood["packages"] == [f"{RASTERIZATION}@1", f"{VEGA_LITE}@1"]
    assert "SCOUT" in derive({"dataflow": flood}, kinds)["tags"]


def test_example_06_draws_its_mean_sunlight_with_the_vega_lite_packages_bars_and_lists_that_package_alone():
    dataflow = _shipped()["docs/examples/06-back-bay-road-sunlight.json"]
    [chart] = [node for node in dataflow["nodes"] if node.get("title") == "Mean sunlight"]
    assert _template(chart) == f"{VEGA_LITE}/bars", chart.get("type")
    assert dataflow.get("packages") == [f"{VEGA_LITE}@1"]
