"""SCOUT's files the routing scripts in this folder read, and the files they write.

SCOUT is https://github.com/urban-toolkit/scout. Each script checks that the
checkout it is given holds the files it reads exactly as committed at
SCOUT_COMMIT (``BLOBS``, git blob ids), so a rerun reads the same bytes.

The scripts write SCOUT's weather and its weather GNN into the Data Catalog
(``<repo>/datasets/<id>@1/``, ``DATASETS``), each dataset with its manifest
(``write_manifest``). SCOUT's data is published by SCOUT and used with the
permission of SCOUT's authors, so a manifest names SCOUT as publisher and no
license. SCOUT's road graph is not a Curio dataset: a Curio road graph comes
from a Curio roads layer. The cut of it that SCOUT's own routing runs on for
the proof is a test fixture (``ROAD_NODES_FILE``, ``ROAD_EDGES_FILE``).
"""

import hashlib
import json
from pathlib import Path

SCOUT_COMMIT = "b98369e50b2972c0fc22180f56da0ac99a98a545"
SCOUT_URL = "https://github.com/urban-toolkit/scout"

ROUTING = "backend/models/routing"
WEATHER_VARIABLES = ("RAIN", "T2", "RH2", "WSPD10", "WDIR10")

# Git blob ids at SCOUT_COMMIT.
BLOBS = {
    # SCOUT's routing modules, as its example imports them.
    f"{ROUTING}/scripts/__init__.py": "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391",
    f"{ROUTING}/scripts/weather_routing.py": "68b83d27e3276533e377da0d50c006e02d4e7aba",
    f"{ROUTING}/scripts/weight_calculation.py": "f39c32956d5e55052e4642e00c6fb102c8fea020",
    f"{ROUTING}/scripts/load_static.py": "9222f6e2e47bd065424af8a2d1df0ee3d2fa53fd",
    f"{ROUTING}/scripts/calculate_isochrones.py": "be1e67dcdc65538a46aa7115ad00c905310ab538",
    # The GNN weights `GNN_weight_calculations` loads, and the older file nothing loads.
    f"{ROUTING}/gnn/rain_model.pth": "013541ca57b0a696511d2bf6ecb4826322665851",
    f"{ROUTING}/gnn/GNN_model.pth": "2f1aef8a9a78a884ef1fab7eba8feaa553121a0a",
    # The five WRF weather files.
    f"{ROUTING}/weather_data/RAIN.nc": "7374e3b9cc586bc2c6156348b19394b7b1e00993",
    f"{ROUTING}/weather_data/T2.nc": "ac7760b366d57d30343554524e6f149e31f0fcc5",
    f"{ROUTING}/weather_data/RH2.nc": "baa370d5d187886b523d74b3998c135258785968",
    f"{ROUTING}/weather_data/WSPD10.nc": "197620cc11e4e93b0ae4ff448a8a285d94cea17a",
    f"{ROUTING}/weather_data/WDIR10.nc": "6a85bfdbb6a0fe24659a3ad1cc02886e38585b53",
    # SCOUT's Chicago road graph (a pickled networkx MultiDiGraph) and the roads
    # layer its data layer node cuts (the same file as the catalog's copy).
    "backend/data/osm/processed/chicago/roads.pkl.gz": "caac6b48c5e41c89c8992d82607be7acefcecfbf",
    "backend/data/osm/processed/chicago/roads.feather": "40aeaa9a27d4a98e5253ede3a4e8e5c9d487e7a4",
    # The server code whose roads cut the reference mirrors (crop_gdf, select_features).
    "backend/server.py": "fd4568fedb3e843c4be2f3fc1f546fd683e6922f",
    # SCOUT's weather routing example: the saved dataflow and the frontend copy.
    "backend/data/dataflows/4833827e401c4e01b041e02481fdacd4.json": "73323160f572e89fec0aad0bf421fdb2576c7b31",
    "frontend/src/examples/weatherRoutingComparisonWorkflow.ts": "8dfe9392e8c02946191ee35c6b325a67a5106cf6",
}

REPO_ROOT = Path(__file__).resolve().parents[2]
CATALOG = REPO_ROOT / "datasets"
#: The scout.routing proof's fixtures.
FIXTURES = REPO_ROOT / "utk_curio" / "backend" / "tests" / "test_packages" / "fixtures" / "scout_routing"

#: The WRF variables' NetCDF group, and each variable's dataset id.
WEATHER_GROUP = "netcdf.scout-wrf"
WEATHER_IDS = {name: f"data.scout.wrf-{name.lower()}" for name in WEATHER_VARIABLES}
WEATHER_GNN = "data.scout.weather-gnn"
#: Each dataset's data file, under ``<catalog>/<id>@1/``.
DATASETS = {
    **{dataset_id: f"data/{name}.nc" for name, dataset_id in WEATHER_IDS.items()},
    WEATHER_GNN: "data/weather_gnn.onnx",
}
#: SCOUT's road graph cut, under ``<fixtures>/``: its nodes and its edges.
ROAD_NODES_FILE = "roads_nodes.parquet"
ROAD_EDGES_FILE = "roads_edges.parquet"

PUBLISHER = "SCOUT (urban-toolkit/scout)"
SOURCE_LABEL = "SCOUT"
STAMP = "2026-10-05T00:00:00Z"
PERMISSION = "used with the permission of SCOUT's authors"


def git_blob_id(path):
    """The id git gives the file's content."""
    data = Path(path).read_bytes()
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check_scout_checkout(scout, paths):
    """Fail unless each of *paths* in the checkout is the file pinned in BLOBS."""
    problems = []
    for rel in paths:
        path = Path(scout) / rel
        if not path.is_file():
            problems.append(f"missing: {rel}")
        elif git_blob_id(path) != BLOBS[rel]:
            problems.append(f"not the file of SCOUT {SCOUT_COMMIT[:8]}: {rel}")
    if problems:
        raise SystemExit("SCOUT checkout check failed:\n  " + "\n  ".join(problems))


def blob_ids(paths):
    return {rel: BLOBS[rel] for rel in paths}


def data_file(catalog, dataset_id):
    """Where *dataset_id*'s data file lives under *catalog*."""
    return Path(catalog) / f"{dataset_id}@1" / DATASETS[dataset_id]


def write_manifest(catalog, dataset_id, *, name, fmt, description, tags,
                   row_count=None, group_id=None, layer_name=None):
    """*dataset_id*'s manifest, with every field the catalog writes, in its order
    (``build_manifest_dict`` in ``utk_curio/backend/app/datasets/domain/manifest.py``)."""
    manifest = {
        "id": dataset_id, "name": name, "version": "1.0.0", "format": fmt,
        "description": description, "publisher": PUBLISHER, "license": "", "tags": list(tags),
        "dataFile": DATASETS[dataset_id], "compatibility": {"major": 1}, "sourceLabel": SOURCE_LABEL,
        "rowCount": row_count, "featureCount": None, "schema": None,
        "createdAt": STAMP, "updatedAt": STAMP, "sourceUpdatedAt": None, "sourceEncoding": None,
        "groupId": group_id, "layerName": layer_name,
        "producerNodeId": None, "producerNodeType": None, "producerDataflowId": None,
        "producerDataflowName": None, "upstreamInputs": None, "discoverySource": None, "collection": None,
    }
    path = Path(catalog) / f"{dataset_id}@1" / "manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return path
