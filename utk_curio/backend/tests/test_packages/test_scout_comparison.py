"""Seven Vega-Lite charts to connect after a Compare Scenarios node (the plan
for #914, step 28.2; re-made from komar41's ScenarioCharts in #914), nodes of
Scout (``curio.scout@1``) beside its two raster nodes (the plan answering
komar41's review of his #914, step 10).

The charts: seven templates that draw with the Vega-Lite node's own behavior,
each with a ``.vl.json`` starter that is a node's whole content. The columns a
chart plots are text widgets, which the starter reads through chips such as
``"field": "[!! y !!]"``; a column widget defaults to its role's name, and the
titles and the Y label format to nothing.

No starter names a scenario, a scenario color or an order for the scenario
column: a chart after a Compare node takes those from the node's labels
(``utils/scenarios/scenarioScales.ts``), so a scenario renamed or recolored is
drawn as its box is.

Every file is read inside its test, so a checkout without the package fails
test by test rather than at collection.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
PACKAGE_ID = "curio.scout"
PACKAGE = REPO / "packages" / f"{PACKAGE_ID}@1"
BUILTIN = REPO / "packages" / "curio.builtin@1" / "manifest.json"

#: The package's two raster nodes (``test_scout_rasters.py``), first in its
#: palette group.
RASTER_TEMPLATES = ["raster-calculator", "rasterize-buildings"]
#: The seven charts, in the palette's order, after the raster nodes.
TEMPLATES = [
    "lines-with-band",
    "curves-by-group",
    "bars-with-error-bars",
    "ensemble-strips",
    "stacked-bars-with-totals",
    "donuts",
    "weighted-matrix",
]

#: Each template's widgets, in order: the columns it plots, then its titles
#: and formats.
WIDGETS = {
    "lines-with-band": ["x", "y", "low", "high", "facet", "x_title", "y_title", "y_format"],
    "curves-by-group": ["x", "y", "group", "x_title", "y_title", "y_format", "group_title"],
    "bars-with-error-bars": ["x", "y", "error", "x_title", "y_title", "y_format"],
    "ensemble-strips": ["y", "y_title", "y_format"],
    "stacked-bars-with-totals": ["y", "part", "y_title", "y_format", "part_title"],
    "donuts": ["part", "value", "highlight"],
    "weighted-matrix": ["factor", "weight"],
}

#: Widgets that hold a title or a format, not a column: empty by default.
NOT_A_COLUMN = re.compile(r".*_(title|format)$")
#: Widgets that name a column but start empty: no facet draws one panel.
EMPTY_COLUMNS = {"facet"}

#: Part 2's manifest flag (feat/package-starter-templates): the template's
#: starter is a node's whole content, kept when an agent plans the node and
#: left alone by Solve.
STARTER_FLAG = "starterIsContent"

CHIP = re.compile(r"\[!!\s*(.*?)\s*!!\]")
SCENARIO_COLUMN = "scenario_name"
#: The channels a Compare node's labels fill on the scenario column.
FILLED_CHANNELS = {"color", "fill", "stroke", "x", "y", "xOffset", "yOffset", "row", "column", "facet"}


def _manifest() -> dict:
    return json.loads((PACKAGE / "manifest.json").read_text(encoding="utf-8"))


def _template(template_id: str) -> dict:
    (template,) = [t for t in _manifest()["templates"] if t["id"] == template_id]
    return template


def _source(template_id: str) -> str:
    return (PACKAGE / _template(template_id)["source"]).read_text(encoding="utf-8")


def _is_column(widget: dict) -> bool:
    return not NOT_A_COLUMN.fullmatch(widget["name"])


def _channels(spec) -> list:
    """``(channel, definition)`` for every channel of every view in *spec*, as
    ``withScenarioScales`` walks it: each encoding's channels, a condition's
    field included, and a facet's field as ``facet`` or its row and column."""
    found = []

    def channel(name, definition):
        if not isinstance(definition, dict):
            return
        if "field" in definition:
            found.append((name, definition))
        condition = definition.get("condition")
        for each in condition if isinstance(condition, list) else [condition]:
            if isinstance(each, dict) and "field" in each:
                found.append((name, each))

    def view(node):
        if isinstance(node, list):
            for item in node:
                view(item)
            return
        if not isinstance(node, dict):
            return
        for name, definition in (node.get("encoding") or {}).items():
            channel(name, definition)
        facet = node.get("facet")
        if isinstance(facet, dict):
            if "field" in facet:
                channel("facet", facet)
            else:
                for name, definition in facet.items():
                    channel(name, definition)
        for key in ("layer", "concat", "hconcat", "vconcat", "spec"):
            if key in node:
                view(node[key])

    view(spec)
    return found


# --- the package -------------------------------------------------------------


def test_the_package_is_scout_from_curio_under_mit_with_only_the_raster_nodes_libraries():
    """The charts need no Python library: the package's are the ones its raster
    nodes import, and no chart's starter imports anything."""
    from utk_curio.backend.app.packages.service import load_package_manifest

    manifest = _manifest()
    assert (manifest["id"], manifest["name"]) == (PACKAGE_ID, "Scout")
    assert (manifest["publisher"], manifest["license"], manifest["version"]) == ("Curio", "MIT", "1.0.0")
    assert manifest["dependencies"] == {"js": {}, "packages": {}, "python": {
        "dask": ">=2026.8.0", "datashader": ">=0.19.1", "geopandas": ">=1.1.3", "numpy": "",
        "pandas": ">=3.0.2", "pillow": ">=12.2.0", "pyarrow": ">=24.0.0", "pyproj": ">=3.7.2",
        "rasterio": ">=1.4", "shapely": ">=2.0", "spatialpandas": ">=0.5.0",
    }}
    assert manifest["readOnly"] is True and manifest["permissions"] == []
    assert manifest.get("kind", "node") == "node"
    assert (PACKAGE / "README.md").is_file()
    loaded = load_package_manifest(PACKAGE)
    assert [t.template_id for t in loaded.templates] == RASTER_TEMPLATES + TEMPLATES
    for template_id in TEMPLATES:
        assert _template(template_id)["source"].endswith(".vl.json"), template_id


def test_it_holds_the_seven_charts_in_the_palettes_order():
    templates = _manifest()["templates"]
    assert [t["id"] for t in templates] == RASTER_TEMPLATES + TEMPLATES
    charts = templates[len(RASTER_TEMPLATES):]
    assert [t["paletteOrder"] for t in charts] == list(
        range(len(RASTER_TEMPLATES), len(RASTER_TEMPLATES) + len(TEMPLATES))
    )
    assert [t["label"] for t in charts] == [
        "Lines with a band", "Curves by group", "Bars with error bars", "Ensemble strips",
        "Stacked bars with totals", "Donuts", "Weighted matrix",
    ]


@pytest.mark.parametrize("template_id", TEMPLATES)
def test_each_chart_is_a_vega_lite_node_with_a_starter_of_its_own(template_id):
    """It draws with the Vega-Lite node's behavior and grammar, reads one table
    on its one input circle, hands that table on as the Vega-Lite node does,
    and opens with its starter, which is its whole content."""
    template = _template(template_id)
    builtin = {t["id"]: t for t in json.loads(BUILTIN.read_text(encoding="utf-8"))["templates"]}["vis-vega"]
    expected = {
        "behavior": "vega", "editor": "grammar", "grammarId": "vega-lite", "engine": "python",
        "hasCode": False, "hasGrammar": True, "hasWidgets": True,
        "badge": "VEGA", "category": "vis_grammar", "iconRef": "fa-solid:chart-line",
    }
    assert {key: template.get(key) for key in expected} == expected
    assert {key: builtin.get(key) for key in expected} == expected, "the Vega-Lite node itself changed"
    assert template["inputPorts"] == [{"cardinality": "1", "types": ["DATAFRAME", "GEODATAFRAME"]}]
    assert template["outputPorts"] == [{"cardinality": "1", "types": builtin["outputPorts"][0]["types"]}]
    assert template["source"] == f"sources/{template_id}.vl.json"
    assert (PACKAGE / template["source"]).is_file()
    assert template.get(STARTER_FLAG) is True


@pytest.mark.parametrize("template_id", TEMPLATES)
def test_each_description_starts_with_its_form_and_its_columns_within_the_rosters_cut(template_id):
    """The list of templates an agent reads cuts each description at 140
    characters (``turns/roster.py``): what the chart draws and the columns it
    reads come first."""
    from utk_curio.backend.app.agents.application.turns.roster import _TEMPLATES_BLOCK_DESC_CHARS

    template = _template(template_id)
    shown = template["description"][:_TEMPLATES_BLOCK_DESC_CHARS]
    assert shown.startswith("After Compare Scenarios: "), shown
    named = re.search(r"widgets? ([a-z_, ]+)\.", shown)
    assert named, f"{template_id}: no widgets within the first {_TEMPLATES_BLOCK_DESC_CHARS} characters: {shown!r}"
    columns = [w["name"] for w in template["widgets"] if _is_column(w)]
    assert [name.strip() for name in named.group(1).split(",")] == columns
    assert "in its box's color" in template["description"]


@pytest.mark.parametrize("template_id", TEMPLATES)
def test_each_widget_is_text_and_a_column_defaults_to_its_role(template_id):
    """A fresh node fails naming the column it lacks rather than drawing
    without it, and its titles and format start empty: no title, and
    Vega-Lite's own labels."""
    widgets = _template(template_id)["widgets"]
    assert [w["name"] for w in widgets] == WIDGETS[template_id]
    for widget in widgets:
        assert set(widget) == {"name", "type", "label", "default"}, widget
        assert widget["type"] == "text" and widget["label"], widget
        if _is_column(widget) and widget["name"] not in EMPTY_COLUMNS:
            assert widget["default"] == widget["name"], widget
        else:
            assert widget["default"] == "", widget


@pytest.mark.parametrize("template_id", TEMPLATES)
def test_every_chip_names_a_widget_and_every_widget_is_read(template_id):
    """The starter reads its widgets and nothing else: no input chip, since a
    Vega-Lite node draws its input's table as it is."""
    chips = set(CHIP.findall(_source(template_id)))
    assert chips == set(WIDGETS[template_id])


@pytest.mark.parametrize("template_id", TEMPLATES)
def test_no_starter_names_a_scenario_or_draws_the_scenario_column_its_own_way(template_id):
    """Every channel on ``scenario_name`` is left for the Compare node's
    labels: no scale, no sort, no domain, and no condition naming a scenario."""
    spec = json.loads(_source(template_id))
    on_scenarios = [(channel, d) for channel, d in _channels(spec) if d.get("field") == SCENARIO_COLUMN]
    assert on_scenarios, f"{template_id} draws no channel on {SCENARIO_COLUMN}"
    for channel, definition in on_scenarios:
        assert channel in FILLED_CHANNELS, (channel, definition)
        assert "scale" not in definition and "sort" not in definition, (channel, definition)
    assert "datum.value ===" not in json.dumps(spec), "a condition names a scenario"
    assert "$schema" in spec and spec["$schema"].startswith("https://vega.github.io/schema/vega-lite/")


@pytest.mark.parametrize("template_id", TEMPLATES)
def test_each_starter_with_its_widget_defaults_is_valid_vega_lite(template_id):
    """Resolved as a run resolves a spec's chips, with each widget's default,
    over a stacked table that has those columns."""
    from utk_curio.backend.app.agents.domain.document_validation import STATUS_VALID, validate_vega_lite
    from utk_curio.backend.app.execution.code_references import resolve_references

    widgets = _template(template_id)["widgets"]
    code, problems = resolve_references(_source(template_id), widgets=widgets, language="json",
                                        inputs=[{"slot": 0}])
    assert not problems, problems
    assert not CHIP.search(code), code
    columns = ["scenario", SCENARIO_COLUMN, *[w["default"] for w in widgets if _is_column(w) and w["default"]]]
    result = validate_vega_lite(code, columns=columns)
    # "unchecked" (the schema could not be read) is not a pass.
    assert result.get("status") == STATUS_VALID, result


def test_the_readme_names_each_chart_and_its_widgets():
    """Each of the package's nodes, the raster ones too: its id, its label
    and each widget it has."""
    readme = (PACKAGE / "README.md").read_text(encoding="utf-8")
    assert readme.startswith(f"# `{PACKAGE_ID}@1`: Scout\n")
    templates = _manifest()["templates"]
    assert [t["id"] for t in templates] == RASTER_TEMPLATES + TEMPLATES
    for template in templates:
        assert f"`{PACKAGE_ID}/{template['id']}`" in readme, template["id"]
        assert template["label"] in readme, template["label"]
        for widget in template.get("widgets") or []:
            assert f"`{widget['name']}`" in readme, (template["id"], widget["name"])
    for template_id in TEMPLATES:
        assert _template(template_id)["widgets"], template_id


def test_the_integrity_file_holds_every_file_and_its_hash():
    recorded = json.loads((PACKAGE / "integrity.json").read_text(encoding="utf-8"))["sha256"]
    on_disk = {
        path.relative_to(PACKAGE).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in PACKAGE.rglob("*")
        if path.is_file() and path.name != "integrity.json"
    }
    assert recorded == on_disk
