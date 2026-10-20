"""The Rasterize Buildings node's output, made from the tiles SCOUT's
``convert_raster`` writes. Curio's own code, beside SCOUT's
``convert_to_raster.py``.

``convert_raster`` writes a folder of tiles: 8-bit gray, 256 by 256 pixels,
where 255 is the maximum height, in EPSG:3395 between the tile's corners,
named ``<zoom>_<x>_<y>.png``, the files SCOUT's Deep Umbra shadow model reads.
It writes a tile only where a building is near it.

The node returns those tiles side by side in one GeoTIFF in EPSG:3395, one
float32 band of heights in metres (gray level times the maximum height over
255), on the tiles' own grid, for an Autark map and for Accumulated Shadow
(``model.scout.deep-umbra@1``). A tile ``convert_raster`` did not write is no
data (NaN, which the file names as its no-data value), so it is neither drawn
nor counted, as SCOUT reads only the tiles there are; inside a written tile,
the ground is a height of 0.
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

# Curio's raster helpers: web map tiles side by side in one GeoTIFF, on the
# tiles' own grid, where ``compute_tile`` draws each tile.
from utk_curio.sandbox.util.rasters import mosaic_web_tiles

from .convert_to_raster import convert_raster

TILE_SIZE = 256
MOSAIC_CRS = "EPSG:3395"
TILE_FILE = re.compile(r"^(\d+)_(\d+)_(\d+)\.png$")


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
    """The tiles ``convert_raster`` wrote in *folder*, one row each, by ``x``
    then ``y``: ``zoom``, ``x``, ``y`` and ``png``, the tile's file in base64."""
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
    """The tiles side by side at *path*, as the module docstring describes:
    heights in metres, and no data where no tile was written."""
    zoom = int(tiles["zoom"].iloc[0])
    metres = float(max_height) / 255.0
    heights = {
        (int(row.x), int(row.y)): tile_pixels(row.png).astype("float32") * metres
        for row in tiles.itertuples(index=False)
    }
    return mosaic_web_tiles(
        heights, zoom, path, crs=MOSAIC_CRS, tile_size=TILE_SIZE, dtype="float32",
        fill=float("nan"), nodata=float("nan"), band_descriptions=["height (m)"],
        tags={
            "zoom": zoom, "tile_x": int(tiles["x"].min()), "tile_y": int(tiles["y"].min()),
            "tile_size": TILE_SIZE, "max_height": float(max_height),
        },
    )


def rasterize_buildings(buildings, attribute, zoom, max_height, output_file):
    """The raster of heights for *buildings*: SCOUT's ``convert_raster`` at
    *zoom* and *max_height* on the heights in column *attribute*, its tiles
    side by side. *output_file(name)* names where a file the node returns is
    written."""
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
    return rasterio.open(write_mosaic(tiles, max_height, output_file(mosaic_name(tiles, max_height))))
