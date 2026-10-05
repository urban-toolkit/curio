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
