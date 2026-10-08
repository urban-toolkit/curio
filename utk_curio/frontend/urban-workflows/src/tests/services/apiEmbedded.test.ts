/**
 * A standalone dashboard reads its rows out of its own page, never the network.
 *
 * Both readers matter and they are not the same one. A chart and a map go
 * through `fetchData`; a Data Pool tile renders its table through
 * `fetchPreviewData`, which bypasses `fetchData` entirely. Embedding only the
 * first would leave a pool tile as the single thing on an otherwise standalone
 * page still calling out, which is exactly the kind of gap that makes a page
 * look offline until somebody opens it offline.
 *
 * The preview has to keep its shape as well as its rows. The sandbox previews by
 * cutting the frame down and then serialising, so a dataframe arrives as columns
 * cut to length and a geodataframe as its first features, both carrying the row
 * counts the tile reports. Anything that is not a frame it sends whole.
 *
 * An Autark map over a Python node's raster asks `fetchRaster` for the raster's
 * GeoTIFF, which the page carries as `/raster` answered it when it was built.
 */
import { resolveRasterInputs } from "../../adapters/node/autkRasters";
import { fetchData, fetchPreviewData, fetchRaster } from "../../services/api";
import { resetEmbeddedDashboardForTests } from "../../standalone/dashboardPayload";
import { RASTER_MAX_CELLS, RASTER_MAX_SIDE } from "../../utils/raster/rasterLoad";

const originalFetch = global.fetch;

function serve(payload: unknown) {
  document.body.innerHTML = "";
  const el = document.createElement("script");
  el.id = "curio-dashboard-payload";
  el.type = "application/json";
  el.textContent = JSON.stringify(payload);
  document.body.appendChild(el);
  resetEmbeddedDashboardForTests();
}

function rows(count: number) {
  return Array.from({ length: count }, (_, i) => i);
}

beforeEach(() => {
  document.body.innerHTML = "";
  resetEmbeddedDashboardForTests();
  global.fetch = jest.fn(() => {
    throw new Error("a standalone dashboard must not reach the network");
  }) as unknown as typeof fetch;
});

afterEach(() => {
  global.fetch = originalFetch;
});

describe("fetchData on a standalone page", () => {
  test("it answers from the page, without a request", async () => {
    const envelope = { dataType: "dataframe", data: { n: [1, 2, 3] }, schema: { n: "int64" } };
    serve({ meta: {}, spec: {}, outputs: { "a.parquet": envelope } });

    const result = await fetchData("a.parquet");

    expect(result).toMatchObject(envelope);
    expect(global.fetch).not.toHaveBeenCalled();
  });

  test("it still fetches for an artifact the page does not carry", async () => {
    serve({ meta: {}, spec: {}, outputs: {} });

    await expect(fetchData("missing.parquet")).rejects.toThrow();
    expect(global.fetch).toHaveBeenCalled();
  });
});

describe("fetchPreviewData on a standalone page", () => {
  test("a pool tile reads its table from the page too", async () => {
    const envelope = { dataType: "dataframe", data: { n: [1, 2] }, schema: {} };
    serve({ meta: {}, spec: {}, outputs: { "a.parquet": envelope } });

    const result = await fetchPreviewData("a.parquet");

    expect(result.data).toEqual({ n: [1, 2] });
    // Short enough that the endpoint would not have cut it, so no preview keys.
    expect(result.preview).toBeUndefined();
    expect(global.fetch).not.toHaveBeenCalled();
  });

  test("a long frame is cut to the same hundred rows the endpoint sends", async () => {
    serve({
      meta: {},
      spec: {},
      outputs: {
        "big.parquet": { dataType: "dataframe", data: { n: rows(250), m: rows(250) }, schema: {} },
      },
    });

    const result = await fetchPreviewData("big.parquet");

    expect(result.data.n).toHaveLength(100);
    expect(result.data.m).toHaveLength(100);
    expect(result.preview).toBe(true);
    expect(result.previewRows).toBe(100);
    expect(result.totalRows).toBe(250);
  });

  test("a geodataframe is cut by features, not by columns", async () => {
    const features = rows(150).map((i) => ({ type: "Feature", properties: { i } }));
    serve({
      meta: {},
      spec: {},
      outputs: {
        "geo.parquet": {
          dataType: "geodataframe",
          data: { type: "FeatureCollection", features },
          schema: {},
        },
      },
    });

    const result = await fetchPreviewData("geo.parquet");

    expect(result.data.features).toHaveLength(100);
    expect(result.data.type).toBe("FeatureCollection");
    expect(result.totalRows).toBe(150);
  });

  test("a dict is sent whole, as the endpoint sends it", async () => {
    serve({
      meta: {},
      spec: {},
      outputs: { "d.json": { dataType: "dict", data: { a: 1, b: 2 }, schema: {} } },
    });

    const result = await fetchPreviewData("d.json");

    expect(result.data).toEqual({ a: 1, b: 2 });
    expect(result.preview).toBeUndefined();
  });
});

describe("fetchRaster on a standalone page", () => {
  const LIMITS = { maxCells: RASTER_MAX_CELLS, maxSide: RASTER_MAX_SIDE };
  const GEOTIFF = Uint8Array.from([0x49, 0x49, 0x2a, 0x00, 0, 1, 2, 127, 128, 254, 255]);
  const META = {
    width: 40, height: 30, count: 1, crs: "EPSG:32616", crsWkt: null,
    transform: [100, 0, 447000, 0, -100, 4637000], nodata: null, dtype: "float32",
  };

  function base64(bytes: Uint8Array): string {
    return btoa(String.fromCharCode(...Array.from(bytes)));
  }

  function served(filename: string, part: number | null, bytes: Uint8Array = GEOTIFF) {
    return { filename, part, status: 200, meta: META, geotiff: base64(bytes) };
  }

  test("it answers with the GeoTIFF the page carries, without a request", async () => {
    serve({ meta: {}, spec: {}, outputs: {}, rasters: [served("r_output", null)] });

    const answer = await fetchRaster("r_output", LIMITS);

    expect(answer.ok).toBe(true);
    if (!answer.ok) return;
    expect(new Uint8Array(answer.bytes)).toEqual(GEOTIFF);
    expect(answer.meta).toEqual(META);
    expect(global.fetch).not.toHaveBeenCalled();
  });

  test("a raster of a tuple is found by its place in it", async () => {
    serve({
      meta: {},
      spec: {},
      outputs: {},
      rasters: [served("t_output", 0, Uint8Array.from([1])), served("t_output", 1, Uint8Array.from([2]))],
    });

    const answer = await fetchRaster("t_output", { part: 1, ...LIMITS });

    expect(answer.ok && Array.from(new Uint8Array(answer.bytes))).toEqual([2]);
    expect(global.fetch).not.toHaveBeenCalled();
  });

  test("each map gets bytes of its own, since a load can take them", async () => {
    serve({ meta: {}, spec: {}, outputs: {}, rasters: [served("r_output", null)] });

    const first = await fetchRaster("r_output", LIMITS);
    const second = await fetchRaster("r_output", LIMITS);

    expect(first.ok && second.ok).toBe(true);
    if (!first.ok || !second.ok) return;
    expect(second.bytes).not.toBe(first.bytes);
    expect(new Uint8Array(second.bytes)).toEqual(GEOTIFF);
  });

  test("a raster /raster refused answers as the refusal, so the map says what the editor says", async () => {
    const big = { ...META, width: 5000, height: 5000 };
    serve({
      meta: {},
      spec: {},
      outputs: {},
      rasters: [{ filename: "big", part: null, status: 413, meta: big, message: "the raster is 5000 by 5000 cells" }],
    });

    const answer = await fetchRaster("big", LIMITS);

    expect(answer).toEqual({ ok: false, status: 413, meta: big, message: "the raster is 5000 by 5000 cells" });
    expect(global.fetch).not.toHaveBeenCalled();
  });

  test("it still asks the server for a raster the page does not carry", async () => {
    serve({ meta: {}, spec: {}, outputs: {} });

    await expect(fetchRaster("missing", LIMITS)).rejects.toThrow();
    expect(global.fetch).toHaveBeenCalled();
  });

  test("the map loads the page's GeoTIFF as it loads one from the server", async () => {
    serve({ meta: {}, spec: {}, outputs: {}, rasters: [served("r_output", null)] });

    const resolved = await resolveRasterInputs([{ outputTableName: "input_0", payload: { artifact: "r_output" } }]);

    expect(resolved.problems).toEqual([]);
    const [source] = resolved.sources;
    expect(new Uint8Array(source.geotiffArrayBuffer)).toEqual(GEOTIFF);
    expect(source.load).toEqual({ coordinateFormat: "EPSG:32616", maxRasterCells: 1200, resampleMethod: "nearest" });
    expect(global.fetch).not.toHaveBeenCalled();
  });
});
