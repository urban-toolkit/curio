/**
 * How an Autark node loads a raster: at its own size, never blended.
 *
 * autk-db's `loadGeoTiff` reads the whole image and, past `maxRasterCells`
 * (one million by default), shrinks it with bilinear resampling, which blends
 * class codes and nodata into values the raster never held. So Curio asks for
 * the raster's own size, up to what a map can hold, and refuses a larger one
 * with a sentence that says to crop it where it is made. `nearest` is passed
 * as well, so a resample, if autk-db ever needs one, picks cell values rather
 * than mixing them.
 *
 * autk-db also reads a raster as EPSG:4326 unless told otherwise, so the CRS
 * goes with it, by its EPSG code.
 *
 * Pure, so it is testable under jest.
 */
import { epsgCode } from "./geotiffWriter";
import type { RasterGrid } from "./rasterWire";

/** The most cells an Autark map loads from one raster: 2048 by 2048. */
export const RASTER_MAX_CELLS = 2048 * 2048;
/** The longest side WebGPU guarantees a texture. */
export const RASTER_MAX_SIDE = 8192;

/** What the sandbox says about a raster artifact, beside its bytes. */
export type RasterMeta = {
  width: number;
  height: number;
  count: number;
  /** `EPSG:<code>`, or null when the CRS has no EPSG code or there is none. */
  crs: string | null;
  /** The CRS as WKT when it has no EPSG code. */
  crsWkt?: string | null;
  /** The affine transform `[a, b, c, d, e, f]`, as rasterio orders it. */
  transform: number[];
  nodata?: number | null;
};

/** What `loadGeoTiff` is given beside the bytes and the table name. */
export type GeotiffLoad = {
  coordinateFormat: string;
  maxRasterCells: number;
  resampleMethod: "nearest";
};

export type RasterLoadPlan = { load: GeotiffLoad; grid: RasterGrid; cells: number };

/** Why a raster of this size is not loaded, or null when it fits. */
export function oversizeSentence(name: string, width: number, height: number): string | null {
  if (width * height <= RASTER_MAX_CELLS && width <= RASTER_MAX_SIDE && height <= RASTER_MAX_SIDE) return null;
  return `${name} is ${width} by ${height} cells, more than an Autark map loads at its own size `
    + `(${RASTER_MAX_CELLS} cells, ${RASTER_MAX_SIDE} on a side). Crop it in the node that makes it, `
    + "for example with a rasterio window read, and run that node again.";
}

/** The parameters for a grid already known, at its own size. */
export function planForGrid(name: string, grid: RasterGrid): RasterLoadPlan | { refused: string } {
  const oversize = oversizeSentence(name, grid.width, grid.height);
  if (oversize) return { refused: oversize };
  if (epsgCode(grid.crs) == null) {
    return { refused: `${name} is in ${grid.crs}, which has no EPSG code, so Autark cannot place it.` };
  }
  const cells = grid.width * grid.height;
  return {
    load: { coordinateFormat: grid.crs.toUpperCase(), maxRasterCells: cells, resampleMethod: "nearest" },
    grid: { ...grid },
    cells,
  };
}

/** The parameters for a raster the sandbox describes, or why it is refused. */
export function planForMeta(name: string, meta: RasterMeta): RasterLoadPlan | { refused: string } {
  const oversize = oversizeSentence(name, meta.width, meta.height);
  if (oversize) return { refused: oversize };
  if (!meta.crs) {
    return {
      refused: meta.crsWkt
        ? `${name} is in a CRS with no EPSG code, so Autark cannot place it. `
          + "Reproject it to an EPSG CRS (rasterio.warp) in the node that makes it."
        : `${name} has no CRS, so Autark cannot place it. Set one in the node that makes it.`,
    };
  }
  const [a, b, c, d, e, f] = meta.transform ?? [];
  if (![a, b, c, d, e, f].every(Number.isFinite)) {
    return { refused: `${name} has no georeferencing, so Autark cannot place it.` };
  }
  if (b !== 0 || d !== 0) {
    return { refused: `${name} is rotated, and an Autark map draws only north-up rasters. Warp it to a north-up grid first.` };
  }
  return planForGrid(name, {
    crs: meta.crs,
    width: meta.width,
    height: meta.height,
    originX: c,
    originY: f,
    resX: a,
    resY: e,
  });
}
