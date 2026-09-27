import React from "react";
import { render, screen, waitFor, fireEvent, within } from "@testing-library/react";

/**
 * AI Settings is the account's credentials screen: its LLM configurations
 * (tested in llmConfigsSection.test.tsx), the per-person HuggingFace and
 * Socrata tokens, and the connection keys a node reaches by name. The tokens
 * keep a Save of their own; nothing here saves a model or an LLM key.
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

// Spread requireActual rather than replacing the module: a partial mock that
// enumerates exports breaks the moment someone adds one. Only getPublicConfig
// is used by the modal.
let mockPublicConfig: Record<string, unknown> = {};
jest.mock("../../utils/authApi", () => ({
  ...jest.requireActual("../../utils/authApi"),
  authApi: {
    ...jest.requireActual("../../utils/authApi").authApi,
    getPublicConfig: jest.fn(() => Promise.resolve(mockPublicConfig)),
  },
}));

import AiSettingsModal from "../../components/AiSettingsModal";

const open = () => render(<AiSettingsModal isOpen onClose={jest.fn()} />);
const keysSection = () => within(screen.getByTestId("connection-keys-section"));
const saveTokens = () => screen.getByRole("button", { name: "Save tokens" });

beforeEach(() => {
  mockUser = { ...SIGNED_IN };
  mockSharedGuest = false;
  mockAuthOn = true;
  mockPublicConfig = {};
  jest.clearAllMocks();
});

describe("AI Settings", () => {
  it("renders its title and the LLM configurations first", async () => {
    open();
    expect(screen.getByRole("heading", { name: "AI Settings" })).toBeInTheDocument();
    expect(await screen.findByTestId("llm-configs-section")).toBeInTheDocument();
  });

  it("offers no provider form of its own", () => {
    open();
    // The single-provider form is gone: an API key and a model belong to a
    // configuration, edited in the section above.
    expect(document.querySelector("#ai-settings-api-key")).toBeNull();
    expect(document.querySelector("#ai-settings-model")).toBeNull();
    expect(screen.queryByText(/answers every AI surface/)).toBeNull();
  });

  it("renders nothing when closed", () => {
    const { container } = render(<AiSettingsModal isOpen={false} onClose={jest.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("AI Settings: the HuggingFace token", () => {
  const field = () => document.querySelector("#ai-settings-hf-token") as HTMLInputElement;

  it("is a masked field with its own Save, disabled until something is typed", () => {
    open();
    expect(field().type).toBe("password");
    expect(field().placeholder).toBe("hf_...");
    expect(saveTokens()).toBeDisabled();
  });

  it("says a token is saved without ever showing it", () => {
    mockUser = { ...SIGNED_IN, has_huggingface_token: true };
    open();
    expect(field().value).toBe("");
    expect(field().placeholder).toContain("unchanged");
  });

  it("saves only what was typed", async () => {
    open();
    fireEvent.change(field(), { target: { value: "hf_abc" } });
    fireEvent.click(saveTokens());
    await waitFor(() =>
      expect(mockUpdate).toHaveBeenCalledWith({ huggingfaceToken: "hf_abc", socrataAppToken: undefined }),
    );
    expect(await screen.findByText("Tokens saved.")).toBeInTheDocument();
  });

  it("removing it clears the HuggingFace box", async () => {
    mockUser = { ...SIGNED_IN, has_huggingface_token: true };
    open();
    fireEvent.click(screen.getAllByRole("button", { name: /Remove saved token/ })[0]);
    await waitFor(() => expect(mockUpdate).toHaveBeenCalledWith({ huggingfaceToken: "" }));
  });

  it("is not offered to a guest on a Curio with sign-in", () => {
    mockUser = { is_guest: true };
    mockSharedGuest = true;
    open();
    expect(field()).toBeNull();
    expect(screen.getByText("Personal tokens cannot be saved on a shared guest account.")).toBeInTheDocument();
  });

  it("the local guest saves its own, and is told the account is shared", async () => {
    // Without --deploy the shared guest is the one local user, and AI Settings
    // is the only place a HuggingFace token is set.
    mockUser = { is_guest: true };
    mockSharedGuest = true;
    mockAuthOn = false;
    open();
    expect(screen.getByText(/tokens saved here are shared too/)).toBeInTheDocument();
    fireEvent.change(field(), { target: { value: "hf_local" } });
    fireEvent.click(saveTokens());
    await waitFor(() =>
      expect(mockUpdate).toHaveBeenCalledWith({ huggingfaceToken: "hf_local", socrataAppToken: undefined }),
    );
    // The panels that run on the account's models stay off for a guest.
    expect(screen.queryByText("Evaluation mode")).toBeNull();
  });
});

describe("AI Settings: Connection keys (dev/116)", () => {
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
    // The tokens' Save stays the only /save/i button while collapsed.
    expect(screen.getAllByRole("button", { name: /save/i })).toHaveLength(1);
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
    render(<AiSettingsModal isOpen onClose={jest.fn()} focus={{ section: "connection-keys", host: "api.census.gov", suggestedName: "census" }} />);
    expect(screen.getByTestId("connection-keys-section")).toHaveAttribute("open");
    expect((screen.getByLabelText("Host") as HTMLInputElement).value).toBe("api.census.gov");
    expect((screen.getByLabelText("Name") as HTMLInputElement).value).toBe("census");
    await waitFor(() => expect(screen.getByLabelText("Name")).toHaveFocus());
  });

  it("saving sends host, value and delivery, then clears the key field and shows the use line", async () => {
    mockPut.mockResolvedValue({ key: CENSUS });
    render(<AiSettingsModal isOpen onClose={jest.fn()} focus={{ section: "connection-keys", host: "api.census.gov" }} />);
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
    render(<AiSettingsModal isOpen onClose={jest.fn()} focus={{ section: "connection-keys", host: "other.gov", suggestedName: "census" }} />);
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

describe("AI Settings: the data-portal token", () => {
  /**
   * A third credential on this screen, and the first that is not about AI at
   * all: the Data Lake Catalog sends it to Socrata portals. It lives here
   * because this is the account's one credentials surface - the Agent
   * Catalog's account policy was deliberately moved INTO this modal rather
   * than living in a second one holding half the answer.
   *
   * It follows the same rules as the HuggingFace token beside it: stored on
   * the user's row, reported as a boolean, blank means keep, and there is an
   * explicit way to remove it.
   */
  const field = () =>
    document.querySelector("#ai-settings-socrata-token") as HTMLInputElement;

  it("is offered, and marked optional when none is saved", () => {
    open();
    expect(field()).toBeInTheDocument();
    expect(field().type).toBe("password");
    // Scoped to the label: the "Get a Socrata app token" link repeats the
    // words, and matching either would not prove the field is labelled.
    expect(
      document.querySelector('label[for="ai-settings-socrata-token"]')
    ).toBeInTheDocument();
  });

  it("says a token is saved without ever showing it", () => {
    mockUser = { ...SIGNED_IN, has_socrata_app_token: true };
    open();
    expect(screen.getByText(/\(saved - leave blank to keep\)/)).toBeInTheDocument();
    expect(field().value).toBe("");
    expect(field().placeholder).toContain("unchanged");
  });

  it("saves what was typed", async () => {
    open();
    fireEvent.change(field(), { target: { value: "tok-123" } });
    fireEvent.click(saveTokens());
    await waitFor(() =>
      expect(mockUpdate).toHaveBeenCalledWith(
        expect.objectContaining({ socrataAppToken: "tok-123" })
      )
    );
  });

  it("leaves a saved token alone when the box is blank", async () => {
    // Blank means keep: saving the HuggingFace token must not touch it.
    mockUser = { ...SIGNED_IN, has_socrata_app_token: true };
    open();
    fireEvent.change(document.querySelector("#ai-settings-hf-token") as HTMLInputElement, {
      target: { value: "hf_abc" },
    });
    fireEvent.click(saveTokens());
    await waitFor(() => expect(mockUpdate).toHaveBeenCalled());
    expect(mockUpdate.mock.calls[0][0].socrataAppToken).toBeUndefined();
  });

  it("offers a way to remove one, which is how blank-means-keep stays escapable", async () => {
    mockUser = { ...SIGNED_IN, has_socrata_app_token: true };
    open();
    const remove = screen
      .getAllByRole("button", { name: /Remove saved token/ })
      .at(-1)!;
    fireEvent.change(field(), { target: { value: "typed-but-unsaved" } });
    fireEvent.click(remove);
    await waitFor(() =>
      expect(mockUpdate).toHaveBeenCalledWith({ socrataAppToken: "" })
    );
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


describe("AI Settings: a deployment-supplied portal token", () => {
  /**
   * A user who sets nothing uses what the operator configured, and setting
   * their own overrides it. An operator running Curio for a class raises the
   * rate limit for everyone with one environment variable.
   */
  const label = () =>
    document.querySelector('label[for="ai-settings-socrata-token"]')!.textContent ?? "";

  it("says the box is optional when nothing is configured", async () => {
    mockPublicConfig = { has_default_socrata_app_token: false };
    open();
    await waitFor(() => expect(label()).toContain("(optional)"));
  });

  it("says it is inherited when the install supplies one", async () => {
    // "(optional)" would be misleading: leaving the box blank already
    // authenticates you.
    mockPublicConfig = { has_default_socrata_app_token: true };
    open();
    await waitFor(() => expect(label()).toContain("inherited"));
    expect(screen.getByText(/Leave this blank to use it/)).toBeInTheDocument();
  });

  it("a token you saved yourself takes precedence in the copy", async () => {
    mockUser = { ...SIGNED_IN, has_socrata_app_token: true };
    mockPublicConfig = { has_default_socrata_app_token: true };
    open();
    await waitFor(() => expect(label()).toContain("saved"));
    expect(label()).not.toContain("inherited");
  });

  it("an unreadable config reports nothing rather than claiming inheritance", async () => {
    const { authApi } = require("../../utils/authApi");
    (authApi.getPublicConfig as jest.Mock).mockRejectedValueOnce(new Error("offline"));
    open();
    await waitFor(() => expect(label()).toContain("(optional)"));
  });
});
