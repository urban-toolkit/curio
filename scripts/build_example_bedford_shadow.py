#!/usr/bin/env python3
"""Write the crown-heights-1550-bedford-shadow example: the shadow on the open
ground around the 18-story building that ZAP project 2026K0123 proposes at
1550 Bedford Avenue, Crown Heights, and on Block 1259 across Eastern Parkway
(Franklin Avenue to Bedford Avenue), in two scenarios:

- Without the proposed building: shadow from the existing buildings only.
- With the proposed building: shadow from the proposed building and the
  existing buildings alike.

The difference between the two is the shade the proposed building adds.

The buildings, the block, the streets and the site come from the bundle
``data.nyc.crown-heights-1550-bedford`` (``scripts/build_bedford_shadow_dataset.py``).
A Map Editor node, the lever of the second scenario, adds the proposed
building in two parts drawn from the site's lot as the project's description
gives its envelope:

- a base up to 135 ft (the maximum base height) on the lot, set back 30 ft
  from the street line of Eastern Parkway at the ground floor;
- the floors above it, up to 185 ft, set back from the base's street walls
  (10 ft on the wide streets, Eastern Parkway and Bedford Avenue, 15 ft on
  Union Street, as R9A's setbacks above the base go).

The filings give no floor plates, so this is the envelope, not the design.

The day is one of 2027's equinoxes and solstices, picked with the Day widget
of "List the day's sun steps". It counts from 1.5 hours after its sunrise to
1.5 hours before its sunset (suntime), in New York time, in 10-minute steps;
at the middle of each step astral gives the sun's azimuth and elevation. Only
open ground counts: the cells under a roof are left out.

In each scenario a Python node draws its buildings into a heights grid on the
ground cells' grid, and two Autark compute steps, WebGPU shaders, march from
the ground toward the sun across it: one gives each cell's minutes in shadow
that day, for the scenario's map; the other the share of Block 1259's open
ground in shadow at each step. Outside the scenarios a plot draws both
scenarios' shares through the day, a table compares their day on the block,
and a map draws the shade the proposed building adds.

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
COLUMN = 645
ROW = 450
#: The ground cells' side and the sun's step, which set how fine the shadow is.
CELL_M, STEP_MIN = 3, 10
#: The days the Day widget offers: 2027's equinoxes and solstices, by their
#: date in New York (the US Naval Observatory's table).
DAYS = {"Spring equinox": "2027-03-20", "Summer solstice": "2027-06-21",
        "Fall equinox": "2027-09-23", "Winter solstice": "2027-12-21"}
DAY = "Winter solstice"
#: The two scenarios, in the order the comparison reads them, with the prefix
#: of their nodes' keys; the colors are the SCOUT examples' for an existing
#: case and a what-if.
SCENARIOS = [
    {"id": "without", "name": "Without the proposed building", "color": "#2a9d8f", "prefix": "base-",
     "description": "The existing buildings alone cast shadow."},
    {"id": "with", "name": "With the proposed building", "color": "#e76f51", "prefix": "",
     "description": "The proposed building, added by the Map Editor, and the existing buildings cast shadow."},
]


def nid(key: str) -> str:
    return str(uuid.uuid5(NAMESPACE, key))


# -- The proposed building ----------------------------------------------------

def massing() -> list[dict]:
    """The two parts the Map Editor node adds, as GeoJSON in EPSG:4326, from
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
    """*value* as the Python literal Map Editor writes (``pyLiteral.ts``)."""
    return json.dumps(value, ensure_ascii=False).replace("true", "True").replace("false", "False").replace("null", "None")


def edit_code(edits: list[dict]) -> str:
    lines = [
        "# Map Editor writes this code from its edit list: each edit, in the",
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
# What the maps color the buildings by: every building here stands today.
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


def steps_code(latitude: float, longitude: float) -> str:
    """The day's window and its sun steps."""
    return f'''import datetime
import math
from zoneinfo import ZoneInfo

import geopandas as gpd
import pyproj
from astral import Observer
from astral.sun import azimuth, elevation
from shapely.geometry import Point
from suntime import Sun

# The day the maps, the table and the plot show, one of 2027's equinoxes and
# solstices (the Day widget), cut into the steps the GPU steps walk. The day
# counts from 1.5 hours after its sunrise to 1.5 hours before its sunset
# (suntime), in New York time, in steps of {STEP_MIN} minutes, the last one
# shorter. At the middle of each step astral gives the sun's azimuth and its
# elevation, with refraction. One point per step, at the site.
DAYS = {json.dumps(DAYS)}
LATITUDE, LONGITUDE = {latitude}, {longitude}  # the site, 1550 Bedford Avenue
NEW_YORK = ZoneInfo("America/New_York")
STEP = datetime.timedelta(minutes={STEP_MIN})
MARGIN = datetime.timedelta(hours=1.5)

label = [!! day !!]
day = datetime.date.fromisoformat(DAYS[label])
sun = Sun(LATITUDE, LONGITUDE)
start = sun.get_sunrise_time(day, NEW_YORK) + MARGIN
end = sun.get_sunset_time(day, NEW_YORK) - MARGIN
# suntime works in UTC, where a summer sunset in New York falls on the next
# day: a window that does not run forward is a wrong day, not an empty one.
if not start < end:
    raise ValueError(f"suntime gave {{label}} ({{day}}) no window: {{start}} to {{end}}")

# The ground cells are in metres in the site's UTM zone, whose north is not
# quite true north: turn the sun's azimuth by the angle between the two.
utm = gpd.GeoSeries([Point(LONGITUDE, LATITUDE)], crs=4326).estimate_utm_crs()
to_grid = pyproj.Transformer.from_crs(4326, utm, always_xy=True)
x0, y0 = to_grid.transform(LONGITUDE, LATITUDE)
x1, y1 = to_grid.transform(LONGITUDE, LATITUDE + 0.01)
turn = math.degrees(math.atan2(x1 - x0, y1 - y0))


def clock(moment):
    """*moment* as a New York clock reads it, to the minute: 8:46 AM EST."""
    moment = (moment + datetime.timedelta(seconds=30)).replace(second=0, microsecond=0)
    noon = "AM" if moment.hour < 12 else "PM"
    return f"{{moment.hour % 12 or 12}}:{{moment.minute:02d}} {{noon}} {{moment.tzname()}}"


observer = Observer(latitude=LATITUDE, longitude=LONGITUDE)
rows, moment = [], start
while moment < end:
    length = min(STEP, end - moment)
    middle = moment + length / 2
    toward = math.radians(azimuth(observer, middle) + turn)
    rows.append({{
        "east": math.sin(toward),
        "north": math.cos(toward),
        "cot": 1 / math.tan(math.radians(elevation(observer, middle))),
        "minutes": length.total_seconds() / 60,
        # The New York clock time written as if it were UTC, so a plot draws
        # the same hours in a browser anywhere.
        "time": middle.replace(tzinfo=None).isoformat(timespec="seconds") + "Z",
        "clock": clock(middle),
    }})
    moment += length
steps = gpd.GeoDataFrame(rows, geometry=[Point(LONGITUDE, LATITUDE)] * len(rows), crs=4326)
steps["day"], steps["window_from"], steps["window_to"] = label, clock(start), clock(end)
# Every step on the first point, for the GPU step that walks the whole day
# from each ground cell.
steps["steps"] = [steps[["east", "north", "cot", "minutes"]].to_numpy().tolist()] + [None] * (len(steps) - 1)
steps.metadata = {{"layerType": "points"}}
return steps
'''


GROUND = f'''import geopandas as gpd
import numpy as np
import shapely

# The open ground the shadow is counted on: square cells of {CELL_M} m over the
# area around the buildings, but for those whose centre lies in an existing
# building (input_0). Each cell holds its column and row, its centre in metres
# from the grid's south-west corner (x east, y north), and on_block, whether
# it lies on Block 1259 (input_1). The grid rides along on every cell (its
# corner in the site's UTM zone, epsg, the cell's side, its columns and rows),
# so the nodes that draw buildings into it draw them on these same cells.
CELL = {CELL_M}
buildings, block = input_0, input_1
utm = buildings.estimate_utm_crs()
roofs = buildings.to_crs(utm)
west, south, east, north = roofs.total_bounds
cols, rows = int(np.ceil((east - west) / CELL)), int(np.ceil((north - south) / CELL))
col, row = np.meshgrid(np.arange(cols), np.arange(rows))
col, row = col.ravel(), row.ravel()
x, y = (col + 0.5) * CELL, (row + 0.5) * CELL
centres = shapely.points(west + x, south + y)
# The rule the buildings are drawn by: a centre in a footprint is under its roof.
under = np.zeros(len(centres), bool)
under[shapely.STRtree(roofs.geometry.values).query(centres, predicate="within")[0]] = True
on_block = shapely.contains_xy(block.to_crs(utm).union_all(), west + x, south + y)
keep = ~under
cells = gpd.GeoDataFrame(
    {{"col": col[keep], "row": row[keep], "x": x[keep], "y": y[keep], "on_block": on_block[keep].astype(int)}},
    geometry=shapely.box(west + x[keep] - CELL / 2, south + y[keep] - CELL / 2,
                         west + x[keep] + CELL / 2, south + y[keep] + CELL / 2),
    crs=utm,
)
cells["grid_west"], cells["grid_south"], cells["cell"] = float(west), float(south), float(CELL)
cells["cols"], cells["rows"], cells["epsg"] = cols, rows, utm.to_epsg()
cells = cells.to_crs(buildings.crs)
# Tell the Autark map these are areas, so it fills them.
cells.metadata = {{"layerType": "polygons"}}
return cells
'''

PREPARE = '''import geopandas as gpd
import numpy as np
import shapely
from shapely.geometry import box

# This scenario's buildings (input_0) as the GPU steps read them, one feature:
# heights, the roof over each cell of the ground grid (input_1), 0 where no
# building stands, row by row from the south; tallest, the highest roof; and
# spots, the centres of Block 1259's open-ground cells. A cell's height is the
# roof of the building its centre lies in, the rule the grid drops cells by.
buildings, grid = input_0, input_1
first = grid.iloc[0]
utm = f"EPSG:{int(first['epsg'])}"
west, south, cell = float(first["grid_west"]), float(first["grid_south"]), float(first["cell"])
cols, rows = int(first["cols"]), int(first["rows"])
col, row = np.meshgrid(np.arange(cols), np.arange(rows))
centres = shapely.points(west + (col.ravel() + 0.5) * cell, south + (row.ravel() + 0.5) * cell)
roofs = buildings.to_crs(utm)
centre, roof = shapely.STRtree(roofs.geometry.values).query(centres, predicate="within")
heights = np.zeros(rows * cols)
np.maximum.at(heights, centre, roofs["height"].to_numpy(dtype=float)[roof])
on_block = grid[grid["on_block"] == 1]
prepared = gpd.GeoDataFrame(
    {
        "heights": [np.round(heights.reshape(rows, cols), 2).tolist()],
        "tallest": [float(heights.max())],
        "spots": [on_block[["x", "y"]].to_numpy(dtype=float).tolist()],
    },
    geometry=[box(west, south, west + cols * cell, south + rows * cell)], crs=utm,
).to_crs(4326)
prepared.metadata = {"layerType": "polygons"}
return prepared
'''

READ_CELLS = '''import pandas as pd

# The ground cells with the minutes the GPU step found each in shadow that
# day (shadow_min) and the share of the day's window that is (shadow_share,
# in %). The step hands on the cells, input_0's first layer, with its result
# under compute, and the day's steps as its third layer. A cell it marked -1
# lies under a roof in this scenario, so it is left out.
cells = [!! input_0:input_0 !!]
steps = [!! input_0:input_2 !!]
# The GPU step hands its layers on as GeoJSON, in longitude and latitude.
if cells.crs is None:
    cells = cells.set_crs(4326)
if "shadow_min" not in cells.columns:
    cells["shadow_min"] = [row.get("shadow_min") if isinstance(row, dict) else None for row in cells["compute"]]
cells["shadow_min"] = pd.to_numeric(cells["shadow_min"])
cells = cells[cells["shadow_min"] >= 0].copy()
window = float(pd.to_numeric(steps["minutes"]).sum())
cells["shadow_share"] = 100 * cells["shadow_min"] / window
cells = cells[["col", "row", "x", "y", "on_block", "shadow_min", "shadow_share", "geometry"]]
cells.metadata = {"layerType": "polygons"}
return cells
'''

READ_STEPS = '''import pandas as pd

# The share of Block 1259's open ground in shadow at each step of the day
# (share, in %), with the step's time and minutes and the day's window, as a
# table the comparison reads. The GPU step hands on the steps, input_0's
# first layer, with its result under compute.
steps = [!! input_0:input_0 !!]
if "share" not in steps.columns:
    steps["share"] = [row.get("share") if isinstance(row, dict) else None for row in steps["compute"]]
return pd.DataFrame({
    "time": steps["time"],
    "clock": steps["clock"],
    "share": pd.to_numeric(steps["share"]),
    "minutes": pd.to_numeric(steps["minutes"]),
    "day": steps["day"],
    "window_from": steps["window_from"],
    "window_to": steps["window_to"],
})
'''

SHOWN = '''import numpy as np

# What the map colors: the cells in shadow at all that day, by the share of
# the day's window they spend in it (in %), in classes 5 points wide, each
# drawn at its middle. Cells of a class that touch become one area: cell by
# cell, the two scenarios' maps would outgrow the data a shared dashboard
# carries. The map sets the scale from 0 to 100, so both maps color a share
# alike.
STEP = 5
shaded = input_0.loc[input_0["shadow_share"] > 0, ["shadow_share", "geometry"]]
shaded = shaded.assign(shadow_share=(np.ceil(shaded["shadow_share"] / STEP) - 0.5) * STEP)
shown = shaded.dissolve(by="shadow_share", as_index=False).explode(index_parts=False).reset_index(drop=True)
shown.metadata = {"layerType": "polygons"}
return shown
'''

ADDED = '''# The shade the proposed building adds on each open-ground cell that day:
# the minutes in shadow with it (input_1) less the minutes without it
# (input_0), cell by cell. The cells under the building itself are not
# ground with it, so they drop out.
without, with_building = input_0, input_1
added = with_building.merge(without[["col", "row", "shadow_min"]], on=["col", "row"], suffixes=("", "_without"))
added["added_min"] = added["shadow_min"] - added["shadow_min_without"]
added = added[["col", "row", "x", "y", "on_block", "added_min", "geometry"]]
added.metadata = {"layerType": "polygons"}
return added
'''

ADDED_SHOWN = '''import math

import geopandas as gpd
import pandas as pd
from shapely.geometry import box

# What the map colors: the cells the proposed building shades at all, by the
# minutes it adds, the scale topped at the 90th percentile of them so the far
# reach of its shadow stays visible beside the cells next to it, which it
# shades almost all day. input_0 is the shade added per cell, input_1 the
# buildings with the proposed one.
shaded = input_0.loc[input_0["added_min"] > 0, ["added_min", "geometry"]].copy()
if len(shaded):
    top = float(shaded["added_min"].quantile(0.9))
    shaded["added_shown"] = shaded["added_min"].clip(upper=top)
    # Autark's legend runs from the layer's lowest value to its highest, so
    # two small cells hidden under the proposed building hold the whole
    # minutes below and above them: the legend reads from floor to ceiling.
    low, high = math.floor(shaded["added_shown"].min()), math.ceil(shaded["added_shown"].max())
    tower = input_1[input_1["status"] != "Existing"].to_crs(shaded.crs).union_all().centroid
    side = 1e-6
    anchors = gpd.GeoDataFrame(
        {"added_shown": [float(low), float(high)]},
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

# The area the maps show, one box around every building. A map loads it first
# and does not draw it: Autark clips every layer it loads after the first to
# the first one's outline, so with this box first every layer stays whole.
return gpd.GeoDataFrame({"area": ["map"]}, geometry=[box(*input_0.total_bounds)], crs=input_0.crs)
'''

COMPARE = '''import pandas as pd

# The day on Block 1259's open ground in both scenarios: each one's average
# time in shadow over the day's window (the share in shadow at each step,
# times the step's minutes, summed), and what the proposed building adds.
# input_0 is the scenario without the proposed building, input_1 the one
# with it.
def duration(minutes):
    hours, rest = divmod(round(minutes), 60)
    if not hours:
        return f"{rest} min"
    return f"{hours} h {rest} min" if rest else f"{hours} h"


without, with_building = input_0, input_1
dark_without = float((without["share"] / 100 * without["minutes"]).sum())
dark_with = float((with_building["share"] / 100 * with_building["minutes"]).sum())
day = with_building.iloc[0]
return pd.DataFrame([{
    "Day": day["day"],
    "From": day["window_from"],
    "To": day["window_to"],
    "Time counted": duration(float(with_building["minutes"].sum())),
    "Without the proposed building": duration(dark_without),
    "With the proposed building": duration(dark_with),
    "Added": duration(dark_with - dark_without),
}])
'''


def grammar(document: dict) -> str:
    return json.dumps(document, indent=2) + "\n"


def march(x: str, y: str) -> list[str]:
    """WGSL lines that set ``shaded`` for the ray from the ground point
    (*x*, *y*), in metres from the grid's south-west corner, toward the sun of
    the step at hand (``sx``, ``sy``: the way to it, ``cot``: the cotangent
    of its elevation). The ray rises ``t / cot`` over a run of ``t``; it
    walks half a cell at a time until it is above the tallest roof or leaves
    the grid, and a roof above it at any sample means shadow."""
    half = CELL_M / 2
    return [
        "var shaded = false;",
        f"for (var t: f32 = {half}; t <= tallest * cot; t += {half}) {{",
        f"    let col = i32(floor(({x} + sx * t) / {CELL_M}.0));",
        f"    let row = i32(floor(({y} + sy * t) / {CELL_M}.0));",
        "    if (col < 0 || row < 0 || col >= i32(heights_cols) || row >= i32(heights_rows)) { break; }",
        "    if (heights[u32(row) * heights_cols + u32(col)] * cot > t) { shaded = true; break; }",
        "}",
    ]


def cells_pass() -> str:
    """The Autark compute step for the map: each ground cell's minutes in
    shadow over the day's steps. input_0 is the ground cells, input_1 the
    scenario's buildings for the GPU and input_2 the day's steps."""
    shader = [
        "// Minutes this ground cell spends in shadow over the day: at each step",
        "// (steps: toward east, toward north, cot of the elevation, minutes), the",
        "// ray from the cell toward the sun across the heights grid. A cell under",
        "// a roof in this scenario gets -1, and the next node leaves it out.",
        f"let own = heights[u32(floor(y / {CELL_M}.0)) * heights_cols + u32(floor(x / {CELL_M}.0))];",
        "if (own > 0.0) { return -1.0; }",
        "var total: f32 = 0.0;",
        "for (var s = 0u; s < steps_rows; s++) {",
        "    let sx = steps[s * 4u];",
        "    let sy = steps[s * 4u + 1u];",
        "    let cot = steps[s * 4u + 2u];",
        *("    " + line for line in march("x", "y")),
        "    if (shaded) { total += steps[s * 4u + 3u]; }",
        "}",
        "return total;",
    ]
    return grammar({"compute": [{
        "dataRef": "[!! input_0 !!]",
        "attributes": {"x": "properties.x", "y": "properties.y"},
        "uniforms": {"tallest": {"fromFeature": {"layer": "[!! input_1 !!]", "path": "properties.tallest"}}},
        "uniformMatrices": {
            "heights": {"fromFeature": {"layer": "[!! input_1 !!]", "path": "properties.heights"}},
            "steps": {"fromFeature": {"layer": "[!! input_2 !!]", "path": "properties.steps"}, "cols": 4},
        },
        "outputColumnName": "shadow_min",
        "wglsFunction": shader,
    }]})


def block_pass() -> str:
    """The Autark compute step for the block: at each step of the day, the
    share of Block 1259's open ground in shadow. input_0 is the day's steps,
    input_1 the scenario's buildings for the GPU."""
    shader = [
        "// The share of Block 1259's open ground in shadow at this step (in %):",
        "// from each of its spots (spots: x, y), the ray toward the sun, marched",
        "// across the heights grid as on the map.",
        "var dark: f32 = 0.0;",
        "for (var p = 0u; p < spots_rows; p++) {",
        "    let px = spots[p * 2u];",
        "    let py = spots[p * 2u + 1u];",
        *("    " + line for line in march("px", "py")),
        "    if (shaded) { dark += 1.0; }",
        "}",
        "return 100.0 * dark / f32(max(spots_rows, 1u));",
    ]
    return grammar({"compute": [{
        "dataRef": "[!! input_0 !!]",
        "attributes": {"sx": "properties.east", "sy": "properties.north", "cot": "properties.cot"},
        "uniforms": {"tallest": {"fromFeature": {"layer": "[!! input_1 !!]", "path": "properties.tallest"}}},
        "uniformMatrices": {
            "heights": {"fromFeature": {"layer": "[!! input_1 !!]", "path": "properties.heights"}},
            "spots": {"fromFeature": {"layer": "[!! input_1 !!]", "path": "properties.spots"}, "cols": 2},
        },
        "outputColumnName": "share",
        "wglsFunction": shader,
    }]})


def shadow_map(value: str, title: str, scale: dict) -> str:
    """A map of one shaded layer, with the streets under it, Block 1259 over
    it and the buildings in 3D, the proposed one in its own color: input_0 is
    the map's area (loaded, not drawn), input_1 the shaded cells, input_2 the
    buildings, input_3 the block and input_4 the streets."""
    return grammar({"map": {"layerRefs": [
        {"dataRef": "[!! input_0 !!]", "isSkip": True},
        {"dataRef": "[!! input_4 !!]", "color": "#d5d9df", "stroke": False, "title": "Streets"},
        {"dataRef": "[!! input_2 !!]", "selectFields": ["building_id"],
         "getFnv": "status", "getFnvType": "categorical", "colorMapInterpolator": "schemeTableau10",
         "title": "Building"},
        # The last color-mapped layer, which Autark gives the map's only legend,
        # and the one pickable layer (Map Editor picks on the buildings itself
        # while editing).
        {"dataRef": "[!! input_1 !!]", "isPick": True, "getFnv": value, "getFnvType": "quantitative",
         "isColorMap": True, "colorMapInterpolator": "interpolateRdPu", **scale, "stroke": False, "opacity": 0.9,
         "title": title},
        # Over the shadow, so the block stays visible; a fixed color, so it
        # takes no legend.
        {"dataRef": "[!! input_3 !!]", "color": "#ffd166", "stroke": "#e09f00", "opacity": 0.4,
         "title": "Block 1259"},
    ]}})


def plot() -> str:
    """Both scenarios' share of Block 1259's open ground in shadow through the
    day: the scenarios' per-step tables stacked by Curio as ``inputs``, a
    line each in its scenario's color."""
    spec = {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "data": {"name": "[!! inputs !!]"},
        "mark": {"type": "line", "point": True},
        "encoding": {
            "x": {"field": "time", "type": "temporal", "scale": {"type": "utc"},
                  "axis": {"format": "%-I %p"}, "title": "Time (New York)"},
            "y": {"field": "share", "type": "quantitative", "scale": {"domain": [0, 100]},
                  "title": "Block 1259's open ground in shadow (%)"},
            "color": {"field": "scenario_name", "type": "nominal", "title": "Scenario",
                      "scale": "SCENARIO_COLORS", "sort": "SCENARIO_ORDER"},
            "tooltip": [
                {"field": "scenario_name", "type": "nominal", "title": "Scenario"},
                {"field": "clock", "type": "nominal", "title": "Time"},
                {"field": "share", "type": "quantitative", "title": "In shadow (%)", "format": ".0f"},
            ],
        },
    }
    return (json.dumps(spec, indent=2)
            .replace('"SCENARIO_COLORS"', "[!! scenario colors !!]")
            .replace('"SCENARIO_ORDER"', "[!! scenario order !!]") + "\n")


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


#: The dashboard: the three maps across the top, then the Day widget's node,
#: the Map Editor, the plot and, under them, the table; by node key.
LAYOUT = {
    "base-shadow-map": {"dashboardPinned": True, "dashboardX": 0, "dashboardY": 0, "dashboardWidth": 420, "dashboardHeight": 380},
    "shadow-map": {"dashboardPinned": True, "dashboardX": 430, "dashboardY": 0, "dashboardWidth": 420, "dashboardHeight": 380},
    "added-map": {"dashboardPinned": True, "dashboardX": 860, "dashboardY": 0, "dashboardWidth": 420, "dashboardHeight": 380},
    "steps": {"dashboardPinned": True, "dashboardX": 0, "dashboardY": 390, "dashboardWidth": 250, "dashboardHeight": 230},
    "add-building": {"dashboardPinned": True, "dashboardX": 260, "dashboardY": 390, "dashboardWidth": 340, "dashboardHeight": 330},
    "plot": {"dashboardPinned": True, "dashboardX": 610, "dashboardY": 390, "dashboardWidth": 670, "dashboardHeight": 330},
    "summary-view": {"dashboardPinned": True, "dashboardX": 0, "dashboardY": 730, "dashboardWidth": 1280, "dashboardHeight": 140},
}


#: The nodes of a scenario's chain, by key without the scenario's prefix.
CHAIN = ("tower", "sun-rays", "block-rays", "shadow-cells", "block-steps", "shadow-shown", "shadow-map")


def scenario_nodes(scenario: dict, top: int) -> list[dict]:
    """One scenario's chain, from its buildings to its map, on the canvas row
    *top*. The second scenario's nodes are copies of the first's
    (``copiedFrom``), titled alike but for its map."""
    p, c = scenario["prefix"], COLUMN
    original = SCENARIOS[0]["prefix"]
    copied = (lambda key: None) if scenario is SCENARIOS[0] else (lambda key: original + key)
    which = scenario["name"][0].lower() + scenario["name"][1:]
    return [
        node(p + "tower", "curio.builtin/computation-analysis", 2 * c, top, PREPARE,
             "Draw this scenario's buildings into a heights grid on the ground cells, with Block 1259's open cells "
             "as the spots the block step reads.", title="Prepare buildings for the GPU", copied=copied("tower")),
        node(p + "sun-rays", "curio.builtin/autk-grammar", 3 * c, top, cells_pass(),
             f"On the GPU, march from every ground cell toward the sun at every {STEP_MIN}-minute step of the day "
             "and add up the minutes a roof blocks it.", title="Cast sun rays on the GPU", copied=copied("sun-rays")),
        node(p + "block-rays", "curio.builtin/autk-grammar", 3 * c, top + ROW, block_pass(),
             "On the GPU, at every step of the day, find the share of Block 1259's open ground a roof keeps from the "
             "sun.", title="Cast sun rays on Block 1259", copied=copied("block-rays")),
        node(p + "shadow-cells", "curio.builtin/computation-analysis", 4 * c, top, READ_CELLS,
             "Keep each open-ground cell's minutes in shadow and their share of the day's window.",
             title="Read shadow per cell", copied=copied("shadow-cells")),
        node(p + "block-steps", "curio.builtin/computation-analysis", 4 * c, top + ROW, READ_STEPS,
             "Keep the share of Block 1259's open ground in shadow at each step, with its time.",
             title="Read shadow on the block per step", copied=copied("block-steps")),
        node(p + "shadow-shown", "curio.builtin/computation-analysis", 5 * c, top, SHOWN,
             "Gather the cells in shadow into classes of the share of the day's window for the map.",
             title="Keep shaded cells for the map",
             copied=copied("shadow-shown")),
        node(p + "shadow-map", "curio.builtin/autk-grammar", 6 * c, top,
             shadow_map("shadow_share", "Shadow (% of the day's window)", {"colorMapRange": [0, 100]}),
             f"Map the shadow on the open ground {which}, with the buildings, Block 1259 and the streets.",
             title=f"Map: {which}", copied=copied("shadow-map"), size=(980, 700)),
    ]


def build() -> dict:
    import geopandas as gpd

    edits = massing()
    site = gpd.read_file(REPO / "datasets" / f"{DATA}@1" / "data" / "site.geojson").union_all().centroid
    c = COLUMN
    without, with_building = SCENARIOS
    nodes = [
        # 1. The data and the day, fixed for both scenarios, on the left.
        node("buildings", "curio.builtin/data-loading", 0, 0, BUILDINGS,
             "Load NYC's building footprints around 1550 Bedford Avenue with their roof heights in metres.",
             title="Load existing buildings"),
        node("block", "curio.builtin/data-loading", 0, ROW, BLOCK,
             "Load Block 1259, across Eastern Parkway from the site, Franklin Avenue to Bedford Avenue.",
             title="Load Block 1259 outline"),
        node("streets", "curio.builtin/data-loading", 0, 2 * ROW, STREETS,
             "Load NYC's street centerlines around the site, each drawn as wide as its roadway.", title="Load streets"),
        node("steps", "curio.builtin/computation-analysis", c, 0, steps_code(round(site.y, 4), round(site.x, 4)),
             "For the day picked, an equinox or a solstice of 2027, count from 1.5 hours after sunrise to 1.5 hours "
             f"before sunset in New York time, in {STEP_MIN}-minute steps, with the sun's direction and height at "
             "each.", title="List the day's sun steps",
             widgets=[{"name": "day", "type": "choice", "label": "Day", "default": DAY,
                       "options": {"choices": list(DAYS), "display": "radio"}}]),
        node("ground", "curio.builtin/computation-analysis", c, ROW, GROUND,
             f"Cover the area with {CELL_M} m cells and keep the open ground, the cells outside every existing "
             "building, marking the ones on Block 1259.", title="Make open-ground grid"),
        node("map-area", "curio.builtin/computation-analysis", c, 2 * ROW, MAP_AREA,
             "Make the box around every building that the maps load first, so Autark keeps their layers whole.",
             title="Map extent (keeps layers whole)"),
        # 2. The scenarios: without the proposed building above, with it below.
        *scenario_nodes(without, -2 * ROW),
        node("add-building", "curio.builtin/edit-features", c, 3 * ROW, edit_code(edits),
             "Add the proposed building on the vacant site, in two parts: its base to 135 ft, 30 ft back from Eastern "
             "Parkway, and its upper floors to 185 ft, set back above the base. Redraw or raise a part here before "
             "Commit edits.", title="Add proposed tower (1550 Bedford Ave)"),
        *scenario_nodes(with_building, 3 * ROW),
        # 3. The comparison, on the right.
        node("added", "curio.builtin/computation-analysis", 7 * c + 400, 0, ADDED,
             "Subtract each open-ground cell's minutes in shadow without the proposed building from its minutes "
             "with it.", title="Shade the tower adds"),
        node("added-shown", "curio.builtin/computation-analysis", 8 * c + 400, 0, ADDED_SHOWN,
             "Keep the cells the proposed building shades and set the map's color scale.",
             title="Keep added shade for the map"),
        node("added-map", "curio.builtin/autk-grammar", 9 * c + 400, -ROW,
             shadow_map("added_shown", "Shade added (minutes)", {}),
             "Map the shade the proposed building adds that day, with Block 1259, the buildings and the streets.",
             title="Map: shade the tower adds", size=(980, 700)),
        node("compare", "curio.builtin/computation-analysis", 7 * c + 400, ROW + ROW // 2, COMPARE,
             "Compare the day on Block 1259's open ground without and with the proposed building, and what it adds.",
             title="Compare the scenarios on Block 1259"),
        node("summary-view", "curio.builtin/vis-simple", 8 * c + 400, ROW + ROW // 2, "",
             "Show the day on Block 1259's open ground in both scenarios and the shade the proposed building adds.",
             title="Table: shadow on Block 1259", size=(980, 150)),
        node("plot", "curio.builtin/vis-vega", 8 * c + 400, 2 * ROW + ROW // 2, plot(),
             "Plot the share of Block 1259's open ground in shadow through the day, a line per scenario.",
             title="Plot: shadow on Block 1259 through the day", size=(980, 500)),
    ]
    edges = [
        edge("buildings", "ground"), edge("block", "ground"),
        edge("buildings", "map-area"),
        edge("buildings", "add-building"),
    ]
    for scenario, buildings in ((without, "buildings"), (with_building, "add-building")):
        p = scenario["prefix"]
        edges += [
            edge(buildings, p + "tower"), edge("ground", p + "tower"),
            edge("ground", p + "sun-rays"), edge(p + "tower", p + "sun-rays"), edge("steps", p + "sun-rays"),
            edge("steps", p + "block-rays"), edge(p + "tower", p + "block-rays"),
            edge(p + "sun-rays", p + "shadow-cells"),
            edge(p + "block-rays", p + "block-steps"),
            edge(p + "shadow-cells", p + "shadow-shown"),
            edge("map-area", p + "shadow-map"), edge(p + "shadow-shown", p + "shadow-map"),
            edge(buildings, p + "shadow-map"), edge("block", p + "shadow-map"), edge("streets", p + "shadow-map"),
        ]
    edges += [
        # Map Editor edits on the map of its own scenario.
        edge("add-building", "shadow-map", interaction=True),
        edge("base-shadow-cells", "added"), edge("shadow-cells", "added"),
        edge("added", "added-shown"), edge("add-building", "added-shown"),
        edge("map-area", "added-map"), edge("added-shown", "added-map"), edge("add-building", "added-map"),
        edge("block", "added-map"), edge("streets", "added-map"),
        # The scenario without the proposed building first: Curio stacks a
        # node's inputs in the order of its circles.
        edge("base-block-steps", "plot"), edge("block-steps", "plot"),
        edge("base-block-steps", "compare"), edge("block-steps", "compare"),
        edge("compare", "summary-view"),
    ]
    # A key that names no node would silently leave its tile off the dashboard.
    ids = {entry["id"] for entry in nodes}
    missing = [key for key in LAYOUT if nid(key) not in ids]
    assert not missing, f"LAYOUT names nodes the example does not have: {missing}"
    places = {nid(key): place for key, place in LAYOUT.items()}
    for entry in nodes:
        entry.update(places.get(entry["id"], {}))
    scenarios = []
    for scenario in SCENARIOS:
        # The Map Editor is the lever of the scenario with the proposed building.
        levers = ["add-building"] if scenario is with_building else []
        scenarios.append({"id": scenario["id"], "name": scenario["name"], "color": scenario["color"],
                          "description": scenario["description"],
                          "nodes": [nid(key) for key in levers + [scenario["prefix"] + k for k in CHAIN]]})
    return {"dataflow": {
        "categories": {"complexity": ["Beginner"]},
        "nodes": nodes,
        "edges": edges,
        "packages": [],
        "datasets": [{"datasetId": DATA, "dirName": f"{DATA}@1", "origin": "imported", "producerNodeId": None,
                      "consumerNodeIds": [], "installedAt": STAMP}],
        "scenarios": scenarios,
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
