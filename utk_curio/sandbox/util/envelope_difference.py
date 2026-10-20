"""Compare Scenarios' Difference of two rasters: the comparison minus the
reference, cell by cell and band by band, on two Autark raster envelopes
(``utils/raster/rasterWire.ts``), the float32 bands autk-db's ``getRaster``
exports (``scenario_difference.subtract_in_autark``). The result is the
envelope the Autark map after the node, a reopen and a dashboard tile read.

The envelopes are subtracted only on one grid: the same size, origin, cell
size and CRS. Anything else is refused with a sentence that names both grids,
their numbers written as JavaScript writes them, so a sentence reads the same
whichever side made it. A cell that is nodata (NaN) in either envelope is
nodata in the result.

Only Compare Scenarios uses this module: step 6.4 of the plan answering
komar41's review of his #914, the Compare Scenarios removal, deletes it with
Compare. The Raster Calculator's operations are the Scout package's
(``scout_rasters.raster_algebra``), which keeps grid checks of its own, so
neither imports the other.
"""
from __future__ import annotations

import base64
import math
from decimal import Decimal

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


def _np():
    import numpy as np

    return np


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
    comparison is higher, or, with *absolute*, of its size, 0 where they agree.
    A cell that is nodata (NaN) in either is nodata in the result. The result
    keeps the reference's properties and takes the comparison's extent and
    grid. Refused, naming both, when their grids or their bands differ."""
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
        difference = other - base
        result = (np.abs(difference) if absolute else difference).astype("<f4")
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
