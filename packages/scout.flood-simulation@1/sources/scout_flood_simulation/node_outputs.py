"""The Simulate Flood node's output, made from SCOUT's projection
(``flood_simulation.py``). Curio's own code, beside the port.

The node reads ``(classes, nbs, no_nbs)``, three rasters on one grid, from
the Data Loading node: the NbS classes and one period's flood depth with NbS
and without (``data.scout.quad-cities-flood``'s ``NBS_others_5m.tif``,
``<period>_NbS.tif`` and ``<period>_noNbS.tif``, each read over the area).

It returns one raster on that grid: one float32 band of the projected depth
in metres, NaN where the projection gives no depth, tagged with the solutions
used and SCOUT's metrics. Raster Statistics reads it for SCOUT's median and
mean, and Compare Scenarios subtracts two.
"""

import hashlib

import rasterio

from .flood_simulation import NBS_NAMES, combine, metrics, nbs_codes

INPUTS = "(classes, nbs, no_nbs): the NbS classes and a period's flood depth with NbS and without"


def flood_rasters(arg):
    """``(classes, nbs, no_nbs)`` from *arg*, checked to share one grid, as
    SCOUT asserts before combining them."""
    if not isinstance(arg, (tuple, list)) or len(arg) != 3 or not all(hasattr(r, "read") for r in arg):
        raise ValueError(f"Simulate Flood reads three rasters, {INPUTS}. Connect the Data Loading node that loads them.")
    classes, nbs, no_nbs = arg
    for name, raster in (("nbs", nbs), ("no_nbs", no_nbs)):
        if (raster.crs, raster.transform, raster.width, raster.height) != (
            classes.crs, classes.transform, classes.width, classes.height
        ):
            raise ValueError(
                f"Simulate Flood reads {INPUTS}, on one grid; {name} is {raster.width} by {raster.height} "
                f"cells at {tuple(raster.transform)[:6]} and classes {classes.width} by {classes.height} at "
                f"{tuple(classes.transform)[:6]}. Read all three over the same bounds."
            )
    return classes, nbs, no_nbs


def chosen(nbs):
    """*nbs*, the widget's value, as SCOUT's names in SCOUT's order, checked."""
    names = [] if nbs is None else [nbs] if isinstance(nbs, str) else [str(name) for name in nbs]
    nbs_codes(names)
    return [name for name in NBS_NAMES if name in names]


def simulate_flood(arg, nbs, output_file):
    """The depth SCOUT projects from *arg*'s ``(classes, nbs, no_nbs)`` with
    the nature-based solutions named in *nbs*. *output_file(name)* names
    where the raster is written."""
    classes, with_nbs, without_nbs = flood_rasters(arg)
    nbs = chosen(nbs)
    combined = combine(classes.read(1), with_nbs.read(1), without_nbs.read(1), nbs, with_nbs.nodata).astype("float32")
    summary = metrics(combined)

    profile = {
        "driver": "GTiff", "width": classes.width, "height": classes.height, "count": 1, "dtype": "float32",
        "crs": classes.crs, "transform": classes.transform, "nodata": float("nan"), "compress": "deflate",
    }
    digest = hashlib.sha256(
        repr((list(classes.transform)[:6], str(classes.crs), nbs)).encode("utf-8") + combined.tobytes()
    ).hexdigest()[:16]
    path = output_file(f"flood-{digest}.tif")
    with rasterio.open(path, "w", **profile) as out:
        out.write(combined, 1)
        out.set_band_description(1, "flood depth (m)")
        out.update_tags(
            nbs="; ".join(nbs) or "none",
            median_flood_depth="" if summary["median flood depth"] is None else repr(summary["median flood depth"]),
            mean_flood_depth="" if summary["mean flood depth"] is None else repr(summary["mean flood depth"]),
        )
    return rasterio.open(path)
