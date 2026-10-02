import React from "react";
import { render, screen, waitFor, fireEvent, within } from "@testing-library/react";

/**
 * API Settings → LLM configurations: the account's endpoints and models, the
 * default an attached agent with no choice answers with, and the Deployment
 * default this Curio offers. Keys are write-only: the section says whether one
 * is saved and never what it is.
 */

const listingOf = (overrides: Record<string, unknown> = {}) => ({
  configs: [],
  default: null,
  deployment: {
    label: "Deployment default",
    endpointOffered: true,
    apiType: "openai_compatible",
    baseUrlHost: "sage.example.edu",
    model: "llama4",
  },
  active: {
    source: "deployment", configId: null, label: "Deployment default", model: "llama4",
    apiType: "openai_compatible", baseUrlHost: "sage.example.edu",
  },
  editable: true,
  reason: null,
  shared: false,
  maxConfigs: 32,
  ...overrides,
});

const MINE = {
  id: "llm-00000000000a", label: "Work", endpoint: "own", apiType: "openai_compatible",
  baseUrl: "https://api.openai.com/v1", baseUrlHost: "api.openai.com", hasApiKey: true,
  model: "gpt-4o-mini", origin: "user", createdAt: 1, updatedAt: 1,
};

let mockListing: Record<string, unknown> = listingOf();
const mockApi = {
  listing: jest.fn(() => Promise.resolve(mockListing)),
  create: jest.fn(),
  update: jest.fn(),
  remove: jest.fn(),
  duplicate: jest.fn(),
  setDefault: jest.fn(),
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
  mockApi.setDefault.mockResolvedValue(mockListing);
  mockApi.remove.mockResolvedValue({ deleted: MINE.id, moved: [], default: null });
  mockApi.duplicate.mockResolvedValue({ config: { ...MINE, id: "llm-00000000000b", label: "Work copy" } });
});

const section = async () => within(await screen.findByTestId("llm-configs-section"));

describe("the configurations table", () => {
  it("lists the Deployment default and says what answers now", async () => {
    render(<LlmConfigsSection />);
    const row = await screen.findByTestId("llm-deployment-row");
    expect(row).toHaveTextContent("Deployment default");
    expect(row).toHaveTextContent("Default");
    expect(row).toHaveTextContent("llama4");
    expect(row).toHaveTextContent("sage.example.edu");
    expect(screen.getByTestId("llm-active")).toHaveTextContent("Answering now: Deployment default · llama4 at sage.example.edu");
    expect(screen.getByText("No configurations of your own yet.")).toBeInTheDocument();
  });

  it("shows a configuration's provider, model and whether a key is saved, never the key", async () => {
    mockListing = listingOf({ configs: [MINE], default: MINE.id });
    render(<LlmConfigsSection />);
    const table = (await section()).getByRole("table");
    await waitFor(() => expect(table).toHaveTextContent("Work"));
    expect(table).toHaveTextContent("OpenAI");
    expect(table).toHaveTextContent("gpt-4o-mini");
    expect(table).toHaveTextContent("saved");
    const mine = screen.getByText("Work").closest("tr")!;
    expect(mine).toHaveTextContent("Default");
    // Its own row offers no "Make default"; the Deployment default's does.
    expect(within(mine).queryByRole("button", { name: /Make Work the default/ })).toBeNull();
    expect(within(screen.getByTestId("llm-deployment-row")).getByRole("button", { name: "Make default" })).toBeInTheDocument();
  });

  it("makes a configuration the default, and duplicates one", async () => {
    mockListing = listingOf({ configs: [MINE] });
    render(<LlmConfigsSection />);
    fireEvent.click(await screen.findByRole("button", { name: "Make Work the default" }));
    await waitFor(() => expect(mockApi.setDefault).toHaveBeenCalledWith(MINE.id));
    // Every action waits for the one before it to finish reloading.
    await waitFor(() => expect(screen.getByRole("button", { name: "Duplicate Work" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Duplicate Work" }));
    await waitFor(() => expect(mockApi.duplicate).toHaveBeenCalledWith(MINE.id));
  });

  it("asks before removing the default and says what answers next", async () => {
    mockListing = listingOf({ configs: [MINE], default: MINE.id });
    render(<LlmConfigsSection />);
    fireEvent.click(await screen.findByRole("button", { name: "Remove Work" }));
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Remove Work? It is your default, so runs will use the Deployment default (llama4).",
    );
    fireEvent.click(screen.getByRole("button", { name: "Confirm removing Work" }));
    await waitFor(() => expect(mockApi.remove).toHaveBeenCalledWith(MINE.id));
  });
});

describe("the editor", () => {
  const openEditor = async () => {
    render(<LlmConfigsSection />);
    fireEvent.click(await screen.findByRole("button", { name: "Add configuration" }));
    return within(screen.getByTestId("llm-config-editor"));
  };

  it("saves an OpenAI configuration with OpenAI's own URL, and makes the first one the default", async () => {
    mockApi.create.mockResolvedValue({ config: { ...MINE, id: "llm-00000000000c" } });
    const editor = await openEditor();
    fireEvent.change(editor.getByLabelText("Label"), { target: { value: "Work" } });
    const key = editor.getByLabelText(/API key/) as HTMLInputElement;
    expect(key.type).toBe("password");
    fireEvent.change(key, { target: { value: "sk-typed-key" } });
    fireEvent.change(editor.getByLabelText("Model"), { target: { value: "gpt-4o-mini" } });
    expect(editor.getByLabelText("Make this my default")).toBeChecked();
    fireEvent.click(editor.getByRole("button", { name: "Add configuration" }));
    await waitFor(() =>
      expect(mockApi.create).toHaveBeenCalledWith({
        label: "Work", model: "gpt-4o-mini", endpoint: "own", apiType: "openai_compatible",
        baseUrl: "https://api.openai.com/v1", apiKey: "sk-typed-key",
      }),
    );
    await waitFor(() => expect(mockApi.setDefault).toHaveBeenCalledWith("llm-00000000000c"));
  });

  it("a Custom endpoint takes a base URL; Anthropic takes none and needs a key", async () => {
    const editor = await openEditor();
    expect(editor.queryByLabelText("Base URL")).toBeNull();
    fireEvent.click(editor.getByRole("button", { name: "Custom" }));
    expect(editor.getByLabelText("Base URL")).toBeInTheDocument();
    expect(editor.getByText("(optional for keyless servers)")).toBeInTheDocument();
    fireEvent.click(editor.getByRole("button", { name: "Anthropic" }));
    expect(editor.queryByLabelText("Base URL")).toBeNull();
    expect(editor.getByText("(required)")).toBeInTheDocument();
  });

  it("This Curio install takes only a label and a model", async () => {
    mockApi.create.mockResolvedValue({ config: { ...MINE, endpoint: "deployment" } });
    const editor = await openEditor();
    fireEvent.click(editor.getByRole("button", { name: "This Curio install" }));
    expect(editor.queryByLabelText(/API key/)).toBeNull();
    fireEvent.change(editor.getByLabelText("Label"), { target: { value: "Here" } });
    fireEvent.change(editor.getByLabelText("Model"), { target: { value: "llama4-large" } });
    fireEvent.click(editor.getByRole("button", { name: "Add configuration" }));
    await waitFor(() =>
      expect(mockApi.create).toHaveBeenCalledWith({ label: "Here", model: "llama4-large", endpoint: "deployment" }),
    );
  });

  it("This Curio install is not offered when the deployment has no endpoint", async () => {
    mockListing = listingOf({
      deployment: { label: "Deployment default", endpointOffered: false, apiType: null, baseUrlHost: null, model: null },
    });
    const editor = await openEditor();
    expect(editor.queryByRole("button", { name: "This Curio install" })).toBeNull();
  });

  it("editing leaves the saved key unless a new one is typed, and says so", async () => {
    mockListing = listingOf({ configs: [MINE], default: MINE.id });
    mockApi.update.mockResolvedValue({ config: MINE });
    render(<LlmConfigsSection />);
    fireEvent.click(await screen.findByRole("button", { name: "Edit Work" }));
    const editor = within(screen.getByTestId("llm-config-editor"));
    expect(editor.getByText("(saved - leave blank to keep)")).toBeInTheDocument();
    expect((editor.getByLabelText(/API key/) as HTMLInputElement).value).toBe("");
    fireEvent.change(editor.getByLabelText("Model"), { target: { value: "gpt-4o" } });
    fireEvent.click(editor.getByRole("button", { name: "Save configuration" }));
    await waitFor(() =>
      expect(mockApi.update).toHaveBeenCalledWith(MINE.id, {
        label: "Work", model: "gpt-4o", endpoint: "own", apiType: "openai_compatible",
        baseUrl: "https://api.openai.com/v1",
      }),
    );
  });

  it("moving a configuration to another endpoint asks for its key again", async () => {
    mockListing = listingOf({ configs: [MINE], default: MINE.id });
    mockApi.update.mockResolvedValue({ config: MINE });
    render(<LlmConfigsSection />);
    fireEvent.click(await screen.findByRole("button", { name: "Edit Work" }));
    const editor = within(screen.getByTestId("llm-config-editor"));
    fireEvent.click(editor.getByRole("button", { name: "Custom" }));
    fireEvent.change(editor.getByLabelText("Base URL"), { target: { value: "http://localhost:11434/v1" } });
    expect(editor.getByText(/never follows a configuration to another endpoint/)).toBeInTheDocument();
    expect(editor.queryByText("(saved - leave blank to keep)")).toBeNull();
    // Saved without a key, the old one is dropped rather than sent to the new host.
    fireEvent.click(editor.getByRole("button", { name: "Save configuration" }));
    await waitFor(() =>
      expect(mockApi.update).toHaveBeenCalledWith(MINE.id, {
        label: "Work", model: "gpt-4o-mini", endpoint: "own", apiType: "openai_compatible",
        baseUrl: "http://localhost:11434/v1", clearApiKey: true,
      }),
    );
  });

  it("a key typed for the new endpoint is sent instead", async () => {
    mockListing = listingOf({ configs: [MINE], default: MINE.id });
    mockApi.update.mockResolvedValue({ config: MINE });
    render(<LlmConfigsSection />);
    fireEvent.click(await screen.findByRole("button", { name: "Edit Work" }));
    const editor = within(screen.getByTestId("llm-config-editor"));
    fireEvent.click(editor.getByRole("button", { name: "Anthropic" }));
    fireEvent.change(editor.getByLabelText(/API key/), { target: { value: "sk-ant-typed" } });
    fireEvent.change(editor.getByLabelText("Model"), { target: { value: "claude-haiku-4-5" } });
    fireEvent.click(editor.getByRole("button", { name: "Save configuration" }));
    await waitFor(() =>
      expect(mockApi.update).toHaveBeenCalledWith(MINE.id, {
        label: "Work", model: "claude-haiku-4-5", endpoint: "own", apiType: "anthropic",
        baseUrl: "", apiKey: "sk-ant-typed",
      }),
    );
  });

  it("fetching models asks with the configuration's id and no typed key", async () => {
    mockListing = listingOf({ configs: [MINE], default: MINE.id });
    mockApi.models.mockResolvedValue({ models: ["gpt-4o", "gpt-4o-mini"], listable: true, source: "live" });
    render(<LlmConfigsSection />);
    fireEvent.click(await screen.findByRole("button", { name: "Edit Work" }));
    const editor = within(screen.getByTestId("llm-config-editor"));
    fireEvent.click(editor.getByRole("button", { name: "Fetch models" }));
    await waitFor(() =>
      expect(mockApi.models).toHaveBeenCalledWith({
        apiType: "openai_compatible", baseUrl: "https://api.openai.com/v1", apiKey: undefined, configId: MINE.id,
      }),
    );
    expect(await editor.findByText("From this endpoint: 2 models")).toBeInTheDocument();
  });

  it("shows the server's refusal", async () => {
    mockApi.create.mockRejectedValue(new Error("a configuration is already labelled 'Work'"));
    const editor = await openEditor();
    fireEvent.change(editor.getByLabelText("Label"), { target: { value: "Work" } });
    fireEvent.change(editor.getByLabelText("Model"), { target: { value: "m" } });
    fireEvent.click(editor.getByRole("button", { name: "Add configuration" }));
    expect(await editor.findByRole("alert")).toHaveTextContent("already labelled 'Work'");
  });
});

describe("guests", () => {
  it("a hosted guest sees the guest configuration and nothing to edit", async () => {
    mockListing = listingOf({
      editable: false,
      reason: "LLM configurations are not available to guests on this Curio.",
      active: { source: "guest", configId: null, label: "Guest configuration", model: "small", baseUrlHost: "guest.example.edu" },
    });
    render(<LlmConfigsSection />);
    expect(await screen.findByText(/not available to guests/)).toBeInTheDocument();
    expect(screen.getByText("small")).toBeInTheDocument();
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.queryByRole("button", { name: "Add configuration" })).toBeNull();
  });

  it("the local guest is told the configurations are shared", async () => {
    mockListing = listingOf({ shared: true });
    render(<LlmConfigsSection />);
    expect(await screen.findByText(/Everyone using this Curio shares this account/)).toBeInTheDocument();
  });
});
