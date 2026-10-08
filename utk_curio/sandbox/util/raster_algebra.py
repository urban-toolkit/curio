"""Raster algebra: operations over rasters on one grid, cell by cell, and a
raster's statistics.

The one implementation behind the Raster Calculator and Raster Statistics
nodes (``curio_raster_calculate``, ``curio_raster_statistics``) and Compare
Scenarios' Difference of two rasters (``scenario_difference.py``).

Rasters are combined only on one grid: the same size, origin, cell size and
CRS. Anything else is refused with a sentence that names both, since putting
one raster on another's grid is a choice the user makes, not one made here.

A cell is nodata where its raster holds its nodata value or a number that is
not finite. An operation gives nodata where an input it reads there is nodata,
and a result marks nodata as NaN.

It works on two kinds of raster:

- a rasterio dataset, what a Python node and the Data Catalog hand on: an
  operation computes at the inputs' own number type (at least float32), so a
  float64 raster keeps every digit, and writes its result as a GeoTIFF the node
  returns;
- an Autark raster envelope (``utils/raster/rasterWire.ts``): the float32
  bands autk-db's ``getRaster`` exports. Compare Scenarios subtracts two of
  them, because its output is the envelope its map, a reopen and a dashboard
  tile read.

The numbers in a refusal are written as JavaScript writes them, so a sentence
reads the same whichever side made it.
"""
from __future__ import annotations

import base64
import hashlib
import math
import warnings
from decimal import Decimal

#: What ``curio_raster_calculate`` does, and how many rasters each operation reads.
ARITHMETIC = ("add", "subtract", "multiply", "divide")
CHOOSE = "choose"
OPERATIONS = ARITHMETIC + (CHOOSE,)

#: The columns of ``curio_raster_statistics``' one row.
STATISTICS = ("mean", "median", "min", "max", "count")

#: How close two grid coordinates must be to count as the same.
RELATIVE_TOLERANCE = 1e-9

#: The key a band's values are written under in an envelope
#: (``WIRE_BAND_KEY`` in ``utils/raster/rasterWire.ts``).
WIRE_BAND_KEY = "float32le"


class RasterAlgebraError(ValueError):
    """An operation the rasters cannot take, with the reason in a sentence."""


# ---------------------------------------------------------------------------
# Numbers and grids in words
# ---------------------------------------------------------------------------

def js_number(value) -> str:
    """*value* as JavaScript's ``String(number)`` writes it: ``30`` for 30.0,
    ``1e-7`` for 0.0000001, ``0`` for -0."""
    x = float(value)
    if math.isnan(x):
        return "NaN"
    if math.isinf(x):
        return "Infinity" if x > 0 else "-Infinity"
    if x == 0:
        return "0"
    sign = "-" if x < 0 else ""
    # The shortest digits that read back as x, which JavaScript also writes.
    _sign, digit_tuple, exponent = Decimal(repr(abs(x))).as_tuple()
    digits = "".join(str(d) for d in digit_tuple)
    stripped = digits.rstrip("0")
    exponent += len(digits) - len(stripped)
    digits = stripped
    k = len(digits)
    n = exponent + k
    if k <= n <= 21:
        text = digits + "0" * (n - k)
    elif 0 < n <= 21:
        text = digits[:n] + "." + digits[n:]
    elif -6 < n <= 0:
        text = "0." + "0" * (-n) + digits
    else:
        power = n - 1
        mark = "+" if power >= 0 else "-"
        mantissa = digits if k == 1 else digits[0] + "." + digits[1:]
        text = f"{mantissa}e{mark}{abs(power)}"
    return sign + text


def _same(a: float, b: float) -> bool:
    return abs(a - b) <= RELATIVE_TOLERANCE * max(1.0, abs(a), abs(b))


def grid_differences(a: dict, b: dict) -> list[str]:
    """What differs between two grids: ``size``, ``origin``, ``resolution``,
    ``rotation`` (a dataset's only), ``CRS``."""
    differs = []
    if a["width"] != b["width"] or a["height"] != b["height"]:
        differs.append("size")
    if not _same(a["originX"], b["originX"]) or not _same(a["originY"], b["originY"]):
        differs.append("origin")
    if not _same(a["resX"], b["resX"]) or not _same(a["resY"], b["resY"]):
        differs.append("resolution")
    if not _same(a.get("rotX", 0.0), b.get("rotX", 0.0)) or not _same(a.get("rotY", 0.0), b.get("rotY", 0.0)):
        differs.append("rotation")
    if str(a["crs"]).upper() != str(b["crs"]).upper():
        differs.append("CRS")
    return differs


def describe_grid(grid: dict) -> str:
    """A grid in words: ``40 by 30 cells of 30 by 30 in EPSG:32616 from (447000, 4637000)``."""
    crs = grid.get("crs")
    if not crs:
        where = "with no CRS"
    elif str(crs).upper().startswith("EPSG:"):
        where = f"in {crs}"
    else:
        where = "in a CRS with no EPSG code"
    return (
        f"{js_number(grid['width'])} by {js_number(grid['height'])} cells of "
        f"{js_number(grid['resX'])} by {js_number(abs(grid['resY']))} {where} "
        f"from ({js_number(grid['originX'])}, {js_number(grid['originY'])})"
    )


def _refuse_grids(what: str, names: list[str], grids: list[dict]) -> None:
    """Refuse *what* when the grids of the rasters named *names* differ: the
    first that differs from the first raster is named with it."""
    for name, grid in zip(names[1:], grids[1:]):
        differs = grid_differences(grids[0], grid)
        if differs:
            raise RasterAlgebraError(
                f"{what} cannot be computed: their grids differ in {', '.join(differs)}. "
                f"{names[0]} is {describe_grid(grids[0])}; {name} is {describe_grid(grid)}. "
                "Put both on one grid first."
            )


# ---------------------------------------------------------------------------
# Cells: values with their nodata as a mask
# ---------------------------------------------------------------------------

def _np():
    import numpy as np

    return np


def in_codes(classes, codes):
    """Where a masked array of classes holds one of *codes*; a nodata class is no class."""
    np = _np()
    return np.isin(np.ma.getdata(classes), list(codes or ())) & ~np.ma.getmaskarray(classes)


def operate(operation: str, values: list, codes=None):
    """*operation* on masked arrays of one shape (float ones for the values it
    computes with): a plain array, NaN where the result is nodata."""
    np = _np()
    if operation == CHOOSE:
        classes, chosen, other = values
        wanted = in_codes(classes, codes)
        result = np.where(wanted, np.ma.getdata(chosen), np.ma.getdata(other))
        nodata = np.where(wanted, np.ma.getmaskarray(chosen), np.ma.getmaskarray(other))
    else:
        a, b = values
        left, right = np.ma.getdata(a), np.ma.getdata(b)
        nodata = np.ma.getmaskarray(a) | np.ma.getmaskarray(b)
        with np.errstate(all="ignore"):
            if operation == "add":
                result = left + right
            elif operation == "subtract":
                result = left - right
            elif operation == "multiply":
                result = left * right
            else:
                result = left / right
                nodata = nodata | (right == 0)
    with np.errstate(all="ignore"):
        nodata = nodata | ~np.isfinite(result)
    return np.where(nodata, np.nan, result)


def _reads(operation: str) -> int:
    if operation in ARITHMETIC:
        return 2
    if operation == CHOOSE:
        return 3
    raise RasterAlgebraError(
        f"The Raster Calculator has no operation {operation!r}. Its operations: {', '.join(OPERATIONS)}."
    )


def _codes(operation: str, codes):
    if operation != CHOOSE:
        if codes:
            raise RasterAlgebraError(f"Only {CHOOSE} reads codes; {operation} takes none.")
        return None
    if codes is None:
        raise RasterAlgebraError(
            f"{CHOOSE} takes input_1 where input_0's class is one of codes, and input_2 elsewhere: "
            "give the codes, for example codes=[21, 31]."
        )
    if isinstance(codes, (int, float)):
        codes = [codes]
    try:
        values = [float(code) for code in codes]
    except (TypeError, ValueError):
        raise RasterAlgebraError(f"codes are numbers, such as [21, 31], not {codes!r}.") from None
    return values


# ---------------------------------------------------------------------------
# rasterio datasets
# ---------------------------------------------------------------------------

def is_dataset(value) -> bool:
    from utk_curio.sandbox.util.rasters import is_dataset as _is

    return _is(value)


def dataset_grid(dataset) -> dict:
    """The grid a dataset's cells lie on, as an envelope names it."""
    from utk_curio.sandbox.util.rasters import epsg_name

    t = dataset.transform
    crs = dataset.crs
    name = epsg_name(crs) or (crs.to_wkt() if crs is not None else None)
    return {
        "crs": name,
        "width": int(dataset.width),
        "height": int(dataset.height),
        "originX": float(t.c),
        "originY": float(t.f),
        "resX": float(t.a),
        "resY": float(t.e),
        "rotX": float(t.b),
        "rotY": float(t.d),
    }


def masked_bands(dataset):
    """Every band of *dataset* as one masked array (bands, rows, columns), at
    its own number type, masked where it is nodata."""
    np = _np()
    values = dataset.read(masked=True)
    if values.dtype.kind == "f":
        values = np.ma.masked_invalid(values, copy=False)
    return values


def _inputs(rasters) -> list:
    """The rasters a step takes: one, or several in input-circle order."""
    if isinstance(rasters, (list, tuple)):
        return list(rasters)
    return [rasters]


def _name(position: int) -> str:
    return f"input_{position}"


def _check_rasters(rasters: list) -> None:
    for position, value in enumerate(rasters):
        if not is_dataset(value):
            raise RasterAlgebraError(
                f"{_name(position)} is not a raster: connect a node that hands on one, such as a "
                "Data Loading node reading a GeoTIFF."
            )


def _content_name(prefix: str, grid: dict, values) -> str:
    digest = hashlib.sha256(repr(sorted(grid.items())).encode("utf-8"))
    digest.update(str(values.dtype).encode("ascii"))
    digest.update(values.tobytes())
    return f"{prefix}-{digest.hexdigest()[:24]}.tif"


def write_raster(values, like, path, *, descriptions=None):
    """*values* (bands, rows, columns, NaN for nodata) on *like*'s grid, as a
    GeoTIFF at *path* with NaN as its nodata."""
    import rasterio

    profile = {
        "driver": "GTiff",
        "width": int(like.width),
        "height": int(like.height),
        "count": int(values.shape[0]),
        "dtype": str(values.dtype),
        "crs": like.crs,
        "transform": like.transform,
        "nodata": float("nan"),
        "compress": "deflate",
    }
    with rasterio.open(path, "w", **profile) as target:
        target.write(values)
        for index, description in enumerate(descriptions or (), start=1):
            if description:
                target.set_band_description(index, description)
    return path


def calculate(operation, rasters, *, codes=None, output_file):
    """*operation* over *rasters* cell by cell: a rasterio dataset.

    ``add``, ``subtract``, ``multiply`` and ``divide`` take input_0 and input_1
    (input_0 minus input_1, input_0 over input_1; a cell divided by 0 is
    nodata). ``choose`` takes input_1 where input_0's class is one of *codes*,
    and input_2 elsewhere; a nodata class is no class. Band by band; a class
    raster of one band applies to every band. *output_file(name)* gives where
    the result is written.
    """
    np = _np()
    operation = str(operation)
    wanted = _reads(operation)
    codes = _codes(operation, codes)
    rasters = _inputs(rasters)
    if len(rasters) != wanted:
        raise RasterAlgebraError(
            f"{operation} reads {wanted} rasters, and the Raster Calculator has {len(rasters)}: "
            "connect one to each input circle."
        )
    _check_rasters(rasters)
    names = [_name(position) for position in range(len(rasters))]
    _refuse_grids(f"{operation} of {', '.join(names)}", names, [dataset_grid(r) for r in rasters])

    bands = [masked_bands(r) for r in rasters]
    value_bands = bands[1:] if operation == CHOOSE else bands
    counts = {b.shape[0] for b in value_bands}
    if len(counts) != 1 or (operation == CHOOSE and bands[0].shape[0] not in (1, *counts)):
        raise RasterAlgebraError(
            f"{operation} cannot be computed: their bands differ. "
            + "; ".join(f"{name} has {b.shape[0]}" for name, b in zip(names, bands)) + "."
        )
    dtype = np.result_type(*(b.dtype for b in value_bands), np.float32)
    value_bands = [b.astype(dtype) for b in value_bands]
    if operation == CHOOSE:
        classes = bands[0]
        if classes.shape[0] != value_bands[0].shape[0]:
            classes = np.ma.concatenate([classes] * value_bands[0].shape[0])
        result = operate(CHOOSE, [classes, *value_bands], codes)
    else:
        result = operate(operation, value_bands)
    values = result.astype(dtype, copy=False)

    like = rasters[1] if operation == CHOOSE else rasters[0]
    path = output_file(_content_name(f"raster-{operation}", dataset_grid(like), values))
    import os
    import rasterio

    if not os.path.exists(path):
        write_raster(values, like, path, descriptions=like.descriptions)
    return rasterio.open(path)


def statistics(raster, *, band=1, mask=None, mask_values=None, where=None):
    """The mean, median, minimum, maximum and count of *raster*'s cells in
    *band*, nodata left out: a one-row table.

    With *mask*, a raster on the same grid (or the node's input_1), only the
    cells whose mask value is one of *mask_values*, or meets *where*, count; a
    nodata mask cell keeps none. *where* is a condition on the mask's first
    band, or on *raster*'s own values when there is no mask: it takes them as a
    float64 array, NaN for nodata, and gives where to keep, such as
    ``lambda height: height < 1.08`` or ``lambda v: (v >= 2) & (v < 5)``.
    """
    import pandas as pd

    np = _np()
    rasters = _inputs(raster)
    if mask is None and len(rasters) == 2:
        rasters, mask = rasters[:1], rasters[1]
    if len(rasters) != 1:
        raise RasterAlgebraError(
            f"Raster Statistics reads one raster, and a mask on input_1, and it has {len(rasters)}."
        )
    _check_rasters(rasters + ([mask] if mask is not None else []))
    dataset = rasters[0]
    band = int(band)
    if not 1 <= band <= dataset.count:
        raise RasterAlgebraError(f"input_0 has bands 1 to {dataset.count}, so it has no band {band}.")
    values = masked_bands(dataset)[band - 1].astype("float64")
    tested = None
    if mask is not None:
        if (mask_values is None) == (where is None):
            raise RasterAlgebraError(
                "A mask keeps the cells whose mask value is one of mask_values, or meets where: give one "
                "of them, for example mask_values=[0] or where=lambda value: value < 1.08."
            )
        _refuse_grids("Statistics of input_0 inside input_1", ["input_0", "input_1"],
                      [dataset_grid(dataset), dataset_grid(mask)])
        tested = masked_bands(mask)[0]
    elif mask_values is not None:
        raise RasterAlgebraError(
            "mask_values pick the cells of a mask raster on input_1, and there is none: connect one, "
            "or give where= for a condition on input_0's own values."
        )
    elif where is not None:
        tested = values
    if tested is not None:
        if mask_values is not None:
            if isinstance(mask_values, (int, float)):
                mask_values = [mask_values]
            keep = in_codes(tested, [float(v) for v in mask_values])
        else:
            if not callable(where):
                raise RasterAlgebraError(
                    f"where is a condition such as lambda value: value < 1.08, not {where!r}."
                )
            plain = np.ma.getdata(tested).astype("float64")
            plain = np.where(np.ma.getmaskarray(tested), np.nan, plain)
            with np.errstate(invalid="ignore"):
                keep = np.asarray(where(plain), dtype=bool)
            if keep.shape != plain.shape:
                raise RasterAlgebraError("where must give one answer per cell, as a comparison of the values does.")
            keep = keep & ~np.ma.getmaskarray(tested)
        values = np.ma.masked_where(~keep, values)
    # The band's own layout, nodata as NaN: what np.nanmedian and np.nanmean
    # read, so the numbers are numpy's on the raster.
    cells = values.filled(np.nan)
    count = int(np.count_nonzero(~np.isnan(cells)))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        row = {
            "mean": np.nanmean(cells) if count else np.nan,
            "median": np.nanmedian(cells) if count else np.nan,
            "min": np.nanmin(cells) if count else np.nan,
            "max": np.nanmax(cells) if count else np.nan,
            "count": count,
        }
    return pd.DataFrame([row], columns=list(STATISTICS))


# ---------------------------------------------------------------------------
# Autark raster envelopes
# ---------------------------------------------------------------------------

def _band_ids(envelope: dict) -> list[str]:
    bands = envelope["data"]["features"][0]["properties"].get("bands")
    return [str(band["id"]) for band in bands] if isinstance(bands, list) else []


def _wire_values(envelope: dict, band: str):
    np = _np()
    wire = envelope["data"]["features"][0]["properties"][band]
    return np.frombuffer(base64.b64decode(wire[WIRE_BAND_KEY]), dtype="<f4")


def subtract_envelopes(reference: tuple, comparison: tuple, absolute: bool = False) -> dict:
    """``comparison`` minus ``reference``, cell by cell and band by band, each a
    ``(name, envelope)``: the envelope of the difference, positive where the
    comparison is higher, or, with *absolute*, its size, 0 where they agree. A cell that is nodata (NaN) in either is nodata in
    the result. The result keeps the reference's properties and takes the
    comparison's extent and grid. Refused, naming both, when their grids or
    their bands differ."""
    np = _np()
    reference_name, a = reference
    comparison_name, b = comparison
    what = f"{comparison_name} minus {reference_name}"
    differs = grid_differences(a["data"]["grid"], b["data"]["grid"])
    if differs:
        raise RasterAlgebraError(
            f"{what} cannot be computed: their grids differ in {', '.join(differs)}. "
            f"{reference_name} is {describe_grid(a['data']['grid'])}; "
            f"{comparison_name} is {describe_grid(b['data']['grid'])}. Put both on one grid first."
        )
    ids, other_ids = _band_ids(a), _band_ids(b)
    if not ids or ",".join(ids) != ",".join(other_ids):
        raise RasterAlgebraError(
            f"{what} cannot be computed: their bands differ. "
            f"{reference_name} has {', '.join(ids) or 'none'}; {comparison_name} has {', '.join(other_ids) or 'none'}."
        )
    properties = dict(a["data"]["features"][0]["properties"])
    for band in ids:
        base = _wire_values(a, band).astype("float64")
        other = _wire_values(b, band).astype("float64")
        difference = np.abs(other - base) if absolute else other - base
        result = difference.astype("<f4")
        properties[band] = {WIRE_BAND_KEY: base64.b64encode(result.tobytes()).decode("ascii")}
    return {
        "dataType": "raster",
        "data": {
            "type": "FeatureCollection",
            "bbox": list(b["data"]["bbox"]),
            "grid": dict(b["data"]["grid"]),
            "features": [{"type": "Feature", "geometry": None, "properties": properties}],
        },
    }
