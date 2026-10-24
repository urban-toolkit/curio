#!/usr/bin/env python3
"""Build the Data Catalog dataset ``data.nyc.crown-heights-1550-bedford``.

Crown Heights, Brooklyn, about 600 by 550 m around 1550 Bedford Avenue (Block
1266, Lot 36), the site of the 18-story building that ZAP project 2026K0123
proposes, as the parts the bedford-avenue-shadow example reads:

==================  =========  ==================================================
part                geometry   source
==================  =========  ==================================================
buildings.parquet   polygons   NYC Open Data, Building Footprints (5zhs-2jue):
                               the buildings that meet BOX, their roof height
                               (``height_roof``, feet) as ``height`` in metres
block-1259.geojson  polygon    NYC MapPLUTO: Block 1259's lots dissolved, the
                               block across Eastern Parkway from the site,
                               Franklin Avenue to Bedford Avenue
site.geojson        polygon    NYC MapPLUTO: the site's lot, BBL 3012660036
streets.geojson     lines      NYC Open Data, Centerline (CSCL, inkn-q76z): the
                               street segments that meet BOX, cut at it, each
                               with its name (``street``) and its roadway's
                               width, curb to curb (``width_ft``); bike paths
                               left out
==================  =========  ==================================================

The buildings are those Building Footprints marks as buildings (feature code
2100) or garages (5110). The footprint it has for the site, "Marked for
Construction", is a planned building that was never built, so it is left out:
the site is vacant, as the project's description says. The buildings are
GeoParquet, their coordinates to a millionth of a degree, so ``datasets/``
stays within its size budget (``test_catalog_dataset_coverage.py``).

This is AUTHORING-ONLY tooling. It needs network access::

    conda run -n curio python scripts/build_bedford_shadow_dataset.py

Licenses: NYC Open Data's Building Footprints and Centerline and the
Department of City Planning's MapPLUTO are free to use under the NYC Open Data Terms of Use.
"""
from __future__ import annotations

import json
import shutil
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

DATASET_ID = "data.nyc.crown-heights-1550-bedford"
OUT = REPO / "datasets" / f"{DATASET_ID}@1"
#: West, south, east, north: the buildings kept, the site and Block 1259 with
#: about 150 m around them (600 by 550 m), the buildings near enough to shade
#: the block or to be shaded by the proposed building.
BOX = (-73.9605, 40.6680, -73.9535, 40.6730)
STAMP = "2026-10-22T00:00:00Z"
FOOTPRINTS = "https://data.cityofnewyork.us/resource/5zhs-2jue.geojson"
CENTERLINE = "https://data.cityofnewyork.us/resource/inkn-q76z.geojson"
#: CSCL's roadway types kept: streets (1) and the parkway's roadways (3); bike
#: paths (6) are left out.
ROADWAYS = {"1", "3"}
MAPPLUTO = ("https://services5.arcgis.com/GfwWNkhOj9bNBqoJ/arcgis/rest/services/"
            "MAPPLUTO/FeatureServer/0/query")
SITE_BBL = 3012660036
TARGET_BLOCK = 1259
FEET = 0.3048
#: Each part's file, label, kind and format, in the bundle's order.
PARTS = (
    ("buildings.parquet", "Buildings with their roof heights in metres (NYC Building Footprints)",
     "geodataframe", "parquet"),
    ("block-1259.geojson", "Block 1259, across Eastern Parkway from the site (NYC MapPLUTO)",
     "geodataframe", "geojson"),
    ("site.geojson", "The site, 1550 Bedford Avenue, Block 1266 Lot 36 (NYC MapPLUTO)",
     "geodataframe", "geojson"),
    ("streets.geojson", "Street centerlines with their names (NYC Centerline, CSCL)", "geodataframe", "geojson"),
)
NAME = "Crown Heights buildings around 1550 Bedford Avenue"
DESCRIPTION = (
    "Crown Heights, Brooklyn, about 600 by 550 m around 1550 Bedford Avenue, the site of the 18-story "
    "building ZAP project 2026K0123 proposes: NYC's building footprints with their roof heights in "
    "metres (building_id is DoITT's id), Block 1259 across Eastern Parkway from the site (Franklin "
    "Avenue to Bedford Avenue, its lots dissolved) and the site's lot, Block 1266 Lot 36, from MapPLUTO. "
    "The site is vacant: the footprint NYC has for it, a planned building never built, is left out."
)


def _get(url: str, params: dict, path: Path) -> Path:
    if not path.exists():
        with urllib.request.urlopen(f"{url}?{urllib.parse.urlencode(params)}", timeout=300) as response:
            path.write_bytes(response.read())
    return path


def footprints(work: Path) -> Path:
    west, south, east, north = BOX
    return _get(FOOTPRINTS, {
        "$where": f"within_box(the_geom, {north + 0.002}, {west - 0.002}, {south - 0.002}, {east + 0.002})",
        "$limit": 50000,
    }, work / "footprints.geojson")


def centerlines(work: Path) -> Path:
    west, south, east, north = BOX
    ring = f"{west} {south}, {east} {south}, {east} {north}, {west} {north}, {west} {south}"
    return _get(CENTERLINE, {"$where": f"intersects(the_geom, 'POLYGON(({ring}))')", "$limit": 5000},
                work / "centerline.geojson")


def streets_part(path: Path):
    import geopandas as gpd
    import pandas as pd
    import shapely
    from shapely.geometry import box

    frame = gpd.read_file(path)
    frame = frame[frame["rw_type"].isin(ROADWAYS)]
    # CSCL's names as a map's legend reads them: Eastern Parkway, Bedford Avenue.
    # A leading ST is Saint (St Johns Place); after the first word it is Street.
    words = {"AVE": "Avenue", "ST": "Street", "PL": "Place", "PKWY": "Parkway", "OPAS": "Overpass"}
    street = frame["full_street_name"].map(lambda name: " ".join(
        word.title() if k == 0 else words.get(word, word.title()) for k, word in enumerate(name.split())))
    cut = frame.geometry.intersection(box(*BOX))
    # CSCL's streetwidth: the roadway's width, curb to curb, in feet.
    width = pd.to_numeric(frame["streetwidth"], errors="coerce")
    streets = gpd.GeoDataFrame({"segment_id": frame["physicalid"].astype("int64"), "street": street,
                                "width_ft": width}, geometry=shapely.set_precision(cut.values, 1e-6), crs=4326)
    return streets[~streets.is_empty].reset_index(drop=True)


def lots(work: Path, where: str, name: str) -> Path:
    return _get(MAPPLUTO, {"where": where, "outFields": "BBL,Block,Lot,Address", "outSR": 4326, "f": "geojson"},
                work / f"{name}.geojson")


def buildings_part(path: Path):
    import geopandas as gpd
    import pandas as pd
    import shapely
    from shapely.geometry import box

    frame = gpd.read_file(path)
    frame = frame[frame["feature_code"].isin(["2100", "5110"])
                  & (frame["last_status_type"] != "Marked for Construction")]
    frame = frame[frame.intersects(box(*BOX))]
    height = pd.to_numeric(frame["height_roof"], errors="coerce") * FEET
    frame = frame[height > 0]
    return gpd.GeoDataFrame({
        "building_id": frame["doitt_id"].astype("int32"),
        "height": height[frame.index].round(1).astype("float32"),
    }, geometry=shapely.set_precision(frame.geometry.values, 1e-6), crs=4326).reset_index(drop=True)


def manifest() -> dict:
    return {
        "id": DATASET_ID,
        "name": NAME,
        "version": "1.0.0",
        "format": "bundle",
        "description": DESCRIPTION,
        "publisher": "NYC Office of Technology and Innovation; NYC Department of City Planning",
        "license": "NYC Open Data Terms of Use",
        "tags": ["new-york", "brooklyn", "crown-heights", "buildings", "streets", "shadow", "bundle"],
        "dataFile": "data/bundle.json",
        "compatibility": {"major": 1},
        "sourceLabel": "NYC Open Data (Building Footprints, Centerline), NYC DCP (MapPLUTO)",
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
    }


def main() -> None:
    import geopandas as gpd

    work = REPO / ".curio" / "build-bedford-shadow"
    work.mkdir(parents=True, exist_ok=True)
    buildings = buildings_part(footprints(work))
    block = gpd.read_file(lots(work, f"Borough='BK' AND Block={TARGET_BLOCK}", "block"))
    block = block.dissolve()[["geometry"]].assign(block=TARGET_BLOCK)[["block", "geometry"]]
    site = gpd.read_file(lots(work, f"BBL={SITE_BBL}", "site"))
    site = site.assign(bbl=site["BBL"].astype("int64"))[["bbl", "Address", "geometry"]].rename(
        columns={"Address": "address"})

    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "data").mkdir(parents=True)
    buildings.to_parquet(OUT / "data" / "buildings.parquet", compression="zstd", compression_level=19)
    block.to_file(OUT / "data" / "block-1259.geojson", driver="GeoJSON", COORDINATE_PRECISION=7)
    site.to_file(OUT / "data" / "site.geojson", driver="GeoJSON", COORDINATE_PRECISION=7)
    streets = streets_part(centerlines(work))
    streets.to_file(OUT / "data" / "streets.geojson", driver="GeoJSON", COORDINATE_PRECISION=6)
    bundle = {"version": 1, "parts": [
        {"index": i, "label": label, "kind": kind, "format": fmt, "file": f"data/{name}"}
        for i, (name, label, kind, fmt) in enumerate(PARTS)
    ]}
    (OUT / "data" / "bundle.json").write_text(json.dumps(bundle, indent=2) + "\n", encoding="utf-8")
    (OUT / "manifest.json").write_text(json.dumps(manifest(), indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    sizes = {path.name: path.stat().st_size for path in (OUT / "data").iterdir()}
    print(f"{len(buildings)} buildings, {len(streets)} street segments; {sizes}")


if __name__ == "__main__":
    main()
