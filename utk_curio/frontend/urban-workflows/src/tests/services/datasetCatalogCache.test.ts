import { renderHook, act } from "@testing-library/react";
import {
  catalogCacheEpoch,
  catalogCacheSize,
  invalidateDatasetCatalogCache,
  peekCatalogCache,
  writeCatalogCache,
} from "../../services/datasetCatalog/datasetCatalogCache";
import {
  datasetCatalogApi,
  notifyDatasetCatalogRefresh,
} from "../../services/datasetCatalog/datasetCatalogApi";
import {
  catalogFetchKey,
  toStableCatalogQuery,
  useDatasetCatalog,
} from "../../services/datasetCatalog/datasetCatalogHooks";
import type {
  DatasetCatalogItem,
  DatasetCatalogResponse,
} from "../../services/datasetCatalog/datasetCatalogTypes";

function makeResponse(id: string): DatasetCatalogResponse {
  return {
    items: [{ id, title: id, origin: "imported", format: "csv" } as DatasetCatalogItem],
    facets: {
      origin: { source_node: 0, computed: 0, imported: 1, hub: 0 },
      format: { csv: 1, geojson: 0, json: 0, parquet: 0, geotiff: 0, shp: 0 },
    } as DatasetCatalogResponse["facets"],
  };
}

describe("datasetCatalogCache", () => {
  beforeEach(() => {
    // Module-level state persists across tests; start each from a clean slate.
    invalidateDatasetCatalogCache();
  });

  it("stores and returns entries written under the current epoch", () => {
    const epoch = catalogCacheEpoch();
    expect(writeCatalogCache("k1", makeResponse("a"), epoch)).toBe(true);
    expect(peekCatalogCache("k1")?.items[0].id).toBe("a");
  });

  it("invalidate clears every key and bumps the epoch", () => {
    const epoch = catalogCacheEpoch();
    writeCatalogCache("k1", makeResponse("a"), epoch);
    writeCatalogCache("k2", makeResponse("b"), epoch);

    invalidateDatasetCatalogCache();

    expect(peekCatalogCache("k1")).toBeUndefined();
    expect(peekCatalogCache("k2")).toBeUndefined();
    expect(catalogCacheSize()).toBe(0);
    expect(catalogCacheEpoch()).toBe(epoch + 1);
  });

  it("drops a write whose fetch started before an invalidation (straddling fetch)", () => {
    const fetchEpoch = catalogCacheEpoch(); // fetch starts…
    invalidateDatasetCatalogCache(); // …mutation invalidates mid-flight…
    expect(writeCatalogCache("k1", makeResponse("stale"), fetchEpoch)).toBe(false); // …response lands

    expect(peekCatalogCache("k1")).toBeUndefined();
    expect(catalogCacheSize()).toBe(0);
  });

  it("evicts least-recently-used entries beyond the cap", () => {
    const epoch = catalogCacheEpoch();
    for (let i = 0; i < 16; i += 1) {
      writeCatalogCache(`k${i}`, makeResponse(`r${i}`), epoch);
    }
    expect(catalogCacheSize()).toBe(16);

    // Touch k0 so it becomes most-recent; the next write must evict k1 instead.
    peekCatalogCache("k0");
    writeCatalogCache("k16", makeResponse("r16"), epoch);

    expect(catalogCacheSize()).toBe(16);
    expect(peekCatalogCache("k0")).toBeDefined();
    expect(peekCatalogCache("k1")).toBeUndefined();
    expect(peekCatalogCache("k16")).toBeDefined();
  });

  it("notifyDatasetCatalogRefresh invalidates the cache even with no listeners mounted", () => {
    const epoch = catalogCacheEpoch();
    writeCatalogCache("k1", makeResponse("a"), epoch);

    notifyDatasetCatalogRefresh();

    expect(peekCatalogCache("k1")).toBeUndefined();
    expect(catalogCacheEpoch()).toBe(epoch + 1);
  });
});

describe("useDatasetCatalog cache epoch guard", () => {
  beforeEach(() => {
    invalidateDatasetCatalogCache();
    jest.restoreAllMocks();
  });

  it("does not repopulate the cache from a fetch that resolved after an invalidation", async () => {
    let resolveFetch!: (response: DatasetCatalogResponse) => void;
    jest.spyOn(datasetCatalogApi, "listCatalog").mockImplementation(
      () => new Promise<DatasetCatalogResponse>((resolve) => {
        resolveFetch = resolve;
      }),
    );

    const query = { dataflowId: "flow-1" };
    const fetchKey = catalogFetchKey(toStableCatalogQuery(query));
    const { result } = renderHook(() => useDatasetCatalog(query));

    // Mount effect kicked off the fetch; invalidate while it is in flight.
    await act(async () => {});
    invalidateDatasetCatalogCache();

    const preMutation = makeResponse("pre-mutation");
    await act(async () => {
      resolveFetch(preMutation);
    });

    // The hook may render the response (freshest data it has)…
    expect(result.current.items.map((i) => i.id)).toEqual(["pre-mutation"]);
    // …but the SHARED cache must not serve it to the next mount.
    expect(peekCatalogCache(fetchKey)).toBeUndefined();
  });

  it("caches a fetch that completed without an intervening invalidation", async () => {
    jest
      .spyOn(datasetCatalogApi, "listCatalog")
      .mockResolvedValue(makeResponse("fresh"));

    const query = { dataflowId: "flow-1" };
    const fetchKey = catalogFetchKey(toStableCatalogQuery(query));
    const { result } = renderHook(() => useDatasetCatalog(query));

    await act(async () => {});

    expect(result.current.items.map((i) => i.id)).toEqual(["fresh"]);
    expect(peekCatalogCache(fetchKey)?.items[0].id).toBe("fresh");
  });
});
