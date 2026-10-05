"""How SCOUT projects a flood with and without nature-based solutions.

Ported from SCOUT (https://github.com/urban-toolkit/scout), file
backend/models/flooding/scripts/flood_simulation.py:
``simulate_flood_projection``'s classes, its choice of depth for each cell and
its metrics. The code keeps SCOUT's names and arithmetic. Changes from SCOUT's
file:

- The three rasters arrive as arrays already read through the bounding box,
  by the dataflow's Data Loading node with
  ``curio_load_data(..., part="<file>", bounds=...)``, instead of SCOUT's fixed
  paths, its ``year_dict`` and its ``from_bounds`` window. Curio's window
  keeps the cells whose centres lie inside the box; SCOUT's rounds the box's
  edges, so a box's edge cells can differ by one.
- The depths are Curio's float32 copies of SCOUT's float64 rasters (see
  scripts/build_example_quad_cities_flood.py), with no depth as NaN.
- The raster and the metrics are returned instead of written to
  ``data/served``; the node writes the raster where Curio says.
"""

import numpy as np

#: SCOUT's NbS class codes and the solution each one is.
dict_use_NBS_classes = {
    21: "Bioswales/Infiltration trenches",
    31: "Permeable pavements",
    43: "Retention ponds",
    52: "Infiltration trench",
    71: "Bioswales",
    81: "Bioswales",
    90: "Constructed wetlands",
    95: "Constructed wetlands",
}

#: The solutions, in the order SCOUT's widgets list them.
NBS_NAMES = [
    "Bioswales/Infiltration trenches",
    "Permeable pavements",
    "Retention ponds",
    "Infiltration trench",
    "Bioswales",
    "Constructed wetlands",
]


def nbs_codes(use_NBS_classes):
    """The class codes of the solutions named in *use_NBS_classes*."""
    use_NBS_classes = set(use_NBS_classes)
    unknown = sorted(use_NBS_classes - set(NBS_NAMES))
    if unknown:
        raise ValueError(f"No nature-based solution is called {', '.join(map(repr, unknown))}; "
                         f"the solutions are {', '.join(NBS_NAMES)}.")
    return {code for code, name in dict_use_NBS_classes.items() if name in use_NBS_classes}


def combine(mask_data_, nbs_data_, nonbs_data_, use_NBS_classes, flood_nodata=None):
    """SCOUT's projection: the depth with NbS where a cell's class is one of
    *use_NBS_classes*, the depth without NbS elsewhere, and no depth (NaN)
    where the chosen raster has none."""
    use_NBS_classes_ = nbs_codes(use_NBS_classes)
    cond_use_NBS = np.isin(mask_data_, list(use_NBS_classes_))
    combined = np.where(cond_use_NBS, nbs_data_, nonbs_data_)
    if flood_nodata is not None and not np.isnan(flood_nodata):
        combined = np.where(combined == flood_nodata, np.nan, combined)
    return combined


def metrics(combined):
    """SCOUT's metrics of a projection, over its cells with a depth."""
    if not np.isfinite(combined).any():
        return {"median flood depth": None, "mean flood depth": None}
    return {
        "median flood depth": float(np.nanmedian(combined)),
        "mean flood depth": float(np.nanmean(combined)),
    }
