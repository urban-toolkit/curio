#!/usr/bin/env python3
"""Ship the FloodRisk example's two context datasets, each as it was obtained.

The FloodRisk example (``docs/examples/dataflows/FloodRisk.json``) measures the
land SCOUT's Quad Cities flood projection covers, over SCOUT's whole flood grid
(the box -90.6879323, 41.4150156 to -90.4252158, 41.6242105, FloodScenarios'
corners). Its flood rasters are ``data.scout.quad-cities-flood``; this script
writes the other two inputs, one Data Catalog dataset each, as a user gets them
from the layers the Dataset Finder finds:

- ``data.cdc.quad-cities-svi-tracts``: the census tracts of CDC/ATSDR's Social
  Vulnerability Index 2020 that meet the grid, from ArcGIS Hub (item
  ``3827cb5593174c79b35119611299279b``, layer 2, tracts). The whole layer is
  268 MB, so it is read with the query the Node Builder handoff writes: Scott
  County, Iowa (19163), Rock Island County (17161) and Henry County (17073),
  Illinois, then the tracts that meet the grid. CDC's column names, and its
  -999 for a missing estimate, are kept as published;
- ``data.usgs.quad-cities-waterways``: the rivers, lakes and reservoirs of
  USGS's National Hydrography Dataset (NHD) that meet the grid, so the example
  can leave the water itself out of the flooded land: NHD's large-scale Area
  layer, its stream and river polygons (FTYPE 460, the Mississippi's channel),
  and its large-scale Waterbody layer, its lakes and ponds (390) and
  reservoirs (436). Swamps and marshes (466) are left out, since the flood
  rasters' constructed wetlands lie on them. NHD's columns, clipped to the grid.

This is AUTHORING-ONLY tooling, run once by hand; nothing imports it.

USAGE
-----
    python scripts/build_flood_risk_datasets.py
"""
from __future__ import annotations

import json
import shutil
import sys
import urllib.parse
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from utk_curio.backend.app.datasets.domain.manifest import (  # noqa: E402
    DatasetManifest,
    build_manifest_dict,
)

TRACTS_ID = "data.cdc.quad-cities-svi-tracts"
WATERWAYS_ID = "data.usgs.quad-cities-waterways"
STAMP = "2026-10-13T00:00:00Z"
#: SCOUT's flood grid, west, south, east, north (FloodScenarios' corners).
BOX = (-90.6879323, 41.4150156, -90.4252158, 41.6242105)
SVI_LAYER = ("https://services3.arcgis.com/ZvidGQkLaDJxRSJ2/arcgis/rest/services/"
             "CDC_ATSDR_Social_Vulnerability_Index_2020_USA/FeatureServer/2")
SVI_COUNTIES = ("19163", "17161", "17073")
#: CDC's columns kept: identity, the estimates the risk measure and the charts
#: read, and the four theme percentiles with the overall one.
SVI_FIELDS = ("FIPS", "STCNTY", "STATE", "COUNTY", "LOCATION", "AREA_SQMI", "E_TOTPOP", "E_HU", "E_HH",
              "E_POV150", "E_UNEMP", "E_AGE65", "E_AGE17", "E_DISABL", "E_NOVEH", "E_MINRTY",
              "RPL_THEME1", "RPL_THEME2", "RPL_THEME3", "RPL_THEME4", "RPL_THEMES")


def _write_manifest(folder: Path, manifest: DatasetManifest) -> None:
    (folder / "manifest.json").write_text(
        json.dumps(build_manifest_dict(manifest), indent=2) + "\n", encoding="utf-8"
    )


def ship_tracts() -> int:
    """CDC's SVI tracts of the three counties that meet the grid."""
    import geopandas as gpd
    from shapely.geometry import box as shapely_box

    where = "STCNTY IN (" + ",".join(f"'{c}'" for c in SVI_COUNTIES) + ")"
    query = urllib.parse.urlencode({
        "where": where, "outFields": ",".join(SVI_FIELDS), "returnGeometry": "true",
        "outSR": "4326", "orderByFields": "FIPS", "f": "geojson",
    })
    with urllib.request.urlopen(f"{SVI_LAYER}/query?{query}", timeout=120) as answer:
        collection = json.load(answer)
    features = collection.get("features") or []
    if not features:
        raise SystemExit("CDC's SVI layer returned no tracts")
    tracts = gpd.GeoDataFrame.from_features(features, crs="EPSG:4326")
    meets = tracts.intersects(shapely_box(*BOX)).to_numpy()
    kept = [f for f, keep in zip(features, meets) if keep]
    for feature in kept:
        feature["properties"] = {k: feature["properties"].get(k) for k in SVI_FIELDS}
        feature.pop("id", None)
    folder = REPO_ROOT / "datasets" / f"{TRACTS_ID}@1"
    if folder.exists():
        shutil.rmtree(folder)
    (folder / "data").mkdir(parents=True)
    (folder / "data" / "svi_tracts.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": kept}) + "\n", encoding="utf-8")
    _write_manifest(folder, DatasetManifest(
        id=TRACTS_ID,
        name="Quad Cities SVI Census Tracts",
        version="1.0.0",
        format="geojson",
        description=(
            f"The {len(kept)} census tracts of Scott County, Iowa and Rock Island and Henry Counties, Illinois that "
            "meet SCOUT's Quad Cities flood grid (-90.6879, 41.4150 to -90.4252, 41.6242), from CDC/ATSDR's Social "
            "Vulnerability Index 2020 (ArcGIS Hub item 3827cb5593174c79b35119611299279b, tracts layer). CDC's "
            "column names: estimates such as E_TOTPOP (people), E_AGE65, E_DISABL, E_NOVEH and E_POV150, and the "
            "percentile rankings RPL_THEME1 to 4 and RPL_THEMES (overall); -999 marks a missing value, as CDC "
            "publishes it. CDC/ATSDR, public domain."
        ),
        publisher="CDC/ATSDR",
        license="Public domain",
        tags=["census-tracts", "social-vulnerability", "svi", "quad-cities", "geojson"],
        data_file="data/svi_tracts.geojson",
        major=1,
        created_at=STAMP,
        updated_at=STAMP,
        row_count=len(kept),
        feature_count=len(kept),
        schema=None,
        source_label="CDC/ATSDR",
    ))
    return len(kept)


NHD = "https://hydro.nationalmap.gov/arcgis/rest/services/nhd/MapServer"
#: NHD layer, the feature types kept from it, and what they are.
NHD_LAYERS = ((9, (460,), "stream and river areas"), (12, (390, 436), "lakes, ponds and reservoirs"))
NHD_FIELDS = ("GNIS_NAME", "FTYPE", "FCODE", "AREASQKM")


def ship_waterways() -> int:
    """NHD's rivers, lakes and reservoirs that meet the grid, clipped to it."""
    import geopandas as gpd
    import pandas as pd
    from shapely.geometry import box as shapely_box

    frames = []
    for layer, ftypes, _what in NHD_LAYERS:
        query = urllib.parse.urlencode({
            "where": f"FTYPE IN ({','.join(map(str, ftypes))})", "outFields": ",".join(NHD_FIELDS),
            "geometry": ",".join(map(str, BOX)), "geometryType": "esriGeometryEnvelope", "inSR": "4326",
            "spatialRel": "esriSpatialRelIntersects", "returnGeometry": "true", "outSR": "4326", "f": "geojson",
        })
        # NHD's Area layer takes about 40 seconds to answer for the grid.
        with urllib.request.urlopen(f"{NHD}/{layer}/query?{query}", timeout=300) as answer:
            features = json.load(answer).get("features") or []
        if not features:
            raise SystemExit(f"NHD layer {layer} returned no features")
        frame = gpd.GeoDataFrame.from_features(features, crs="EPSG:4326")
        frame.columns = [c.upper() if c.lower() in {f.lower() for f in NHD_FIELDS} else c for c in frame.columns]
        frames.append(frame[[*NHD_FIELDS, "geometry"]])
    water = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs="EPSG:4326")
    water["geometry"] = water.geometry.intersection(shapely_box(*BOX))
    water = water[~water.geometry.is_empty].reset_index(drop=True)
    folder = REPO_ROOT / "datasets" / f"{WATERWAYS_ID}@1"
    if folder.exists():
        shutil.rmtree(folder)
    (folder / "data").mkdir(parents=True)
    (folder / "data" / "waterways.geojson").write_text(water.to_json(drop_id=True) + "\n", encoding="utf-8")
    km2 = water.to_crs("EPSG:26915").area.sum() / 1e6
    _write_manifest(folder, DatasetManifest(
        id=WATERWAYS_ID,
        name="Quad Cities Waterways",
        version="1.0.0",
        format="geojson",
        description=(
            f"The {len(water)} rivers, lakes and reservoirs of USGS's National Hydrography Dataset (NHD) that meet "
            "SCOUT's Quad Cities flood grid (-90.6879, 41.4150 to -90.4252, 41.6242), clipped to it, "
            f"{km2:.0f} km2 of water: NHD's large-scale Area layer, its stream and river areas (FTYPE 460, the "
            "Mississippi's channel), and its large-scale Waterbody layer, its lakes and ponds (390) and reservoirs "
            "(436); swamps and marshes (466) are left out. NHD's columns GNIS_NAME, FTYPE, FCODE and AREASQKM (the "
            "whole feature's area, before clipping). From hydro.nationalmap.gov/arcgis/rest/services/nhd/MapServer, "
            "layers 9 and 12. USGS, public domain."
        ),
        publisher="U.S. Geological Survey",
        license="Public domain",
        tags=["water", "rivers", "nhd", "usgs", "quad-cities", "geojson"],
        data_file="data/waterways.geojson",
        major=1,
        created_at=STAMP,
        updated_at=STAMP,
        row_count=len(water),
        feature_count=len(water),
        schema=None,
        source_label="USGS",
    ))
    return len(water)


def main() -> int:
    tracts = ship_tracts()
    waterways = ship_waterways()
    print(f"{TRACTS_ID}: {tracts} tracts; {WATERWAYS_ID}: {waterways} waterways")
    return 0


if __name__ == "__main__":
    sys.exit(main())
