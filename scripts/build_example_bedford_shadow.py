#!/usr/bin/env python3
"""Write the crown-heights-1550-bedford-shadow example: the shadow the 18-story
building that ZAP project 2026K0123 proposes at 1550 Bedford Avenue, Crown
Heights, would cast, accumulated over a date, a month or the whole year, on
the ground around it and on Block 1259 across Eastern Parkway (Franklin
Avenue to Bedford Avenue).

The buildings, the block, the streets and the site come from the bundle
``data.nyc.crown-heights-1550-bedford`` (``scripts/build_bedford_shadow_dataset.py``).
A Map Edits node adds the proposed building to the buildings in two parts
drawn from the site's lot as the project's description gives its envelope:

- a base up to 135 ft (the maximum base height) on the lot, set back 30 ft
  from the street line of Eastern Parkway at the ground floor;
- the floors above it, up to 185 ft, set back from the base's street walls
  (10 ft on the wide streets, Eastern Parkway and Bedford Avenue, 15 ft on
  Union Street, as R9A's setbacks above the base go).

The filings give no floor plates, so this is the envelope, not the design.

Three Parameter nodes make the selection: Period (Date, Month or Year), Date
and Month; the one Period names is used. A Python node covers the area with
small ground cells and gives them the selection's days; another hands the
proposed building's parts to an Autark compute step, a WebGPU shader that
casts sun rays from every cell every few minutes of every selected day and
accumulates the minutes the building blocks the sun. Only the proposed
building casts shadow: this is its own shadow, not the shade it adds over
what the other buildings already cast. An Autark map draws the accumulated
shadow with Block 1259, the proposed building and the other buildings, and a
table gives the shade it adds on Block 1259, on average per spot.

    python scripts/build_example_bedford_shadow.py

AUTHORING-ONLY tooling. The output is deterministic, so a rerun rewrites the
same file.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "docs" / "examples" / "dataflows" / "crown-heights-1550-bedford-shadow.json"
NAME = "Crown Heights shade from 1550 Bedford Avenue"
NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, f"https://curio.dev/examples/{NAME}")
DATA = "data.nyc.crown-heights-1550-bedford"
STAMP = "2026-10-22T00:00:00Z"
TIMESTAMP = 1792627200000
FEET = 0.3048
#: The envelope: the base and the top's heights, the base's setback from
#: Eastern Parkway at grade, and the top's setbacks above the base.
BASE_FT, TOP_FT, GRADE_SETBACK_FT = 135, 185, 30
TOP_SETBACK_FT = {"eastern_parkway": 10, "bedford": 10, "union": 15}
PROPOSED = "Proposed: 1550 Bedford Ave"
EXISTING_COLOR, PROPOSED_COLOR = "#2a9d8f", "#e76f51"
COLUMN = 645
ROW = 450


def nid(key: str) -> str:
    return str(uuid.uuid5(NAMESPACE, key))


# -- The proposed building ----------------------------------------------------

def massing() -> list[dict]:
    """The two parts the Map Edits node adds, as GeoJSON in EPSG:4326, from
    the site's lot: its edges told apart by where they lie, in New York's
    state plane (feet), Eastern Parkway's to the north, Bedford Avenue's to the
    east and Union Street's to the south."""
    import geopandas as gpd
    from shapely.geometry import LineString, mapping

    lot = gpd.read_file(REPO / "datasets" / f"{DATA}@1" / "data" / "site.geojson").to_crs(2263).geometry.iloc[0]
    ring = list(lot.exterior.coords)[:-1]
    edges = [(ring[i], ring[(i + 1) % len(ring)]) for i in range(len(ring))]
    middle = lambda edge: ((edge[0][0] + edge[1][0]) / 2, (edge[0][1] + edge[1][1]) / 2)
    street = {
        "eastern_parkway": max(edges, key=lambda e: middle(e)[1]),
        "bedford": max(edges, key=lambda e: middle(e)[0]),
        "union": min(edges, key=lambda e: middle(e)[1]),
    }
    def strip(edge, feet):
        """The band *feet* deep along *edge*, run on past the lot's corners,
        which are not square, so it cuts the lot's whole street side."""
        (x0, y0), (x1, y1) = edge
        dx, dy = x1 - x0, y1 - y0
        reach = 200 / (dx * dx + dy * dy) ** 0.5
        return LineString([(x0 - dx * reach, y0 - dy * reach), (x1 + dx * reach, y1 + dy * reach)]).buffer(
            feet, cap_style="flat")

    base = lot.difference(strip(street["eastern_parkway"], GRADE_SETBACK_FT))
    top = base
    for name, feet in TOP_SETBACK_FT.items():
        top = top.difference(strip(street[name], feet + (GRADE_SETBACK_FT if name == "eastern_parkway" else 0)))
    parts = gpd.GeoSeries([base.difference(top), top], crs=2263).to_crs(4326)

    def rounded(geometry):
        shape = mapping(geometry)
        return {"type": shape["type"], "coordinates": json.loads(json.dumps(shape["coordinates"]),
                parse_float=lambda v: round(float(v), 7))}

    return [
        {"op": "add", "id": 900000001, "geometry": rounded(parts.iloc[0]), "crs": "EPSG:4326",
         "values": {"height": round(BASE_FT * FEET, 1), "status": PROPOSED},
         "label": f"Base to {BASE_FT} ft, {GRADE_SETBACK_FT} ft back from Eastern Parkway"},
        {"op": "add", "id": 900000002, "geometry": rounded(parts.iloc[1]), "crs": "EPSG:4326",
         "values": {"height": round(TOP_FT * FEET, 1), "status": PROPOSED},
         "label": f"Upper floors to {TOP_FT} ft, set back above the base"},
    ]


def py(value) -> str:
    """*value* as the Python literal Map Edits writes (``pyLiteral.ts``)."""
    return json.dumps(value, ensure_ascii=False).replace("true", "True").replace("false", "False").replace("null", "None")


def edit_code(edits: list[dict]) -> str:
    lines = [
        "# Map Edits writes this code from its edit list: each edit, in the",
        "# order it was made, on the features whose key is one of its ids. It is",
        "# written again when the list changes.",
        "return curio_edit_features(input_0, [",
    ]
    for edit in edits:
        lines.append("    {" + ", ".join(f"{json.dumps(k)}: {py(v)}" for k, v in edit.items()) + "},")
    lines += ['], key="building_id")', ""]
    return "\n".join(lines)


# -- Node code ------------------------------------------------------------------

BUILDINGS = f'''# NYC's building footprints about 600 by 550 m around 1550 Bedford Avenue,
# each with its roof height in metres (height) and DoITT's id (building_id).
# The site is vacant, so no building stands on it.
buildings = curio_load_data("{DATA}", part="buildings.parquet")
# What the shadow map colors the buildings by: every building here stands today.
buildings["status"] = "Existing"
# Mark the frame as buildings, so an Autark map extrudes each footprint to its height.
buildings.metadata = {{"layerType": "buildings"}}
return buildings
'''

BLOCK = f'''# Block 1259, across Eastern Parkway from the site, Franklin Avenue to
# Bedford Avenue: its lots, dissolved into one outline.
return curio_load_data("{DATA}", part="block-1259.geojson")
'''

STREETS = f'''# NYC's street centerlines around the site, each segment with its street's
# name (street) and its roadway's width, curb to curb, in feet (width_ft),
# drawn as wide as that: each centerline becomes a strip of its width, in
# metres in the streets' UTM zone. Square ends close the corners where
# segments meet. A segment with no width, such as a footbridge, gets 10 ft.
streets = curio_load_data("{DATA}", part="streets.geojson")
utm = streets.estimate_utm_crs()
half = streets["width_ft"].fillna(10) * 0.3048 / 2
streets = streets.set_geometry(streets.to_crs(utm).buffer(half, cap_style="square").to_crs(streets.crs))
# Tell the Autark map these are areas, so it fills them.
streets.metadata = {{"layerType": "polygons"}}
return streets
'''

def grammar(document: dict) -> str:
    return json.dumps(document, indent=2) + "\n"


def node(key, type_, x, y, content, goal, title=None, widgets=None, copied=None, size=None):
    metadata = {"keywords": []}
    if widgets:
        metadata["widgets"] = widgets
    if copied:
        metadata["copiedFrom"] = [nid(copied)]
    entry = {"id": nid(key), "type": type_, "x": x, "y": y, "content": content, "out": "DEFAULT",
             "in": "DEFAULT", "goal": goal, "metadata": metadata}
    if title:
        entry["title"] = title
        # What the node's header shows in place of its type's name (#412).
        metadata["packageTemplateLabel"] = title
    if size:
        entry["width"], entry["height"] = size
    return entry


#: How many data edges each node has taken so far: the next one goes on its
#: next input circle, so edges are written in their target's input order.
CIRCLES: dict[str, int] = {}


def edge(source, target, interaction=False):
    s, t = nid(source), nid(target)
    if interaction:
        return {"id": f"reactflow__edge-{s}in/out-{t}in/out", "source": s, "target": t,
                "sourceHandle": "in/out", "targetHandle": "in/out", "type": "Interaction"}
    circle = CIRCLES.get(target, 0)
    CIRCLES[target] = circle + 1
    handle = "in" if circle == 0 else f"in_{circle}"
    return {"id": f"reactflow__edge-{s}out-{t}{handle}", "source": s, "target": t, "sourceHandle": "out",
            "targetHandle": handle}


PERIOD = "Date"
DATE = "2027-12-21"
MONTH = "Dec"
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
#: The ground cells' side and the sun's step, which set how fine the shadow is.
CELL_M, STEP_MIN = 3, 10

GROUND = f'''import calendar
import datetime

import geopandas as gpd
import numpy as np
import shapely

# The ground the proposed building's shadow is accumulated on: square cells of
# CELL metres over the area around the buildings. For the GPU shader, each
# cell holds its centre in metres from the proposed building's centre (x east,
# y north) and the days of the year the selection covers (first_day,
# last_day). on_block says whether the cell lies on Block 1259, input_1;
# input_0 is the buildings with the proposed one added.
CELL = {CELL_M}
YEAR = 2027
buildings, block = input_0, input_1
period, date, month = [!! @period !!], [!! @date !!], [!! @month !!]

# The days the selection covers: one date, a month, or the whole year.
if period == "Date":
    day = datetime.date.fromisoformat(str(date)[:10]).replace(year=YEAR)
    first = last = day.timetuple().tm_yday
    label = day.strftime("%b %d")
elif period == "Month":
    number = list(calendar.month_abbr).index(month)
    first = datetime.date(YEAR, number, 1).timetuple().tm_yday
    last = first + calendar.monthrange(YEAR, number)[1] - 1
    label = calendar.month_name[number]
else:
    first, last, label = 1, 365, "The whole year"

# Metres, in the buildings' UTM zone, centred on the proposed building.
utm = buildings.estimate_utm_crs()
proposed = buildings[buildings["status"] != "Existing"].to_crs(utm)
origin = proposed.union_all().centroid
west, south, east, north = buildings.to_crs(utm).total_bounds
xs, ys = np.meshgrid(np.arange(west, east, CELL), np.arange(south, north, CELL))
xs, ys = xs.ravel(), ys.ravel()
cells = gpd.GeoDataFrame(
    {{"x": xs + CELL / 2 - origin.x, "y": ys + CELL / 2 - origin.y}},
    geometry=shapely.box(xs, ys, xs + CELL, ys + CELL), crs=utm,
)
centres = cells.geometry.centroid
cells["on_block"] = centres.within(block.to_crs(utm).union_all()).astype(int)
# Under the proposed building itself, where its shadow does not count.
cells["under_building"] = centres.within(proposed.union_all()).astype(int)
cells["first_day"], cells["last_day"], cells["selection"] = first, last, label
cells["cell_m2"] = CELL * CELL
cells = cells.to_crs(buildings.crs)
# Tell the Autark map these are areas, so it fills them.
cells.metadata = {{"layerType": "polygons"}}
return cells
'''

TOWER = '''import geopandas as gpd
import shapely
from shapely.geometry import box

# The proposed building as the GPU shader reads it, one feature for the
# whole building: corners, every part's outline in metres from the
# building's centre (x east, y north), counter-clockwise and not closed, one
# part after another; and parts, a row per part: its first corner, its
# number of corners and its height in metres. A part is drawn as its convex
# outline, which casts the shadow a U-shaped base does once the taller part
# inside it is there too. input_0 is the buildings with the proposed one.
buildings = input_0
utm = buildings.estimate_utm_crs()
proposed = buildings[buildings["status"] != "Existing"].to_crs(utm)
origin = proposed.union_all().centroid
corners, parts = [], []
for outline, height in zip(proposed.geometry, proposed["height"]):
    hull = shapely.geometry.polygon.orient(outline.convex_hull, sign=1.0)
    ring = [(x - origin.x, y - origin.y) for x, y in list(hull.exterior.coords)[:-1]]
    parts.append([len(corners), len(ring), float(height)])
    corners.extend([list(corner) for corner in ring])
tower = gpd.GeoDataFrame(
    {"corners": [corners], "parts": [parts], "height_m": [float(proposed["height"].max())]},
    geometry=[proposed.union_all()], crs=utm,
).to_crs(buildings.crs)
tower.metadata = {"layerType": "polygons"}
return tower
'''


def shadow_compute(latitude: float) -> str:
    """The Autark compute step: for every ground cell (input_0), the minutes
    the proposed building (input_1) shades it over the selected days."""
    shader = [
        "// Minutes the proposed building shades this cell over first_day..last_day:",
        f"// the sun every {STEP_MIN} minutes of solar time, the cell in shadow when the",
        "// ray from it toward the sun passes through a part below the part's height.",
        "let pi = 3.14159265;",
        "let lat = radians(latitude);",
        "var total: f32 = 0.0;",
        "for (var d = u32(first_day); d <= u32(last_day); d++) {",
        "    // The sun's declination (Cooper's formula).",
        "    let dec = radians(23.44) * sin(2.0 * pi * (284.0 + f32(d)) / 365.0);",
        f"    for (var k = 0u; k < {1440 // STEP_MIN}u; k++) {{",
        f"        let hour = radians((f32(k) * {STEP_MIN}.0 + {STEP_MIN / 2} - 720.0) / 4.0);",
        "        let up = sin(lat) * sin(dec) + cos(lat) * cos(dec) * cos(hour);",
        "        if (up <= 0.0) { continue; }",
        "        let toward_e = -cos(dec) * sin(hour);",
        "        let toward_n = cos(lat) * sin(dec) - sin(lat) * cos(dec) * cos(hour);",
        "        let level = sqrt(toward_e * toward_e + toward_n * toward_n);",
        "        let sx = toward_e / level;",
        "        let sy = toward_n / level;",
        "        var shaded = false;",
        "        for (var p = 0u; p < parts_rows; p++) {",
        "            let start = u32(parts[p * 3u]);",
        "            let count = u32(parts[p * 3u + 1u]);",
        "            // How far toward the sun the part can still block it.",
        "            let reach = parts[p * 3u + 2u] * level / up;",
        "            var lo: f32 = 0.0;",
        "            var hi: f32 = reach;",
        "            var crosses = true;",
        "            for (var i = 0u; i < count; i++) {",
        "                let a = start + i;",
        "                let b = start + (i + 1u) % count;",
        "                let ax = corners[a * 2u];",
        "                let ay = corners[a * 2u + 1u];",
        "                let nx = corners[b * 2u + 1u] - ay;",
        "                let ny = ax - corners[b * 2u];",
        "                let num = nx * (ax - x) + ny * (ay - y);",
        "                let den = nx * sx + ny * sy;",
        "                if (abs(den) < 1e-9) {",
        "                    if (num < 0.0) { crosses = false; break; }",
        "                } else if (den > 0.0) {",
        "                    hi = min(hi, num / den);",
        "                } else {",
        "                    lo = max(lo, num / den);",
        "                }",
        "            }",
        "            if (crosses && lo <= hi) { shaded = true; break; }",
        "        }",
        f"        if (shaded) {{ total += {STEP_MIN}.0; }}",
        "    }",
        "}",
        "return total;",
    ]
    return grammar({"compute": [{
        "dataRef": "[!! input_0 !!]",
        "attributes": {"x": "properties.x", "y": "properties.y",
                       "first_day": "properties.first_day", "last_day": "properties.last_day"},
        "uniforms": {"latitude": round(latitude, 4)},
        "uniformMatrices": {
            "corners": {"fromFeature": {"layer": "[!! input_1 !!]", "path": "properties.corners"}, "cols": 2},
            "parts": {"fromFeature": {"layer": "[!! input_1 !!]", "path": "properties.parts"}, "cols": 3},
        },
        "outputColumnName": "shadow_min",
        "wglsFunction": shader,
    }]})


SHADOW_CELLS = '''import pandas as pd

# The ground cells with the minutes the GPU step found the proposed building
# shades each over the selection (shadow_min) and the same in hours
# (shadow_h). The step hands on the cells, input_0's first layer, with its
# result under compute; the cells under the building are left out.
cells = [!! input_0:input_0 !!]
# The GPU step hands its layers on as GeoJSON, in longitude and latitude.
if cells.crs is None:
    cells = cells.set_crs(4326)
if "shadow_min" not in cells.columns:
    cells["shadow_min"] = [row.get("shadow_min") if isinstance(row, dict) else None for row in cells["compute"]]
cells = cells[cells["under_building"] == 0].copy()
cells["shadow_min"] = pd.to_numeric(cells["shadow_min"]).fillna(0.0)
cells["shadow_h"] = cells["shadow_min"] / 60
cells = cells[["x", "y", "on_block", "selection", "cell_m2", "shadow_min", "shadow_h", "geometry"]]
cells.metadata = {"layerType": "polygons"}
return cells
'''

SHADOW_SHOWN = '''import math

import geopandas as gpd
import pandas as pd
from shapely.geometry import box

# What the map colors: the cells the proposed building shades at all, by
# hours of shadow, the scale topped at the 90th percentile of them so the
# far reach of the shadow stays visible beside the cells next to the building,
# which it shades almost all day. input_0 is the shadow per cell, input_1 the
# buildings with the proposed one.
shaded = input_0[input_0["shadow_h"] > 0].copy()
if len(shaded):
    top = float(shaded["shadow_h"].quantile(0.9))
    shaded["shadow_shown"] = shaded["shadow_h"].clip(upper=top)
    # Autark's legend runs from the layer's lowest value to its highest, so
    # two small cells hidden under the proposed building hold the whole hours
    # below and above them: the legend reads from the floor to the ceiling.
    low, high = math.floor(shaded["shadow_shown"].min()), math.ceil(shaded["shadow_shown"].max())
    tower = input_1[input_1["status"] != "Existing"].to_crs(shaded.crs).union_all().centroid
    side = 1e-6
    anchors = gpd.GeoDataFrame(
        {"shadow_shown": [float(low), float(high)]},
        geometry=[box(tower.x - side, tower.y - side, tower.x, tower.y),
                  box(tower.x, tower.y, tower.x + side, tower.y + side)],
        crs=shaded.crs,
    )
    shaded = pd.concat([shaded, anchors], ignore_index=True)
shaded.metadata = {"layerType": "polygons"}
return shaded
'''

MAP_AREA = '''import geopandas as gpd
from shapely.geometry import box

# The area the map shows, one box around every building. The map loads it
# first and does not draw it: Autark clips every layer it loads after the
# first to the first one's outline, so with this box first every layer stays
# whole.
return gpd.GeoDataFrame({"area": ["map"]}, geometry=[box(*input_0.total_bounds)], crs=input_0.crs)
'''

SUMMARY = '''import pandas as pd

# The selection's answer: the proposed building's shade on a spot of Block
# 1259, on average over the whole block (a spot the shadow never reaches
# counts as 0). It is also the sunlight that spot loses.
cells = input_0
minutes = float(cells.loc[cells["on_block"] == 1, "shadow_min"].mean())
return pd.DataFrame([{
    "Selection": cells["selection"].iloc[0],
    "Shade added on Block 1259": f"{minutes:.0f} min" if minutes < 90 else f"{minutes / 60:,.1f} h",
}])
'''


def shadow_map() -> str:
    """The accumulated shadow over the ground, with the streets under it,
    Block 1259 over it and the buildings in 3D, the proposed one in its own
    color: input_0 is the map's area (loaded, not drawn), input_1 the shaded
    cells, input_2 the buildings Map Edits hands on, input_3 the block and
    input_4 the streets."""
    return grammar({"map": {"layerRefs": [
        {"dataRef": "[!! input_0 !!]", "isSkip": True},
        {"dataRef": "[!! input_4 !!]", "color": "#d5d9df", "stroke": False, "title": "Streets"},
        {"dataRef": "[!! input_2 !!]", "selectFields": ["building_id"],
         "getFnv": "status", "getFnvType": "categorical", "colorMapInterpolator": "schemeTableau10",
         "title": "Building"},
        # The last color-mapped layer, which Autark gives the map's only legend,
        # and the one pickable layer (Map Edits picks on the buildings itself
        # while editing).
        {"dataRef": "[!! input_1 !!]", "isPick": True, "getFnv": "shadow_shown", "getFnvType": "quantitative",
         "isColorMap": True, "colorMapInterpolator": "interpolateRdPu", "stroke": False, "opacity": 0.9,
         "title": "Accumulated shadow (hours)"},
        # Over the shadow, so the block stays visible; a fixed color, so it
        # takes no legend.
        {"dataRef": "[!! input_3 !!]", "color": "#ffd166", "stroke": "#e09f00", "opacity": 0.4,
         "title": "Block 1259"},
    ]}})


def parameter(key, x, y, widget, goal, title):
    return node(key, "curio.builtin/parameter", x, y, "", goal, title=title, widgets=[widget])


#: The layout saved in Curio (2026-10-23): where nodes were moved or resized on
#: the canvas, and the dashboard's pinned nodes with their places and sizes, by
#: node title.
LAYOUT = {
    "Cast sun rays on the GPU": {"x": 1957, "y": 167},
    "Keep shaded cells for the map": {"x": 3220, "y": 230},
    "Map extent (keeps layers whole)": {"x": 3215, "y": -181},
    "Add proposed tower (1550 Bedford Ave)": {"x": 620, "y": -109, "dashboardPinned": True, "dashboardX": 186, "dashboardY": 38, "dashboardWidth": 448, "dashboardHeight": 541},
    "Map: tower's accumulated shadow": {"x": 3862, "y": 12, "dashboardPinned": True, "dashboardX": 641, "dashboardY": 38, "dashboardWidth": 526, "dashboardHeight": 374},
    "Choose period: Date, Month or Year": {"dashboardPinned": True, "dashboardX": -217, "dashboardY": 38, "dashboardWidth": 384, "dashboardHeight": 163},
    "Pick a date (for Date)": {"y": 748, "dashboardPinned": True, "dashboardX": -216, "dashboardY": 218, "dashboardWidth": 382, "dashboardHeight": 166},
    "Table: shade added on Block 1259": {"x": 3862, "y": 774, "width": 979, "height": 162, "dashboardPinned": True, "dashboardX": 641, "dashboardY": 418, "dashboardWidth": 526, "dashboardHeight": 159},
    "Pick a month (for Month)": {"y": 986, "dashboardPinned": True, "dashboardX": -215, "dashboardY": 404, "dashboardWidth": 382, "dashboardHeight": 172},
}


def build() -> dict:
    import geopandas as gpd

    edits = massing()
    latitude = float(gpd.read_file(REPO / "datasets" / f"{DATA}@1" / "data" / "site.geojson").union_all().centroid.y)
    c = COLUMN
    map_x, map_size = 6 * c, (980, 700)
    nodes = [
        # 1. The data and the selection, on the left.
        node("buildings", "curio.builtin/data-loading", 0, 0, BUILDINGS,
             "Load NYC's building footprints around 1550 Bedford Avenue with their roof heights in metres.",
             title="Load existing buildings"),
        node("block", "curio.builtin/data-loading", 0, ROW, BLOCK,
             "Load Block 1259, across Eastern Parkway from the site, Franklin Avenue to Bedford Avenue.",
             title="Load Block 1259 outline"),
        node("streets", "curio.builtin/data-loading", 0, 2 * ROW, STREETS,
             "Load NYC's street centerlines around the site, each drawn as wide as its roadway.", title="Load streets"),
        parameter("period", c, ROW + 60,
                  {"name": "period", "type": "choice", "label": "Accumulate over", "default": PERIOD,
                   "options": {"choices": ["Date", "Month", "Year"], "display": "radio"}},
                  "Accumulate the shadow over one date, one month or the whole year.", "Choose period: Date, Month or Year"),
        parameter("date", c, ROW + 280,
                  {"name": "date", "type": "date", "label": "Date (when Period is Date)", "default": DATE},
                  "The date the shadow is accumulated over when Period is Date.", "Pick a date (for Date)"),
        parameter("month", c, ROW + 500,
                  {"name": "month", "type": "choice", "label": "Month (when Period is Month)", "default": MONTH,
                   "options": {"choices": MONTHS, "display": "dropdown"}},
                  "The month the shadow is accumulated over when Period is Month.", "Pick a month (for Month)"),
        # 2. The proposed building, added on the map.
        node("add-building", "curio.builtin/edit-features", c, 0, edit_code(edits),
             "Add the proposed building on the vacant site, in two parts: its base to 135 ft, 30 ft back from Eastern "
             "Parkway, and its upper floors to 185 ft, set back above the base. Redraw or raise a part here before "
             "Commit edits.", title="Add proposed tower (1550 Bedford Ave)"),
        # 3. What the GPU step reads.
        node("tower", "curio.builtin/computation-analysis", 2 * c, 0, TOWER,
             "Hand the proposed building's parts to the shader: their corners in metres and their heights.",
             title="Prepare tower for the GPU"),
        node("ground", "curio.builtin/computation-analysis", 2 * c, ROW, GROUND,
             f"Cover the area with {CELL_M} m ground cells and give them the days the selection covers.",
             title="Make ground grid and selected days"),
        # 4. The shadow, on the GPU.
        node("sun-rays", "curio.builtin/autk-grammar", 3 * c, ROW // 2, shadow_compute(latitude),
             f"On the GPU, every {STEP_MIN} minutes of every selected day, find the ground cells the proposed "
             "building blocks the sun from, and accumulate their minutes of shadow.", title="Cast sun rays on the GPU"),
        node("shadow-cells", "curio.builtin/computation-analysis", 4 * c, ROW // 2, SHADOW_CELLS,
             "Keep each ground cell's accumulated shadow, in minutes and hours.", title="Read shadow per cell"),
        node("shadow-shown", "curio.builtin/computation-analysis", 5 * c, 0, SHADOW_SHOWN,
             "Keep the cells the building shades and set the map's color scale.", title="Keep shaded cells for the map"),
        node("map-area", "curio.builtin/computation-analysis", 5 * c, -ROW, MAP_AREA,
             "Make the box around every building that the map loads first, so Autark keeps its layers whole.",
             title="Map extent (keeps layers whole)"),
        node("summary", "curio.builtin/computation-analysis", 5 * c, ROW + ROW // 2, SUMMARY,
             "Average the proposed building's shade over Block 1259's spots.",
             title="Average shade on Block 1259"),
        # 5. The answers, on the right: the map and the table under it.
        node("shadow-map", "curio.builtin/autk-grammar", map_x, -ROW, shadow_map(),
             "Map the proposed building's accumulated shadow for the selection, with Block 1259 highlighted, the "
             "proposed building in its own color and the other buildings and streets around it.",
             title="Map: tower's accumulated shadow", size=map_size),
        node("summary-view", "curio.builtin/vis-simple", map_x, -ROW + map_size[1] + 80, "",
             "Show the shade the proposed building adds on Block 1259 for the selection.",
             title="Table: shade added on Block 1259", size=(map_size[0], 150)),
    ]
    edges = [
        edge("buildings", "add-building"),
        edge("add-building", "tower"),
        edge("add-building", "ground"), edge("block", "ground"),
        edge("ground", "sun-rays"), edge("tower", "sun-rays"),
        edge("sun-rays", "shadow-cells"),
        edge("shadow-cells", "shadow-shown"), edge("add-building", "shadow-shown"), edge("buildings", "map-area"),
        edge("map-area", "shadow-map"), edge("shadow-shown", "shadow-map"), edge("add-building", "shadow-map"),
        edge("block", "shadow-map"), edge("streets", "shadow-map"),
        edge("add-building", "shadow-map", interaction=True),
        edge("shadow-cells", "summary"), edge("summary", "summary-view"),
    ]
    for entry in nodes:
        entry.update(LAYOUT.get(entry.get("title"), {}))
    return {"dataflow": {
        "categories": {"complexity": ["Intermediate"]},
        "nodes": nodes,
        "edges": edges,
        "packages": [],
        "datasets": [{"datasetId": DATA, "dirName": f"{DATA}@1", "origin": "imported", "producerNodeId": None,
                      "consumerNodeIds": [], "installedAt": STAMP}],
        "name": NAME,
        "task": "",
        "timestamp": TIMESTAMP,
        "provenance_id": NAME,
    }}


def main() -> None:
    OUT.write_text(json.dumps(build(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(REPO)}")


if __name__ == "__main__":
    main()
