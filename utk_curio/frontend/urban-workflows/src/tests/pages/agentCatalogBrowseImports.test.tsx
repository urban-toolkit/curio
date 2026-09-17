/**
 * The account's own agents belong on /catalog/agents (#305).
 *
 * The page listed `GET /api/agents/catalog` and nothing else — built-ins union
 * published definitions. An agent the user authored and imported is in neither
 * set, so it appeared on no surface carrying `CatalogPublishPill`, and publish
 * was unreachable from the UI: the **Imported** filter could only ever match a
 * built-in the user had added to their account.
 *
 * Both peers already merge. `useNodeCatalogBrowse` fetches `catalog()` AND
 * `listInstalled()` and unions them; the Data Catalog lists `imported.*` and
 * `computed.*` rows. This pins the same shape for agents, with one difference
 * that matters: on a duplicate the IMPORTS card wins `publishable`, because
 * `list_global_catalog` never sets it, so a catalog row says false even for an
 * agent the caller published themselves (which is also why Unpublish was
 * unreachable).
 */
import { renderHook, act, waitFor } from "@testing-library/react";

const BUILTIN = {
  dirName: "agent.chat-agent",
  id: "agent.chat-agent",
  name: "Chat",
  purpose: "Conversational assistant",
  category: "node",
  capabilities: [],
  hooks: ["node"],
  tags: [],
  imported: false,
  published: false,
  publishable: false,
  provenance: { publisher: "curio", trust: "built-in" },
};

/** What the user wrote and uploaded through the drawer's Import agent footer. */
const MINE = {
  dirName: "me.my-agent",
  id: "me.my-agent",
  name: "My Agent",
  purpose: "Something I wrote",
  category: "canvas",
  capabilities: [],
  hooks: ["canvas"],
  tags: [],
  imported: true,
  published: false,
  publishable: true,
  provenance: { publisher: "me", trust: "imported" },
};

jest.mock("../../api/agentsApi", () => ({
  agentsApi: {
    catalog: jest.fn(),
    listImports: jest.fn(),
    publish: jest.fn(() => Promise.resolve({})),
    unpublish: jest.fn(() => Promise.resolve({})),
    import: jest.fn(() => Promise.resolve({})),
    removeImport: jest.fn(() => Promise.resolve({})),
  },
}));

jest.mock("../../providers/ToastProvider", () => ({
  useToastContext: () => ({ showToast: jest.fn() }),
}));

import { agentsApi } from "../../api/agentsApi";
import { useAgentCatalogBrowse } from "../../pages/agents/useAgentCatalogBrowse";

const mockCatalog = agentsApi.catalog as jest.Mock;
const mockImports = agentsApi.listImports as jest.Mock;

beforeEach(() => {
  jest.clearAllMocks();
  mockCatalog.mockResolvedValue({ items: [BUILTIN], agents: [BUILTIN], facets: null });
  mockImports.mockResolvedValue({ agents: [MINE] });
});

async function browse() {
  const { result } = renderHook(() => useAgentCatalogBrowse());
  await waitFor(() => expect(result.current.loading).toBe(false));
  return result;
}

describe("/catalog/agents lists the account's own agents", () => {
  it("shows an agent that exists only in the account's imports", async () => {
    const result = await browse();
    expect(result.current.agents.map((a) => a.dirName)).toEqual(
      expect.arrayContaining(["agent.chat-agent", "me.my-agent"]),
    );
  });

  it("offers Publish on it, which is the whole point", async () => {
    const result = await browse();
    const mine = result.current.agents.find((a) => a.dirName === "me.my-agent");
    expect(mine?.publishable).toBe(true);
  });

  it("makes the Imported filter mean something", async () => {
    const result = await browse();
    act(() => result.current.setFilter("imported"));
    await waitFor(() =>
      expect(result.current.filtered.map((a) => a.dirName)).toEqual(["me.my-agent"]),
    );
    expect(result.current.importedCount).toBe(1);
  });

  it("counts a category that only an imported agent has", async () => {
    const result = await browse();
    expect(Object.fromEntries(result.current.categories)).toMatchObject({ canvas: 1, node: 1 });
  });

  it("does not list the same agent twice once it is published", async () => {
    // Published, so it is in BOTH answers. The catalog row says
    // publishable:false (the backend never sets it), so the import's must win
    // or Unpublish is unreachable from the only surface that offers it.
    const published = { ...MINE, published: true, publishable: false, imported: false };
    const mineToo = { ...MINE, published: true, publishable: true };
    mockCatalog.mockResolvedValue({ items: [BUILTIN, published], agents: [], facets: null });
    mockImports.mockResolvedValue({ agents: [mineToo] });

    const result = await browse();

    const rows = result.current.agents.filter((a) => a.dirName === "me.my-agent");
    expect(rows).toHaveLength(1);
    expect(rows[0].published).toBe(true);
    expect(rows[0].publishable).toBe(true);
    expect(rows[0].imported).toBe(true);
  });

  it("keeps the catalog readable when the imports call fails", async () => {
    // The imports list is an addition, not a precondition: a failure there must
    // not blank the roster the user is reading.
    mockImports.mockRejectedValue(new Error("imports are down"));
    const result = await browse();
    expect(result.current.agents.map((a) => a.dirName)).toEqual(["agent.chat-agent"]);
  });

  it("re-reads both lists after an action, so a fresh import appears", async () => {
    const result = await browse();
    mockCatalog.mockClear();
    mockImports.mockClear();

    await act(async () => {
      await result.current.reload();
    });

    expect(mockCatalog).toHaveBeenCalledTimes(1);
    expect(mockImports).toHaveBeenCalledTimes(1);
  });
});
