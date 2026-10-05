"""SCOUT's flood function, ported from SCOUT, https://github.com/urban-toolkit/scout
(``backend/compute/quad_city_flooding_simulation/scripts/flood_simulation.py``).

``simulate_flood_projection`` keeps SCOUT's name, parameters and arithmetic: a
window read of the region from the class raster and from the period's flood
depth rasters with and without nature-based solutions (NbS), at full
resolution; per cell, the depth with NbS where the cell's class is one of the
chosen solutions and the depth without NbS elsewhere; the median and mean depth.
The changes:

- the three rasters are files the caller names in ``rasters`` (the node passes
  the Data Catalog's, through ``curio_data_path``), not fixed paths under
  ``./models``;
- ``topleft`` and ``bottomright`` may also be Curio locations,
  ``{"lat": ..., "lon": ...}``, besides SCOUT's ``"lon, lat"`` text;
- ``output`` says where the depth raster goes: a function that gives the path
  for a file name (the node passes ``curio_output_file``). The file is named
  after its content, so two results never share one;
- it returns the depth raster, opened, and SCOUT's one-row table of the median
  and mean depth, instead of writing both under ``./data/served``;
- a period with no rasters, corners that are not the top-left and the
  bottom-right, and a region that reaches past the rasters are refused in a
  sentence.
"""

import hashlib
from collections.abc import Mapping

import numpy as np
import pandas as pd
import rasterio
from rasterio.windows import from_bounds

#: SCOUT's NbS classes: each code of the class raster, and the solution it is.
NBS_CLASSES = {
    21: "Bioswales/Infiltration trenches",
    31: "Permeable pavements",
    43: "Retention ponds",
    52: "Infiltration trench",
    71: "Bioswales",
    81: "Bioswales",
    90: "Constructed wetlands",
    95: "Constructed wetlands",
}

#: The solutions, each once, in SCOUT's order.
NBS_NAMES = list(dict.fromkeys(NBS_CLASSES.values()))

#: SCOUT's periods, as its widget names them and as its file names do.
PERIODS = {
    "2020 - 2040": "2020_2040",
    "2050 - 2080": "2050_2080",
    "2080 - 2100": "2080_2100",
}

#: How far past the rasters, in cells, a region may reach. SCOUT's own
#: example reaches past its rasters' south and east edges by less than one.
REACH_CELLS = 1


def lon_lat(point, corner):
    """``(lon, lat)`` of a corner: SCOUT's ``"lon, lat"`` text, or a location."""
    if isinstance(point, str):
        lon, lat = map(float, point.split(","))
        return lon, lat
    if isinstance(point, Mapping) and "lat" in point and "lon" in point:
        return float(point["lon"]), float(point["lat"])
    raise ValueError(
        f"The {corner} corner is {point!r}. Give a location, {{\"lat\": ..., \"lon\": ...}}, "
        "or SCOUT's \"lon, lat\" text."
    )


def _inside(bounds, cell, min_lon, min_lat, max_lon, max_lat):
    """Refuse a region that reaches more than ``REACH_CELLS`` cells past *bounds*."""
    reach = REACH_CELLS * cell
    if (
        min_lon < bounds.left - reach or max_lon > bounds.right + reach
        or min_lat < bounds.bottom - reach or max_lat > bounds.top + reach
    ):
        raise ValueError(
            f"The region, longitude {min_lon} to {max_lon} and latitude {min_lat} to {max_lat}, reaches past "
            f"the flood rasters, which cover longitude {bounds.left:.4f} to {bounds.right:.4f} and latitude "
            f"{bounds.bottom:.4f} to {bounds.top:.4f}. Move the corners inside them."
        )


def depth_file_name(combined, profile):
    """A file name that follows the depth raster's content."""
    digest = hashlib.sha1(combined.tobytes())
    digest.update(repr((profile["crs"], tuple(profile["transform"])[:6], combined.shape)).encode("utf-8"))
    return f"flood-depth-{digest.hexdigest()[:16]}.tif"


def simulate_flood_projection(
    topleft,
    bottomright,
    output,
    year="2020 - 2040",
    use_NBS_classes=[
        "Bioswales/Infiltration trenches",
        "Permeable pavements",
        "Retention ponds",
        "Infiltration trench",
        "Bioswales",
        "Constructed wetlands",
    ],
    rasters=None,
):
    """``(depth, metrics)`` for the region between *topleft* and *bottomright*
    in period *year*, with the NbS named in *use_NBS_classes* in place.

    *rasters* names the files: ``"classes"`` the class raster, and each period
    its ``(with NbS, without NbS)`` depth rasters. *output(name)* gives the path
    the depth raster is written to.
    """
    dict_use_NBS_classes = NBS_CLASSES

    use_NBS_classes = set(use_NBS_classes)

    use_NBS_classes_ = {
        code for code, name in dict_use_NBS_classes.items()
        if name in use_NBS_classes
    }

    if year not in PERIODS:
        raise ValueError(f"There is no flood projection for {year!r}. The periods: {', '.join(PERIODS)}.")
    if not isinstance(rasters, Mapping) or "classes" not in rasters or year not in rasters:
        raise ValueError(
            f"Name the rasters to read: {{\"classes\": <class raster>, {year!r}: "
            "(<depth with NbS>, <depth without NbS>)}."
        )
    mask_path = rasters["classes"]
    nbs_flood_path, nonbs_flood_path = rasters[year]

    # "lon, lat" text, or a location
    top_left_lon, top_left_lat = lon_lat(topleft, "top-left")
    bottom_right_lon, bottom_right_lat = lon_lat(bottomright, "bottom-right")

    # build bounds for rasterio
    min_lon = top_left_lon
    max_lon = bottom_right_lon
    max_lat = top_left_lat
    min_lat = bottom_right_lat
    if not (min_lon < max_lon and min_lat < max_lat):
        raise ValueError(
            f"The top-left corner ({top_left_lat}, {top_left_lon}) must be north and west of the "
            f"bottom-right corner ({bottom_right_lat}, {bottom_right_lon})."
        )

    with rasterio.open(mask_path) as src_mask, \
         rasterio.open(nbs_flood_path) as src_nbs, \
         rasterio.open(nonbs_flood_path) as src_nonbs:

        assert src_mask.crs == src_nbs.crs == src_nonbs.crs, "the three rasters must share one CRS"
        assert src_mask.transform == src_nbs.transform == src_nonbs.transform, (
            "the three rasters must share one grid"
        )
        _inside(src_mask.bounds, abs(src_mask.transform.a), min_lon, min_lat, max_lon, max_lat)

        window = from_bounds(
            min_lon,
            min_lat,
            max_lon,
            max_lat,
            transform=src_mask.transform,
        )

        mask_data_ = src_mask.read(1, window=window)
        nbs_data_ = src_nbs.read(1, window=window)
        nonbs_data_ = src_nonbs.read(1, window=window)

        out_transform = src_mask.window_transform(window)
        out_height, out_width = mask_data_.shape

        cond_use_NBS = np.isin(mask_data_, list(use_NBS_classes_))
        combined = np.where(cond_use_NBS, nbs_data_, nonbs_data_)

        flood_nodata = src_nbs.nodata
        if flood_nodata is not None:
            combined = np.where(combined == flood_nodata, np.nan, combined)

        profile = src_nbs.profile.copy()
        profile.update(
            dtype=combined.dtype,
            height=out_height,
            width=out_width,
            transform=out_transform,
            nodata=0.0,
        )

        median_val = np.nanmedian(combined)
        mean_val = np.nanmean(combined)

        df = pd.DataFrame([{
            "median flood depth": median_val,
            "mean flood depth": mean_val,
        }])

    output_path = output(depth_file_name(combined, profile))
    with rasterio.open(output_path, "w", **profile) as dst:
        dst.write(combined, 1)

    return rasterio.open(output_path), df
