import React from "react";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";

const mockOpenDrawer = jest.fn();

jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({ projectId: "p1" }),
}));
jest.mock("../../providers/AgentsCatalogDrawerProvider", () => ({
  useAgentsCatalogDrawerControls: () => ({ openAgentsCatalogDrawer: mockOpenDrawer }),
}));
jest.mock("../../api/agentsApi", () => ({
  agentsApi: { listProjectAgents: jest.fn() },
}));

import { agentsApi } from "../../api/agentsApi";
import { AgentsPaletteDropdown } from "../../components/menus/nodes/agentsPalette/AgentsPaletteDropdown";
import {
  AGENTS_PALETTE_REFRESH_EVENT,
  AGENT_DRAG_MIME,
} from "../../utils/agentsPaletteEvents";

const api = agentsApi as jest.Mocked<typeof agentsApi>;

function card(id: string) {
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
    imported: true,
    installedInProject: true,
    published: false,
    publishable: true,
    scope: "installed" as const,
  };
}

beforeEach(() => {
  jest.clearAllMocks();
  api.listProjectAgents.mockResolvedValue({ agents: [card("agent.node-explainer")] });
});

describe("AgentsPaletteDropdown", () => {
  it("shows the installed count and lists agents when opened", async () => {
    render(<AgentsPaletteDropdown />);
    await waitFor(() => expect(api.listProjectAgents).toHaveBeenCalledWith("p1"));
    fireEvent.click(screen.getByRole("button", { name: /AGENTS/ }));
    expect(await screen.findByText("node-explainer")).toBeInTheDocument();
  });

  it("footer opens the catalog drawer", async () => {
    render(<AgentsPaletteDropdown />);
    await waitFor(() => expect(api.listProjectAgents).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("button", { name: /AGENTS/ }));
    fireEvent.click(screen.getByRole("button", { name: /Get more agents/ }));
    expect(mockOpenDrawer).toHaveBeenCalled();
  });

  it("clicking a row opens the drawer", async () => {
    render(<AgentsPaletteDropdown />);
    await waitFor(() => expect(api.listProjectAgents).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("button", { name: /AGENTS/ }));
    fireEvent.click(await screen.findByText("node-explainer"));
    expect(mockOpenDrawer).toHaveBeenCalled();
  });

  it("empty state opens the drawer", async () => {
    api.listProjectAgents.mockResolvedValue({ agents: [] });
    render(<AgentsPaletteDropdown />);
    await waitFor(() => expect(api.listProjectAgents).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("button", { name: /AGENTS/ }));
    fireEvent.click(screen.getByRole("button", { name: /browse the catalog/i }));
    expect(mockOpenDrawer).toHaveBeenCalled();
  });

  it("a row is a drag source writing the agent coordinate", async () => {
    render(<AgentsPaletteDropdown />);
    await waitFor(() => expect(api.listProjectAgents).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("button", { name: /AGENTS/ }));
    const row = await screen.findByText("node-explainer");
    const setData = jest.fn();
    fireEvent.dragStart(row.closest("[draggable]") as Element, {
      dataTransfer: { setData, effectAllowed: "" },
    });
    expect(setData).toHaveBeenCalledWith(AGENT_DRAG_MIME, "agent.node-explainer@1.0.0");
  });

  it("refreshes on the palette-refresh event", async () => {
    render(<AgentsPaletteDropdown />);
    await waitFor(() => expect(api.listProjectAgents).toHaveBeenCalledTimes(1));
    api.listProjectAgents.mockClear();
    act(() => {
      window.dispatchEvent(new Event(AGENTS_PALETTE_REFRESH_EVENT));
    });
    await waitFor(() => expect(api.listProjectAgents).toHaveBeenCalledTimes(1));
  });
});
