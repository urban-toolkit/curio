import React from "react";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";

jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({ projectId: "p1" }),
}));

jest.mock("../../api/agentsApi", () => ({
  agentsApi: {
    catalog: jest.fn(() => Promise.resolve({ agents: [] })),
    listImports: jest.fn(() => Promise.resolve({ agents: [] })),
    listProjectAgents: jest.fn(() => Promise.resolve({ agents: [] })),
    import: jest.fn(),
    removeImport: jest.fn(),
    installToProject: jest.fn(),
    uninstallFromProject: jest.fn(),
  },
}));

import {
  AgentCatalogDrawerProvider,
  useAgentCatalogDrawerControls,
} from "../../providers/AgentCatalogDrawerProvider";

const Consumer: React.FC = () => {
  const { openAgentCatalogDrawer, isAgentCatalogDrawerOpen } = useAgentCatalogDrawerControls();
  return (
    <button onClick={openAgentCatalogDrawer}>
      {isAgentCatalogDrawerOpen ? "open" : "closed"} — toggle
    </button>
  );
};

function renderProvider() {
  return render(
    <AgentCatalogDrawerProvider>
      <Consumer />
    </AgentCatalogDrawerProvider>,
  );
}

describe("AgentCatalogDrawerProvider", () => {
  it("does not render the drawer until opened", () => {
    renderProvider();
    expect(screen.queryByRole("dialog", { name: "Agent Catalog" })).not.toBeInTheDocument();
  });

  it("opens the drawer on demand", async () => {
    renderProvider();
    fireEvent.click(screen.getByText(/toggle/));
    await waitFor(() =>
      expect(screen.getByRole("dialog", { name: "Agent Catalog" })).toBeInTheDocument(),
    );
  });

  it("has a Close button, and the scrim also dismisses when unpinned", async () => {
    renderProvider();
    fireEvent.click(screen.getByText(/toggle/));
    await waitFor(() => screen.getByRole("dialog", { name: "Agent Catalog" }));
    const dialog = screen.getByRole("dialog", { name: "Agent Catalog" });
    expect(
      within(dialog).getByRole("button", { name: "Close Agent Catalog drawer" }),
    ).toBeInTheDocument();
    // The scrim's own label is distinct, so this resolves one element rather
    // than two - the ambiguity the Node drawer still carries.
    fireEvent.click(screen.getByRole("button", { name: "Dismiss Agent Catalog" }));
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "Agent Catalog" })).not.toBeInTheDocument(),
    );
  });

  it("stays mounted through the exit slide and unmounts on exit completion", async () => {
    renderProvider();
    fireEvent.click(screen.getByText(/toggle/));
    await waitFor(() => screen.getByRole("dialog", { name: "Agent Catalog" }));
    fireEvent.keyDown(window, { key: "Escape" });
    // Immediately after close: no longer accessible (aria-hidden), but still
    // in the DOM sliding out — no abrupt removal (dev/43).
    expect(screen.queryByRole("dialog", { name: "Agent Catalog" })).not.toBeInTheDocument();
    const root = document.querySelector("[data-curio-agent-catalog-drawer]");
    expect(root).toBeInTheDocument();
    // The panel's transform transitionend settles the close and unmounts.
    const panel = root!.querySelector("aside") as Element;
    fireEvent.transitionEnd(panel, { propertyName: "transform" });
    await waitFor(() =>
      expect(document.querySelector("[data-curio-agent-catalog-drawer]")).toBeNull(),
    );
  });

  it("reopening during the exit slide cancels the pending unmount", async () => {
    renderProvider();
    fireEvent.click(screen.getByText(/toggle/));
    await waitFor(() => screen.getByRole("dialog", { name: "Agent Catalog" }));
    fireEvent.keyDown(window, { key: "Escape" });
    fireEvent.click(screen.getByText(/toggle/)); // reopen mid-exit
    await waitFor(() => screen.getByRole("dialog", { name: "Agent Catalog" }));
    // Well past the exit timer, the drawer is still open.
    await new Promise((r) => setTimeout(r, 450));
    expect(screen.getByRole("dialog", { name: "Agent Catalog" })).toBeInTheDocument();
  });

  it("closes on Escape when unpinned", async () => {
    renderProvider();
    fireEvent.click(screen.getByText(/toggle/));
    await waitFor(() => screen.getByRole("dialog", { name: "Agent Catalog" }));
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "Agent Catalog" })).not.toBeInTheDocument(),
    );
  });

  it("pinned blocks the backdrop and Escape dismissals", async () => {
    renderProvider();
    fireEvent.click(screen.getByText(/toggle/));
    await waitFor(() => screen.getByRole("dialog", { name: "Agent Catalog" }));
    fireEvent.click(screen.getByRole("button", { name: "Pin drawer open" }));
    fireEvent.click(screen.getByRole("button", { name: "Dismiss Agent Catalog" }));
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.getByRole("dialog", { name: "Agent Catalog" })).toBeInTheDocument();
    // Unpin → dismissal works again.
    fireEvent.click(screen.getByRole("button", { name: "Unpin drawer" }));
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "Agent Catalog" })).not.toBeInTheDocument(),
    );
  });

  it("throws if the controls hook is used outside the provider", () => {
    const spy = jest.spyOn(console, "error").mockImplementation(() => undefined);
    expect(() => render(<Consumer />)).toThrow(/must be used within/);
    spy.mockRestore();
  });
});
