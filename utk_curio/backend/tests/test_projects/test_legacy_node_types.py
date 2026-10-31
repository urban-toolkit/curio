"""A dataflow saved with the Scout package's nodes reads as if saved after
#1270: its raster nodes the Rasterization package's, its charts Vega-Lite
nodes with the same spec, widgets and title, and its packages renamed or
dropped (``projects/legacy_node_types.py``)."""
from __future__ import annotations

import json

from utk_curio.backend.app.projects import storage
from utk_curio.backend.app.projects.legacy_node_types import (
    REPLACED_NODE_TYPES,
    current_node_type,
    migrate_legacy_types,
)

WIDGETS = [{"name": "y", "type": "text", "default": "y", "value": "sunlight"}]


def _spec(nodes, packages):
    return {"dataflow": {"name": "old", "nodes": nodes, "edges": [], "packages": packages}}


def test_a_chart_is_a_vega_lite_node_with_its_spec_widgets_and_title():
    chart = {"id": "c", "type": "curio.scout/bars", "title": "Mean sunlight",
             "content": "{\"mark\": \"bar\"}", "metadata": {"widgets": WIDGETS}}
    spec = migrate_legacy_types(_spec([chart], ["curio.scout@1"]))
    (node,) = spec["dataflow"]["nodes"]
    assert node == {**chart, "type": "curio.builtin/vis-vega"}
    # Its charts need no package, so Scout is dropped, not renamed.
    assert spec["dataflow"]["packages"] == []


def test_raster_nodes_are_rasterizations_and_the_package_is_renamed_once():
    spec = migrate_legacy_types(_spec(
        [{"id": "r", "type": "curio.scout/raster-calculator@1"},
         {"id": "b", "type": "curio.scout/rasterize-buildings"},
         {"id": "c", "type": "curio.scout/donuts@1"}],
        ["curio.scout@1", "model.scout.deep-umbra@1", "curio.rasterization@1"],
    ))
    assert [n["type"] for n in spec["dataflow"]["nodes"]] == [
        "curio.rasterization/raster-calculator@1", "curio.rasterization/rasterize-buildings", "curio.builtin/vis-vega@1",
    ]
    assert spec["dataflow"]["packages"] == ["curio.rasterization@1", "model.scout.deep-umbra@1"]


def test_every_other_node_and_spec_is_left_as_it_is():
    nodes = [{"id": "p", "type": "curio.builtin/computation-analysis@1"}, {"id": "m", "type": "model.scout.deep-umbra/accumulated-shadow"}]
    spec = _spec(nodes, ["model.scout.deep-umbra@1"])
    assert migrate_legacy_types(json.loads(json.dumps(spec))) == spec
    assert migrate_legacy_types(None) is None and migrate_legacy_types({"x": 1}) == {"x": 1}
    assert current_node_type("curio.scout") == "curio.scout"


def test_the_table_maps_every_scout_template():
    assert sorted(t.split("/", 1)[1] for t in REPLACED_NODE_TYPES) == sorted([
        "raster-calculator", "rasterize-buildings", "lines-with-band", "curves-by-group",
        "bars-with-error-bars", "ensemble-strips", "stacked-bars-with-totals", "donuts",
        "weighted-matrix", "dots-with-a-range", "bars", "grouped-bars", "lines", "points",
        "pie", "lollipops", "table",
    ])


def test_a_saved_project_reads_migrated(tmp_path):
    (tmp_path / storage.SPEC_FILE).write_text(json.dumps(_spec(
        [{"id": "c", "type": "curio.scout/bars"}], ["curio.scout@1"],
    )), encoding="utf-8")
    spec = storage.read_spec_in(tmp_path)
    assert spec["dataflow"]["nodes"][0]["type"] == "curio.builtin/vis-vega"
    assert spec["dataflow"]["packages"] == []
