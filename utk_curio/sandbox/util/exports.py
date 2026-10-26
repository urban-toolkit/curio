"""``curio_export(data, name)``: write a node's data to a file it returns.

The file goes where ``curio_output_file`` puts the files a node returns, and
the call returns the file's name, which is the output of a Data Export node:
its Download button reads the file that name names (``util/output_files.py``).

What the data is decides how it is written: a table as CSV, a GeoDataFrame as
GeoJSON, a raster as GeoTIFF, and anything else as JSON. An empty name names
the file after the data (a layer's name, else ``data_export``), and a name with
no extension gets the format's.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import unicodedata

#: The stem of a file whose data carries no name of its own.
DEFAULT_STEM = "data_export"

#: The extension each kind of data is written with (``codec.detect_kind``).
EXTENSIONS = {"dataframe": "csv", "geodataframe": "geojson", "raster": "tif"}
JSON_EXTENSION = "json"

#: The longest name ``curio_output_file`` takes.
MAX_NAME_CHARS = 128

_SEPARATORS = re.compile(r"[\\/]+")
_UNSAFE = re.compile(r"[<>:\"|?*\x00-\x1f\x7f]")
_SPACES = re.compile(r"\s+")
_NOT_PLAIN = re.compile(r"[^A-Za-z0-9._-]")
_LEADING = re.compile(r"^[^A-Za-z0-9]+")
_TRAILING = re.compile(r"[._]+$")


def extension_for(data) -> str:
    """The extension *data* is written with."""
    from utk_curio.sandbox.util.codec import detect_kind

    return EXTENSIONS.get(detect_kind(data), JSON_EXTENSION)


def _plain(text: str) -> str:
    """*text* as one plain file name: letters without their accents, a space
    or a path separator as ``_``, nothing a file name cannot carry, and no
    leading dot (a hidden file) or trailing one (an empty extension)."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = _SEPARATORS.sub(" ", text.strip())
    text = _UNSAFE.sub("", text)
    text = _SPACES.sub("_", text.strip())
    text = _NOT_PLAIN.sub("_", text)
    text = _LEADING.sub("", text)
    return _TRAILING.sub("", text)


def data_name(data) -> str:
    """The name *data* carries of its own: a layer's, as Curio keeps it on a
    GeoDataFrame (``metadata["name"]``) or a table (``attrs["name"]``)."""
    for holder in (getattr(data, "metadata", None), getattr(data, "attrs", None)):
        if isinstance(holder, dict) and isinstance(holder.get("name"), str):
            return holder["name"]
    return ""


def export_name(name, data) -> str:
    """The file *name* names for *data*: made plain, named after the data when
    empty, and given the data's format's extension when it has none."""
    extension = extension_for(data)
    stem = _plain(str(name) if name is not None else "")
    if not stem:
        stem = _plain(data_name(data)) or DEFAULT_STEM
    if "." not in stem:
        return f"{stem[: MAX_NAME_CHARS - len(extension) - 1]}.{extension}"
    return stem[:MAX_NAME_CHARS]


def _json_default(value):
    """What JSON cannot hold, as the nearest value it can."""
    import numpy as np

    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    return str(value)


def write(data, path: str) -> None:
    """Write *data* to *path*, in the format its kind is written in."""
    from utk_curio.sandbox.util.codec import _json_safe_value, detect_kind

    kind = detect_kind(data)
    if kind == "geodataframe":
        data.to_file(path, driver="GeoJSON")
        return
    if kind == "dataframe":
        import pandas as pd

        # A default index (0, 1, 2, ...) says nothing; any other is a column.
        data.to_csv(path, index=not isinstance(data.index, pd.RangeIndex))
        return
    if kind == "raster":
        # A GeoTIFF already is the file; any other raster (a VRT, a window)
        # is written out as one.
        if getattr(data, "driver", None) == "GTiff" and os.path.isfile(str(data.name)):
            shutil.copyfile(data.name, path)
            return
        import rasterio.shutil

        rasterio.shutil.copy(data, path, driver="GTiff")
        return
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(_json_safe_value(data), handle, ensure_ascii=False, default=_json_default)


def export(data, name, output_file) -> str:
    """Write *data* to the file *name* names in the node's output folder
    (*output_file* is the node's ``curio_output_file``) and return the
    file's name."""
    file_name = export_name(name, data)
    write(data, output_file(file_name))
    return file_name
