"""The Rasterize Buildings node's two outputs, made from the tiles SCOUT's
``convert_raster`` writes. Curio's own code, beside SCOUT's
``convert_to_raster.py``.

- **tiles**: one row per tile ``convert_raster`` writes: ``zoom``, ``x``,
  ``y`` and ``png``, the tile's PNG file in base64. 8-bit gray, 256 by 256
  pixels, where 255 is the maximum height, in EPSG:3395 between the tile's
  corners: the files SCOUT's Deep Umbra shadow model reads, named
  ``<zoom>_<x>_<y>.png``.
- **mosaic**: the tiles side by side in one GeoTIFF in EPSG:3395, one float32
  band of heights in metres (gray level times the maximum height over 255),
  for an Autark map. A tile ``convert_raster`` does not write, because no
  building is near it, is 0, the ground.
"""

import base64
import hashlib
import io
import os
import re
import shutil
import uuid

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from PIL import Image
from rasterio.transform import Affine
from rasterio.windows import Window

from .convert_to_raster import convert_raster, invtransformer, num2deg

TILE_SIZE = 256
MOSAIC_CRS = "EPSG:3395"
TILE_FILE = re.compile(r"^(\d+)_(\d+)_(\d+)\.png$")


def tile_bounds(x, y, zoom):
    """``(west, south, east, north)`` of tile *x*, *y* in EPSG:3395: the box
    ``compute_tile`` draws the tile over."""
    north_lat, west_lon = num2deg(x, y, zoom)
    south_lat, east_lon = num2deg(x + 1, y + 1, zoom)
    west, north = invtransformer.transform(north_lat, west_lon)
    east, south = invtransformer.transform(south_lat, east_lon)
    return west, south, east, north


def height_layer(buildings, attribute):
    """*buildings* as ``convert_raster`` reads a layer: one ``height`` column
    taken from *attribute*, a fresh index, and only rows with a geometry."""
    if not isinstance(buildings, gpd.GeoDataFrame):
        raise ValueError("Rasterize Buildings needs a buildings layer, a GeoDataFrame of polygons.")
    if buildings.crs is None:
        raise ValueError(
            "The buildings layer has no CRS. Set one in the node that makes it, "
            "for example gdf.set_crs(4326) for longitude and latitude."
        )
    if attribute not in buildings.columns:
        columns = ", ".join(str(c) for c in buildings.columns if c != buildings.geometry.name)
        raise ValueError(f"The buildings layer has no column '{attribute}'. Its columns: {columns}.")
    layer = gpd.GeoDataFrame(
        {"height": pd.to_numeric(buildings[attribute], errors="coerce").to_numpy(dtype="float64")},
        geometry=buildings.geometry.to_numpy(),
        crs=buildings.crs,
    )
    layer = layer[layer.geometry.notna() & ~layer.geometry.is_empty].reset_index(drop=True)
    if layer.empty:
        raise ValueError("The buildings layer has no geometries to rasterize.")
    return layer


def read_tiles(folder):
    """The tiles in *folder*, one row each, by ``x`` then ``y``."""
    rows = []
    for name in os.listdir(folder):
        match = TILE_FILE.match(name)
        if not match:
            continue
        with open(os.path.join(folder, name), "rb") as handle:
            png = base64.b64encode(handle.read()).decode("ascii")
        zoom, x, y = (int(part) for part in match.groups())
        rows.append({"zoom": zoom, "x": x, "y": y, "png": png})
    tiles = pd.DataFrame(rows, columns=["zoom", "x", "y", "png"])
    return tiles.sort_values(["x", "y"], ignore_index=True)


def tile_pixels(png):
    """A tile's 256 by 256 gray levels, from its ``png`` value."""
    with Image.open(io.BytesIO(base64.b64decode(png))) as image:
        return np.asarray(image)


def mosaic_name(tiles, max_height):
    """A file name that follows the tiles' content."""
    digest = hashlib.sha1(f"{float(max_height)!r}".encode("ascii"))
    for row in tiles.itertuples(index=False):
        digest.update(f"{row.zoom}_{row.x}_{row.y}:{row.png}\n".encode("ascii"))
    return f"buildings-{digest.hexdigest()[:16]}.tif"


def write_mosaic(tiles, max_height, path):
    """The tiles side by side at *path*, as the module docstring describes."""
    zoom = int(tiles["zoom"].iloc[0])
    xs = range(int(tiles["x"].min()), int(tiles["x"].max()) + 1)
    ys = range(int(tiles["y"].min()), int(tiles["y"].max()) + 1)
    west, _, east, north = tile_bounds(xs[0], ys[0], zoom)
    _, south, _, _ = tile_bounds(xs[0], ys[-1], zoom)
    width, height = TILE_SIZE * len(xs), TILE_SIZE * len(ys)
    # Every column of tiles has the same width in EPSG:3395. Rows differ in
    # height by a few millionths, so one grid places every tile row within a
    # small fraction of a cell.
    transform = Affine((east - west) / TILE_SIZE, 0.0, west, 0.0, -(north - south) / height, north)
    pixels = {(int(row.x), int(row.y)): tile_pixels(row.png) for row in tiles.itertuples(index=False)}
    metres = float(max_height) / 255.0
    ground = np.zeros((TILE_SIZE, TILE_SIZE), dtype="float32")
    profile = {
        "driver": "GTiff", "width": width, "height": height, "count": 1, "dtype": "float32",
        "crs": MOSAIC_CRS, "transform": transform, "tiled": True,
        "blockxsize": TILE_SIZE, "blockysize": TILE_SIZE, "compress": "deflate",
    }
    with rasterio.open(path, "w", **profile) as mosaic:
        for x in xs:
            for y in ys:
                gray = pixels.get((x, y))
                cells = ground if gray is None else gray.astype("float32") * metres
                window = Window((x - xs[0]) * TILE_SIZE, (y - ys[0]) * TILE_SIZE, TILE_SIZE, TILE_SIZE)
                mosaic.write(cells, 1, window=window)
        mosaic.set_band_description(1, "height (m)")
        mosaic.update_tags(zoom=zoom, tile_x=xs[0], tile_y=ys[0], tile_size=TILE_SIZE, max_height=float(max_height))
    return path


def rasterize_buildings(buildings, attribute, zoom, max_height, output_file):
    """``(mosaic, tiles)`` for *buildings*: SCOUT's ``convert_raster`` at
    *zoom* and *max_height* on the heights in column *attribute*.
    *output_file(name)* names where a file the node returns is written."""
    layer = height_layer(buildings, attribute)
    # convert_raster empties the folder it is given, so it gets one of its own.
    work = output_file(f"tiles-{uuid.uuid4().hex}")
    try:
        convert_raster(layer, "height", int(zoom), work, max_height=float(max_height))
        tiles = read_tiles(work)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    if tiles.empty:
        raise ValueError("No tile holds a building; check the layer's geometries and CRS.")
    path = write_mosaic(tiles, max_height, output_file(mosaic_name(tiles, max_height)))
    return rasterio.open(path), tiles
