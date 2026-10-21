#!/usr/bin/env python3
"""Write the chicago-loop-layers example: one Autark map of downtown Chicago with
a layer of every kind an Autark map draws, for an Interaction node to edit.

The data is one bundle, ``data.curio.chicago-loop-layers`` (built by
``scripts/build_chicago_loop_layers_dataset.py``), loaded part by part:

- polygons: census tracts with CDC/ATSDR's Social Vulnerability Index, Overture
  buildings (extruded by height), OpenStreetMap parks and water;
- lines: OpenStreetMap roads, the CTA 'L' rail lines;
- points: OpenStreetMap trees, the CTA 'L' stations.

Each loader marks its frame with the Autark layer type it is (``buildings``,
``parks``, ``water``, ``roads``, ``polygons``, ``polylines``, ``points``), so the
map draws each the way Autark draws that kind of layer. The tracts are the
map's first input: Autark clips every later layer to the first polygon layer
it loads, and the tracts cover the whole area.

    python scripts/build_example_chicago_loop_layers.py

The eight loaders feed both the map, one per circle, and an Interaction
node, on the same circles, so a layer has one name in both (input_0 ...
input_7). An interaction edge links the Interaction node and the map both
ways, as two Autark views are linked: a pick on the map reaches the node, the
editing happens on the map, and the map draws, and hands on, its layers with
the node's edits. Every layer has
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
LOOP_MAP = {
    "map": {
        "layerRefs": [
            {"dataRef": "[!! input_0 !!]", "isColorMap": True, "getFnv": "RPL_THEMES",
             "getFnvType": "quantitative", "colorMapInterpolator": "interpolateOrRd",
             "colorMapRange": [0, 1], "title": "Social vulnerability (SVI percentile)",
             "opacity": 0.55, "isPick": True},
            {"dataRef": "[!! input_3 !!]"},
            {"dataRef": "[!! input_2 !!]"},
            {"dataRef": "[!! input_4 !!]"},
            {"dataRef": "[!! input_5 !!]", "isColorMap": True, "getFnv": "legend",
             "getFnvType": "categorical", "colorMapInterpolator": "schemeTableau10",
             "title": "CTA 'L' line"},
            {"dataRef": "[!! input_1 !!]", "isColorMap": True, "getFnv": "height",
             "getFnvType": "quantitative", "colorMapInterpolator": "interpolateViridis",
             "colorMapRange": [0, 250], "title": "Building height (m)", "isPick": True},
            {"dataRef": "[!! input_6 !!]"},
            {"dataRef": "[!! input_7 !!]", "isColorMap": True, "getFnv": "ada",
             "getFnvType": "categorical", "colorMapInterpolator": "schemeSet1",
             "title": "CTA station", "isPick": True},
        ]
    }
}
#: The Interaction node's code with no edits yet, fed by the eight loaders
#: (``editFeaturesCode(undefined, 8)``).
NO_EDITS = (
    "# Edit Features writes this code from its edit list: each edit, in the\n"
    "# order it was made, on the features whose key is one of its ids. It is\n"
    "# written again when the list changes.\n"
    "return curio_edit_features([" + ", ".join(f"input_{k}" for k in range(8)) + "], [], by_input=True)\n"
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
    ("loop_map", "curio.builtin/autk-grammar", "Downtown Chicago layers",
     "Draw every layer on one map: tracts by social vulnerability, buildings by height, parks, water, roads, "
     "the 'L', trees and stations.", json.dumps(LOOP_MAP, indent=2), 560, 200),
    ("interaction", "curio.builtin/edit-features", "Edit the map's layers",
     "Read the map's layers, by the geometry of their features, and add, reshape, move, change or remove their "
     "features on the map, add properties, or make a new layer.", NO_EDITS, 1600, 200),
]
#: source key -> (target key, input index)
LAYER_KEYS = ["tracts", "buildings", "parks", "water", "roads", "cta_lines", "trees", "cta_stations"]
EDGES = (
    [(key, "loop_map", k) for k, key in enumerate(LAYER_KEYS)]
    + [(key, "interaction", k) for k, key in enumerate(LAYER_KEYS)]
)
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
                 "consumerNodeIds": [], "installedAt": STAMP} for d in (LAYERS,)]
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
