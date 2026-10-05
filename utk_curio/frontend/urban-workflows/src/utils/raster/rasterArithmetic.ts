/**
 * Arithmetic on two rasters, cell by cell, in Curio's Autark adapter.
 *
 * Autark has no raster arithmetic, so a comparison of two rasters reads the
 * band arrays autk-db's `getRaster` exports (with the grid Curio adds, see
 * `rasterWire.ts`) and writes the result as a collection of the same shape,
 * which autk-map draws as any other raster.
 *
 * Two rasters are compared only on one grid: the same size, origin, cell size
 * and CRS. Anything else is refused with a sentence that names both, since
 * resampling one onto the other is a choice the user makes, not one made here.
 *
 * Self-contained on purpose: no imports at run time, so the same functions can
 * run where Autark data sections run, in the sandbox's Node process.
 */
import type { RasterCollection, RasterGrid } from "./rasterWire";

export type NamedRaster = { name: string; collection: RasterCollection };

/** How close two grid coordinates must be to count as the same. */
const RELATIVE_TOLERANCE = 1e-9;

function same(a: number, b: number): boolean {
  return Math.abs(a - b) <= RELATIVE_TOLERANCE * Math.max(1, Math.abs(a), Math.abs(b));
}

/** What differs between two grids: `size`, `origin`, `resolution`, `CRS`. */
export function gridDifferences(a: RasterGrid, b: RasterGrid): string[] {
  const differs: string[] = [];
  if (a.width !== b.width || a.height !== b.height) differs.push("size");
  if (!same(a.originX, b.originX) || !same(a.originY, b.originY)) differs.push("origin");
  if (!same(a.resX, b.resX) || !same(a.resY, b.resY)) differs.push("resolution");
  if (String(a.crs).toUpperCase() !== String(b.crs).toUpperCase()) differs.push("CRS");
  return differs;
}

/** A grid in words: `40 by 30 cells of 30 by 30 in EPSG:32616 from (447000, 4637000)`. */
export function describeGrid(grid: RasterGrid): string {
  return `${grid.width} by ${grid.height} cells of ${grid.resX} by ${Math.abs(grid.resY)} `
    + `in ${grid.crs} from (${grid.originX}, ${grid.originY})`;
}

function bandIds(collection: RasterCollection): string[] {
  const bands = collection.features[0]?.properties?.bands;
  return Array.isArray(bands) ? bands.map((band) => String(band.id)) : [];
}

/**
 * `comparison` minus `reference`, cell by cell and band by band: positive
 * where the comparison is higher. A cell that is nodata (NaN) in either is
 * nodata in the result. Refused, naming both, when their grids or their bands
 * differ.
 */
export function subtractRasters(
  reference: NamedRaster,
  comparison: NamedRaster,
): { collection: RasterCollection } | { refused: string } {
  const a = reference.collection.grid;
  const b = comparison.collection.grid;
  const differs = gridDifferences(a, b);
  if (differs.length > 0) {
    return {
      refused: `${comparison.name} minus ${reference.name} cannot be computed: their grids differ in `
        + `${differs.join(", ")}. ${reference.name} is ${describeGrid(a)}; `
        + `${comparison.name} is ${describeGrid(b)}. Put both on one grid first.`,
    };
  }
  const ids = bandIds(reference.collection);
  const otherIds = bandIds(comparison.collection);
  if (ids.length === 0 || ids.join(",") !== otherIds.join(",")) {
    return {
      refused: `${comparison.name} minus ${reference.name} cannot be computed: their bands differ. `
        + `${reference.name} has ${ids.join(", ") || "none"}; ${comparison.name} has ${otherIds.join(", ") || "none"}.`,
    };
  }

  const cells = a.width * a.height;
  const from = reference.collection.features[0].properties;
  const to = comparison.collection.features[0].properties;
  const properties: Record<string, unknown> = { ...from };
  for (const id of ids) {
    const base = from[id] as ArrayLike<number>;
    const other = to[id] as ArrayLike<number>;
    const result = new Float32Array(cells);
    for (let i = 0; i < cells; i++) result[i] = Number(other[i]) - Number(base[i]);
    properties[id] = result;
  }
  return {
    collection: {
      type: "FeatureCollection",
      bbox: [...comparison.collection.bbox],
      grid: { ...b },
      features: [{ type: "Feature", geometry: null, properties: properties as any }],
    },
  };
}
