#!/usr/bin/env python3
"""Build the Data Catalog dataset ``data.osm.chicago-downtown-roads``.

The roads of downtown Chicago, the Loop with the West Loop and the South Loop,
from OpenStreetMap: longitude -87.662 to -87.613, latitude 41.859 to 41.898,
the box SCOUT's weather routing example routes in. The WeatherRouting test
dataflow loads them with ``curio_load_data`` and hands them to its Weather
Routing node and its Autark map.

HOW
---
1. Overpass's ``highway`` ways in the box, with the Chicago boundary relation
   autk-db's OSM loader clips to, written to a temporary ``.pbf``
   (``scripts/build_example_pbfs.py``'s helpers).
2. Each road cut at the box, its points inside and the one just outside next
   to them (``crop_roads``), as SCOUT's road graph is cut: Overpass hands on a
   road that crosses the box whole.
3. The ``.pbf`` loaded by autk-db's OSM loader in Node, as an Autark node's
   ``data`` section loads one (``run_js_script``, as the canvas runs it), and
   its roads layer picked as a Weather Routing node's layer chip picks it
   (``curio_layer``): the roads are what Autark makes of OpenStreetMap.
4. The roads' lines and the tags routing and the map read, in EPSG:4326, to
   ``datasets/data.osm.chicago-downtown-roads@1/data/roads.parquet`` with its
   manifest.

This is AUTHORING-ONLY tooling. It needs pyosmium besides Curio's environment,
network access to Overpass, and the repository's Node packages (``npm
install`` at the repository root installs the autk-db build Curio pins)::

    conda run -n curio pip install osmium     # one-time
    conda run -n curio python scripts/build_chicago_downtown_roads.py

The roads are OpenStreetMap data, (c) OpenStreetMap contributors, ODbL 1.0.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DATASET_ID = "data.osm.chicago-downtown-roads"
OUT_DIR = REPO_ROOT / "datasets" / f"{DATASET_ID}@1"
DATA_FILE = "data/roads.parquet"
#: South, west, north, east.
BOX = (41.859, -87.662, 41.898, -87.613)
#: The boundary relation autk-db's OSM loader clips the layers to.
BOUNDARY = "Chicago"
#: The layer autk-db names its roads, and the tags kept: what routing reads
#: (highway, oneway, maxspeed) and the street's name.
ROADS_LAYER = "table_osm_roads"
TAGS = ["highway", "oneway", "maxspeed", "name"]


def autk_db_load(pbf: Path) -> str:
    """autk-db's OSM load of *pbf*, as an Autark node's compiled data section
    runs it (``adapters/node/autkDataCompile.ts``), handing on its layers."""
    options = {
        "pbfFileUrl": "roads.osm.pbf",
        "queryArea": {"geocodeArea": BOUNDARY, "areas": [BOUNDARY]},
        "outputTableName": "table_osm",
        "autoLoadLayers": {"layers": ["roads"]},
    }
    return (
        "import { AutkDb } from '@urban-toolkit/autk-db';\n"
        "const fs = await import('node:fs');\n"
        "const __fetch = globalThis.fetch;\n"
        "globalThis.fetch = async (url, opts) => String(url).endsWith('.pbf')\n"
        f"  ? new Response(fs.readFileSync({json.dumps(str(pbf))}))\n"
        "  : __fetch(url, opts);\n"
        "const db = new AutkDb();\n"
        "await db.init();\n"
        f"await db.loadOsm({json.dumps(options)});\n"
        "const out = [];\n"
        "for (const t of db.getLayersMetadata()) {\n"
        "  const geojson = await db.getLayer(t.name);\n"
        "  geojson.crs = { type: 'name', properties: { name: 'urn:ogc:def:crs:EPSG::3395' } };\n"
        "  out.push({ name: t.name, type: t.type, geojson });\n"
        "}\n"
        "return out;\n"
    )


def schema_of(roads) -> dict:
    fields = [{"name": c, "type": "STRING", "nullable": bool(roads[c].isna().any())} for c in roads.columns
              if c != "geometry"]
    fields.append({"name": "geometry", "type": "GEOMETRY", "nullable": False})
    kinds = sorted(set(roads.geometry.geom_type))
    return {"fields": fields, "geometryType": kinds[0] if len(kinds) == 1 else "Geometry", "crs": "EPSG:4326"}


def manifest(roads) -> dict:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00Z")
    s, w, n, e = BOX
    return {
        "id": DATASET_ID,
        "name": "Chicago downtown roads",
        "version": "1.0.0",
        "format": "parquet",
        "description": (
            "The roads of downtown Chicago, the Loop with the West Loop and the South Loop, from "
            f"OpenStreetMap: longitude {w} to {e}, latitude {s} to {n}. One line per road, cut at the "
            "box, with its highway class, oneway, maxspeed and name, as Autark's OpenStreetMap loader "
            "reads them. Built by scripts/build_chicago_downtown_roads.py."
        ),
        "publisher": "OpenStreetMap contributors",
        "license": "ODbL-1.0",
        "tags": ["roads", "openstreetmap", "chicago", "parquet"],
        "dataFile": DATA_FILE,
        "compatibility": {"major": 1},
        "sourceLabel": "© OpenStreetMap contributors (ODbL)",
        "createdAt": today,
        "updatedAt": today,
        "rowCount": len(roads),
        "featureCount": None,
        "schema": schema_of(roads),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--node-modules", help="a node_modules folder holding Curio's autk-db build")
    args = parser.parse_args()
    sys.path.insert(0, str(REPO_ROOT))
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import build_example_pbfs as pbfs
    from utk_curio.sandbox.app import worker
    from utk_curio.sandbox.util.input_layers import curio_layer

    if args.node_modules:
        worker.ROOT_NODE_MODULES = str(Path(args.node_modules).resolve())
    with tempfile.TemporaryDirectory() as work:
        pbf = Path(work) / "roads.osm.pbf"
        xml = pbfs.fetch_osm_xml(pbfs.overpass_query(BOX, False, [BOUNDARY], roads_only=True))
        pbfs.xml_to_pbf(xml, str(pbf))
        pbfs.crop_roads(str(pbf), BOX)
        result, _logs, errors = worker.run_js_script(autk_db_load(pbf), None, cwd=str(REPO_ROOT),
                                                     node_type="AUTK_GRAMMAR")
    payload = json.loads(result) if result else {}
    if not payload.get("success"):
        raise SystemExit(f"the load failed: {payload.get('error') or errors[-10:]}")
    layer = curio_layer(payload["value"], ROADS_LAYER, 0)
    roads = layer[[c for c in TAGS if c in layer.columns] + ["geometry"]].to_crs(4326).reset_index(drop=True)
    (OUT_DIR / "data").mkdir(parents=True, exist_ok=True)
    roads.to_parquet(OUT_DIR / DATA_FILE, index=False)
    (OUT_DIR / "manifest.json").write_text(json.dumps(manifest(roads), indent=2, ensure_ascii=False) + "\n",
                                           encoding="utf-8")
    print(f"{len(roads)} roads, columns {list(roads.columns)}, written to {OUT_DIR}")


if __name__ == "__main__":
    main()
