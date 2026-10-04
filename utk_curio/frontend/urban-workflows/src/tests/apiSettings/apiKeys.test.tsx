import React from "react";
import { act, render, screen, waitFor, fireEvent, within } from "@testing-library/react";

/**
 * API Settings, API keys: every key the account uses in one list, and one "Add
 * configuration" whose Kind picks what is added. The language models are
 * tested in llmConfigurations.test.tsx; this file covers the other two kinds.
 * A data source key the Discovery Catalog sends (the Hugging Face and Socrata
 * tokens among them), drawn from the server's list; and a key node code reads
 * by name, bound to one host. Every key is write-only.
 */

const SIGNED_IN = { is_guest: false };

// Mutable so the guest case can share one module registry with the rest.
let mockUser: Record<string, unknown> = { ...SIGNED_IN };
let mockSharedGuest = false;
// Sign-in on (a --deploy Curio) unless a test says otherwise.
let mockAuthOn = true;

const mockUpdate = jest.fn().mockResolvedValue(undefined);

jest.mock("../../providers/UserProvider", () => ({
  useUserContext: () => ({
    user: mockUser, updateTokens: mockUpdate, isSharedGuest: mockSharedGuest, enableUserAuth: mockAuthOn,
  }),
}));

// No language model of the account's own and no Deployment default, so the
// list holds only the kinds this file is about.
let mockLlmEditable = true;
jest.mock("../../api/llmConfigsApi", () => ({
  llmConfigsApi: {
    listing: jest.fn(() =>
      Promise.resolve({
        configs: [],
        default: null,
        deployment: { label: "Deployment default", endpointOffered: false, apiType: null, baseUrlHost: null, model: null },
        active: { source: null, error: "No LLM configuration answers this run." },
        editable: mockLlmEditable,
        reason: mockLlmEditable ? null : "LLM configurations are not available to guests on this Curio.",
        shared: false,
        maxConfigs: 32,
      }),
    ),
  },
}));

// The keys node code reads: the client is mocked so the suite never fetches,
// and a mutable list drives the rows.
let mockKeys: Array<Record<string, unknown>> = [];
const mockPut = jest.fn();
const mockRemove = jest.fn();
const mockListNodeKeys = jest.fn(() => Promise.resolve({ keys: mockKeys }));
jest.mock("../../api/connectionKeysApi", () => ({
  connectionKeysApi: {
    list: () => mockListNodeKeys(),
    put: (...args: unknown[]) => mockPut(...args),
    remove: (...args: unknown[]) => mockRemove(...args),
  },
}));

// The Discovery Catalog's key slots, as `GET /api/discovery/keys` lists them.
// Spread requireActual rather than replacing the module: a partial mock that
// enumerates exports breaks the moment someone adds one.
type Row = Record<string, unknown>;
const HF_ROW = (over: Row = {}): Row => ({
  slot: "huggingface.token", label: "Hugging Face token", field: "huggingface_token",
  helpUrl: "https://huggingface.co/settings/tokens", placeholder: "hf_...", note: null,
  present: false, inherited: false,
  sources: [
    { name: "Hugging Face documentation images", dirName: "source.huggingface.documentation-images@1" },
    { name: "Hugging Face models", dirName: "source.huggingface.models@1" },
  ],
  ...over,
});
const SOCRATA_ROW = (over: Row = {}): Row => ({
  slot: "socrata.app-token", label: "Socrata app token", field: "socrata_app_token",
  helpUrl: "https://evergreen.data.socrata.com/signup", placeholder: "Your app token",
  note: "Socrata portals answer without one; a token raises the rate limit.",
  present: false, inherited: false,
  sources: [{ name: "City of Chicago Data Portal", dirName: "source.cityofchicago.data-portal@1" }],
  ...over,
});
const MAPILLARY_ROW = (over: Row = {}): Row => ({
  slot: "mapillary.token", label: "Mapillary client token", field: "mapillary_access_token",
  helpUrl: "https://www.mapillary.com/dashboard/developers", placeholder: "MLY|...", note: null,
  present: false, inherited: false, sources: [{ name: "Mapillary", dirName: "source.mapillary.imagery@1" }],
  ...over,
});
let mockKeyRows: Row[] = [];
const mockListKeys = jest.fn(() => Promise.resolve({ keys: mockKeyRows }));
const mockNotifyRefresh = jest.fn();
jest.mock("../../services/discoveryCatalog", () => {
  const actual = jest.requireActual("../../services/discoveryCatalog");
  return {
    ...actual,
    discoveryCatalogApi: { ...actual.discoveryCatalogApi, listKeys: () => mockListKeys() },
    notifyDiscoveryCatalogRefresh: () => mockNotifyRefresh(),
  };
});

import { ApiSettingsPanel } from "../../components/apiSettings/ApiSettingsPanel";
import type { ApiSettingsFocus, ApiSettingsTab } from "../../components/apiSettings/apiSettingsRequest";

function Panel({ focus = null }: { focus?: ApiSettingsFocus | null }) {
  const [tab, setTab] = React.useState<ApiSettingsTab>("keys");
  return <ApiSettingsPanel tab={tab} onTabChange={setTab} focus={focus} />;
}

const open = (focus: ApiSettingsFocus | null = null) => render(<Panel focus={focus} />);
const HF_ID = "#api-settings-key-huggingface-token";
const SOCRATA_ID = "#api-settings-key-socrata-app-token";
const field = (id: string) => document.querySelector(id) as HTMLInputElement | null;
const labelOf = (id: string) => document.querySelector(`label[for="${id.slice(1)}"]`)?.textContent ?? "";
const rowOf = async (name: string) => (await screen.findByText(name, { selector: "td" })).closest("tr")!;
const kindSelect = () => screen.getByLabelText("Kind") as HTMLSelectElement;
const kindValues = () => Array.from(kindSelect().options).map((o) => o.value);

/** "Add configuration", then the given Kind. */
const addKind = async (value: string) => {
  fireEvent.click(await screen.findByRole("button", { name: "Add configuration" }));
  fireEvent.change(kindSelect(), { target: { value } });
};

// Both lists arrive after the first render, so a check that a screen lacks
// something waits for them first: made before they land, it passes whether or
// not the rows would follow.
const listsSettled = () =>
  act(async () => {
    await mockListKeys.mock.results[mockListKeys.mock.results.length - 1]?.value;
    await mockListNodeKeys.mock.results[mockListNodeKeys.mock.results.length - 1]?.value;
  });

beforeEach(() => {
  mockUser = { ...SIGNED_IN };
  mockSharedGuest = false;
  mockAuthOn = true;
  mockLlmEditable = true;
  mockKeyRows = [HF_ROW(), SOCRATA_ROW()];
  mockKeys = [];
  jest.clearAllMocks();
  mockUpdate.mockResolvedValue(undefined);
});

describe("API keys", () => {
  it("is the first tab, with the list's kinds in one table", async () => {
    mockKeyRows = [HF_ROW({ present: true }), SOCRATA_ROW()];
    mockKeys = [{ name: "census", host: "api.census.gov", delivery: "code", use: "", createdAt: 1, lastUsedAt: null }];
    open();
    expect(screen.getByRole("tab", { name: "API keys" })).toHaveAttribute("aria-selected", "true");
    const table = await screen.findByRole("table");
    expect(within(table).getAllByRole("columnheader").map((h) => h.textContent)).toEqual([
      "Name", "Kind", "Details", "Key", "Actions",
    ]);
    await waitFor(() => expect(table).toHaveTextContent("census"));
    expect(await rowOf("Hugging Face token")).toHaveTextContent("Data source");
    expect(await rowOf("census")).toHaveTextContent("Node code");
  });

  it("offers no provider form of its own", async () => {
    open();
    await listsSettled();
    // The single-provider form is gone: an API key and a model belong to a
    // language model configuration.
    expect(document.querySelector("#api-settings-api-key")).toBeNull();
    expect(document.querySelector("#api-settings-model")).toBeNull();
    expect(screen.queryByText(/answers every AI surface/)).toBeNull();
  });

  it("Add configuration offers a language model, every data source without a key, and a key for node code", async () => {
    mockKeyRows = [HF_ROW({ present: true }), SOCRATA_ROW(), MAPILLARY_ROW()];
    open();
    fireEvent.click(await screen.findByRole("button", { name: "Add configuration" }));
    expect(kindValues()).toEqual(["llm", "source:socrata.app-token", "source:mapillary.token", "node"]);
  });

  it("evaluation and model training are gone", async () => {
    open();
    await listsSettled();
    expect(screen.queryByText("Evaluation mode")).toBeNull();
    expect(screen.queryByText("Model training")).toBeNull();
  });
});

describe("a data source key: the Hugging Face token", () => {
  it("is a masked field with its own Save, disabled until something is typed", async () => {
    open();
    await addKind("source:huggingface.token");
    const hf = field(HF_ID)!;
    expect(hf.type).toBe("password");
    expect(hf.placeholder).toBe("hf_...");
    expect(hf).toHaveFocus();
    const save = within(screen.getByTestId("source-key-editor")).getByRole("button", { name: "Save" });
    expect(save).toBeDisabled();
    fireEvent.change(hf, { target: { value: "hf_abc" } });
    expect(save).toBeEnabled();
  });

  it("says a token is saved without ever showing it", async () => {
    mockKeyRows = [HF_ROW({ present: true }), SOCRATA_ROW()];
    open();
    expect(await rowOf("Hugging Face token")).toHaveTextContent("saved");
    fireEvent.click(screen.getByRole("button", { name: "Replace Hugging Face token" }));
    expect(field(HF_ID)!.value).toBe("");
    expect(field(HF_ID)!.placeholder).toContain("unchanged");
  });

  it("saves only what was typed", async () => {
    open();
    await addKind("source:huggingface.token");
    fireEvent.change(field(HF_ID)!, { target: { value: "hf_abc" } });
    fireEvent.click(within(screen.getByTestId("source-key-editor")).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(mockUpdate).toHaveBeenCalledWith({ huggingface_token: "hf_abc" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Saved the Hugging Face token.");
    expect(screen.queryByTestId("source-key-editor")).toBeNull();
  });

  it("removing it asks first, then clears it", async () => {
    mockKeyRows = [HF_ROW({ present: true }), SOCRATA_ROW()];
    open();
    await rowOf("Hugging Face token");
    fireEvent.click(screen.getByRole("button", { name: "Remove Hugging Face token" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Remove the saved Hugging Face token?");
    fireEvent.click(screen.getByRole("button", { name: "Confirm removing Hugging Face token" }));
    await waitFor(() => expect(mockUpdate).toHaveBeenCalledWith({ huggingface_token: "" }));
  });

  it("is not offered to a guest on a Curio with sign-in", async () => {
    mockUser = { is_guest: true };
    mockSharedGuest = true;
    mockLlmEditable = false;
    open();
    expect(await screen.findByText("Personal keys cannot be saved on a shared guest account.")).toBeInTheDocument();
    await listsSettled();
    expect(mockListKeys).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Add configuration" })).toBeNull();
    expect(field(HF_ID)).toBeNull();
  });

  it("the local guest saves its own, and is told the account is shared", async () => {
    // Without --deploy the shared guest is the one local user, and API Settings
    // is the only place a Hugging Face token is set.
    mockUser = { is_guest: true };
    mockSharedGuest = true;
    mockAuthOn = false;
    open();
    expect(screen.getByRole("note")).toHaveTextContent(/keys saved here are shared too/);
    await addKind("source:huggingface.token");
    fireEvent.change(field(HF_ID)!, { target: { value: "hf_local" } });
    fireEvent.click(within(screen.getByTestId("source-key-editor")).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(mockUpdate).toHaveBeenCalledWith({ huggingface_token: "hf_local" }));
  });
});

describe("a key for node code (dev/116)", () => {
  const CENSUS = {
    name: "census", host: "api.census.gov", delivery: "query:key",
    use: 'api_key = curio_secret("census")', createdAt: 1, lastUsedAt: null,
  };

  beforeEach(() => {
    mockPut.mockReset();
    mockRemove.mockReset();
  });

  it("lists refs only, never a value, and the key field is masked and write-only", async () => {
    mockKeys = [CENSUS];
    open();
    const row = await rowOf("census");
    expect(row).toHaveTextContent("api.census.gov");
    expect(row).toHaveTextContent('query parameter "key"');
    expect(row).toHaveTextContent("never used");
    await addKind("node");
    const value = screen.getByLabelText("Key") as HTMLInputElement;
    expect(value.type).toBe("password");
    expect(value.autocomplete).toBe("new-password");
    expect(value.value).toBe("");
    expect(screen.getByText(/never appears in your dataflow, proposals or chat/)).toBeInTheDocument();
  });

  it("a card's request opens the form with the host filled and a name suggested", async () => {
    open({ section: "connection-keys", host: "api.census.gov", suggestedName: "census" });
    const editor = await screen.findByTestId("node-key-editor");
    expect(kindSelect().value).toBe("node");
    expect((within(editor).getByLabelText("Host") as HTMLInputElement).value).toBe("api.census.gov");
    expect((within(editor).getByLabelText("Name") as HTMLInputElement).value).toBe("census");
    await waitFor(() => expect(within(editor).getByLabelText("Name")).toHaveFocus());
  });

  it("saving sends host, value and delivery, then closes the form and shows the use line", async () => {
    mockPut.mockResolvedValue({ key: CENSUS });
    open({ section: "connection-keys", host: "api.census.gov" });
    await screen.findByTestId("node-key-editor");
    fireEvent.change(screen.getByLabelText("Sent as"), { target: { value: "query" } });
    fireEvent.change(screen.getByLabelText("Parameter name"), { target: { value: "key" } });
    fireEvent.change(screen.getByLabelText("Key"), { target: { value: "s3cr3t-value" } });
    fireEvent.click(screen.getByRole("button", { name: "Save key" }));
    await waitFor(() => expect(mockPut).toHaveBeenCalledWith("census", { host: "api.census.gov", value: "s3cr3t-value", delivery: "query:key" }));
    expect(await screen.findByRole("status")).toHaveTextContent('Use it in node code as api_key = curio_secret("census")');
    expect(screen.queryByTestId("node-key-editor")).toBeNull();
    expect(await rowOf("census")).toHaveTextContent("Node code");
  });

  it("a 409 offers to replace the host binding; remove asks first and names the consequence", async () => {
    mockKeys = [CENSUS];
    const conflict = Object.assign(new Error("'census' is saved for api.census.gov; pass replace to bind it to other.gov"), { status: 409 });
    mockPut.mockRejectedValueOnce(conflict).mockResolvedValueOnce({ key: { ...CENSUS, host: "other.gov" } });
    mockRemove.mockResolvedValue({ deleted: "census" });
    open({ section: "connection-keys", host: "other.gov", suggestedName: "census" });
    await screen.findByTestId("node-key-editor");
    fireEvent.change(screen.getByLabelText("Key"), { target: { value: "s3cr3t-value" } });
    fireEvent.click(screen.getByRole("button", { name: "Save key" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/pass replace/));
    fireEvent.change(screen.getByLabelText("Key"), { target: { value: "s3cr3t-value" } });
    fireEvent.click(screen.getByRole("button", { name: "Replace the host binding" }));
    await waitFor(() => expect(mockPut).toHaveBeenLastCalledWith("census", expect.objectContaining({ replace: true, host: "other.gov" })));
    // Remove: a confirmation with the consequence, then the call.
    await waitFor(() => expect(screen.queryByTestId("node-key-editor")).toBeNull());
    fireEvent.click(await screen.findByRole("button", { name: "Remove census" }));
    expect(screen.getByRole("alert")).toHaveTextContent('Nodes that call curio_secret("census") will fail until a key with this name is saved again.');
    fireEvent.click(screen.getByRole("button", { name: "Confirm removing census" }));
    await waitFor(() => expect(mockRemove).toHaveBeenCalledWith("census"));
    await waitFor(() => expect(screen.queryByText("census", { selector: "td" })).toBeNull());
  });

  it("Replace keeps the name and the host, and asks for the key again", async () => {
    mockKeys = [CENSUS];
    mockPut.mockResolvedValue({ key: CENSUS });
    open();
    await rowOf("census");
    fireEvent.click(screen.getByRole("button", { name: "Replace census" }));
    const editor = within(screen.getByTestId("node-key-editor"));
    expect(editor.getByRole("heading", { name: "Replace census" })).toBeInTheDocument();
    expect((editor.getByLabelText("Name") as HTMLInputElement).readOnly).toBe(true);
    expect((editor.getByLabelText("Host") as HTMLInputElement).value).toBe("api.census.gov");
    expect((editor.getByLabelText("Parameter name") as HTMLInputElement).value).toBe("key");
    await waitFor(() => expect(editor.getByLabelText("Key")).toHaveFocus());
    fireEvent.change(editor.getByLabelText("Key"), { target: { value: "n3w" } });
    fireEvent.click(editor.getByRole("button", { name: "Save key" }));
    await waitFor(() => expect(mockPut).toHaveBeenCalledWith("census", { host: "api.census.gov", value: "n3w", delivery: "query:key" }));
  });

  it("on a Curio with sign-in, neither a temporary guest nor the shared guest can add one", async () => {
    mockUser = { ...SIGNED_IN, is_guest: true };
    mockLlmEditable = false;
    const { unmount } = open({ section: "connection-keys", host: "api.census.gov" });
    await listsSettled();
    expect(screen.queryByTestId("node-key-editor")).toBeNull();
    expect(mockListNodeKeys).not.toHaveBeenCalled();
    unmount();
    // The shared guest is every guest at once: the server neither saves nor
    // sends its keys.
    mockSharedGuest = true;
    open();
    expect(await screen.findByText("Personal keys cannot be saved on a shared guest account.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add configuration" })).toBeNull();
  });

  it("without --deploy the shared guest can add one, under the sharing note", async () => {
    mockUser = { ...SIGNED_IN, is_guest: true };
    mockSharedGuest = true;
    mockAuthOn = false;
    open();
    expect(screen.getByRole("note")).toHaveTextContent("Everyone using this Curio shares this account, so keys saved here are shared too.");
    await addKind("node");
    expect(screen.getByTestId("node-key-editor")).toBeInTheDocument();
  });
});

describe("a data source key: the Socrata app token", () => {
  /**
   * A key that is not about AI at all: the Discovery Catalog sends it to
   * Socrata portals. It lives here because this is the account's one keys
   * surface.
   *
   * It follows the same rules as the Hugging Face token: stored on the user's
   * row, reported as a boolean, blank means keep, and there is an explicit way
   * to remove it.
   */
  it("is offered, and marked optional when none is saved", async () => {
    open();
    await addKind("source:socrata.app-token");
    expect(field(SOCRATA_ID)!.type).toBe("password");
    // Scoped to the label: the "Get a Socrata app token" link repeats the
    // words, and matching either would not prove the field is labelled.
    expect(labelOf(SOCRATA_ID)).toContain("Socrata app token");
    expect(labelOf(SOCRATA_ID)).toContain("(optional)");
    expect(screen.getByRole("link", { name: /Get a Socrata app token/ })).toHaveAttribute(
      "href", "https://evergreen.data.socrata.com/signup",
    );
  });

  it("says a token is saved without ever showing it", async () => {
    mockKeyRows = [HF_ROW(), SOCRATA_ROW({ present: true })];
    open();
    await rowOf("Socrata app token");
    fireEvent.click(screen.getByRole("button", { name: "Replace Socrata app token" }));
    expect(labelOf(SOCRATA_ID)).toContain("(saved - leave blank to keep)");
    expect(field(SOCRATA_ID)!.value).toBe("");
    expect(field(SOCRATA_ID)!.placeholder).toContain("unchanged");
  });

  it("saves what was typed", async () => {
    open();
    await addKind("source:socrata.app-token");
    fireEvent.change(field(SOCRATA_ID)!, { target: { value: "tok-123" } });
    fireEvent.click(within(screen.getByTestId("source-key-editor")).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(mockUpdate).toHaveBeenCalledWith({ socrata_app_token: "tok-123" }));
  });

  it("leaves a saved token alone when another key is saved", async () => {
    // Blank means keep: saving the Hugging Face token must not touch it.
    mockKeyRows = [HF_ROW(), SOCRATA_ROW({ present: true })];
    open();
    await addKind("source:huggingface.token");
    fireEvent.change(field(HF_ID)!, { target: { value: "hf_abc" } });
    fireEvent.click(within(screen.getByTestId("source-key-editor")).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(mockUpdate).toHaveBeenCalled());
    expect(mockUpdate.mock.calls[0][0]).toEqual({ huggingface_token: "hf_abc" });
  });

  it("offers a way to remove one, which is how blank-means-keep stays escapable", async () => {
    mockKeyRows = [HF_ROW(), SOCRATA_ROW({ present: true })];
    open();
    await rowOf("Socrata app token");
    fireEvent.click(screen.getByRole("button", { name: "Remove Socrata app token" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm removing Socrata app token" }));
    await waitFor(() => expect(mockUpdate).toHaveBeenCalledWith({ socrata_app_token: "" }));
    // The Socrata token is the one cleared, not the Hugging Face one.
    expect(mockUpdate).toHaveBeenCalledTimes(1);
  });

  it("is not offered to a guest", async () => {
    // A guest account is shared, so a personal credential saved on it would be
    // everyone's. The backend refuses it too.
    mockUser = { is_guest: true };
    open();
    await listsSettled();
    // What this guest may add, if anything, is a language model alone.
    fireEvent.click(await screen.findByRole("button", { name: "Add configuration" }));
    expect(kindValues()).toEqual(["llm"]);
    expect(field(SOCRATA_ID)).toBeNull();
  });
});

describe("a deployment-supplied portal token", () => {
  /**
   * A user who sets nothing uses what the operator configured, and setting
   * their own overrides it. An operator running Curio for a class raises the
   * rate limit for everyone with one environment variable.
   */
  it("says the box is optional when nothing is configured", async () => {
    mockKeyRows = [HF_ROW(), SOCRATA_ROW({ inherited: false })];
    open();
    await addKind("source:socrata.app-token");
    expect(labelOf(SOCRATA_ID)).toContain("(optional)");
  });

  it("is listed as this Curio's, and overriding it says it is inherited", async () => {
    // "(optional)" would be misleading: leaving the box blank already
    // authenticates you.
    mockKeyRows = [HF_ROW(), SOCRATA_ROW({ inherited: true })];
    open();
    expect(await rowOf("Socrata app token")).toHaveTextContent("set by this Curio");
    expect(screen.queryByRole("button", { name: "Remove Socrata app token" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Override Socrata app token" }));
    expect(labelOf(SOCRATA_ID)).toContain("inherited");
    expect(screen.getByText(/Leave this blank to use it/)).toBeInTheDocument();
  });

  it("a token you saved yourself takes precedence in the copy", async () => {
    mockKeyRows = [HF_ROW(), SOCRATA_ROW({ present: true, inherited: true })];
    open();
    expect(await rowOf("Socrata app token")).toHaveTextContent("saved");
    fireEvent.click(screen.getByRole("button", { name: "Replace Socrata app token" }));
    expect(labelOf(SOCRATA_ID)).toContain("saved");
    expect(labelOf(SOCRATA_ID)).not.toContain("inherited");
  });

  it("an unreadable key list reports nothing rather than claiming inheritance", async () => {
    mockListKeys.mockRejectedValueOnce(new Error("offline"));
    open();
    expect(await screen.findByText("offline")).toBeInTheDocument();
    expect(screen.queryByText(/inherited/)).toBeNull();
    fireEvent.click(await screen.findByRole("button", { name: "Add configuration" }));
    expect(kindValues()).toEqual(["llm", "node"]);
  });
});

describe("the Discovery Catalog's keys", () => {
  it("offers every key the server lists, including one this screen has never heard of", async () => {
    mockKeyRows = [HF_ROW(), MAPILLARY_ROW()];
    open();
    await addKind("source:mapillary.token");
    const mapillary = field("#api-settings-key-mapillary-token")!;
    expect(screen.getByTestId("source-key-editor").querySelector('[data-key-slot="mapillary.token"]')).not.toBeNull();
    fireEvent.change(mapillary, { target: { value: "MLY|abc" } });
    fireEvent.click(within(screen.getByTestId("source-key-editor")).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(mockUpdate).toHaveBeenCalledWith({ mapillary_access_token: "MLY|abc" }));
  });

  it("says which sources send each key, in the form and in the list", async () => {
    mockKeyRows = [HF_ROW({ present: true }), SOCRATA_ROW()];
    open();
    expect(await rowOf("Hugging Face token")).toHaveTextContent(
      "Used by Hugging Face documentation images and Hugging Face models.",
    );
    await addKind("source:socrata.app-token");
    expect(screen.getByText(/Used by City of Chicago Data Portal\./)).toBeInTheDocument();
  });

  it("a source's key link opens on that key's field", async () => {
    open({ section: "source-key", slot: "socrata.app-token" });
    await waitFor(() => expect(field(SOCRATA_ID)).toHaveFocus());
    expect(kindSelect().value).toBe("source:socrata.app-token");
  });

  it("a source's key link to a saved key opens its Replace form", async () => {
    mockKeyRows = [HF_ROW(), SOCRATA_ROW({ present: true })];
    open({ section: "source-key", slot: "socrata.app-token" });
    await waitFor(() => expect(field(SOCRATA_ID)).toHaveFocus());
    expect(screen.getByRole("heading", { name: "Replace Socrata app token" })).toBeInTheDocument();
  });

  // The Discovery Catalog's cards and source pages read whether a key is set,
  // so they hear when one is saved or removed (#626).
  it("tells the Discovery Catalog once a key is saved", async () => {
    open();
    await addKind("source:socrata.app-token");
    fireEvent.change(field(SOCRATA_ID)!, { target: { value: "tok-123" } });
    fireEvent.click(within(screen.getByTestId("source-key-editor")).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(mockNotifyRefresh).toHaveBeenCalledTimes(1));
    expect(mockUpdate).toHaveBeenCalledWith({ socrata_app_token: "tok-123" });
    expect(mockUpdate.mock.invocationCallOrder[0]).toBeLessThan(mockNotifyRefresh.mock.invocationCallOrder[0]);
  });

  it("tells the Discovery Catalog once a key is removed", async () => {
    mockKeyRows = [HF_ROW(), SOCRATA_ROW({ present: true })];
    open();
    await rowOf("Socrata app token");
    fireEvent.click(screen.getByRole("button", { name: "Remove Socrata app token" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm removing Socrata app token" }));
    await waitFor(() => expect(mockNotifyRefresh).toHaveBeenCalledTimes(1));
    expect(mockUpdate).toHaveBeenCalledWith({ socrata_app_token: "" });
    expect(mockUpdate.mock.invocationCallOrder[0]).toBeLessThan(mockNotifyRefresh.mock.invocationCallOrder[0]);
  });

  it("a save that fails tells the Discovery Catalog nothing", async () => {
    mockUpdate.mockRejectedValueOnce(new Error("refused"));
    open();
    await addKind("source:socrata.app-token");
    fireEvent.change(field(SOCRATA_ID)!, { target: { value: "tok-123" } });
    fireEvent.click(within(screen.getByTestId("source-key-editor")).getByRole("button", { name: "Save" }));
    expect(await within(screen.getByTestId("source-key-editor")).findByText("refused")).toBeInTheDocument();
    expect(mockNotifyRefresh).not.toHaveBeenCalled();
  });
});
