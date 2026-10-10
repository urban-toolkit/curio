import React from "react";
import { act, render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";

/**
 * `--no-allow-publish` hides Publish on /catalog/agents (#861).
 *
 * The node and data catalogs read the switch from
 * `packagesApi.factoryCapabilities()` and hide Publish and Unpublish when it is
 * off. The agent page passed `catalogPublishAllowed` as a constant true, so an
 * agent of your own offered Publish on a server that refuses it.
 */

/** The account's own imported agent: the one card that can be published. */
const mockMine = {
  dirName: "me.my-agent",
  id: "me.my-agent",
  name: "My Agent",
  purpose: "Something I wrote",
  category: "canvas",
  version: "1.0.0",
  capabilities: [],
  hooks: ["canvas"],
  tags: [],
  requiresAgents: [],
  imported: true,
  published: false,
  publishable: true,
  provenance: { publisher: "me", trust: "imported" },
};

jest.mock("../../services/agents/agentsApi", () => ({
  agentsApi: {
    catalog: jest.fn(() => Promise.resolve({ items: [], agents: [], facets: null })),
    listImports: jest.fn(() => Promise.resolve({ agents: [mockMine] })),
  },
}));

const mockCapabilities = jest.fn();
jest.mock("../../services/packages/packagesApi", () => ({
  packagesApi: { factoryCapabilities: () => mockCapabilities() },
}));

jest.mock("../../providers/ToastProvider", () => ({
  useToastContext: () => ({ showToast: jest.fn() }),
}));

import { AgentCatalogBrowse } from "../../pages/agents/AgentCatalogBrowse";

async function renderWithPublishing(catalogPublish: boolean) {
  mockCapabilities.mockResolvedValue({ catalogPublish });
  render(<AgentCatalogBrowse />);
  // The drawer opens on the first card, the account's own agent.
  await screen.findAllByText("My Agent");
}

beforeEach(() => {
  mockCapabilities.mockReset();
});

describe("/catalog/agents follows the publish switch (#861)", () => {
  it("offers no Publish when the server forbids publishing", async () => {
    await renderWithPublishing(false);
    await act(async () => {});
    expect(screen.queryByRole("button", { name: "Publish" })).not.toBeInTheDocument();
    // Hidden because the server said so, not because nothing asked it.
    await waitFor(() => expect(mockCapabilities).toHaveBeenCalled());
  });

  it("offers Publish when the server allows it", async () => {
    await renderWithPublishing(true);
    expect(await screen.findByRole("button", { name: "Publish" })).toBeInTheDocument();
  });
});
