import React from "react";
import { render, screen, waitFor, fireEvent, within } from "@testing-library/react";

/**
 * API Settings is the account's keys screen, in two parts. The Agent Catalog's:
 * its LLM configurations (tested in llmConfigsSection.test.tsx) and the
 * connection keys a node reaches by name. The Discovery Catalog's: one row per
 * key a source can send (the HuggingFace and Socrata tokens among them), drawn
 * from the server's list. Each key row has a Save of its own; nothing here
 * saves a model or an LLM key.
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

// The LLM configurations section fetches its listing; a minimal one keeps it
// quiet here.
jest.mock("../../api/llmConfigsApi", () => ({
  llmConfigsApi: {
    listing: jest.fn(() =>
      Promise.resolve({
        configs: [],
        default: null,
        deployment: { label: "Deployment default", endpointOffered: false, apiType: null, baseUrlHost: null, model: null },
        active: { source: null, error: "No LLM configuration answers this run." },
        editable: true,
        reason: null,
        shared: false,
        maxConfigs: 32,
      }),
    ),
  },
}));

// dev/116: the Connection keys section lives in this modal; its client is
// mocked so the suite never fetches, and a mutable list drives the table.
let mockKeys: Array<Record<string, unknown>> = [];
const mockPut = jest.fn();
const mockRemove = jest.fn();
jest.mock("../../api/connectionKeysApi", () => ({
  connectionKeysApi: {
    list: jest.fn(() => Promise.resolve({ keys: mockKeys })),
    put: (...args: unknown[]) => mockPut(...args),
    remove: (...args: unknown[]) => mockRemove(...args),
    suggestName: jest.fn(() => Promise.resolve({ name: "census" })),
  },
}));

// The Discovery Catalog's key rows, as `GET /api/discovery/keys` lists them.
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
let mockKeyRows: Row[] = [];
const mockListKeys = jest.fn(() => Promise.resolve({ keys: mockKeyRows }));
jest.mock("../../services/discoveryCatalog", () => {
  const actual = jest.requireActual("../../services/discoveryCatalog");
  return {
    ...actual,
    discoveryCatalogApi: { ...actual.discoveryCatalogApi, listKeys: () => mockListKeys() },
  };
});

import ApiSettingsModal from "../../components/ApiSettingsModal";

const open = () => render(<ApiSettingsModal isOpen onClose={jest.fn()} />);
const keysSection = () => within(screen.getByTestId("connection-keys-section"));
const HF_ID = "#api-settings-key-huggingface-token";
const SOCRATA_ID = "#api-settings-key-socrata-app-token";
const rowOf = (slot: string) => within(document.querySelector(`[data-key-slot="${slot}"]`) as HTMLElement);
// The rows arrive with the key list, so a test that starts from one waits for it.
const findRow = async (slot: string) =>
  within(
    await waitFor(() => {
      const el = document.querySelector(`[data-key-slot="${slot}"]`) as HTMLElement | null;
      expect(el).not.toBeNull();
      return el as HTMLElement;
    }),
  );

beforeEach(() => {
  mockUser = { ...SIGNED_IN };
  mockSharedGuest = false;
  mockAuthOn = true;
  mockKeyRows = [HF_ROW(), SOCRATA_ROW()];
  jest.clearAllMocks();
});

describe("API Settings", () => {
  it("renders its title and the LLM configurations first", async () => {
    open();
    expect(screen.getByRole("heading", { name: "API Settings" })).toBeInTheDocument();
    expect(await screen.findByTestId("llm-configs-section")).toBeInTheDocument();
  });

  it("offers no provider form of its own", () => {
    open();
    // The single-provider form is gone: an API key and a model belong to a
    // configuration, edited in the section above.
    expect(document.querySelector("#api-settings-api-key")).toBeNull();
    expect(document.querySelector("#api-settings-model")).toBeNull();
    expect(screen.queryByText(/answers every AI surface/)).toBeNull();
  });

  it("renders nothing when closed", () => {
    const { container } = render(<ApiSettingsModal isOpen={false} onClose={jest.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("groups its keys by the catalog that uses them", async () => {
    open();
    expect(screen.getByRole("heading", { name: "Agent Catalog" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Discovery Catalog" })).toBeInTheDocument();
  });
});

describe("API Settings: the HuggingFace token", () => {
  const field = () => document.querySelector(HF_ID) as HTMLInputElement;

  it("is a masked field with its own Save, disabled until something is typed", async () => {
    open();
    await waitFor(() => expect(field()).not.toBeNull());
    expect(field().type).toBe("password");
    expect(field().placeholder).toBe("hf_...");
    const save = rowOf("huggingface.token").getByRole("button", { name: "Save" });
    expect(save).toBeDisabled();
    fireEvent.change(field(), { target: { value: "hf_abc" } });
    expect(save).toBeEnabled();
  });

  it("says a token is saved without ever showing it", async () => {
    mockKeyRows = [HF_ROW({ present: true }), SOCRATA_ROW()];
    open();
    await waitFor(() => expect(field()).not.toBeNull());
    expect(field().value).toBe("");
    expect(field().placeholder).toContain("unchanged");
  });

  it("saves only what was typed", async () => {
    open();
    await waitFor(() => expect(field()).not.toBeNull());
    fireEvent.change(field(), { target: { value: "hf_abc" } });
    fireEvent.click(rowOf("huggingface.token").getByRole("button", { name: "Save" }));
    await waitFor(() => expect(mockUpdate).toHaveBeenCalledWith({ huggingface_token: "hf_abc" }));
    expect(await rowOf("huggingface.token").findByText("Saved.")).toBeInTheDocument();
  });

  it("removing it clears the HuggingFace box", async () => {
    mockKeyRows = [HF_ROW({ present: true }), SOCRATA_ROW()];
    open();
    fireEvent.click(await (await findRow("huggingface.token")).findByRole("button", { name: "Remove saved key" }));
    await waitFor(() => expect(mockUpdate).toHaveBeenCalledWith({ huggingface_token: "" }));
  });

  it("is not offered to a guest on a Curio with sign-in", () => {
    mockUser = { is_guest: true };
    mockSharedGuest = true;
    open();
    expect(field()).toBeNull();
    expect(screen.getByText("Personal keys cannot be saved on a shared guest account.")).toBeInTheDocument();
  });

  it("the local guest saves its own, and is told the account is shared", async () => {
    // Without --deploy the shared guest is the one local user, and API Settings
    // is the only place a HuggingFace token is set.
    mockUser = { is_guest: true };
    mockSharedGuest = true;
    mockAuthOn = false;
    open();
    expect(screen.getByText(/keys saved here are shared too/)).toBeInTheDocument();
    await waitFor(() => expect(field()).not.toBeNull());
    fireEvent.change(field(), { target: { value: "hf_local" } });
    fireEvent.click(rowOf("huggingface.token").getByRole("button", { name: "Save" }));
    await waitFor(() => expect(mockUpdate).toHaveBeenCalledWith({ huggingface_token: "hf_local" }));
    // The panels that run on the account's models stay off for a guest.
    expect(screen.queryByText("Evaluation mode")).toBeNull();
  });
});

describe("API Settings: Connection keys (dev/116)", () => {
  const CENSUS = {
    name: "census", host: "api.census.gov", delivery: "query:key",
    use: 'api_key = curio_secret("census")', createdAt: 1, lastUsedAt: null,
  };

  beforeEach(() => {
    mockUser = { ...SIGNED_IN };
    mockKeys = [];
    mockPut.mockReset();
    mockRemove.mockReset();
  });

  it("is a collapsed section with the count; nothing of it joins the form until opened", async () => {
    mockKeys = [CENSUS];
    open();
    const section = screen.getByTestId("connection-keys-section");
    await waitFor(() => expect(section).toHaveTextContent("Connection keys (1)"));
    expect(section).not.toHaveAttribute("open");
    expect(screen.queryByRole("button", { name: "Save key" })).toBeNull();
    // While collapsed, the only Save buttons are the source keys' own, one per row.
    await waitFor(() => expect(document.querySelector(HF_ID)).not.toBeNull());
    expect(screen.getAllByRole("button", { name: /save/i })).toHaveLength(mockKeyRows.length);
  });

  it("lists refs only — never a value — and the key field is masked and write-only", async () => {
    mockKeys = [CENSUS];
    open();
    fireEvent.click(await screen.findByText(/^Connection keys/));
    const table = await keysSection().findByRole("table");
    expect(table).toHaveTextContent("census");
    expect(table).toHaveTextContent("api.census.gov");
    expect(table).toHaveTextContent('query parameter "key"');
    expect(table).toHaveTextContent("never used");
    const value = screen.getByLabelText("Key") as HTMLInputElement;
    expect(value.type).toBe("password");
    expect(value.autocomplete).toBe("new-password");
    expect(value.value).toBe("");
    expect(screen.getByText(/never appears in your dataflow, proposals or chat/)).toBeInTheDocument();
  });

  it("a focus from a card opens the section with the host filled and a name suggested", async () => {
    render(<ApiSettingsModal isOpen onClose={jest.fn()} focus={{ section: "connection-keys", host: "api.census.gov", suggestedName: "census" }} />);
    expect(screen.getByTestId("connection-keys-section")).toHaveAttribute("open");
    expect((screen.getByLabelText("Host") as HTMLInputElement).value).toBe("api.census.gov");
    expect((screen.getByLabelText("Name") as HTMLInputElement).value).toBe("census");
    await waitFor(() => expect(screen.getByLabelText("Name")).toHaveFocus());
  });

  it("saving sends host, value and delivery, then clears the key field and shows the use line", async () => {
    mockPut.mockResolvedValue({ key: CENSUS });
    render(<ApiSettingsModal isOpen onClose={jest.fn()} focus={{ section: "connection-keys", host: "api.census.gov" }} />);
    fireEvent.change(screen.getByLabelText("Sent as"), { target: { value: "query" } });
    fireEvent.change(screen.getByLabelText("Parameter name"), { target: { value: "key" } });
    fireEvent.change(screen.getByLabelText("Key"), { target: { value: "s3cr3t-value" } });
    fireEvent.click(screen.getByRole("button", { name: "Save key" }));
    await waitFor(() => expect(mockPut).toHaveBeenCalledWith("census", { host: "api.census.gov", value: "s3cr3t-value", delivery: "query:key" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent('Use it in node code as api_key = curio_secret("census")'));
    expect((screen.getByLabelText("Key") as HTMLInputElement).value).toBe("");
    expect(keysSection().getByRole("table")).toHaveTextContent("census");
  });

  it("a 409 offers to replace the host binding; remove asks first and names the consequence", async () => {
    mockKeys = [CENSUS];
    const conflict = Object.assign(new Error("'census' is saved for api.census.gov; pass replace to bind it to other.gov"), { status: 409 });
    mockPut.mockRejectedValueOnce(conflict).mockResolvedValueOnce({ key: { ...CENSUS, host: "other.gov" } });
    mockRemove.mockResolvedValue({ deleted: "census" });
    render(<ApiSettingsModal isOpen onClose={jest.fn()} focus={{ section: "connection-keys", host: "other.gov", suggestedName: "census" }} />);
    fireEvent.change(screen.getByLabelText("Key"), { target: { value: "s3cr3t-value" } });
    fireEvent.click(screen.getByRole("button", { name: "Save key" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/pass replace/));
    fireEvent.change(screen.getByLabelText("Key"), { target: { value: "s3cr3t-value" } });
    fireEvent.click(screen.getByRole("button", { name: "Replace the host binding" }));
    await waitFor(() => expect(mockPut).toHaveBeenLastCalledWith("census", expect.objectContaining({ replace: true, host: "other.gov" })));
    // Remove: a confirmation with the consequence, then the call.
    fireEvent.click(await screen.findByRole("button", { name: "Remove census" }));
    expect(screen.getByRole("alert")).toHaveTextContent('Nodes that call curio_secret("census") will fail until a key with this name is saved again.');
    fireEvent.click(screen.getByRole("button", { name: "Confirm removing census" }));
    await waitFor(() => expect(mockRemove).toHaveBeenCalledWith("census"));
    await waitFor(() => expect(keysSection().queryByRole("table")).toBeNull());
  });

  it("a temporary guest sees no key form; the shared guest sees it with the sharing banner", async () => {
    mockUser = { ...SIGNED_IN, is_guest: true };
    const { unmount } = open();
    expect(screen.queryByTestId("connection-keys-section")).toBeNull();
    unmount();
    mockSharedGuest = true;
    open();
    expect(screen.getByTestId("connection-keys-section")).toBeInTheDocument();
  });
});

describe("API Settings: the data-portal token", () => {
  /**
   * A key that is not about AI at all: the Discovery Catalog sends it to
   * Socrata portals. It lives here because this is the account's one keys
   * surface.
   *
   * It follows the same rules as the HuggingFace token beside it: stored on
   * the user's row, reported as a boolean, blank means keep, and there is an
   * explicit way to remove it.
   */
  const field = () => document.querySelector(SOCRATA_ID) as HTMLInputElement;
  const label = () => document.querySelector(`label[for="${SOCRATA_ID.slice(1)}"]`);

  it("is offered, and marked optional when none is saved", async () => {
    open();
    await waitFor(() => expect(field()).toBeInTheDocument());
    expect(field().type).toBe("password");
    // Scoped to the label: the "Get a Socrata app token" link repeats the
    // words, and matching either would not prove the field is labelled.
    expect(label()).toBeInTheDocument();
    expect(label()!.textContent).toContain("(optional)");
  });

  it("says a token is saved without ever showing it", async () => {
    mockKeyRows = [HF_ROW(), SOCRATA_ROW({ present: true })];
    open();
    expect(await screen.findByText(/\(saved - leave blank to keep\)/)).toBeInTheDocument();
    expect(field().value).toBe("");
    expect(field().placeholder).toContain("unchanged");
  });

  it("saves what was typed", async () => {
    open();
    await waitFor(() => expect(field()).not.toBeNull());
    fireEvent.change(field(), { target: { value: "tok-123" } });
    fireEvent.click(rowOf("socrata.app-token").getByRole("button", { name: "Save" }));
    await waitFor(() => expect(mockUpdate).toHaveBeenCalledWith({ socrata_app_token: "tok-123" }));
  });

  it("leaves a saved token alone when the box is blank", async () => {
    // Blank means keep: saving the HuggingFace token must not touch it.
    mockKeyRows = [HF_ROW(), SOCRATA_ROW({ present: true })];
    open();
    await waitFor(() => expect(document.querySelector(HF_ID)).not.toBeNull());
    fireEvent.change(document.querySelector(HF_ID) as HTMLInputElement, { target: { value: "hf_abc" } });
    fireEvent.click(rowOf("huggingface.token").getByRole("button", { name: "Save" }));
    await waitFor(() => expect(mockUpdate).toHaveBeenCalled());
    expect(mockUpdate.mock.calls[0][0]).not.toHaveProperty("socrata_app_token");
  });

  it("offers a way to remove one, which is how blank-means-keep stays escapable", async () => {
    mockKeyRows = [HF_ROW(), SOCRATA_ROW({ present: true })];
    open();
    const remove = await (await findRow("socrata.app-token")).findByRole("button", { name: "Remove saved key" });
    fireEvent.change(field(), { target: { value: "typed-but-unsaved" } });
    fireEvent.click(remove);
    await waitFor(() => expect(mockUpdate).toHaveBeenCalledWith({ socrata_app_token: "" }));
    // The Socrata box is the one cleared, not the HuggingFace one.
    await waitFor(() => expect(field().value).toBe(""));
  });

  it("is not offered to a guest", () => {
    // A guest account is shared, so a personal credential saved on it would be
    // everyone's. The backend refuses it too.
    mockUser = { is_guest: true };
    open();
    expect(field()).toBeNull();
  });
});

describe("API Settings: a deployment-supplied portal token", () => {
  /**
   * A user who sets nothing uses what the operator configured, and setting
   * their own overrides it. An operator running Curio for a class raises the
   * rate limit for everyone with one environment variable.
   */
  const label = () =>
    document.querySelector(`label[for="${SOCRATA_ID.slice(1)}"]`)?.textContent ?? "";

  it("says the box is optional when nothing is configured", async () => {
    mockKeyRows = [HF_ROW(), SOCRATA_ROW({ inherited: false })];
    open();
    await waitFor(() => expect(label()).toContain("(optional)"));
  });

  it("says it is inherited when the install supplies one", async () => {
    // "(optional)" would be misleading: leaving the box blank already
    // authenticates you.
    mockKeyRows = [HF_ROW(), SOCRATA_ROW({ inherited: true })];
    open();
    await waitFor(() => expect(label()).toContain("inherited"));
    expect(screen.getByText(/Leave this blank to use it/)).toBeInTheDocument();
  });

  it("a token you saved yourself takes precedence in the copy", async () => {
    mockKeyRows = [HF_ROW(), SOCRATA_ROW({ present: true, inherited: true })];
    open();
    await waitFor(() => expect(label()).toContain("saved"));
    expect(label()).not.toContain("inherited");
  });

  it("an unreadable key list reports nothing rather than claiming inheritance", async () => {
    mockListKeys.mockRejectedValueOnce(new Error("offline"));
    open();
    expect(await screen.findByText("offline")).toBeInTheDocument();
    expect(screen.queryByText(/inherited/)).toBeNull();
    expect(document.querySelector(SOCRATA_ID)).toBeNull();
  });
});

describe("API Settings: the Discovery Catalog's keys", () => {
  it("draws a row for every key the server lists, including one this screen has never heard of", async () => {
    mockKeyRows = [
      HF_ROW(),
      { slot: "mapillary.token", label: "Mapillary client token", field: "mapillary_access_token",
        helpUrl: "https://www.mapillary.com/dashboard/developers", placeholder: "MLY|...", note: null,
        present: false, inherited: false, sources: [{ name: "Mapillary", dirName: "source.mapillary.imagery@1" }] },
    ];
    open();
    const field = await waitFor(() => {
      const el = document.querySelector("#api-settings-key-mapillary-token") as HTMLInputElement;
      expect(el).not.toBeNull();
      return el;
    });
    fireEvent.change(field, { target: { value: "MLY|abc" } });
    fireEvent.click(rowOf("mapillary.token").getByRole("button", { name: "Save" }));
    await waitFor(() => expect(mockUpdate).toHaveBeenCalledWith({ mapillary_access_token: "MLY|abc" }));
  });

  it("says which sources send each key", async () => {
    open();
    expect(await (await findRow("socrata.app-token")).findByText(/Used by City of Chicago Data Portal\./)).toBeInTheDocument();
    expect(rowOf("huggingface.token").getByText(
      /Used by Hugging Face documentation images and Hugging Face models\./,
    )).toBeInTheDocument();
  });

  it("a source's key link opens on that key's row", async () => {
    render(<ApiSettingsModal isOpen onClose={jest.fn()} focus={{ section: "source-key", slot: "socrata.app-token" }} />);
    await waitFor(() => expect(document.querySelector(SOCRATA_ID)).toHaveFocus());
  });
});
