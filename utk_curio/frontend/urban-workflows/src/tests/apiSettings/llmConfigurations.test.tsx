import React from "react";
import { render, screen, waitFor, fireEvent, within } from "@testing-library/react";

/**
 * API Settings, the language models: on the API keys tab, the account's
 * endpoints and models beside the Deployment default this Curio offers, each a
 * row of the one key list; on the Agent configuration tab, the default an
 * agent with no choice of its own runs on. Keys are write-only: the list says
 * whether one is saved and never what it is.
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
  model: "gpt-4o-mini", createdAt: 1, updatedAt: 1,
};

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

let mockUser: Record<string, unknown> = { is_guest: false };
let mockAuthOn = true;
jest.mock("../../providers/UserProvider", () => ({
  useUserContext: () => ({
    user: mockUser, updateTokens: jest.fn(), isSharedGuest: false, enableUserAuth: mockAuthOn,
  }),
}));
// The other kinds of key are empty here; apiKeys.test.tsx covers them.
jest.mock("../../api/connectionKeysApi", () => ({
  connectionKeysApi: { list: () => Promise.resolve({ keys: [] }) },
}));
jest.mock("../../services/discoveryCatalog", () => {
  const actual = jest.requireActual("../../services/discoveryCatalog");
  return {
    ...actual,
    discoveryCatalogApi: { ...actual.discoveryCatalogApi, listKeys: () => Promise.resolve({ keys: [] }) },
    notifyDiscoveryCatalogRefresh: () => undefined,
  };
});

import { ApiSettingsPanel } from "../../components/apiSettings/ApiSettingsPanel";
import type { ApiSettingsFocus, ApiSettingsTab } from "../../components/apiSettings/apiSettingsRequest";

function Panel({ initial = "keys", focus = null }: { initial?: ApiSettingsTab; focus?: ApiSettingsFocus | null }) {
  const [tab, setTab] = React.useState<ApiSettingsTab>(initial);
  return <ApiSettingsPanel tab={tab} onTabChange={setTab} focus={focus} />;
}

beforeEach(() => {
  mockListing = listingOf();
  mockUser = { is_guest: false };
  mockAuthOn = true;
  jest.clearAllMocks();
  mockApi.listing.mockImplementation(() => Promise.resolve(mockListing));
  mockApi.setDefault.mockResolvedValue(mockListing);
  mockApi.remove.mockResolvedValue({ deleted: MINE.id, moved: [], default: null });
  mockApi.duplicate.mockResolvedValue({ config: { ...MINE, id: "llm-00000000000b", label: "Work copy" } });
});

const table = async () => screen.findByRole("table");
const showTab = (name: string) => fireEvent.click(screen.getByRole("tab", { name }));

describe("the language models in the key list", () => {
  it("lists the Deployment default as this Curio's, and Agent configuration says what answers now", async () => {
    render(<Panel />);
    const row = await screen.findByTestId("llm-deployment-row");
    expect(row).toHaveTextContent("Deployment default");
    expect(row).toHaveTextContent("Default");
    expect(row).toHaveTextContent("Language model");
    expect(row).toHaveTextContent("llama4");
    expect(row).toHaveTextContent("sage.example.edu");
    expect(row).toHaveTextContent("set by this Curio");
    expect(within(await table()).getAllByRole("row")).toHaveLength(2); // the header and this row
    showTab("Agent configuration");
    expect(await screen.findByTestId("llm-active")).toHaveTextContent(
      "Answering now: Deployment default · llama4 at sage.example.edu",
    );
  });

  it("shows a configuration's provider, model and whether a key is saved, never the key", async () => {
    mockListing = listingOf({ configs: [MINE], default: MINE.id });
    render(<Panel />);
    const list = await table();
    await waitFor(() => expect(list).toHaveTextContent("Work"));
    const mine = within(list).getByText("Work").closest("tr")!;
    expect(mine).toHaveTextContent("OpenAI");
    expect(mine).toHaveTextContent("gpt-4o-mini");
    expect(mine).toHaveTextContent("saved");
    expect(mine).toHaveTextContent("Default");
    expect(mine.textContent).not.toContain("sk-");
    // The default is chosen on Agent configuration, not from a row.
    expect(screen.queryByRole("button", { name: /Make .* the default/ })).toBeNull();
  });

  it("makes a configuration the default on Agent configuration, and duplicates one", async () => {
    mockListing = listingOf({ configs: [MINE] });
    render(<Panel initial="agents" />);
    const choice = (await screen.findByLabelText("Default for agents")) as HTMLSelectElement;
    expect(choice.value).toBe("");
    expect(Array.from(choice.options).map((o) => [o.value, o.textContent])).toEqual([
      ["", "Deployment default · llama4"],
      [MINE.id, "Work · gpt-4o-mini"],
    ]);
    fireEvent.change(choice, { target: { value: MINE.id } });
    await waitFor(() => expect(mockApi.setDefault).toHaveBeenCalledWith(MINE.id));
    showTab("API keys");
    // Every action waits for the one before it to finish reloading.
    await waitFor(() => expect(screen.getByRole("button", { name: "Duplicate Work" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Duplicate Work" }));
    await waitFor(() => expect(mockApi.duplicate).toHaveBeenCalledWith(MINE.id));
  });

  it("the Deployment default goes back to being the default from the same choice", async () => {
    mockListing = listingOf({ configs: [MINE], default: MINE.id });
    render(<Panel initial="agents" />);
    const choice = (await screen.findByLabelText("Default for agents")) as HTMLSelectElement;
    expect(choice.value).toBe(MINE.id);
    fireEvent.change(choice, { target: { value: "" } });
    await waitFor(() => expect(mockApi.setDefault).toHaveBeenCalledWith(null));
  });

  it("with nothing to choose from, Agent configuration sends you to API keys", async () => {
    mockListing = listingOf({
      deployment: { label: "Deployment default", endpointOffered: false, apiType: null, baseUrlHost: null, model: null },
      active: { source: null, error: "No LLM configuration answers this run." },
    });
    render(<Panel initial="agents" />);
    fireEvent.click(await screen.findByRole("button", { name: "Add one on the API keys tab" }));
    expect(screen.getByRole("tab", { name: "API keys" })).toHaveAttribute("aria-selected", "true");
    expect(await screen.findByRole("button", { name: "Add configuration" })).toBeInTheDocument();
  });

  it("asks before removing the default and says what answers next", async () => {
    mockListing = listingOf({ configs: [MINE], default: MINE.id });
    render(<Panel />);
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
    render(<Panel />);
    fireEvent.click(await screen.findByRole("button", { name: "Add configuration" }));
    // A language model is the first kind "Add configuration" offers.
    expect((screen.getByLabelText("Kind") as HTMLSelectElement).value).toBe("llm");
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
    render(<Panel />);
    fireEvent.click(await screen.findByRole("button", { name: "Edit Work" }));
    const editor = within(screen.getByTestId("llm-config-editor"));
    // An edit is not an add: no kind to choose.
    expect(screen.queryByLabelText("Kind")).toBeNull();
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
    render(<Panel />);
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
    render(<Panel />);
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
    render(<Panel />);
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

  it("a full account cannot add another language model, but can add other keys", async () => {
    mockListing = listingOf({ configs: [MINE], maxConfigs: 1 });
    render(<Panel />);
    fireEvent.click(await screen.findByRole("button", { name: "Add configuration" }));
    const kind = screen.getByLabelText("Kind") as HTMLSelectElement;
    const llm = Array.from(kind.options).find((o) => o.value === "llm")!;
    expect(llm.disabled).toBe(true);
    expect(kind.value).toBe("node");
    expect(screen.getByTestId("node-key-editor")).toBeInTheDocument();
  });
});

describe("guests", () => {
  it("a hosted guest sees the guest configuration and nothing to edit", async () => {
    mockUser = { is_guest: true };
    mockListing = listingOf({
      editable: false,
      reason: "LLM configurations are not available to guests on this Curio.",
      active: { source: "guest", configId: null, label: "Guest configuration", model: "small", baseUrlHost: "guest.example.edu" },
    });
    render(<Panel />);
    expect(await screen.findByText(/not available to guests/)).toBeInTheDocument();
    expect(screen.getByText("small")).toBeInTheDocument();
    expect(screen.getByText("Personal keys cannot be saved on a shared guest account.")).toBeInTheDocument();
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.queryByRole("button", { name: "Add configuration" })).toBeNull();
    showTab("Agent configuration");
    expect(await screen.findByText(/not available to guests/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Default for agents")).toBeNull();
  });

  it("the local guest is told the keys are shared", async () => {
    mockListing = listingOf({ shared: true });
    render(<Panel />);
    expect(await screen.findByText(/Everyone using this Curio shares this account/)).toBeInTheDocument();
  });
});
