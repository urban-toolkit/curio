"""The shadow tiles SCOUT's ``run_shadow_model`` writes, side by side in one
raster an Autark map draws. Curio's own code, beside SCOUT's ``deep_umbra.py``.

The mosaic is a GeoTIFF in EPSG:3395, one float32 band of minutes: a tile's
gray level times the season's minutes over 255 (720 in summer, 540 in spring,
360 in winter, SCOUT's ``factor``). Each tile sits where SCOUT's rasterizer drew
the heights it was predicted from, its corners from SCOUT's ``num2deg`` and the
WGS 84 to World Mercator transform, so the shadow and the height mosaic of
Rasterize Buildings' tiles share one grid, as a Raster Statistics mask needs.
A cell no tile covers has no value (NaN): a GeoTIFF that names no nodata is read
by autk-db with 0 as its nodata, which would leave every cell in the sun out of
an Autark map.
"""

import hashlib
import math
import os
import re

import cv2
import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.transform import Affine

TILE_SIZE = 256
TILE_FILE = re.compile(r"^(\d+)_(\d+)_(\d+)\.png$")

#: SCOUT's rasterizer's transform from longitude and latitude to World Mercator.
invtransformer = Transformer.from_crs(4326, 3395)


def num2deg(xtile, ytile, zoom):
    """The north-west corner of tile (xtile, ytile): ``(latitude, longitude)``,
    as SCOUT's rasterizer finds it."""
    n = 2.0 ** zoom
    lon_deg = xtile / n * 360.0 - 180.0
    lat_rad = math.atan(math.sinh(math.pi * (1 - 2 * ytile / n)))
    lat_deg = math.degrees(lat_rad)
    return (lat_deg, lon_deg)


def corner(x, y, zoom):
    """The north-west corner of tile *x*, *y* in EPSG:3395."""
    return invtransformer.transform(*num2deg(x, y, zoom))


def season_minutes(season):
    """The minutes of shadow a gray level of 255 stands for: SCOUT's ``factor``."""
    return 360 if season == "winter" else 540 if season == "spring" else 720


def mosaic(folder, season, output_file):
    """The shadow tiles in *folder* as one raster of minutes, opened.
    *output_file(name)* names where the GeoTIFF is written."""
    minutes = season_minutes(season)
    tiles = {}
    zooms = set()
    digest = hashlib.sha1(season.encode("ascii"))
    for name in sorted(os.listdir(folder)):
        match = TILE_FILE.match(name)
        if match:
            zooms.add(int(match[1]))
            tiles[int(match[2]), int(match[3])] = cv2.imread(os.path.join(folder, name), cv2.IMREAD_UNCHANGED)
            with open(os.path.join(folder, name), "rb") as handle:
                digest.update(name.encode("ascii") + handle.read())
    if not tiles:
        raise ValueError("Deep Umbra wrote no shadow tile: the height tiles it read are not there.")
    (zoom,) = zooms

    xs = range(min(x for x, _ in tiles), max(x for x, _ in tiles) + 1)
    ys = range(min(y for _, y in tiles), max(y for _, y in tiles) + 1)
    west, north = corner(xs[0], ys[0], zoom)
    east, south = corner(xs[0] + 1, ys[-1] + 1, zoom)
    # As the height mosaic: the rows split the span evenly.
    x_res = (east - west) / TILE_SIZE
    y_res = (south - north) / (TILE_SIZE * len(ys))

    shadow = np.full((len(ys) * TILE_SIZE, len(xs) * TILE_SIZE), np.nan, dtype="float32")
    for (x, y), gray in tiles.items():
        row, column = (y - ys[0]) * TILE_SIZE, (x - xs[0]) * TILE_SIZE
        shadow[row:row + TILE_SIZE, column:column + TILE_SIZE] = gray * (float(minutes) / 255.0)

    path = output_file(f"shadow-{digest.hexdigest()[:16]}.tif")
    profile = {
        "driver": "GTiff", "width": shadow.shape[1], "height": shadow.shape[0], "count": 1,
        "dtype": "float32", "crs": "EPSG:3395", "transform": Affine(x_res, 0.0, west, 0.0, y_res, north),
        "nodata": float("nan"),
        "tiled": True, "blockxsize": TILE_SIZE, "blockysize": TILE_SIZE, "compress": "deflate",
    }
    with rasterio.open(path, "w", **profile) as raster:
        raster.write(shadow, 1)
        raster.set_band_description(1, "accumulated shadow (min)")
        raster.update_tags(zoom=zoom, tile_x=xs[0], tile_y=ys[0], tile_size=TILE_SIZE,
                           season=season, minutes=minutes)
    return rasterio.open(path)
