"""The Accumulated Shadow node's input and outputs, around SCOUT's Deep Umbra
(``deep_umbra.py``). Curio's own code.

- **input**: a raster of building heights in metres, in EPSG:3395 on the
  zoom-16 tile grid SCOUT's tiles use (256 cells a tile): the mosaic of
  Rasterize Buildings (``scout.raster-conversion@1``), or its ``(mosaic,
  tiles)`` output, of which the node reads the mosaic. Every tile of the raster
  is predicted, from the tile and its eight neighbours; cells beyond the raster
  are ground.
- **mosaic**: the accumulated shadow on the input's own grid, one float32 band
  in minutes (Deep Umbra's output from 0 to 1, times the season's minutes).
- **metrics**: one row, the season and the mean and median accumulated shadow in
  minutes over the ground (cells with no building), as SCOUT's
  ``run_shadow_model`` writes them to its metrics file.

Deep Umbra reads 8-bit heights where 255 is 550 m: a height becomes
``255 * height / 550``, rounded half to even and kept within 0 to 255, as SCOUT's
rasterizer writes it (``cv2.imwrite``), so the heights of Rasterize Buildings'
mosaic give back its tiles' gray levels exactly.
"""

import hashlib
import math

import numpy as np
import pandas as pd
import rasterio
from pyproj import Transformer

from .deep_umbra import TILE, predict_shadow, season_factor, shadow_fraction

#: The Data Catalog dataset that holds Deep Umbra as an ONNX model.
MODEL_ID = "data.scout.deep-umbra"

#: What Deep Umbra was trained on: zoom-16 tiles where 255 is 550 m.
DEEP_UMBRA_ZOOM = 16
DEEP_UMBRA_MAX_HEIGHT = 550.0

#: The seasons SCOUT's code knows (its widget offers spring, summer and winter).
SEASONS = ("spring", "summer", "fall", "winter")

#: SCOUT's tile grid: EPSG:3395, whose x is the WGS 84 semi-major axis times the
#: longitude in radians, so a zoom-z tile is this many metres wide over 2 ** z.
MOSAIC_CRS = "EPSG:3395"
EQUATOR_METRES = 2.0 * math.pi * 6378137.0
#: How far, in cells, a raster's corner may sit from a tile corner.
GRID_SLACK = 0.01

MISSING_MODEL = (
    f"Accumulated Shadow runs SCOUT's Deep Umbra model, the Data Catalog dataset "
    f"{MODEL_ID}@1, and this Curio does not have it. The model is in the Curio "
    "repository (https://github.com/urban-toolkit/curio) but not in the pip package: "
    f"copy the repository's folder datasets/{MODEL_ID}@1 into this Curio's shared "
    "Data Catalog folder (the one --catalog-root names, else the datasets folder "
    "beside the installed utk_curio package), or start Curio from a clone of the "
    "repository, then run this node again."
)

NOT_A_HEIGHT_RASTER = (
    "Accumulated Shadow reads a raster of building heights: connect the output of "
    "Rasterize Buildings (scout.raster-conversion), or a raster of heights in metres "
    "in EPSG:3395 on the zoom-16 tile grid."
)

_TO_4326 = Transformer.from_crs(3395, 4326, always_xy=True)


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


def _is_raster(value):
    return hasattr(value, "read") and hasattr(value, "transform") and hasattr(value, "crs")


def height_raster(value):
    """The one raster in the node's input: the input itself, or the one raster
    among its parts (Rasterize Buildings hands on ``(mosaic, tiles)``)."""
    parts = list(value) if isinstance(value, (list, tuple)) else [value]
    rasters = [part for part in parts if _is_raster(part)]
    if len(rasters) != 1:
        raise ValueError(NOT_A_HEIGHT_RASTER)
    return rasters[0]


def _deg2num(lon_deg, lat_deg, zoom):
    """The tile coordinates of a point, as SCOUT's rasterizer computes them
    (``convert_to_raster.deg2num``), not rounded."""
    n = 2.0 ** zoom
    xtile = (lon_deg + 180.0) / 360.0 * n
    ytile = (1.0 - math.asinh(math.tan(math.radians(lat_deg))) / math.pi) / 2.0 * n
    return xtile, ytile


def tile_grid(raster):
    """``(zoom, x, y, columns, rows)``: the zoom level of the raster's tile grid,
    the tile at its north-west corner, and how many tiles it spans, read from
    its CRS and transform. Refuses, in a sentence that says what to change, a
    raster that is not on SCOUT's tile grid or not at zoom 16."""
    crs = raster.crs.to_epsg() if raster.crs is not None else None
    if crs != 3395:
        shown = f"EPSG:{crs}" if crs else (raster.crs.to_string() if raster.crs else "no CRS")
        raise ValueError(
            f"Deep Umbra reads heights in {MOSAIC_CRS} (World Mercator) on SCOUT's tile grid, "
            f"and this raster is in {shown}. Connect the mosaic of Rasterize Buildings."
        )
    a, b, c, d, e, f = tuple(raster.transform)[:6]
    if b != 0 or d != 0 or a <= 0 or e >= 0:
        raise ValueError(f"{NOT_A_HEIGHT_RASTER} This one is rotated or not north up.")
    level = math.log2(EQUATOR_METRES / (TILE * a))
    zoom = round(level)
    if abs(level - zoom) * TILE > GRID_SLACK:
        raise ValueError(f"{NOT_A_HEIGHT_RASTER} This one's cells are not a tile's 256th.")
    if zoom != DEEP_UMBRA_ZOOM:
        raise ValueError(
            f"Deep Umbra reads zoom-{DEEP_UMBRA_ZOOM} tiles, and this raster is at zoom {zoom}. "
            f"Set Rasterize Buildings' Zoom level to {DEEP_UMBRA_ZOOM}."
        )
    xtile, ytile = _deg2num(*_TO_4326.transform(c, f), zoom)
    x, y = round(xtile), round(ytile)
    if abs(xtile - x) * TILE > GRID_SLACK or abs(ytile - y) * TILE > GRID_SLACK:
        raise ValueError(f"{NOT_A_HEIGHT_RASTER} This one's corner is not a tile's corner.")
    if raster.width % TILE or raster.height % TILE:
        raise ValueError(f"{NOT_A_HEIGHT_RASTER} This one is not a whole number of tiles.")
    tags = raster.tags()
    for name, found in (("zoom", zoom), ("tile_x", x), ("tile_y", y)):
        if name in tags and int(float(tags[name])) != found:
            raise ValueError(
                f"The raster says its {name} is {tags[name]}, and its grid says {found}: "
                "it is not the mosaic Rasterize Buildings wrote."
            )
    return zoom, x, y, raster.width // TILE, raster.height // TILE


def gray_levels(raster):
    """The raster's heights as Deep Umbra's 8-bit levels, float32: ``255 *
    height / 550``, rounded half to even, within 0 to 255; no data is ground.
    Refuses a mosaic Rasterize Buildings drew with another maximum height."""
    tags = raster.tags()
    if "max_height" in tags and float(tags["max_height"]) != DEEP_UMBRA_MAX_HEIGHT:
        raise ValueError(
            f"Deep Umbra reads tiles where 255 is {DEEP_UMBRA_MAX_HEIGHT:g} m, and these were drawn "
            f"with {float(tags['max_height']):g} m. Set Rasterize Buildings' Maximum height to "
            f"{DEEP_UMBRA_MAX_HEIGHT:g}."
        )
    heights = raster.read(1, masked=True).astype(np.float64).filled(np.nan)
    levels = 255.0 * (heights / DEEP_UMBRA_MAX_HEIGHT)
    levels = np.where(np.isfinite(levels), levels, 0.0)
    return np.clip(np.rint(levels), 0, 255).astype(np.float32)


def neighbourhood(padded, column, row):
    """Tile (*column*, *row*) of the raster and its eight neighbours, 768 by
    768, from the raster's levels *padded* by one tile of ground on each side."""
    return padded[row * TILE:(row + 3) * TILE, column * TILE:(column + 3) * TILE]


def shadow_fractions(raster, season, model):
    """Deep Umbra on every tile of *raster*: ``(fraction, ground)``, two arrays
    on the raster's grid: the shadow from 0 to 1, and where there is no building."""
    zoom, x, y, columns, rows = tile_grid(raster)
    levels = gray_levels(raster)
    padded = np.pad(levels, TILE)
    fraction = np.zeros(levels.shape, dtype=np.float32)
    ground = np.zeros(levels.shape, dtype=bool)
    for row in range(rows):
        for column in range(columns):
            input_height, prediction = predict_shadow(
                model, neighbourhood(padded, column, row), season, zoom, x + column, y + row
            )
            block = (slice(row * TILE, (row + 1) * TILE), slice(column * TILE, (column + 1) * TILE))
            fraction[block] = shadow_fraction(prediction)
            ground[block] = input_height == 0
    return fraction, ground


def mosaic_name(raster, season):
    """A file name that follows the heights, their grid and the season."""
    digest = hashlib.sha1(season.encode("ascii"))
    digest.update(repr(tuple(raster.transform)[:6]).encode("ascii"))
    digest.update(raster.read(1).tobytes())
    return f"shadow-{digest.hexdigest()[:16]}.tif"


def accumulated_shadow(value, season, model, output_file):
    """``(mosaic, metrics)`` for the heights in *value*, in *season*, from the
    Deep Umbra session *model*. *output_file(name)* names where a file the node
    returns is written."""
    if season not in SEASONS:
        raise ValueError(f"Accumulated Shadow knows the seasons spring, summer and winter, not {season!r}.")
    raster = height_raster(value)
    zoom, x, y, _columns, _rows = tile_grid(raster)
    fraction, ground = shadow_fractions(raster, season, model)
    factor = season_factor(season)
    minutes = fraction * np.float32(factor)
    every = minutes[ground]
    metrics = pd.DataFrame([{
        "season": season,
        "mean_minutes": float(np.mean(every)),
        "median_minutes": float(np.median(every)),
    }])
    profile = {
        "driver": "GTiff", "width": raster.width, "height": raster.height, "count": 1,
        "dtype": "float32", "crs": raster.crs, "transform": raster.transform, "tiled": True,
        "blockxsize": TILE, "blockysize": TILE, "compress": "deflate",
    }
    path = output_file(mosaic_name(raster, season))
    with rasterio.open(path, "w", **profile) as out:
        out.write(minutes, 1)
        out.set_band_description(1, "accumulated shadow (min)")
        out.update_tags(zoom=zoom, tile_x=x, tile_y=y, tile_size=TILE, season=season, minutes=factor)
    return rasterio.open(path), metrics
