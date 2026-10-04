import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

/**
 * An agent's details name the configuration it runs on, read-only: the choice
 * is made in API Settings, which the link opens on that agent's row.
 */

jest.mock("../../services/agents/agentsApi", () => ({
  agentsApi: { readDefinition: jest.fn(() => Promise.resolve({ manifest: {}, prompts: {} })) },
}));

let mockListing: Record<string, unknown> = {};
jest.mock("../../api/llmConfigsApi", () => ({
  llmConfigsApi: { listing: jest.fn(() => Promise.resolve(mockListing)) },
}));

import { AgentDetailModal } from "../../components/agents/catalog/AgentDetailModal";
import {
  API_SETTINGS_EVENT,
  type ApiSettingsFocus,
} from "../../components/apiSettings/apiSettingsRequest";

const AGENT = {
  id: "agent.node-content-builder", version: "1.0.0", dirName: "agent.node-content-builder@1.0.0",
  name: "Node Content Builder", category: "node", purpose: "Writes node content.",
  capabilities: ["node.content.generate"], hooks: ["node"],
  provenance: { publisher: "curio", trust: "built-in" }, imported: false,
  installedInProject: false, published: false, publishable: false, scope: "browse",
  requiresAgents: [], inCatalog: true,
} as never;

const listingWith = (editable: boolean) => ({
  editable,
  active: { source: "default", label: "Work", model: "gpt-4o-mini" },
  agents: [{
    id: "agent.node-content-builder", name: "Node Content Builder", category: "node",
    choice: "llm-00000000000b",
    answers: { source: "assigned", label: "Local", model: "llama3" },
  }],
});

it("names what the agent runs on and opens API Settings on its row", async () => {
  mockListing = listingWith(true);
  const onClose = jest.fn();
  const asked: ApiSettingsFocus[] = [];
  const listener = (event: Event) => asked.push((event as CustomEvent<ApiSettingsFocus>).detail);
  window.addEventListener(API_SETTINGS_EVENT, listener);
  render(<AgentDetailModal agent={AGENT} onClose={onClose} />);
  expect(await screen.findByText("Local · llama3")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Change in API Settings" }));
  await waitFor(() => expect(asked).toEqual([{ section: "agent-models", agentId: "agent.node-content-builder" }]));
  expect(onClose).toHaveBeenCalled();
  window.removeEventListener(API_SETTINGS_EVENT, listener);
});

it("offers no change when this account cannot choose one", async () => {
  mockListing = listingWith(false);
  render(<AgentDetailModal agent={AGENT} onClose={jest.fn()} />);
  expect(await screen.findByText("Local · llama3")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Change in API Settings" })).toBeNull();
});
