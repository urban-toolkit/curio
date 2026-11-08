"""Web map tiles: where a tile lies, and tiles side by side in one GeoTIFF on
their own grid. Rasterize Buildings writes its mosaic of SCOUT's tiles with
``mosaic_web_tiles``, and Deep Umbra's node (``model.scout.deep-umbra@1``,
whose package names Rasterization in ``dependencies.packages``) places each tile it
predicts with ``tile_bounds`` and writes them side by side with ``mosaic_rasters``.
"""
from __future__ import annotations

import math


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


# ---------------------------------------------------------------------------
# Rasters on one grid, side by side
# ---------------------------------------------------------------------------

def mosaic_grid(tiles, resolution=None):
    """``(west, north, x_res, y_res, width, height, offsets)``: the grid
    *tiles* make side by side, and where each one's top-left cell lands on it.

    Each tile is a dict with its ``transform`` (rasterio's order, a to f),
    ``width`` and ``height``. The grid starts at the tiles' north-west corner,
    its cells are *resolution* ``(x, y)`` in size, else the first tile's, and
    it reaches the farthest tile's far edge. A tile goes where its corner falls,
    to the nearest cell. A rotated tile is refused.
    """
    transforms = [tuple(tile["transform"])[:6] for tile in tiles]
    if any(abs(t[1]) > 1e-12 or abs(t[3]) > 1e-12 for t in transforms):
        raise ValueError("a tile is rotated; only north-up tiles make a mosaic")
    x_res, y_res = resolution or (transforms[0][0], transforms[0][4])
    extents = []
    for t, tile in zip(transforms, tiles):
        x0, y0 = t[2], t[5]
        extents.append((x0, y0 + int(tile["height"]) * t[4], x0 + int(tile["width"]) * t[0], y0))
    west = min(e[0] for e in extents)
    south = min(e[1] for e in extents)
    east = max(e[2] for e in extents)
    north = max(e[3] for e in extents)
    size_x = int(math.ceil((east - west) / x_res - 1e-9))
    size_y = int(math.ceil((north - south) / -y_res - 1e-9))
    offsets = [
        (int(round((x0 - west) / x_res)), int(round((north - y0) / -y_res))) for x0, _s, _e, y0 in extents
    ]
    return west, north, x_res, y_res, size_x, size_y, offsets


def mosaic_rasters(tiles, path, *, crs, dtype, bands=1, nodata=None, resolution=None, fill=0,
                   band_descriptions=None, tags=None):
    """Rasters that lie on one grid (:func:`mosaic_grid`), side by side in one
    GeoTIFF at *path*, which is returned.

    Every tile holds its ``cells`` (``(rows, columns)``, or ``(bands, rows,
    columns)``), written in *dtype*; a part of the grid no tile covers holds
    *fill*, and the file names *nodata*, when given, as its no-data value.
    """
    import numpy as np
    import rasterio
    from rasterio.transform import Affine
    from rasterio.windows import Window

    west, north, x_res, y_res, size_x, size_y, offsets = mosaic_grid(tiles, resolution)
    if not all("cells" in tile for tile in tiles):
        raise ValueError("every tile of a mosaic holds its cells")
    sizes = {(int(tile["width"]), int(tile["height"])) for tile in tiles}
    tile_w, tile_h = next(iter(sizes))
    # Tiles of one size, each in its own slot of the grid: written slot by
    # slot, the GeoTIFF's blocks being the tiles.
    regular = len(sizes) == 1 and all(x % tile_w == 0 and y % tile_h == 0 for x, y in offsets)
    profile = {
        "driver": "GTiff", "width": size_x, "height": size_y, "count": bands, "dtype": dtype,
        "crs": crs, "transform": Affine(x_res, 0.0, west, 0.0, y_res, north),
    }
    if regular and tile_w % 16 == 0 and tile_h % 16 == 0:
        profile.update({"tiled": True, "blockxsize": tile_w, "blockysize": tile_h})
    profile["compress"] = "deflate"
    if nodata is not None:
        profile["nodata"] = nodata

    def planes(tile):
        cells = np.asarray(tile["cells"], dtype=dtype)
        return cells[np.newaxis] if cells.ndim == 2 else cells

    with rasterio.open(path, "w", **profile) as mosaic:
        if regular:
            by_slot = dict(zip(offsets, tiles))
            blank = np.full((tile_h, tile_w), fill, dtype=dtype)
            for column in range(0, size_x, tile_w):
                for row in range(0, size_y, tile_h):
                    tile = by_slot.get((column, row))
                    window = Window(column, row, tile_w, tile_h)
                    for band in range(bands):
                        mosaic.write(blank if tile is None else planes(tile)[band], band + 1, window=window)
        else:
            mosaic.write(np.full((bands, size_y, size_x), fill, dtype=dtype))
            for (x_off, y_off), tile in zip(offsets, tiles):
                cells = planes(tile)
                mosaic.write(cells, window=Window(x_off, y_off, cells.shape[2], cells.shape[1]))
        for index, description in enumerate(band_descriptions or (), start=1):
            if description:
                mosaic.set_band_description(index, description)
        if tags:
            mosaic.update_tags(**tags)
    return path
