"""Rasters that lie on one grid, side by side in one raster.

``mosaic_rasters`` lays tiles side by side where their corners fall
(``mosaic_grid``): a GDAL VRT that points at their files, or a GeoTIFF of
their cells. ``mosaic_collection`` lays a raster collection's rows side by side
in a VRT: Media's Mosaic Rasters (``curio.media@1``, whose package names
Rasterization in ``dependencies.packages``) returns it. Rasterize Buildings
writes its tiles with ``mosaic_web_tiles`` (``web_tiles.py``), on
``mosaic_rasters``, and Deep Umbra's node (``model.scout.deep-umbra@1``) writes
its shadow with ``mosaic_rasters``.
"""
from __future__ import annotations

import hashlib
import json
import math
from xml.sax.saxutils import escape

import numpy as np
import rasterio
from rasterio.transform import Affine
from rasterio.windows import Window

#: What node code calls.
__all__ = ["mosaic_grid", "mosaic_rasters", "mosaic_collection"]

#: A raster's number type as GDAL names it in a VRT.
GDAL_TYPES = {
    "uint8": "Byte", "int8": "Int8", "uint16": "UInt16", "int16": "Int16",
    "uint32": "UInt32", "int32": "Int32", "float32": "Float32", "float64": "Float64",
}


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
    raster at *path*, which is returned.

    When every tile names its file (``path``), the mosaic is a GDAL VRT that
    points at them: they stay where they are. With a *nodata* value each tile's
    no-data cells are see-through, so where tiles overlap the tile below shows;
    without one, a later tile covers an earlier one.

    When every tile holds its ``cells`` (``(rows, columns)``, or ``(bands,
    rows, columns)``), the mosaic is a GeoTIFF of them in *dtype*, and a part of
    the grid no tile covers holds *fill*.
    """
    grid = mosaic_grid(tiles, resolution)
    if all("path" in tile for tile in tiles):
        return _write_mosaic_vrt(tiles, path, grid, crs=crs, dtype=dtype, bands=bands, nodata=nodata)
    if all("cells" in tile for tile in tiles):
        return _write_mosaic_geotiff(tiles, path, grid, crs=crs, dtype=dtype, bands=bands, nodata=nodata,
                                     fill=fill, band_descriptions=band_descriptions, tags=tags)
    raise ValueError("every tile of a mosaic names its file, or every tile holds its cells")


def _write_mosaic_vrt(tiles, path, grid, *, crs, dtype, bands, nodata):
    west, north, x_res, y_res, size_x, size_y, offsets = grid
    gdal_type = GDAL_TYPES.get(str(dtype), "Float64")
    # With a no-data value, each tile is a ComplexSource whose no-data pixels are
    # see-through; a SimpleSource would copy them over its neighbour.
    source = "ComplexSource" if nodata is not None else "SimpleSource"
    parts = [
        f'<VRTDataset rasterXSize="{size_x}" rasterYSize="{size_y}">',
        f"  <SRS>{escape(crs)}</SRS>",
        f"  <GeoTransform>{west}, {x_res}, 0, {north}, 0, {y_res}</GeoTransform>",
    ]
    for band in range(1, bands + 1):
        parts.append(f'  <VRTRasterBand dataType="{gdal_type}" band="{band}">')
        if nodata is not None:
            parts.append(f"    <NoDataValue>{nodata}</NoDataValue>")
        for (x_off, y_off), tile in zip(offsets, tiles):
            width, height = int(tile["width"]), int(tile["height"])
            parts += [
                f"    <{source}>",
                f'      <SourceFilename relativeToVRT="0">{escape(str(tile["path"]))}</SourceFilename>',
                f"      <SourceBand>{band}</SourceBand>",
                f'      <SrcRect xOff="0" yOff="0" xSize="{width}" ySize="{height}"/>',
                f'      <DstRect xOff="{x_off}" yOff="{y_off}" xSize="{width}" ySize="{height}"/>',
            ]
            if nodata is not None:
                parts.append(f"      <NODATA>{nodata}</NODATA>")
            parts.append(f"    </{source}>")
        parts.append("  </VRTRasterBand>")
    parts.append("</VRTDataset>")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(parts))
    return path


def _write_mosaic_geotiff(tiles, path, grid, *, crs, dtype, bands, nodata, fill, band_descriptions, tags):
    west, north, x_res, y_res, size_x, size_y, offsets = grid
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


def mosaic_collection(tiles, output_file):
    """A raster collection's rows, as ``curio_load_collection`` gives them,
    side by side in one GDAL VRT (:func:`mosaic_rasters`) that
    *output_file(name)* places, opened: Mosaic Rasters' step
    (``curio.media@1``).

    Every tile must be on this machine, georeferenced and north-up, and share
    its CRS, resolution, band count, data type and no-data value; the first
    difference is named.
    """
    tiles = tiles[tiles["kind"] == "raster"]
    if tiles.empty:
        raise ValueError("Mosaic Rasters needs a raster collection's rows")
    missing = tiles[tiles["path"].isna()]
    if not missing.empty:
        raise ValueError(
            f"{missing.iloc[0]['relpath']} is not on this machine yet; cache the collection's files first"
        )
    unplaced = tiles[tiles["transform"].isna()] if "transform" in tiles.columns else tiles
    if not unplaced.empty:
        first = unplaced.iloc[0]
        reason = first.get("probe_error") if isinstance(first.get("probe_error"), str) else "no georeferencing"
        raise ValueError(f"{first['relpath']} cannot be placed on a map: {reason}")
    for column in ("crs", "res", "bands", "dtype", "nodata"):
        if column not in tiles.columns:
            continue
        values = tiles[column].dropna().astype(str).unique()
        if len(values) > 1:
            raise ValueError(f"these tiles differ in {column}: {', '.join(values[:4])}")

    declared = tiles["nodata"].dropna() if "nodata" in tiles.columns else []
    pieces = [
        {"transform": json.loads(transform), "width": width, "height": height, "path": path}
        for transform, width, height, path in zip(tiles["transform"], tiles["width"], tiles["height"], tiles["path"])
    ]
    name = "mosaic-" + hashlib.sha1("\n".join(sorted(tiles["file_id"])).encode()).hexdigest()[:16] + ".vrt"
    path = mosaic_rasters(
        pieces, output_file(name), crs=str(tiles["crs"].iloc[0]), dtype=str(tiles["dtype"].iloc[0]),
        bands=int(tiles["bands"].iloc[0]), nodata=declared.iloc[0] if len(declared) else None,
    )
    return rasterio.open(path)
