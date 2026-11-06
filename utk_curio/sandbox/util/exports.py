"""``curio_export(data, name, part=None)``: write a node's data to a file it returns.

The file goes where ``curio_output_file`` puts the files a node returns, and
the call returns the file's name, which is the output of a Data Export node:
its Download button reads the file that name names (``util/output_files.py``).

What the data is decides how it is written: a table as CSV, a GeoDataFrame as
GeoJSON, a raster as GeoTIFF, a tuple, list or dict that holds a table or a
raster (a bundle's parts) as one zip of its parts (``util/bundle_zip.py``),
and anything else as JSON. Nothing is written as its text: JSON refuses a
table, a raster or any other object it cannot hold. ``part`` writes one part
of a tuple, list or dict, named by its label, its key or its position, in its
own format; empty, it writes every part.

An empty name is ``data_export``, which the node's Download names after what
feeds the node (``utils/dataExportTarget.ts`` in the canvas). The file's
extension is its format's: a name with none gets it, and a name ending in
another data format's (``trees.csv`` for a GeoDataFrame) gets it in that one's
place, so a file's name never says a format its bytes are not.
"""

from __future__ import annotations

import datetime
import decimal
import json
import os
import pathlib
import re
import shutil
import unicodedata
import uuid

#: The stem of a file whose data carries no name of its own.
DEFAULT_STEM = "data_export"

#: The extensions a file of each kind of data may end in (``codec.detect_kind``),
#: the one it is given first.
EXTENSIONS = {"dataframe": ("csv",), "geodataframe": ("geojson", "json"), "raster": ("tif", "tiff")}
JSON_EXTENSIONS = ("json",)
ZIP_EXTENSIONS = ("zip",)

#: The values JSON writes as their text, which is what they are.
_TEXT_VALUES = (datetime.date, datetime.time, datetime.timedelta, decimal.Decimal, uuid.UUID, pathlib.PurePath)

#: The extensions of data formats: a name ending in one that is not its data's
#: format's has it replaced by the format's. Any other ending, ``trees.v2``,
#: is part of the name, and the format's extension follows it.
DATA_EXTENSIONS = frozenset({
    "csv", "tsv", "txt", "json", "geojson", "tif", "tiff", "parquet", "gpkg",
    "shp", "zip", "xlsx", "xls", "nc", "pbf", "xml", "kml", "gml",
})

#: The longest name ``curio_output_file`` takes.
MAX_NAME_CHARS = 128

_SEPARATORS = re.compile(r"[\\/]+")
_UNSAFE = re.compile(r"[<>:\"|?*\x00-\x1f\x7f]")
_SPACES = re.compile(r"\s+")
_NOT_PLAIN = re.compile(r"[^A-Za-z0-9._-]")
_LEADING = re.compile(r"^[^A-Za-z0-9]+")
_TRAILING = re.compile(r"[._]+$")


def extensions_for(data) -> tuple:
    """The extensions a file of *data* may end in, the one it is given first."""
    from utk_curio.sandbox.util.bundle_zip import holds_parts
    from utk_curio.sandbox.util.codec import detect_kind

    if holds_parts(data):
        return ZIP_EXTENSIONS
    return EXTENSIONS.get(detect_kind(data), JSON_EXTENSIONS)


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


def export_name(name, data) -> str:
    """The file *name* names for *data*: made plain, ``data_export`` when
    empty, and ending in the extension of the format *data* is written in."""
    extensions = extensions_for(data)
    stem = _plain(str(name) if name is not None else "") or DEFAULT_STEM
    base, dot, ending = stem.rpartition(".")
    if dot and ending.lower() in extensions:
        stem, extension = base, ending
    else:
        if dot and ending.lower() in DATA_EXTENSIONS:
            stem = _TRAILING.sub("", base) or DEFAULT_STEM
        extension = extensions[0]
    return f"{stem[: MAX_NAME_CHARS - len(extension) - 1]}.{extension}"


def _json_default(value):
    """What JSON cannot hold, as the nearest value it can: a numpy number or
    array as one, a date, a time, a decimal, a UUID or a path as its text. A
    table, a raster or any other object is refused, saying what it is: its
    text is no data (a table's is its preview)."""
    import numpy as np

    from utk_curio.sandbox.util.codec import _json_safe_value, named_type

    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, np.ndarray):
        return _json_safe_value(value.tolist())
    if isinstance(value, (np.datetime64, np.timedelta64, _TEXT_VALUES)):
        return str(value)
    raise TypeError(
        "curio_export writes a table, a GeoDataFrame, a raster or a JSON value, and the data "
        f"holds {named_type(value)}, which is none of them."
    )


def write(data, path: str) -> None:
    """Write *data* to *path*, in the format its kind is written in. A tuple,
    list or dict that holds a table or a raster is a zip of its parts
    (``bundle_zip``)."""
    from utk_curio.sandbox.util import bundle_zip
    from utk_curio.sandbox.util.codec import _json_safe_value, detect_kind

    if bundle_zip.holds_parts(data):
        bundle_zip.write_zip(path, *bundle_zip.parts_of(data))
        return
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
    # Whole before the file is opened, so a value JSON refuses leaves none.
    text = json.dumps(_json_safe_value(data), ensure_ascii=False, default=_json_default)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


def export(data, name, output_file, part=None) -> str:
    """Write *data*, or the one part of it *part* names (``bundle_zip.pick``;
    None or empty for all of it), to the file *name* names in the node's
    output folder (*output_file* is the node's ``curio_output_file``) and
    return the file's name."""
    if part is not None and part != "":
        from utk_curio.sandbox.util.bundle_zip import pick

        data = pick(data, part)
    file_name = export_name(name, data)
    write(data, output_file(file_name))
    return file_name
