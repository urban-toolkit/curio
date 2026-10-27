"""``lower-manhattan-park-shade.json``: SCOUT's shadow model on the parks of
Lower Manhattan, with the towers around them removed or capped (step 18 of the
#914 plan: komar41's ShadowsAnywhere, re-made on Curio's nodes).

The shipped test dataflow reads ``lower_mnt.osm.pbf`` with one Autark data
node: OpenStreetMap's parks of a box, the Financial District to City Hall, and
the buildings of a box about 300 m larger on every side, up to the extract's
edge, so the towers that shade the parks at its edge are there too. Its
context:

- Building heights gives every building part a height in metres;
- Open-air parks keeps the named parks large enough to measure, in the open;
- Buildings around parks marks the parts the what-ifs change, by one rule for
  every park: at least the Tall building height tall (a widget of its own,
  60 m) and within the Distance from a park (a widget of its own, 75 m) of any
  park;
- the Season node, a Python node that holds the season and returns it, wired
  into every Accumulated Shadow's second circle.

Three scenarios: Existing; Towers removed, whose Map Editor node removes the
marked parts; and Height cap, whose Map Editor node cuts them down to the
Tall building height. Each rasterizes its buildings
(``curio.scout@1``), runs Deep Umbra on them
(``model.scout.deep-umbra@1``), measures the shade in each park, and draws its
buildings in 3D and its shadow on Autark maps; each what-if's Map Editor node
is linked to its buildings map, which it edits on. Scout's Dots with a range
charts each park's mean minutes of shadow in the three scenarios, and for
each what-if a Raster Calculator (``curio.scout@1``) takes the change in
shadow cell by cell and a Python node each park's change in shade, each drawn
by an Autark map after it. Until the plan answering komar41's review (step
6.3), Compare Scenarios nodes did all three.

The first tests read the file. The others run it as written, once for the
module, on the extract and with no socket: the data node compiled and run as
a run on the server runs it (``test_autk_server_data_load.py``), and every
code node in the sandbox with its package's modules and the model's weights.
The chart's rows and the changes are held to what the Compare Scenarios nodes
the dataflow held wrote from the same values (``_support/scenario_changes.py``
and the shadows' own cells). What does not depend on the model is pinned
exactly: the layers, the parks, the
rule, the levers and the rasters' grid. Deep Umbra's minutes are pinned within 1 minute a park:
onnxruntime's output moves with its thread count past 16
(``test_scout_shadow.py``), and at 32 and 64 threads a park's mean moved by at
most 0.39 minutes from a run on 8.

The dataflow and the packages' code are read inside each test, so a checkout
without them fails each test on its own.
"""
from __future__ import annotations

import json
import math
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
DATAFLOW = REPO / "docs" / "examples" / "dataflows" / "lower-manhattan-park-shade.json"
NAME = "Lower Manhattan park shade with towers removed or capped"
EXTRACT = "docs/examples/data/lower_mnt.osm.pbf"
RASTER_PACKAGE = REPO / "packages" / "curio.scout@1"
RASTER_MODULE = "scout_rasters"
MODEL_PACKAGE = REPO / "packages" / "model.scout.deep-umbra@1"
MODEL_ID = "model.scout.deep-umbra"

AUTARK = "curio.builtin/autk-grammar"
PYTHON = "curio.builtin/computation-analysis"
PARAMETER = "curio.builtin/parameter"
INTERACTION = "curio.builtin/edit-features"
COMPARE = "curio.builtin/compare-scenarios"
RASTERIZE = "curio.scout/rasterize-buildings"
SHADOW = "model.scout.deep-umbra/accumulated-shadow"
CALCULATOR = "curio.scout/raster-calculator"
DOTS = "curio.scout/dots-with-a-range"
#: The chart and the changes, which keep the ids of the Compare Scenarios nodes
#: they replaced.
CHART = "park-shade-chart"
#: The chart's widgets: the park on its Y axis and each scenario's mean minutes
#: on its X axis, each titled by its column, as Compare titled its grouped bars
#: of the minutes as they are.
CHART_WIDGETS = {"category": "park", "value": "mean_min", "x_title": "mean_min", "y_title": "park"}
#: What each what-if's change says it does, in its comment.
DOING = {"towers-removed": "removing the towers", "height-cap": "cutting the towers down"}

#: The scenarios, in the order the chart and every change read them, and the
#: key of each scenario's nodes.
SCENARIOS = [
    ("existing", "Existing", "#2a9d8f", "existing"),
    ("towers-removed", "Towers removed", "#e76f51", "removed"),
    ("height-cap", "Height cap", "#6a4c93", "capped"),
]
#: [west, south, east, north]: the parks' box, the Financial District to City
#: Hall, and the buildings' box around it, about 300 m larger on every side up
#: to the box the extract is cut at, which ends over the water to the west and
#: south.
PARKS_BOX = [-74.018, 40.7, -74.004, 40.713]
BUILDINGS_BOX = [-74.0194416, 40.698762, -74.0005, 40.7157]
#: How much larger the buildings' box is, where the extract allows.
MARGIN_M = 300
#: The rule's defaults, Buildings around parks' two widgets'.
PARK_DISTANCE_M = 75
TALL_HEIGHT_M = 60

#: What the data node hands on: autk-db 4.1.1's parks of the parks' box, and
#: the buildings of the buildings' box, a row for each building and each part
#: of one, in 423 clusters of buildings that overlap (``building_id``).
PARK_FEATURES = 215
BUILDING_ROWS = 2688
BUILDING_IDS = 423
#: OpenStreetMap's height for One World Trade Center, its spire included.
TALLEST_M = 541.0
#: The parts at least 60 m tall within 75 m of a park, in 97 of the clusters.
MARKED_ROWS = 527
MARKED_IDS = 97

#: The parks Open-air parks keeps: named, at least 500 m², not mostly under
#: building footprints, each once. Imagination Playground is two outlines in
#: OpenStreetMap, a playground and a park, under one name.
PARKS = [
    "Battery Park", "Battery Playscape", "Bowling Green", "City Hall Park", "Coenties Slip",
    "DeLury Square", "Drumgoole Plaza", "East River Waterfront Esplanade", "Elizabeth H. Berger Plaza",
    "Imagination Playground", "Liberty Park", "Little West Dog Run", "Living Memorial Grove",
    "Louise Nevelson Plaza", "Mannahatta Park", "Old Slip Park", "Parks Dog Run", "Pearl Street Playground",
    "Rector Park", "Robert F. Wagner Jr. Park", "South Cove Park", "The Battery Oval", "The Battery Woodland",
    "The Esplanade", "The Queen Elizabeth II September 11th Garden", "Trinity Churchyard",
    "Vietnam Veterans Plaza", "West Thames Park", "Zuccotti Park",
]

#: The rasters every scenario's nodes make, on one grid: 4 by 5 zoom-16 tiles
#: in EPSG:3395, starting at tile 19293, 24639.
GRID = (1024, 1280)
TILE = {"zoom": "16", "tile_x": "19293", "tile_y": "24639"}

#: Each park's mean minutes of shadow in summer, per scenario, from a run on 8
#: threads; a run on another machine is within MINUTES of each.
MINUTES = 1.0
MEANS = {
    "existing": {
        "Battery Park": 77.78, "Battery Playscape": 105.11, "Bowling Green": 369.75, "City Hall Park": 160.02,
        "Coenties Slip": 486.00, "DeLury Square": 472.17, "Drumgoole Plaza": 229.16,
        "East River Waterfront Esplanade": 95.83, "Elizabeth H. Berger Plaza": 371.09,
        "Imagination Playground": 261.89, "Liberty Park": 213.36, "Little West Dog Run": 313.45,
        "Living Memorial Grove": 101.86, "Louise Nevelson Plaza": 569.35, "Mannahatta Park": 458.83,
        "Old Slip Park": 504.19, "Parks Dog Run": 105.60, "Pearl Street Playground": 358.58,
        "Rector Park": 144.58, "Robert F. Wagner Jr. Park": 45.67, "South Cove Park": 236.46,
        "The Battery Oval": 47.45, "The Battery Woodland": 47.13, "The Esplanade": 184.48,
        "The Queen Elizabeth II September 11th Garden": 498.29, "Trinity Churchyard": 403.59,
        "Vietnam Veterans Plaza": 378.02, "West Thames Park": 295.10, "Zuccotti Park": 354.78,
    },
    "towers-removed": {
        "Battery Park": 41.26, "Battery Playscape": 63.28, "Bowling Green": 173.25, "City Hall Park": 115.40,
        "Coenties Slip": 374.35, "DeLury Square": 204.90, "Drumgoole Plaza": 180.55,
        "East River Waterfront Esplanade": 31.14, "Elizabeth H. Berger Plaza": 187.69,
        "Imagination Playground": 191.24, "Liberty Park": 134.23, "Little West Dog Run": 48.33,
        "Living Memorial Grove": 71.16, "Louise Nevelson Plaza": 350.21, "Mannahatta Park": 257.11,
        "Old Slip Park": 355.70, "Parks Dog Run": 39.64, "Pearl Street Playground": 231.65,
        "Rector Park": 44.49, "Robert F. Wagner Jr. Park": 28.51, "South Cove Park": 192.51,
        "The Battery Oval": 26.46, "The Battery Woodland": 3.43, "The Esplanade": 120.95,
        "The Queen Elizabeth II September 11th Garden": 196.43, "Trinity Churchyard": 166.84,
        "Vietnam Veterans Plaza": 96.32, "West Thames Park": 123.39, "Zuccotti Park": 99.29,
    },
    "height-cap": {
        "Battery Park": 55.70, "Battery Playscape": 79.01, "Bowling Green": 304.88, "City Hall Park": 134.17,
        "Coenties Slip": 392.74, "DeLury Square": 422.19, "Drumgoole Plaza": 203.16,
        "East River Waterfront Esplanade": 65.40, "Elizabeth H. Berger Plaza": 255.07,
        "Imagination Playground": 207.74, "Liberty Park": 159.93, "Little West Dog Run": 248.95,
        "Living Memorial Grove": 87.30, "Louise Nevelson Plaza": 472.49, "Mannahatta Park": 406.78,
        "Old Slip Park": 456.21, "Parks Dog Run": 78.92, "Pearl Street Playground": 282.67,
        "Rector Park": 108.53, "Robert F. Wagner Jr. Park": 36.57, "South Cove Park": 195.65,
        "The Battery Oval": 32.83, "The Battery Woodland": 23.29, "The Esplanade": 148.71,
        "The Queen Elizabeth II September 11th Garden": 437.02, "Trinity Churchyard": 306.58,
        "Vietnam Veterans Plaza": 296.94, "West Thames Park": 229.16, "Zuccotti Park": 223.35,
    },
}

#: The code each Map Editor node writes from its edits (editFeaturesCode).
EDIT_NOTE = (
    "# Map Editor writes this code from its edit list: each edit, in the\n"
    "# order it was made, on the features whose key is one of its ids. It is\n"
    "# written again when the list changes.\n"
)
LEVERS = {
    "towers-removed": (
        {"key": "building_id", "edits": [
            {"op": "remove", "where": "around_park", "label": "Tall parts around a park"},
        ]},
        EDIT_NOTE + "return curio_edit_features(input_0, [\n"
        '    {"op": "remove", "where": "around_park", "label": "Tall parts around a park"},\n'
        '], key="building_id")\n',
    ),
    "height-cap": (
        {"key": "building_id", "edits": [
            {"op": "expr", "where": "around_park", "column": "height", "value": "min(height, height_cap_m)",
             "label": "Tall parts around a park cut to the cap"},
        ]},
        EDIT_NOTE + "return curio_edit_features(input_0, [\n"
        '    {"op": "expr", "where": "around_park", "column": "height", "value": "min(height, height_cap_m)", '
        '"label": "Tall parts around a park cut to the cap"},\n'
        '], key="building_id")\n',
    ),
}

def _change_code(scenario: str, name: str) -> str:
    """A what-if's change in shadow: its Raster Calculator's code."""
    return (
        f"# {name}'s accumulated shadow, on input_1, minus Existing's, on\n"
        f"# input_0, cell by cell, in minutes: below zero where {DOING[scenario]}\n"
        "# takes shadow away, 0 where nothing changes.\n"
        "from scout_rasters.raster_algebra import raster_calculate\n"
        "\n"
        'return raster_calculate("subtract", [input_1, input_0], output_file=curio_output_file)\n'
    )


#: Color ranges the maps shown side by side share, so a color is the same value
#: on each: heights to the rasterizers' Maximum height, the top gray level Deep
#: Umbra reads; shadow to a whole summer day, the most minutes Deep Umbra's
#: output stands for in any season; a change in shadow, either way, as much.
HEIGHT_RANGE = [0, 550]
SHADOW_RANGE = [0, 720]
CHANGE_RANGE = [-720, 720]


def _map(get_fnv, interpolator, color_range, title, *, quantitative=False, center=None, pick_by=None) -> dict:
    layer = {"dataRef": "[!! input_0 !!]"}
    if pick_by is not None:
        layer["isPick"] = True
        layer["selectFields"] = [pick_by]
    layer["getFnv"] = get_fnv
    if quantitative:
        layer["getFnvType"] = "quantitative"
    layer["colorMapInterpolator"] = interpolator
    layer["colorMapRange"] = color_range
    if center is not None:
        layer["colorMapCenter"] = center
    layer["title"] = title
    return {"map": {"layerRefs": [layer]}}


def _dataflow() -> dict:
    return json.loads(DATAFLOW.read_text(encoding="utf-8"))["dataflow"]


def _nodes(spec: dict) -> dict:
    return {node["id"]: node for node in spec["nodes"]}


def _into(spec: dict) -> dict:
    return {(edge["target"], edge["targetHandle"]): edge["source"] for edge in spec["edges"]}


def _template(package: Path, node_type: str) -> tuple[dict, str]:
    """The template of *node_type* in *package*, and its source."""
    template_id = node_type.split("/", 1)[1]
    (template,) = [t for t in json.loads((package / "manifest.json").read_text(encoding="utf-8"))["templates"]
                   if t["id"] == template_id]
    return template, (package / template["source"]).read_text(encoding="utf-8")


def _node_id(key: str, what: str) -> str:
    return f"park-shade-{key}-{what}"


def _season(spec: dict) -> dict:
    """The one node titled Season: the Python node that holds the season."""
    (season,) = [node for node in spec["nodes"] if node.get("title") == "Season"]
    return season


# ---------------------------------------------------------------------------
# The file
# ---------------------------------------------------------------------------

def test_it_is_three_scenarios_over_one_context_from_the_extract():
    """One Autark data node and four code nodes, the Season node among them,
    are the context, and no Parameter node is left; each scenario holds its
    lever (none in Existing), its package
    nodes, its shade per park and its two maps; the chart, the changes and
    the maps after the changes are in no scenario, and no Compare Scenarios
    node is left. No dataset: the data comes from the extract. The lockfile
    names both packages."""
    spec = _dataflow()
    assert spec["name"] == NAME
    assert spec["packages"] == ["curio.scout@1", "model.scout.deep-umbra@1"]
    assert not spec.get("datasets"), spec.get("datasets")
    assert spec["categories"] == {"city": ["New York"], "topic": ["Heat and climate", "Greenery"],
                                  "complexity": ["Beginner"]}
    nodes = _nodes(spec)
    scenarios = {scenario["id"]: scenario for scenario in spec["scenarios"]}
    assert [(s["id"], s["name"], s["color"]) for s in spec["scenarios"]] == [s[:3] for s in SCENARIOS]
    members = {node_id for scenario in spec["scenarios"] for node_id in scenario["nodes"]}
    # Below the scenarios: every node a scenario's node feeds, and so on down.
    below: set = set()
    frontier = list(members)
    while frontier:
        source = frontier.pop()
        for edge in spec["edges"]:
            if edge["source"] == source and edge["target"] not in members | below:
                below.add(edge["target"])
                frontier.append(edge["target"])
    context = sorted(nodes[n]["type"] for n in nodes if n not in members | below)
    assert context == sorted([AUTARK, PYTHON, PYTHON, PYTHON, PYTHON]), context
    assert PARAMETER not in {node["type"] for node in spec["nodes"]}
    for scenario, _name, _color, key in SCENARIOS:
        types = sorted(nodes[n]["type"] for n in scenarios[scenario]["nodes"])
        lever = [] if scenario == "existing" else [INTERACTION]
        assert types == sorted([*lever, RASTERIZE, SHADOW, PYTHON, AUTARK, AUTARK]), (scenario, types)
    assert sorted(nodes[n]["type"] for n in below) == sorted(
        [DOTS] + [CALCULATOR] * 2 + [PYTHON] * 2 + [AUTARK] * 4), below
    assert COMPARE not in {node["type"] for node in spec["nodes"]}
    # The chart feeds nothing; each change feeds one Autark map.
    changes = {n for n in below if nodes[n]["type"] in (CALCULATOR, PYTHON)}
    assert not [e for e in spec["edges"] if e["source"] == CHART]
    after = sorted(nodes[e["target"]]["type"] for e in spec["edges"] if e["source"] in changes)
    assert after == [AUTARK] * 4, after


def test_the_loader_reads_the_parks_box_and_the_buildings_box_around_it():
    """The data node loads the extract twice into one table name: its parks in
    the parks' box, as Autark cuts them at it, and its buildings in a box
    about 300 m larger on every side, up to the box the extract is cut at.
    Nothing else: no surface, roads or water. Both boxes are inside the
    extract's, so it holds every feature either load keeps."""
    spec = _dataflow()
    loader = _nodes(spec)["park-shade-layers"]
    assert loader["type"] == AUTARK
    document = json.loads(loader["content"])
    assert set(document) == {"data"}, "the loader draws nothing, so a run on the server runs it"
    assert document["data"] == [
        {"type": "osm", "pbfFileUrl": EXTRACT, "queryArea": {"bbox": PARKS_BOX},
         "outputTableName": "table_osm", "autoLoadLayers": {"layers": ["parks"]}},
        {"type": "osm", "pbfFileUrl": EXTRACT, "queryArea": {"bbox": BUILDINGS_BOX},
         "outputTableName": "table_osm", "autoLoadLayers": {"layers": ["buildings"]}},
    ]
    import importlib.util

    script = importlib.util.spec_from_file_location("build_example_pbfs", REPO / "scripts" / "build_example_pbfs.py")
    pbfs = importlib.util.module_from_spec(script)
    script.loader.exec_module(pbfs)
    cut_south, cut_west, cut_north, cut_east = pbfs.AREAS["lower_mnt"].box
    west, south, east, north = PARKS_BOX
    assert cut_west <= west < east <= cut_east and cut_south <= south < north <= cut_north
    # The parks' box grown by MARGIN_M on every side, then cut at the extract's box.
    metres_per_degree = 111_320
    lon = MARGIN_M / (metres_per_degree * math.cos(math.radians((south + north) / 2)))
    lat = MARGIN_M / metres_per_degree
    grown = [max(west - lon, cut_west), max(south - lat, cut_south), min(east + lon, cut_east),
             min(north + lat, cut_north)]
    assert BUILDINGS_BOX == pytest.approx(grown, abs=10 / metres_per_degree), (BUILDINGS_BOX, grown)
    assert (BUILDINGS_BOX[0], BUILDINGS_BOX[1]) == (cut_west, cut_south), "the extract ends west and south"


def test_the_package_nodes_are_as_the_palette_drops_them():
    """Each scenario's Rasterize Buildings holds the template's source and
    widgets, and its Accumulated Shadow the template's cell reading the season
    on its second circle, from the Season node, a Python node whose widget is
    the template's and whose code returns it. Buildings around parks holds
    the rule's two settings as widgets of its own."""
    spec = _dataflow()
    nodes = _nodes(spec)
    raster_template, raster_source = _template(RASTER_PACKAGE, RASTERIZE)
    umbra_template, umbra_source = _template(MODEL_PACKAGE, SHADOW)
    for _scenario, _name, _color, key in SCENARIOS:
        rasterizer, shadow = nodes[_node_id(key, "rasterize")], nodes[_node_id(key, "shadow")]
        assert rasterizer["type"] == RASTERIZE and rasterizer["content"] == raster_source
        assert rasterizer["metadata"]["widgets"] == raster_template["widgets"]
        assert shadow["type"] == SHADOW
        assert shadow["content"] == umbra_source.replace("[!! season !!]", "input_1")
        assert not shadow["metadata"].get("widgets")
    season = _season(spec)
    assert season["type"] == PYTHON
    # Its header and the chips it feeds name it Season, not its type's name.
    assert season["metadata"]["packageTemplateLabel"] == "Season"
    assert season["metadata"]["widgets"] == umbra_template["widgets"]
    assert season["content"].rstrip("\n").endswith("\nreturn [!! season !!]"), season["content"]
    around = nodes["park-shade-around"]
    assert [(w["name"], w["label"], w["default"], w["options"]["units"]) for w in around["metadata"]["widgets"]] == [
        ("park_distance", "Distance from a park", PARK_DISTANCE_M, "m"),
        ("tall_height", "Tall building height", TALL_HEIGHT_M, "m"),
    ]


def test_the_wiring_reads_each_input_where_its_code_does():
    """Building heights and Open-air parks read the loader's layers by name;
    Buildings around parks reads its two widgets; each scenario's chain starts
    at Building heights (Existing) or at its lever, which reads Buildings
    around parks; each Accumulated Shadow reads the season on input_1, from
    the Season node, which reads nothing; each Shade per park reads its
    shadow on input_0 and the parks on input_1. Each lever is linked to the
    buildings map it feeds by an interaction edge, from its in/out dot to the
    map's, for selections both ways: the dataflow's only interaction edges."""
    spec = _dataflow()
    nodes = _nodes(spec)
    into = _into(spec)
    assert into[("park-shade-heights", "in")] == "park-shade-layers"
    assert "[!! input_0:table_osm_buildings !!]" in nodes["park-shade-heights"]["content"]
    assert (into[("park-shade-parks", "in")], into[("park-shade-parks", "in_1")]) == (
        "park-shade-layers", "park-shade-heights",
    )
    assert "[!! input_0:table_osm_parks !!]" in nodes["park-shade-parks"]["content"]
    assert (into[("park-shade-around", "in")], into[("park-shade-around", "in_1")]) == (
        "park-shade-heights", "park-shade-parks",
    )
    for code, name in (("[!! tall_height !!]", "Tall building height"), ("[!! park_distance !!]", "Distance")):
        assert code in nodes["park-shade-around"]["content"], name
    season = _season(spec)["id"]
    assert not [e for e in spec["edges"] if e["target"] == season]
    assert sorted(e["target"] for e in spec["edges"] if e["source"] == season) == sorted(
        _node_id(key, "shadow") for _s, _n, _c, key in SCENARIOS
    )
    for scenario, _name, _color, key in SCENARIOS:
        start = "park-shade-heights" if scenario == "existing" else _node_id(key, "lever")
        if scenario != "existing":
            assert into[(start, "in")] == "park-shade-around", scenario
        assert into[(_node_id(key, "rasterize"), "in")] == start
        assert into[(_node_id(key, "buildings-map"), "in")] == start
        assert into[(_node_id(key, "shadow"), "in")] == _node_id(key, "rasterize")
        assert into[(_node_id(key, "shadow"), "in_1")] == season
        assert into[(_node_id(key, "shadow-map"), "in")] == _node_id(key, "shadow")
        assert (into[(_node_id(key, "shade"), "in")], into[(_node_id(key, "shade"), "in_1")]) == (
            _node_id(key, "shadow"), "park-shade-parks",
        )
    links = sorted((e["source"], e["target"], e["sourceHandle"], e["targetHandle"])
                   for e in spec["edges"] if e.get("type") == "Interaction")
    assert links == sorted(
        (_node_id(key, "lever"), _node_id(key, "buildings-map"), "in/out", "in/out") for _s, _n, _c, key in SCENARIOS[1:]
    ), links


def test_the_levers_are_interaction_nodes_whose_code_is_their_log():
    """Towers removed and Height cap are Map Editor nodes keyed on
    building_id, each with one labelled edit picked by the condition
    around_park, so a user can add more and press Commit edits; each node's
    code, its only state, is the code it writes from its log: one call that
    carries the log, and no metadata key holds the log too."""
    from utk_curio.sandbox.util.input_names import call_as_node

    nodes = _nodes(_dataflow())
    for scenario, name, _color, key in SCENARIOS[1:]:
        lever = nodes[_node_id(key, "lever")]
        settings, code = LEVERS[scenario]
        assert (lever["type"], lever["title"]) == (INTERACTION, name)
        assert "editFeatures" not in lever["metadata"], lever["metadata"]
        assert lever["content"] == code
        calls = []
        call_as_node(
            textwrap.indent(lever["content"], "    "),
            {"curio_edit_features": lambda value, edits, **kwargs: calls.append((value, edits, kwargs))},
            "the buildings", [0],
        )
        assert calls == [("the buildings", settings["edits"], {"key": settings["key"]})], (scenario, calls)


def test_the_chart_and_the_changes_hold_what_they_compare():
    """One chart of each park's mean minutes in the three scenarios: Scout's
    Dots with a range, its spec its template's own, a park per row and a dot
    per scenario, reading the three Shade per park nodes in the order of
    their boxes. For each what-if, a Raster Calculator of the what-if's
    shadow minus Existing's, and a Python node of the what-if's shade per park
    minus Existing's, matched by the park's name, each reading Existing's on
    input_0 and the what-if's on input_1, as Compare Scenarios' Difference
    read them. The two what-ifs' codes differ only in the what-if's name."""
    spec = _dataflow()
    nodes = _nodes(spec)
    into = _into(spec)
    chart = nodes[CHART]
    template, source = _template(RASTER_PACKAGE, DOTS)
    assert (chart["type"], chart["content"]) == (DOTS, source)
    assert set(chart["metadata"]) == {"keywords", "widgets"}, chart["metadata"]
    assert [{k: v for k, v in w.items() if k != "value"} for w in chart["metadata"]["widgets"]] == template["widgets"]
    assert {w["name"]: w["value"] for w in chart["metadata"]["widgets"]} == CHART_WIDGETS
    assert [into[(CHART, circle)] for circle in ("in", "in_1", "in_2")] == [
        _node_id(key, "shade") for _s, _n, _c, key in SCENARIOS
    ]
    codes = {}
    for scenario, name, _color, key in SCENARIOS[1:]:
        change, park_change = nodes[f"park-shade-{key}-change"], nodes[f"park-shade-{key}-park-change"]
        assert (change["type"], change["content"]) == (CALCULATOR, _change_code(scenario, name)), scenario
        assert (into[(change["id"], "in")], into[(change["id"], "in_1")]) == (
            _node_id("existing", "shadow"), _node_id(key, "shadow"),
        )
        assert park_change["type"] == PYTHON, scenario
        assert 'before, after = input_0.set_index("park"), input_1.set_index("park")\n' in park_change["content"]
        assert "\nout[numbers] = now - was\n" in park_change["content"]
        assert (into[(park_change["id"], "in")], into[(park_change["id"], "in_1")]) == (
            _node_id("existing", "shade"), _node_id(key, "shade"),
        )
        for node in (change, park_change):
            assert node["metadata"] == {"keywords": []}, node["id"]
        codes[scenario] = park_change["content"]
    assert codes["towers-removed"].replace("Towers removed", "Height cap") == codes["height-cap"]


def test_every_map_is_valid_and_the_maps_side_by_side_share_one_range(tmp_path):
    """Each scenario's buildings in 3D over the rasterizers' height range and
    its shadow over a summer day's minutes; each what-if's buildings picked by
    building_id, the column its lever's edits find them by, as the map the
    lever edits on; each what-if's change in shadow on a scale centered on no
    change, and each park's change on a scale whose middle stays visible, both
    over the same minutes either way. Every document is valid for the
    grammar."""
    from utk_curio.backend.app.agents.domain import document_validation

    spec = _dataflow()
    nodes = _nodes(spec)
    expected = {}
    for scenario, _name, _color, key in SCENARIOS:
        expected[_node_id(key, "buildings-map")] = _map(
            "height", "interpolateViridis", HEIGHT_RANGE, "Building height (m)", quantitative=True,
            pick_by=None if scenario == "existing" else LEVERS[scenario][0]["key"])
        expected[_node_id(key, "shadow-map")] = _map(
            "band_1", "interpolateReds", SHADOW_RANGE, "Accumulated shadow (minutes)")
    for _scenario, name, _color, key in SCENARIOS[1:]:
        expected[f"park-shade-{key}-change-map"] = _map(
            "band_1", "interpolateRdBu", CHANGE_RANGE, f"Shadow change, {name} (minutes)", center=0)
        expected[f"park-shade-{key}-park-change-map"] = _map(
            "mean_min", "interpolateRdYlBu", CHANGE_RANGE, f"Change in mean shadow, {name} (minutes)",
            quantitative=True)
    maps = {n: node for n, node in nodes.items() if node["type"] == AUTARK and n != "park-shade-layers"}
    assert sorted(maps) == sorted(expected)
    for node_id, document in expected.items():
        assert json.loads(maps[node_id]["content"]) == document, node_id
        named = maps[node_id]["content"].replace("[!! input_0 !!]", "input_0")
        assert document_validation.validate(AUTARK, named) == {"status": document_validation.STATUS_VALID}
    raster_template, _source = _template(RASTER_PACKAGE, RASTERIZE)
    (max_height,) = [w["default"] for w in raster_template["widgets"] if w["name"] == "max_height"]
    assert HEIGHT_RANGE == [0, max_height]
    from utk_curio.sandbox.util.package_modules import importable
    from utk_curio.sandbox.util.staging import stage_package_modules

    run = tmp_path / "run"
    run.mkdir()
    staged = stage_package_modules(_PACKAGE_MODULES[SHADOW], str(run))
    import importlib

    with importable(str(run / staged["root"]), staged["names"]):
        deep_umbra = importlib.import_module("deep_umbra.deep_umbra")
        outputs = importlib.import_module("deep_umbra.node_outputs")
        longest = max(deep_umbra.season_factor(season) for season in outputs.SEASONS)
    assert SHADOW_RANGE == [0, longest] and CHANGE_RANGE == [-longest, longest]


# ---------------------------------------------------------------------------
# The dataflow, run as written
# ---------------------------------------------------------------------------

#: Put before the compiled data node: serves the extract from disk, as the
#: backend's ``/file/`` route would, and refuses any other request
#: (``test_autk_server_data_load.py``).
_FETCH_FROM_DISK = """{
  const __fs = require('fs');
  const __path = require('path');
  const __prefix = '__CURIO_BACKEND_URL__/file/';
  globalThis.fetch = async (url) => {
    const href = typeof url === 'string' ? url : (url && url.url) || String(url);
    const rel = href.startsWith(__prefix) ? decodeURIComponent(href.slice(__prefix.length)) : null;
    if (rel !== EXTRACT) throw new Error('no socket in this test: ' + href);
    return new Response(__fs.readFileSync(__path.join(ROOT, rel)), { status: 200 });
  };
}
"""

#: Each package node's modules, as a run stages them: Accumulated Shadow's
#: own, then Scout's, which its package names in ``dependencies.packages``.
_PACKAGE_MODULES = {
    RASTERIZE: {"root": str(RASTER_PACKAGE / "sources"), "names": [RASTER_MODULE]},
    CALCULATOR: {"root": str(RASTER_PACKAGE / "sources"), "names": [RASTER_MODULE]},
    SHADOW: [
        {"root": str(MODEL_PACKAGE / "sources"), "names": ["deep_umbra"]},
        {"root": str(RASTER_PACKAGE / "sources"), "names": [RASTER_MODULE]},
    ],
}


def _load_layers(content: str) -> list:
    """The data node's layers, as a run on the server hands them on."""
    from utk_curio.common.autk_data_compiler import compile_data_spec
    from utk_curio.sandbox.app.worker import execute_js_code
    from utk_curio.sandbox.util.parsers import load_from_duckdb

    code = compile_data_spec(content)
    serve = _FETCH_FROM_DISK.replace("EXTRACT", json.dumps(EXTRACT)).replace("ROOT", json.dumps(str(REPO)))
    result = execute_js_code(serve + code, "", "AUTK_GRAMMAR", "", launch_dir=str(REPO), session_id=None)
    assert result["output"]["path"], result["stderr"]
    return load_from_duckdb(result["output"]["path"], session_id=None)


def _run_code(node: dict, inputs: list, media: Path):
    """*node*'s code, its references resolved as a run resolves them, run in
    the sandbox on *inputs* (one value per circle, each saved as its own
    upstream output): ``(the value it hands on, what it printed)``."""
    from utk_curio.backend.app.execution.code_references import resolve_references
    from utk_curio.sandbox.app.worker import execute_code
    from utk_curio.sandbox.util.parsers import load_from_duckdb, save_to_duckdb

    widgets = (node.get("metadata") or {}).get("widgets") or []
    code, problems = resolve_references(
        node["content"], widgets, "python", inputs=[{"slot": slot} for slot in range(len(inputs))],
    )
    assert problems == [], (node["id"], problems)
    if not inputs:
        file_path, data_type = "", ""
    elif len(inputs) == 1:
        file_path, data_type = save_to_duckdb(inputs[0], node_id=f"{node['id']}-in"), ""
    else:
        file_path = repr([{"path": save_to_duckdb(value, node_id=f"{node['id']}-in-{slot}")}
                          for slot, value in enumerate(inputs)])
        data_type = "outputs"
    result = execute_code(
        textwrap.indent(code, "    "), file_path, node["type"], data_type,
        save_dataset=False, media_dir=str(media), package_modules=_PACKAGE_MODULES.get(node["type"]),
        models={MODEL_ID: str(MODEL_PACKAGE)}, input_slots=list(range(len(inputs))),
    )
    assert result["stderr"] == "", f"{node['id']}: {result['stderr']}"
    return load_from_duckdb(result["output"]["path"]), result["stdout"]


@pytest.fixture(scope="module")
def ran(tmp_path_factory):
    """Every node of the dataflow run as written, once for the module, but the
    chart, which draws in the browser: ``{node id: (value, printed)}``, the
    data node's value its layers."""
    from utk_curio.cli import dependencies
    from utk_curio.sandbox.app.worker import _worker_init
    from utk_curio.sandbox.util.db import init_db, release_connection

    spec = _dataflow()
    nodes = _nodes(spec)
    into = _into(spec)
    root = tmp_path_factory.mktemp("park-shade")
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("CURIO_LAUNCH_CWD", str(root))
        patch.setenv("CURIO_SHARED_DATA", str(root / "data"))
        patch.setenv("HOME", str(root))
        patch.setattr(Path, "home", lambda: root)
        # An address nothing answers at: the fetch above is the only way in.
        patch.setenv("FLASK_BACKEND_HOST", "curio-backend.invalid")
        patch.setenv("FLASK_BACKEND_PORT", "1")
        release_connection()
        init_db()
        dependencies.seed_duckdb_extensions()
        _worker_init()
        values = {"park-shade-layers": (_load_layers(nodes["park-shade-layers"]["content"]), [])}

        def inputs_of(node_id):
            handles = sorted((h for (target, h) in into if target == node_id),
                             key=lambda h: 0 if h == "in" else int(h.split("_")[1]))
            return [values[into[(node_id, h)]][0] for h in handles]

        order = [_season(spec)["id"], "park-shade-heights", "park-shade-parks", "park-shade-around",
                 "park-shade-removed-lever", "park-shade-capped-lever"]
        for _scenario, _name, _color, key in SCENARIOS:
            order += [_node_id(key, "rasterize"), _node_id(key, "shadow"), _node_id(key, "shade")]
        for _scenario, _name, _color, key in SCENARIOS[1:]:
            order += [f"park-shade-{key}-change", f"park-shade-{key}-park-change"]
        for node_id in order:
            values[node_id] = _run_code(nodes[node_id], inputs_of(node_id), root / "media")
        yield values
        release_connection()


def _value(ran, node_id):
    return ran[node_id][0]


def _through_the_store(value):
    """*value* as a node reads it on a circle: saved as an upstream output,
    and read back."""
    from utk_curio.sandbox.util.parsers import load_from_duckdb, save_to_duckdb

    return load_from_duckdb(save_to_duckdb(value, node_id="park-shade-input"))


def test_the_loader_hands_on_the_parks_and_every_building_part(ran):
    layers = _value(ran, "park-shade-layers")
    assert [(layer["name"], layer["type"], len(layer["geojson"]["features"])) for layer in layers] == [
        ("table_osm_parks", "parks", PARK_FEATURES),
        ("table_osm_buildings", "buildings", BUILDING_ROWS),
    ]


def test_building_heights_gives_every_part_a_height_in_metres(ran):
    """Every row a height above the ground: the height mapped for it, else its
    levels times the floor height, else the default height; the building_id,
    name and footprint kept, the frame marked as buildings."""
    buildings = _value(ran, "park-shade-heights")
    assert list(buildings.columns) == ["building_id", "name", "geometry", "height"]
    assert len(buildings) == BUILDING_ROWS and buildings["building_id"].nunique() == BUILDING_IDS
    assert buildings["height"].notna().all() and (buildings["height"] > 0).all()
    assert float(buildings["height"].max()) == TALLEST_M
    assert getattr(buildings, "metadata", None) == {"layerType": "buildings"}


def test_open_air_parks_are_the_named_parks_large_enough_and_in_the_open(ran):
    parks = _value(ran, "park-shade-parks")
    assert list(parks.columns) == ["park", "area_m2", "geometry"]
    assert list(parks["park"]) == PARKS
    assert (parks["area_m2"] >= 500).all(), parks[parks["area_m2"] < 500]
    assert parks.crs.to_epsg() == 4326


def test_buildings_around_parks_marks_the_parts_by_one_rule_for_every_park(ran):
    """The node's marks are the rule's, recomputed here: a part is marked
    exactly when it is at least the Tall building height tall and within the
    Distance from a park of any park. Height cap's cap is on every row."""
    marked = _value(ran, "park-shade-around")
    parks = _value(ran, "park-shade-parks")
    assert len(marked) == BUILDING_ROWS
    assert getattr(marked, "metadata", None) == {"layerType": "buildings"}
    utm = parks.estimate_utm_crs()
    outlines = parks.to_crs(utm).geometry.union_all()
    near = marked.to_crs(utm).geometry.distance(outlines) <= PARK_DISTANCE_M
    rule = (marked["height"] >= TALL_HEIGHT_M) & near
    assert (marked["around_park"] == rule).all()
    assert int(marked["around_park"].sum()) == MARKED_ROWS
    assert marked.loc[marked["around_park"], "building_id"].nunique() == MARKED_IDS
    assert (marked["height_cap_m"] == TALL_HEIGHT_M).all()
    assert set(marked["nearest_park"]) <= set(PARKS)


def test_towers_removed_hands_on_every_part_but_the_marked_ones(ran):
    marked = _value(ran, "park-shade-around")
    removed, printed = ran["park-shade-removed-lever"]
    assert len(removed) == BUILDING_ROWS - MARKED_ROWS
    assert not removed["around_park"].any()
    kept = marked[~marked["around_park"]]
    assert removed["height"].tolist() == kept["height"].tolist()
    assert printed == [f"Map Editor: the input, features matched on building_id: {MARKED_ROWS} removed."]


def test_height_cap_cuts_the_marked_parts_to_the_tall_building_height(ran):
    marked = _value(ran, "park-shade-around")
    capped, printed = ran["park-shade-capped-lever"]
    assert len(capped) == BUILDING_ROWS
    assert (capped.loc[marked["around_park"].to_numpy(), "height"] == TALL_HEIGHT_M).all()
    assert (capped.loc[~marked["around_park"].to_numpy(), "height"].to_numpy()
            == marked.loc[~marked["around_park"], "height"].to_numpy()).all()
    assert printed == [f"Map Editor: the input, features matched on building_id: {MARKED_ROWS} changed."]


def test_the_three_scenarios_rasters_share_one_grid(ran):
    """The heights and the shadows of the three scenarios are on one grid, the
    tiles around the buildings' box, and each shadow says its season's minutes."""
    grids = set()
    for _scenario, _name, _color, key in SCENARIOS:
        heights, shadow = _value(ran, _node_id(key, "rasterize")), _value(ran, _node_id(key, "shadow"))
        for raster in (heights, shadow):
            assert (raster.width, raster.height) == GRID and raster.crs.to_epsg() == 3395
            grids.add(tuple(raster.transform)[:6])
            assert {k: raster.tags()[k] for k in TILE} == TILE
        assert (shadow.tags()["season"], shadow.tags()["minutes"]) == ("summer", "720")
    assert len(grids) == 1, grids


def test_each_park_has_its_minutes_of_shadow_and_the_levers_take_shadow_away(ran):
    """One row per park in each scenario, its mean minutes within MINUTES of
    the pinned run's; in every park removing the towers takes away more shadow
    than capping them, and capping them takes some away."""
    means = {}
    for scenario, _name, _color, key in SCENARIOS:
        shade = _value(ran, _node_id(key, "shade"))
        assert list(shade["park"]) == PARKS, scenario
        assert {"cells", "mean_min", "median_min", "p90_min", "pct_daylight",
                "share_sun", "share_partial", "share_deep"} <= set(shade.columns)
        shares = shade["share_sun"] + shade["share_partial"] + shade["share_deep"]
        assert all(abs(total - 1) < 1e-9 for total in shares), scenario
        means[scenario] = dict(zip(shade["park"], shade["mean_min"]))
        off = {park: (round(means[scenario][park], 2), pinned)
               for park, pinned in MEANS[scenario].items() if abs(means[scenario][park] - pinned) > MINUTES}
        assert not off, f"{scenario}: (ours, pinned) {off}"
    for park in PARKS:
        assert means["towers-removed"][park] < means["height-cap"][park] < means["existing"][park], park


def test_the_chart_stacks_the_three_scenarios_parks(ran):
    """The rows the chart reads, its ``inputs`` dataset as a chart stacks it
    (``stack_inputs``, the twin of the browser's): each scenario's parks in
    circle order, under its box's id and name, each row what Compare
    Scenarios' stacked table held for it (``stacked_rows``), its outline left
    out."""
    from utk_curio.backend.tests._support.scenario_changes import stacked_rows
    from utk_curio.sandbox.util.scenario_stack import stack_inputs

    spec = _dataflow()
    assert _nodes(spec)[CHART]["type"] == DOTS, _nodes(spec)[CHART]["type"]
    into = _into(spec)
    box = {node_id: (s["id"], s["name"]) for s in spec["scenarios"] for node_id in s["nodes"]}
    entries = [(*box[into[(CHART, circle)]], _value(ran, into[(CHART, circle)])) for circle in ("in", "in_1", "in_2")]
    rows = stack_inputs(entries)
    stacked = stacked_rows(entries)
    assert all(list(row)[:2] == ["scenario", "scenario_name"] for row in stacked)
    assert len(stacked) == len(rows) == 3 * len(PARKS)
    for scenario, name, _color, _key in SCENARIOS:
        held = [row for row in stacked if row["scenario"] == scenario]
        assert {row["scenario_name"] for row in held} == {name} and [row["park"] for row in held] == PARKS
    assert [row["__input__"] for row in rows] == [circle for circle in range(3) for _park in PARKS]
    assert [{k: v for k, v in row.items() if k != "__input__"} for row in rows] == stacked


def test_each_parks_change_in_shade_is_the_what_if_minus_existing(ran):
    existing = _value(ran, _node_id("existing", "shade")).set_index("park")
    for scenario, _name, _color, key in SCENARIOS[1:]:
        change = _value(ran, f"park-shade-{key}-park-change")
        what_if = _value(ran, _node_id(key, "shade")).set_index("park")
        assert list(change["park"]) == PARKS and set(change["change"]) == {"changed"}, scenario
        for row in change.itertuples():
            expected = what_if.loc[row.park, "mean_min"] - existing.loc[row.park, "mean_min"]
            assert abs(row.mean_min - expected) < 1e-9, (scenario, row.park)
            assert row.mean_min < 0, (scenario, row.park)


def test_each_parks_change_is_what_compares_difference_wrote(ran, tmp_path):
    """Each what-if's park change, run as written, is what Compare Scenarios'
    Difference keyed on the park wrote for the same two inputs
    (``keyed_change``): the same columns in the same order, ``park`` first and
    ``change`` second, each of their types, every value and outline, and the
    coordinate system. With the what-if's parks in the opposite order each
    park is still matched by its name, as Compare matched it, and the change
    is the same."""
    from geopandas.testing import assert_geodataframe_equal

    from utk_curio.backend.tests._support.scenario_changes import keyed_change

    nodes = _nodes(_dataflow())
    existing = _value(ran, _node_id("existing", "shade"))
    for scenario, _name, _color, key in SCENARIOS[1:]:
        assert nodes[f"park-shade-{key}-park-change"]["type"] == PYTHON, scenario
        what_if = _value(ran, _node_id(key, "shade"))
        ours = _value(ran, f"park-shade-{key}-park-change")
        compares = keyed_change(_through_the_store(existing), _through_the_store(what_if), "park")
        assert list(ours.columns)[:2] == ["park", "change"], list(ours.columns)
        assert list(ours.columns) == list(compares.columns)
        assert ours.dtypes.astype(str).tolist() == compares.dtypes.astype(str).tolist()
        assert_geodataframe_equal(ours, compares)
        assert ours.crs.to_epsg() == 4326
        reversed_parks = what_if.iloc[::-1].reset_index(drop=True)
        assert list(reversed_parks["park"]) == PARKS[::-1]
        again, _printed = _run_code(nodes[f"park-shade-{key}-park-change"], [existing, reversed_parks],
                                    tmp_path / "media")
        assert_geodataframe_equal(
            again, keyed_change(_through_the_store(existing), _through_the_store(reversed_parks), "park"),
        )
        assert_geodataframe_equal(again, ours)


#: The park the what-if leaves out, and the one Existing leaves out, in the
#: next test.
LEFT_OUT, ONLY_IN_THE_WHAT_IF = "Coenties Slip", "Bowling Green"


def test_a_park_one_side_lacks_is_removed_or_added_as_compare_wrote_it(ran, tmp_path):
    """A user's edit can leave a park out of one scenario. Each what-if's park
    change then writes what Compare Scenarios' Difference keyed on the park
    wrote (``keyed_change``): a park only Existing has is ``removed``, in
    Existing's order, its numbers empty and its outline Existing's; a park
    only the what-if has is ``added``, after every park of Existing's, its
    numbers empty and its outline the what-if's. Every other park is the
    what-if's minus Existing's, as before."""
    import numpy as np
    from geopandas.testing import assert_geodataframe_equal

    from utk_curio.backend.tests._support.scenario_changes import keyed_change

    nodes = _nodes(_dataflow())
    existing = _value(ran, _node_id("existing", "shade"))
    numbers = ["area_m2", "cells", "mean_min", "median_min", "p90_min", "pct_daylight",
               "share_sun", "share_partial", "share_deep"]
    for scenario, _name, _color, key in SCENARIOS[1:]:
        node = nodes[f"park-shade-{key}-park-change"]
        assert node["type"] == PYTHON, scenario
        what_if = _value(ran, _node_id(key, "shade"))
        cases = {
            "removed": (existing, what_if[what_if["park"] != LEFT_OUT].reset_index(drop=True)),
            "added": (existing[existing["park"] != ONLY_IN_THE_WHAT_IF].reset_index(drop=True), what_if),
        }
        for change, inputs in cases.items():
            ours, _printed = _run_code(node, list(inputs), tmp_path / "media")
            compared = keyed_change(*(_through_the_store(value) for value in inputs), "park")
            assert list(ours.columns) == list(compared.columns), (scenario, change)
            assert ours.dtypes.astype(str).tolist() == compared.dtypes.astype(str).tolist(), (scenario, change)
            assert_geodataframe_equal(ours, compared)
            park = LEFT_OUT if change == "removed" else ONLY_IN_THE_WHAT_IF
            expected_order = PARKS if change == "removed" else [p for p in PARKS if p != park] + [park]
            assert list(ours["park"]) == expected_order, (scenario, change)
            (row,) = ours.index[ours["park"] == park]
            assert ours.loc[row, "change"] == change, (scenario, change)
            assert ours.loc[row, numbers].isna().all(), (scenario, change)
            outline = inputs[0 if change == "removed" else 1]
            assert ours.geometry[row].equals_exact(outline.geometry[outline["park"] == park].iloc[0], 1e-9), (
                scenario, change)
            others = ours[ours["park"] != park]
            assert set(others["change"]) == {"changed"}, (scenario, change)
            assert np.allclose(
                others["mean_min"].to_numpy(),
                what_if.set_index("park").loc[others["park"], "mean_min"].to_numpy()
                - existing.set_index("park").loc[others["park"], "mean_min"].to_numpy(),
                rtol=0, atol=1e-9,
            ), (scenario, change)


#: What Compare Scenarios' own functions wrote on fixed Shade per park tables
#: (``park_shade_inputs``), from main before step 6.4 of the plan answering
#: komar41's review removed them (``make_compare_fixtures.py`` beside it, on
#: 72f5d3df5). Deep Umbra's shadow moves with onnxruntime's thread count, so a
#: fixture of a run's shadow would hold one machine's numbers.
COMPARE_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "compare_scenarios" / "park_shade.json"


def test_each_parks_change_on_fixed_tables_is_what_compare_wrote(ran, tmp_path):
    """On Shade per park tables of fixed numbers, each what-if's park change,
    run as written, is what Compare Scenarios' Difference keyed on the park
    wrote (``park_shade.json``): every column, type, value and outline, also
    with the what-if's parks reversed, and with a park left out of one side.
    ``keyed_change`` writes the same."""
    from utk_curio.backend.tests._support.scenario_changes import (
        assert_frame_matches,
        keyed_change,
        park_shade_inputs,
    )

    held = json.loads(COMPARE_FIXTURE.read_text(encoding="utf-8"))
    nodes = _nodes(_dataflow())
    tables = park_shade_inputs(PARKS)
    existing = tables["existing"]
    for scenario, _name, _color, key in SCENARIOS[1:]:
        node = nodes[f"park-shade-{key}-park-change"]
        assert node["type"] == PYTHON, scenario
        what_if = tables[scenario]
        cases = {
            "change": ([existing, what_if], held["change"][scenario]),
            "reversed": ([existing, what_if.iloc[::-1].reset_index(drop=True)], held["change"][scenario]),
            "removed": ([existing, what_if[what_if["park"] != LEFT_OUT].reset_index(drop=True)],
                        held["oneSide"][scenario]["removed"]),
            "added": ([existing[existing["park"] != ONLY_IN_THE_WHAT_IF].reset_index(drop=True), what_if],
                      held["oneSide"][scenario]["added"]),
        }
        for case, (inputs, fixture) in cases.items():
            ours, _printed = _run_code(node, inputs, tmp_path / "media")
            assert_frame_matches(ours, fixture, what=f"the park change, {scenario}, {case}")
            rule = _through_the_store(keyed_change(*(_through_the_store(value) for value in inputs), "park"))
            assert_frame_matches(rule, fixture, what=f"keyed_change, {scenario}, {case}")


def test_the_chart_stacks_fixed_tables_as_compare_stacked_them(ran):
    """On the same fixed tables, the rows the chart reads (``stack_inputs``)
    are what Compare Scenarios' stacked table held (``park_shade.json``), the
    outlines left out, and so are ``stacked_rows``."""
    from utk_curio.backend.tests._support.scenario_changes import (
        assert_rows_match,
        park_shade_inputs,
        stacked_rows,
    )
    from utk_curio.sandbox.util.scenario_stack import stack_inputs

    held = json.loads(COMPARE_FIXTURE.read_text(encoding="utf-8"))["stack"]["rows"]
    tables = park_shade_inputs(PARKS)
    entries = [(scenario, name, _through_the_store(tables[scenario])) for scenario, name, _color, _key in SCENARIOS]
    rows = stack_inputs(entries)
    assert [row["__input__"] for row in rows] == [circle for circle in range(3) for _park in PARKS]
    assert_rows_match([{k: v for k, v in row.items() if k != "__input__"} for row in rows], held,
                      what="the chart's rows")
    assert_rows_match(stacked_rows(entries), held, what="stacked_rows")


def test_each_what_ifs_change_in_shadow_is_a_raster_on_the_shadows_grid(ran):
    """Each what-if's Raster Calculator subtracts the shadows cell by cell on
    their own grid, the what-if's minus Existing's: each takes shadow away on
    the whole, by at most a day's minutes. It is, cell for cell, what Compare
    Scenarios' Difference took from the same shadows, to within float32's last
    places: each shadow's float32 cells, the what-if's minus Existing's, the
    difference written as float32, and no value where either shadow has
    none."""
    import numpy as np

    nodes = _nodes(_dataflow())
    shadow = _value(ran, _node_id("existing", "shadow"))
    before = shadow.read(1, masked=True).astype("float32").filled(np.nan).astype("float64")
    for scenario, _name, _color, key in SCENARIOS[1:]:
        assert nodes[f"park-shade-{key}-change"]["type"] == CALCULATOR, scenario
        change = _value(ran, f"park-shade-{key}-change")
        assert (change.crs.to_epsg(), change.width, change.height) == (3395, *GRID), scenario
        assert tuple(change.transform)[:6] == tuple(shadow.transform)[:6], scenario
        cells = change.read(1, masked=True).astype("float32").filled(np.nan)
        finite = cells[~np.isnan(cells)]
        assert finite.min() < -100 and finite.mean() < 0, (scenario, finite.min(), finite.mean())
        assert -720 <= finite.min() and finite.max() <= 720, (scenario, finite.min(), finite.max())

        what_if = _value(ran, _node_id(key, "shadow"))
        assert tuple(what_if.transform)[:6] == tuple(shadow.transform)[:6], scenario
        after = what_if.read(1, masked=True).astype("float32").filled(np.nan).astype("float64")
        took = (after - before).astype("float32")
        compared = took[~np.isnan(took)]
        assert compared.min() < -100 and compared.mean() < 0, (scenario, compared.min(), compared.mean())
        assert -720 <= compared.min() and compared.max() <= 720, (scenario, compared.min(), compared.max())
        assert np.array_equal(np.isnan(cells), np.isnan(took)), scenario
        assert np.allclose(cells, took, rtol=0, atol=1e-3, equal_nan=True), (
            scenario, float(np.nanmax(np.abs(cells - took))),
        )
