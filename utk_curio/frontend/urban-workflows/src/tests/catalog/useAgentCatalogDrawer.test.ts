import { renderHook, act, waitFor } from "@testing-library/react";

jest.mock("../../api/agentsApi", () => ({
  agentsApi: {
    catalog: jest.fn(),
    listImports: jest.fn(),
    listProjectAgents: jest.fn(),
    import: jest.fn(),
    removeImport: jest.fn(),
    installToProject: jest.fn(),
    uninstallFromProject: jest.fn(),
    publish: jest.fn(),
    unpublish: jest.fn(),
  },
}));

import { agentsApi } from "../../api/agentsApi";
import { useAgentCatalogDrawer } from "../../components/agents/catalog/useAgentCatalogDrawer";

const api = agentsApi as jest.Mocked<typeof agentsApi>;

function card(id: string) {
  return {
    id,
    version: "1.0.0",
    dirName: `${id}@1.0.0`,
    name: id,
    category: "node",
    purpose: "",
    capabilities: [],
    hooks: [],
    provenance: { publisher: "curio", trust: "built-in" },
    imported: false,
    installedInProject: false,
    published: false,
    publishable: false,
    requiresAgents: [],
    scope: "browse" as const,
  };
}

beforeEach(() => {
  jest.clearAllMocks();
  api.catalog.mockResolvedValue({ agents: [card("agent.node-explainer")] });
  api.listImports.mockResolvedValue({ agents: [card("agent.chat-agent")] });
  api.listProjectAgents.mockResolvedValue({ agents: [card("agent.debug-agent")] });
  api.import.mockResolvedValue({ coord: "x", imported: true });
  api.installToProject.mockResolvedValue({ agents: [], installed: [], required: [] });
  api.publish.mockResolvedValue({ coord: "x", published: true });
});

describe("useAgentCatalogDrawer", () => {
  it("loads the global catalog when presented", async () => {
    const { result } = renderHook(() => useAgentCatalogDrawer(true, "p1"));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(api.catalog).toHaveBeenCalledWith("p1");
    expect(result.current.cards.map((c) => c.id)).toEqual(["agent.node-explainer"]);
  });

  it("does not fetch when not presented", async () => {
    renderHook(() => useAgentCatalogDrawer(false, "p1"));
    await new Promise((r) => setTimeout(r, 10));
    expect(api.catalog).not.toHaveBeenCalled();
  });

  it("switching scope fetches that scope", async () => {
    const { result } = renderHook(() => useAgentCatalogDrawer(true, "p1"));
    await waitFor(() => expect(result.current.loading).toBe(false));
    act(() => result.current.setScope("imports"));
    await waitFor(() => expect(result.current.cards.map((c) => c.id)).toEqual(["agent.chat-agent"]));
    expect(api.listImports).toHaveBeenCalled();
  });

  it("install calls the endpoint then reloads the scope", async () => {
    const { result } = renderHook(() => useAgentCatalogDrawer(true, "p1"));
    await waitFor(() => expect(result.current.loading).toBe(false));
    api.catalog.mockClear();
    await act(async () => {
      await result.current.install("agent.node-explainer@1.0.0");
    });
    expect(api.installToProject).toHaveBeenCalledWith("p1", "agent.node-explainer@1.0.0");
    expect(api.catalog).toHaveBeenCalled(); // reloaded
    expect(result.current.busyCoord).toBeNull();
  });

  it("publish calls the endpoint then reloads", async () => {
    const { result } = renderHook(() => useAgentCatalogDrawer(true, "p1"));
    await waitFor(() => expect(result.current.loading).toBe(false));
    await act(async () => {
      await result.current.publish("agent.my-custom@1.0.0");
    });
    expect(api.publish).toHaveBeenCalledWith("agent.my-custom@1.0.0");
  });

  it("surfaces errors without throwing", async () => {
    api.catalog.mockRejectedValueOnce(new Error("boom"));
    const { result } = renderHook(() => useAgentCatalogDrawer(true, "p1"));
    await waitFor(() => expect(result.current.error).toBe("boom"));
    expect(result.current.cards).toEqual([]);
  });

  it("installed scope with no project yields empty", async () => {
    const { result } = renderHook(() => useAgentCatalogDrawer(true, null));
    await waitFor(() => expect(result.current.loading).toBe(false));
    act(() => result.current.setScope("installed"));
    await waitFor(() => expect(result.current.cards).toEqual([]));
    expect(api.listProjectAgents).not.toHaveBeenCalled();
  });
});
