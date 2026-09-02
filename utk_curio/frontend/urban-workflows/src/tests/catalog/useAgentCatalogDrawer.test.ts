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

const mockShowToast = jest.fn();
jest.mock("../../providers/ToastProvider", () => ({
  useToastContext: () => ({ showToast: mockShowToast }),
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
    // Two scopes, not three. "imports" listed the ACCOUNT's imported
    // definitions inside a per-dataflow drawer, which is the wrong surface for
    // an account-level list - and its row button was the only thing in the
    // product that wrote built-ins into that list, which is how "Dataflow
    // builder" came to report itself as one of the user's own imports.
    const { result } = renderHook(() => useAgentCatalogDrawer(true, "p1"));
    await waitFor(() => expect(result.current.loading).toBe(false));
    act(() => result.current.setScope("installed"));
    await waitFor(() => expect(api.listProjectAgents).toHaveBeenCalledWith("p1"));
    // And the account listing is never reached from this drawer at all.
    expect(api.listImports).not.toHaveBeenCalled();
  });

  it("install calls the endpoint then reloads the scope", async () => {
    const { result } = renderHook(() => useAgentCatalogDrawer(true, "p1"));
    await waitFor(() => expect(result.current.loading).toBe(false));
    api.catalog.mockClear();
    await act(async () => {
      await result.current.install(card("agent.node-explainer"));
    });
    expect(api.installToProject).toHaveBeenCalledWith("p1", "agent.node-explainer@1.0.0");
    expect(api.catalog).toHaveBeenCalled(); // reloaded
    expect(result.current.busyCoord).toBeNull();
  });

  it("toasts the agent's display name on install and on uninstall (#198)", async () => {
    const { result } = renderHook(() => useAgentCatalogDrawer(true, "p1"));
    await waitFor(() => expect(result.current.loading).toBe(false));
    mockShowToast.mockClear();

    await act(async () => {
      await result.current.install(card("agent.node-explainer"));
    });
    // The exact copy the Data catalog established, so all three agree.
    expect(mockShowToast).toHaveBeenCalledWith(
      "Added agent.node-explainer to this project.",
      "success",
    );

    mockShowToast.mockClear();
    await act(async () => {
      await result.current.uninstall(card("agent.node-explainer"));
    });
    expect(mockShowToast).toHaveBeenCalledWith(
      "Removed agent.node-explainer from this project.",
      "success",
    );
  });

  it("a failed install reports the error and toasts nothing (#198)", async () => {
    const { result } = renderHook(() => useAgentCatalogDrawer(true, "p1"));
    await waitFor(() => expect(result.current.loading).toBe(false));
    mockShowToast.mockClear();
    api.installToProject.mockRejectedValueOnce(new Error("pip exploded"));

    await act(async () => {
      await result.current.install(card("agent.node-explainer"));
    });

    // The drawer's own banner carries failures; a success toast here would
    // claim an add that never happened.
    expect(result.current.error).toBe("pip exploded");
    expect(mockShowToast).not.toHaveBeenCalled();
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

  it("installed scope with no project shows the account's agents, not nothing", async () => {
    // This asserted the opposite - empty - and that was the reported bug: a
    // dataflow is created on its FIRST SAVE, so a brand-new one has no project,
    // no lockfile to read, and this tab rendered blank even for agents the user
    // had just added to every project. They are in this dataflow too, one save
    // away, and `save_project` seeds them the moment it exists.
    //
    // The per-project read is still the truth once there IS a project: the
    // account list would otherwise show agents the user removed from THIS
    // dataflow.
    const { result } = renderHook(() => useAgentCatalogDrawer(true, null));
    await waitFor(() => expect(result.current.loading).toBe(false));
    act(() => result.current.setScope("installed"));
    await waitFor(() => expect(result.current.cards.length).toBeGreaterThan(0));
    expect(api.listProjectAgents).not.toHaveBeenCalled();
    expect(api.listImports).toHaveBeenCalled();
  });
});
