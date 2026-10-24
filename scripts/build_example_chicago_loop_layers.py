#!/usr/bin/env python3
"""Write the chicago-loop-layers example: one Autark map of downtown Chicago with
a layer of every kind an Autark map draws, for a Map Editor node to edit.

The layers come from two places:

- an Autark node loads OpenStreetMap's parks, water, roads and buildings from
  the examples' ``chicago_downtown.osm.pbf``, in the box it is cut at
  (``queryArea.bbox``, as chicago-rain-wind-routing loads it: the extract also
  carries the whole Chicago boundary);
- the bundle ``data.curio.chicago-loop-layers`` (built by
  ``scripts/build_chicago_loop_layers_dataset.py``) gives the rest, part by
  part: census tracts with CDC/ATSDR's Social Vulnerability Index (polygons),
  the CTA 'L' rail lines (lines), OpenStreetMap's trees and the CTA 'L'
  stations (points).

Each loader marks its frame with the Autark layer type it is (``polygons``,
``polylines``, ``points``), so the map draws each the way Autark draws that
kind of layer; the Autark node's layers carry their own types.

    python scripts/build_example_chicago_loop_layers.py

The layers go Data → Interaction → map on data edges: the five data nodes feed
the Map Editor node, one per circle (CIRCLES), and it feeds the map, handing
on every layer under its name. A loader's layer has no name of its own, so it
is named after its circle (input_0, input_2, ...); the Autark node's layers
keep their tables' names (table_osm_parks, ...). The map reads each with a
layer chip (``[!! input_0:input_2 !!]``: the layer input_2 of the map's one
input). The tracts are the first circle, so they are the first layer the map
loads: Autark clips every later layer to the first polygon layer it loads, and
the tracts cover the box but for the lake along its east edge. An
interaction edge links the Interaction
node and the map both ways, as two Autark views are linked: the editing
happens on the map, which shows the edits at once, and Commit edits hands the
edited layers to the map. The bundle's layers have a column that identifies
their features (FIPS, line_id, osm_id, station_id), and Autark's buildings
have building_id; Autark's parks, water and roads carry their OpenStreetMap
tags and no id column.

AUTHORING-ONLY tooling. The output is deterministic, so a rerun rewrites the
same file. It keeps the layout saved on the canvas (``keep_canvas``).
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
STAMP = "2026-10-22T00:00:00Z"
#: The examples' OpenStreetMap extract of downtown Chicago, and the box it is
#: cut at (west, south, east, north; ``build_example_pbfs.py``).
PBF = "docs/examples/data/chicago_downtown.osm.pbf"
BOX = [-87.662, 41.859, -87.613, 41.898]
#: The OpenStreetMap load's name: its layers are the tables <name>_<layer>.
OSM_TABLE = "table_osm"
OSM_LAYERS = ["parks", "water", "roads", "buildings"]
#: The Map Editor node's circles, in order: the node that feeds each.
CIRCLES = ["tracts", "osm", "cta_lines", "trees", "cta_stations"]


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


def layer(key: str) -> str:
    """The map's chip for a layer the Map Editor node hands on: a loader's
    layer is named after its circle on the node (input_<k>), and each of the
    Autark node's layers after its table (table_osm_parks)."""
    name = f"{OSM_TABLE}_{key}" if key in OSM_LAYERS else f"input_{CIRCLES.index(key)}"
    return f"[!! input_0:{name} !!]"


def interaction_code(circles: int) -> str:
    """The Map Editor node's code with no edits yet, fed by *circles* inputs:
    what ``editFeaturesCode(undefined, circles)`` writes (``editFeatures.ts``)."""
    return (
        "# Map Editor writes this code from its edit list: each edit, in the\n"
        "# order it was made, on the features whose key is one of its ids. It is\n"
        "# written again when the list changes.\n"
        "return curio_edit_features([" + ", ".join(f"input_{k}" for k in range(circles)) + "], [], by_input=True)\n"
    )


TRACTS = loader(
    "tracts.geojson", "polygons",
    "The census tracts that meet the area, with CDC/ATSDR's Social Vulnerability\n"
    "# Index 2020: RPL_THEMES is the overall percentile, 0 least and 1 most\n"
    "# vulnerable; CDC writes -999 where it has no value.",
    "for column in [c for c in frame.columns if c.startswith((\"RPL_\", \"E_\"))]:\n"
    "    frame[column] = frame[column].where(frame[column] != -999)\n",
)
OSM = {
    "data": [
        {
            "type": "osm",
            "pbfFileUrl": PBF,
            "queryArea": {"bbox": BOX},
            "outputTableName": OSM_TABLE,
            "autoLoadLayers": {"layers": OSM_LAYERS},
        }
    ]
}
CTA_LINES = loader(
    "cta_lines.geojson", "polylines",
    "The CTA 'L' rail lines, from the City of Chicago data portal; legend is\n"
    "# the line's code (RD Red, BL Blue, ML the Loop's shared track, ...).",
)
TREES = loader("trees.parquet", "points", "OpenStreetMap's mapped trees (natural=tree), as points.")
CTA_STATIONS = loader(
    "cta_stations.geojson", "points",
    "The CTA 'L' stations; ada is whether the station is accessible.",
    "frame[\"ada\"] = frame[\"ada\"].map({True: \"accessible\", False: \"not accessible\"}).fillna(\"unknown\")\n",
)
LOOP_MAP = {
    "map": {
        "layerRefs": [
            {"dataRef": layer("tracts"), "isColorMap": True, "getFnv": "RPL_THEMES",
             "getFnvType": "quantitative", "colorMapInterpolator": "interpolateOrRd",
             "colorMapRange": [0, 1], "title": "Social vulnerability (SVI percentile)",
             "opacity": 0.55, "isPick": True},
            # Water, parks and trees in colors of their own: Autark draws a
            # layer with none in grey, as the roads.
            {"dataRef": layer("water"), "title": "Water", "color": "#6baed6"},
            {"dataRef": layer("parks"), "title": "Parks", "color": "#74c476"},
            {"dataRef": layer("roads"), "title": "Roads"},
            {"dataRef": layer("cta_lines"), "isColorMap": True, "getFnv": "legend",
             "getFnvType": "categorical", "colorMapInterpolator": "schemeTableau10",
             "title": "CTA 'L' line"},
            {"dataRef": layer("buildings"), "isColorMap": True, "getFnv": "height",
             "getFnvType": "quantitative", "colorMapInterpolator": "interpolateViridis",
             "colorMapRange": [0, 250], "title": "Building height (m)", "isPick": True},
            {"dataRef": layer("trees"), "title": "Trees", "color": "#238b45"},
            {"dataRef": layer("cta_stations"), "isColorMap": True, "getFnv": "ada",
             "getFnvType": "categorical", "colorMapInterpolator": "schemeSet1",
             "title": "CTA station", "isPick": True},
        ]
    }
}

#: key, type, title, goal, content, x, y, and what else a node sets
NODES = [
    ("tracts", "curio.builtin/data-loading", "Census tracts (SVI)",
     "Load the census tracts that meet downtown Chicago, with CDC/ATSDR's Social Vulnerability Index 2020.",
     TRACTS, 0, 0, {}),
    # In the place of the loaders the Autark node replaces.
    ("osm", "curio.builtin/autk-grammar", "OpenStreetMap layers",
     "Load OpenStreetMap's parks, water, roads and buildings of downtown Chicago.",
     json.dumps(OSM, indent=2), 0, 358, {}),
    ("cta_lines", "curio.builtin/data-loading", "CTA 'L' lines",
     "Load the CTA 'L' rail lines of downtown Chicago.", CTA_LINES, 0, 750, {}),
    ("trees", "curio.builtin/data-loading", "Trees", "Load OpenStreetMap's mapped trees of downtown Chicago.",
     TREES, 0, 900, {}),
    ("cta_stations", "curio.builtin/data-loading", "CTA 'L' stations",
     "Load the CTA 'L' stations of downtown Chicago, accessible or not.", CTA_STATIONS, 0, 1050, {}),
    ("loop_map", "curio.builtin/autk-grammar", "Downtown Chicago layers",
     "Draw every layer on one map: tracts by social vulnerability, buildings by height, parks, water, roads, "
     "the 'L', trees and stations.", json.dumps(LOOP_MAP, indent=2), 1240, 200,
     # A map large enough to tell the layers apart.
     {"width": 960, "height": 720}),
    ("interaction", "curio.builtin/edit-features", "Edit the map's layers",
     "Read the map's layers, by the geometry of their features, and add, reshape, move, change or remove their "
     "features on the map, add properties, or make a new layer.", interaction_code(len(CIRCLES)), 560, 200,
     # Room for the layer list and the forms, beside the map.
     {"width": 560, "height": 900}),
]
#: source key, target key, input circle
EDGES = [(key, "interaction", k) for k, key in enumerate(CIRCLES)] + [("interaction", "loop_map", 0)]
#: The interaction edges, both ways: the Map Editor node and the map it edits on.
LINKS = [("interaction", "loop_map")]


def build() -> dict:
    nodes = []
    for key, typ, title, goal, content, x, y, extra in NODES:
        nodes.append({"id": nid(key), "type": typ, "x": x, "y": y, "content": content, "out": "DEFAULT",
                      "in": "DEFAULT", "goal": goal, "metadata": {"keywords": [], "packageTemplateLabel": title},
                      "title": title, **extra})
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
                 "consumerNodeIds": [], "installedAt": STAMP} for d in (LAYERS,)]
    return {"dataflow": {
        "categories": {"complexity": ["Beginner"], "city": ["Chicago"]},
        "nodes": nodes, "edges": edges, "scenarios": [], "packages": [], "datasets": datasets,
        "name": NAME, "task": "", "timestamp": 1792540800000, "provenance_id": NAME,
    }}


#: What a save on the canvas sets on a node: kept from the shipped file. A
#: shipped example opens with every node open, as the others do.
CANVAS_KEYS = ("x", "y", "width", "height")


def keep_canvas(flow: dict) -> dict:
    """Keep the layout arranged on the canvas and saved into the shipped file
    (each node's place and size). A node the file does not have keeps its own
    place."""
    if not OUT.exists():
        return flow
    old = {n["id"]: n for n in json.loads(OUT.read_text())["dataflow"].get("nodes") or []}
    for n in flow["dataflow"]["nodes"]:
        if n["id"] not in old:
            continue
        for key in CANVAS_KEYS:
            if key in old[n["id"]]:
                n[key] = old[n["id"]][key]
            else:
                n.pop(key, None)
    return flow


def main() -> None:
    OUT.write_text(json.dumps(keep_canvas(build()), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(REPO)}")


if __name__ == "__main__":
    main()
