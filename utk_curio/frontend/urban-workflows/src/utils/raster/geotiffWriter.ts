/**
 * A raster collection back into GeoTIFF bytes, for autk-db to load.
 *
 * autk-db loads a raster only from GeoTIFF bytes (`loadGeoTiff`), so a raster
 * that reaches an Autark node as a collection (from another Autark node, or a
 * comparison) is written out here first and loaded the same way a Python
 * node's file is. The file is the plainest GeoTIFF there is: little-endian,
 * uncompressed float32, one strip per band, georeferenced by a tie point and a
 * pixel scale in the grid's own CRS, with NaN as its nodata. GDAL reads it as
 * the same grid (`test_rasters.py`, over `rasterWire.cases.json`).
 *
 * Pure, so it is testable under jest.
 */
import { epsgCode } from "./rasterLoad";
import type { RasterGrid } from "./rasterWire";

const SHORT = 3;
const LONG = 4;
const DOUBLE = 12;
const ASCII = 2;
const TYPE_SIZE: Record<number, number> = { [SHORT]: 2, [LONG]: 4, [DOUBLE]: 8, [ASCII]: 1 };

type Tag = { id: number; type: number; values: number[] | string };

/**
 * Whether an EPSG code names a geographic CRS. EPSG numbers its geographic 2D
 * CRSs from 4000 to 4999, EPSG:4326 among them.
 */
export function isGeographicEpsg(code: number): boolean {
  return code >= 4000 && code <= 4999;
}

/**
 * GeoTIFF bytes for a grid and its bands. Each band holds one value per cell,
 * rows from south to north, as autk-db's `getRaster` gives them; the file
 * writes them north to south, as a GeoTIFF reads.
 */
export function writeGeoTiff(grid: RasterGrid, bands: ArrayLike<number>[]): ArrayBuffer {
  const { width, height } = grid;
  const code = epsgCode(grid.crs);
  if (code == null) throw new Error(`a GeoTIFF needs an EPSG CRS, not ${grid.crs}`);
  if (bands.length === 0) throw new Error("a GeoTIFF needs at least one band");
  const cells = width * height;
  for (const band of bands) {
    if (band.length !== cells) throw new Error("every band needs one value per cell");
  }

  const count = bands.length;
  const planeBytes = cells * 4;
  const dataStart = 8;
  const ifdStart = dataStart + count * planeBytes;
  const geographic = isGeographicEpsg(code);

  const tags: Tag[] = [
    { id: 256, type: LONG, values: [width] },
    { id: 257, type: LONG, values: [height] },
    { id: 258, type: SHORT, values: bands.map(() => 32) },
    { id: 259, type: SHORT, values: [1] },
    { id: 262, type: SHORT, values: [1] },
    { id: 273, type: LONG, values: bands.map((_, i) => dataStart + i * planeBytes) },
    { id: 277, type: SHORT, values: [count] },
    { id: 278, type: LONG, values: [height] },
    { id: 279, type: LONG, values: bands.map(() => planeBytes) },
    { id: 284, type: SHORT, values: [count > 1 ? 2 : 1] },
    ...(count > 1 ? [{ id: 338, type: SHORT, values: bands.slice(1).map(() => 0) }] : []),
    { id: 339, type: SHORT, values: bands.map(() => 3) },
    { id: 33550, type: DOUBLE, values: [grid.resX, -grid.resY, 0] },
    { id: 33922, type: DOUBLE, values: [0, 0, 0, grid.originX, grid.originY, 0] },
    {
      id: 34735,
      type: SHORT,
      values: [
        1, 1, 0, 3,
        1024, 0, 1, geographic ? 2 : 1,
        1025, 0, 1, 1,
        geographic ? 2048 : 3072, 0, 1, code,
      ],
    },
    { id: 42113, type: ASCII, values: "nan\0" },
  ];

  // Values longer than four bytes go after the directory, each 8-byte aligned.
  const ifdBytes = 2 + tags.length * 12 + 4;
  let extra = ifdStart + ifdBytes;
  const offsets = new Map<number, number>();
  for (const tag of tags) {
    const size = TYPE_SIZE[tag.type] * tag.values.length;
    if (size > 4) {
      extra = Math.ceil(extra / 8) * 8;
      offsets.set(tag.id, extra);
      extra += size;
    }
  }

  const buffer = new ArrayBuffer(extra);
  const view = new DataView(buffer);
  view.setUint8(0, 0x49);
  view.setUint8(1, 0x49);
  view.setUint16(2, 42, true);
  view.setUint32(4, ifdStart, true);

  for (let b = 0; b < count; b++) {
    const band = bands[b];
    const plane = dataStart + b * planeBytes;
    for (let row = 0; row < height; row++) {
      const from = (height - 1 - row) * width;
      const to = plane + row * width * 4;
      for (let col = 0; col < width; col++) view.setFloat32(to + col * 4, Number(band[from + col]), true);
    }
  }

  const write = (at: number, type: number, value: number | string) => {
    if (type === SHORT) view.setUint16(at, value as number, true);
    else if (type === LONG) view.setUint32(at, value as number, true);
    else if (type === DOUBLE) view.setFloat64(at, value as number, true);
    else view.setUint8(at, (value as string).charCodeAt(0));
  };

  view.setUint16(ifdStart, tags.length, true);
  tags.forEach((tag, i) => {
    const entry = ifdStart + 2 + i * 12;
    view.setUint16(entry, tag.id, true);
    view.setUint16(entry + 2, tag.type, true);
    view.setUint32(entry + 4, tag.values.length, true);
    const at = offsets.get(tag.id);
    if (at != null) view.setUint32(entry + 8, at, true);
    const base = at ?? entry + 8;
    const size = TYPE_SIZE[tag.type];
    for (let k = 0; k < tag.values.length; k++) {
      const value = typeof tag.values === "string" ? tag.values[k] : tag.values[k];
      write(base + k * size, tag.type, value);
    }
  });
  view.setUint32(ifdStart + 2 + tags.length * 12, 0, true);
  return buffer;
}
