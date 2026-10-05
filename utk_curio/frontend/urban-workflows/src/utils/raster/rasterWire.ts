/**
 * A raster as Autark holds it, and as it travels between nodes.
 *
 * autk-db's `getRaster` exports a raster table as a FeatureCollection of one
 * feature with no geometry: the grid's size (`rasterResX`, `rasterResY`), its
 * bands, one Float32Array per band with rows from south to north, and the
 * extent in the workspace CRS as `bbox`. It does not say which CRS, origin or
 * cell size the grid was read in, so Curio adds them as `grid`, read from the
 * raster when it was loaded. Raster arithmetic compares grids on those fields.
 *
 * Between nodes the collection is an envelope, `{dataType: "raster", data}`,
 * whose bands are base64 of little-endian float32: a nodata cell (NaN)
 * survives JSON, and a Python node gets back exactly the values Autark held.
 * `utk_curio/sandbox/util/rasters.py` reads it; both sides run the cases in
 * `rasterWire.cases.json`.
 *
 * Pure, with no autk import, so it is testable under jest.
 */

/** The grid a raster's cells lie on. */
export type RasterGrid = {
  /** The CRS the grid is laid out in, as `EPSG:<code>`. */
  crs: string;
  width: number;
  height: number;
  /** The grid's top-left corner, in `crs`. */
  originX: number;
  originY: number;
  /** The cell size in `crs` units; `resY` is negative for a north-up grid. */
  resX: number;
  resY: number;
};

export type RasterBand = { id: string; label: string };

export type RasterProperties = {
  rasterResX: number;
  rasterResY: number;
  bands: RasterBand[];
  /** Each band's values by its id, rows from south to north. */
  [band: string]: unknown;
};

/** autk-db's `getRaster` collection, with the grid Curio adds. */
export type RasterCollection = {
  type: "FeatureCollection";
  bbox: number[];
  grid: RasterGrid;
  features: Array<{ type: "Feature"; geometry: null; properties: RasterProperties }>;
};

export const RASTER_DATA_TYPE = "raster";

/** The key a band's values are written under on the wire. */
export const WIRE_BAND_KEY = "float32le";

export type RasterEnvelope = {
  dataType: typeof RASTER_DATA_TYPE;
  data: RasterCollection;
  layerName?: string;
};

function isObject(value: unknown): value is Record<string, any> {
  return value != null && typeof value === "object" && !Array.isArray(value);
}

/** The ids of a collection's bands, in their order. */
export function rasterBandIds(collection: RasterCollection): string[] {
  const bands = collection.features[0]?.properties?.bands;
  return Array.isArray(bands) ? bands.map((band) => String(band.id)) : [];
}

/** A `getRaster` collection with its grid, its band arrays shared, not copied. */
export function withGrid(collection: any, grid: RasterGrid): RasterCollection {
  return { ...collection, grid: { ...grid } } as RasterCollection;
}

const CHUNK = 0x8000;

/** Base64 of the values as little-endian float32. */
export function encodeFloat32(values: ArrayLike<number>): string {
  const bytes = new Uint8Array(values.length * 4);
  const view = new DataView(bytes.buffer);
  for (let i = 0; i < values.length; i++) view.setFloat32(i * 4, Number(values[i]), true);
  let binary = "";
  for (let i = 0; i < bytes.length; i += CHUNK) {
    binary += String.fromCharCode.apply(null, Array.from(bytes.subarray(i, i + CHUNK)));
  }
  return btoa(binary);
}

/** The values base64 of little-endian float32 holds. */
export function decodeFloat32(text: string): Float32Array {
  const binary = atob(text);
  if (binary.length % 4 !== 0) throw new Error("a band's bytes are not a whole number of float32 values");
  const view = new DataView(new ArrayBuffer(binary.length));
  for (let i = 0; i < binary.length; i++) view.setUint8(i, binary.charCodeAt(i));
  const values = new Float32Array(binary.length / 4);
  for (let i = 0; i < values.length; i++) values[i] = view.getFloat32(i * 4, true);
  return values;
}

/** Whether a value is a raster envelope, whatever its bands hold. */
export function isRasterEnvelope(value: unknown): value is { dataType: "raster"; data: any; layerName?: string } {
  return isObject(value) && value.dataType === RASTER_DATA_TYPE && isObject(value.data)
    && value.data.type === "FeatureCollection";
}

/** The envelope a node hands on for a raster collection. */
export function encodeRasterEnvelope(collection: RasterCollection, layerName?: string): RasterEnvelope {
  const [feature] = collection.features;
  const properties: Record<string, unknown> = { ...feature.properties };
  for (const id of rasterBandIds(collection)) {
    properties[id] = { [WIRE_BAND_KEY]: encodeFloat32(feature.properties[id] as ArrayLike<number>) };
  }
  return {
    dataType: RASTER_DATA_TYPE,
    data: {
      type: "FeatureCollection",
      bbox: [...collection.bbox],
      grid: { ...collection.grid },
      features: [{ type: "Feature", geometry: null, properties: properties as RasterProperties }],
    },
    ...(layerName ? { layerName } : {}),
  };
}

const GRID_NUMBERS: Array<keyof RasterGrid> = ["width", "height", "originX", "originY", "resX", "resY"];

/**
 * The collection an envelope holds, its bands as Float32Arrays, or why it
 * cannot be read.
 */
export function decodeRasterEnvelope(value: unknown): { collection: RasterCollection } | { problem: string } {
  if (!isRasterEnvelope(value)) return { problem: "it is not a raster" };
  const data = value.data;
  const grid = data.grid;
  if (!isObject(grid) || typeof grid.crs !== "string" || !GRID_NUMBERS.every((key) => Number.isFinite(grid[key]))) {
    return { problem: "it does not say which grid its cells lie on" };
  }
  const feature = Array.isArray(data.features) ? data.features[0] : null;
  const properties = isObject(feature?.properties) ? feature.properties : null;
  if (!properties || properties.rasterResX !== grid.width || properties.rasterResY !== grid.height) {
    return { problem: "its size does not match its grid" };
  }
  const bands: RasterBand[] = Array.isArray(properties.bands) ? properties.bands : [];
  if (bands.length === 0) return { problem: "it has no bands" };
  const decoded: Record<string, unknown> = { ...properties };
  for (const band of bands) {
    const wire = properties[band.id];
    const values = isObject(wire) && typeof wire[WIRE_BAND_KEY] === "string"
      ? decodeFloat32(wire[WIRE_BAND_KEY])
      : null;
    if (!values || values.length !== grid.width * grid.height) {
      return { problem: `its band ${band.id} does not hold one value per cell` };
    }
    decoded[band.id] = values;
  }
  return {
    collection: {
      type: "FeatureCollection",
      bbox: Array.isArray(data.bbox) ? [...data.bbox] : [],
      grid: { ...(grid as RasterGrid) },
      features: [{ type: "Feature", geometry: null, properties: decoded as RasterProperties }],
    },
  };
}
