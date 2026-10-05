"""SCOUT's building rasterizer ("OSM vector to raster").

Ported from SCOUT (https://github.com/urban-toolkit/scout), file
backend/compute/raster_conversion/scripts/convert_to_raster.py at b98369e5.
The functions keep SCOUT's names, parameters and arithmetic, so a buildings
layer becomes the tiles SCOUT writes. Changes from SCOUT's file:

- pygeos calls are shapely 2 calls (pygeos was merged into shapely 2), and a
  GeoDataFrame's geometries are read with ``np.asarray(...array)``.
- ``create_image`` writes the PNG with Pillow instead of ``cv2.imwrite``,
  converting to 8 bits the way OpenCV does (round half to even, saturate,
  NaN and infinities to 0), so the pixels are the same.
- ``convert_raster`` also takes a GeoDataFrame as ``vector_in``, and takes the
  maximum height (SCOUT's fixed 550) as ``max_height``. An attribute other
  than ``height`` raises SCOUT's message instead of printing it.
- SCOUT's polygons reducer is set on a Canvas subclass rather than patched
  onto datashader's own Canvas.
- The unused imports (matplotlib, cv2, pygeos) and SCOUT's commented-out
  earlier versions of ``create_image`` and ``compute_tile`` are left out.
"""

import pandas as pd
import geopandas as gpd
import spatialpandas as sp
import datashader as ds
import numpy as np
import pyarrow as pa
import shapely
import math
import dask

from PIL import Image
from shapely.geometry import box
from pyproj import Transformer

from datashader.core import bypixel
import os

from pathlib import Path

transformer = Transformer.from_crs(3395, 4326)
invtransformer = Transformer.from_crs(4326,3395)

def get_flat_coords_offset_arrays(arr):
    """
    Version for MultiPolygon data
    """
    # explode/flatten the MultiPolygons
    arr_flat, part_indices = shapely.get_parts(arr, return_index=True)
    # the offsets into the multipolygon parts
    offsets1 = np.insert(np.bincount(part_indices).cumsum(), 0, 0)

    # explode/flatten the Polygons into Rings
    arr_flat2, ring_indices = shapely.get_rings(arr_flat, return_index=True)
    # the offsets into the exterior/interior rings of the multipolygon parts
    offsets2 = np.insert(np.bincount(ring_indices).cumsum(), 0, 0)

    # the coords and offsets into the coordinates of the rings
    coords, indices = shapely.get_coordinates(arr_flat2, return_index=True)
    offsets3 = np.insert(np.bincount(indices).cumsum(), 0, 0)

    return coords, offsets1, offsets2, offsets3

def spatialpandas_from_pygeos(arr):
    coords, offsets1, offsets2, offsets3 = get_flat_coords_offset_arrays(arr)
    coords_flat = coords.ravel()
    offsets3 *= 2

    # create a pyarrow array from this
    _parr3 = pa.ListArray.from_arrays(pa.array(offsets3), pa.array(coords_flat))
    _parr2 = pa.ListArray.from_arrays(pa.array(offsets2), _parr3)
    parr = pa.ListArray.from_arrays(pa.array(offsets1), _parr2)

    return sp.geometry.MultiPolygonArray(parr)

def polygons(self, source, geometry, agg=None):
    from datashader.glyphs import PolygonGeom
    from datashader.reductions import any as any_rdn
    from spatialpandas import GeoDataFrame
    from spatialpandas.dask import DaskGeoDataFrame
    if isinstance(source, DaskGeoDataFrame):
        # Downselect partitions to those that may contain polygons in viewport
        x_range = self.x_range if self.x_range is not None else (None, None)
        y_range = self.y_range if self.y_range is not None else (None, None)
        source = source.cx_partitions[slice(*x_range), slice(*y_range)]
    elif isinstance(source, gpd.GeoDataFrame):
        # Downselect actual rows to those for which the polygon is in viewport
        x_range = self.x_range if self.x_range is not None else (None, None)
        y_range = self.y_range if self.y_range is not None else (None, None)
        source = source.cx[slice(*x_range), slice(*y_range)]
        # Convert the subset to ragged array format of spatialpandas
        geometries = spatialpandas_from_pygeos(np.asarray(source.geometry.array))
        source = pd.DataFrame(source)
        source["geometry"] = geometries
    elif not isinstance(source, GeoDataFrame):
        raise ValueError(
            "source must be an instance of spatialpandas.GeoDataFrame or \n"
            "spatialpandas.dask.DaskGeoDataFrame.\n"
            "  Received value of type {typ}".format(typ=type(source)))

    if agg is None:
        agg = any_rdn()
    glyph = PolygonGeom(geometry)
    return bypixel(source, self, glyph, agg)

class Canvas(ds.Canvas):
    polygons = polygons

cvs = Canvas(plot_width=256, plot_height=256)

def deg2num(lat_deg, lon_deg, zoom):
    lat_rad = math.radians(lat_deg)
    n = 2.0 ** zoom
    xtile = ((lon_deg + 180.0) / 360.0 * n)
    ytile = ((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return (xtile, ytile)

def num2deg(xtile, ytile, zoom):
    n = 2.0 ** zoom
    lon_deg = xtile / n * 360.0 - 180.0
    lat_rad = math.atan(math.sinh(math.pi * (1 - 2 * ytile / n)))
    lat_deg = math.degrees(lat_rad)
    return (lat_deg, lon_deg)

def compute_all(gdf, zoom, max_height, outputfolder):
    bounds = gdf.total_bounds
    lat0,lng0 = transformer.transform(bounds[0],bounds[1])
    lat1,lng1 = transformer.transform(bounds[2],bounds[3])
    coord0 = deg2num(lat0,lng0,zoom)
    coord1 = deg2num(lat1,lng1,zoom)
    bottomleft = [min(coord0[0],coord1[0]),min(coord0[1],coord1[1])]
    topright = [max(coord0[0],coord1[0]),max(coord0[1],coord1[1])]

    # Create folders (serial)
    for i in range(math.floor(bottomleft[0]),math.ceil(topright[0])):
        folder = '%s/%d/%d/'%(outputfolder,zoom,i)
        if not os.path.exists(folder):
            os.makedirs(folder)

    delayed = []
    for i in range(math.floor(bottomleft[0]),math.ceil(topright[0])):
        for j in range(math.floor(bottomleft[1]),math.ceil(topright[1])):
            ddelayed = compute_tile(gdf, i, j, zoom, max_height, outputfolder)
            delayed.append(ddelayed)
    dask.compute(*delayed)

def elevation(filtered, bbox):
    proxy = pd.DataFrame({'height': 0, 'geometry': bbox}, index=[len(filtered)])
    proxy = gpd.GeoDataFrame(proxy)
    proxy.crs = '3395'

    clipped = gpd.clip(filtered, proxy)
    intersection = pd.concat([proxy, clipped], ignore_index=True)
    intersection = intersection[intersection.geom_type.isin(['Polygon', 'MultiPolygon'])]
    if len(intersection) > 0:
        intersection = sp.GeoDataFrame(intersection)
        values = cvs.polygons(intersection, geometry='geometry', agg=ds.max("height"))
    else:
        values = np.zeros((256,256))
    values = np.flipud(values)
    return values

def to_uint8(values):
    """``cv2.imwrite``'s conversion of a float image to 8 bits: round half
    to even, saturate to 0..255, NaN and infinities to 0."""
    values = np.asarray(values, dtype=np.float64)
    values = np.where(np.isfinite(values), values, 0.0)
    return np.clip(np.rint(values), 0, 255).astype(np.uint8)

def create_image(values, i, j, zoom, max_height, outputfolder):
    filename_ = '%s/%d_%d_%d.png'%(outputfolder,zoom,i,j)

    values = 255.0 * (values / max_height)
    Image.fromarray(to_uint8(values)).save(filename_)

def compute_tile(gdf, i, j, zoom, max_height, outputfolder):
    bb0 = num2deg(i,j,zoom)
    bb1 = num2deg(i+1,j+1,zoom)
    bb0 = invtransformer.transform(bb0[0],bb0[1])
    bb1 = invtransformer.transform(bb1[0],bb1[1])
    bbox = box(bb0[0],bb0[1],bb1[0],bb1[1])
    filtered = gdf.loc[gdf.sindex.intersection(bbox.bounds)]

    if len(filtered) > 0:
        values = elevation(filtered, bbox)
        create_image(values, i, j, zoom, max_height, outputfolder)

    else:
        print(f"No data for tile {zoom}/{i}/{j}")

def convert_raster(vector_in: str, attribute: str, zoom: int, raster_out: str, max_height: float = 550):
    raster_out = Path(raster_out)

    gdf = vector_in if isinstance(vector_in, gpd.GeoDataFrame) else gpd.read_file(vector_in)
    gdf = gdf.to_crs(epsg=3395)

    bounds = gdf.total_bounds
    lat0,lng0 = transformer.transform(bounds[0],bounds[1])
    lat1,lng1 = transformer.transform(bounds[2],bounds[3])
    coord0 = deg2num(lat0,lng0,zoom)
    coord1 = deg2num(lat1,lng1,zoom)
    bottomleft = [min(coord0[0],coord1[0]),min(coord0[1],coord1[1])]
    topright = [max(coord0[0],coord1[0]),max(coord0[1],coord1[1])]

    raster_out.mkdir(parents=True, exist_ok=True)

    if raster_out.exists():
        for file in raster_out.iterdir():
            file.unlink()

    if attribute == "height":
        raster_out.mkdir(parents=True, exist_ok=True)
        delayed = []
        for i in range(math.floor(bottomleft[0]),math.ceil(topright[0])):
            for j in range(math.floor(bottomleft[1]),math.ceil(topright[1])):
                ddelayed = compute_tile(gdf, i, j, zoom, max_height, raster_out)
                delayed.append(ddelayed)
        dask.compute(*delayed)

        print(f"Raster tiles for buildings height created at zoom level {zoom} in {raster_out}")
    else:
        raise ValueError(f"Feature '{attribute}' not supported for layer")

    return
