#!/usr/bin/env python3
"""Write the FloodRisk example, ``docs/examples/dataflows/FloodRisk.json``.

FloodScenarios (example 25) compares SCOUT's Quad Cities flood depth with no
nature-based solutions (NbS) and with all of them, by its median. FloodRisk asks
how deep that flood stands on the tracts along the Mississippi, how much the solutions
lower it, and in which tracts by their vulnerability. It stays beside
FloodScenarios, which this script never touches.

- Region: SCOUT's whole flood grid, fixed in the scout.flood package's code.
- Shared context: one Parameter node, the Map period both Flood Projections
  map (FloodScenarios shares its period the same way). The projection periods
  the bar chart compares (one or more) are a widget of Average depth by period,
  the one node that reads them.
- Data: two datasets, each loaded as a dataset dragged from the Data Catalog
  is: CDC's Social Vulnerability Index tracts and USGS's waterways (NHD), both
  of which the Dataset Finder finds; harmonized into the riverside tracts, those
  the Mississippi's channel touches, which Harmonize saves as a computed
  dataset. The depth nodes load it, and the waterways, with Curio's API
  (curio_computed_path, curio_load_data) rather than by edges.
- Each scenario (No NbS, All NbS): the scout.flood package's Flood Projection,
  its own code as FloodScenarios runs it, for the Map period, with its four
  solutions (none, or all), and a map of the depth on the riverside tracts with
  their borders over it, and of each tract's average depth over its land, on
  one scale in both. One Average depth by period node runs SCOUT's flood
  projection for every ticked period, both scenarios, for the bar chart. A Tract
  borders node turns the saved riverside tracts into 60 m bands for the maps.
- Comparisons: the change in depth on the riverside tracts, how much NbS lowers
  each tract's average depth, and two Vega-Lite charts: the bar chart of the
  period depths, whose rows name their scenario, and the scatter, reading the
  tract depths stacked (``inputs``), naming its scenarios from ``__input__``.
- Agents (attached in a live project, not in this file): the Dataset Finder on
  the two loaders, the Node Content Builder on the harmonizing and depth
  nodes, and the Researcher on the canvas, which writes its findings into notes.

The two scenarios keep SCOUT's own rule: a solution changes the depth only
where it is placed, so the measures are of land, not of buildings, which
almost never stand where a solution goes.

It also writes the example's prompt fixture,
``docs/examples/prompts/dataflows/FloodRisk.prompt.json``, whose digest and
expected graph ``scripts/example_fixture_skeleton.py`` derives.

USAGE
-----
    python scripts/build_example_flood_risk.py
"""
from __future__ import annotations

import copy
import importlib.util
import json
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PACKAGE = REPO / "packages" / "scout.flood@1"
DATAFLOWS = REPO / "docs" / "examples" / "dataflows"
TARGET = DATAFLOWS / "FloodRisk.json"
FIXTURE = REPO / "docs" / "examples" / "prompts" / "dataflows" / "FloodRisk.prompt.json"
NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "https://curio.dev/examples/FloodRisk")
TRACTS = "data.cdc.quad-cities-svi-tracts"
WATERWAYS = "data.usgs.quad-cities-waterways"
FLOOD = "data.scout.quad-cities-flood"
VEGA_SCHEMA = "https://vega.github.io/schema/vega-lite/v6.json"
#: SCOUT's whole flood grid, the region both scenarios project: its top-left and
#: bottom-right corners (FloodScenarios' defaults).
GRID_TOPLEFT = {"lat": 41.6242105, "lon": -90.6879323}
GRID_BOTTOMRIGHT = {"lat": 41.4150156, "lon": -90.4252158}
PERIODS = ["2020 - 2050", "2050 - 2080", "2080 - 2100"]
#: The scout.flood package's four solutions, one per kind (its bioswales/
#: infiltration trenches are SCOUT's classes 21, 52, 71 and 81).
SOLUTIONS = ["Bioswales/Infiltration trenches", "Permeable pavements", "Retention ponds", "Constructed wetlands"]
#: key, name, color (FloodScenarios' own), the solutions in place.
SCENARIOS = [("no-nbs", "No NbS", "#e76f51", []), ("all-nbs", "All NbS", "#2a9d8f", SOLUTIONS)]


def _charts_module():
    spec = importlib.util.spec_from_file_location("scenario_charts", REPO / "scripts" / "build_scenario_charts_example.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


name_the_scenarios = _charts_module().name_the_scenarios


def node_id(key: str) -> str:
    return str(uuid.uuid5(NAMESPACE, key))


def node(key, node_type, x, y, title, goal, content, metadata=None, **extra) -> dict:
    return {
        "id": node_id(key), "type": node_type, "x": x, "y": y, "content": content,
        "out": "DEFAULT", "in": "DEFAULT", "goal": goal,
        "metadata": {"keywords": [], **(metadata or {}), "packageTemplateLabel": title},
        "title": title, **extra,
    }


def edge(source: dict, target: dict, slot: int) -> dict:
    handle = "in" if slot == 0 else f"in_{slot}"
    return {
        "id": f"reactflow__edge-{source['id']}out-{target['id']}{handle}",
        "source": source["id"], "target": target["id"], "sourceHandle": "out", "targetHandle": handle,
    }


# ── node code ────────────────────────────────────────────────────────────────

# What a Data Loading node holds when a dataset is dragged from the Data Catalog.
LOAD_TRACTS = f'''# How these census tracts were acquired, to do it again:
# 1. Set up an LLM in API Settings; the Dataset Finder answers with it.
# 2. Agent Catalog (canvas top bar) -> Dataset Finder -> Add to project, and drag
#    it onto this node, then open its chat.
# 3. Ask: "Census tracts with CDC's Social Vulnerability Index (SVI) 2020 for
#    Scott County, Iowa and Rock Island and Henry Counties, Illinois."
# 4. Under External sources it finds CDC/ATSDR's "CDC/ATSDR Social
#    Vulnerability Index 2020 USA" on ArcGIS Hub (item
#    3827cb5593174c79b35119611299279b; layer 2 holds the tracts). The whole
#    layer is about 268 MB, every tract in the country, so either:
#    - Download it (Downloadable) and keep the tracts that meet SCOUT's flood
#      grid in a node after this one, or
#    - let it hand off to the Node Builder, which writes a loader asking the
#      layer only for the three counties: STCNTY IN ('19163','17161','17073').
# 5. Keep the tracts that meet SCOUT's flood grid, West -90.6879323,
#    South 41.4150156, East -90.4252158, North 41.6242105: 86 tracts, CDC's
#    column names, -999 missing.
# 6. Shipped: that query and that box, run by scripts/build_flood_risk_datasets.py,
#    saved as {TRACTS}, so every account loads it by the same id.
df = curio_load_data("{TRACTS}")
return df
'''

HARMONIZE = '''# Harmonize: CDC's tracts into the shape the depth measures read, kept to the
# riverside tracts: those that touch the Mississippi's channel. input_0 is the
# tracts as CDC publishes them; the waterways are NHD's, loaded here, whose
# stream and river areas (FTYPE 460) are the Mississippi's channel.
# Output: the riverside tracts with an SVI percentile, readable names, in
# EPSG:4326, saved as this dataflow's computed dataset "riverside-tracts", which
# the depth nodes read with curio_computed_path, and returned for the maps.
import numpy as np

tracts = input_0
waterways = curio_load_data("data.usgs.quad-cities-waterways")

# CDC: readable names, its -999 as missing, the tract's FIPS code as text.
t = tracts.to_crs("EPSG:4326").replace(-999, np.nan)
t = t.rename(columns={
    "FIPS": "tract_fips", "LOCATION": "tract", "COUNTY": "county", "STATE": "state",
    "E_TOTPOP": "people", "E_HU": "housing_units", "E_AGE65": "people_65_plus",
    "E_DISABL": "people_disabled", "E_NOVEH": "households_no_vehicle",
    "E_POV150": "people_below_150_poverty", "RPL_THEMES": "svi", "RPL_THEME1": "svi_socioeconomic",
    "RPL_THEME2": "svi_household", "RPL_THEME3": "svi_minority_language", "RPL_THEME4": "svi_housing_transport",
})
t["tract_fips"] = t["tract_fips"].astype(str).str.zfill(11)
t = t[["tract_fips", "tract", "county", "state", "people", "housing_units", "people_65_plus", "people_disabled",
       "households_no_vehicle", "people_below_150_poverty", "svi", "svi_socioeconomic", "svi_household",
       "svi_minority_language", "svi_housing_transport", "geometry"]].reset_index(drop=True)

# The riverside tracts: those the Mississippi's channel touches, with an SVI
# percentile.
river = waterways[waterways["FTYPE"] == 460].to_crs("EPSG:4326").union_all()
riverside = t[t.intersects(river) & t["svi"].notna()].reset_index(drop=True)
# One category for every tract, so the maps draw them in one strong color.
riverside["tract_group"] = "Riverside tract"
riverside.to_file(curio_save_file("riverside-tracts.geojson"), driver="GeoJSON")
return riverside
'''

#: The Flood Projection's code: the scout.flood package's own, as FloodScenarios
#: has it, with its period the dataflow's Map period (a shared Parameter node).
FLOOD_PROJECTION = (PACKAGE / "sources" / "flood-projection.py").read_text(encoding="utf-8").replace(
    "[!! timeline !!]", "[!! @timeline !!]")
assert "[!! @timeline !!]" in FLOOD_PROJECTION
#: Its widgets, the package's template's, but the period, which is shared.
FLOOD_WIDGETS = [w for w in json.loads((PACKAGE / "manifest.json").read_text(encoding="utf-8"))["templates"][0]["widgets"]
                 if w["name"] != "timeline"]

#: Shared by the depth nodes: the grid's cells' areas and
#: the water, on the depth raster's own grid.
_GRID = '''

def depth_of(raster):
    """The depth in metres, 0 where SCOUT's raster holds no data (dry land)."""
    depth = raster.read(1).astype("float64")
    depth[~np.isfinite(depth) | (depth < 0)] = 0.0
    return depth


def cell_areas(raster):
    """Each cell's area in km2: SCOUT's grid is in degrees, so a cell narrows
    with its latitude."""
    t = raster.transform
    lat = t.f + t.e * (np.arange(raster.height) + 0.5)
    rows = (abs(t.a) * 111.32 * np.cos(np.radians(lat))) * (abs(t.e) * 110.574)
    return np.broadcast_to(rows[:, None], (raster.height, raster.width))


def water_on(raster, water):
    """Where the grid's cells are water: rivers, lakes and reservoirs."""
    return rasterize(((g, 1) for g in water.geometry), out_shape=(raster.height, raster.width),
                     transform=raster.transform, fill=0, dtype="uint8").astype(bool)
'''

PERIOD_DEPTH = f'''"""Average depth by period: for every period ticked in its Projection periods widget, the
average flood depth over the riverside tracts' land (the water itself left
out, dry land as 0 m), weighted by area, with no nature-based solution and
with all four: SCOUT's simulate_flood_projection run for each, on SCOUT's
whole grid, as the Flood Projection nodes run it for the map period. Input:
none. The riverside tracts are Harmonize's computed dataset, the water NHD's
waterways. One row per period and scenario.
"""
import hashlib
import json
import os

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.features import rasterize
from scout_flood.flood_simulation import simulate_flood_projection
{_GRID}

ORDER = {json.dumps(PERIODS)}
#: Each scenario's name and the solutions in place.
SCENARIOS = {json.dumps({name: chosen for _, name, _, chosen in SCENARIOS})}
#: SCOUT's whole grid.
topleft, bottomright = {json.dumps(GRID_TOPLEFT)}, {json.dumps(GRID_BOTTOMRIGHT)}

periods = [p for p in ORDER if p in [!! periods !!]]
rasters = os.path.dirname(curio_data_path("{FLOOD}"))
tracts = gpd.read_file(curio_computed_path("riverside-tracts"))
water = curio_load_data("{WATERWAYS}").to_crs("EPSG:4326")

rows, land = [], None
for period in periods:
    for name, chosen in SCENARIOS.items():
        # Named by its settings: every node's output files share one folder.
        settings = json.dumps([topleft, bottomright, period, sorted(chosen)], sort_keys=True)
        path = curio_output_file(f"period-flood-{{hashlib.sha256(settings.encode()).hexdigest()[:16]}}.tif")
        simulate_flood_projection(
            f"{{topleft['lon']!r}}, {{topleft['lat']!r}}",
            f"{{bottomright['lon']!r}}, {{bottomright['lat']!r}}",
            "flood",
            year=period,
            use_NBS_classes=chosen,
            data_dir=rasters,
            output_path=path,
        )
        with rasterio.open(path) as grid:
            if land is None:
                area = cell_areas(grid)
                inside = rasterize(((g, 1) for g in tracts.geometry), out_shape=(grid.height, grid.width),
                                   transform=grid.transform, fill=0, dtype="uint8").astype(bool)
                land = inside & ~water_on(grid, water)
                land_km2 = float(area[land].sum())
            depth = depth_of(grid)
        rows.append({{
            "period": period,
            "scenario_name": name,
            "mean_depth_m": round(float((depth * area)[land].sum()) / land_km2, 4),
            "land_km2": round(land_km2, 3),
        }})
return pd.DataFrame(rows)
'''

TRACT_DEPTH = f'''# Tract depth: each tract's average flood depth for the mapped period, over
# its land (the water itself left out, dry land as 0 m), as polygons for a
# choropleth, with the tract's SVI percentile for the scatter against it: the
# riverside tracts. input_0 is this scenario's Flood Projection (its first
# item the depth for the mapped period). The riverside tracts are Harmonize's
# computed dataset, the water NHD's waterways.
import geopandas as gpd
import numpy as np
from rasterio.features import rasterize
{_GRID}

grid = input_0[0]
tracts = gpd.read_file(curio_computed_path("riverside-tracts"))
water = curio_load_data("{WATERWAYS}").to_crs("EPSG:4326")
depth = depth_of(grid)
area = cell_areas(grid)
# Each cell's tract, 1 to the number of tracts, 0 outside every tract.
tract_of = rasterize(((g, i + 1) for i, g in enumerate(tracts.geometry)), out_shape=(grid.height, grid.width),
                     transform=grid.transform, fill=0, dtype="int32")
land = (tract_of > 0) & ~water_on(grid, water)

# Area-weighted mean depth of each tract's land; no value for a tract with none.
weighted = np.bincount(tract_of[land], weights=(depth * area)[land], minlength=len(tracts) + 1)
land_km2 = np.bincount(tract_of[land], weights=area[land], minlength=len(tracts) + 1)
mean = np.full(len(tracts) + 1, np.nan)
mean[land_km2 > 0] = weighted[land_km2 > 0] / land_km2[land_km2 > 0]

result = tracts[["tract_fips", "tract", "svi", "tract_group", "geometry"]].copy()
result["mean_depth_m"] = mean[1:].round(3)
return result[result["mean_depth_m"].notna()].reset_index(drop=True)
'''

DEPTH_ON_RIVERSIDE = '''# The mapped depth only on the riverside tracts: no data elsewhere, so the
# depth map shows those tracts alone. input_0 is this scenario's Flood
# Projection (its first item the depth for the mapped period); the riverside
# tracts are Harmonize's computed dataset.
import os

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.features import rasterize

depth = input_0[0]
tracts = gpd.read_file(curio_computed_path("riverside-tracts"))
inside = rasterize(((g, 1) for g in tracts.geometry), out_shape=(depth.height, depth.width),
                   transform=depth.transform, fill=0, dtype="uint8").astype(bool)
# SCOUT's no-data cells and the cells outside those tracts: no value.
cells = depth.read(1, masked=True).astype("float64").filled(np.nan).astype("float32")
cells[~inside] = np.nan
# Named after this scenario's depth (SCOUT's flood-<hash>.tif): every node's
# output files share one folder, so a fixed name would be overwritten by the
# other scenario's.
path = curio_output_file("riverside_" + os.path.basename(depth.name))
with rasterio.open(path, "w", **{**depth.profile, "dtype": "float32", "nodata": np.nan}) as out:
    out.write(cells, 1)
return rasterio.open(path)
'''

DIFFERENCE = '''# The size of the change in depth from No NbS (input_0) to All NbS (input_1),
# cell by cell, for the period both maps draw: 0 where they agree. Each input
# is its scenario's depth on the riverside tracts, no data elsewhere.
return curio_raster_calculate("subtract", [input_1, input_0], absolute=True)
'''

TRACT_BORDERS = '''# Tract borders: each riverside tract's outline as a band WIDTH_M wide, for the
# maps to draw over the depth in one strong color. Autark draws a line 3 m
# wide, under a pixel on a map of the whole grid, and a polygon's fill with its
# outline, which would tint the depth under it. The riverside tracts are
# Harmonize's computed dataset.
import geopandas as gpd

WIDTH_M = 60

tracts = gpd.read_file(curio_computed_path("riverside-tracts"))
borders = tracts[["tract_fips", "tract", "tract_group", "geometry"]].copy()
metres = borders.estimate_utm_crs()
borders["geometry"] = borders.to_crs(metres).boundary.buffer(WIDTH_M / 2).to_crs(borders.crs)
return borders.reset_index(drop=True)
'''

TRACT_DEPTH_CHANGE = '''# Tract depth change: how much All NbS lowers each riverside tract's average
# depth, No NbS's minus All NbS's, for the period both maps draw. input_0 is
# the No NbS tract depths, input_1 the All NbS ones.
none, all_ = input_0, input_1
result = none.rename(columns={"mean_depth_m": "depth_no_nbs_m"})
result = result.merge(all_[["tract_fips", "mean_depth_m"]].rename(columns={"mean_depth_m": "depth_all_nbs_m"}),
                      on="tract_fips")
result["lowered_m"] = (result["depth_no_nbs_m"] - result["depth_all_nbs_m"]).round(3)
return result
'''


#: Both scenarios' depth maps color the same depth alike: over 0 to 11 m, past
#: SCOUT's deepest cell (10.67 m), whatever each raster's own range.
DEPTH_RANGE_M = [0, 11]
#: The tracts' average depths share one scale too: 0 to 5 m, past the deepest
#: tract average in SCOUT's own rasters (4.5 m, 2080 - 2100 with no NbS).
TRACT_DEPTH_RANGE_M = [0, 5]
#: The riverside tracts' borders over a map, in one strong color (their one
#: category, "tract_group"), with no legend of their own.
BORDERS_LAYER = {"dataRef": "[!! input_1 !!]", "getFnv": "tract_group", "colorMapInterpolator": "schemeSet1",
                 "legend": False}


def map_grammar(raster_title: str) -> str:
    # The depth first, then the tracts' borders over it.
    return json.dumps({"map": {"layerRefs": [
        {"dataRef": "[!! input_0 !!]", "getFnv": "band_1", "colorMapInterpolator": "interpolateBlues",
         "colorMapRange": DEPTH_RANGE_M, "legendTitle": raster_title},
        BORDERS_LAYER,
    ]}}, indent=2)


# Each tract colored by its average depth, on one scale in both scenarios; its
# outline is its own.
TRACT_DEPTH_MAP = json.dumps({"map": {"layerRefs": [
    {"dataRef": "[!! input_0 !!]", "getFnv": "mean_depth_m", "colorMapInterpolator": "interpolateBlues",
     "colorMapRange": TRACT_DEPTH_RANGE_M, "legendTitle": "Average flood depth per tract (m)"},
]}}, indent=2)


# The tracts coloured by their vulnerability: the same in both scenarios, so one map.
SVI_MAP = json.dumps({"map": {"layerRefs": [
    {"dataRef": "[!! input_0 !!]", "getFnv": "svi", "colorMapInterpolator": "interpolateReds",
     "legendTitle": "Social vulnerability (SVI percentile)"},
]}}, indent=2)


# The change in depth on the riverside tracts, their borders over it.
DIFFERENCE_MAP = json.dumps({"map": {"layerRefs": [
    {"dataRef": "[!! input_0 !!]", "getFnv": "band_1", "colorMapInterpolator": "interpolateBlues",
     "legendTitle": "Flood depth change (m)"},
    BORDERS_LAYER,
]}}, indent=2)


# Each riverside tract colored by how much All NbS lowers its average depth.
TRACT_CHANGE_MAP = json.dumps({"map": {"layerRefs": [
    {"dataRef": "[!! input_0 !!]", "getFnv": "lowered_m", "colorMapInterpolator": "interpolateBlues",
     "legendTitle": "Average depth lowered by NbS (m)"},
]}}, indent=2)


# ── charts ───────────────────────────────────────────────────────────────────

SCENARIO_COLOR = {"field": "scenario_name", "type": "nominal", "title": "Scenario"}
TRACT_SHORT = {"calculate": "replace(replace(datum.tract, /, (Scott|Rock Island|Henry) County.*$/, ''), "
                            "'Census Tract ', 'Tract ')", "as": "tract_short"}


def chart_period_depth() -> dict:
    """Average flood depth per period, with and without NbS, and how much NbS
    lowers it."""
    none, all_ = (name for _, name, _, _ in SCENARIOS)
    names = [name for _, name, _, _ in SCENARIOS]
    # The rows name their scenario themselves (one node runs both), so the
    # scenarios' order and colors are set here.
    color = {**SCENARIO_COLOR, "scale": {"domain": names, "range": [c for _, _, c, _ in SCENARIOS]}}
    encoding = {
        "x": {"field": "period", "type": "nominal", "title": None, "axis": {"labelAngle": 0}},
        "xOffset": {"field": "scenario_name", "type": "nominal", "sort": names},
        "y": {"field": "mean_depth_m", "type": "quantitative", "title": "Average flood depth (m)"},
    }
    return {
        "title": {"text": "Average flood depth, with and without NbS",
                  "subtitle": f"Land of the riverside tracts. Label: how much {all_} lowers it."},
        "width": 440, "height": 280,
        "transform": [
            {"calculate": f"datum.scenario_name == '{none}' ? datum.mean_depth_m : 0", "as": "none_m"},
            {"joinaggregate": [{"op": "sum", "field": "none_m", "as": "none_m"}], "groupby": ["period"]},
            {"calculate": "datum.none_m - datum.mean_depth_m", "as": "lowered_m"},
            {"calculate": f"datum.scenario_name == '{all_}' && datum.none_m > 0 ? "
                          "'−' + format(datum.lowered_m, '.2f') + ' m (−' + "
                          "format(datum.lowered_m / datum.none_m, '.0%') + ')' : ''", "as": "less"},
        ],
        "layer": [
            {"mark": {"type": "bar"},
             "encoding": {**encoding, "color": color,
                          "tooltip": [{"field": "period", "title": "Period"},
                                      {"field": "scenario_name", "title": "Scenario"},
                                      {"field": "mean_depth_m", "title": "Average depth (m)", "format": ".2f"},
                                      {"field": "lowered_m", "title": f"Lower than {none} (m)", "format": ".2f"}]}},
            {"mark": {"type": "text", "dy": -7, "fontWeight": "bold", "fontSize": 11},
             "encoding": {**encoding, "text": {"field": "less"}}},
        ],
    }


def chart_svi_depth() -> dict:
    """Each tract's SVI against its average flood depth, a dumbbell per tract:
    its No NbS and All NbS depths joined by a line, so what NbS changes in
    each tract reads at its vulnerability."""
    none, all_ = (name for _, name, _, _ in SCENARIOS)
    x = {"field": "svi", "type": "quantitative", "title": "Social vulnerability (SVI percentile)",
         "scale": {"domain": [0, 1]}}
    y = {"field": "mean_depth_m", "type": "quantitative", "title": "Average flood depth over the tract's land (m)"}
    hover = {"name": "hover", "select": {"type": "point", "fields": ["tract_fips"], "on": "pointerover",
                                          "clear": "pointerout"}}
    return {
        "title": {"text": "Social vulnerability against average flood depth",
                  "subtitle": f"Each riverside tract: its depth with {none} and {all_}, joined."},
        "width": 520, "height": 320,
        "transform": [{"filter": "isValid(datum.svi) && isValid(datum.mean_depth_m)"}, TRACT_SHORT],
        "layer": [
            {"transform": [{"pivot": "scenario_name", "value": "mean_depth_m",
                            "groupby": ["tract_fips", "tract_short", "svi"]},
                           {"calculate": f"datum['{none}'] - datum['{all_}']", "as": "lowered"}],
             "params": [hover],
             "mark": {"type": "rule", "strokeWidth": 2},
             "encoding": {
                 "x": x, "y": {"field": none, "type": "quantitative"}, "y2": {"field": all_},
                 "color": {"condition": {"param": "hover", "empty": False, "value": "#333"}, "value": "#bbb"},
                 "tooltip": [{"field": "tract_short", "title": "Tract"},
                             {"field": "svi", "title": "SVI percentile", "format": ".2f"},
                             {"field": none, "title": f"Average depth, {none} (m)", "format": ".2f"},
                             {"field": all_, "title": f"Average depth, {all_} (m)", "format": ".2f"},
                             {"field": "lowered", "title": "Lowered by NbS (m)", "format": ".2f"}]}},
            {"mark": {"type": "circle", "size": 70, "opacity": 0.9, "stroke": "#fff", "strokeWidth": 0.5},
             "encoding": {
                 "x": x, "y": y, "color": SCENARIO_COLOR,
                 "tooltip": [{"field": "tract_short", "title": "Tract"},
                             {"field": "scenario_name", "title": "Scenario"},
                             {"field": "svi", "title": "SVI percentile", "format": ".2f"},
                             {"field": "mean_depth_m", "title": "Average depth (m)", "format": ".2f"}]}},
        ],
    }


#: key, title, goal, spec, what it reads ("period-depth": both scenarios'
#: average depth by period; "tract-depth": both scenarios' tract depths).
CHARTS = [
    ("period-depth", "Average flood depth, with and without NbS",
     "Compare the average flood depth of each compared period, with and without NbS, and how much NbS lowers it.",
     chart_period_depth, "period-depth"),
    ("svi-depth", "Social vulnerability against average flood depth",
     "Show each tract's social vulnerability against its average flood depth with and without NbS, the two joined "
     "per tract, so what NbS changes reads at each tract's vulnerability.",
     chart_svi_depth, "tract-depth"),
]


# ── the dataflow ─────────────────────────────────────────────────────────────

def parameter(key, x, y, title, goal, widget, pinned=None) -> dict:
    extra = {}
    if pinned:
        extra = {"dashboardPinned": True, "dashboardControlsOnly": True, **pinned}
    return node(key, "curio.builtin/parameter", x, y, title, goal, "", {"widgets": [widget]}, **extra)


def build() -> dict:
    map_period = parameter(
        "param/map-period", 100, 190, "Map period",
        "The projection period both scenarios' Flood Projections map, as FloodScenarios shares its period.",
        {"name": "timeline", "type": "choice", "label": "Map period", "default": PERIODS[0],
         "options": {"choices": list(PERIODS), "display": "radio"}},
        pinned={"dashboardWidth": 420, "dashboardHeight": 150},
    )
    period_depth = node(
        "compare/period-depth", "scout.flood/flood-projection", 650, 2650, "Average depth by period",
        "For each period ticked in its Projection periods widget, run SCOUT's flood projection with no nature-based solution "
        "and with all four, and average each depth over the riverside tracts' land, weighted by area, the rivers, "
        "lakes and reservoirs left out and dry land as 0 m. Return one row per period and scenario.",
        PERIOD_DEPTH,
        {"widgets": [{"name": "periods", "type": "checkbox-group", "label": "Projection periods",
                      "default": list(PERIODS), "options": {"choices": list(PERIODS)}}]},
        dashboardPinned=True, dashboardControlsOnly=True, dashboardWidth=420, dashboardHeight=150,
    )
    load_tracts = node("load/tracts", "curio.builtin/data-loading", 100, 700, "SVI census tracts",
                       "Load the census tracts SCOUT's flood grid meets, with CDC's Social Vulnerability Index.",
                       LOAD_TRACTS)
    harmonize = node(
        "harmonize", "curio.builtin/computation-analysis", 650, 850, "Harmonize tracts and waterways",
        "Harmonize CDC's SVI tracts and keep the riverside ones: rename CDC's columns, read -999 as missing, "
        "keep the tract's FIPS code as text, and keep the tracts the Mississippi's channel (NHD's stream and river "
        "areas, FTYPE 460, loaded with curio_load_data) touches that have an SVI percentile. Save them as the "
        "computed dataset riverside-tracts, which the depth nodes read, and return them, in EPSG:4326, for the maps.",
        HARMONIZE,
    )
    tract_borders = node("tract-borders", "curio.builtin/computation-analysis", 1200, 1150, "Tract borders",
                         "Read the riverside tracts Harmonize saved and turn each outline into a band 60 m wide, for "
                         "the maps to draw over the depth and the waterways.", TRACT_BORDERS)
    svi_map = node("svi-map", "curio.builtin/autk-grammar", 2350, 1000, "Social vulnerability map",
                   "Map the riverside tracts, coloured by their social vulnerability (SVI percentile).",
                   SVI_MAP,
                   dashboardPinned=True, dashboardWidth=470, dashboardHeight=380)
    nodes = [map_period, period_depth, load_tracts, harmonize, tract_borders, svi_map]
    edges = [edge(load_tracts, harmonize, 0), edge(harmonize, svi_map, 0)]
    members, floods, tract_depths, riverside_depths = {}, [], [], []
    for index, (key, name, color, chosen) in enumerate(SCENARIOS):
        base = 0 if index == 0 else 1300
        flood = node(
            f"{key}/flood", "scout.flood/flood-projection", 650, base, f"Flood Projection - {name}",
            f"Project the flood depth {'with no nature-based solution' if not chosen else 'with all four kinds of nature-based solution'} "
            f"in place, for the Map period, on SCOUT's whole grid: the scout.flood package's own code.",
            FLOOD_PROJECTION,
            {"widgets": [{**copy.deepcopy(w), **({"value": list(chosen)} if w["name"] == "use_NBS_classes" else {})}
                         for w in FLOOD_WIDGETS]},
            dashboardPinned=True, dashboardControlsOnly=True, dashboardWidth=460, dashboardHeight=330,
        )
        depth_on_riverside = node(
            f"{key}/depth-on-riverside", "curio.builtin/computation-analysis", 1200, base + (400 if index == 0 else 600),
            f"Depth on riverside tracts - {name}",
            f"Keep the mapped period's flood depth only on the riverside tracts, no data elsewhere, {name}.",
            DEPTH_ON_RIVERSIDE,
        )
        flood_map = node(
            f"{key}/map", "curio.builtin/autk-grammar", 1750, base + (-450 if index == 0 else 450),
            f"Flood depth map - {name}",
            f"Map the flood depth for the mapped period on the riverside tracts, the tracts' borders over "
            f"it, {name}.",
            map_grammar("Flood depth (m)"),
            dashboardPinned=True, dashboardWidth=470, dashboardHeight=380,
        )
        tract_depth = node(
            f"{key}/tract-depth", "curio.builtin/computation-analysis", 2350, 1500 + 450 * index,
            f"Tract depth - {name}",
            f"Average the flood depth over each tract's land for the mapped period, water left out and dry land as "
            f"0 m, for the riverside tracts. Return them as polygons with their SVI percentile and average depth, "
            f"{name}.",
            TRACT_DEPTH,
        )
        tract_depth_map = node(
            f"{key}/tract-depth-map", "curio.builtin/autk-grammar", 2900, 1000 + 450 * index,
            f"Average depth per tract - {name}",
            f"Map the average flood depth of each riverside tract, for the mapped period, {name}.",
            TRACT_DEPTH_MAP,
            dashboardPinned=True, dashboardWidth=470, dashboardHeight=380,
        )
        nodes += [flood, depth_on_riverside, flood_map, tract_depth, tract_depth_map]
        edges += [
            edge(flood, depth_on_riverside, 0),
            edge(depth_on_riverside, flood_map, 0), edge(tract_borders, flood_map, 1),
            edge(flood, tract_depth, 0),
            edge(tract_depth, tract_depth_map, 0),
        ]
        members[key] = [n["id"] for n in (flood, depth_on_riverside, flood_map, tract_depth, tract_depth_map)]
        floods.append(flood)
        tract_depths.append(tract_depth)
        riverside_depths.append(depth_on_riverside)


    difference = node("compare/difference", "curio.builtin/computation-analysis", 2350, 450,
                      "Flood depth change",
                      "Take the absolute change in flood depth from No NbS to All NbS on the riverside tracts.",
                      DIFFERENCE)
    difference_map = node("compare/difference-map", "curio.builtin/autk-grammar", 2900, 450,
                          "Flood depth change map",
                          "Map how much the flood depth changes on the riverside tracts with every nature-based "
                          "solution in place, the tracts' borders over it.",
                          DIFFERENCE_MAP, dashboardPinned=True, dashboardWidth=470, dashboardHeight=380)
    tract_change = node("compare/tract-depth-change", "curio.builtin/computation-analysis", 2350, 2400,
                        "Tract depth change",
                        "For each riverside tract, take how much All NbS lowers its average flood depth: No NbS's "
                        "average depth minus All NbS's.",
                        TRACT_DEPTH_CHANGE)
    tract_change_map = node("compare/tract-depth-change-map", "curio.builtin/autk-grammar", 2900, 1900,
                            "Average depth change per tract",
                            "Map how much All NbS lowers each riverside tract's average flood depth.",
                            TRACT_CHANGE_MAP, dashboardPinned=True, dashboardWidth=470, dashboardHeight=380)
    nodes += [difference, difference_map, tract_change, tract_change_map]
    edges += [edge(riverside_depths[0], difference, 0), edge(riverside_depths[1], difference, 1),
              edge(difference, difference_map, 0), edge(tract_borders, difference_map, 1),
              edge(tract_depths[0], tract_change, 0), edge(tract_depths[1], tract_change, 1),
              edge(tract_change, tract_change_map, 0)]

    names = [name for _, name, _, _ in SCENARIOS]
    colors = [color for _, _, color, _ in SCENARIOS]
    keys = [key for key, _, _, _ in SCENARIOS]
    for row, (key, title, goal, spec, reads) in enumerate(CHARTS):
        # The tract depths are stacked, one input per scenario, and named from
        # __input__; the period depths are one node whose rows name their scenario.
        named = ({"$schema": VEGA_SCHEMA, **spec()} if reads == "period-depth"
                 else name_the_scenarios({"$schema": VEGA_SCHEMA, **spec()}, keys, names, colors))
        chart = node(f"chart/{key}", "curio.builtin/vis-vega", 3500, row * 800 - 200, title, goal,
                     json.dumps(named, indent=2), dashboardPinned=True)
        nodes.append(chart)
        feeds = [period_depth] if reads == "period-depth" else tract_depths
        edges += [edge(feed, chart, slot) for slot, feed in enumerate(feeds)]

    return {
        "dataflow": {
            "categories": {"complexity": ["Beginner"]},
            "nodes": nodes,
            "edges": edges,
            "scenarios": [
                {"id": key, "name": name, "color": color, "nodes": members[key]}
                for key, name, color, _ in SCENARIOS
            ],
            "packages": ["scout.flood@1"],
            "datasets": [
                {"datasetId": dataset, "dirName": f"{dataset}@1", "origin": "imported", "producerNodeId": None,
                 "consumerNodeIds": [], "installedAt": "2026-10-12T00:00:00Z"}
                for dataset in (TRACTS, WATERWAYS, FLOOD)
            ],
            "name": "FloodRisk",
            "task": "",
            "timestamp": 1791763200000,
            "provenance_id": "FloodRisk",
        }
    }


PROMPT = (
    "Measure how deep SCOUT's Quad Cities flood projection stands on the census tracts along the Mississippi, for two scenarios: one with no "
    "nature-based solutions in place and a copy of it with all of them, over SCOUT's whole flood grid, from 90.688 "
    "to 90.425 degrees west and 41.415 to 41.624 degrees north. A shared setting holds the period the maps show, "
    "2020 to 2050 by default. Load the census tracts the grid "
    "meets with CDC's Social Vulnerability Index and the grid's rivers, lakes and reservoirs from USGS's National "
    "Hydrography Dataset, two datasets in the Data Catalog, and harmonize the tracts: give CDC's columns "
    "readable names with its missing-value code as missing, and keep the riverside tracts, those the Mississippi's "
    "channel touches, with an SVI percentile; map the "
    "riverside tracts, coloured by their vulnerability, on an Autark map. In each "
    "scenario, run SCOUT's flood projection for the map period, a setting both scenarios share; and, for the "
    "riverside tracts, draw the mapped period's depth on those "
    "tracts alone, the tracts' borders over it, on an Autark map, each tract's average depth over its land, on one 0 "
    "to 5 metre scale in both, on another. In one more node, run the flood projection for every period ticked "
    "in its own setting, all three by default, "
    "with no solutions and with all of them, and average each depth over all the riverside tracts' land, leaving "
    "the water itself out. Then map the absolute change in depth between the scenarios on the riverside "
    "tracts, the tracts' borders over it, and how much the solutions lower each tract's average depth, and "
    "compare them in "
    "two Vega-Lite charts: the average depth per period with and without the solutions and how much they lower it, "
    "and each tract's social vulnerability against its average depth, its depths with and without the solutions "
    "joined. SCOUT's flood projection is not part of the standard node set, "
    "so whatever provides it needs installing first."
)

#: (node title, words the content must mention, the output it must give).
INTENTS = [
    ("Harmonize tracts and waterways", ["tract", "water"], None),
    ("Flood Projection - No NbS", ["flood"], None),
    ("Flood Projection - All NbS", ["flood"], None),
    ("Average depth by period", ["depth", "period"], "dataframe"),
    ("Tract depth - No NbS", ["depth", "tract"], "geodataframe"),
    ("Tract depth - All NbS", ["depth", "tract"], "geodataframe"),
    ("Flood depth change", ["flood"], "raster"),
    ("Tract depth change", ["depth", "tract"], "geodataframe"),
]


def write_fixture() -> None:
    spec = importlib.util.spec_from_file_location("skeleton", REPO / "scripts" / "example_fixture_skeleton.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    from utk_curio.backend.app.agents.evaluation.canonical import canonical_graph_from_spec
    from utk_curio.backend.app.agents.evaluation.dependencies import referenced_sources

    templates = module.template_index()
    drafted = module.skeleton(TARGET, templates)
    example = json.loads(TARGET.read_text())
    graph = canonical_graph_from_spec(example, templates=templates,
                                      sources=referenced_sources(example, templates=templates))
    refs = [n["ref"] for n in drafted["expected"]["nodes"]]
    ref_of = {example["dataflow"]["nodes"][origin]["title"]: ref for ref, origin in zip(refs, graph.origins)}
    intents = []
    for title, words, kind in INTENTS:
        intents.append({"ref": ref_of[title], "mustMention": words, **({"outputKind": kind} if kind else {})})
    fixture = {
        "$schema": "https://curio.dev/schemas/example-prompt-fixture.v1.json",
        "fixtureId": "FloodRisk",
        "version": 1,
        "source": drafted["source"],
        "prompt": PROMPT,
        "context": None,
        "required": drafted["required"],
        "expected": drafted["expected"],
        "intents": intents,
        "execution": {"mode": "sandbox", "browserOnlyKinds": [], "notes": None},
        "capability": {"tier": "T1", "needs": ["package-enlist:templates"], "skip": []},
        "thresholds": {"pass": 0.9, "templates": 1.0, "topology": 0.9, "dependencies": 1.0},
        "split": "train",
        "review": {"status": "pending-owner-review", "draftedBy": "claude-opus-5-5 from the example JSON, 2026-10-13",
                   "reviewedBy": None, "reviewedAt": None},
        "consent": {
            "dataContent": "identifiers-only",
            "licence": "MIT (this repository)",
            "sourceLicences": [
                {"datasetId": TRACTS, "licence": "Public domain"},
                {"datasetId": WATERWAYS, "licence": "Public domain"},
                {"datasetId": FLOOD, "licence": "to be confirmed"},
            ],
            "notes": "The prompt, the expected graph and the plan target are authored in this repository; the export "
                     "carries the datasets' identifiers only. The tracts are CDC/ATSDR's and the waterways USGS's "
                     "(both public domain), the flood rasters SCOUT's (urban-toolkit/scout), used with the permission "
                     "of its authors; their licence is to be confirmed.",
        },
        "notes": "A shared context (the map period), two loaders, each a dataset dragged from "
                 "the Data Catalog, and a Harmonize node that saves the riverside tracts as a computed dataset "
                 "(curio_save_file), which the depth nodes read with curio_computed_path, feed two scenarios. Each runs the package's Flood Projection "
                 "for the map period, then an Autark map of the depth with the tracts' borders over it; one Autark "
                 "map shows the tracts' vulnerability for both. A Python node takes the absolute change in depth "
                 "(curio_raster_calculate) for an Autark map; one Flood Projection node runs every compared period "
                 "for both scenarios for a bar chart, and the scatter reads the tract depths stacked (the dataset "
                 "inputs) and names each circle's scenario from __input__.",
    }
    FIXTURE.write_text(json.dumps(fixture, indent=2) + "\n")


#: What the canvas sets on a node and a save writes: where it stands, its
#: size, whether it is collapsed, and whether it shows its controls alone.
CANVAS_KEYS = ("x", "y", "width", "height", "minimized", "controlsOnly", "controlsOnlyWidth",
               "controlsOnlyHeight", "saveOutputDataset")


def keep_canvas(flow: dict) -> dict:
    """Keep the layout arranged on the canvas and saved into the shipped file:
    each node's canvas keys, and each scenario's upstream and downstream (a
    save stores them). A node the file does not have keeps its own place."""
    if not TARGET.exists():
        return flow
    shipped = json.loads(TARGET.read_text())["dataflow"]
    old = {n["id"]: n for n in shipped.get("nodes") or []}
    for n in flow["dataflow"]["nodes"]:
        for key in CANVAS_KEYS:
            if key in old.get(n["id"], {}):
                n[key] = old[n["id"]][key]
    old_scenarios = {s["id"]: s for s in shipped.get("scenarios") or []}
    for scenario in flow["dataflow"]["scenarios"]:
        for key in ("upstream", "downstream"):
            if key in old_scenarios.get(scenario["id"], {}):
                scenario[key] = old_scenarios[scenario["id"]][key]
    return flow


def main() -> int:
    TARGET.write_text(json.dumps(keep_canvas(build()), indent=2) + "\n")
    write_fixture()
    print(f"wrote {TARGET.relative_to(REPO)} and {FIXTURE.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
