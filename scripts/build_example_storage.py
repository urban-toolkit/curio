#!/usr/bin/env python3
"""Generate ``docs/examples/data/storage/``, the example storage source.

The folder behind ``datalakes/lake.curio.example-storage@1``: one small
instance of each way a storage source can be organized, all synthetic, all
generated here so the bytes are reproducible and carry no one's data.

    air-quality/<sensor>/<day>.csv     CSV files by sensor subfolder
    air-quality/stations.csv           a table with its own header
    city/roads.shp (+ .dbf .shx .prj)  a shapefile
    city/parks.geojson                 a GeoJSON file
    orthos/<year>/tile_<n>.tif         orthorectified tiles (EPSG:32616)
    dashcam/<date>/<trip>_<n>.jpg      video frames, two sequences
    dashcam/<date>/telemetry.csv       a position per frame
    survey/<year>/IMG_<n>.jpg          geotagged photos
    survey/<year>/clip_<n>.mp4         a one-second H.264 video
    noise/<sensor>/<YYYYmmdd_HHMMSS>.wav  audio recordings

It then adds the resources the storage examples read to the committed Data
Catalog, as ``datasets/data.curio.storage-*@1``, through the Data Lake
Catalog's own add path, so each example can name its data by a stable id the
way every other example does. File times are pinned first, so the indexes come
out the same on every run.

Needs Pillow, rasterio, geopandas and PyAV, all of which ``curio.builtin@1``
installs. Run from the repository root:

    PYTHONPATH=$PWD python scripts/build_example_storage.py
"""

from __future__ import annotations

import csv
import json
import math
import os
import shutil
import struct
import tempfile
import wave
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ROOT = REPO / "docs" / "examples" / "data" / "storage"
SOURCE = REPO / "datalakes" / "lake.curio.example-storage@1"
CATALOG = REPO / "datasets"

#: Every generated file's modification time, and every date the committed
#: datasets record: 2024-05-01T00:00:00Z.
PINNED_EPOCH = 1714521600
PINNED_ISO = "2024-05-01T00:00:00Z"

# The Chicago Loop, where the other examples also live.
LAT, LON = 41.8819, -87.6278


def write_air_quality(root: Path) -> None:
    folder = root / "air-quality"
    stations = [
        ("sensor_A", "Clark and Madison", 41.8819, -87.6308),
        ("sensor_B", "State and Lake", 41.8857, -87.6278),
        ("sensor_C", "Michigan and Adams", 41.8795, -87.6243),
    ]
    for index, (sensor, _name, _lat, _lon) in enumerate(stations):
        for day in range(1, 4):
            path = folder / sensor / f"2024-01-{day:02d}.csv"
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("w", newline="") as handle:
                writer = csv.writer(handle, lineterminator="\n")
                header = ["timestamp", "pm25", "pm10", "temp_c"]
                # The third day gained a humidity column, as real loggers do.
                if day == 3:
                    header.append("humidity")
                writer.writerow(header)
                for hour in range(0, 24, 6):
                    pm25 = round(8 + index * 2 + 3 * math.sin((hour + day) / 4), 1)
                    row = [f"2024-01-{day:02d}T{hour:02d}:00:00", pm25, round(pm25 * 1.8, 1),
                           round(-3 + hour / 4 + index, 1)]
                    if day == 3:
                        row.append(60 + index * 5)
                    writer.writerow(row)
    with (folder / "stations.csv").open("w", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["sensor", "name", "lat", "lon"])
        for row in stations:
            writer.writerow(row)


def write_city(root: Path) -> None:
    import geopandas as gpd
    from shapely.geometry import LineString, Polygon

    folder = root / "city"
    folder.mkdir(parents=True, exist_ok=True)
    roads = gpd.GeoDataFrame(
        {"name": ["Madison St", "State St"], "lanes": [4, 4]},
        geometry=[
            LineString([(-87.6350, 41.8819), (-87.6200, 41.8819)]),
            LineString([(-87.6278, 41.8750), (-87.6278, 41.8900)]),
        ],
        crs=4326,
    )
    # The .dbf header records a date, today's unless it is given one.
    roads.to_file(
        folder / "roads.shp", engine="pyogrio",
        layer_options={"DBF_DATE_LAST_UPDATE": PINNED_ISO[:10]},
    )
    parks = gpd.GeoDataFrame(
        {"name": ["Millennium Park"]},
        geometry=[Polygon([(-87.6250, 41.8810), (-87.6210, 41.8810),
                           (-87.6210, 41.8840), (-87.6250, 41.8840)])],
        crs=4326,
    )
    (folder / "parks.geojson").write_text(parks.to_json(), encoding="utf-8")


def write_orthos(root: Path) -> None:
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin

    size, res = 32, 0.5
    # Two adjacent tiles per campaign, in UTM zone 16N, over the Loop.
    origins = [(447600.0, 4636800.0), (447600.0 + size * res, 4636800.0)]
    for year in (2023, 2024):
        folder = root / "orthos" / str(year)
        folder.mkdir(parents=True, exist_ok=True)
        for index, (x, y) in enumerate(origins, start=1):
            yy, xx = np.mgrid[0:size, 0:size]
            shade = 40 if year == 2023 else 0
            bands = np.stack([
                (xx * 7 + shade) % 256, (yy * 7 + index * 30) % 256, ((xx + yy) * 4) % 256,
            ]).astype("uint8")
            with rasterio.open(
                folder / f"tile_{index:04d}.tif", "w", driver="GTiff", width=size, height=size,
                count=3, dtype="uint8", crs="EPSG:32616", transform=from_origin(x, y, res, res),
                compress="deflate", photometric="RGB",
            ) as dst:
                dst.write(bands)
                dst.update_tags(TIFFTAG_DATETIME=f"{year}:06:15 11:00:00")


def _frame(width: int, height: int, t: float):
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (width, height), (90, 110, 130))
    draw = ImageDraw.Draw(image)
    draw.rectangle([0, height * 2 // 3, width, height], fill=(60, 60, 60))
    x = int((t * 12) % width)
    draw.rectangle([x, height // 2, x + 10, height // 2 + 8], fill=(200, 40, 40))
    return image


def write_dashcam(root: Path) -> None:
    folder = root / "dashcam" / "2024-05-01"
    folder.mkdir(parents=True, exist_ok=True)
    rows = []
    for trip, count in (("trip01", 6), ("trip02", 4)):
        for frame in range(1, count + 1):
            name = f"{trip}_{frame:06d}.jpg"
            _frame(64, 48, frame).save(folder / name, quality=70)
            rows.append([name, round(LAT + frame * 0.0001, 6), round(LON + (0.0002 if trip == "trip02" else 0), 6)])
    with (folder / "telemetry.csv").open("w", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["file_name", "lat", "lon"])
        writer.writerows(rows)


def _gps_exif(lat: float, lon: float, when: str):
    from PIL import Image
    from PIL.TiffImagePlugin import IFDRational

    def dms(value: float):
        value = abs(value)
        degrees = int(value)
        minutes = int((value - degrees) * 60)
        seconds = round(((value - degrees) * 60 - minutes) * 60, 2)
        return (IFDRational(degrees, 1), IFDRational(minutes, 1), IFDRational(int(seconds * 100), 100))

    exif = Image.Exif()
    exif[0x0110] = "Curio example camera"  # Model
    exif[0x0132] = when  # DateTime
    exif.get_ifd(0x8769)[0x9003] = when  # DateTimeOriginal
    gps = exif.get_ifd(0x8825)
    gps[1] = "N" if lat >= 0 else "S"
    gps[2] = dms(lat)
    gps[3] = "E" if lon >= 0 else "W"
    gps[4] = dms(lon)
    return exif


def write_survey(root: Path) -> None:
    import av
    import numpy as np

    shots = [
        (2024, 1, 41.8826, -87.6233, "2024:07:04 09:30:00"),
        (2024, 2, 41.8841, -87.6315, "2024:07:04 10:05:00"),
        (2025, 3, 41.8790, -87.6360, "2025:03:21 15:45:00"),
    ]
    for year, index, lat, lon, when in shots:
        folder = root / "survey" / str(year)
        folder.mkdir(parents=True, exist_ok=True)
        _frame(96, 64, index * 3).save(
            folder / f"IMG_{index:04d}.jpg", quality=75, exif=_gps_exif(lat, lon, when)
        )
    clip = root / "survey" / "2025" / "clip_01.mp4"
    container = av.open(str(clip), mode="w")
    stream = container.add_stream("libx264", rate=10)
    stream.width, stream.height, stream.pix_fmt = 64, 48, "yuv420p"
    stream.options = {"crf": "32", "preset": "veryfast"}
    for index in range(10):
        frame = av.VideoFrame.from_ndarray(np.asarray(_frame(64, 48, index)), format="rgb24")
        for packet in stream.encode(frame):
            container.mux(packet)
    for packet in stream.encode():
        container.mux(packet)
    container.close()


def _tone(path: Path, *, seconds: float, freq: float, level: float, rate: int = 8000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frames = bytearray()
    for n in range(int(seconds * rate)):
        sample = level * math.sin(2 * math.pi * freq * n / rate)
        frames += struct.pack("<h", int(sample * 32767))
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(bytes(frames))


def write_noise(root: Path) -> None:
    folder = root / "noise"
    _tone(folder / "sensor_01" / "20240501_060000.wav", seconds=0.5, freq=220, level=0.2)
    _tone(folder / "sensor_01" / "20240501_070000.wav", seconds=0.5, freq=220, level=0.6)
    _tone(folder / "sensor_02" / "20240501_060000.wav", seconds=0.5, freq=440, level=0.4)


#: The committed datasets: the lake resource each is added from, its id, its
#: name and what it holds.
DATASETS = [
    ("orthos", "data.curio.storage-orthos", "Example drone orthoimagery",
     "Four orthorectified tiles over the Loop from two flights, indexed where they are."),
    ("dashcam", "data.curio.storage-dashcam", "Example dashcam frames",
     "Two dashcam sequences with a position per frame, indexed where they are."),
    ("air-quality", "data.curio.storage-air-quality", "Example air quality readings",
     "Three days of readings from three sensors, combined from one CSV file per sensor and day."),
    ("stations", "data.curio.storage-stations", "Example air quality stations",
     "Where each air quality sensor stands."),
    ("survey", "data.curio.storage-survey", "Example street survey",
     "Geotagged photos and a video from two survey years, indexed where they are."),
    ("noise", "data.curio.storage-noise", "Example noise recordings",
     "Short recordings from two noise sensors, timed by their file names, indexed where they are."),
    ("roads", "data.curio.storage-roads", "Example roads",
     "Two road segments, added from a shapefile."),
    ("parks", "data.curio.storage-parks", "Example parks",
     "A park outline, added from a GeoJSON file."),
]


def pin_times(root: Path) -> None:
    for path in root.rglob("*"):
        os.utime(path, (PINNED_EPOCH, PINNED_EPOCH))


def _counts(path: Path, fmt: str) -> tuple[int | None, int | None]:
    """``(rowCount, featureCount)`` as the Data Catalog lists them."""
    import geopandas as gpd
    import pandas as pd

    if fmt == "geojson":
        return None, len(gpd.read_file(path))
    if fmt == "csv":
        return len(pd.read_csv(path)), None
    try:
        return None, len(gpd.read_parquet(path))
    except Exception:  # noqa: BLE001 - a table without geometry
        return len(pd.read_parquet(path)), None


def build_datasets() -> list[str]:
    """Add each of ``DATASETS`` from the example source and commit the result."""
    state = tempfile.mkdtemp(prefix="curio-example-storage-")
    os.environ["CURIO_STATE_DIR"] = state
    try:
        from utk_curio.backend.app.datalakes.application.storage_acquire import StorageAcquire
        from utk_curio.backend.app.datalakes.domain.manifest import load_source_manifest
        from utk_curio.backend.app.datalakes.providers import build_storage
        from utk_curio.backend.app.datasets.install.installer import install_imported_path
        from utk_curio.backend.app.datasets.repositories import index as index_repo

        # The build writes files to commit, with no database to index them in.
        index_repo.safe_upsert_from_dir = lambda *_args, **_kwargs: None

        manifest = load_source_manifest(SOURCE)
        provider = build_storage(manifest, None)
        placed: list[Path] = []

        def install_path(path, filename, fmt, **kwargs):
            result = install_imported_path(
                "1", path, filename, fmt,
                title=kwargs.get("title"),
                lake_source=kwargs.get("lake_source"),
                description=kwargs.get("description"),
                collection=kwargs.get("collection"),
            )
            placed.append(result.dest)
            return {"id": result.manifest.id}

        acquire = StorageAcquire(
            user_key="1",
            storage_for=lambda _m: provider,
            install_path=install_path,
            import_layers=None,
            find_held=lambda *_a: None,
        )
        written = []
        for resource_id, dataset_id, title, description in DATASETS:
            acquire.acquire(manifest, resource_id, title=title)
            written.append(_commit(placed.pop(), dataset_id, title, description))
        return written
    finally:
        shutil.rmtree(state, ignore_errors=True)


def _commit(built: Path, dataset_id: str, title: str, description: str) -> str:
    """Move one added dataset into ``datasets/`` under its committed id."""
    raw = json.loads((built / "manifest.json").read_text(encoding="utf-8"))
    fmt = raw["format"]
    rows, features = _counts(built / raw["dataFile"], fmt)
    lake = dict(raw.get("lakeSource") or {}, fetchedAt=PINNED_ISO)
    collection = raw.get("collection")
    if collection:
        collection = dict(collection, indexedAt=PINNED_ISO)
    kind = (collection or {}).get("kind")
    out = {
        "id": dataset_id,
        "name": title,
        "version": "1.0.0",
        "format": fmt,
        "description": description,
        "publisher": "Curio",
        "license": "CC0-1.0",
        "tags": ["example", "storage", kind or fmt],
        "dataFile": raw["dataFile"],
        "compatibility": {"major": 1},
        "sourceLabel": "Example storage",
        "createdAt": PINNED_ISO,
        "updatedAt": PINNED_ISO,
        "rowCount": rows if collection is None else len(__import__("pandas").read_parquet(built / raw["dataFile"])),
        "featureCount": None if collection else features,
        "schema": None,
        "lakeSource": lake,
    }
    if collection:
        out["collection"] = collection
    target = CATALOG / f"{dataset_id}@1"
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(built / "data", target / "data")
    (target / "manifest.json").write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    return target.name


def main() -> None:
    if ROOT.exists():
        shutil.rmtree(ROOT)
    ROOT.mkdir(parents=True)
    write_air_quality(ROOT)
    write_city(ROOT)
    write_orthos(ROOT)
    write_dashcam(ROOT)
    write_survey(ROOT)
    write_noise(ROOT)
    pin_times(ROOT)
    files = sorted(p for p in ROOT.rglob("*") if p.is_file())
    total = sum(p.stat().st_size for p in files)
    datasets = build_datasets()
    print(json.dumps({"files": len(files), "bytes": total, "datasets": datasets}))


if __name__ == "__main__":
    main()
