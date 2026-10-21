#!/usr/bin/env python3
"""Build the Data Catalog dataset ``data.curio.chicago-loop-layers``.

Downtown Chicago, the Loop with the West Loop, the South Loop, Streeterville
and the Near North lakefront up to Oak Street Beach, as nine layers of every
geometry an Autark map draws, for the chicago-loop-layers example (one Autark
map, many kinds of layer) and the Interaction node that edits them:

=================  =========  ==================================================
part               geometry   source
=================  =========  ==================================================
tracts.geojson     polygons   CDC/ATSDR Social Vulnerability Index 2020, the
                              Cook County tracts that meet BOX, CDC's columns
buildings.parquet  polygons   Overture Maps buildings (``source.overture.maps``)
parks.geojson      polygons   OpenStreetMap parks and green space, no yards
water.geojson      polygons   OpenStreetMap water (the river, the harbours)
roads.parquet      lines      OpenStreetMap roads, no footways or cycleways
cta_lines.geojson  lines      City of Chicago portal, CTA 'L' (Rail) Lines
trees.geojson      points     OpenStreetMap, ``natural=tree``
cta_stations       points     City of Chicago portal, CTA 'L' (Rail) Stations
beach_sensors      points     City of Chicago portal, the Chicago Park
                              District's beach sensors in BOX, each with its
                              reading at noon on 2025-07-06 (the day SCOUT's
                              WRF forecast covers)
=================  =========  ==================================================

The Overture buildings come through Curio's own Discovery Catalog provider,
the code a **Download** runs. The OpenStreetMap layers are read from BBBike's
Chicago extract (PBF_URL) with GDAL's OSM driver, keeping the tags Autark's
parks, water and roads layers keep: the live Overpass API refused these
queries for hours when this was built. The rest are fetched from their public
APIs. Every layer is cut at BOX, in EPSG:4326.

This is AUTHORING-ONLY tooling. It needs network access and the repository's
Node packages (``npm install`` at the root installs the autk-db Curio pins)::

    conda run -n curio python scripts/build_chicago_loop_layers_dataset.py

Licenses: OpenStreetMap and Overture are ODbL 1.0; the City of Chicago portal's
data is under its Terms of Use; CDC/ATSDR's SVI is public domain.
"""
from __future__ import annotations

import json
import shutil
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from utk_curio.backend.app.discovery.domain.manifest import load_source_manifest  # noqa: E402
from utk_curio.backend.app.discovery.infrastructure.transport import HttpDiscoveryTransport  # noqa: E402
from utk_curio.backend.app.discovery.providers import overture  # noqa: E402

DATASET_ID = "data.curio.chicago-loop-layers"
OUT = REPO / "datasets" / f"{DATASET_ID}@1"
#: West, south, east, north: the shipped downtown roads' box, taken north to
#: Oak Street Beach and east to the lakefront, so the Oak Street weather station
#: and the Ohio Street Beach sensor are in it.
BOX = [-87.662, 41.859, -87.605, 41.906]
PLACE = "Downtown Chicago, the Loop to Oak Street Beach"
OVERTURE = "source.overture.maps@1"
PORTAL = "https://data.cityofchicago.org/resource"
SVI_LAYER = ("https://services3.arcgis.com/ZvidGQkLaDJxRSJ2/arcgis/rest/services/"
             "CDC_ATSDR_Social_Vulnerability_Index_2020_USA/FeatureServer/2")
SVI_FIELDS = ("FIPS", "LOCATION", "AREA_SQMI", "E_TOTPOP", "E_HU", "E_POV150", "E_AGE65", "E_NOVEH",
              "RPL_THEME1", "RPL_THEME2", "RPL_THEME3", "RPL_THEME4", "RPL_THEMES")
#: The beach sensors' readings: the hour the WRF forecast's noon is, local time.
READING_AT = "2025-07-06T12:00:00"


def _get_json(url: str, timeout: int = 120):
    with urllib.request.urlopen(url, timeout=timeout) as answer:
        return json.loads(answer.read().decode("utf-8"))


def _inside(lon: float, lat: float) -> bool:
    west, south, east, north = BOX
    return west <= lon <= east and south <= lat <= north


def _write_geojson(path: Path, features: list[dict]) -> None:
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features},
                               separators=(",", ":"), ensure_ascii=False), encoding="utf-8")


def svi_tracts(work: Path) -> Path:
    west, south, east, north = BOX
    query = urllib.parse.urlencode({
        "where": "STCNTY='17031'", "outFields": ",".join(SVI_FIELDS), "returnGeometry": "true",
        "geometry": f"{west},{south},{east},{north}", "geometryType": "esriGeometryEnvelope",
        "inSR": "4326", "spatialRel": "esriSpatialRelIntersects", "outSR": "4326", "f": "geojson",
    })
    collection = _get_json(f"{SVI_LAYER}/query?{query}")
    features = collection.get("features") or []
    if not features:
        raise SystemExit("CDC's SVI layer returned no tracts")
    for feature in features:
        feature["properties"] = {k: feature["properties"].get(k) for k in SVI_FIELDS}
    # Cut at BOX, as the other layers are: CDC returns every tract that touches it.
    import geopandas as gpd
    from shapely.geometry import box

    tracts = gpd.GeoDataFrame.from_features(features, crs="EPSG:4326")
    tracts = gpd.clip(tracts, box(*BOX)).reset_index(drop=True)
    path = work / "tracts.geojson"
    tracts.to_file(path, driver="GeoJSON")
    print(f"{len(tracts)} tracts")
    return path


def overture_buildings(work: Path) -> tuple[Path, str]:
    manifest = load_source_manifest(REPO / "discovery" / OVERTURE)
    service = overture.OvertureService(manifest, transport=HttpDiscoveryTransport())
    (buildings,) = service.load(manifest.resource("buildings"), {"area": {"box": BOX, "label": PLACE}},
                                work, stage=print)
    print(f"{buildings.features} buildings, Overture release {service.release}")
    return buildings.path, service.release


#: OpenStreetMap's Chicago extract from BBBike: the live Overpass API often
#: refuses queries this size, and an extract is the same data, dated.
PBF_URL = "https://download.bbbike.org/osm/bbbike/Chicago/Chicago.osm.pbf"
#: The tags Autark's parks and water layers keep (see the Discovery manifest).
#: Gardens are left out: in OpenStreetMap they are mostly private yards.
PARK_TAGS = {"leisure": {"park", "playground", "dog_park", "nature_reserve", "pitch"},
             "landuse": {"grass", "recreation_ground", "village_green", "cemetery", "forest", "meadow"},
             "natural": {"wood", "scrub", "grassland"}}
WATER_TAGS = {"natural": {"water", "wetland", "bay"}, "landuse": {"reservoir", "basin"},
              "waterway": {"riverbank", "dock"}}
MIN_PARK_M2 = 150
#: Autark's roads layer leaves out footways, cycleways, steps and pedestrian streets.
NOT_ROADS = {"footway", "cycleway", "steps", "pedestrian", "path", "corridor", "elevator", "platform",
             "bridleway", "proposed", "construction", "raceway", "bus_stop"}


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


def _osm_ids(frame):
    """Each feature's OpenStreetMap id, a number: a way's id for an area made of
    one way, else the relation's, node's or way's own. It identifies a feature,
    so an Interaction node can edit it."""
    import pandas as pd

    ids = frame["osm_way_id"] if "osm_way_id" in frame.columns else pd.Series([None] * len(frame), index=frame.index)
    ids = ids.where(ids.notna(), frame["osm_id"])
    return pd.to_numeric(ids, errors="coerce").astype("Int64")


def pbf_layers(work: Path) -> dict[str, Path]:
    """Parks, water, roads and trees from the extract, cut at BOX."""
    import geopandas as gpd
    import pandas as pd
    from shapely.geometry import box

    pbf = work / "Chicago.osm.pbf"
    if not pbf.exists():
        print("Downloading OpenStreetMap's Chicago extract (BBBike)...")
        urllib.request.urlretrieve(PBF_URL, pbf)
    area = box(*BOX)

    def read(layer):
        return gpd.read_file(pbf, layer=layer, bbox=tuple(BOX), engine="pyogrio")

    def tagged(frame, wanted):
        other = frame["other_tags"].map(_other)
        kind = pd.Series([None] * len(frame), index=frame.index, dtype=object)
        for key, values in wanted.items():
            column = frame[key] if key in frame.columns else other.map(lambda t, k=key: t.get(k))
            hit = column.isin(values) & kind.isna()
            kind[hit] = column[hit]
        keep = kind.notna()
        return frame[keep].assign(kind=kind[keep], osm_id=_osm_ids(frame[keep]))[["osm_id", "name", "kind", "geometry"]]

    polygons = read("multipolygons")
    parks = gpd.clip(tagged(polygons, PARK_TAGS), area)
    # Small patches of grass along streets and yards are not parks a map should show.
    parks = parks[parks.to_crs(parks.estimate_utm_crs()).area >= MIN_PARK_M2]
    water = gpd.clip(tagged(polygons, WATER_TAGS), area)
    lines = read("lines")
    roads = lines[lines["highway"].notna() & ~lines["highway"].isin(NOT_ROADS)].copy()
    other = roads["other_tags"].map(_other)
    for key in ("oneway", "maxspeed", "lanes"):
        roads[key] = other.map(lambda t, k=key: t.get(k))
    roads["osm_id"] = _osm_ids(roads)
    roads = gpd.clip(roads[["osm_id", "highway", "oneway", "maxspeed", "lanes", "name", "geometry"]], area)
    points = read("points")
    tags = points["other_tags"].map(_other)
    trees = points[tags.map(lambda t: t.get("natural") == "tree")].copy()
    for key in ("genus", "species", "leaf_type"):
        trees[key] = tags[trees.index].map(lambda t, k=key: t.get(k))
    trees["osm_id"] = _osm_ids(trees)
    trees = gpd.clip(trees[["osm_id", "genus", "species", "leaf_type", "geometry"]], area)
    out = {}
    for name, frame in (("parks", parks), ("water", water), ("roads", roads), ("trees", trees)):
        frame = frame[~frame.geometry.is_empty]
        # A feature cut in two by the box's edge keeps one id: keep its parts as one.
        frame = frame.dissolve(by="osm_id", as_index=False) if frame["osm_id"].duplicated().any() else frame
        frame = frame.reset_index(drop=True)
        path = work / f"{name}.pbf.geojson"
        frame.to_file(path, driver="GeoJSON")
        out[name] = path
        print(f"{len(frame)} {name}")
    return out


def portal_geojson(work: Path, dataset: str, name: str, keep=None) -> Path:
    west, south, east, north = BOX
    collection = _get_json(f"{PORTAL}/{dataset}.geojson?$limit=50000")
    features = []
    for feature in collection["features"]:
        geometry = feature.get("geometry")
        if not geometry:
            continue
        if geometry["type"] == "Point":
            lon, lat = geometry["coordinates"][:2]
            if not _inside(lon, lat):
                continue
        else:
            points = json.dumps(geometry["coordinates"])
            coords = [float(v) for v in points.replace("[", " ").replace("]", " ").replace(",", " ").split()]
            pairs = list(zip(coords[0::2], coords[1::2]))
            if not any(_inside(lon, lat) for lon, lat in pairs):
                continue
        feature["properties"] = {k: v for k, v in (feature.get("properties") or {}).items()
                                 if not k.startswith(":@") and (keep is None or k in keep)}
        features.append(feature)
    if features and features[0]["geometry"]["type"] != "Point":
        # The portal's line segments have no id: number them in a fixed order.
        features.sort(key=lambda f: (str(f["properties"].get("legend")), str(f["properties"].get("description"))))
        for number, feature in enumerate(features, start=1):
            feature["properties"] = {"line_id": number, **feature["properties"]}
    path = work / f"{name}.geojson"
    _write_geojson(path, features)
    print(f"{len(features)} {name}")
    return path


def beach_sensors(work: Path) -> Path:
    """The Park District's sensors in BOX, each with its reading at READING_AT."""
    locations = _get_json(f"{PORTAL}/g3ip-u8rb.json")
    weather = {row["station_name"]: row for row in _get_json(
        f"{PORTAL}/k7hf-8y75.json?" + urllib.parse.urlencode({"$where": f"measurement_timestamp='{READING_AT}'"}))}
    water = {row["beach_name"]: row for row in _get_json(
        f"{PORTAL}/qmqz-2xku.json?" + urllib.parse.urlencode({"$where": f"measurement_timestamp='{READING_AT}'"}))}
    numeric = ("air_temperature", "wet_bulb_temperature", "humidity", "wind_speed", "wind_direction",
               "barometric_pressure", "solar_radiation", "interval_rain", "water_temperature", "turbidity",
               "wave_height", "wave_period")
    features = []
    for row in locations:
        lon, lat = float(row["longitude"]), float(row["latitude"])
        if not _inside(lon, lat):
            continue
        name, kind = row["sensor_name"], row["sensor_type"]
        reading = weather.get(name) if kind == "Weather" else water.get(name)
        # A sensor that sent nothing at that hour keeps its place, marked as such.
        properties = {"name": name, "sensor_type": kind, "reading_at": READING_AT, "has_reading": bool(reading)}
        for key in numeric:
            if reading and reading.get(key) not in (None, ""):
                properties[key] = float(reading[key])
        features.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]},
                         "properties": properties})
    path = work / "beach_sensors.geojson"
    _write_geojson(path, features)
    print(f"{len(features)} beach sensors: " + ", ".join(f["properties"]["name"] for f in features))
    return path


PARTS = [
    ("tracts.geojson", "Census tracts with CDC/ATSDR's SVI 2020", "geodataframe", "geojson"),
    ("buildings.parquet", "Buildings (Overture Maps)", "geodataframe", "parquet"),
    ("parks.geojson", "Parks (OpenStreetMap)", "geodataframe", "geojson"),
    ("water.geojson", "Water (OpenStreetMap)", "geodataframe", "geojson"),
    ("roads.parquet", "Roads (OpenStreetMap)", "geodataframe", "parquet"),
    ("cta_lines.geojson", "CTA 'L' rail lines (City of Chicago)", "geodataframe", "geojson"),
    ("trees.geojson", "Trees (OpenStreetMap, natural=tree)", "geodataframe", "geojson"),
    ("cta_stations.geojson", "CTA 'L' rail stations (City of Chicago)", "geodataframe", "geojson"),
    ("beach_sensors.geojson", "Beach weather and water sensors (Chicago Park District)", "geodataframe", "geojson"),
]


def main() -> None:
    import geopandas as gpd

    # A cache beside the repository's other scratch files, so a rerun after an
    # Overpass refusal does not ask again for the layers it already has.
    work = REPO / ".curio" / "build-cache" / DATASET_ID
    work.mkdir(parents=True, exist_ok=True)
    osm = pbf_layers(work)
    files = {
        "tracts.geojson": svi_tracts(work),
        "parks.geojson": osm["parks"],
        "water.geojson": osm["water"],
        "trees.geojson": osm["trees"],
        "cta_lines.geojson": portal_geojson(work, "xbyr-jnvx", "cta_lines"),
        "cta_stations.geojson": portal_geojson(work, "3tzw-cg4m", "cta_stations",
                                               keep={"station_id", "longname", "lines", "address", "ada",
                                                     "legend"}),
        "beach_sensors.geojson": beach_sensors(work),
    }
    roads = osm["roads"]
    buildings, release = overture_buildings(work)

    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "data").mkdir(parents=True)
    for name, path in files.items():
        shutil.copyfile(path, OUT / "data" / name)
    frame = gpd.read_file(roads)
    keep = [c for c in ("osm_id", "highway", "oneway", "maxspeed", "lanes", "name", "geometry") if c in frame.columns]
    frame[keep].to_parquet(OUT / "data" / "roads.parquet")
    shutil.copyfile(buildings, OUT / "data" / "buildings.parquet")

    counts = {}
    for name, *_ in PARTS:
        part = OUT / "data" / name
        counts[name] = len(gpd.read_parquet(part) if name.endswith(".parquet") else gpd.read_file(part))
    bundle = {"version": 1, "parts": [
        {"index": i, "label": label, "kind": kind, "format": fmt, "file": f"data/{name}"}
        for i, (name, label, kind, fmt) in enumerate(PARTS)]}
    (OUT / "data" / "bundle.json").write_text(json.dumps(bundle, indent=2) + "\n", encoding="utf-8")
    west, south, east, north = BOX
    today = time.strftime("%Y-%m-%dT00:00:00Z", time.gmtime())
    listing = "; ".join(f"{name} ({counts[name]:,})" for name, *_ in PARTS)
    manifest = {
        "id": DATASET_ID,
        "name": "Chicago Loop Map Layers",
        "version": "1.0.0",
        "format": "bundle",
        "description": (
            f"Downtown Chicago, longitude {west} to {east}, latitude {south} to {north}: the Loop with the West "
            "Loop, the South Loop, Streeterville and the lakefront up to Oak Street Beach, as nine layers of "
            "every geometry an Autark map draws: " + listing + ". Tracts: CDC/ATSDR's Social Vulnerability "
            "Index 2020 for the Cook County tracts that meet the box, cut at it (CDC's column names, -999 missing; AREA_SQMI is the whole tract's). "
            f"Buildings: Overture Maps release {release}, height in metres where Overture has it. Parks, water, "
            "roads and trees (natural=tree): OpenStreetMap, from BBBike's Chicago extract. CTA 'L' "
            "lines and stations: City of Chicago data portal. Beach sensors: the Chicago Park District's "
            f"weather and water sensors in the box, each with its reading at {READING_AT} local time, the day "
            "of SCOUT's WRF forecast (data.scout.chicago-weather-2025-07-06). All EPSG:4326. Built by "
            "scripts/build_chicago_loop_layers_dataset.py."
        ),
        "publisher": "CDC/ATSDR; Overture Maps Foundation; OpenStreetMap contributors; City of Chicago",
        "license": "ODbL-1.0 (OpenStreetMap, Overture); City of Chicago Terms of Use; CDC/ATSDR public domain",
        "tags": ["chicago", "loop", "svi", "buildings", "parks", "roads", "trees", "cta", "weather", "bundle"],
        "dataFile": "data/bundle.json",
        "compatibility": {"major": 1},
        "sourceLabel": "CDC/ATSDR, Overture Maps, OpenStreetMap, City of Chicago",
        "rowCount": None,
        "featureCount": None,
        "schema": None,
        "createdAt": today,
        "updatedAt": today,
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
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(REPO)}: {listing}")


if __name__ == "__main__":
    main()
