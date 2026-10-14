/**
 * The Model Catalog's HTTP calls: the packages client, filtered to kind
 * `model`, sent with the session's bearer token like every other catalog
 * client, through the shared `apiFetch`. Nothing goes to `/api/models`.
 */
import { packagesApi } from "../../services/packages";
import { ddrnetPackage } from "../_support/modelPackages";

type FetchCall = [string, RequestInit];

function mockFetch(body: unknown, init: { ok?: boolean; status?: number } = {}) {
  const fetchMock = jest.fn().mockResolvedValue({
    ok: init.ok ?? true,
    status: init.status ?? 200,
    json: async () => body,
  });
  (global as unknown as { fetch: unknown }).fetch = fetchMock;
  return fetchMock;
}

function call(fetchMock: jest.Mock, index = 0): FetchCall {
  return fetchMock.mock.calls[index] as FetchCall;
}

/** The client as main types it: `kind`, `weightsLicense`, the listing's
 *  `usage` and Remove from account's `unusedOnly` are new. */
const api = packagesApi as unknown as {
  catalog: (kind?: string) => Promise<{ packages: unknown[] }>;
  listInstalled: (kind?: string, opts?: { usage?: boolean }) => Promise<{ packages: unknown[] }>;
  weightsLicense: (dirName: string) => Promise<string>;
  uninstallFromProject: (projectId: string, dirName: string) => Promise<unknown>;
  uninstall: (dirName: string, opts?: { unusedOnly?: boolean }) => Promise<unknown>;
};

beforeEach(() => {
  // `getToken` reads the session cookie; at the root of a host it is named
  // `session_token`.
  document.cookie = "session_token=tok-123; path=/";
});

afterEach(() => {
  document.cookie = "session_token=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/";
  jest.restoreAllMocks();
});

describe("the packages client, as the Model Catalog calls it", () => {
  test("lists the catalog's model packages with kind=model", async () => {
    const fetchMock = mockFetch({ packages: [ddrnetPackage()], families: [], catalogCollisions: [] });
    const res = await api.catalog("model");
    const [url, init] = call(fetchMock);
    expect(url).toMatch(/\/api\/packages\/catalog\?kind=model$/);
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer tok-123");
    expect((res.packages[0] as { dirName: string }).dirName).toBe("model.curio.ddrnet23-slim@1");
  });

  test("lists the account's model packages with kind=model", async () => {
    const fetchMock = mockFetch({ packages: [] });
    await api.listInstalled("model");
    expect(call(fetchMock)[0]).toMatch(/\/api\/packages\?kind=model$/);
  });

  test("without a kind, both listings ask for every package, as the Node Catalog always has", async () => {
    const fetchMock = mockFetch({ packages: [], families: [], catalogCollisions: [] });
    await api.catalog();
    await api.listInstalled();
    expect(call(fetchMock, 0)[0]).toMatch(/\/api\/packages\/catalog$/);
    expect(call(fetchMock, 1)[0]).toMatch(/\/api\/packages$/);
  });

  test("reads a model package's weights license text", async () => {
    const fetchMock = mockFetch({ text: "MIT License\n\nCopyright" });
    const text = await api.weightsLicense("model.curio.ddrnet23-slim@1");
    expect(call(fetchMock)[0]).toMatch(/\/api\/packages\/model\.curio\.ddrnet23-slim%401\/weights-license$/);
    expect(text).toBe("MIT License\n\nCopyright");
  });

  test("a package whose weights have no license text rejects with 404", async () => {
    mockFetch({ error: "no license text" }, { ok: false, status: 404 });
    await expect(api.weightsLicense("model.scout.deep-umbra@1")).rejects.toMatchObject({ status: 404 });
  });

  test("Remove takes a model out of one dataflow as it takes a node package", async () => {
    const fetchMock = mockFetch({ packages: [] });
    await api.uninstallFromProject("p1", "imported.xabc@1");
    const [url, init] = call(fetchMock);
    expect(url).toMatch(/\/api\/packages\/projects\/p1\/imported\.xabc@1$/);
    expect(init.method).toBe("DELETE");
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer tok-123");
  });

  test("a catalog page asks the store which packages a dataflow uses", async () => {
    const fetchMock = mockFetch({ packages: [] });
    await api.listInstalled(undefined, { usage: true });
    await api.listInstalled("model", { usage: true });
    expect(call(fetchMock, 0)[0]).toMatch(/\/api\/packages\?usage=true$/);
    expect(call(fetchMock, 1)[0]).toMatch(/\/api\/packages\?kind=model&usage=true$/);
  });

  test("Remove from account deletes a package only while no dataflow uses it", async () => {
    const fetchMock = mockFetch({});
    await api.uninstall("imported.xabc@1", { unusedOnly: true });
    const [url, init] = call(fetchMock);
    expect(url).toMatch(/\/api\/packages\/imported\.xabc@1\?unusedOnly=true$/);
    expect(init.method).toBe("DELETE");
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer tok-123");
  });
});
