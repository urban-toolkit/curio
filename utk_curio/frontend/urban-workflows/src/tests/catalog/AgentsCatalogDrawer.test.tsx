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
    getProjectAgentDefaults: jest.fn(),
    updateProjectAgentDefaults: jest.fn(),
    getAgentSettings: jest.fn(),
    uploadImport: jest.fn(),
    updateAgentSettings: jest.fn(),
  },
}));

import { agentsApi } from "../../api/agentsApi";
import { AgentsCatalogDrawer } from "../../components/agents/catalog/AgentsCatalogDrawer";

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
    scope: "global",
    ...over,
  };
}

beforeEach(() => {
  jest.clearAllMocks();
  api.catalog.mockResolvedValue({ agents: [card("agent.node-explainer")] } as any);
  api.listImports.mockResolvedValue({ agents: [card("agent.chat-agent", { scope: "my-imports", imported: true })] } as any);
  api.listProjectAgents.mockResolvedValue({ agents: [] } as any);
  api.installToProject.mockResolvedValue({ agents: [] } as any);
  api.uninstallFromProject.mockResolvedValue({ agents: [] } as any);
  api.publish.mockResolvedValue({ coord: "x", published: true } as any);
  const effective = {
    quotas: { runsPerDay: { value: 200, usedToday: 0, source: "deployment" } },
    cost: {
      dailyBudgetUsd: { value: null, source: null },
      estimatedCostPerRunUsd: { value: null, source: null },
      configured: false,
      estimatedSpendTodayUsd: null,
    },
    resources: { maxOutputTokens: { value: 4096, source: "deployment" } },
  };
  api.getProjectAgentDefaults.mockResolvedValue({
    coord: "agent.chat-agent@1.0.0",
    name: "Chat",
    revision: 1,
    settings: {},
    effective,
  } as any);
  api.getAgentSettings.mockResolvedValue({
    revision: 1,
    settings: {},
    effective,
    ceilings: { quotas: { runsPerDay: 200 }, resources: { maxOutputTokens: 4096 }, cost: {} },
    usedToday: 0,
  } as any);
});

describe("AgentsCatalogDrawer", () => {
  it("is hidden (not accessible) when not presented", () => {
    // dev/43: the drawer stays mounted through the exit slide; while not
    // presented it is aria-hidden and pointer-inert, never abruptly removed.
    const { container } = render(
      <AgentsCatalogDrawer presented={false} projectId="p1" pinned={false} onPinToggle={jest.fn()} />,
    );
    expect(screen.queryByRole("dialog", { name: "Agents Catalog" })).not.toBeInTheDocument();
    const root = container.querySelector("[data-curio-agents-catalog-drawer]");
    expect(root).toHaveAttribute("aria-hidden", "true");
  });

  it("renders the three scopes and the global cards", async () => {
    render(<AgentsCatalogDrawer presented projectId="p1" pinned={false} onPinToggle={jest.fn()} />);
    expect(screen.getByText("Global Catalog")).toBeInTheDocument();
    expect(screen.getByText("My Imports")).toBeInTheDocument();
    expect(screen.getByText("Installed in this project")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("node-explainer")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Install" })).toBeInTheDocument();
  });

  it("switching to My Imports fetches and shows Delete", async () => {
    render(<AgentsCatalogDrawer presented projectId="p1" pinned={false} onPinToggle={jest.fn()} />);
    await waitFor(() => expect(screen.getByText("node-explainer")).toBeInTheDocument());
    fireEvent.click(screen.getByText("My Imports"));
    await waitFor(() => expect(api.listImports).toHaveBeenCalled());
    await waitFor(() => expect(screen.getByText("chat-agent")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Delete" })).toBeInTheDocument();
  });

  it("Install disabled without a project", async () => {
    render(<AgentsCatalogDrawer presented projectId={null} pinned={false} onPinToggle={jest.fn()} />);
    await waitFor(() => expect(screen.getByText("node-explainer")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Install" })).toBeDisabled();
  });

  it("shows Publish only for a publishable My Imports card and publishes on click", async () => {
    api.listImports.mockResolvedValue({
      agents: [
        card("agent.my-custom", { scope: "my-imports", imported: true, publishable: true }),
        card("agent.node-explainer", { scope: "my-imports", imported: true, publishable: false }),
      ],
    } as any);
    render(<AgentsCatalogDrawer presented projectId="p1" pinned={false} onPinToggle={jest.fn()} />);
    fireEvent.click(screen.getByText("My Imports"));
    await waitFor(() => expect(screen.getByText("my-custom")).toBeInTheDocument());
    // Exactly one Publish control — the built-in card (publishable:false) shows none.
    const publishBtns = screen.getAllByRole("button", { name: /publish/i });
    expect(publishBtns).toHaveLength(1);
    fireEvent.click(publishBtns[0]);
    await waitFor(() => expect(api.publish).toHaveBeenCalledWith("agent.my-custom@1.0.0"));
  });

  it("clicking Install calls the install endpoint", async () => {
    render(<AgentsCatalogDrawer presented projectId="p1" pinned={false} onPinToggle={jest.fn()} />);
    await waitFor(() => expect(screen.getByText("node-explainer")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Install" }));
    await waitFor(() =>
      expect(api.installToProject).toHaveBeenCalledWith("p1", "agent.node-explainer@1.0.0"),
    );
  });

  it("roster header shows the Pin only (DEC-042): no Close button", async () => {
    const onPinToggle = jest.fn();
    render(<AgentsCatalogDrawer presented projectId="p1" pinned={false} onPinToggle={onPinToggle} />);
    const pin = screen.getByRole("button", { name: "Pin drawer open" });
    expect(pin).toHaveAttribute("aria-pressed", "false");
    // DEC-042: no Close button inside the drawer (the scrim outside the
    // dialog carries the dismissal, like the other catalog drawers).
    const dialog = screen.getByRole("dialog", { name: "Agents Catalog" });
    expect(within(dialog).queryByRole("button", { name: /close/i })).not.toBeInTheDocument();
    fireEvent.click(pin);
    expect(onPinToggle).toHaveBeenCalledTimes(1);
  });

  it("a pinned roster header exposes Unpin", () => {
    render(<AgentsCatalogDrawer presented projectId="p1" pinned onPinToggle={jest.fn()} />);
    expect(screen.getByRole("button", { name: "Unpin drawer" })).toHaveAttribute("aria-pressed", "true");
  });

  it("installed scope shows the labeled Project agent settings cog (dev/23)", async () => {
    api.listProjectAgents = jest.fn().mockResolvedValue({
      agents: [card("agent.chat-agent", { scope: "installed", installedInProject: true })],
    } as any);
    render(<AgentsCatalogDrawer presented projectId="p1" pinned={false} onPinToggle={jest.fn()} />);
    fireEvent.click(screen.getByText("Installed in this project"));
    await waitFor(() => expect(screen.getByText("chat-agent")).toBeInTheDocument());
    const cog = screen.getByRole("button", { name: /project agent settings/i });
    expect(cog).toBeEnabled();
    fireEvent.click(cog);
    await waitFor(() =>
      expect(screen.getByText("Project agent default")).toBeInTheDocument(),
    );
  });

  it("global and My Imports scopes show no settings cog", async () => {
    render(<AgentsCatalogDrawer presented projectId="p1" pinned={false} onPinToggle={jest.fn()} />);
    await waitFor(() => expect(screen.getByText("node-explainer")).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: /project agent settings/i })).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("My Imports"));
    await waitFor(() => expect(screen.getByText("chat-agent")).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: /project agent settings/i })).not.toBeInTheDocument();
  });

  it("the roster header's Agent settings cog opens the account scope (dev/24)", async () => {
    render(<AgentsCatalogDrawer presented projectId="p1" pinned={false} onPinToggle={jest.fn()} />);
    await waitFor(() => expect(screen.getByText("node-explainer")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /agent settings/i }));
    await waitFor(() => expect(screen.getByText("Account policy")).toBeInTheDocument());
  });

  it("the footer Import package button opens the upload modal (dev/36)", async () => {
    render(<AgentsCatalogDrawer presented projectId="p1" pinned={false} onPinToggle={jest.fn()} />);
    await waitFor(() => expect(screen.getByText("node-explainer")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Import package" }));
    await waitFor(() =>
      expect(screen.getByRole("dialog", { name: "Import agent package" })).toBeInTheDocument(),
    );
  });
});

describe("AgentsCatalogDrawer tab transitions + state sync (memo dev/47)", () => {
  it("a previously visited tab renders its cache instantly — no Loading reset", async () => {
    render(<AgentsCatalogDrawer presented projectId="p1" pinned={false} onPinToggle={jest.fn()} />);
    await waitFor(() => expect(screen.getByText("node-explainer")).toBeInTheDocument());
    fireEvent.click(screen.getByText("My Imports"));
    await waitFor(() => expect(screen.getByText("chat-agent")).toBeInTheDocument());
    fireEvent.click(screen.getByText("Global Catalog"));
    // Cached rows are visible immediately; no Loading… flash, no blanking.
    expect(screen.getByText("node-explainer")).toBeInTheDocument();
    expect(screen.queryByText("Loading…")).toBeNull();
  });

  it("an imported AND installed agent shows Uninstall on My Imports (Node Content Builder regression)", async () => {
    api.listImports.mockResolvedValue({
      agents: [
        card("agent.node-content-builder", {
          scope: "my-imports",
          imported: true,
          installedInProject: true,
        }),
      ],
    } as any);
    render(<AgentsCatalogDrawer presented projectId="p1" pinned={false} onPinToggle={jest.fn()} />);
    await waitFor(() => expect(screen.getByText("node-explainer")).toBeInTheDocument());
    fireEvent.click(screen.getByText("My Imports"));
    await waitFor(() => expect(screen.getByText("node-content-builder")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Uninstall" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Install" })).toBeNull();
  });

  it("My Imports is fetched with the open project's id (lockfile truth)", async () => {
    render(<AgentsCatalogDrawer presented projectId="p1" pinned={false} onPinToggle={jest.fn()} />);
    fireEvent.click(screen.getByText("My Imports"));
    await waitFor(() => expect(api.listImports).toHaveBeenCalledWith("p1"));
  });

  it("a lifecycle action refreshes every scope so all tabs agree", async () => {
    render(<AgentsCatalogDrawer presented projectId="p1" pinned={false} onPinToggle={jest.fn()} />);
    await waitFor(() => expect(screen.getByText("node-explainer")).toBeInTheDocument());
    api.catalog.mockClear();
    api.listImports.mockClear();
    api.listProjectAgents.mockClear();
    fireEvent.click(screen.getByRole("button", { name: "Install" }));
    await waitFor(() => expect(api.installToProject).toHaveBeenCalledWith("p1", "agent.node-explainer@1.0.0"));
    await waitFor(() => {
      expect(api.catalog).toHaveBeenCalled();
      expect(api.listImports).toHaveBeenCalled();
      expect(api.listProjectAgents).toHaveBeenCalled();
    });
  });

  it("a refresh error keeps the cached rows (banner over content)", async () => {
    render(<AgentsCatalogDrawer presented projectId="p1" pinned={false} onPinToggle={jest.fn()} />);
    await waitFor(() => expect(screen.getByText("node-explainer")).toBeInTheDocument());
    api.listImports.mockRejectedValue(new Error("network down"));
    fireEvent.click(screen.getByText("My Imports"));
    // First visit fails → error banner; switch back: Global cache intact.
    await waitFor(() => expect(screen.getByText("network down")).toBeInTheDocument());
    fireEvent.click(screen.getByText("Global Catalog"));
    expect(screen.getByText("node-explainer")).toBeInTheDocument();
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
    render(<AgentsCatalogDrawer presented projectId="p1" pinned={false} onPinToggle={jest.fn()} />);
    fireEvent.click(screen.getByText("My Imports"));
    await waitFor(() => expect(screen.getByText("chat-agent")).toBeInTheDocument());
    fireEvent.click(screen.getByText("Global Catalog"));
    await waitFor(() => expect(screen.getByText("fresh-agent")).toBeInTheDocument());
    // The slow FIRST response lands late: it must be dropped, not repainted.
    await act(async () => {
      resolveSlow({ agents: [card("agent.stale-agent")] });
    });
    expect(screen.queryByText("stale-agent")).toBeNull();
    expect(screen.getByText("fresh-agent")).toBeInTheDocument();
  });
});
