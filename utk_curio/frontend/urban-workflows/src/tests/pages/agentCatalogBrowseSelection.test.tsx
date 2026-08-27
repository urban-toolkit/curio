import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { renderHook, act } from "@testing-library/react";

/**
 * Closing the /catalog/agents detail drawer has to keep it closed.
 *
 * The selection was a plain `string | null`, and an effect re-selected
 * `filtered[0]` whenever it was nullish. Close sets it to `null`, so the effect
 * could not tell "user dismissed this" from "page just loaded" and reopened the
 * drawer immediately, often on a different agent than the one being read. The
 * two peer catalogs (useNodeCatalogBrowse, DataCatalogBrowse) carry a third
 * state for exactly this reason; the agent page had dropped it.
 */

const CARDS = [
  {
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
    provenance: { publisher: "curio", trust: "built-in" },
  },
  {
    dirName: "agent.debug-agent",
    id: "agent.debug-agent",
    name: "Debug",
    purpose: "Diagnose errors",
    category: "node",
    capabilities: [],
    hooks: ["node"],
    tags: [],
    imported: false,
    published: false,
    provenance: { publisher: "curio", trust: "built-in" },
  },
];

jest.mock("../../api/agentsApi", () => ({
  agentsApi: {
    catalog: jest.fn(() => Promise.resolve({ items: CARDS, agents: CARDS, facets: null })),
    listImports: jest.fn(() => Promise.resolve({ agents: [] })),
  },
}));

jest.mock("../../providers/ToastProvider", () => ({
  useToastContext: () => ({ showToast: jest.fn() }),
}));

import { useAgentCatalogBrowse } from "../../pages/agents/useAgentCatalogBrowse";

describe("/catalog/agents selection", () => {
  it("shows the first agent on arrival", async () => {
    const { result } = renderHook(() => useAgentCatalogBrowse());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.selectedAgent?.dirName).toBe("agent.chat-agent");
  });

  it("keeps the drawer closed after Close, and does not jump to another agent", async () => {
    const { result } = renderHook(() => useAgentCatalogBrowse());
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => result.current.setSelectedCoord("agent.debug-agent"));
    expect(result.current.selectedAgent?.dirName).toBe("agent.debug-agent");

    // What the drawer's Close button does.
    act(() => result.current.setSelectedCoord(null));

    expect(result.current.selectedAgent).toBeNull();
    // The regression: the effect used to fire here and reopen on filtered[0].
    await new Promise((r) => setTimeout(r, 0));
    expect(result.current.selectedAgent).toBeNull();
  });

  it("reopens on the first row when the user picks again after closing", async () => {
    const { result } = renderHook(() => useAgentCatalogBrowse());
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => result.current.setSelectedCoord(null));
    expect(result.current.selectedAgent).toBeNull();

    act(() => result.current.setSelectedCoord("agent.debug-agent"));
    expect(result.current.selectedAgent?.dirName).toBe("agent.debug-agent");
  });

  it("falls back to the default when the selected agent is filtered out", async () => {
    const { result } = renderHook(() => useAgentCatalogBrowse());
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => result.current.setSelectedCoord("agent.debug-agent"));
    act(() => result.current.setSearch("Chat"));

    await waitFor(() =>
      expect(result.current.selectedAgent?.dirName).toBe("agent.chat-agent"),
    );
  });
});
