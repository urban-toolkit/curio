"""Run the Local Relief model on a height raster, and write its answer as one.

The node's code loads the model (``curio_load_model``) and hands it here with
the input raster; this module prepares the array the model reads, runs it, and
writes the result on the input's grid. Keeping it in a module, not in the
node's code, lets a test call it without Curio.
"""

import numpy as np
import rasterio

#: The model's input and output, as the export named them.
INPUT = "height"
OUTPUT = "relief"


def local_relief(raster, model, output_file):
    """*raster* (a rasterio dataset of heights in metres) through *model*: a
    GeoTIFF on the same grid, written where *output_file* says, opened.

    A cell with no data is read as ground (0 m) for its neighbours' sake, and
    has no data in the result."""
    band = raster.read(1, masked=True)
    heights = band.filled(0).astype(np.float32)

    # The model reads (1, 1, rows, columns), as it was exported: NCHW.
    (relief,) = model.run({INPUT: heights[np.newaxis, np.newaxis]})
    relief = relief[0, 0].astype(np.float32)
    relief[np.ma.getmaskarray(band)] = np.nan

    profile = {
        "driver": "GTiff",
        "width": raster.width,
        "height": raster.height,
        "count": 1,
        "dtype": "float32",
        "crs": raster.crs,
        "transform": raster.transform,
        "nodata": float("nan"),
    }
    path = output_file("local-relief.tif")
    with rasterio.open(path, "w", **profile) as out:
        out.write(relief, 1)
    return rasterio.open(path)
