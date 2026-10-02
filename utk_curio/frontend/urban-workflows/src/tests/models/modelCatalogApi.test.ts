/**
 * The Model Catalog's HTTP client: the four routes the backend serves under
 * `/api/models`, sent with the session's bearer token like every other catalog
 * client, through the shared `apiFetch`.
 */
import { modelCatalogApi } from "../../services/modelCatalog";
import { shippedModel } from "../_support/modelRows";

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

beforeEach(() => {
  // `getToken` reads the session cookie; at the root of a host it is named
  // `session_token`.
  document.cookie = "session_token=tok-123; path=/";
});

afterEach(() => {
  document.cookie = "session_token=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/";
  jest.restoreAllMocks();
});

describe("modelCatalogApi", () => {
  test("lists the catalog, with the search text as q", async () => {
    const fetchMock = mockFetch({ items: [shippedModel()] });
    const res = await modelCatalogApi.listCatalog({ q: "  street scenes " });
    const [url, init] = call(fetchMock);
    expect(url).toMatch(/\/api\/models\/catalog\?q=street\+scenes$/);
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer tok-123");
    expect(res.items[0].id).toBe("model.curio.ddrnet23-slim");
  });

  test("an empty search sends no query string at all", async () => {
    const fetchMock = mockFetch({ items: [] });
    await modelCatalogApi.listCatalog({ q: "   " });
    expect(call(fetchMock)[0]).toMatch(/\/api\/models\/catalog$/);
  });

  test("reads one model by its id, encoded", async () => {
    const fetchMock = mockFetch(shippedModel());
    await modelCatalogApi.getModel("model.curio.ddrnet23-slim@1");
    expect(call(fetchMock)[0]).toMatch(/\/api\/models\/model\.curio\.ddrnet23-slim%401$/);
  });

  test("reads the license text", async () => {
    const fetchMock = mockFetch({ text: "MIT License\n\nCopyright" });
    const text = await modelCatalogApi.getLicense("model.curio.ddrnet23-slim");
    expect(call(fetchMock)[0]).toMatch(/\/api\/models\/model\.curio\.ddrnet23-slim\/license$/);
    expect(text).toBe("MIT License\n\nCopyright");
  });

  test("deletes with DELETE and the bearer token", async () => {
    const fetchMock = mockFetch({ deleted: "imported.xabc" });
    const res = await modelCatalogApi.deleteModel("imported.xabc");
    const [url, init] = call(fetchMock);
    expect(url).toMatch(/\/api\/models\/imported\.xabc$/);
    expect(init.method).toBe("DELETE");
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer tok-123");
    expect(res).toEqual({ deleted: "imported.xabc" });
  });

  test("a refused delete rejects with the server's reason and status", async () => {
    mockFetch(
      { error: "DDRNet23-Slim ships with Curio and cannot be deleted" },
      { ok: false, status: 403 },
    );
    await expect(modelCatalogApi.deleteModel("model.curio.ddrnet23-slim")).rejects.toMatchObject({
      message: "DDRNet23-Slim ships with Curio and cannot be deleted",
      status: 403,
    });
  });

  test("an unknown model rejects with 404", async () => {
    mockFetch({ error: "no model 'x' in your Model Catalog" }, { ok: false, status: 404 });
    await expect(modelCatalogApi.getModel("x")).rejects.toMatchObject({ status: 404 });
  });
});
