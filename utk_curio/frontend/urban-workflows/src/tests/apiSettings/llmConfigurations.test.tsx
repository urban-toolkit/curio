import React from "react";
import { render, screen, waitFor, fireEvent, within } from "@testing-library/react";

/**
 * API Settings, the language models: on the API keys tab, one read-only Curio
 * row per endpoint this Curio offers (the operator's endpoint file) and the
 * account's own configurations, each a row of the one key list; on the Agent
 * configuration tab, the default an agent with no choice of its own runs on,
 * picked from Curio's models and the account's configurations. Keys are
 * write-only: the list says whether one is saved and never what it is.
 */

// Fake names only: the file's sections and models.
const GATEWAY = { name: "Gateway Lab", models: ["llama4", "llama4-large"] };
const SECOND = { name: "Second: west/2", models: ["org/small-model", "llama4"] };

const deploymentOf = (...endpoints: Array<{ name: string; models: string[] }>) => ({
  label: "Curio's default",
  apiType: endpoints.length ? "openai_compatible" : null,
  model: endpoints.length ? endpoints[0].models[0] : null,
  endpoints,
});

const NO_FILE = deploymentOf();

const listingOf = (overrides: Record<string, unknown> = {}) => ({
  configs: [],
  default: null,
  deployment: deploymentOf(GATEWAY),
  // As the server answers: this Curio's endpoint is never named by its host.
  active: {
    source: "deployment", configId: null, label: "Curio's default", model: "llama4",
    apiType: "openai_compatible", baseUrlHost: "",
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

/** A pick of one of Curio's models, as the server stores it. */
const pick = (endpoint: string, model: string) => `curio:${JSON.stringify([endpoint, model])}`;

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
const curioRows = () => screen.queryAllByTestId("llm-curio-row");
/** A select's options as [value, text, group label], in order. */
const optionsOf = (select: HTMLSelectElement) =>
  Array.from(select.options).map((o) => [
    o.value, o.textContent, o.parentElement?.tagName === "OPTGROUP" ? (o.parentElement as HTMLOptGroupElement).label : "",
  ]);
/** The buttons of a row, by accessible name, in order. */
const buttonsOf = (row: HTMLElement) => within(row).queryAllByRole("button").map((b) => b.getAttribute("aria-label") ?? b.textContent);

describe("Curio's rows in the key list", () => {
  it("lists each endpoint of the file as Curio, provided by its section, with its models, in file order", async () => {
    mockListing = listingOf({ deployment: deploymentOf(GATEWAY, SECOND) });
    render(<Panel />);
    await waitFor(() => expect(curioRows()).toHaveLength(2));
    const [first, second] = curioRows();
    expect(first).toHaveAttribute("data-endpoint", "Gateway Lab");
    expect(second).toHaveAttribute("data-endpoint", "Second: west/2");
    const cells = (row: HTMLElement) => within(row).getAllByRole("cell");
    expect(cells(first)[0]).toHaveTextContent("CurioProvided by Gateway Lab");
    expect(cells(second)[0]).toHaveTextContent("CurioProvided by Second: west/2");
    expect(cells(first)[1]).toHaveTextContent("Language model");
    expect(cells(second)[1]).toHaveTextContent("Language model");
    // The first model, then the others under it.
    expect(cells(first)[2]).toHaveTextContent("llama4Curio defaultllama4-large");
    expect(cells(second)[2]).toHaveTextContent("org/small-modelllama4");
    // Only the first section's first model is Curio's default.
    expect(within(first).getAllByText("Curio default")).toHaveLength(1);
    expect(within(second).queryByText("Curio default")).toBeNull();
    // Read-only: no Edit, no Remove, no note.
    expect(buttonsOf(first)).toEqual([]);
    expect(buttonsOf(second)).toEqual([]);
    expect(first).not.toHaveTextContent("sage.example.edu");
  });

  it("names no endpoint's host, even when a listing carries one", async () => {
    mockListing = listingOf({ deployment: { ...deploymentOf(GATEWAY), baseUrlHost: "sage.example.edu" } });
    render(<Panel />);
    await waitFor(() => expect(curioRows()).toHaveLength(1));
    expect(document.body).not.toHaveTextContent("sage.example.edu");
    showTab("Agent configuration");
    const active = await screen.findByTestId("llm-active");
    expect(active).toHaveTextContent("Answering now: Curio's default · llama4");
    expect(active).not.toHaveTextContent(" at ");
    expect(document.body).not.toHaveTextContent("sage.example.edu");
  });

  it("has no Curio rows without the file", async () => {
    mockListing = listingOf({ deployment: NO_FILE, configs: [MINE] });
    render(<Panel />);
    await waitFor(() => expect(within(screen.getByRole("table")).getByText("Work")).toBeInTheDocument());
    expect(curioRows()).toEqual([]);
    expect(screen.queryByText("Curio default")).toBeNull();
  });

  it("is a list with no button to Agent configuration, with and without the file", async () => {
    for (const deployment of [deploymentOf(GATEWAY), NO_FILE]) {
      mockListing = listingOf({ deployment, configs: [MINE] });
      const { unmount } = render(<Panel />);
      await waitFor(() => expect(within(screen.getByRole("table")).getByText("Work")).toBeInTheDocument());
      expect(screen.queryByRole("button", { name: /Agent configuration|Configure agents/ })).toBeNull();
      // The tab at the top is the way there.
      expect(screen.getByRole("tab", { name: "Agent configuration" })).toBeInTheDocument();
      unmount();
    }
  });
});

describe("the account's own configurations in the key list", () => {
  it("shows a configuration's provider, model and whether a key is saved, never the key", async () => {
    mockListing = listingOf({ configs: [MINE], default: MINE.id });
    render(<Panel />);
    const list = await table();
    await waitFor(() => expect(list).toHaveTextContent("Work"));
    const mine = within(list).getByText("Work").closest("tr")!;
    expect(mine).toHaveTextContent("Key saved");
    expect(mine).toHaveTextContent("OpenAI");
    expect(mine).toHaveTextContent("gpt-4o-mini");
    expect(mine.textContent).not.toContain("sk-");
    // The default is marked in its details and chosen on Agent configuration, not from a row.
    const cells = within(mine).getAllByRole("cell");
    expect(cells[2]).toHaveTextContent("My default");
    expect(screen.queryByRole("button", { name: /Make .* the default/ })).toBeNull();
  });

  it("ends a row it owns with Remove, then Edit: icons with their names and tooltips, and no text buttons", async () => {
    mockListing = listingOf({ configs: [MINE] });
    render(<Panel />);
    const remove = await screen.findByRole("button", { name: "Remove Work" });
    const row = remove.closest("tr")!;
    expect(buttonsOf(row)).toEqual(["Remove Work", "Edit Work"]);
    expect(remove).toHaveAttribute("data-tooltip", "Remove");
    expect(within(row).getByRole("button", { name: "Edit Work" })).toHaveAttribute("data-tooltip", "Edit");
    expect(within(row).queryByRole("button", { name: /Duplicate/ })).toBeNull();
    expect(row.querySelectorAll("[title]")).toHaveLength(0);
    expect(within(row).getByRole("button", { name: "Edit Work" }).textContent).toBe("");
  });

  it("Add configuration is the + at the end of the list's header, with a tooltip", async () => {
    render(<Panel />);
    const list = await table();
    const add = within(list).getByRole("button", { name: "Add configuration" });
    expect(add.closest("th")).not.toBeNull();
    expect(add).toHaveAttribute("data-tooltip", "Add configuration");
    expect(add).not.toHaveAttribute("title");
    expect(within(list).getAllByRole("columnheader").map((h) => h.textContent)).toEqual([
      "Name", "Kind", "Details", "Actions",
    ]);
  });

  it("asks before removing the default and says what answers next", async () => {
    mockListing = listingOf({ configs: [MINE], default: MINE.id });
    render(<Panel />);
    fireEvent.click(await screen.findByRole("button", { name: "Remove Work" }));
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Remove Work? It is your default, so runs will use Curio's default (llama4).",
    );
    fireEvent.click(screen.getByRole("button", { name: "Confirm removing Work" }));
    await waitFor(() => expect(mockApi.remove).toHaveBeenCalledWith(MINE.id));
  });

  it("Keep leaves it, with its icons back", async () => {
    mockListing = listingOf({ configs: [MINE] });
    render(<Panel />);
    fireEvent.click(await screen.findByRole("button", { name: "Remove Work" }));
    fireEvent.click(screen.getByRole("button", { name: "Keep" }));
    expect(screen.getByRole("button", { name: "Edit Work" })).toBeInTheDocument();
    expect(mockApi.remove).not.toHaveBeenCalled();
  });
});

describe("the Agent configuration default", () => {
  it("offers Curio's default with its model, each endpoint's models by group, then my configurations", async () => {
    mockListing = listingOf({ configs: [MINE], deployment: deploymentOf(GATEWAY, SECOND) });
    render(<Panel initial="agents" />);
    const choice = (await screen.findByLabelText("Default for my agents")) as HTMLSelectElement;
    expect(choice.value).toBe("");
    expect(optionsOf(choice)).toEqual([
      ["", "Curio's default: llama4", ""],
      [pick("Gateway Lab", "llama4"), "llama4", "Curio · Gateway Lab"],
      [pick("Gateway Lab", "llama4-large"), "llama4-large", "Curio · Gateway Lab"],
      [pick("Second: west/2", "org/small-model"), "org/small-model", "Curio · Second: west/2"],
      [pick("Second: west/2", "llama4"), "llama4", "Curio · Second: west/2"],
      [MINE.id, "Work: gpt-4o-mini", "My configurations"],
    ]);
  });

  it("offers only my configurations without the file", async () => {
    mockListing = listingOf({ configs: [MINE], deployment: NO_FILE, default: MINE.id });
    render(<Panel initial="agents" />);
    const choice = (await screen.findByLabelText("Default for my agents")) as HTMLSelectElement;
    expect(choice.value).toBe(MINE.id);
    expect(optionsOf(choice)).toEqual([
      ["", "None chosen", ""],
      [MINE.id, "Work: gpt-4o-mini", "My configurations"],
    ]);
    expect(choice.querySelectorAll("optgroup")).toHaveLength(1);
  });

  it("picks one of Curio's models, the same name on the second endpoint being that endpoint's", async () => {
    mockListing = listingOf({ configs: [MINE], deployment: deploymentOf(GATEWAY, SECOND) });
    render(<Panel initial="agents" />);
    const choice = (await screen.findByLabelText("Default for my agents")) as HTMLSelectElement;
    fireEvent.change(choice, { target: { value: pick("Second: west/2", "llama4") } });
    await waitFor(() => expect(mockApi.setDefault).toHaveBeenCalledWith(pick("Second: west/2", "llama4")));
  });

  it("shows a pick the file no longer offers, so it is picked again", async () => {
    const gone = pick("Old lab", "model-z");
    mockListing = listingOf({ configs: [MINE], default: gone });
    render(<Panel initial="agents" />);
    const choice = (await screen.findByLabelText("Default for my agents")) as HTMLSelectElement;
    expect(choice.value).toBe(gone);
    const shown = choice.options[choice.selectedIndex];
    expect(shown.textContent).toBe("Curio · Old lab: model-z (no longer offered)");
    expect(shown.disabled).toBe(true);
    fireEvent.change(choice, { target: { value: pick("Gateway Lab", "llama4-large") } });
    await waitFor(() => expect(mockApi.setDefault).toHaveBeenCalledWith(pick("Gateway Lab", "llama4-large")));
  });

  it("makes a configuration the default, and Curio's default goes back from the same choice", async () => {
    mockListing = listingOf({ configs: [MINE] });
    render(<Panel initial="agents" />);
    const choice = (await screen.findByLabelText("Default for my agents")) as HTMLSelectElement;
    fireEvent.change(choice, { target: { value: MINE.id } });
    await waitFor(() => expect(mockApi.setDefault).toHaveBeenCalledWith(MINE.id));
    await waitFor(() => expect(choice).toBeEnabled());
    fireEvent.change(choice, { target: { value: "" } });
    await waitFor(() => expect(mockApi.setDefault).toHaveBeenLastCalledWith(null));
  });

  it("with nothing to choose from, Agent configuration sends you to API keys", async () => {
    mockListing = listingOf({
      deployment: NO_FILE,
      active: { source: null, error: "No LLM configuration answers this run." },
    });
    render(<Panel initial="agents" />);
    fireEvent.click(await screen.findByRole("button", { name: "Add one on the API keys tab" }));
    expect(screen.getByRole("tab", { name: "API keys" })).toHaveAttribute("aria-selected", "true");
    expect(await screen.findByRole("button", { name: "Add configuration" })).toBeInTheDocument();
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
  const providerTabs = (editor: ReturnType<typeof within>) =>
    within(editor.getByRole("group", { name: "Provider" })).getAllByRole("button").map((b) => b.textContent);

  it("is the same with and without the file: four providers, a key and a model with Fetch", async () => {
    for (const deployment of [deploymentOf(GATEWAY, SECOND), NO_FILE]) {
      mockListing = listingOf({ deployment });
      const { unmount } = render(<Panel />);
      fireEvent.click(await screen.findByRole("button", { name: "Add configuration" }));
      const editor = within(screen.getByTestId("llm-config-editor"));
      const kind = screen.getByLabelText("Kind");
      const label = editor.getByLabelText("Label");
      // Kind comes first, then Label.
      expect(kind.compareDocumentPosition(label) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
      expect(providerTabs(editor)).toEqual(["OpenAI", "Anthropic", "Gemini", "Custom"]);
      expect(editor.queryByRole("button", { name: "This Curio install" })).toBeNull();
      expect(screen.getByTestId("llm-config-editor")).not.toHaveTextContent("This Curio install");
      expect(editor.getByLabelText(/API key/)).toBeInTheDocument();
      expect((editor.getByLabelText("Model") as HTMLElement).tagName).toBe("INPUT");
      expect(editor.getByRole("button", { name: "Fetch models" })).toBeInTheDocument();
      expect(editor.getByLabelText("Make this my default")).toBeInTheDocument();
      expect(editor.getByRole("button", { name: "Cancel" })).toBeInTheDocument();
      expect(editor.getByRole("button", { name: "Add configuration" })).toBeInTheDocument();
      // Nothing about Curio's own models is in the form.
      expect(screen.getByTestId("llm-config-editor")).not.toHaveTextContent("Gateway Lab");
      unmount();
    }
  });

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

  it("Edit is the same form, with Duplicate on the left and no Remove", async () => {
    mockListing = listingOf({ configs: [MINE], default: MINE.id });
    mockApi.update.mockResolvedValue({ config: MINE });
    render(<Panel />);
    fireEvent.click(await screen.findByRole("button", { name: "Edit Work" }));
    const editorRoot = screen.getByTestId("llm-config-editor");
    const editor = within(editorRoot);
    expect(editor.getByRole("heading", { name: "Edit Work" })).toBeInTheDocument();
    expect(providerTabs(editor)).toEqual(["OpenAI", "Anthropic", "Gemini", "Custom"]);
    // The footer: Duplicate, then Cancel and Save configuration; nothing removes from here.
    const footer = editor.getAllByRole("button").slice(-3).map((b) => b.textContent);
    expect(footer).toEqual(["Duplicate", "Cancel", "Save configuration"]);
    expect(editor.queryByRole("button", { name: /^Remove( Work)?$/ })).toBeNull();
    // While it is open the list adds nothing else.
    expect(within(screen.getByRole("table")).queryByRole("button", { name: "Add configuration" })).toBeNull();
  });

  it("Duplicate in the editor copies it server-side and closes the editor", async () => {
    mockListing = listingOf({ configs: [MINE], default: MINE.id });
    render(<Panel />);
    fireEvent.click(await screen.findByRole("button", { name: "Edit Work" }));
    fireEvent.click(within(screen.getByTestId("llm-config-editor")).getByRole("button", { name: "Duplicate Work" }));
    await waitFor(() => expect(mockApi.duplicate).toHaveBeenCalledWith(MINE.id));
    expect(screen.queryByTestId("llm-config-editor")).toBeNull();
    expect(await screen.findByRole("status")).toHaveTextContent("Added Work copy.");
  });

  it("a full account cannot duplicate from the editor", async () => {
    mockListing = listingOf({ configs: [MINE], maxConfigs: 1 });
    render(<Panel />);
    fireEvent.click(await screen.findByRole("button", { name: "Edit Work" }));
    expect(within(screen.getByTestId("llm-config-editor")).getByRole("button", { name: "Duplicate Work" })).toBeDisabled();
  });

  it("editing leaves the saved key unless a new one is typed, and says so", async () => {
    mockListing = listingOf({ configs: [MINE], default: MINE.id });
    mockApi.update.mockResolvedValue({ config: MINE });
    render(<Panel />);
    fireEvent.click(await screen.findByRole("button", { name: "Edit Work" }));
    const editor = within(screen.getByTestId("llm-config-editor"));
    // An edit is not an add: no kind to choose.
    expect(screen.queryByLabelText("Kind")).toBeNull();
    expect(editor.getByText("(saved, leave blank to keep)")).toBeInTheDocument();
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
    expect(editor.queryByText("(saved, leave blank to keep)")).toBeNull();
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
  it("a hosted guest sees Curio's rows, the guest configuration and nothing to edit or choose", async () => {
    mockUser = { is_guest: true };
    mockListing = listingOf({
      editable: false,
      reason: "LLM configurations are not available to guests on this Curio.",
      deployment: deploymentOf(GATEWAY, SECOND),
      active: { source: "guest", configId: null, label: "Guest configuration", model: "small", baseUrlHost: "guest.example.edu" },
    });
    render(<Panel />);
    expect(await screen.findByText(/not available to guests/)).toBeInTheDocument();
    expect(screen.getByText("small")).toBeInTheDocument();
    // This Curio's endpoint is never named by its host, even one a listing carries.
    expect(screen.getByText("small").closest("p")).toHaveTextContent("Guests use small on this Curio's endpoint.");
    expect(document.body).not.toHaveTextContent("guest.example.edu");
    expect(screen.getByText("Personal keys cannot be saved on a shared guest account.")).toBeInTheDocument();
    // The list holds only Curio's rows, and no button at all.
    const list = await table();
    expect(curioRows()).toHaveLength(2);
    expect(within(list).getAllByRole("row")).toHaveLength(3); // the header and Curio's two rows
    expect(within(list).queryAllByRole("button")).toEqual([]);
    expect(screen.queryByRole("button", { name: "Add configuration" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Agent configuration|Configure agents/ })).toBeNull();
    showTab("Agent configuration");
    expect(await screen.findByText(/not available to guests/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Default for my agents")).toBeNull();
    expect(screen.queryByRole("combobox")).toBeNull();
  });

  it("the local guest is told the keys are shared", async () => {
    mockListing = listingOf({ shared: true });
    render(<Panel />);
    expect(await screen.findByText(/Everyone using this Curio shares this account/)).toBeInTheDocument();
  });
});
