"""Web map tiles: where a tile lies, and tiles side by side in one GeoTIFF on
their own grid. Rasterize Buildings writes its mosaic of SCOUT's tiles with
``mosaic_web_tiles``, and Deep Umbra's node (``model.scout.deep-umbra@1``,
whose package names Scout in ``dependencies.packages``) places each tile it
predicts with ``tile_bounds``. The mosaic itself is written by Curio's
``mosaic_rasters``, which Curio Media's Mosaic Rasters writes with too.
"""
from __future__ import annotations

import math

from utk_curio.sandbox.util.rasters import mosaic_rasters


# ---------------------------------------------------------------------------
# Map tiles side by side
# ---------------------------------------------------------------------------

def tile_corner(x, y, zoom):
    """``(lat, lon)`` of the north-west corner of web map tile *x*, *y* at
    *zoom*, in degrees."""
    n = 2.0 ** zoom
    lon_deg = x / n * 360.0 - 180.0
    lat_rad = math.atan(math.sinh(math.pi * (1 - 2 * y / n)))
    lat_deg = math.degrees(lat_rad)
    return (lat_deg, lon_deg)


def tile_bounds(x, y, zoom, crs="EPSG:3395"):
    """``(west, south, east, north)`` of web map tile *x*, *y* at *zoom*, in *crs*."""
    from pyproj import Transformer

    to_crs = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    north_lat, west_lon = tile_corner(x, y, zoom)
    south_lat, east_lon = tile_corner(x + 1, y + 1, zoom)
    west, north = to_crs.transform(west_lon, north_lat)
    east, south = to_crs.transform(east_lon, south_lat)
    return west, south, east, north


def mosaic_web_tiles(tiles, zoom, path, *, crs="EPSG:3395", tile_size=256, dtype="float32", fill=0,
                     nodata=None, band_descriptions=None, tags=None):
    """Web map tiles side by side in one GeoTIFF at *path* (:func:`mosaic_rasters`).

    *tiles* maps ``(x, y)`` to the tile's cells, *tile_size* square, rows from
    north to south. Columns of tiles run west to east with x and rows north to
    south with y; a tile *tiles* lacks inside their span holds *fill*, and the
    file names *nodata*, when given, as its no-data value. The grid
    is the tiles' own in *crs*: it starts at the north-west tile's corner, its
    cells are a tile's width over *tile_size* wide, and its rows split the span
    from the top row's north edge to the bottom row's south edge, so each tile
    sits in its slot within a small fraction of a cell (in a cylindrical
    projection, rows differ in height by a few millionths).
    """
    xs = range(min(x for x, _ in tiles), max(x for x, _ in tiles) + 1)
    ys = range(min(y for _, y in tiles), max(y for _, y in tiles) + 1)
    west, _, east, north = tile_bounds(xs[0], ys[0], zoom, crs)
    _, south, _, _ = tile_bounds(xs[0], ys[-1], zoom, crs)
    x_res, y_res = (east - west) / tile_size, -(north - south) / (tile_size * len(ys))
    pieces = [
        {
            "transform": (x_res, 0.0, west + (x - xs[0]) * tile_size * x_res, 0.0, y_res,
                          north + (y - ys[0]) * tile_size * y_res),
            "width": tile_size, "height": tile_size, "cells": cells,
        }
        for (x, y), cells in tiles.items()
    ]
    return mosaic_rasters(pieces, path, crs=crs, dtype=dtype, resolution=(x_res, y_res), fill=fill,
                          nodata=nodata, band_descriptions=band_descriptions, tags=tags)
