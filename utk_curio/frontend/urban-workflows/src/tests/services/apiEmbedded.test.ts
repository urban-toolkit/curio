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
 */
import { fetchData, fetchPreviewData } from "../../services/api";
import { resetEmbeddedDashboardForTests } from "../../standalone/dashboardPayload";

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
