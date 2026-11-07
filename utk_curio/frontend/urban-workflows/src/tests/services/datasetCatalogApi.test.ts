import {
  encodeLiveOutputsParam,
  datasetCatalogApi,
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

describe("datasetCatalogApi.downloadDataset (a bundle's zip)", () => {
  let saved: string[] = [];
  const createObjectURL = URL.createObjectURL;
  const revokeObjectURL = URL.revokeObjectURL;

  beforeEach(() => {
    saved = [];
    URL.createObjectURL = jest.fn(() => "blob:export");
    URL.revokeObjectURL = jest.fn();
    jest.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      saved.push(this.download);
    });
  });

  afterEach(() => {
    URL.createObjectURL = createObjectURL;
    URL.revokeObjectURL = revokeObjectURL;
    jest.restoreAllMocks();
  });

  function respond(type: string, disposition: string | null) {
    (global as any).fetch = jest.fn().mockResolvedValue({
      ok: true,
      blob: async () => new Blob(["PK"], { type }),
      headers: { get: (name: string) => (name.toLowerCase() === "content-disposition" ? disposition : null) },
    });
  }

  test("saves under the server's name, and a zip it names no file for still ends in .zip", async () => {
    respond("application/zip", 'attachment; filename="Chicago Loop Layers.zip"');
    await datasetCatalogApi.downloadDataset("data.curio.chicago-loop-layers", { format: "bundle" });
    // By the zip's type, then by the bundle's format when the type says nothing.
    respond("application/zip", null);
    await datasetCatalogApi.downloadDataset("computed.flow.n1", { format: "bundle" });
    respond("application/octet-stream", null);
    await datasetCatalogApi.downloadDataset("computed.flow.n2", { format: "bundle" });

    expect(saved).toEqual(["Chicago Loop Layers.zip", "computed_flow_n1.zip", "computed_flow_n2.zip"]);
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

  test("states where a hand-downloaded file came from, and nothing for a plain upload", async () => {
    const fetchMock = mockFetch();
    const file = new File(["a,b\n1,2"], "cities.csv", { type: "text/csv" });

    await datasetCatalogApi.importDataset(file, {
      discoverySource: { resourceUrl: "https://data.example.org/cities.csv" },
    });
    await datasetCatalogApi.importDataset(file);

    const stated = fetchMock.mock.calls[0][1].body as FormData;
    expect(JSON.parse(stated.get("discoverySource") as string)).toEqual({
      resourceUrl: "https://data.example.org/cities.csv",
    });
    expect((fetchMock.mock.calls[1][1].body as FormData).get("discoverySource")).toBeNull();
  });
});
