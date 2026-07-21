import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

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
  api.installToProject.mockResolvedValue({ agents: [] } as any);
  api.publish.mockResolvedValue({ coord: "x", published: true } as any);
});

describe("AgentsCatalogDrawer", () => {
  it("renders nothing when not presented", () => {
    const { container } = render(
      <AgentsCatalogDrawer presented={false} projectId="p1" pinned={false} onPinToggle={jest.fn()} />,
    );
    expect(container).toBeEmptyDOMElement();
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
    expect(screen.queryByRole("button", { name: /close/i })).not.toBeInTheDocument();
    fireEvent.click(pin);
    expect(onPinToggle).toHaveBeenCalledTimes(1);
  });

  it("a pinned roster header exposes Unpin", () => {
    render(<AgentsCatalogDrawer presented projectId="p1" pinned onPinToggle={jest.fn()} />);
    expect(screen.getByRole("button", { name: "Unpin drawer" })).toHaveAttribute("aria-pressed", "true");
  });
});
