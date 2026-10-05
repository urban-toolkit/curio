/**
 * A raster between nodes (#662, step 8): autk-db's `getRaster` collection
 * with Curio's grid, as the envelope another node receives, and as the
 * GeoTIFF Curio writes for autk-db to load. The sandbox runs the same cases
 * (utk_curio/sandbox/tests/test_rasters.py): a Python node rebuilds the
 * envelope as a rasterio dataset, and GDAL reads the GeoTIFF as the same grid.
 */
import cases from "../../utils/raster/rasterWire.cases.json";
import { writeGeoTiff } from "../../utils/raster/geotiffWriter";
import {
  decodeFloat32,
  decodeRasterEnvelope,
  encodeFloat32,
  encodeRasterEnvelope,
  isRasterEnvelope,
  type RasterCollection,
} from "../../utils/raster/rasterWire";

type Case = (typeof cases.cases)[number];

const float32 = (values: Array<number | null>) => Float32Array.from(values, (v) => (v === null ? NaN : v));

/** The collection autk-db's getRaster gives for a case, with its grid. */
function collectionOf(c: Case): RasterCollection {
  const bands = c.bands as Record<string, Array<number | null>>;
  const properties: Record<string, unknown> = {
    rasterResX: c.grid.width,
    rasterResY: c.grid.height,
    bands: Object.keys(bands).map((id) => ({ id, label: id })),
  };
  for (const [id, values] of Object.entries(bands)) properties[id] = float32(values);
  return {
    type: "FeatureCollection",
    bbox: c.bbox,
    grid: c.grid,
    features: [{ type: "Feature", geometry: null, properties: properties as any }],
  };
}

/** NaN-aware: what a band holds, with null for a nodata cell. */
const asList = (values: ArrayLike<number>) => Array.from(values, (v) => (Number.isNaN(v) ? null : v));

const base64Of = (buffer: ArrayBuffer) => Buffer.from(new Uint8Array(buffer)).toString("base64");

describe.each(cases.cases.map((c) => [c.name, c] as const))("%s", (_name, c) => {
  test("the envelope a node receives", () => {
    expect(encodeRasterEnvelope(collectionOf(c), c.layerName)).toEqual(c.envelope);
  });

  test("the envelope reads back as the same collection, nodata included", () => {
    const decoded = decodeRasterEnvelope(c.envelope);
    if (!("collection" in decoded)) throw new Error(decoded.problem);
    expect(decoded.collection.grid).toEqual(c.grid);
    expect(decoded.collection.bbox).toEqual(c.bbox);
    const props = decoded.collection.features[0].properties;
    for (const [id, values] of Object.entries(c.bands)) {
      expect(props[id]).toBeInstanceOf(Float32Array);
      expect(asList(props[id] as Float32Array)).toEqual(values);
    }
  });

  test("the GeoTIFF autk-db is handed", () => {
    const collection = collectionOf(c);
    const props = collection.features[0].properties;
    const bands = Object.keys(c.bands).map((id) => props[id] as Float32Array);
    expect(base64Of(writeGeoTiff(c.grid, bands))).toBe(c.geotiff_base64);
  });
});

describe("the wire", () => {
  test("float32 survives base64, NaN and all", () => {
    const values = float32([0, -1.5, null, 3.25e8, 1e-7]);
    const back = decodeFloat32(encodeFloat32(values));
    expect(asList(back)).toEqual(asList(values));
  });

  test("only an envelope with a collection is a raster envelope", () => {
    expect(isRasterEnvelope(cases.cases[0].envelope)).toBe(true);
    expect(isRasterEnvelope({ dataType: "raster", data: "/data/heat.tif" })).toBe(false);
    expect(isRasterEnvelope({ dataType: "geodataframe", data: { type: "FeatureCollection", features: [] } })).toBe(false);
  });

  test("an envelope that cannot be read says why", () => {
    const envelope = JSON.parse(JSON.stringify(cases.cases[0].envelope));
    delete envelope.data.grid;
    expect(decodeRasterEnvelope(envelope)).toEqual({ problem: "it does not say which grid its cells lie on" });

    const short = JSON.parse(JSON.stringify(cases.cases[0].envelope));
    short.data.features[0].properties.band_1.float32le = encodeFloat32([1, 2, 3]);
    expect(decodeRasterEnvelope(short)).toEqual({ problem: "its band band_1 does not hold one value per cell" });

    const wrongSize = JSON.parse(JSON.stringify(cases.cases[0].envelope));
    wrongSize.data.features[0].properties.rasterResX = 5;
    expect(decodeRasterEnvelope(wrongSize)).toEqual({ problem: "its size does not match its grid" });
  });

  test("a GeoTIFF needs an EPSG CRS and one value per cell", () => {
    const grid = cases.cases[0].grid;
    expect(() => writeGeoTiff({ ...grid, crs: "ESRI:102003" }, [new Float32Array(12)])).toThrow("EPSG");
    expect(() => writeGeoTiff(grid, [new Float32Array(11)])).toThrow("one value per cell");
  });
});
