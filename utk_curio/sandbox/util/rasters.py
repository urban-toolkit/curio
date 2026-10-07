"""Rasters between Python nodes and Autark nodes.

A Python node's raster is a rasterio dataset, stored by its file's path. An
Autark node loads a raster from GeoTIFF bytes (autk-db's ``loadGeoTiff``), so
``GET /raster`` serves an artifact's raster as a GeoTIFF, written afresh by GDAL
so that whatever the source is (a GeoTIFF, the VRT Mosaic Rasters writes, a
JPEG 2000 tile) the browser reads one format, with its nodata in the file. The
``X-Curio-Raster`` header describes it: size, bands, CRS, transform, nodata.
A raster larger than the caller can load is refused with its size before any
of it is written.

The other way, an Autark node hands a raster on as autk-db's ``getRaster``
collection, in an envelope (``utils/raster/rasterWire.ts`` in the frontend):
each band base64 of little-endian float32 with rows from south to north, and
the grid the cells lie on. A Python node receives it as a rasterio dataset
rebuilt here on a GeoTIFF file of its own, so Python code keeps Curio's raster
contract: a raster is a ``rasterio.io.DatasetReader``. Both sides run the cases
in ``rasterWire.cases.json``.
"""
from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import sys
import tempfile
from pathlib import Path

#: The response header the raster route describes the raster in, as JSON.
RASTER_META_HEADER = "X-Curio-Raster"

#: The key a band's values are written under in an envelope.
WIRE_BAND_KEY = "float32le"

#: Long WKT is cut to this many characters in the header.
_WKT_CHARS = 256


class RasterRefused(Exception):
    """A raster the route will not serve, with the status and what it read."""

    def __init__(self, status: int, code: str, message: str, meta: dict | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.meta = meta


def _rasterio():
    import rasterio  # an optional library: curio.builtin declares it

    return rasterio


def is_dataset(value) -> bool:
    """Whether *value* is an open rasterio dataset, without importing rasterio."""
    module = sys.modules.get("rasterio")
    return module is not None and isinstance(value, module.io.DatasetReader)


def epsg_name(crs) -> str | None:
    """``EPSG:<code>`` for a CRS that has one, else None."""
    if crs is None:
        return None
    code = crs.to_epsg()
    return f"EPSG:{code}" if code else None


def raster_meta(dataset) -> dict:
    """What the browser needs to know of a raster to load and place it."""
    crs = dataset.crs
    name = epsg_name(crs)
    t = dataset.transform
    nodata = dataset.nodata
    # NaN or an infinity is no number JSON can carry; autk-db reads every
    # non-finite cell as nodata anyway.
    if nodata is not None and not math.isfinite(float(nodata)):
        nodata = None
    return {
        "width": int(dataset.width),
        "height": int(dataset.height),
        "count": int(dataset.count),
        "crs": name,
        "crsWkt": crs.to_wkt()[:_WKT_CHARS] if crs is not None and name is None else None,
        "transform": [t.a, t.b, t.c, t.d, t.e, t.f],
        "nodata": None if nodata is None else float(nodata),
        "dtype": dataset.dtypes[0] if dataset.count else None,
    }


def _close_all(value) -> None:
    for item in value if isinstance(value, (list, tuple)) else (value,):
        if is_dataset(item):
            item.close()


def raster_artifact(art_id, *, session_id=None, part=None):
    """The rasterio dataset an artifact holds, by the one reader rule.

    ``part`` picks one item of a Python tuple. The store first, then a
    project's hydrated copy (``parsers.load_artifact``), as ``/get`` reads.
    """
    from utk_curio.sandbox.util.parsers import load_artifact

    value = load_artifact(art_id, session_id=session_id)
    if part is not None:
        if not isinstance(value, (list, tuple)) or not 0 <= part < len(value):
            _close_all(value)
            raise RasterRefused(404, "not-found", f"artifact {art_id} has no part {part}")
        chosen = value[part]
        _close_all([item for index, item in enumerate(value) if index != part])
        value = chosen
    if not is_dataset(value):
        _close_all(value)
        raise RasterRefused(422, "not-a-raster", f"artifact {art_id} is not a raster")
    return value


def geotiff_bytes(dataset) -> bytes:
    """The raster as GeoTIFF bytes, written by GDAL with its nodata in the file."""
    _rasterio()
    from rasterio.shutil import copy as copy_raster

    with tempfile.TemporaryDirectory(prefix="curio-raster-") as folder:
        target = os.path.join(folder, "raster.tif")
        copy_raster(dataset, target, driver="GTiff", COMPRESS="DEFLATE")
        with open(target, "rb") as handle:
            return handle.read()


def serve_raster(art_id, *, session_id=None, part=None, max_cells=None, max_side=None):
    """``(bytes, meta)`` for the raster route, or :class:`RasterRefused`."""
    dataset = raster_artifact(art_id, session_id=session_id, part=part)
    try:
        meta = raster_meta(dataset)
        width, height = meta["width"], meta["height"]
        if (max_cells and width * height > max_cells) or (max_side and max(width, height) > max_side):
            raise RasterRefused(
                413, "too-large", f"the raster is {width} by {height} cells", meta
            )
        return geotiff_bytes(dataset), meta
    finally:
        dataset.close()


def meta_header(meta: dict) -> str:
    """The header value: JSON, ASCII only, so any HTTP stack carries it."""
    return json.dumps(meta, ensure_ascii=True, allow_nan=False)


# ---------------------------------------------------------------------------
# Autark's raster collection, for a Python node
# ---------------------------------------------------------------------------

def is_raster_envelope(value) -> bool:
    """Whether *value* is an Autark raster envelope: ``{dataType: 'raster', data}``
    whose data is a collection with its grid."""
    if not isinstance(value, dict) or value.get("dataType") != "raster":
        return False
    data = value.get("data")
    return isinstance(data, dict) and data.get("type") == "FeatureCollection" and "grid" in data


def envelope_arrays(envelope):
    """``(grid, band ids, values)`` of an envelope: values as a float32 array of
    shape (bands, height, width), rows from north to south as rasterio reads."""
    import numpy as np

    data = envelope["data"]
    grid = data["grid"]
    width, height = int(grid["width"]), int(grid["height"])
    properties = data["features"][0]["properties"]
    if int(properties.get("rasterResX", -1)) != width or int(properties.get("rasterResY", -1)) != height:
        raise ValueError("the raster's size does not match its grid")
    ids = [str(band["id"]) for band in properties.get("bands") or []]
    if not ids:
        raise ValueError("the raster has no bands")
    planes = []
    for band in ids:
        wire = properties.get(band)
        if not isinstance(wire, dict) or not isinstance(wire.get(WIRE_BAND_KEY), str):
            raise ValueError(f"band {band} holds no values")
        values = np.frombuffer(base64.b64decode(wire[WIRE_BAND_KEY]), dtype="<f4")
        if values.size != width * height:
            raise ValueError(f"band {band} does not hold one value per cell")
        # autk-db keeps row 0 at the south edge; a GeoTIFF starts at the north.
        planes.append(values.reshape(height, width)[::-1])
    return grid, ids, np.stack(planes).astype("float32")


def envelope_transform(grid):
    """The affine transform of an envelope's grid."""
    from affine import Affine

    return Affine(float(grid["resX"]), 0.0, float(grid["originX"]),
                  0.0, float(grid["resY"]), float(grid["originY"]))


def raster_from_envelope(envelope, directory):
    """The rasterio dataset an Autark raster envelope describes, opened from a
    GeoTIFF written into *directory* (named after its content, so the same
    raster is written once)."""
    rasterio = _rasterio()
    from rasterio.crs import CRS

    grid, ids, values = envelope_arrays(envelope)
    digest = hashlib.sha256(
        json.dumps({key: grid[key] for key in sorted(grid)}, sort_keys=True).encode("utf-8")
        + "\0".join(ids).encode("utf-8")
        + values.tobytes()
    ).hexdigest()[:24]
    folder = Path(directory)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"autark-raster-{digest}.tif"
    if not path.exists():
        partial = folder / f".autark-raster-{digest}.{os.getpid()}.tif"
        with rasterio.open(
            partial, "w", driver="GTiff",
            width=int(grid["width"]), height=int(grid["height"]), count=len(ids),
            dtype="float32", crs=CRS.from_user_input(grid["crs"]),
            transform=envelope_transform(grid), nodata=float("nan"),
        ) as target:
            target.write(values)
            for index, band in enumerate(ids, start=1):
                target.set_band_description(index, band)
        os.replace(partial, path)
    return rasterio.open(path)


def rasters_for_python(value, directory):
    """A Python node's input with each Autark raster envelope in it, at the top
    or one of its parts, made a rasterio dataset; anything else as it came.

    *directory* is where the rebuilt files go, or a function that returns it,
    called only when there is one to write.
    """
    def folder():
        return directory() if callable(directory) else directory

    if is_raster_envelope(value):
        return raster_from_envelope(value, folder())
    if isinstance(value, (list, tuple)) and any(is_raster_envelope(item) for item in value):
        target = folder()
        items = [raster_from_envelope(item, target) if is_raster_envelope(item) else item
                 for item in value]
        return tuple(items) if isinstance(value, tuple) else items
    return value


def python_raster_dir() -> Path:
    """Where an in-process run writes the rasters it rebuilds: beside the
    artifacts, so a node that returns one hands on a file that stays."""
    from utk_curio.sandbox.util.parsers import _shared_data_dir

    folder = _shared_data_dir() / "artifacts"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


# ---------------------------------------------------------------------------
# A window of a raster
# ---------------------------------------------------------------------------

def window_of(dataset, bounds, name: str):
    """The window of *dataset* that ``bounds = (west, south, east, north)``, in
    the raster's CRS, covers: the whole cells whose centres lie inside the
    bounds, on the raster's own grid. Refused, in a sentence, when the bounds
    are not a box, when they reach past the raster, or when they hold no cell's
    centre."""
    from rasterio.windows import Window

    try:
        west, south, east, north = (float(value) for value in bounds)
    except (TypeError, ValueError):
        raise ValueError(
            f"bounds are four numbers, (west, south, east, north), in {name}'s CRS, not {bounds!r}."
        ) from None
    if not all(math.isfinite(v) for v in (west, south, east, north)) or west >= east or south >= north:
        raise ValueError(
            f"bounds {(west, south, east, north)} are not (west, south, east, north) with west "
            "less than east and south less than north."
        )
    t = dataset.transform
    if t.b != 0 or t.d != 0:
        raise ValueError(f"{name} is rotated, so bounds cannot pick a window of it; warp it to a north-up grid first.")
    cols = sorted(((west - t.c) / t.a, (east - t.c) / t.a))
    rows = sorted(((north - t.f) / t.e, (south - t.f) / t.e))
    first_col, last_col = math.ceil(cols[0] - 0.5), math.floor(cols[1] - 0.5)
    first_row, last_row = math.ceil(rows[0] - 0.5), math.floor(rows[1] - 0.5)
    covers = dataset.bounds
    crs = epsg_name(dataset.crs) or "its CRS"
    if first_col < 0 or first_row < 0 or last_col >= dataset.width or last_row >= dataset.height:
        raise ValueError(
            f"bounds {(west, south, east, north)} reach past {name}, which covers west {covers.left}, "
            f"south {covers.bottom}, east {covers.right} and north {covers.top} in {crs}. "
            "Pick bounds inside it."
        )
    if last_col < first_col or last_row < first_row:
        raise ValueError(f"bounds {(west, south, east, north)} hold no cell centre of {name}; widen them.")
    return Window(first_col, first_row, last_col - first_col + 1, last_row - first_row + 1)


def read_window(dataset, bounds, output_file, *, name: str = "the raster"):
    """The cells of *dataset* inside *bounds* (:func:`window_of`), every band
    at the raster's own number type, nodata and cell size, as a rasterio
    dataset of their own: a GeoTIFF *output_file(name)* places, named after its
    content."""
    rasterio = _rasterio()

    window = window_of(dataset, bounds, name)
    values = dataset.read(window=window)
    transform = dataset.window_transform(window)
    profile = {
        "driver": "GTiff",
        "width": int(window.width),
        "height": int(window.height),
        "count": int(dataset.count),
        "dtype": dataset.dtypes[0],
        "crs": dataset.crs,
        "transform": transform,
        "nodata": dataset.nodata,
        "compress": "deflate",
    }
    digest = hashlib.sha256(
        json.dumps([list(transform)[:6], str(dataset.crs), repr(dataset.nodata), values.dtype.str,
                    list(values.shape)]).encode("utf-8")
        + values.tobytes()
    ).hexdigest()[:24]
    path = output_file(f"window-{digest}.tif")
    if not os.path.exists(path):
        partial = f"{path}.{os.getpid()}.partial"
        with rasterio.open(partial, "w", **profile) as target:
            target.write(values)
            for index, description in enumerate(dataset.descriptions, start=1):
                if description:
                    target.set_band_description(index, description)
            target.update_tags(**dataset.tags())
        os.replace(partial, path)
    return rasterio.open(path)


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


# ---------------------------------------------------------------------------
# Rasters on one grid, side by side
# ---------------------------------------------------------------------------

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
    from xml.sax.saxutils import escape

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
    import numpy as np
    from rasterio.transform import Affine
    from rasterio.windows import Window

    rasterio = _rasterio()
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
    """Mosaic Rasters' step (``curio.media@1``): a raster collection's rows, as
    ``curio_load_collection`` gives them, side by side in one GDAL VRT
    (:func:`mosaic_rasters`) that *output_file(name)* places, opened.

    Every tile must be on this machine, georeferenced and north-up, and share
    its CRS, resolution, band count, data type and no-data value; the first
    difference is named.
    """
    rasterio = _rasterio()
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
