#!/usr/bin/env python3
"""Write the ShadowsAnywhere example: SCOUT's shadow study on a city SCOUT
never shipped, with the data from the Discovery Catalog and the minutes of
shadow in each park compared across three scenarios.

``WhatIfShadows`` runs SCOUT's rasterizer and Deep Umbra on SCOUT's own
Chicago Loop buildings. This dataflow runs the same nodes on Lower Manhattan,
some 30 parks among very tall towers, from ``data.curio.lower-manhattan-shadows``
(Overture Maps' buildings and OpenStreetMap's parks, as the Discovery Catalog
downloads them; built by ``scripts/build_lower_manhattan_shadows_dataset.py``):

- **Building heights** fills the height Rasterize Buildings needs, from
  Overture's height, its number of floors, or a default.
- **Open-air parks** keeps the named parks large enough to measure, not under
  a roof and not mapped twice.
- **Buildings around parks** marks the buildings the what-ifs change, by one
  rule for every park: at least the **Tall building height** tall, within the
  **Distance from a park** of any park. Every park has its tall neighbours
  changed the same way, so the parks compare fairly.
- Three scenarios: **Existing**; **Towers removed**, without the marked
  buildings; and **Height cap**, the marked buildings cut down to the tall
  building height. The two what-ifs change the same buildings. Each
  rasterizes its buildings, runs Deep Umbra for the season the **Season**
  parameter sets, and measures its **Shade per park**: the minutes of shadow
  in each park, their share of the season's daylight, and the share of the
  park in sun, partial shade and deep shade.
- The comparison: each what-if's change in the shadow cell by cell and the
  sun each park gains, on maps, and a Vega-Lite chart that compares the
  parks' shade across the three scenarios.

Building heights, Open-air parks, Buildings around parks and Shade per park
are the nodes a Node Content Builder writes from their goals: their code is
shipped written, and attaching the agent and Solve this node writes it again.

The SCOUT nodes' code and widgets are WhatIfShadows' own, read from it, so the
two stay the same nodes. The ids are new, so the two never share a node.

It keeps the layout saved in the shipped file from the canvas (where each
node stands, its size, which nodes are collapsed); a node the file does not
have yet is laid out as ``scripts/tidy_example_layout.py`` does. It writes
the example's prompt fixture,
``docs/examples/prompts/dataflows/ShadowsAnywhere.prompt.json``, whose digest
and expected graph ``scripts/example_fixture_skeleton.py`` derives.

    python scripts/build_shadows_anywhere_example.py

AUTHORING-ONLY tooling. It is not imported at runtime; the output is
deterministic, so a rerun rewrites the same file.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import sys
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
DATAFLOWS = REPO / "docs" / "examples" / "dataflows"
FIXTURE = REPO / "docs" / "examples" / "prompts" / "dataflows" / "ShadowsAnywhere.prompt.json"
SOURCE = "WhatIfShadows"
NAME = "ShadowsAnywhere"
DATASET_ID = "data.curio.lower-manhattan-shadows"
NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, f"https://curio.dev/examples/{NAME}")
VEGA_SCHEMA = "https://vega.github.io/schema/vega-lite/v6.json"

#: The scenarios, in input-circle order on every comparison node: key, name, colour.
EXISTING, REMOVED, CAPPED = "Existing", "Towers removed", "Height cap"
SCENARIOS = [
    ("existing", EXISTING, "#2a9d8f"),
    ("towers-removed", REMOVED, "#e76f51"),
    ("height-cap", CAPPED, "#6a4c93"),
]
NAMES = [name for _key, name, _color in SCENARIOS]
COLORS = {name: color for _key, name, color in SCENARIOS}
WHAT_IFS = NAMES[1:]

#: The rule's defaults, the two Parameter nodes': every one of the 31 parks
#: has tall neighbours changed (110 of the 209 buildings of 60 m or more),
#: not the whole district.
PARK_DISTANCE_M = 75
TALL_HEIGHT_M = 60


def node_id(key: str) -> str:
    return str(uuid.uuid5(NAMESPACE, key))


def node(key, type_, title, x, y, content, goal, *, widgets=None, **extra) -> dict:
    metadata = {"keywords": []}
    if widgets:
        metadata["widgets"] = widgets
    return {
        "id": node_id(key),
        "type": type_,
        "x": x,
        "y": y,
        "out": "DEFAULT",
        "in": "DEFAULT",
        "goal": goal,
        "metadata": metadata,
        "title": title,
        "content": content,
        **extra,
    }


def edge(source: str, target: str, slot: int = 0) -> dict:
    s, t = node_id(source), node_id(target)
    handle = "in" if slot == 0 else f"in_{slot}"
    return {"id": f"reactflow__edge-{s}out-{t}{handle}", "source": s, "target": t,
            "sourceHandle": "out", "targetHandle": handle}


def number(name, label, default, *, units=None, minimum=0, step=1) -> dict:
    options = {"min": minimum, "step": step}
    if units:
        options["units"] = units
    return {"name": name, "type": "number", "label": label, "default": default, "options": options}


def parameter(key, title, goal, widget) -> dict:
    """A Parameter node: one widget, which other nodes read as [!! @name !!]."""
    return node(key, "curio.builtin/parameter", title, 0, 0, "", goal, widgets=[widget])


def source_nodes() -> dict[str, dict]:
    """WhatIfShadows' Existing nodes by title, for their code and widgets."""
    flow = json.loads((DATAFLOWS / f"{SOURCE}.json").read_text(encoding="utf-8"))
    return {n["title"]: n for n in flow["dataflow"]["nodes"]}


def spec(body: dict) -> str:
    return json.dumps({"$schema": VEGA_SCHEMA, "data": {"name": "inputs"}, **body}, indent=2)


SCENARIO_NAME = {"calculate": "[" + ", ".join(f"'{n}'" for n in NAMES) + "][datum.__input__]",
                 "as": "scenario_name"}
SCENARIO_COLOR = {"domain": NAMES, "range": [COLORS[n] for n in NAMES]}
SCENARIO_LEGEND = {"title": "Scenario", "orient": "bottom"}

# ----------------------------------------------------------------------------
# Code of the shared nodes
# ----------------------------------------------------------------------------

BUILDINGS = f'''# Overture Maps' buildings of Lower Manhattan, as the Discovery Catalog's
# Overture Maps source downloads them, for the parks' box and about 300 m more:
# a tower just outside the parks' box still shades a park at its edge.
return curio_load_data("{DATASET_ID}", part="buildings.parquet")
'''

HEIGHTS = '''# Rasterize Buildings reads a "height" column in metres with a value in every
# row. Overture gives most buildings a height; for the rest, take the number of
# floors times the floor height, and else the default height.
buildings = input_0[~input_0["is_underground"].fillna(False).astype(bool)]
height = buildings["height"].fillna(buildings["num_floors"] * float([!! floor_height !!]))
buildings = buildings.assign(height=height.fillna(float([!! default_height !!])))
# Overture's nested columns (names, sources) are not needed downstream.
buildings = buildings[["id", "height", "num_floors", "class", "geometry"]].reset_index(drop=True)
# Mark the frame as buildings, so an Autark map extrudes each footprint to its height.
buildings.metadata = {"layerType": "buildings"}
return buildings
'''

PARKS = f'''# OpenStreetMap's parks, playgrounds and green spaces of Lower Manhattan, the
# Financial District to City Hall, as the Discovery Catalog's OpenStreetMap
# source downloads its Parks layer.
return curio_load_data("{DATASET_ID}", part="parks.geojson")
'''

OPEN_AIR_PARKS = '''# The named parks large enough to measure, in the open: a "park" mostly under
# building footprints, such as a public atrium, is left out. Areas in metres,
# in the UTM zone of the parks, so this works for any city.
utm = input_0.estimate_utm_crs()
parks = input_0[input_0["name"].notna() & input_0.geometry.type.isin(["Polygon", "MultiPolygon"])]
parks = parks.to_crs(utm)
area = parks.area
roofed = parks.intersection(input_1.to_crs(utm).union_all()).area / area
parks = parks[(area >= float([!! min_area !!])) & (roofed < 0.5)].assign(area_m2=area)
# One park mapped twice (two outlines that almost coincide, under two names)
# counts once: the larger outline is kept.
kept = []
for i in parks.sort_values("area_m2", ascending=False).index:
    if not any(parks.geometry[i].intersection(parks.geometry[k]).area >= 0.8 * parks.area_m2[i]
               and parks.area_m2[k] <= 1.25 * parks.area_m2[i] for k in kept):
        kept.append(i)
parks = parks.loc[sorted(kept)]
parks = parks.rename(columns={"name": "park"})[["park", "osm_id", "area_m2", "geometry"]]
# A park's name is its key in the charts: two parks with one name keep their OSM id.
twice = parks["park"].duplicated(keep=False)
parks.loc[twice, "park"] = parks["park"] + " (" + parks["osm_id"].astype(str) + ")"
return parks.to_crs(4326).sort_values("park").reset_index(drop=True)
'''

AROUND_PARKS = '''import pandas as pd

# The buildings the what-ifs change, by one rule for every park, so the parks
# compare fairly: at least the Tall building height tall, and within the
# Distance from a park of any park. input_0 is the buildings, input_1 the parks.
# Distances in metres, in the parks' UTM zone.
buildings, parks = input_0, input_1
utm = parks.estimate_utm_crs()
footprints = buildings.to_crs(utm).geometry
distance = pd.DataFrame({park: footprints.distance(outline)
                         for park, outline in zip(parks["park"], parks.to_crs(utm).geometry)})
marked = buildings.assign(nearest_park=distance.idxmin(axis=1), park_distance_m=distance.min(axis=1))
marked["around_park"] = ((marked["height"] >= float([!! @tall_height !!]))
                         & (marked["park_distance_m"] <= float([!! @park_distance !!])))
# assign drops the frame's metadata: mark it as buildings again.
marked.metadata = {"layerType": "buildings"}
return marked
'''

TOWERS_REMOVED = '''# Towers removed: the buildings Buildings around parks marks are taken out.
remaining = input_0[~input_0["around_park"]].reset_index(drop=True)
# SCOUT's rasterizer looks rows up by position, hence reset_index; filtering
# drops the frame's metadata, so mark it as buildings again.
remaining.metadata = {"layerType": "buildings"}
return remaining
'''

HEIGHT_CAP = '''# Height cap: the buildings Buildings around parks marks are cut down to the
# Tall building height; every other building keeps its height.
cap = float([!! @tall_height !!])
capped = input_0.assign(height=input_0["height"].where(~input_0["around_park"], cap))
capped.metadata = {"layerType": "buildings"}
return capped
'''

SHADE_PER_PARK = '''import numpy as np
import pandas as pd
from rasterio.features import geometry_mask

# input_0: the accumulated shadow in minutes, a raster; input_1: the parks.
shadow, parks = input_0, input_1
# The minutes of daylight Deep Umbra's season stands for, SCOUT's factor.
daylight = {"winter": 360, "spring": 540}.get([!! @season !!], 720)
minutes = shadow.read(1, masked=True).filled(np.nan).astype("float64")
rows = []
for park in parks.to_crs(shadow.crs).itertuples():
    inside = geometry_mask([park.geometry], out_shape=minutes.shape, transform=shadow.transform, invert=True)
    values = minutes[inside]
    values = values[~np.isnan(values)]
    if values.size == 0:
        continue
    share = values / daylight
    rows.append({
        "park": park.park,
        "cells": int(values.size),
        "mean_min": float(values.mean()),
        "median_min": float(np.median(values)),
        "p90_min": float(np.percentile(values, 90)),
        "pct_daylight": float(values.mean() / daylight),
        # Shares of the park's cells: in sun (shaded under a quarter of the
        # daylight), in partial shade, and in deep shade (over three quarters).
        "share_sun": float((share < 0.25).mean()),
        "share_partial": float(((share >= 0.25) & (share < 0.75)).mean()),
        "share_deep": float((share >= 0.75).mean()),
    })
return parks.merge(pd.DataFrame(rows), on="park")
'''

SUN_GAINED = '''# The minutes of shadow each park loses from Existing (input_0) to Towers
# removed (input_1) and to Height cap (input_2): the sun it gains under each,
# on its outline for the maps.
existing = input_0.set_index("park")["mean_min"]
gained = input_0[["park", "area_m2", "geometry"]].copy()
for column, what_if in (("gain_removed_min", input_1), ("gain_capped_min", input_2)):
    gained[column] = (existing - what_if.set_index("park")["mean_min"]).reindex(gained["park"]).values
return gained
'''


def change_code(what_if: str) -> str:
    return (f"# The size of the change from Existing (input_0) to {what_if} (input_1),\n"
            "# cell by cell: 0 where they agree.\n"
            'return curio_raster_calculate("subtract", [input_1, input_0], absolute=True)\n')


#: The colour ranges the maps compared side by side share, so the same value
#: is the same colour in every scenario: Lower Manhattan's tallest building is
#: 417 m, a park gains at most 434 minutes of sun, and a summer's shadow, or
#: its change, is at most its 720 minutes of daylight.
HEIGHT_RANGE = [0, 420]
SUN_GAINED_RANGE = [0, 440]
SHADOW_RANGE = [0, 720]


def autk_map(get_fnv: str, interpolator: str, legend: str, quantitative: bool = False,
             color_range: list | None = None) -> str:
    layer = {"dataRef": "[!! input_0 !!]", "getFnv": get_fnv}
    if quantitative:
        layer["getFnvType"] = "quantitative"
    layer.update({"colorMapInterpolator": interpolator, "legendTitle": legend})
    if color_range:
        layer["colorMapRange"] = color_range
    return json.dumps({"map": {"layerRefs": [layer]}}, indent=2)


# ----------------------------------------------------------------------------
# The comparison charts
# ----------------------------------------------------------------------------

#: Each park's mean minutes in every scenario, on every row of it, and the sun
#: each what-if gains it: the minutes of shadow it takes away from Existing.
PER_PARK = [
    SCENARIO_NAME,
    *({"calculate": f"datum.__input__ === {i} ? datum.mean_min : null", "as": f"{key}_rows"}
      for i, key in enumerate(("existing", "removed", "capped"))),
    {"joinaggregate": [{"op": "max", "field": f"{key}_rows", "as": key} for key in ("existing", "removed", "capped")],
     "groupby": ["park"]},
    {"filter": "isValid(datum.existing) && isValid(datum.removed) && isValid(datum.capped)"},
    {"calculate": "datum.existing - datum.removed", "as": "gain_removed"},
    {"calculate": "datum.existing - datum.capped", "as": "gain_capped"},
    {"calculate": "min(datum.existing, datum.removed, datum.capped)", "as": "lowest"},
    {"calculate": "max(datum.existing, datum.removed, datum.capped)", "as": "highest"},
]
#: The parks, the one Towers removed gives the most sun first.
PARK_ORDER = {"field": "gain_removed", "op": "max", "order": "descending"}


def scenario_points(x: dict) -> list[dict]:
    """A dot per row in its scenario's colour, the same dot for every scenario."""
    color = {"field": "scenario_name", "type": "nominal", "scale": SCENARIO_COLOR, "legend": SCENARIO_LEGEND}
    return [{
        "mark": {"type": "point", "filled": True, "size": 60, "opacity": 1, "tooltip": True},
        "encoding": {"x": x, "color": color},
    }]


PARK_SHADE = spec({
    "title": {"text": "Minutes of shadow per park", "subtitle": "Click a bar to pick a park"},
    "transform": PER_PARK,
    "hconcat": [
        {
            "width": 300,
            "height": {"step": 13},
            "encoding": {
                "y": {"field": "park", "type": "nominal", "sort": PARK_ORDER, "title": None},
                "opacity": {"condition": {"param": "pick", "empty": True, "value": 1}, "value": 0.25},
            },
            "layer": [
                {
                    "transform": [{"filter": "datum.__input__ === 0"}],
                    "mark": {"type": "rule", "color": "#9ca3af", "strokeWidth": 2},
                    "encoding": {
                        "x": {"field": "lowest", "type": "quantitative", "title": "Mean shadow (minutes)"},
                        "x2": {"field": "highest"},
                    },
                },
                *scenario_points({"field": "mean_min", "type": "quantitative"}),
            ],
        },
        {
            "width": 220,
            # A park's row, as on the left: with yOffset the step would otherwise be a bar's.
            "height": {"step": 13, "for": "position"},
            "transform": [
                {"filter": "datum.__input__ === 0"},
                {"fold": ["gain_removed", "gain_capped"], "as": ["gain_key", "gain"]},
                {"calculate": f"datum.gain_key === 'gain_removed' ? '{REMOVED}' : '{CAPPED}'", "as": "what_if"},
            ],
            "params": [{"name": "pick", "select": {"type": "point", "fields": ["park"]}}],
            "mark": {"type": "bar", "tooltip": True, "cursor": "pointer"},
            "encoding": {
                "y": {"field": "park", "type": "nominal", "sort": PARK_ORDER, "axis": None},
                "yOffset": {"field": "what_if", "sort": WHAT_IFS},
                "x": {"field": "gain", "type": "quantitative", "title": "Sun gained (minutes)"},
                # The scenarios' scale, which the two views share: the dots' legend names the bars too.
                "color": {"field": "what_if", "type": "nominal", "scale": SCENARIO_COLOR, "legend": SCENARIO_LEGEND},
                "opacity": {"condition": {"param": "pick", "empty": True, "value": 1}, "value": 0.25},
            },
        },
    ],
})

# ----------------------------------------------------------------------------
# The dataflow
# ----------------------------------------------------------------------------

def scenario_nodes(src: dict[str, dict], key: str, name: str) -> list[dict]:
    """One scenario's SCOUT chain, maps and shade per park, WhatIfShadows' own
    nodes with new ids, saving its tiles and shadows under its own names."""
    suffix = f" - {name}"
    saved = "" if key == "existing" else f"-{key}"

    def scout(title: str, goal: str, widget_values: dict) -> dict:
        n = copy.deepcopy(src[f"{title} - {EXISTING}"])
        widgets = copy.deepcopy(n["metadata"].get("widgets") or [])
        for w in widgets:
            w.pop("value", None)
            if w["name"] in widget_values and widget_values[w["name"]] != w["default"]:
                w["value"] = widget_values[w["name"]]
        return node(f"{key}/{title}", n["type"], f"{title}{suffix}", 0, 0, n["content"], goal,
                    widgets=widgets or None)

    tiles, shadows = f"tiles{saved}", f"shadows{saved}"
    return [
        scout("Rasterize Buildings", f"Rasterize the {name.lower()} buildings into zoom-16 height tiles.",
              {"tiles": tiles}),
        scout("Accumulated Shadow", f"Predict the {name.lower()} buildings' accumulated shadow with Deep Umbra.",
              {"tiles": tiles, "shadows": shadows}),
        node(f"{key}/Shadow raster", "curio.builtin/computation-analysis", f"Shadow raster{suffix}", 0, 0,
             "# Accumulated Shadow returns (shadow, metrics): this is the shadow in minutes, a raster.\n"
             "return input_0[0]\n",
             "Take the accumulated shadow raster from Accumulated Shadow."),
        node(f"{key}/Shade per park", "curio.builtin/computation-analysis", f"Shade per park{suffix}", 0, 0,
             SHADE_PER_PARK,
             "For each park (input_1), the accumulated shadow raster's cells inside it (input_0, minutes, "
             "EPSG:3395): mean, median and 90th percentile minutes, the mean as a share of the season's daylight of "
             "the Season parameter (SCOUT's 720 minutes in summer, 540 in spring, 360 in winter), and the shares of "
             "its cells in sun (under 25% of daylight), partial shade and deep shade (over 75%). One row per park, "
             "with its outline and area."),
        node(f"{key}/Buildings in 3D", "curio.builtin/autk-grammar", f"Buildings in 3D{suffix}", 0, 0,
             autk_map("height", "interpolateViridis", "Building height (m)", quantitative=True,
                      color_range=HEIGHT_RANGE),
             f"Draw the {name.lower()} buildings in 3D, coloured by height."),
        node(f"{key}/Shadow map", "curio.builtin/autk-grammar", f"Shadow map{suffix}", 0, 0,
             autk_map("band_1", "interpolateReds", "Accumulated shadow (minutes)", color_range=SHADOW_RANGE),
             f"Draw the {name.lower()} buildings' accumulated shadow on a map.", width=500, height=536),
    ]


#: The node keys of a scenario's own nodes, its scenario membership.
#: The shadow maps stand outside their scenarios, beside the comparison maps.
SCENARIO_MEMBERS = ("Transformation", "Rasterize Buildings", "Accumulated Shadow", "Shadow raster",
                    "Shade per park", "Buildings in 3D")


def build() -> Path:
    src = source_nodes()
    season = copy.deepcopy(src["Season"])
    season.update(id=node_id("Season"), goal="The season all three scenarios' shadow runs in.")
    for k in ("dashboardPinned", "dashboardX", "dashboardY", "dashboardWidth", "dashboardHeight",
              "dashboardControlsOnly"):
        season.pop(k, None)

    shared = [
        node("Buildings", "curio.builtin/data-loading", "Buildings", 0, 0, BUILDINGS,
             "Load Overture Maps' buildings of Lower Manhattan, downloaded from the Discovery Catalog."),
        season,
        parameter("Distance from a park", "Distance from a park",
                  "How close to a park a tall building must be for the what-ifs to change it.",
                  number("park_distance", "Distance from a park", PARK_DISTANCE_M, units="m", step=5)),
        parameter("Tall building height", "Tall building height",
                  "The height from which the what-ifs change a building near a park, and Height cap's cap.",
                  number("tall_height", "Building height cap", TALL_HEIGHT_M, units="m", step=5)),
        node("Building heights", "curio.builtin/computation-analysis", "Building heights", 0, 0, HEIGHTS,
             "Give every building a height in metres for Rasterize Buildings: Overture's height, else its number "
             "of floors times the floor height, else the default height; leave out underground buildings and "
             "keep id, height, num_floors, class and the footprint.",
             widgets=[number("floor_height", "Floor height", 3.5, units="m", step=0.1),
                      number("default_height", "Default height", 10, units="m")]),
        node("Parks", "curio.builtin/data-loading", "Parks", 0, 0, PARKS,
             "Load OpenStreetMap's parks of Lower Manhattan, downloaded from the Discovery Catalog."),
        node("Open-air parks", "curio.builtin/computation-analysis", "Open-air parks", 0, 0, OPEN_AIR_PARKS,
             "Keep the named parks (input_0) of at least the minimum area that are not mostly under the building "
             "footprints (input_1), a park mapped twice once; one row per park with its name as park, osm_id, "
             "area_m2 and outline, in EPSG:4326.",
             widgets=[number("min_area", "Minimum area", 500, units="m²", step=50)]),
        node("Buildings around parks", "curio.builtin/computation-analysis", "Buildings around parks", 0, 0,
             AROUND_PARKS,
             "Mark the buildings (input_0) the what-ifs change, by one rule for every park (input_1): around_park "
             "when at least the Tall building height tall and within the Distance from a park of any park, in "
             "metres in the parks' UTM zone; with each building's nearest_park and park_distance_m."),
        node("towers-removed/Transformation", "curio.builtin/data-transformation",
             f"Data Transformation - {REMOVED}", 0, 0, TOWERS_REMOVED,
             "Take out the buildings Buildings around parks marks."),
        node("height-cap/Transformation", "curio.builtin/data-transformation",
             f"Data Transformation - {CAPPED}", 0, 0, HEIGHT_CAP,
             "Cut the buildings Buildings around parks marks down to the Tall building height."),
    ]
    scenario_chains = [n for key, name, _color in SCENARIOS for n in scenario_nodes(src, key, name)]
    comparison = []
    for key, name, _color in SCENARIOS[1:]:
        comparison += [
            node(f"change/{key}", "curio.builtin/computation-analysis", f"Shadow change - {name}", 0, 0,
                 change_code(name),
                 f"Take the size of the change in the accumulated shadow from Existing to {name}, cell by cell."),
            node(f"change map/{key}", "curio.builtin/autk-grammar", f"Shadow change map - {name}", 0, 0,
                 autk_map("band_1", "interpolateReds", f"Shadow change, {name} (minutes)",
                          color_range=SHADOW_RANGE),
                 f"Map where the accumulated shadow changes under {name}.", width=495, height=537),
        ]
    comparison += [
        node("Sun gained per park", "curio.builtin/computation-analysis", "Sun gained per park", 0, 0, SUN_GAINED,
             "For each park, the minutes of shadow it loses from Existing to Towers removed and to Height cap, "
             "with its outline."),
        node("sun map/removed", "curio.builtin/autk-grammar", f"Sun gained per park map - {REMOVED}", 0, 0,
             autk_map("gain_removed_min", "interpolateReds", "Sun gained, Towers removed (minutes)", quantitative=True,
                      color_range=SUN_GAINED_RANGE),
             "Map the parks, coloured by the minutes of sun each gains when the towers are removed.",
             width=495, height=537),
        node("sun map/capped", "curio.builtin/autk-grammar", f"Sun gained per park map - {CAPPED}", 0, 0,
             autk_map("gain_capped_min", "interpolateReds", "Sun gained, Height cap (minutes)", quantitative=True,
                      color_range=SUN_GAINED_RANGE),
             "Map the parks, coloured by the minutes of sun each gains under the height cap.",
             width=495, height=537),
        node("Minutes of shadow per park", "curio.builtin/vis-vega", "Minutes of shadow per park", 0, 0, PARK_SHADE,
             "Compare each park's mean minutes of shadow in the three scenarios, a range per park, beside the "
             "sun each what-if gains it, linked by a park picked on the bars.", width=820, height=760),
    ]
    nodes = shared + scenario_chains + comparison

    edges = [
        edge("Buildings", "Building heights"),
        edge("Parks", "Open-air parks"),
        edge("Building heights", "Open-air parks", 1),
        edge("Building heights", "Buildings around parks"),
        edge("Open-air parks", "Buildings around parks", 1),
        edge("Buildings around parks", "towers-removed/Transformation"),
        edge("Buildings around parks", "height-cap/Transformation"),
    ]
    for key, _name, _color in SCENARIOS:
        upstream = "Building heights" if key == "existing" else f"{key}/Transformation"
        edges += [
            edge(upstream, f"{key}/Rasterize Buildings"),
            edge(upstream, f"{key}/Buildings in 3D"),
            edge(f"{key}/Rasterize Buildings", f"{key}/Accumulated Shadow"),
            edge(f"{key}/Accumulated Shadow", f"{key}/Shadow raster"),
            edge(f"{key}/Shadow raster", f"{key}/Shadow map"),
            edge(f"{key}/Shadow raster", f"{key}/Shade per park"),
            edge("Open-air parks", f"{key}/Shade per park", 1),
        ]
    for key, _name, _color in SCENARIOS[1:]:
        edges += [
            edge("existing/Shadow raster", f"change/{key}"),
            edge(f"{key}/Shadow raster", f"change/{key}", 1),
            edge(f"change/{key}", f"change map/{key}"),
        ]
    for target in ("Sun gained per park", "Minutes of shadow per park"):
        edges += [edge(f"{key}/Shade per park", target, slot) for slot, (key, _n, _c) in enumerate(SCENARIOS)]
    edges += [edge("Sun gained per park", "sun map/removed"), edge("Sun gained per park", "sun map/capped")]

    ids = {n["id"] for n in nodes}
    flow = {
        "dataflow": {
            "categories": {"complexity": ["Beginner"], "city": ["New York"]},
            "nodes": nodes,
            "edges": edges,
            "scenarios": [
                {"id": key, "name": name, "color": color,
                 "nodes": [node_id(f"{key}/{t}") for t in SCENARIO_MEMBERS if node_id(f"{key}/{t}") in ids]}
                for key, name, color in SCENARIOS
            ],
            "packages": ["scout.raster-conversion@1", "scout.shadow@1"],
            "datasets": [{
                "datasetId": DATASET_ID,
                "dirName": f"{DATASET_ID}@1",
                "origin": "imported",
                "producerNodeId": None,
                "consumerNodeIds": [],
                "installedAt": "2026-10-14T00:00:00Z",
            }],
            "name": NAME,
            "task": "",
            "timestamp": 1791936000000,
            "provenance_id": NAME,
        }
    }
    out = DATAFLOWS / f"{NAME}.json"
    if out.exists():
        keep_canvas(flow["dataflow"], json.loads(out.read_text(encoding="utf-8"))["dataflow"])
    else:
        lay_out(flow["dataflow"])
    out.write_text(json.dumps(flow, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return out


def script(name: str):
    """One of this folder's scripts, as a module."""
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


#: What the canvas sets on a node and a save writes: where it stands, its
#: size, whether it is collapsed, and whether a Parameter shows its control alone.
CANVAS_KEYS = ("x", "y", "width", "height", "minimized", "controlsOnly", "saveOutputDataset")


def keep_canvas(dataflow: dict, shipped: dict) -> None:
    """Keep the layout arranged on the canvas and saved into the shipped file:
    each node's canvas keys, and each scenario's upstream and downstream (a
    save stores them). A node the shipped file does not have yet is laid out
    by ``lay_out``, as a new dataflow is."""
    old = {n["id"]: n for n in shipped.get("nodes") or []}
    if any(n["id"] not in old for n in dataflow["nodes"]):
        lay_out(dataflow)
    for n in dataflow["nodes"]:
        for key in CANVAS_KEYS:
            if key in old.get(n["id"], {}):
                n[key] = old[n["id"]][key]
    old_scenarios = {s["id"]: s for s in shipped.get("scenarios") or []}
    for scenario in dataflow["scenarios"]:
        for key in ("upstream", "downstream"):
            if key in old_scenarios.get(scenario["id"], {}):
                scenario[key] = old_scenarios[scenario["id"]][key]


def lay_out(dataflow: dict) -> None:
    """Place the nodes as ``tidy_example_layout.py --write`` would."""
    tidy = script("tidy_example_layout")
    layout, report = tidy.tidy_layout(dataflow, tidy._template_index())
    if report["overlaps"]:
        raise SystemExit(f"{NAME}: the layout has {report['overlaps']} overlaps")
    for n in dataflow["nodes"]:
        n["x"], n["y"] = layout[n["id"]]


PROMPT = (
    "Run SCOUT's shadow study on Lower Manhattan and compare the shadow in its parks across three scenarios. Load "
    "Overture Maps' buildings and OpenStreetMap's parks of Lower Manhattan from the Data Catalog, one bundle, as the "
    "Discovery Catalog downloaded them. Give every building a height in metres, from Overture's height, else its "
    "number of floors times a floor height, else a default height, both set on the node, without underground "
    "buildings and Overture's nested columns. Keep the named parks of at least a minimum area, set on the node, "
    "that are not mostly under building footprints, a park mapped twice once. Mark the buildings the what-ifs "
    "change by one rule for every park: at least a tall building height, 60 metres, and within a distance of any "
    "park, 75 metres, both shared settings. The scenarios: the buildings as they are; the marked buildings taken "
    "out; and the marked buildings cut down to the tall building height. In each, turn the buildings' heights into "
    "a zoom 16 height raster with SCOUT's building rasterizer, run SCOUT's Deep Umbra shadow model on it, with one "
    "season setting all three share, set to summer, take the accumulated shadow raster from what it returns, and "
    "measure each park's minutes of shadow: the mean, median and 90th percentile, the mean as a share of the "
    "season's daylight, and the shares of the park in sun, partial shade and deep shade. Draw each scenario's "
    "buildings in 3D coloured by height and its shadow raster on Autark maps. Then map the absolute change in "
    "shadow from the buildings as they are to each what-if, cell by cell, with a raster calculator, and the "
    "minutes of sun each park gains under each what-if, and compare the parks in a Vega-Lite chart: each "
    "park's mean shadow in the three scenarios beside the sun each what-if gains it, linked by a park picked "
    "on the bars. The rasterizer and the shadow model are not part of the standard node set, so whatever provides them "
    "needs installing first."
)

#: (node title, words the content must mention, the output it must give).
INTENTS = [
    ("Buildings", ["building"], "geodataframe"),
    ("Building heights", ["height"], "geodataframe"),
    ("Parks", ["park"], "geodataframe"),
    ("Open-air parks", ["park"], "geodataframe"),
    ("Buildings around parks", ["park", "height"], "geodataframe"),
    (f"Data Transformation - {REMOVED}", ["around_park"], "geodataframe"),
    (f"Data Transformation - {CAPPED}", ["around_park", "height"], "geodataframe"),
    *((f"Rasterize Buildings - {n}", ["height", "tile"], "dataframe") for n in NAMES),
    *((f"Accumulated Shadow - {n}", ["shadow"], None) for n in NAMES),
    *((f"Shadow raster - {n}", ["shadow"], "raster") for n in NAMES),
    *((f"Shade per park - {n}", ["park", "daylight"], "geodataframe") for n in NAMES),
    *((f"Shadow change - {n}", ["change"], "raster") for n in WHAT_IFS),
    ("Sun gained per park", ["park"], "geodataframe"),
]


def write_fixture(target: Path) -> None:
    from utk_curio.backend.app.agents.evaluation.canonical import canonical_graph_from_spec
    from utk_curio.backend.app.agents.evaluation.dependencies import referenced_sources

    skeleton = script("example_fixture_skeleton")
    templates = skeleton.template_index()
    drafted = skeleton.skeleton(target, templates)
    example = json.loads(target.read_text(encoding="utf-8"))
    graph = canonical_graph_from_spec(example, templates=templates,
                                      sources=referenced_sources(example, templates=templates))
    refs = [n["ref"] for n in drafted["expected"]["nodes"]]
    ref_of = {example["dataflow"]["nodes"][origin]["title"]: ref for ref, origin in zip(refs, graph.origins)}
    fixture = {
        "$schema": "https://curio.dev/schemas/example-prompt-fixture.v1.json",
        "fixtureId": NAME,
        "version": 1,
        "source": drafted["source"],
        "prompt": PROMPT,
        "context": None,
        "required": drafted["required"],
        "expected": drafted["expected"],
        "intents": [{"ref": ref_of[title], "mustMention": words, **({"outputKind": kind} if kind else {})}
                    for title, words, kind in INTENTS],
        "execution": {"mode": "sandbox", "browserOnlyKinds": [], "notes": None},
        "capability": {"tier": "T1", "needs": ["package-enlist:templates"], "skip": []},
        "thresholds": {"pass": 0.9, "templates": 1.0, "topology": 0.9, "dependencies": 1.0},
        "split": "train",
        "review": {"status": "pending-owner-review", "draftedBy": "claude-opus-5-5 from the example JSON, 2026-10-14",
                   "reviewedBy": None, "reviewedAt": None},
        "consent": {
            "dataContent": "identifiers-only",
            "licence": "MIT (this repository)",
            "sourceLicences": [{"datasetId": DATASET_ID, "licence": "ODbL-1.0"}],
            "notes": "The prompt, the expected graph and the plan target are authored in this repository; the export "
                     "carries the dataset's identifier only. The buildings are Overture Maps' and the parks "
                     "OpenStreetMap's, both ODbL 1.0; the Deep Umbra model the shadow nodes name is SCOUT's "
                     "(urban-toolkit/scout), used with the permission of its authors.",
        },
        "notes": "A shared context (the bundle's two loaders, Building heights, Open-air parks, Buildings around "
                 "parks and three Parameter nodes) feeds three scenarios. Each runs SCOUT's rasterizer and Deep "
                 "Umbra, takes the shadow raster apart, measures the shade in each park (rasterio's "
                 "geometry_mask) and draws its buildings and shadow on Autark maps; Towers removed and Height cap "
                 "first change the buildings Buildings around parks marks, in a Data Transformation each. Python "
                 "nodes take each what-if's absolute change in shadow (curio_raster_calculate) and the sun each park "
                 "gains, on Autark maps; a Vega-Lite chart reads its three inputs stacked (the dataset "
                 "inputs) and names each circle's scenario from __input__.",
    }
    FIXTURE.write_text(json.dumps(fixture, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    target = build()
    write_fixture(target)
    print(f"wrote {target.relative_to(REPO)} and {FIXTURE.relative_to(REPO)}")
