import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

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
  AgentsCatalogDrawerProvider,
  useAgentsCatalogDrawerControls,
} from "../../providers/AgentsCatalogDrawerProvider";

const Consumer: React.FC = () => {
  const { openAgentsCatalogDrawer, isAgentsCatalogDrawerOpen } = useAgentsCatalogDrawerControls();
  return (
    <button onClick={openAgentsCatalogDrawer}>
      {isAgentsCatalogDrawerOpen ? "open" : "closed"} — toggle
    </button>
  );
};

function renderProvider() {
  return render(
    <AgentsCatalogDrawerProvider>
      <Consumer />
    </AgentsCatalogDrawerProvider>,
  );
}

describe("AgentsCatalogDrawerProvider", () => {
  it("does not render the drawer until opened", () => {
    renderProvider();
    expect(screen.queryByRole("dialog", { name: "Agents Catalog" })).not.toBeInTheDocument();
  });

  it("opens the drawer on demand", async () => {
    renderProvider();
    fireEvent.click(screen.getByText(/toggle/));
    await waitFor(() =>
      expect(screen.getByRole("dialog", { name: "Agents Catalog" })).toBeInTheDocument(),
    );
  });

  it("has no Close button (DEC-042); the backdrop dismisses when unpinned", async () => {
    renderProvider();
    fireEvent.click(screen.getByText(/toggle/));
    await waitFor(() => screen.getByRole("dialog", { name: "Agents Catalog" }));
    expect(screen.queryByRole("button", { name: /close/i })).not.toBeInTheDocument();
    fireEvent.click(document.querySelector('[class*="backdrop"]') as Element);
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "Agents Catalog" })).not.toBeInTheDocument(),
    );
  });

  it("closes on Escape when unpinned", async () => {
    renderProvider();
    fireEvent.click(screen.getByText(/toggle/));
    await waitFor(() => screen.getByRole("dialog", { name: "Agents Catalog" }));
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "Agents Catalog" })).not.toBeInTheDocument(),
    );
  });

  it("pinned blocks the backdrop and Escape dismissals", async () => {
    renderProvider();
    fireEvent.click(screen.getByText(/toggle/));
    await waitFor(() => screen.getByRole("dialog", { name: "Agents Catalog" }));
    fireEvent.click(screen.getByRole("button", { name: "Pin drawer open" }));
    fireEvent.click(document.querySelector('[class*="backdrop"]') as Element);
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.getByRole("dialog", { name: "Agents Catalog" })).toBeInTheDocument();
    // Unpin → dismissal works again.
    fireEvent.click(screen.getByRole("button", { name: "Unpin drawer" }));
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "Agents Catalog" })).not.toBeInTheDocument(),
    );
  });

  it("throws if the controls hook is used outside the provider", () => {
    const spy = jest.spyOn(console, "error").mockImplementation(() => undefined);
    expect(() => render(<Consumer />)).toThrow(/must be used within/);
    spy.mockRestore();
  });
});
