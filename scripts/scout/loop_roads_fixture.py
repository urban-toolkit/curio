"""Write the Chicago Loop's roads layer, as an Autark node hands it to Weather Routing.

An Autark node whose `data` section loads the roads of the committed
OpenStreetMap extract `docs/examples/data/chicago_loop.osm.pbf` (`SOURCE` below)
runs in the sandbox, through autk-db in Node (`run_js_script`, as the canvas runs
it), and hands on its layer array, `[{name, type, geojson}]` in autk-db's
EPSG:3395, each FeatureCollection naming that CRS. A Weather Routing node reads
the roads layer through its layer chip, `[!! input_0:table_osm_roads !!]`,
which runs as `curio_layer` (`utk_curio/sandbox/util/input_layers.py`) and gives
it as a GeoDataFrame.

This script runs that section the same way, then `curio_layer` on its layers,
and writes the roads' lines and the tags routing reads (highway, oneway and
maxspeed) as the model.scout.weather-gnn tests' fixture
`utk_curio/backend/tests/test_packages/fixtures/scout_routing/loop_roads.parquet`,
which the node's widget tests route on. The roads are OpenStreetMap data, as the
extract is.

    python scripts/scout/loop_roads_fixture.py [--node-modules <folder>] [--out <file>]

It needs the repository's Node packages (`npm install` at the repository root
installs the autk-db release Curio pins), or `--node-modules` naming a folder
that holds that release.
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT = REPO_ROOT / "utk_curio" / "backend" / "tests" / "test_packages" / "fixtures" / "scout_routing" / "loop_roads.parquet"
#: The Autark data source the roads come from: the Loop's extract, its roads layer.
SOURCE = {
    "type": "osm",
    "pbfFileUrl": "docs/examples/data/chicago_loop.osm.pbf",
    "queryArea": {"geocodeArea": "Chicago", "areas": ["Loop"]},
    "outputTableName": "table_osm",
    "autoLoadLayers": {"layers": ["roads"]},
}
#: The layer the Weather Routing node's layer chip reads, and the tags routing reads.
ROADS_LAYER = "table_osm_roads"
ROUTING_TAGS = ["highway", "oneway", "maxspeed"]


def code_for(source):
    """autk-db's load of *source*, as the canvas's compiled data section runs it
    (`adapters/node/autkDataCompile.ts`), with the extract read from the checkout."""
    options = {k: v for k, v in source.items() if k != "type"}
    return (
        "import { AutkDb } from '@urban-toolkit/autk-db';\n"
        "const fs = await import('node:fs');\n"
        "const __fetch = globalThis.fetch;\n"
        "globalThis.fetch = async (url, opts) => String(url).endsWith('.pbf')\n"
        f"  ? new Response(fs.readFileSync({json.dumps(str(REPO_ROOT))} + '/' + String(url)))\n"
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


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--node-modules", help="a node_modules folder holding the autk-db release Curio pins")
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args()
    sys.path.insert(0, str(REPO_ROOT))
    from utk_curio.sandbox.app import worker
    from utk_curio.sandbox.util.input_layers import curio_layer

    node_modules = Path(args.node_modules).resolve() if args.node_modules else None
    result, _logs, errors = worker.run_js_script(
        code_for(SOURCE), None, cwd=str(REPO_ROOT), node_type="AUTK_GRAMMAR", node_modules=node_modules,
    )
    payload = json.loads(result) if result else {}
    if not payload.get("success"):
        raise SystemExit(f"the load failed: {payload.get('error') or errors[-10:]}")
    # The layer chip's call, on the layers as a Weather Routing node gets them.
    layer = curio_layer(payload["value"], ROADS_LAYER, 0)
    roads = layer[[c for c in ROUTING_TAGS if c in layer.columns] + ["geometry"]]
    roads.to_parquet(args.out, index=False)
    print(f"{len(roads)} roads in {roads.crs}, columns {list(roads.columns)}, written to {args.out}")


if __name__ == "__main__":
    main()
