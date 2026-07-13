import {
  encodeLiveOutputsParam,
  buildInstalledDatasetRef,
  upsertDataflowDatasetRef,
  applyInstalledDatasetToProject,
  datasetCatalogApi,
  DATASET_CATALOG_REFRESH_EVENT,
} from "../../services/datasetCatalog/datasetCatalogApi";

/**
 * Regression for issue #139: the liveOutputs query param must be encoded as
 * UTF-8-safe base64 so the backend's ``base64.b64decode(raw).decode("utf-8")``
 * round-trips. downloadDataset previously used raw ``btoa``, which throws (or
 * mis-encodes) on non-Latin1 filenames/data_types and 404s.
 */
describe("encodeLiveOutputsParam", () => {
  const decodeUtf8 = (b64: string) => Buffer.from(b64, "base64").toString("utf-8");

  test("round-trips non-Latin1 filenames (CJK + accents + emoji) as UTF-8", () => {
    const outputs = [
      { node_id: "n1", filename: "café_\u6570\u636e_\uD83C\uDF0D.csv", data_type: "dataframe" },
    ];
    const encoded = encodeLiveOutputsParam(outputs);
    expect(JSON.parse(decodeUtf8(encoded))).toEqual(outputs);
  });

  test("does not throw on code points > 0xFF (the raw btoa bug)", () => {
    const outputs = [{ node_id: "n", filename: "\uD83C\uDF0D" }];
    expect(() => encodeLiveOutputsParam(outputs)).not.toThrow();
    // Contrast: the previous implementation would have thrown here.
    expect(() => btoa(JSON.stringify(outputs))).toThrow();
  });

  test("still encodes the original ASCII export case", () => {
    const outputs = [{ node_id: "n1", filename: "data.csv", data_type: "dataframe" }];
    expect(decodeUtf8(encodeLiveOutputsParam(outputs))).toBe(JSON.stringify(outputs));
  });
});

describe("datasetCatalogApi.importDataset (source file date)", () => {
  const okJson = { id: "imported.x1", origin: "imported" };

  afterEach(() => {
    jest.restoreAllMocks();
  });

  function mockFetch() {
    const fetchMock = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => okJson,
    });
    (global as any).fetch = fetchMock;
    return fetchMock;
  }

  test("sends the file's lastModified as sourceUpdatedAt (epoch ms)", async () => {
    const fetchMock = mockFetch();
    const file = new File(["a,b\n1,2"], "cities.csv", {
      type: "text/csv",
      lastModified: 1577934245000,
    });

    await datasetCatalogApi.importDataset(file);

    const body = fetchMock.mock.calls[0][1].body as FormData;
    expect(body.get("sourceUpdatedAt")).toBe("1577934245000");
    expect(body.get("file")).toBeInstanceOf(File);
  });

  test("omits sourceUpdatedAt when lastModified is not a positive number", async () => {
    const fetchMock = mockFetch();
    const file = new File(["x"], "x.csv", { type: "text/csv", lastModified: 0 });

    await datasetCatalogApi.importDataset(file);

    const body = fetchMock.mock.calls[0][1].body as FormData;
    expect(body.get("sourceUpdatedAt")).toBeNull();
  });
});

describe("buildInstalledDatasetRef", () => {
  test("maps the install payload to the lean spec ref shape", () => {
    const ref = buildInstalledDatasetRef({
      id: "computed.n1@1",
      dirName: "computed.n1@1",
      origin: "computed",
      producerNodeId: "n1",
    });
    expect(ref).toMatchObject({
      datasetId: "computed.n1@1",
      dirName: "computed.n1@1",
      origin: "computed",
      producerNodeId: "n1",
    });
    expect(typeof ref.installedAt).toBe("string");
  });

  test("defaults origin to 'computed' and producerNodeId to null", () => {
    const ref = buildInstalledDatasetRef({ id: "d1", dirName: "d1" });
    expect(ref.origin).toBe("computed");
    expect(ref.producerNodeId).toBeNull();
  });
});

describe("upsertDataflowDatasetRef", () => {
  const ref = buildInstalledDatasetRef({ id: "d1", dirName: "d1" });

  test("appends when the dataset is new", () => {
    const out = upsertDataflowDatasetRef([{ datasetId: "other" }], "d1", ref);
    expect(out).toHaveLength(2);
    expect(out[1]).toBe(ref);
  });

  test("replaces an existing entry matched by datasetId (no duplicates)", () => {
    const out = upsertDataflowDatasetRef([{ datasetId: "d1", stale: true }], "d1", ref);
    expect(out).toHaveLength(1);
    expect(out[0]).toBe(ref);
  });

  test("also matches a legacy entry keyed by `id`", () => {
    const out = upsertDataflowDatasetRef([{ id: "d1", stale: true }], "d1", ref);
    expect(out).toHaveLength(1);
    expect(out[0]).toBe(ref);
  });

  test("tolerates a non-array previous value", () => {
    expect(upsertDataflowDatasetRef(undefined, "d1", ref)).toEqual([ref]);
    expect(upsertDataflowDatasetRef(null, "d1", ref)).toEqual([ref]);
  });
});

describe("applyInstalledDatasetToProject", () => {
  test("upserts via the setter and fires the catalog refresh event", () => {
    const dispatch = jest.spyOn(window, "dispatchEvent");
    let state: unknown[] = [{ datasetId: "old" }];
    const setter = jest.fn((updater: any) => {
      state = typeof updater === "function" ? updater(state) : updater;
    });

    applyInstalledDatasetToProject(
      { id: "computed.n1@1", dirName: "computed.n1@1", producerNodeId: "n1" },
      setter as any,
    );

    expect(setter).toHaveBeenCalledTimes(1);
    expect(state).toHaveLength(2);
    expect((state[1] as any).datasetId).toBe("computed.n1@1");
    expect(dispatch).toHaveBeenCalledWith(
      expect.objectContaining({ type: DATASET_CATALOG_REFRESH_EVENT }),
    );
    dispatch.mockRestore();
  });

  test("is a no-op for a missing or partial payload", () => {
    const dispatch = jest.spyOn(window, "dispatchEvent");
    const setter = jest.fn();
    applyInstalledDatasetToProject(null, setter as any);
    applyInstalledDatasetToProject({ id: "x" } as any, setter as any); // no dirName
    expect(setter).not.toHaveBeenCalled();
    expect(dispatch).not.toHaveBeenCalled();
    dispatch.mockRestore();
  });
});
