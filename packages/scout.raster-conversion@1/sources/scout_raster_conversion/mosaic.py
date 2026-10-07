"""The tiles SCOUT's ``convert_raster`` writes, side by side in one raster an
Autark map draws. Curio's own code, beside SCOUT's ``convert_to_raster.py``.

The mosaic is a GeoTIFF in EPSG:3395, one float32 band of heights in metres:
a tile's gray level times the maximum height over 255. Each tile sits where
``compute_tile`` drew it, its corners from SCOUT's ``num2deg`` and
``invtransformer``. A tile ``convert_raster`` did not write, because no
building is near it, is 0, the ground.
"""

import hashlib
import os
import re

import cv2
import numpy as np
import rasterio
from rasterio.transform import Affine

from .convert_to_raster import invtransformer, num2deg

TILE_SIZE = 256
TILE_FILE = re.compile(r"^(\d+)_(\d+)_(\d+)\.png$")


def corner(x, y, zoom):
    """The north-west corner of tile *x*, *y* in EPSG:3395, as ``compute_tile`` finds it."""
    return invtransformer.transform(*num2deg(x, y, zoom))


def mosaic(folder, zoom, max_height, output_file):
    """The tiles in *folder* as one raster, opened. *output_file(name)* names
    where the GeoTIFF is written."""
    tiles = {}
    digest = hashlib.sha1(f"{zoom}:{float(max_height)!r}".encode("ascii"))
    for name in sorted(os.listdir(folder)):
        match = TILE_FILE.match(name)
        if match:
            tiles[int(match[2]), int(match[3])] = cv2.imread(os.path.join(folder, name), cv2.IMREAD_UNCHANGED)
            with open(os.path.join(folder, name), "rb") as handle:
                digest.update(name.encode("ascii") + handle.read())

    xs = range(min(x for x, _ in tiles), max(x for x, _ in tiles) + 1)
    ys = range(min(y for _, y in tiles), max(y for _, y in tiles) + 1)
    west, north = corner(xs[0], ys[0], zoom)
    east, south = corner(xs[0] + 1, ys[-1] + 1, zoom)
    # A row of tiles is a few millionths of a cell taller or shorter than the
    # next in Mercator; the rows split the span evenly.
    x_res = (east - west) / TILE_SIZE
    y_res = (south - north) / (TILE_SIZE * len(ys))

    heights = np.zeros((len(ys) * TILE_SIZE, len(xs) * TILE_SIZE), dtype="float32")
    for (x, y), gray in tiles.items():
        row, column = (y - ys[0]) * TILE_SIZE, (x - xs[0]) * TILE_SIZE
        heights[row:row + TILE_SIZE, column:column + TILE_SIZE] = gray * (float(max_height) / 255.0)

    path = output_file(f"buildings-{digest.hexdigest()[:16]}.tif")
    profile = {
        "driver": "GTiff", "width": heights.shape[1], "height": heights.shape[0], "count": 1,
        "dtype": "float32", "crs": "EPSG:3395", "transform": Affine(x_res, 0.0, west, 0.0, y_res, north),
        "tiled": True, "blockxsize": TILE_SIZE, "blockysize": TILE_SIZE, "compress": "deflate",
    }
    with rasterio.open(path, "w", **profile) as raster:
        raster.write(heights, 1)
        raster.set_band_description(1, "height (m)")
        raster.update_tags(zoom=zoom, tile_x=xs[0], tile_y=ys[0], tile_size=TILE_SIZE, max_height=float(max_height))
    return rasterio.open(path)
