import React from "react";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";

/**
 * AI Settings is the one account-level place the models are configured.
 *
 * It has one job: which provider answers Curio's AI surfaces. It briefly grew a
 * second "Agent limits" tab holding run and spend caps, which is gone - Curio
 * does not police usage, so there was nothing left for those fields to set.
 *
 * The deployment's own default is part of this screen rather than hidden behind
 * it. `curio.py start --llm-provider/--llm-base-url/--llm-model` write the same
 * account-wide setting this panel edits, so the panel shows what they wrote as
 * the inherited value.
 */

const SIGNED_IN = {
  is_guest: false,
  has_llm_api_key: false,
  llm_api_type: null,
  llm_base_url: null,
  llm_model: null,
};

// Mutable so the guest case can share one module registry with the rest -
// jest.resetModules() + doMock after the import under test has already been
// evaluated does not re-bind it.
let mockUser: Record<string, unknown> = { ...SIGNED_IN };

const mockUpdate = jest.fn().mockResolvedValue(undefined);

jest.mock("../../providers/UserProvider", () => ({
  useUserContext: () => ({ user: mockUser, updateLlmConfig: mockUpdate }),
}));

let mockDefault: unknown = {
  apiType: null,
  baseUrl: null,
  model: null,
  hasApiKey: false,
};
let mockDefaultRejects = false;

let mockModels: {
  models: string[];
  listable: boolean;
  source?: string;
  remembered?: string[];
  rememberedAt?: string | null;
  warning?: string | null;
} = {
  models: [],
  listable: true,
};
let mockModelsRejects: string | null = null;

jest.mock("../../api/agentsApi", () => ({
  agentsApi: {
    providerDefault: jest.fn(() =>
      mockDefaultRejects ? Promise.reject(new Error("nope")) : Promise.resolve(mockDefault),
    ),
    providerModels: jest.fn(() =>
      mockModelsRejects
        ? Promise.reject(new Error(mockModelsRejects))
        : Promise.resolve(mockModels),
    ),
  },
}));

import AiSettingsModal from "../../components/AiSettingsModal";
import { agentsApi } from "../../api/agentsApi";

const open = () => render(<AiSettingsModal isOpen onClose={jest.fn()} />);

beforeEach(() => {
  mockUser = { ...SIGNED_IN };
  mockDefault = { apiType: null, baseUrl: null, model: null, hasApiKey: false };
  mockDefaultRejects = false;
  mockModels = { models: [], listable: true };
  mockModelsRejects = null;
  jest.clearAllMocks();
});

describe("AI Settings", () => {
  it("is titled AI Settings, not LLM Settings", () => {
    open();
    expect(screen.getByRole("heading", { name: "AI Settings" })).toBeInTheDocument();
    expect(screen.queryByText("LLM Settings")).toBeNull();
  });

  it("shows the provider form, with no second tab", () => {
    open();
    // The OpenAI/Anthropic/Gemini/Custom picker is a button group, not a
    // labelled form control, so it is the landmark for "the form is here".
    expect(screen.getByRole("button", { name: "OpenAI" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Agent limits" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Provider" })).toBeNull();
  });

  it("mentions no quota, budget or run limit anywhere", () => {
    // The whole point of removing the limits tab: Curio does not present a
    // surface for capping what a user may spend.
    const { container } = open();
    expect(container.textContent).not.toMatch(/quota|budget|runs per day|limit/i);
  });

  it("says which surfaces this provider answers", () => {
    // The linkage was invisible: an agent that stopped working gave no hint
    // that this modal was where to look.
    open();
    expect(screen.getByText(/agents/i)).toBeInTheDocument();
    expect(screen.getByText(/node-authoring assistants and chat/i)).toBeInTheDocument();
  });

  it("renders nothing when closed", () => {
    const { container } = render(<AiSettingsModal isOpen={false} onClose={jest.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("the HuggingFace token", () => {
  it("is offered as an account setting, not an operator-only env var", async () => {
    // Gated models are unlocked per HuggingFace account by accepting a
    // licence, so one shared deployment token cannot represent what each user
    // may download. It used to live only in HUGGINGFACE_TOKEN.
    open();
    expect(
      screen.getByPlaceholderText("hf_..."),
    ).toBeInTheDocument();
    expect(screen.getByText(/only needed for/i)).toBeInTheDocument();
    expect(screen.getByText(/gated/i)).toBeInTheDocument();
  });

  it("shows it as saved without ever rendering the value", () => {
    mockUser = { ...SIGNED_IN, has_huggingface_token: true };
    open();
    const box = screen.getByPlaceholderText(/unchanged/i);
    expect(box).toHaveValue("");
    expect(screen.getByText(/leave blank to keep/i)).toBeInTheDocument();
  });

  it("sends it only when the user typed one", async () => {
    open();
    fireEvent.click(screen.getByRole("button", { name: /^Save$/ }));
    await waitFor(() => expect(mockUpdate).toHaveBeenCalled());
    expect(mockUpdate.mock.calls[0][0].huggingfaceToken).toBeUndefined();
  });

  it("sends what the user typed", async () => {
    open();
    fireEvent.change(screen.getByPlaceholderText("hf_..."), {
      target: { value: "hf_mine" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^Save$/ }));
    await waitFor(() => expect(mockUpdate).toHaveBeenCalled());
    expect(mockUpdate.mock.calls[0][0].huggingfaceToken).toBe("hf_mine");
  });
});

describe("the deployment default is visible to the user it applies to", () => {
  it("names the model and endpoint the launcher flags set", async () => {
    mockDefault = {
      apiType: "openai_compatible",
      baseUrl: "https://llm.example.test/v1",
      model: "some-model",
      hasApiKey: true,
    };
    open();
    // --llm-model
    expect(await screen.findByText("some-model")).toBeInTheDocument();
    // --llm-base-url
    expect(screen.getByText("https://llm.example.test/v1")).toBeInTheDocument();
    expect(screen.getByText(/leave a field blank to use it/i)).toBeInTheDocument();
  });

  it("offers it as the model placeholder rather than as a saved value", async () => {
    // A suggestion written into the value would save as an explicit override
    // the user never chose, detaching them from the deployment default.
    mockDefault = { apiType: "openai_compatible", baseUrl: null, model: "some-model", hasApiKey: false };
    open();
    const box = await screen.findByPlaceholderText("some-model (from this deployment)");
    expect(box).toHaveValue("");
  });

  it("says the key is optional when the deployment supplies one", async () => {
    mockDefault = { apiType: "openai_compatible", baseUrl: null, model: "m", hasApiKey: true };
    open();
    expect(
      await screen.findByText(/this deployment provides one/i),
    ).toBeInTheDocument();
  });

  it("says plainly when nothing is configured", async () => {
    open();
    await waitFor(() => expect(agentsApi.providerDefault).toHaveBeenCalled());
    expect(screen.getByText(/no default is configured/i)).toBeInTheDocument();
  });

  it("still edits the user's own config when the lookup fails", async () => {
    // A deployment default is a nicety, not a prerequisite.
    mockDefaultRejects = true;
    open();
    await waitFor(() => expect(agentsApi.providerDefault).toHaveBeenCalled());
    expect(screen.getByRole("button", { name: "OpenAI" })).toBeInTheDocument();
  });

  it("is not fetched for a guest, who cannot act on it", async () => {
    mockUser = { is_guest: true };
    open();
    expect(screen.getByText(/configured by whoever runs this/i)).toBeInTheDocument();
    expect(agentsApi.providerDefault).not.toHaveBeenCalled();
  });

  it("renders on the overlay layer, above the Agent Catalog drawer", () => {
    // The drawer's header cog is the only route to this panel from the canvas.
    // Without layer="overlay" the shell paints at --curio-z-modal-base (500)
    // while the drawer sits at --curio-z-agent-drawer (10048), so the panel
    // opened *underneath* the drawer and its scrim ate the clicks: the button
    // looked dead and the canvas had no working way to configure a provider.
    //
    // Asserted through the class rather than a computed z-index because jsdom
    // does not apply stylesheets, which is exactly why the whole suite stayed
    // green while the feature was unreachable.
    const { baseElement } = open();
    expect(baseElement.querySelector(".modalOverlay")).not.toBeNull();
    expect(baseElement.querySelector(".backdropOverlay")).not.toBeNull();
  });
});

describe("AI Settings: clearing what was saved", () => {
  it("sends a blank model so the deployment default can be inherited again", async () => {
    // `model || undefined` used to be dropped by JSON.stringify, so a cleared
    // box was omitted from the PATCH and the stale override survived. The
    // panel's own copy says a blank field inherits the deployment default.
    mockUser = { ...SIGNED_IN, llm_model: "old-model" };
    const { baseElement } = open();
    // The Model box is the only text input on the default (non-custom)
    // provider; Base URL is hidden and the two secrets are type="password".
    // Queried from baseElement because ModalShell portals to document.body.
    const modelBox = baseElement.querySelector('input[type="text"]')!;
    fireEvent.change(modelBox, { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: /save/i }));

    await waitFor(() => expect(mockUpdate).toHaveBeenCalled());
    expect(mockUpdate.mock.calls[0][0]).toMatchObject({ model: "" });
  });

  it("offers a way to remove a saved API key", async () => {
    mockUser = { ...SIGNED_IN, has_llm_api_key: true };
    open();
    fireEvent.click(screen.getByRole("button", { name: /remove saved key/i }));
    await waitFor(() => expect(mockUpdate).toHaveBeenCalledWith({ apiKey: "" }));
  });

  it("offers a way to remove a saved HuggingFace token", async () => {
    mockUser = { ...SIGNED_IN, has_huggingface_token: true };
    open();
    fireEvent.click(screen.getByRole("button", { name: /remove saved token/i }));
    await waitFor(() =>
      expect(mockUpdate).toHaveBeenCalledWith({ huggingfaceToken: "" }),
    );
  });

  it("shows no remove control when nothing is saved", () => {
    mockUser = { ...SIGNED_IN };
    open();
    expect(screen.queryByRole("button", { name: /remove saved/i })).toBeNull();
  });
});

/**
 * The Model field asks the endpoint what it serves.
 *
 * Typing a model name from memory is how you end up saving one the endpoint
 * does not have, which surfaces much later as a failed agent run rather than as
 * a wrong value in this box. The list has to come from the endpoint being
 * configured *right now*, which is why the fetch sends what is on screen rather
 * than what was last saved.
 */
describe("AI Settings: choosing a model from the endpoint", () => {
  const fetchModels = async () => {
    fireEvent.click(screen.getByRole("button", { name: /Fetch models/i }));
    await waitFor(() =>
      expect(agentsApi.providerModels).toHaveBeenCalled(),
    );
  };

  it("is a free-text box until the models are known", () => {
    open();
    expect(screen.getByLabelText("Model")).toHaveProperty("tagName", "INPUT");
    expect(screen.queryByRole("combobox")).toBeNull();
  });

  it("becomes a dropdown of what the endpoint serves", async () => {
    mockModels = { models: ["gemma4", "llama4-nim"], listable: true };
    open();
    await fetchModels();

    const select = await screen.findByLabelText("Model");
    expect(select.tagName).toBe("SELECT");
    expect(
      Array.from(select.querySelectorAll("option")).map((o) => o.textContent),
    ).toEqual(expect.arrayContaining(["gemma4", "llama4-nim"]));

    fireEvent.change(select, { target: { value: "gemma4" } });
    expect((select as HTMLSelectElement).value).toBe("gemma4");
  });

  it("sends the credentials on screen, not the ones last saved", async () => {
    mockModels = { models: ["gemma4"], listable: true };
    open();
    fireEvent.click(screen.getByRole("button", { name: "Custom" }));
    fireEvent.change(screen.getByLabelText("Base URL"), {
      target: { value: "https://example.invalid/" },
    });
    await fetchModels();

    expect(agentsApi.providerModels).toHaveBeenCalledWith(
      expect.objectContaining({
        apiType: "openai_compatible",
        baseUrl: "https://example.invalid/",
      }),
    );
  });

  it("keeps a saved model selectable when the endpoint no longer lists it", async () => {
    mockUser = { ...SIGNED_IN, llm_model: "retired-model" };
    mockModels = { models: ["gemma4"], listable: true };
    open();
    await fetchModels();

    const select = (await screen.findByLabelText("Model")) as HTMLSelectElement;
    expect(select.value).toBe("retired-model");
    expect(screen.getByText("retired-model (not listed)")).toBeInTheDocument();
  });

  it("stays typeable when the endpoint cannot be listed", async () => {
    mockModelsRejects = "Could not list models: 401 invalid key";
    open();
    await fetchModels();

    await screen.findByText(/Could not list models/);
    // The point: a listing failure must not cost you the ability to configure.
    expect(screen.getByLabelText("Model")).toHaveProperty("tagName", "INPUT");
  });

  it("does not offer one provider's models for another", async () => {
    mockModels = { models: ["gemma4"], listable: true };
    open();
    await fetchModels();
    expect((await screen.findByLabelText("Model")).tagName).toBe("SELECT");

    fireEvent.click(screen.getByRole("button", { name: "Anthropic" }));
    expect(screen.getByLabelText("Model")).toHaveProperty("tagName", "INPUT");
  });
});

/**
 * #241 asked whether Curio should discover models dynamically, ship a fixed
 * list, or do both. It does both - and both halves come from the API.
 *
 * The fallback is a *recording*: what this endpoint reported the last time it
 * could be asked, kept per account. Nothing is authored, so nothing drifts and
 * nobody maintains it. Two things this suite has to keep honest. The panel must
 * never claim a provider "does not publish a model list" - that was the old
 * copy for Anthropic and Gemini, and it was untrue: nobody had asked them. And
 * a replay must never read as the present tense, because saving a model the
 * endpoint no longer has surfaces much later as a failed agent run.
 *
 * The guard tests above still apply and are load-bearing: the field is free
 * text until Fetch is pressed, and one provider's list is never offered for
 * another.
 */
describe("AI Settings: replaying the last listing", () => {
  const REMEMBERED = {
    models: ["claude-sonnet-5", "claude-haiku-4-5"],
    listable: false,
    source: "remembered",
    remembered: ["claude-sonnet-5", "claude-haiku-4-5"],
    rememberedAt: "2026-09-01T12:00:00+00:00",
    warning: "Add an API key above to ask this provider what it serves.",
  };

  const fetchModels = async () => {
    fireEvent.click(screen.getByRole("button", { name: /Fetch models/i }));
    await waitFor(() => expect(agentsApi.providerModels).toHaveBeenCalled());
  };

  it("offers what the endpoint last reported when it cannot be asked now", async () => {
    mockModels = { ...REMEMBERED };
    open();
    fireEvent.click(screen.getByRole("button", { name: "Anthropic" }));
    await fetchModels();

    const select = (await screen.findByLabelText("Model")) as HTMLSelectElement;
    expect(select.tagName).toBe("SELECT");
    expect(
      Array.from(select.querySelectorAll("option")).map((o) => o.textContent),
    ).toEqual(expect.arrayContaining(["claude-sonnet-5", "claude-haiku-4-5"]));
  });

  it("never says a provider publishes no model list", async () => {
    // The old copy. It was wrong, and it was a dead end for the user.
    mockModels = { ...REMEMBERED, warning: "Could not list models: 401" };
    const { baseElement } = open();
    fireEvent.click(screen.getByRole("button", { name: "Anthropic" }));
    await fetchModels();
    expect(baseElement.textContent).not.toMatch(/does not publish a model list/i);
  });

  it("says these are a replay, and when they were true", async () => {
    // Presenting a recording as the present tense is the failure mode here.
    mockModels = { ...REMEMBERED };
    open();
    fireEvent.click(screen.getByRole("button", { name: "Anthropic" }));
    await fetchModels();

    expect(await screen.findByText(/Add an API key above/)).toBeInTheDocument();
    expect(screen.getByText(/last reported/i)).toBeInTheDocument();

    const select = (await screen.findByLabelText("Model")) as HTMLSelectElement;
    const label = select.querySelector("optgroup")!.getAttribute("label")!;
    expect(label).toMatch(/Last reported by this endpoint/i);
    expect(label).toMatch(/2026/);
  });

  it("labels a live list as current, with no date", async () => {
    mockModels = {
      models: ["gemma4", "llama4-nim"],
      listable: true,
      source: "live",
      remembered: [],
      rememberedAt: null,
      warning: null,
    };
    open();
    await fetchModels();

    const select = (await screen.findByLabelText("Model")) as HTMLSelectElement;
    expect(
      select.querySelector("optgroup")!.getAttribute("label"),
    ).toBe("From this endpoint");
    expect(screen.queryByText(/last reported/i)).toBeNull();
  });

  it("survives a replay with no usable timestamp", async () => {
    // An older store entry may carry models but no seenAt. Worth showing the
    // models; not worth an "Invalid Date" in the label.
    mockModels = { ...REMEMBERED, rememberedAt: null };
    open();
    fireEvent.click(screen.getByRole("button", { name: "Anthropic" }));
    await fetchModels();

    const select = (await screen.findByLabelText("Model")) as HTMLSelectElement;
    const label = select.querySelector("optgroup")!.getAttribute("label")!;
    expect(label).toMatch(/Last reported by this endpoint/i);
    expect(label).not.toMatch(/Invalid Date/);
  });

  it("drops the replay when the provider changes", async () => {
    // One provider's models offered for another is worse than none.
    mockModels = { ...REMEMBERED };
    open();
    fireEvent.click(screen.getByRole("button", { name: "Anthropic" }));
    await fetchModels();
    expect((await screen.findByLabelText("Model")).tagName).toBe("SELECT");

    fireEvent.click(screen.getByRole("button", { name: "OpenAI" }));
    expect(screen.getByLabelText("Model")).toHaveProperty("tagName", "INPUT");
    expect(screen.queryByText(/last reported/i)).toBeNull();
  });

  it("still reports an endpoint that answered with nothing at all", async () => {
    mockModels = {
      models: [],
      listable: true,
      source: "live",
      remembered: [],
      rememberedAt: null,
      warning: null,
    };
    open();
    fireEvent.click(screen.getByRole("button", { name: "Custom" }));
    await fetchModels();
    expect(await screen.findByText(/returned no models/i)).toBeInTheDocument();
    expect(screen.getByLabelText("Model")).toHaveProperty("tagName", "INPUT");
  });
});

describe("AI Settings: the saved key belongs to one provider", () => {
  const SAVED_ON_GEMINI = {
    ...SIGNED_IN,
    has_llm_api_key: true,
    llm_api_type: "gemini",
  };

  const savedMarkers = () => ({
    label: screen.queryByText(/saved - leave blank to keep/i),
    masked: screen.queryByPlaceholderText(/unchanged/i),
    remove: screen.queryByRole("button", { name: /remove saved key/i }),
  });

  it("shows saved, the masked box and Remove on the provider it was saved for", () => {
    mockUser = SAVED_ON_GEMINI;
    open();
    const { label, masked, remove } = savedMarkers();
    expect(label).not.toBeNull();
    expect(masked).not.toBeNull();
    expect(remove).not.toBeNull();
  });

  it.each(["OpenAI", "Anthropic", "Custom"])(
    "shows none of them on the %s tab",
    (tab) => {
      mockUser = SAVED_ON_GEMINI;
      open();
      fireEvent.click(screen.getByRole("button", { name: tab }));
      const { label, masked, remove } = savedMarkers();
      expect(label).toBeNull();
      expect(masked).toBeNull();
      expect(remove).toBeNull();
    },
  );

  it("leaves an empty, prompting box on a provider with no key", () => {
    mockUser = SAVED_ON_GEMINI;
    open();
    fireEvent.click(screen.getByRole("button", { name: "Anthropic" }));
    const box = screen.getByPlaceholderText("Enter your API key");
    expect(box).toHaveValue("");
    expect(screen.getByText("(required)")).toBeInTheDocument();
  });

  it("explains that there is only one key, and whose it is", () => {
    // Without this the empty box reads as "your Gemini key was lost".
    mockUser = SAVED_ON_GEMINI;
    open();
    fireEvent.click(screen.getByRole("button", { name: "Anthropic" }));
    expect(screen.getByText(/one provider key per account/i)).toBeInTheDocument();
    expect(screen.getByText(/belongs to Gemini/i)).toBeInTheDocument();
    expect(screen.getByText(/Saving here replaces it/i)).toBeInTheDocument();
  });

  it("names that explanation from the input, for a screen reader", () => {
    mockUser = SAVED_ON_GEMINI;
    const { baseElement } = open();
    fireEvent.click(screen.getByRole("button", { name: "Anthropic" }));
    const described = baseElement
      .querySelector("#ai-settings-api-key")!
      .getAttribute("aria-describedby");
    expect(described).toBeTruthy();
    expect(baseElement.querySelector(`#${described}`)).not.toBeNull();
  });

  it("says nothing about other providers when no key is saved at all", () => {
    mockUser = { ...SIGNED_IN };
    open();
    fireEvent.click(screen.getByRole("button", { name: "Anthropic" }));
    expect(screen.queryByText(/one provider key per account/i)).toBeNull();
  });

  it("clears the stale key when saving under a different provider", async () => {
    // The defect: `apiKey || undefined` was dropped from the PATCH, so the
    // Gemini key survived and was relabelled Anthropic.
    mockUser = SAVED_ON_GEMINI;
    open();
    fireEvent.click(screen.getByRole("button", { name: "Anthropic" }));
    fireEvent.click(screen.getByRole("button", { name: /^Save$/ }));

    await waitFor(() => expect(mockUpdate).toHaveBeenCalled());
    const sent = mockUpdate.mock.calls[0][0];
    expect(sent.apiType).toBe("anthropic");
    expect(sent.apiKey).toBe("");
  });

  it("sends the typed key when saving under a different provider", async () => {
    mockUser = SAVED_ON_GEMINI;
    open();
    fireEvent.click(screen.getByRole("button", { name: "Anthropic" }));
    fireEvent.change(screen.getByPlaceholderText("Enter your API key"), {
      target: { value: "sk-ant-new" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^Save$/ }));

    await waitFor(() => expect(mockUpdate).toHaveBeenCalled());
    expect(mockUpdate.mock.calls[0][0].apiKey).toBe("sk-ant-new");
  });

  it("still keeps the key when saving on the provider it belongs to", async () => {
    // "Blank means keep" is what the label promises, and re-typing a key to
    // change an unrelated field would be hostile.
    mockUser = SAVED_ON_GEMINI;
    open();
    fireEvent.click(screen.getByRole("button", { name: /^Save$/ }));

    await waitFor(() => expect(mockUpdate).toHaveBeenCalled());
    expect(mockUpdate.mock.calls[0][0].apiKey).toBeUndefined();
  });

  it("treats a saved custom endpoint as its own provider", () => {
    // uiModeFromSaved reads a base URL as "custom", so a key saved against
    // Ollama must not show as saved on the OpenAI tab.
    mockUser = {
      ...SIGNED_IN,
      has_llm_api_key: true,
      llm_api_type: "openai_compatible",
      llm_base_url: "http://localhost:11434/v1",
    };
    open();
    // Opens on Custom, which is where the key lives.
    expect(savedMarkers().remove).not.toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "OpenAI" }));
    expect(savedMarkers().remove).toBeNull();
  });
});

describe("AI Settings: refetching after the first answer", () => {
  it("drops the replay explanation once a live list arrives", async () => {
    // Fetch with no key, paste one, Refresh. The old note would otherwise sit
    // over a list that is now genuinely from the endpoint.
    mockModels = {
      models: ["claude-sonnet-5"],
      listable: false,
      source: "remembered",
      remembered: ["claude-sonnet-5"],
      rememberedAt: "2026-09-01T12:00:00+00:00",
      warning: "Add an API key above to ask this provider what it serves.",
    };
    open();
    fireEvent.click(screen.getByRole("button", { name: "Anthropic" }));
    fireEvent.click(screen.getByRole("button", { name: /Fetch models/i }));
    await screen.findByText(/last reported/i);

    mockModels = {
      models: ["claude-opus-5"],
      listable: true,
      source: "live",
      remembered: [],
      rememberedAt: null,
      warning: null,
    };
    fireEvent.click(screen.getByRole("button", { name: /Refresh models/i }));
    await waitFor(() =>
      expect(screen.queryByText(/last reported/i)).toBeNull(),
    );
  });
});

describe("AI Settings: the model suggestions are canonical ids", () => {
  it("offers no date-suffixed model as a placeholder", async () => {
    // The Anthropic placeholder read `claude-haiku-4-5-20251001` while the
    // provider reports the bare `claude-haiku-4-5`, so the same model appeared
    // under two spellings on one screen. A constructed `-YYYYMMDD` variant is
    // also not guaranteed to resolve at the provider.
    const suffixed = /-20\d{6}/;
    for (const tab of ["OpenAI", "Anthropic", "Gemini"]) {
      const { unmount } = render(<AiSettingsModal isOpen onClose={jest.fn()} />);
      fireEvent.click(screen.getByRole("button", { name: tab }));
      const box = screen.getByLabelText("Model") as HTMLInputElement;
      expect(box.placeholder).not.toMatch(suffixed);
      unmount();
    }
  });
});
