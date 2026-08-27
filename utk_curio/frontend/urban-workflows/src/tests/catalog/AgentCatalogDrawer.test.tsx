import React from "react";
import { render, screen, fireEvent, waitFor, within, act } from "@testing-library/react";

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
    uploadImport: jest.fn(),
  },
}));

import { agentsApi } from "../../api/agentsApi";
import { AgentCatalogDrawer } from "../../components/agents/catalog/AgentCatalogDrawer";

const api = agentsApi as jest.Mocked<typeof agentsApi>;

function card(id: string, over: Record<string, unknown> = {}) {
  return {
    id,
    version: "1.0.0",
    dirName: `${id}@1.0.0`,
    name: id.replace("agent.", ""),
    category: "node",
    purpose: "does a thing",
    capabilities: ["node.explain"],
    hooks: ["node"],
    provenance: { publisher: "curio", trust: "built-in" },
    imported: false,
    installedInProject: false,
    published: false,
    publishable: false,
    requiresAgents: [],
    scope: "browse",
    ...over,
  };
}

beforeEach(() => {
  jest.clearAllMocks();
  api.catalog.mockResolvedValue({ agents: [card("agent.node-explainer")] } as any);
  api.listImports.mockResolvedValue({ agents: [card("agent.chat-agent", { scope: "imports", imported: true })] } as any);
  api.listProjectAgents.mockResolvedValue({ agents: [] } as any);
  api.installToProject.mockResolvedValue({ agents: [] } as any);
  api.uninstallFromProject.mockResolvedValue({ agents: [] } as any);
  api.publish.mockResolvedValue({ coord: "x", published: true } as any);
});

// AI Settings reads UserProvider, which reaches the package registry and
// through it vega (ESM, unloadable under jest). projectsPageChrome and
// projectsListScroll mock it for the same reason. What this file asserts is
// that the cog opens it - not what it contains.
jest.mock("../../components/AiSettingsModal", () => ({
  __esModule: true,
  default: ({ isOpen }: { isOpen: boolean }) =>
    isOpen ? <div data-testid="ai-settings-modal">AI Settings</div> : null,
}));

describe("AgentCatalogDrawer", () => {
  it("is hidden (not accessible) when not presented", () => {
    // dev/43: the drawer stays mounted through the exit slide; while not
    // presented it is aria-hidden and pointer-inert, never abruptly removed.
    const { container } = render(
      <AgentCatalogDrawer presented={false} projectId="p1" pinned={false} onPinToggle={jest.fn()} />,
    );
    expect(screen.queryByRole("dialog", { name: "Agent Catalog" })).not.toBeInTheDocument();
    const root = container.querySelector("[data-curio-agent-catalog-drawer]");
    expect(root).toHaveAttribute("aria-hidden", "true");
  });

  it("renders the three tabs and the browse cards", async () => {
    render(<AgentCatalogDrawer presented projectId="p1" pinned={false} onPinToggle={jest.fn()} />);
    expect(screen.getByText("Browse all")).toBeInTheDocument();
    expect(screen.getByText("My imports")).toBeInTheDocument();
    expect(screen.getByText("In dataflow")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("node-explainer")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Add to dataflow" })).toBeInTheDocument();
  });

  it("switching to My imports fetches and offers Remove from my account", async () => {
    render(<AgentCatalogDrawer presented projectId="p1" pinned={false} onPinToggle={jest.fn()} />);
    await waitFor(() => expect(screen.getByText("node-explainer")).toBeInTheDocument());
    fireEvent.click(screen.getByText("My imports"));
    await waitFor(() => expect(api.listImports).toHaveBeenCalled());
    await waitFor(() => expect(screen.getByText("chat-agent")).toBeInTheDocument());
    // Not "Delete": the call drops the registry entry and leaves the
    // definition on disk, so the drawer says what the browse page says.
    expect(screen.getByRole("button", { name: "Remove from my account" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Delete" })).toBeNull();
  });

  it("Add to dataflow disabled without a project", async () => {
    render(<AgentCatalogDrawer presented projectId={null} pinned={false} onPinToggle={jest.fn()} />);
    await waitFor(() => expect(screen.getByText("node-explainer")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Add to dataflow" })).toBeDisabled();
  });

  it("shows Publish only for a publishable My imports card and publishes on click", async () => {
    api.listImports.mockResolvedValue({
      agents: [
        card("agent.my-custom", { scope: "imports", imported: true, publishable: true }),
        card("agent.node-explainer", { scope: "imports", imported: true, publishable: false }),
      ],
    } as any);
    render(<AgentCatalogDrawer presented projectId="p1" pinned={false} onPinToggle={jest.fn()} />);
    fireEvent.click(screen.getByText("My imports"));
    await waitFor(() => expect(screen.getByText("my-custom")).toBeInTheDocument());
    // Exactly one Publish control — the built-in card (publishable:false) shows none.
    const publishBtns = screen.getAllByRole("button", { name: /publish/i });
    expect(publishBtns).toHaveLength(1);
    fireEvent.click(publishBtns[0]);
    await waitFor(() => expect(api.publish).toHaveBeenCalledWith("agent.my-custom@1.0.0"));
  });

  it("clicking Add to dataflow calls the install endpoint", async () => {
    render(<AgentCatalogDrawer presented projectId="p1" pinned={false} onPinToggle={jest.fn()} />);
    await waitFor(() => expect(screen.getByText("node-explainer")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Add to dataflow" }));
    await waitFor(() =>
      expect(api.installToProject).toHaveBeenCalledWith("p1", "agent.node-explainer@1.0.0"),
    );
  });

  it("discloses a missing required dependency on the card and the Add button", async () => {
    api.catalog.mockResolvedValue({
      agents: [
        card("agent.dataflow-builder", {
          name: "Dataflow Builder",
          category: "canvas",
          requiresAgents: [{
            id: "agent.node-content-builder", name: "Node Content Builder",
            coord: "agent.node-content-builder@1.0.0", visible: true, installedInProject: false,
          }],
        }),
      ],
    } as any);
    render(<AgentCatalogDrawer presented projectId="p1" pinned={false} onPinToggle={jest.fn()} />);
    await waitFor(() => expect(screen.getByText("Dataflow Builder")).toBeInTheDocument());
    expect(screen.getByText(/Requires:/)).toBeInTheDocument();
    expect(screen.getByText("Node Content Builder (not installed)")).toBeInTheDocument();
    const btn = screen.getByRole("button", { name: "Add to dataflow (+1 required)" });
    expect(btn).toHaveAttribute("title", "Also adds Node Content Builder (required)");
    fireEvent.click(btn);
    await waitFor(() =>
      expect(api.installToProject).toHaveBeenCalledWith("p1", "agent.dataflow-builder@1.0.0"),
    );
  });

  it("a satisfied dependency renders a check and a plain Add to dataflow", async () => {
    api.catalog.mockResolvedValue({
      agents: [
        card("agent.dataflow-builder", {
          name: "Dataflow Builder",
          requiresAgents: [{
            id: "agent.node-content-builder", name: "Node Content Builder",
            coord: "agent.node-content-builder@1.0.0", visible: true, installedInProject: true,
          }],
        }),
      ],
    } as any);
    render(<AgentCatalogDrawer presented projectId="p1" pinned={false} onPinToggle={jest.fn()} />);
    await waitFor(() => expect(screen.getByText("Dataflow Builder")).toBeInTheDocument());
    expect(screen.getByText("Node Content Builder ✓")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add to dataflow" })).toBeInTheDocument();
  });

  it("a 409 from uninstalling a required dependency surfaces verbatim (dev/106)", async () => {
    api.listProjectAgents.mockResolvedValue({
      agents: [card("agent.node-content-builder", { scope: "installed", installedInProject: true })],
    } as any);
    api.uninstallFromProject.mockRejectedValue(
      new Error("agent.node-content-builder@1.0.0 is required by Dataflow Builder (agent.dataflow-builder@1.0.0) — uninstall that agent first"),
    );
    render(<AgentCatalogDrawer presented projectId="p1" pinned={false} onPinToggle={jest.fn()} />);
    fireEvent.click(screen.getByText("In dataflow"));
    await waitFor(() => expect(screen.getByText("node-content-builder")).toBeInTheDocument());
    // Removal now confirms, as it does in the Node and Data drawers.
    const confirmSpy = jest.spyOn(window, "confirm").mockReturnValue(true);
    fireEvent.click(screen.getByRole("button", { name: "Remove from dataflow" }));
    confirmSpy.mockRestore();
    await waitFor(() =>
      expect(screen.getByText(/is required by Dataflow Builder/)).toBeInTheDocument(),
    );
  });

  it("header carries the Pin and a Close, like the other catalog drawers", async () => {
    const onPinToggle = jest.fn();
    render(<AgentCatalogDrawer presented projectId="p1" pinned={false} onPinToggle={onPinToggle} />);
    const pin = screen.getByRole("button", { name: "Pin drawer open" });
    expect(pin).toHaveAttribute("aria-pressed", "false");
    // The drawer used to omit this, on the grounds that the other catalog
    // drawers dismiss through the scrim. They do not - both render a close
    // button from the shared DrawerHeader - so a dialog with no in-dialog
    // dismissal was the odd one out, and the harder one to leave by keyboard.
    const dialog = screen.getByRole("dialog", { name: "Agent Catalog" });
    expect(
      within(dialog).getByRole("button", { name: "Close Agent Catalog drawer" }),
    ).toBeInTheDocument();
    fireEvent.click(pin);
    expect(onPinToggle).toHaveBeenCalledTimes(1);
  });

  it("a pinned roster header exposes Unpin", () => {
    render(<AgentCatalogDrawer presented projectId="p1" pinned onPinToggle={jest.fn()} />);
    expect(screen.getByRole("button", { name: "Unpin drawer" })).toHaveAttribute("aria-pressed", "true");
  });

  it("no card offers a per-agent settings cog, in any scope", async () => {
    // There used to be one per In-dataflow card, opening a run/spend policy
    // editor. Curio no longer caps either, so the editor and its three scopes
    // are gone and a card's actions are add, remove, publish.
    api.listProjectAgents = jest.fn().mockResolvedValue({
      agents: [card("agent.chat-agent", { scope: "installed", installedInProject: true })],
    } as any);
    render(<AgentCatalogDrawer presented projectId="p1" pinned={false} onPinToggle={jest.fn()} />);
    await waitFor(() => expect(screen.getByText("node-explainer")).toBeInTheDocument());
    for (const tab of ["My imports", "In dataflow"]) {
      fireEvent.click(screen.getByText(tab));
      await waitFor(() => expect(screen.getByText("chat-agent")).toBeInTheDocument());
      // Scoped to the card: the drawer header keeps its own AI Settings
      // button, which is the provider, not a per-agent policy.
      const row = screen.getByText("chat-agent").closest("article")!;
      expect(
        within(row).queryByRole("button", { name: /settings/i }),
      ).not.toBeInTheDocument();
    }
  });

  it("the header cog opens AI Settings, which owns the account scope", async () => {
    // The account policy moved into AI Settings, on its "Agent limits" tab,
    // beside the provider those limits apply to. The drawer opens that one
    // surface instead of a second modal holding half the answer. AI Settings
    // is loaded lazily here (a static import would pull UserProvider, the
    // package registry and vega into every canvas), so the assertion waits.
    render(<AgentCatalogDrawer presented projectId="p1" pinned={false} onPinToggle={jest.fn()} />);
    await waitFor(() => expect(screen.getByText("node-explainer")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /ai settings/i }));
    await waitFor(() =>
      expect(screen.getByTestId("ai-settings-modal")).toBeInTheDocument(),
    );
  });

  it("the footer Import agent button opens the upload modal", async () => {
    render(<AgentCatalogDrawer presented projectId="p1" pinned={false} onPinToggle={jest.fn()} />);
    await waitFor(() => expect(screen.getByText("node-explainer")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Import agent" }));
    await waitFor(() =>
      expect(screen.getByRole("dialog", { name: "Import agent package" })).toBeInTheDocument(),
    );
  });
});

describe("AgentCatalogDrawer tab transitions + state sync (memo dev/47)", () => {
  it("a previously visited tab renders its cache instantly — no Loading reset", async () => {
    render(<AgentCatalogDrawer presented projectId="p1" pinned={false} onPinToggle={jest.fn()} />);
    await waitFor(() => expect(screen.getByText("node-explainer")).toBeInTheDocument());
    fireEvent.click(screen.getByText("My imports"));
    await waitFor(() => expect(screen.getByText("chat-agent")).toBeInTheDocument());
    fireEvent.click(screen.getByText("Browse all"));
    // Cached rows are visible immediately; no Loading… flash, no blanking.
    expect(screen.getByText("node-explainer")).toBeInTheDocument();
    expect(screen.queryByText("Loading…")).toBeNull();
  });

  it("an imported AND installed agent shows Remove from dataflow on My imports", async () => {
    api.listImports.mockResolvedValue({
      agents: [
        card("agent.node-content-builder", {
          scope: "imports",
          imported: true,
          installedInProject: true,
        }),
      ],
    } as any);
    render(<AgentCatalogDrawer presented projectId="p1" pinned={false} onPinToggle={jest.fn()} />);
    await waitFor(() => expect(screen.getByText("node-explainer")).toBeInTheDocument());
    fireEvent.click(screen.getByText("My imports"));
    await waitFor(() => expect(screen.getByText("node-content-builder")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Remove from dataflow" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add to dataflow" })).toBeNull();
  });

  it("My imports is fetched with the open project's id (lockfile truth)", async () => {
    render(<AgentCatalogDrawer presented projectId="p1" pinned={false} onPinToggle={jest.fn()} />);
    fireEvent.click(screen.getByText("My imports"));
    await waitFor(() => expect(api.listImports).toHaveBeenCalledWith("p1"));
  });

  it("a lifecycle action refreshes every scope so all tabs agree", async () => {
    render(<AgentCatalogDrawer presented projectId="p1" pinned={false} onPinToggle={jest.fn()} />);
    await waitFor(() => expect(screen.getByText("node-explainer")).toBeInTheDocument());
    api.catalog.mockClear();
    api.listImports.mockClear();
    api.listProjectAgents.mockClear();
    fireEvent.click(screen.getByRole("button", { name: "Add to dataflow" }));
    await waitFor(() => expect(api.installToProject).toHaveBeenCalledWith("p1", "agent.node-explainer@1.0.0"));
    await waitFor(() => {
      expect(api.catalog).toHaveBeenCalled();
      expect(api.listImports).toHaveBeenCalled();
      expect(api.listProjectAgents).toHaveBeenCalled();
    });
  });

  it("a refresh error keeps the cached rows (banner over content)", async () => {
    render(<AgentCatalogDrawer presented projectId="p1" pinned={false} onPinToggle={jest.fn()} />);
    await waitFor(() => expect(screen.getByText("node-explainer")).toBeInTheDocument());
    api.listImports.mockRejectedValue(new Error("network down"));
    fireEvent.click(screen.getByText("My imports"));
    // First visit fails → error banner; switch back: Global cache intact.
    await waitFor(() => expect(screen.getByText("network down")).toBeInTheDocument());
    fireEvent.click(screen.getByText("Browse all"));
    expect(screen.getByText("node-explainer")).toBeInTheDocument();
  });

  it("search filters the visible rows and clearing restores them (dev/68)", async () => {
    api.catalog.mockResolvedValue({
      agents: [card("agent.node-explainer"), card("agent.dataset-finder", { category: "data" })],
    } as any);
    render(<AgentCatalogDrawer presented projectId="p1" pinned={false} onPinToggle={jest.fn()} />);
    await waitFor(() => expect(screen.getByText("node-explainer")).toBeInTheDocument());
    const input = screen.getByPlaceholderText("Search agents, publishers, tags…");
    fireEvent.change(input, { target: { value: "explainer" } });
    expect(screen.getByText("node-explainer")).toBeInTheDocument();
    expect(screen.queryByText("dataset-finder")).toBeNull();
    fireEvent.change(input, { target: { value: "" } });
    expect(screen.getByText("dataset-finder")).toBeInTheDocument();
  });

  it("a no-match query shows the search-specific empty message (dev/68)", async () => {
    render(<AgentCatalogDrawer presented projectId="p1" pinned={false} onPinToggle={jest.fn()} />);
    await waitFor(() => expect(screen.getByText("node-explainer")).toBeInTheDocument());
    fireEvent.change(screen.getByPlaceholderText("Search agents, publishers, tags…"), {
      target: { value: "zzz-no-such-agent" },
    });
    expect(
      screen.getByText("No agents match the current filters."),
    ).toBeInTheDocument();
  });

  it('"Sort: Name" reorders rows alphabetically; "Sort: New" keeps roster order (dev/68)', async () => {
    api.catalog.mockResolvedValue({
      agents: [card("agent.zeta-agent"), card("agent.alpha-agent")],
    } as any);
    render(<AgentCatalogDrawer presented projectId="p1" pinned={false} onPinToggle={jest.fn()} />);
    await waitFor(() => expect(screen.getByText("zeta-agent")).toBeInTheDocument());
    const names = () =>
      screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent);
    // Default "new" = the server roster order.
    expect(names()).toEqual(["zeta-agent", "alpha-agent"]);
    fireEvent.change(screen.getByRole("combobox", { name: "Sort agents" }), {
      target: { value: "name" },
    });
    expect(names()).toEqual(["alpha-agent", "zeta-agent"]);
  });

  it("the search query persists across scope tab switches (dev/68)", async () => {
    render(<AgentCatalogDrawer presented projectId="p1" pinned={false} onPinToggle={jest.fn()} />);
    await waitFor(() => expect(screen.getByText("node-explainer")).toBeInTheDocument());
    const input = screen.getByPlaceholderText("Search agents, publishers, tags…");
    fireEvent.change(input, { target: { value: "chat" } });
    fireEvent.click(screen.getByText("My imports"));
    await waitFor(() => expect(screen.getByText("chat-agent")).toBeInTheDocument());
    expect(input).toHaveValue("chat");
  });

  it("each row leads with a per-category avatar, tint and glyph (dev/68)", async () => {
    api.catalog.mockResolvedValue({
      agents: [card("agent.node-explainer"), card("agent.dataset-finder", { category: "data" })],
    } as any);
    const { container } = render(
      <AgentCatalogDrawer presented projectId="p1" pinned={false} onPinToggle={jest.fn()} />,
    );
    await waitFor(() => expect(screen.getByText("node-explainer")).toBeInTheDocument());
    const avatars = container.querySelectorAll(".cardAvatar");
    expect(avatars).toHaveLength(2);
    // Each category keeps its own key. These two used to be `avatar_package`
    // and `avatar_data`, because `node` folded onto the package neutral - the
    // collapse that left three quarters of the roster the same grey.
    expect(avatars[0].className).toContain("avatar_node");
    expect(avatars[1].className).toContain("avatar_data");
    // And the glyph differs too, which the tint alone never achieved: every
    // card drew the same robot.
    const glyphs = [...avatars].map(
      (el) => el.querySelector("svg")?.getAttribute("data-icon"),
    );
    expect(glyphs).toEqual(["circle-nodes", "database"]);
    // Decorative - hidden from the accessibility tree.
    avatars.forEach((el) => expect(el).toHaveAttribute("aria-hidden"));
  });

  it("out-of-order responses are dropped (race guard)", async () => {
    let resolveSlow: (v: unknown) => void = () => undefined;
    const slow = new Promise((r) => {
      resolveSlow = r;
    });
    // First Global fetch hangs; the revisit's fetch resolves fresh data first.
    api.catalog
      .mockImplementationOnce(() => slow as any)
      .mockResolvedValue({ agents: [card("agent.fresh-agent")] } as any);
    render(<AgentCatalogDrawer presented projectId="p1" pinned={false} onPinToggle={jest.fn()} />);
    fireEvent.click(screen.getByText("My imports"));
    await waitFor(() => expect(screen.getByText("chat-agent")).toBeInTheDocument());
    fireEvent.click(screen.getByText("Browse all"));
    await waitFor(() => expect(screen.getByText("fresh-agent")).toBeInTheDocument());
    // The slow FIRST response lands late: it must be dropped, not repainted.
    await act(async () => {
      resolveSlow({ agents: [card("agent.stale-agent")] });
    });
    expect(screen.queryByText("stale-agent")).toBeNull();
    expect(screen.getByText("fresh-agent")).toBeInTheDocument();
  });
});
