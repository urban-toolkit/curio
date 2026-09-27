"""Mosaic Rasters.

Input: a raster collection's rows, as Data Loading's `curio_collection(...)`
returns them, usually filtered first to one year, one sensor or one area.
Output: one raster, a virtual mosaic (a GDAL VRT) of every tile, which any
node that takes a RASTER reads, the zonal-statistics nodes included. The
tiles stay where they are: the mosaic points at them.

Every tile must share its CRS, resolution, band count and data type, and be
north-up. The node names the first difference it finds.
"""

import hashlib
import json
import math
from xml.sax.saxutils import escape

import rasterio

GDAL_TYPES = {
    "uint8": "Byte", "int8": "Int8", "uint16": "UInt16", "int16": "Int16",
    "uint32": "UInt32", "int32": "Int32", "float32": "Float32", "float64": "Float64",
}

tiles = arg
tiles = tiles[tiles["kind"] == "raster"]
if tiles.empty:
    raise ValueError("Mosaic Rasters needs a raster collection's rows")
missing = tiles[tiles["path"].isna()]
if not missing.empty:
    raise ValueError(
        f"{missing.iloc[0]['relpath']} is not on this machine yet; cache the collection's files first"
    )

for column in ("crs", "res", "bands", "dtype"):
    values = tiles[column].dropna().astype(str).unique()
    if len(values) > 1:
        raise ValueError(f"these tiles differ in {column}: {', '.join(values[:4])}")

transforms = [json.loads(t) for t in tiles["transform"]]
if any(abs(t[1]) > 1e-12 or abs(t[3]) > 1e-12 for t in transforms):
    raise ValueError("a tile is rotated; only north-up tiles make a mosaic")
x_res, y_res = transforms[0][0], transforms[0][4]
extents = []
for t, width, height in zip(transforms, tiles["width"], tiles["height"]):
    x0, y0 = t[2], t[5]
    extents.append((x0, y0 + int(height) * y_res, x0 + int(width) * x_res, y0))
west = min(e[0] for e in extents)
south = min(e[1] for e in extents)
east = max(e[2] for e in extents)
north = max(e[3] for e in extents)
size_x = int(math.ceil((east - west) / x_res - 1e-9))
size_y = int(math.ceil((north - south) / -y_res - 1e-9))

bands = int(tiles["bands"].iloc[0])
dtype = GDAL_TYPES.get(str(tiles["dtype"].iloc[0]), "Float64")
nodata = tiles["nodata"].iloc[0] if "nodata" in tiles.columns else None
crs = str(tiles["crs"].iloc[0])

parts = [
    f'<VRTDataset rasterXSize="{size_x}" rasterYSize="{size_y}">',
    f"  <SRS>{escape(crs)}</SRS>",
    f"  <GeoTransform>{west}, {x_res}, 0, {north}, 0, {y_res}</GeoTransform>",
]
for band in range(1, bands + 1):
    parts.append(f'  <VRTRasterBand dataType="{dtype}" band="{band}">')
    if nodata is not None and nodata == nodata:
        parts.append(f"    <NoDataValue>{nodata}</NoDataValue>")
    for (x0, _s, _e, y0), path, width, height in zip(extents, tiles["path"], tiles["width"], tiles["height"]):
        x_off = int(round((x0 - west) / x_res))
        y_off = int(round((north - y0) / -y_res))
        parts += [
            "    <SimpleSource>",
            f'      <SourceFilename relativeToVRT="0">{escape(str(path))}</SourceFilename>',
            f"      <SourceBand>{band}</SourceBand>",
            f'      <SrcRect xOff="0" yOff="0" xSize="{int(width)}" ySize="{int(height)}"/>',
            f'      <DstRect xOff="{x_off}" yOff="{y_off}" xSize="{int(width)}" ySize="{int(height)}"/>',
            "    </SimpleSource>",
        ]
    parts.append("  </VRTRasterBand>")
parts.append("</VRTDataset>")

name = "mosaic-" + hashlib.sha1("\n".join(sorted(tiles["file_id"])).encode()).hexdigest()[:16] + ".vrt"
path = curio_output_file(name)
with open(path, "w", encoding="utf-8") as handle:
    handle.write("\n".join(parts))
return rasterio.open(path)
