"""Scout's fifteen Vega-Lite charts that compare scenarios (``curio.scout@1``),
beside its two raster nodes.

Seven are re-made from komar41's ScenarioCharts (#914; the plan for #914, step
28.2), one is the first view of his "Minutes of shadow per park" chart (Dots
with a range), and seven were the chart presets of the Compare Scenarios node,
since removed (the plan answering komar41's review, steps 6.2 and 6.4).

Each is a template that draws with the Vega-Lite node's own behavior, with a
``.vl.json`` starter that is a node's whole content. A chart takes one input
per scenario, as many circles as it has inputs, and its spec reads them all as
the dataset ``inputs``: every input's rows stacked, each row named by its
input's scenario box (``__input__``, ``scenario``, ``scenario_name``). The
columns a chart plots are text widgets, which the starter reads through chips
such as ``"field": "[!! y !!]"``; a column widget defaults to its role's name,
and the titles and the Y label format to nothing. Combine, and the Lines' X
type, are choice widgets, and the Table's columns a list.

No starter names a scenario or a scenario's color. Each channel on the scenario
column writes its scenarios through a scenario chip: a color, fill or stroke
its scale as ``[!! scenario colors !!]`` (a text mark's as
``[!! scenario text_colors !!]``), and an axis, offset or facet its order as
``[!! scenario order !!]``. A run resolves them from the boxes its inputs come
from (``utils/references/codeReferences.ts``), so a scenario renamed or
recolored is drawn as its box is.

Every file is read inside its test, so a checkout without the package fails
test by test rather than at collection.
"""
from __future__ import annotations

import copy
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
#: The fifteen charts, in the palette's order, after the raster nodes: the
#: seven from ScenarioCharts, Dots with a range, and Compare's seven presets.
TEMPLATES = [
    "lines-with-band",
    "curves-by-group",
    "bars-with-error-bars",
    "ensemble-strips",
    "stacked-bars-with-totals",
    "donuts",
    "weighted-matrix",
    "dots-with-a-range",
    "bars",
    "grouped-bars",
    "lines",
    "points",
    "pie",
    "lollipops",
    "table",
]
LABELS = [
    "Lines with a band", "Curves by group", "Bars with error bars", "Ensemble strips",
    "Stacked bars with totals", "Donuts", "Weighted matrix", "Dots with a range",
    "Bars", "Grouped bars", "Lines", "Points", "Pie", "Lollipops", "Table",
]
#: Compare's presets, which combine a column's values as Combine says.
COMBINING = ["bars", "grouped-bars", "lines", "pie", "lollipops"]

#: Each template's widgets, in order: the columns it plots, then how it
#: combines them, then its titles and formats.
WIDGETS = {
    "lines-with-band": ["x", "y", "low", "high", "facet", "x_title", "y_title", "y_format"],
    "curves-by-group": ["x", "y", "group", "x_title", "y_title", "y_format", "group_title"],
    "bars-with-error-bars": ["x", "y", "error", "x_title", "y_title", "y_format"],
    "ensemble-strips": ["y", "y_title", "y_format"],
    "stacked-bars-with-totals": ["y", "part", "y_title", "y_format", "part_title"],
    "donuts": ["part", "value", "highlight"],
    "weighted-matrix": ["factor", "weight"],
    "dots-with-a-range": ["category", "value", "x_title", "y_title"],
    "bars": ["y", "combine", "y_title"],
    "grouped-bars": ["x", "y", "combine", "x_title", "y_title"],
    "lines": ["x", "x_type", "y", "combine", "x_title", "y_title"],
    "points": ["x", "y", "x_title", "y_title"],
    "pie": ["value", "combine", "value_title"],
    "lollipops": ["value", "combine", "x_title"],
    "table": ["columns"],
}

#: Widgets that hold a title or a format, not a column: empty by default.
NOT_A_COLUMN = re.compile(r".*_(title|format)$")
#: Widgets that pick how a chart draws, not a column: a choice each. Combine
#: is the measure's Vega-Lite aggregate, and offers Vega-Lite's own.
CHOICES = {
    "combine": ["mean", "sum", "median", "min", "max", "count"],
    "x_type": ["quantitative", "temporal", "ordinal", "nominal"],
}
#: The Combine each chart made from a Compare Scenarios preset starts with.
COMBINE_DEFAULTS = {"bars": "mean", "grouped-bars": "mean", "lines": "mean", "pie": "sum", "lollipops": "mean"}
#: Widgets that name a column but start empty: no facet draws one panel.
EMPTY_COLUMNS = {"facet"}
#: The Table's list of columns, which starts with the scenarios' names.
LISTS = {"columns": ["scenario_name"]}

#: Part 2's manifest flag (feat/package-starter-templates): the template's
#: starter is a node's whole content, kept when an agent plans the node and
#: left alone by Solve.
STARTER_FLAG = "starterIsContent"

CHIP = re.compile(r"\[!!\s*(.*?)\s*!!\]")
SCENARIO_COLUMN = "scenario_name"
#: The columns every row of ``inputs`` carries: its input's circle, and its
#: input's scenario box's id and name.
INPUT_COLUMNS = ["__input__", "scenario", SCENARIO_COLUMN]
#: The channels on the scenario column that draw its colors, and those that put
#: it in order.
COLOR_CHANNELS = {"color", "fill", "stroke"}
ORDER_CHANNELS = {"x", "y", "xOffset", "yOffset", "row", "column", "facet"}
#: The scenario chips a starter may write: the scale of the boxes' colors, the
#: same in text shades, and their names in order.
SCENARIO_CHIPS = {"scenario colors", "scenario text_colors", "scenario order"}
#: The chip of the dataset every starter reads its inputs stacked in.
DATASET_CHIP = "inputs"
#: The label of the one box a starter's input comes from, as a run hands it.
BOX = {"scenario": "s-base", "name": "Baseline", "color": "#2a9d8f", "rank": 0}


def _manifest() -> dict:
    return json.loads((PACKAGE / "manifest.json").read_text(encoding="utf-8"))


def _template(template_id: str) -> dict:
    (template,) = [t for t in _manifest()["templates"] if t["id"] == template_id]
    return template


def _source(template_id: str) -> str:
    return (PACKAGE / _template(template_id)["source"]).read_text(encoding="utf-8")


def _is_column(widget: dict) -> bool:
    return not NOT_A_COLUMN.fullmatch(widget["name"]) and widget["name"] not in CHOICES


def _columns(widgets: list) -> list:
    """The columns *widgets* name with their defaults, the Table's list
    flattened."""
    named = []
    for widget in widgets:
        if not _is_column(widget):
            continue
        value = widget.get("value", widget["default"])
        named.extend(value if isinstance(value, list) else [value] if value else [])
    return named


def _resolved(template_id: str, widgets: list | None = None) -> tuple[str, list]:
    """The starter as a run resolves its chips: with each widget's default, or
    with *widgets*, over one input from a box."""
    from utk_curio.backend.app.execution.code_references import resolve_references

    return resolve_references(
        _source(template_id), widgets=widgets or _template(template_id)["widgets"],
        language="json", inputs=[{"slot": 0, "scenario": BOX}],
    )


def _written(template_id: str):
    """The starter as written, each chip that stands on its own (outside a
    string) read as the text ``chip:<what stands inside it>``. A chip inside a
    string, as a title's or a field's, stays part of that string."""
    source = _source(template_id)
    marked, at, in_string = [], 0, False
    while at < len(source):
        char = source[at]
        chip = None if in_string else CHIP.match(source, at)
        if chip:
            marked.append(json.dumps(f"chip:{chip.group(1)}"))
            at = chip.end()
            continue
        if in_string and char == "\\":
            marked.append(source[at:at + 2])
            at += 2
            continue
        if char == '"':
            in_string = not in_string
        marked.append(char)
        at += 1
    return json.loads("".join(marked))


def _channels(spec) -> list:
    """``(channel, definition, on a text mark)`` for every channel of every
    view in *spec*: each encoding's channels, a condition's field included,
    and a facet's field as ``facet`` or its row and column."""
    found = []

    def channel(name, definition, on_text):
        if not isinstance(definition, dict):
            return
        if "field" in definition:
            found.append((name, definition, on_text))
        condition = definition.get("condition")
        for each in condition if isinstance(condition, list) else [condition]:
            if isinstance(each, dict) and "field" in each:
                found.append((name, each, on_text))

    def view(node):
        if isinstance(node, list):
            for item in node:
                view(item)
            return
        if not isinstance(node, dict):
            return
        mark = node.get("mark")
        on_text = (mark.get("type") if isinstance(mark, dict) else mark) == "text"
        for name, definition in (node.get("encoding") or {}).items():
            channel(name, definition, on_text)
        facet = node.get("facet")
        if isinstance(facet, dict):
            if "field" in facet:
                channel("facet", facet, False)
            else:
                for name, definition in facet.items():
                    channel(name, definition, False)
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


def test_it_holds_the_fifteen_charts_in_the_palettes_order():
    templates = _manifest()["templates"]
    assert [t["id"] for t in templates] == RASTER_TEMPLATES + TEMPLATES
    charts = templates[len(RASTER_TEMPLATES):]
    assert [t["paletteOrder"] for t in charts] == list(
        range(len(RASTER_TEMPLATES), len(RASTER_TEMPLATES) + len(TEMPLATES))
    )
    assert [t["label"] for t in charts] == LABELS


@pytest.mark.parametrize("template_id", TEMPLATES)
def test_each_chart_is_a_vega_lite_node_with_a_starter_of_its_own(template_id):
    """It draws with the Vega-Lite node's behavior and grammar, takes one input
    per scenario on circles that grow as the Vega-Lite node's do, hands its
    input on as the Vega-Lite node does, and opens with its starter, which is
    its whole content."""
    template = _template(template_id)
    builtin = {t["id"]: t for t in json.loads(BUILTIN.read_text(encoding="utf-8"))["templates"]}["vis-vega"]
    expected = {
        "behavior": "vega", "editor": "grammar", "grammarId": "vega-lite", "engine": "python",
        "hasCode": False, "hasGrammar": True, "hasWidgets": True,
        "badge": "VEGA", "category": "vis_grammar", "iconRef": "fa-solid:chart-line",
    }
    assert {key: template.get(key) for key in expected} == expected
    assert {key: builtin.get(key) for key in expected} == expected, "the Vega-Lite node itself changed"
    assert template["inputPorts"] == [{"cardinality": "[1,n]", "types": ["DATAFRAME", "GEODATAFRAME"]}]
    assert template["inputPorts"] == builtin["inputPorts"]
    assert template["outputPorts"] == [{"cardinality": "1", "types": builtin["outputPorts"][0]["types"]}]
    assert template["source"] == f"sources/{template_id}.vl.json"
    assert (PACKAGE / template["source"]).is_file()
    assert template.get(STARTER_FLAG) is True


@pytest.mark.parametrize("template_id", TEMPLATES)
def test_each_description_starts_with_its_form_and_its_columns_within_the_rosters_cut(template_id):
    """The list of templates an agent reads cuts each description at 140
    characters (``turns/roster.py``): that it takes one input per scenario,
    what the chart draws and the columns it reads come first."""
    from utk_curio.backend.app.agents.application.turns.roster import _TEMPLATES_BLOCK_DESC_CHARS

    template = _template(template_id)
    shown = template["description"][:_TEMPLATES_BLOCK_DESC_CHARS]
    assert shown.startswith("One input per scenario: "), shown
    assert "Compare Scenarios" not in template["description"]
    named = re.search(r"widgets? ([a-z_, ]+)\.", shown)
    assert named, f"{template_id}: no widgets within the first {_TEMPLATES_BLOCK_DESC_CHARS} characters: {shown!r}"
    columns = [w["name"] for w in template["widgets"] if _is_column(w)]
    assert [name.strip() for name in named.group(1).split(",")] == columns
    assert "in its box's color" in template["description"]


@pytest.mark.parametrize("template_id", TEMPLATES)
def test_each_widget_is_a_column_a_title_or_a_choice_with_its_default(template_id):
    """A fresh node fails naming the column it lacks rather than drawing
    without it, and its titles and format start empty: no title, and
    Vega-Lite's own labels. Combine starts at its preset's default, the Lines'
    X type at quantitative, and the Table lists the scenarios' names."""
    widgets = _template(template_id)["widgets"]
    assert [w["name"] for w in widgets] == WIDGETS[template_id]
    for widget in widgets:
        name = widget["name"]
        assert widget["label"], widget
        if name in CHOICES:
            assert set(widget) == {"name", "type", "label", "default", "options"}, widget
            assert widget["type"] == "choice" and widget["options"] == {"choices": CHOICES[name]}, widget
            expected = COMBINE_DEFAULTS[template_id] if name == "combine" else "quantitative"
            assert widget["default"] == expected, widget
            continue
        assert set(widget) == {"name", "type", "label", "default"}, widget
        if name in LISTS:
            assert (widget["type"], widget["default"]) == ("text-list", LISTS[name]), widget
        elif _is_column(widget) and name not in EMPTY_COLUMNS:
            assert (widget["type"], widget["default"]) == ("text", name), widget
        else:
            assert (widget["type"], widget["default"]) == ("text", ""), widget
    assert ("combine" in WIDGETS[template_id]) == (template_id in COMBINING)


@pytest.mark.parametrize("template_id", TEMPLATES)
def test_every_chip_names_a_widget_and_every_widget_is_read(template_id):
    """The starter reads its widgets, its scenarios and the dataset its inputs
    are stacked in, and nothing else: no input chip, nor an input's scenario
    chip, since a chart reads its inputs as one dataset."""
    chips = set(CHIP.findall(_source(template_id)))
    assert chips - SCENARIO_CHIPS - {DATASET_CHIP} == set(WIDGETS[template_id])
    assert chips & SCENARIO_CHIPS, f"{template_id} writes no scenario chip"
    assert DATASET_CHIP in chips, f"{template_id} does not name its dataset by its chip"


@pytest.mark.parametrize("template_id", TEMPLATES)
def test_each_starter_reads_its_inputs_stacked(template_id):
    """Its one data block names the dataset ``inputs`` by its chip, written
    inside quotes as the editor inserts it, and resolves to that name, whose
    rows are every input's, each named by its input's scenario box; no view
    names data of its own."""
    assert _written(template_id)["data"] == {"name": f"[!! {DATASET_CHIP} !!]"}
    code, problems = _resolved(template_id)
    assert not problems, problems
    spec = json.loads(code)
    assert spec["data"] == {"name": "inputs"}
    assert json.dumps(spec).count('"data"') == 1, "a view names data of its own"


@pytest.mark.parametrize("template_id", TEMPLATES)
def test_every_channel_on_the_scenario_column_writes_its_scenarios_through_a_chip(template_id):
    """A color, fill or stroke on ``scenario_name`` takes the scale of the
    boxes' colors from its chip, a text mark's in their text shades, and an
    axis, offset or facet on it their order from its chip: as Curio's hidden
    fill drew them before the chips, so no chart draws differently. No
    condition names a scenario."""
    spec = _written(template_id)
    on_scenarios = [(c, d, text) for c, d, text in _channels(spec) if d.get("field") == SCENARIO_COLUMN]
    assert on_scenarios, f"{template_id} draws no channel on {SCENARIO_COLUMN}"
    for channel, definition, on_text in on_scenarios:
        if channel in COLOR_CHANNELS:
            chip = "scenario text_colors" if on_text else "scenario colors"
            assert definition.get("scale") == f"chip:{chip}", (channel, definition)
            assert "sort" not in definition, (channel, definition)
        else:
            assert channel in ORDER_CHANNELS, (channel, definition)
            assert definition.get("sort") == "chip:scenario order" and "scale" not in definition, (channel, definition)
    assert "datum.value ===" not in json.dumps(spec), "a condition names a scenario"
    assert "$schema" in spec and spec["$schema"].startswith("https://vega.github.io/schema/vega-lite/")


@pytest.mark.parametrize("template_id", TEMPLATES)
def test_each_starter_with_its_widget_defaults_is_valid_vega_lite(template_id):
    """Resolved as a run resolves a spec's chips, with each widget's default,
    over inputs that have those columns: it reads no other."""
    from utk_curio.backend.app.agents.domain.document_validation import STATUS_VALID, validate_vega_lite

    widgets = _template(template_id)["widgets"]
    code, problems = _resolved(template_id)
    assert not problems, problems
    assert not CHIP.search(code), code
    result = validate_vega_lite(code, columns=INPUT_COLUMNS + _columns(widgets))
    # "unchecked" (the schema could not be read) is not a pass.
    assert result.get("status") == STATUS_VALID, result


@pytest.mark.parametrize("template_id", TEMPLATES)
def test_no_chart_draws_a_geoshape(template_id):
    """The rows of ``inputs`` carry no geometry, so no chart draws one."""
    code, _problems = _resolved(template_id)
    spec = json.loads(code)
    marks = []

    def view(node):
        if isinstance(node, list):
            for item in node:
                view(item)
        elif isinstance(node, dict):
            if "mark" in node:
                marks.append(node["mark"]["type"] if isinstance(node["mark"], dict) else node["mark"])
            for key in ("layer", "concat", "hconcat", "vconcat", "spec"):
                view(node.get(key))

    view(spec)
    assert marks and "geoshape" not in marks, marks


@pytest.mark.parametrize("template_id", [t for t in TEMPLATES if set(WIDGETS[t]) & set(CHOICES)])
def test_every_choice_is_valid_vega_lite(template_id):
    """Each of Combine's choices, a count among them, and each X type, written
    where its chip stands: each is a spec Vega-Lite reads."""
    from utk_curio.backend.app.agents.domain.document_validation import STATUS_VALID, validate_vega_lite

    template = _template(template_id)
    for name in set(WIDGETS[template_id]) & set(CHOICES):
        for choice in CHOICES[name]:
            widgets = copy.deepcopy(template["widgets"])
            for widget in widgets:
                if widget["name"] == name:
                    widget["value"] = choice
            code, problems = _resolved(template_id, widgets)
            assert not problems, (name, choice, problems)
            result = validate_vega_lite(code, columns=INPUT_COLUMNS + _columns(widgets))
            assert result.get("status") == STATUS_VALID, (name, choice, result)


def test_the_table_shows_the_columns_its_widget_lists_in_order():
    """The validator leaves a fold's columns unchecked, so they are checked
    here: the table folds exactly the listed columns, in the list's order, up
    to 40 rows."""
    widgets = copy.deepcopy(_template("table")["widgets"])
    listed = ["scenario_name", "rain_held_pct", "roof_cooling_c"]
    widgets[0]["value"] = listed
    code, problems = _resolved("table", widgets)
    assert not problems, problems
    spec = json.loads(code)
    assert spec["transform"] == [
        {"window": [{"op": "row_number", "as": "curio_row"}]},
        {"filter": "datum.curio_row <= 40"},
        {"fold": listed, "as": ["curio_column", "curio_cell"]},
    ]
    assert spec["encoding"]["x"]["sort"] == listed
    assert spec["encoding"]["text"] == {"field": "curio_cell", "type": "nominal"}


def test_dots_with_a_range_draw_a_rule_per_category_and_a_dot_per_scenario():
    """komar41's park chart's first view, for any category and value: one grey
    rule per category from its lowest value to its highest, a dot for each
    row in its scenario's color, and the categories the scenarios differ most
    on first."""
    widgets = copy.deepcopy(_template("dots-with-a-range")["widgets"])
    for widget, value in zip(widgets, ["park", "mean_min", "Mean shadow (minutes)", ""]):
        widget["value"] = value
    code, problems = _resolved("dots-with-a-range", widgets)
    assert not problems, problems
    spec = json.loads(code)
    assert spec["transform"] == [
        {"joinaggregate": [
            {"op": "min", "field": "mean_min", "as": "curio_lowest"},
            {"op": "max", "field": "mean_min", "as": "curio_highest"},
        ], "groupby": ["park"]},
        {"calculate": "datum.curio_highest - datum.curio_lowest", "as": "curio_range"},
        {"window": [{"op": "row_number", "as": "curio_rank"}], "groupby": ["park"]},
    ]
    assert spec["encoding"]["y"] == {
        "field": "park", "type": "nominal", "title": "",
        "sort": {"field": "curio_range", "op": "max", "order": "descending"},
    }
    rule, dots = spec["layer"]
    assert rule["transform"] == [{"filter": "datum.curio_rank === 1"}]
    assert rule["mark"]["type"] == "rule"
    assert (rule["encoding"]["x"]["field"], rule["encoding"]["x2"]["field"]) == ("curio_lowest", "curio_highest")
    assert dots["mark"]["type"] == "point" and dots["encoding"]["x"]["field"] == "mean_min"
    assert dots["encoding"]["color"]["field"] == SCENARIO_COLUMN
    assert {rule["encoding"]["x"]["title"], dots["encoding"]["x"]["title"]} == {"Mean shadow (minutes)"}


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
    # A chart takes each scenario's outcome on a circle of its own: none
    # connects after a Compare Scenarios node.
    assert "Compare Scenarios" not in readme


def test_the_integrity_file_holds_every_file_and_its_hash():
    recorded = json.loads((PACKAGE / "integrity.json").read_text(encoding="utf-8"))["sha256"]
    on_disk = {
        path.relative_to(PACKAGE).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in PACKAGE.rglob("*")
        if path.is_file() and path.name != "integrity.json"
    }
    assert recorded == on_disk
