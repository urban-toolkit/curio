#!/usr/bin/env python3
"""Write the chicago-loop-layers example: one Autark map of downtown Chicago with
a layer of every kind an Autark map draws, for an Interaction node to edit.

The data is one bundle, ``data.curio.chicago-loop-layers`` (built by
``scripts/build_chicago_loop_layers_dataset.py``), loaded part by part:

- polygons: census tracts with CDC/ATSDR's Social Vulnerability Index, Overture
  buildings (extruded by height), OpenStreetMap parks and water;
- lines: OpenStreetMap roads, the CTA 'L' rail lines;
- points: OpenStreetMap trees, the CTA 'L' stations, the Chicago Park
  District's beach weather and water sensors with their noon reading on
  2025-07-06;
- a raster: the air temperature at 2 m of SCOUT's WRF forecast for that noon
  (``data.scout.chicago-weather-2025-07-06``), on a second map with the
  sensors over it, the station's reading against the model's.

Each loader marks its frame with the Autark layer type it is (``buildings``,
``parks``, ``water``, ``roads``, ``polygons``, ``polylines``, ``points``), so the
map draws each the way Autark draws that kind of layer. The tracts are the
map's first input: Autark clips every later layer to the first polygon layer
it loads, and the tracts cover the whole area.

    python scripts/build_example_chicago_loop_layers.py

The layers go Data → Interaction → map: the nine loaders feed an Interaction
node, one per circle, and it feeds the main map, handing on every layer under
the name of its circle (input_0 ... input_8), which the map's document reads
with layer chips (``[!! input_0:input_3 !!]``: the layer input_3 of the map's
one input).
An interaction edge links the Interaction node and the map both ways, as two
Autark views are linked: the editing happens on the map, which shows the edits
at once, and Commit edits hands the edited layers to the map. Every layer has
a column that identifies its features (FIPS, id, osm_id, line_id, station_id,
name).

AUTHORING-ONLY tooling. The output is deterministic, so a rerun rewrites the
same file.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "docs" / "examples" / "dataflows" / "chicago-loop-layers.json"
NAME = "Chicago Loop layers"
NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, f"https://curio.dev/examples/{NAME}")
LAYERS = "data.curio.chicago-loop-layers"
WEATHER = "data.scout.chicago-weather-2025-07-06"
STAMP = "2026-10-20T00:00:00Z"


def nid(key: str) -> str:
    return str(uuid.uuid5(NAMESPACE, key))


def loader(part: str, layer_type: str, intro: str, extra: str = "") -> str:
    return (
        f"# {intro}\n"
        f'frame = curio_load_data("{LAYERS}", part="{part}")\n'
        f"{extra}"
        f"# Tell the Autark map what kind of layer this is, so it draws it as one.\n"
        f'frame.metadata = {{"layerType": "{layer_type}"}}\n'
        "return frame\n"
    )


TRACTS = loader(
    "tracts.geojson", "polygons",
    "The census tracts that meet the area, with CDC/ATSDR's Social Vulnerability\n"
    "# Index 2020: RPL_THEMES is the overall percentile, 0 least and 1 most\n"
    "# vulnerable; CDC writes -999 where it has no value.",
    "for column in [c for c in frame.columns if c.startswith((\"RPL_\", \"E_\"))]:\n"
    "    frame[column] = frame[column].where(frame[column] != -999)\n",
)
BUILDINGS = loader(
    "buildings.parquet", "buildings",
    "Overture Maps' buildings. Autark extrudes a buildings layer by its height\n"
    "# column, in metres: Overture's height, else 3.5 m a floor, else 10 m.",
    "frame = frame[~frame[\"is_underground\"].fillna(False).astype(bool)]\n"
    "height = frame[\"height\"].fillna(frame[\"num_floors\"] * 3.5).fillna(10.0)\n"
    "frame = frame.assign(height=height)[[\"id\", \"height\", \"num_floors\", \"class\", \"geometry\"]]\n"
    "frame = frame.reset_index(drop=True)\n",
)
PARKS = loader("parks.geojson", "parks", "OpenStreetMap's parks, playgrounds and other green space.")
WATER = loader("water.geojson", "water", "OpenStreetMap's water: the Chicago River and the lake's edge.")
ROADS = loader("roads.parquet", "roads", "OpenStreetMap's roads, with their highway class, oneway, maxspeed and name.")
CTA_LINES = loader(
    "cta_lines.geojson", "polylines",
    "The CTA 'L' rail lines, from the City of Chicago data portal; legend is\n"
    "# the line's code (RD Red, BL Blue, ML the Loop's shared track, ...).",
)
TREES = loader("trees.geojson", "points", "OpenStreetMap's mapped trees (natural=tree), as points.")
CTA_STATIONS = loader(
    "cta_stations.geojson", "points",
    "The CTA 'L' stations; ada is whether the station is accessible.",
    "frame[\"ada\"] = frame[\"ada\"].map({True: \"accessible\", False: \"not accessible\"}).fillna(\"unknown\")\n",
)
SENSORS = loader(
    "beach_sensors.geojson", "points",
    "The Chicago Park District's beach sensors in the area, each with its reading\n"
    "# at noon on 2025-07-06: the Oak Street weather station (air_temperature in\n"
    "# degrees C, humidity, wind) and the Ohio Street Beach water sensor.",
)
TEMPERATURE = f'''# The air temperature at 2 m of SCOUT's WRF forecast at noon in Chicago on
# 2025-07-06 (17:00 UTC; the file's hours are UTC from 00:00), in degrees C, on a
# regular longitude-latitude grid over the map's area: WRF's own grid is curved,
# so each cell takes the nearest WRF point.
import numpy as np
import rasterio
from rasterio.transform import from_bounds
from scipy.spatial import cKDTree

HOUR_UTC = 17
WEST, SOUTH, EAST, NORTH = -87.662, 41.859, -87.605, 41.906
CELL = 0.002

wrf = curio_load_data("{WEATHER}", part="T2.nc")
lat = wrf["XLAT"].isel(Time=HOUR_UTC).values.ravel()
lon = wrf["XLONG"].isel(Time=HOUR_UTC).values.ravel()
celsius = wrf["T2"].isel(Time=HOUR_UTC).values.ravel() - 273.15

width, height = int(round((EAST - WEST) / CELL)), int(round((NORTH - SOUTH) / CELL))
xs = WEST + (np.arange(width) + 0.5) * CELL
ys = NORTH - (np.arange(height) + 0.5) * CELL
grid_lon, grid_lat = np.meshgrid(xs, ys)
_, nearest = cKDTree(np.column_stack([lon, lat])).query(np.column_stack([grid_lon.ravel(), grid_lat.ravel()]))
cells = celsius[nearest].reshape(height, width).astype("float32")

path = curio_output_file("wrf_t2_noon_2025-07-06.tif")
profile = {{"driver": "GTiff", "width": width, "height": height, "count": 1, "dtype": "float32",
           "crs": "EPSG:4326", "transform": from_bounds(WEST, SOUTH, EAST, NORTH, width, height)}}
with rasterio.open(path, "w", **profile) as out:
    out.write(cells, 1)
return rasterio.open(path)
'''

LOOP_MAP = {
    "map": {
        "layerRefs": [
            {"dataRef": "[!! input_0:input_0 !!]", "isColorMap": True, "getFnv": "RPL_THEMES",
             "getFnvType": "quantitative", "colorMapInterpolator": "interpolateOrRd",
             "colorMapRange": [0, 1], "title": "Social vulnerability (SVI percentile)",
             "opacity": 0.55, "isPick": True},
            {"dataRef": "[!! input_0:input_3 !!]"},
            {"dataRef": "[!! input_0:input_2 !!]"},
            {"dataRef": "[!! input_0:input_4 !!]"},
            {"dataRef": "[!! input_0:input_5 !!]", "isColorMap": True, "getFnv": "legend",
             "getFnvType": "categorical", "colorMapInterpolator": "schemeTableau10",
             "title": "CTA 'L' line"},
            {"dataRef": "[!! input_0:input_1 !!]", "isColorMap": True, "getFnv": "height",
             "getFnvType": "quantitative", "colorMapInterpolator": "interpolateViridis",
             "colorMapRange": [0, 250], "title": "Building height (m)", "isPick": True},
            {"dataRef": "[!! input_0:input_6 !!]"},
            {"dataRef": "[!! input_0:input_7 !!]", "isColorMap": True, "getFnv": "ada",
             "getFnvType": "categorical", "colorMapInterpolator": "schemeSet1",
             "title": "CTA station", "isPick": True},
            {"dataRef": "[!! input_0:input_8 !!]", "isColorMap": True, "getFnv": "sensor_type",
             "getFnvType": "categorical", "colorMapInterpolator": "schemeDark2",
             "title": "Beach sensor", "isPick": True},
        ]
    }
}
TEMPERATURE_MAP = {
    "map": {
        "layerRefs": [
            {"dataRef": "[!! input_0 !!]", "isColorMap": True, "getFnv": "band_1",
             "getFnvType": "quantitative", "colorMapInterpolator": "interpolateTurbo",
             "colorMapRange": [17, 29], "title": "Air temperature at noon, WRF (°C)"},
            {"dataRef": "[!! input_1 !!]", "isColorMap": True, "getFnv": "air_temperature",
             "getFnvType": "quantitative", "colorMapInterpolator": "interpolateTurbo",
             "colorMapRange": [17, 29], "title": "Measured at noon (°C)", "isPick": True},
        ]
    }
}

#: The Interaction node's code with no edits yet, fed by the nine loaders
#: (``editFeaturesCode(undefined, 9)``).
NO_EDITS = (
    "# Edit Features writes this code from its edit list: each edit, in the\n"
    "# order it was made, on the features whose key is one of its ids. It is\n"
    "# written again when the list changes.\n"
    "return curio_edit_features([" + ", ".join(f"input_{k}" for k in range(9)) + "], [], by_input=True)\n"
)

#: key, type, title, goal, content, x, y
NODES = [
    ("tracts", "curio.builtin/data-loading", "Census tracts (SVI)",
     "Load the census tracts that meet downtown Chicago, with CDC/ATSDR's Social Vulnerability Index 2020.",
     TRACTS, 0, 0),
    ("buildings", "curio.builtin/data-loading", "Buildings",
     "Load Overture Maps' buildings of downtown Chicago, with a height for every one.", BUILDINGS, 0, 150),
    ("parks", "curio.builtin/data-loading", "Parks", "Load OpenStreetMap's parks of downtown Chicago.", PARKS, 0, 300),
    ("water", "curio.builtin/data-loading", "Water", "Load OpenStreetMap's water of downtown Chicago.", WATER, 0, 450),
    ("roads", "curio.builtin/data-loading", "Roads", "Load OpenStreetMap's roads of downtown Chicago.", ROADS, 0, 600),
    ("cta_lines", "curio.builtin/data-loading", "CTA 'L' lines",
     "Load the CTA 'L' rail lines of downtown Chicago.", CTA_LINES, 0, 750),
    ("trees", "curio.builtin/data-loading", "Trees", "Load OpenStreetMap's mapped trees of downtown Chicago.",
     TREES, 0, 900),
    ("cta_stations", "curio.builtin/data-loading", "CTA 'L' stations",
     "Load the CTA 'L' stations of downtown Chicago, accessible or not.", CTA_STATIONS, 0, 1050),
    ("sensors", "curio.builtin/data-loading", "Beach weather sensors",
     "Load the Chicago Park District's beach sensors in downtown Chicago with their noon reading on 2025-07-06.",
     SENSORS, 0, 1200),
    ("temperature", "curio.builtin/computation-analysis", "Air temperature at noon (WRF)",
     "Map SCOUT's WRF forecast of the air temperature at noon on 2025-07-06 over downtown Chicago, as a raster.",
     TEMPERATURE, 0, 1400),
    ("loop_map", "curio.builtin/autk-grammar", "Downtown Chicago layers",
     "Draw every layer on one map: tracts by social vulnerability, buildings by height, parks, water, roads, "
     "the 'L', trees, stations and the beach sensors.", json.dumps(LOOP_MAP, indent=2), 1240, 200),
    ("temperature_map", "curio.builtin/autk-grammar", "Air temperature at noon",
     "Draw the WRF air temperature at noon with the beach sensors over it, in the same colors, to compare the "
     "station's reading with the model.", json.dumps(TEMPERATURE_MAP, indent=2), 560, 1250),
    ("interaction", "curio.builtin/edit-features", "Edit the map's layers",
     "Read the map's layers, by the geometry of their features, and add, reshape, move, change or remove their "
     "features on the map, add properties, or make a new layer.", NO_EDITS, 560, 200),
]
#: source key -> (target key, input index)
EDGES = [
    ("tracts", "interaction", 0), ("buildings", "interaction", 1), ("parks", "interaction", 2),
    ("water", "interaction", 3), ("roads", "interaction", 4), ("cta_lines", "interaction", 5),
    ("trees", "interaction", 6), ("cta_stations", "interaction", 7), ("sensors", "interaction", 8),
    ("interaction", "loop_map", 0),
    ("temperature", "temperature_map", 0), ("sensors", "temperature_map", 1),
]
#: The interaction edges, both ways: the Interaction node and the map it edits on.
LINKS = [("interaction", "loop_map")]


def build() -> dict:
    nodes = []
    for key, typ, title, goal, content, x, y in NODES:
        nodes.append({"id": nid(key), "type": typ, "x": x, "y": y, "content": content, "out": "DEFAULT",
                      "in": "DEFAULT", "goal": goal, "metadata": {"keywords": [], "packageTemplateLabel": title},
                      "title": title})
        if typ == "curio.builtin/autk-grammar":
            # A map large enough to tell the layers apart.
            nodes[-1].update({"width": 960, "height": 720})
        if typ == "curio.builtin/edit-features":
            # Room for the layer list and the forms, beside the map.
            nodes[-1].update({"width": 560, "height": 900})
    edges = []
    for source, target, index in EDGES:
        handle = "in" if index == 0 else f"in_{index}"
        s, t = nid(source), nid(target)
        edges.append({"id": f"reactflow__edge-{s}out-{t}{handle}", "source": s, "target": t,
                      "sourceHandle": "out", "targetHandle": handle})
    for source, target in LINKS:
        s, t = nid(source), nid(target)
        edges.append({"id": f"reactflow__edge-{s}in/out-{t}in/out", "source": s, "target": t,
                      "sourceHandle": "in/out", "targetHandle": "in/out", "type": "Interaction"})
    datasets = [{"datasetId": d, "dirName": f"{d}@1", "origin": "imported", "producerNodeId": None,
                 "consumerNodeIds": [], "installedAt": STAMP} for d in (LAYERS, WEATHER)]
    return {"dataflow": {
        "categories": {"complexity": ["Beginner"], "city": ["Chicago"]},
        "nodes": nodes, "edges": edges, "scenarios": [], "packages": [], "datasets": datasets,
        "name": NAME, "task": "", "timestamp": 1792540800000, "provenance_id": NAME,
    }}


def main() -> None:
    OUT.write_text(json.dumps(build(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(REPO)}")


if __name__ == "__main__":
    main()
