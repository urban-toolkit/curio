import React from "react";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";

const mockOpenDrawer = jest.fn();

jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({ projectId: "p1" }),
}));
jest.mock("../../providers/AgentsCatalogDrawerProvider", () => ({
  useAgentsCatalogDrawerControls: () => ({
    openAgentsCatalogDrawer: mockOpenDrawer,
    isAgentsCatalogDrawerOpen: false,
  }),
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
    fireEvent.click(screen.getByRole("button", { name: /Agents/i }));
    expect(await screen.findByText("node-explainer")).toBeInTheDocument();
    // Row shows the install coordinate (major only) and a compatible-target pill.
    expect(screen.getByText("agent.node-explainer@1")).toBeInTheDocument();
    expect(screen.getByText("Node")).toBeInTheDocument();
  });

  it("footer opens the catalog drawer", async () => {
    render(<AgentsPaletteDropdown />);
    await waitFor(() => expect(api.listProjectAgents).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("button", { name: /Agents/i }));
    fireEvent.click(screen.getByRole("button", { name: /Browse Agents Catalog/i }));
    expect(mockOpenDrawer).toHaveBeenCalled();
  });

  it("clicking a row opens the drawer", async () => {
    render(<AgentsPaletteDropdown />);
    await waitFor(() => expect(api.listProjectAgents).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("button", { name: /Agents/i }));
    fireEvent.click(await screen.findByText("node-explainer"));
    expect(mockOpenDrawer).toHaveBeenCalled();
  });

  it("empty state shows the hint and the catalog footer opens the drawer", async () => {
    api.listProjectAgents.mockResolvedValue({ agents: [] });
    render(<AgentsPaletteDropdown />);
    await waitFor(() => expect(api.listProjectAgents).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("button", { name: /Agents/i }));
    expect(
      screen.getByText(/No agents installed in this project yet/i),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Browse Agents Catalog/i }));
    expect(mockOpenDrawer).toHaveBeenCalled();
  });

  it("a row is a drag source writing the agent coordinate", async () => {
    render(<AgentsPaletteDropdown />);
    await waitFor(() => expect(api.listProjectAgents).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("button", { name: /Agents/i }));
    await screen.findByText("node-explainer");
    const dragHandle = screen.getByTitle(/Drag onto a node or the canvas to attach/i);
    const setData = jest.fn();
    fireEvent.dragStart(dragHandle, {
      dataTransfer: { setData, effectAllowed: "" },
    });
    expect(setData).toHaveBeenCalledWith(AGENT_DRAG_MIME, "agent.node-explainer@1.0.0");
  });

  // The palette dock is pointer-events: none; the root re-enables events via a
  // `.root > *` selector, so the trigger's column and the open panel must stay
  // DIRECT children of the root. This guards against a refactor that nests them
  // and silently makes the dropdown click-through to the canvas again.
  it("keeps the trigger column and open panel as direct children of the root", async () => {
    render(<AgentsPaletteDropdown />);
    await waitFor(() => expect(api.listProjectAgents).toHaveBeenCalled());
    const trigger = screen.getByRole("button", { name: /Agents/i });
    const column = trigger.parentElement as HTMLElement; // .column
    const root = column.parentElement as HTMLElement;
    expect(root.className).toContain("root");
    expect(column.parentElement).toBe(root);
    fireEvent.click(trigger);
    const panel = await screen.findByRole("region", { name: /Agents palette/i });
    expect(panel.parentElement).toBe(root);
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
