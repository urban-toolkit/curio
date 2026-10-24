#!/usr/bin/env python3
"""Build the Data Catalog dataset ``data.curio.chicago-loop-layers``.

Downtown Chicago in the box of the examples' ``chicago_downtown.osm.pbf``
(``scripts/build_example_pbfs.py``), as the layers of the chicago-loop-layers
example that an Autark node cannot load from that extract:

====================  =========  ================================================
part                  geometry   source
====================  =========  ================================================
tracts.geojson        polygons   CDC/ATSDR Social Vulnerability Index 2020, the
                                 Cook County tracts that meet BOX, CDC's columns
cta_lines.geojson     lines      City of Chicago portal, CTA 'L' (Rail) Lines
trees.parquet         points     OpenStreetMap, ``natural=tree``, from BBBike's
                                 Chicago extract
cta_stations.geojson  points     City of Chicago portal, CTA 'L' (Rail) Stations
====================  =========  ================================================

The example loads OpenStreetMap's parks, water, roads and buildings with an
Autark node from ``chicago_downtown.osm.pbf``, so the dataset leaves them out.
Every part is cut at BOX in EPSG:4326 (``write_dataset``): what lies in it is
kept, and a line or a polygon that crosses its edge is cut there. The trees are
GeoParquet, about a tenth of their GeoJSON; the other parts are small enough as
GeoJSON.

This is AUTHORING-ONLY tooling. It needs network access::

    conda run -n curio python scripts/build_chicago_loop_layers_dataset.py

Licenses: OpenStreetMap is ODbL 1.0; the City of Chicago portal's data is under
its Terms of Use; CDC/ATSDR's SVI is public domain.
"""
from __future__ import annotations

import json
import shutil
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

DATASET_ID = "data.curio.chicago-loop-layers"
OUT = REPO / "datasets" / f"{DATASET_ID}@1"
#: West, south, east, north: the box ``chicago_downtown.osm.pbf`` is cut at
#: (``build_example_pbfs.py``), which the example's Autark node loads.
BOX = (-87.662, 41.859, -87.613, 41.898)
#: The date the dataset is stamped with, its ``createdAt`` and ``updatedAt``.
STAMP = "2026-10-22T00:00:00Z"
#: The most the dataset's files may take, so ``datasets/`` stays within the
#: catalog's size budget (``test_catalog_dataset_coverage.py``).
MAX_BYTES = 500_000
PORTAL = "https://data.cityofchicago.org/resource"
SVI_LAYER = ("https://services3.arcgis.com/ZvidGQkLaDJxRSJ2/arcgis/rest/services/"
             "CDC_ATSDR_Social_Vulnerability_Index_2020_USA/FeatureServer/2")
SVI_FIELDS = ("FIPS", "LOCATION", "AREA_SQMI", "E_TOTPOP", "E_HU", "E_POV150", "E_AGE65", "E_NOVEH",
              "RPL_THEME1", "RPL_THEME2", "RPL_THEME3", "RPL_THEME4", "RPL_THEMES")
STATION_FIELDS = ("station_id", "longname", "lines", "address", "ada", "legend")
#: OpenStreetMap's Chicago extract from BBBike.
PBF_URL = "https://download.bbbike.org/osm/bbbike/Chicago/Chicago.osm.pbf"
TREE_TAGS = ("genus", "species", "leaf_type")

#: Each part's file, label, kind and format, in the bundle's order.
PARTS = [
    ("tracts.geojson", "Census tracts with CDC/ATSDR's Social Vulnerability Index 2020", "geodataframe", "geojson"),
    ("cta_lines.geojson", "CTA 'L' rail lines (City of Chicago)", "geodataframe", "geojson"),
    ("trees.parquet", "Trees (OpenStreetMap)", "geodataframe", "parquet"),
    ("cta_stations.geojson", "CTA 'L' rail stations (City of Chicago)", "geodataframe", "geojson"),
]
NAME = "Chicago Loop Layers"
DESCRIPTION = (
    "Downtown Chicago: census tracts with CDC/ATSDR's Social Vulnerability Index 2020, the CTA 'L' rail "
    "lines and stations from the City of Chicago, and trees from OpenStreetMap."
)


def _get_json(url: str, timeout: int = 120):
    with urllib.request.urlopen(url, timeout=timeout) as answer:
        return json.loads(answer.read().decode("utf-8"))


def _write_geojson(path: Path, features: list[dict]) -> None:
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features},
                               separators=(",", ":"), ensure_ascii=False), encoding="utf-8")


def _other(tags: str | None) -> dict:
    """GDAL's other_tags, '"k"=>"v","k2"=>"v2"', as a dict."""
    found = {}
    if not isinstance(tags, str):
        return found
    for item in tags.split('","'):
        if "=>" in item:
            key, value = item.split("=>", 1)
            found[key.strip('"')] = value.strip('"')
    return found


# -- Sources (network) -------------------------------------------------------

def svi_tracts(work: Path) -> Path:
    """CDC/ATSDR's SVI 2020 for the Cook County tracts that meet BOX, CDC's columns, whole."""
    west, south, east, north = BOX
    query = urllib.parse.urlencode({
        "where": "STCNTY='17031'", "outFields": ",".join(SVI_FIELDS), "returnGeometry": "true",
        "geometry": f"{west},{south},{east},{north}", "geometryType": "esriGeometryEnvelope",
        "inSR": "4326", "spatialRel": "esriSpatialRelIntersects", "outSR": "4326", "f": "geojson",
    })
    features = _get_json(f"{SVI_LAYER}/query?{query}").get("features") or []
    if not features:
        raise SystemExit("CDC's SVI layer returned no tracts")
    for feature in features:
        feature["properties"] = {k: feature["properties"].get(k) for k in SVI_FIELDS}
    path = work / "tracts.cdc.geojson"
    _write_geojson(path, features)
    return path


def portal_layer(work: Path, dataset: str, name: str, keep=None) -> Path:
    """A City of Chicago portal layer, all of it, with its columns or the ones in *keep*."""
    features = []
    for feature in _get_json(f"{PORTAL}/{dataset}.geojson?$limit=50000")["features"]:
        if not feature.get("geometry"):
            continue
        feature["properties"] = {k: v for k, v in (feature.get("properties") or {}).items()
                                 if not k.startswith(":@") and (keep is None or k in keep)}
        features.append(feature)
    path = work / f"{name}.portal.geojson"
    _write_geojson(path, features)
    return path


def pbf_trees(work: Path) -> Path:
    """OpenStreetMap's trees (``natural=tree``) in BBBike's Chicago extract, read with GDAL's OSM driver."""
    import geopandas as gpd
    import pandas as pd

    pbf = work / "Chicago.osm.pbf"
    if not pbf.exists():
        print("Downloading OpenStreetMap's Chicago extract (BBBike)...")
        urllib.request.urlretrieve(PBF_URL, pbf)
    points = gpd.read_file(pbf, layer="points", bbox=BOX, engine="pyogrio")
    tags = points["other_tags"].map(_other)
    trees = points[tags.map(lambda t: t.get("natural") == "tree")].copy()
    for key in TREE_TAGS:
        trees[key] = tags[trees.index].map(lambda t, k=key: t.get(k))
    # Its id, a number, identifies a tree, so a Map Editor node can edit it.
    trees["osm_id"] = pd.to_numeric(trees["osm_id"], errors="coerce").astype("Int64")
    path = work / "trees.pbf.geojson"
    trees[["osm_id", *TREE_TAGS, "geometry"]].to_file(path, driver="GeoJSON")
    return path


# -- The dataset (no network) ------------------------------------------------

def cut(frame):
    """*frame* cut at BOX, in its own order: what lies in it, and the part
    inside it of a line or a polygon that crosses its edge."""
    import geopandas as gpd
    from shapely.geometry import box

    frame = gpd.clip(frame, box(*BOX), keep_geom_type=True).sort_index()
    return frame[~frame.geometry.is_empty].reset_index(drop=True)


def cut_lines(frame):
    """The CTA lines cut at BOX. The portal's line segments have no id: they
    are numbered, ``line_id`` from 1, by their line code and description."""
    frame = cut(frame.drop(columns=["line_id"], errors="ignore"))
    keys = frame[["legend", "description"]].astype("string").fillna("")
    order = sorted(range(len(frame)), key=lambda i: (keys.iat[i, 0], keys.iat[i, 1]))
    frame = frame.iloc[order].reset_index(drop=True)
    frame.insert(0, "line_id", range(1, len(frame) + 1))
    return frame


CUTS = {"cta_lines.geojson": cut_lines}


def write_part(frame, path: Path) -> None:
    if path.suffix == ".parquet":
        frame.to_parquet(path, compression="zstd")
    else:
        frame.to_file(path, driver="GeoJSON")


def manifest() -> dict:
    return {
        "id": DATASET_ID,
        "name": NAME,
        "version": "1.0.0",
        "format": "bundle",
        "description": DESCRIPTION,
        "publisher": "CDC/ATSDR; City of Chicago; OpenStreetMap contributors",
        "license": "CDC/ATSDR public domain; City of Chicago Terms of Use; ODbL-1.0 (OpenStreetMap)",
        "tags": ["chicago", "loop", "census-tracts", "svi", "cta", "trees", "bundle"],
        "dataFile": "data/bundle.json",
        "compatibility": {"major": 1},
        "sourceLabel": "CDC/ATSDR, City of Chicago, OpenStreetMap",
        "rowCount": None,
        "featureCount": None,
        "schema": None,
        "createdAt": STAMP,
        "updatedAt": STAMP,
        "sourceUpdatedAt": None,
        "sourceEncoding": None,
        "groupId": None,
        "layerName": None,
        "producerNodeId": None,
        "producerNodeType": None,
        "producerDataflowId": None,
        "producerDataflowName": None,
        "upstreamInputs": None,
        "discoverySource": None,
        "collection": None,
    }


def write_dataset(sources: dict[str, Path], out: Path = OUT) -> dict[str, int]:
    """Write the dataset into *out* from each part's source, a GeoJSON file of
    any extent in EPSG:4326, cut at BOX. Returns each part's rows."""
    import geopandas as gpd

    if out.exists():
        shutil.rmtree(out)
    (out / "data").mkdir(parents=True)
    rows = {}
    for name, *_ in PARTS:
        frame = CUTS.get(name, cut)(gpd.read_file(sources[name]))
        write_part(frame, out / "data" / name)
        rows[name] = len(frame)
    bundle = {"version": 1, "parts": [
        {"index": i, "label": label, "kind": kind, "format": fmt, "file": f"data/{name}"}
        for i, (name, label, kind, fmt) in enumerate(PARTS)]}
    (out / "data" / "bundle.json").write_text(json.dumps(bundle, indent=2) + "\n", encoding="utf-8")
    (out / "manifest.json").write_text(json.dumps(manifest(), indent=1, ensure_ascii=False) + "\n",
                                       encoding="utf-8")
    size = sum(path.stat().st_size for path in out.rglob("*") if path.is_file())
    if size > MAX_BYTES:
        raise SystemExit(f"{out.name} takes {size:,} bytes, over {MAX_BYTES:,}: the catalog has no room for it")
    return rows


def main() -> None:
    # A cache beside the repository's other scratch files, so a rerun does not
    # download again what it already has.
    work = REPO / ".curio" / "build-cache" / DATASET_ID
    work.mkdir(parents=True, exist_ok=True)
    sources = {
        "tracts.geojson": svi_tracts(work),
        "cta_lines.geojson": portal_layer(work, "xbyr-jnvx", "cta_lines"),
        "trees.parquet": pbf_trees(work),
        "cta_stations.geojson": portal_layer(work, "3tzw-cg4m", "cta_stations", keep=STATION_FIELDS),
    }
    rows = write_dataset(sources)
    print(f"wrote {OUT.relative_to(REPO)}: " + "; ".join(f"{name} ({n:,})" for name, n in rows.items()))


if __name__ == "__main__":
    main()
