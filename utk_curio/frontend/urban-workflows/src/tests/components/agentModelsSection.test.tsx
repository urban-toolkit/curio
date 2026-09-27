import React from "react";
import { render, screen, waitFor, fireEvent, within } from "@testing-library/react";

/**
 * AI Settings → Agent models: the configuration each agent runs on, chosen
 * from the account's configurations, the Deployment default, or Default
 * (follow the default configuration). Saved on change; the configurations
 * table says which agents each one is chosen for, and removing one names the
 * agents that go back to the default.
 */

const WORK = {
  id: "llm-00000000000a", label: "Work", endpoint: "own", apiType: "openai_compatible",
  baseUrl: "https://api.openai.com/v1", baseUrlHost: "api.openai.com", hasApiKey: true,
  model: "gpt-4o-mini", origin: "user", createdAt: 1, updatedAt: 1,
};
const LOCAL = { ...WORK, id: "llm-00000000000b", label: "Local", baseUrl: "http://localhost:11434/v1",
  baseUrlHost: "localhost:11434", hasApiKey: false, model: "llama3" };

const answering = (label: string, model: string, source = "default") => ({
  source, configId: null, label, model, apiType: "openai_compatible", baseUrlHost: "api.openai.com",
});

const listingOf = (overrides: Record<string, unknown> = {}) => ({
  configs: [WORK, LOCAL],
  default: WORK.id,
  assignments: { "agent.node-content-builder": LOCAL.id },
  agents: [
    { id: "agent.chat-agent", name: "Chat", category: "chat", choice: null, answers: answering("Work", "gpt-4o-mini") },
    { id: "agent.dataflow-builder", name: "Dataflow Builder", category: "dataflow", choice: null,
      answers: answering("Work", "gpt-4o-mini") },
    { id: "agent.node-content-builder", name: "Node Content Builder", category: "node", choice: LOCAL.id,
      answers: answering("Local", "llama3", "assigned") },
  ],
  deployment: { label: "Deployment default", endpointOffered: true, apiType: "openai_compatible",
    baseUrlHost: "sage.example.edu", model: "llama4" },
  active: answering("Work", "gpt-4o-mini"),
  editable: true,
  reason: null,
  shared: false,
  maxConfigs: 32,
  ...overrides,
});

let mockListing: Record<string, unknown> = listingOf();
const mockApi = {
  listing: jest.fn(() => Promise.resolve(mockListing)),
  create: jest.fn(),
  update: jest.fn(),
  remove: jest.fn(),
  duplicate: jest.fn(),
  setDefault: jest.fn(),
  setAssignments: jest.fn(),
  models: jest.fn(),
};
// The factory runs before this module's constants exist, so it delegates.
jest.mock("../../api/llmConfigsApi", () => ({
  llmConfigsApi: new Proxy({}, {
    get: (_target, name: string) => (...args: unknown[]) =>
      (mockApi as Record<string, (...a: unknown[]) => unknown>)[name](...args),
  }),
}));

import { LlmConfigsSection } from "../../components/llmConfigs/LlmConfigsSection";

beforeEach(() => {
  mockListing = listingOf();
  jest.clearAllMocks();
  mockApi.listing.mockImplementation(() => Promise.resolve(mockListing));
  mockApi.setAssignments.mockImplementation(() => Promise.resolve(mockListing));
  mockApi.remove.mockResolvedValue({ deleted: LOCAL.id, moved: ["agent.node-content-builder"], default: WORK.id });
});

const models = async () => within(await screen.findByTestId("agent-models-section"));
const select = (name: string) => screen.getByLabelText(name) as HTMLSelectElement;

describe("Agent models", () => {
  it("lists every agent with its choice and what it runs on", async () => {
    render(<LlmConfigsSection />);
    const section = await models();
    expect(section.getAllByRole("combobox")).toHaveLength(3);
    expect(select("Chat").value).toBe("");
    expect(select("Node Content Builder").value).toBe(LOCAL.id);
    expect(section.getByText("Runs on Local · llama3")).toBeInTheDocument();
  });

  it("offers Default, every configuration and the Deployment default", async () => {
    render(<LlmConfigsSection />);
    await models();
    const options = Array.from(select("Chat").options).map((o) => [o.value, o.textContent]);
    expect(options).toEqual([
      ["", "Default (Work)"],
      [WORK.id, "Work · gpt-4o-mini"],
      [LOCAL.id, "Local · llama3"],
      ["deployment", "Deployment default · llama4"],
    ]);
  });

  it("saves a choice on change, and Default clears it", async () => {
    render(<LlmConfigsSection />);
    await models();
    fireEvent.change(select("Chat"), { target: { value: LOCAL.id } });
    await waitFor(() => expect(mockApi.setAssignments).toHaveBeenCalledWith({ "agent.chat-agent": LOCAL.id }));
    await waitFor(() => expect(select("Node Content Builder")).toBeEnabled());
    fireEvent.change(select("Node Content Builder"), { target: { value: "" } });
    await waitFor(() =>
      expect(mockApi.setAssignments).toHaveBeenLastCalledWith({ "agent.node-content-builder": null }),
    );
  });

  it("says what the Dataflow Builder's Solve also runs, and the rules", async () => {
    render(<LlmConfigsSection />);
    const section = await models();
    expect(section.getByText(/Its Solve also runs Node Content Builder and Dataset Finder/)).toBeInTheDocument();
    expect(section.getByText(/on its choice, else on its caller's/)).toBeInTheDocument();
  });

  it("shows why an agent has nothing to run on", async () => {
    mockListing = listingOf({
      agents: [{ id: "agent.chat-agent", name: "Chat", category: "chat", choice: "llm-gone",
        answers: { source: null, error: "The LLM configuration chosen for agent.chat-agent no longer exists." } }],
    });
    render(<LlmConfigsSection />);
    const section = await models();
    expect(section.getByText(/no longer exists/)).toBeInTheDocument();
  });

  it("opens on the agent a card asked about", async () => {
    render(<LlmConfigsSection focus={{ section: "agent-models", agentId: "agent.dataflow-builder" }} />);
    await models();
    await waitFor(() => expect(select("Dataflow Builder")).toHaveFocus());
  });
});

describe("the configurations table and the choices", () => {
  it("says which agents each configuration is chosen for", async () => {
    render(<LlmConfigsSection />);
    const table = within(await screen.findByTestId("llm-configs-section")).getByRole("table");
    await waitFor(() => expect(table).toHaveTextContent("Local"));
    const local = within(table).getByText("Local").closest("tr")!;
    expect(local).toHaveTextContent("Node Content Builder");
  });

  it("names the agents that go back to the default when one is removed", async () => {
    render(<LlmConfigsSection />);
    fireEvent.click(await screen.findByRole("button", { name: "Remove Local" }));
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Remove Local? Node Content Builder goes back to the default.",
    );
    fireEvent.click(screen.getByRole("button", { name: "Confirm removing Local" }));
    await waitFor(() => expect(mockApi.remove).toHaveBeenCalledWith(LOCAL.id));
  });

  it("opens the editor of the configuration a card asked about", async () => {
    render(<LlmConfigsSection focus={{ section: "llm-configs", configId: LOCAL.id }} />);
    expect(await screen.findByText("Edit Local")).toBeInTheDocument();
  });
});
