"""The Accumulated Shadow node's input and outputs, around SCOUT's Deep Umbra
(``deep_umbra.py``). Curio's own code.

- **input**: the tiles of Rasterize Buildings (``scout.raster-conversion@1``):
  its ``(mosaic, tiles)`` output, or the tiles table alone. A row per tile, with
  ``zoom``, ``x``, ``y`` and ``png``, the tile's 8-bit gray PNG in base64, where
  255 is 550 m: the files SCOUT's ``run_shadow_model`` reads, named
  ``<zoom>_<x>_<y>.png``.
- **mosaic**: the accumulated shadow of every tile, side by side in one
  GeoTIFF in EPSG:3395 on the tiles' own grid, one float32 band in minutes
  (Deep Umbra's output from 0 to 1, times the season's minutes). A place in the
  mosaic no tile covers is nodata.
- **metrics**: one row, the season and the mean and median accumulated shadow in
  minutes over the ground of every tile (its pixels with no building), as
  SCOUT's ``run_shadow_model`` writes them to its metrics file.
"""

import base64
import hashlib
import math
import os
import shutil
import uuid

import numpy as np
import pandas as pd
import rasterio
from pyproj import Transformer
from rasterio.transform import Affine
from rasterio.windows import Window

from .deep_umbra import predict_tiles, season_factor

#: The Data Catalog dataset that holds Deep Umbra as an ONNX model.
MODEL_ID = "data.scout.deep-umbra"

#: What Deep Umbra was trained on: zoom-16 tiles where 255 is 550 m.
DEEP_UMBRA_ZOOM = 16
DEEP_UMBRA_MAX_HEIGHT = 550.0

#: The seasons SCOUT's code knows (its widget offers spring, summer and winter).
SEASONS = ("spring", "summer", "fall", "winter")

TILE_SIZE = 256
TILE_COLUMNS = ("zoom", "x", "y", "png")
MOSAIC_CRS = "EPSG:3395"

MISSING_MODEL = (
    f"Accumulated Shadow runs SCOUT's Deep Umbra model, the Data Catalog dataset "
    f"{MODEL_ID}@1, and this Curio does not have it. The model is in the Curio "
    "repository (https://github.com/urban-toolkit/curio) but not in the pip package: "
    f"copy the repository's folder datasets/{MODEL_ID}@1 into this Curio's shared "
    "Data Catalog folder (the one --catalog-root names, else the datasets folder "
    "beside the installed utk_curio package), or start Curio from a clone of the "
    "repository, then run this node again."
)

_TO_3395 = Transformer.from_crs(4326, 3395)


def open_model(load):
    """The Deep Umbra session *load* returns, or :data:`MISSING_MODEL` when
    this Curio has no such dataset. *load* is the node's
    ``lambda: curio_load_data("data.scout.deep-umbra")``."""
    try:
        return load()
    except RuntimeError as error:
        if f"'{MODEL_ID}' is not available" not in str(error):
            raise
        raise RuntimeError(MISSING_MODEL) from None


def _is_tiles(value):
    return isinstance(value, pd.DataFrame) and all(column in value.columns for column in TILE_COLUMNS)


def tiles_of(value):
    """``(tiles, max_height)`` from the node's input: the tiles table, and the
    maximum height the tiles were drawn with when a mosaic beside them says so."""
    parts = list(value) if isinstance(value, (list, tuple)) else [value]
    tiles = [part for part in parts if _is_tiles(part)]
    if len(tiles) != 1:
        raise ValueError(
            "Accumulated Shadow reads the tiles of Rasterize Buildings (scout.raster-conversion): "
            "connect its output, or a table with one row per tile and the columns zoom, x, y and png."
        )
    max_height = None
    for part in parts:
        tags = part.tags() if hasattr(part, "tags") and hasattr(part, "transform") else {}
        if "max_height" in tags:
            max_height = float(tags["max_height"])
    return tiles[0], max_height


def check_tiles(tiles, max_height, season):
    """Refuse what Deep Umbra was not trained on, in a sentence that says what to change."""
    if season not in SEASONS:
        raise ValueError(f"Accumulated Shadow knows the seasons spring, summer and winter, not {season!r}.")
    if tiles.empty:
        raise ValueError("Accumulated Shadow has no tiles to read: the buildings layer drew none.")
    zooms = sorted({int(zoom) for zoom in tiles["zoom"]})
    if zooms != [DEEP_UMBRA_ZOOM]:
        shown = ", ".join(str(zoom) for zoom in zooms)
        raise ValueError(
            f"Deep Umbra reads zoom-{DEEP_UMBRA_ZOOM} tiles, and these are zoom {shown}. "
            f"Set Rasterize Buildings' Zoom level to {DEEP_UMBRA_ZOOM}."
        )
    if max_height is not None and max_height != DEEP_UMBRA_MAX_HEIGHT:
        raise ValueError(
            f"Deep Umbra reads tiles where 255 is {DEEP_UMBRA_MAX_HEIGHT:g} m, and these were drawn "
            f"with {max_height:g} m. Set Rasterize Buildings' Maximum height to {DEEP_UMBRA_MAX_HEIGHT:g}."
        )


def write_tiles(tiles, folder):
    """Each row's PNG as ``<zoom>_<x>_<y>.png`` in *folder*, as SCOUT reads them."""
    os.makedirs(folder, exist_ok=True)
    for row in tiles.itertuples(index=False):
        name = f"{int(row.zoom)}_{int(row.x)}_{int(row.y)}.png"
        with open(os.path.join(folder, name), "wb") as handle:
            handle.write(base64.b64decode(row.png))


def _tile_corner(x, y, zoom):
    """``(latitude, longitude)`` of tile *x*, *y*'s north-west corner, as the
    rasterizer computes it (``convert_to_raster.num2deg``)."""
    n = 2.0 ** zoom
    lat_rad = math.atan(math.sinh(math.pi * (1 - 2 * y / n)))
    return math.degrees(lat_rad), x / n * 360.0 - 180.0


def tile_bounds(x, y, zoom):
    """``(west, south, east, north)`` of tile *x*, *y* in EPSG:3395, where the
    rasterizer drew it."""
    west, north = _TO_3395.transform(*_tile_corner(x, y, zoom))
    east, south = _TO_3395.transform(*_tile_corner(x + 1, y + 1, zoom))
    return west, south, east, north


def mosaic_name(tiles, season):
    """A file name that follows the tiles and the season."""
    digest = hashlib.sha1(season.encode("ascii"))
    for row in tiles.itertuples(index=False):
        digest.update(f"{row.zoom}_{row.x}_{row.y}:{row.png}\n".encode("ascii"))
    return f"shadow-{digest.hexdigest()[:16]}.tif"


def write_mosaic(minutes, zoom, season, path):
    """The tiles' shadow, ``{(x, y): 256 by 256 minutes}``, side by side at
    *path*, as the module docstring describes. Rasterize Buildings writes its
    mosaic on the same grid."""
    xs = range(min(x for x, _ in minutes), max(x for x, _ in minutes) + 1)
    ys = range(min(y for _, y in minutes), max(y for _, y in minutes) + 1)
    west, _, east, north = tile_bounds(xs[0], ys[0], zoom)
    _, south, _, _ = tile_bounds(xs[0], ys[-1], zoom)
    width, height = TILE_SIZE * len(xs), TILE_SIZE * len(ys)
    # Every column of tiles has the same width in EPSG:3395. Rows differ in
    # height by a few millionths, so one grid places every tile row within a
    # small fraction of a cell.
    transform = Affine((east - west) / TILE_SIZE, 0.0, west, 0.0, -(north - south) / height, north)
    nodata = np.full((TILE_SIZE, TILE_SIZE), np.nan, dtype="float32")
    profile = {
        "driver": "GTiff", "width": width, "height": height, "count": 1, "dtype": "float32",
        "crs": MOSAIC_CRS, "transform": transform, "nodata": float("nan"), "tiled": True,
        "blockxsize": TILE_SIZE, "blockysize": TILE_SIZE, "compress": "deflate",
    }
    with rasterio.open(path, "w", **profile) as mosaic:
        for x in xs:
            for y in ys:
                cells = minutes.get((x, y))
                cells = nodata if cells is None else np.asarray(cells, dtype="float32")
                window = Window((x - xs[0]) * TILE_SIZE, (y - ys[0]) * TILE_SIZE, TILE_SIZE, TILE_SIZE)
                mosaic.write(cells, 1, window=window)
        mosaic.set_band_description(1, "accumulated shadow (min)")
        mosaic.update_tags(
            zoom=zoom, tile_x=xs[0], tile_y=ys[0], tile_size=TILE_SIZE,
            season=season, minutes=season_factor(season),
        )
    return path


def accumulated_shadow(value, season, model, output_file):
    """``(mosaic, metrics)`` for the tiles in *value*, in *season*, from the
    Deep Umbra session *model*. *output_file(name)* names where a file the node
    returns is written."""
    tiles, max_height = tiles_of(value)
    check_tiles(tiles, max_height, season)
    zoom = DEEP_UMBRA_ZOOM
    factor = season_factor(season)
    work = output_file(f"height-tiles-{uuid.uuid4().hex}")
    minutes = {}
    vals = []
    try:
        write_tiles(tiles, work)
        for _stem, _zoom, x, y, arr_norm, tile_vals, _gray in predict_tiles(work, season, model):
            minutes[(x, y)] = arr_norm * factor
            vals.append(tile_vals)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    every = np.concatenate(vals)
    metrics = pd.DataFrame([{
        "season": season,
        "mean_minutes": float(np.mean(every)),
        "median_minutes": float(np.median(every)),
    }])
    path = write_mosaic(minutes, zoom, season, output_file(mosaic_name(tiles, season)))
    return rasterio.open(path), metrics
