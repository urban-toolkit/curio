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
  curated?: string[];
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
 * list, or do both. It does both.
 *
 * Two things this suite has to keep honest. The panel must never claim a
 * provider "does not publish a model list" - that was the old copy for
 * Anthropic and Gemini, and it was untrue: nobody had asked them. And a
 * curated suggestion must stay visibly distinct from what an endpoint actually
 * reported, because confusing the two is how a model the endpoint does not have
 * gets saved, which surfaces much later as a failed agent run.
 *
 * The guard tests above still apply and are load-bearing: the field is free
 * text until Fetch is pressed, and one provider's list is never offered for
 * another.
 */
describe("AI Settings: the curated fallback", () => {
  const fetchModels = async () => {
    fireEvent.click(screen.getByRole("button", { name: /Fetch models/i }));
    await waitFor(() => expect(agentsApi.providerModels).toHaveBeenCalled());
  };

  it("offers known models when the endpoint could not be asked", async () => {
    mockModels = {
      models: ["claude-sonnet-5", "claude-haiku-4-5"],
      listable: false,
      source: "curated",
      curated: ["claude-sonnet-5", "claude-haiku-4-5"],
      warning: "Add an API key above to ask this provider what it serves.",
    };
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
    mockModels = {
      models: ["claude-sonnet-5"],
      listable: false,
      source: "curated",
      curated: ["claude-sonnet-5"],
      warning: "Could not list models: 401",
    };
    const { baseElement } = open();
    fireEvent.click(screen.getByRole("button", { name: "Anthropic" }));
    await fetchModels();
    expect(baseElement.textContent).not.toMatch(/does not publish a model list/i);
  });

  it("says why it is offering a curated list rather than a live one", async () => {
    mockModels = {
      models: ["claude-sonnet-5"],
      listable: false,
      source: "curated",
      curated: ["claude-sonnet-5"],
      warning: "Add an API key above to ask this provider what it serves.",
    };
    open();
    fireEvent.click(screen.getByRole("button", { name: "Anthropic" }));
    await fetchModels();
    expect(await screen.findByText(/Add an API key above/)).toBeInTheDocument();
    expect(screen.getByText(/Showing known models/i)).toBeInTheDocument();
  });

  it("keeps curated suggestions in their own group, after the live ones", async () => {
    // A suggestion read as "what this endpoint serves" is how the wrong model
    // gets saved.
    mockModels = {
      models: ["endpoint-model", "gpt-4o-mini"],
      listable: true,
      source: "live+curated",
      curated: ["gpt-4o-mini"],
      warning: null,
    };
    open();
    await fetchModels();

    const select = (await screen.findByLabelText("Model")) as HTMLSelectElement;
    const groups = Array.from(select.querySelectorAll("optgroup"));
    expect(groups.map((g) => g.getAttribute("label"))).toEqual([
      "From this endpoint",
      "Known models for this provider",
    ]);
    expect(
      Array.from(groups[0].querySelectorAll("option")).map((o) => o.value),
    ).toEqual(["endpoint-model"]);
    expect(
      Array.from(groups[1].querySelectorAll("option")).map((o) => o.value),
    ).toEqual(["gpt-4o-mini"]);
  });

  it("draws no curated group when everything came from the endpoint", async () => {
    mockModels = {
      models: ["gemma4"],
      listable: true,
      source: "live",
      curated: [],
      warning: null,
    };
    open();
    await fetchModels();

    const select = (await screen.findByLabelText("Model")) as HTMLSelectElement;
    expect(
      Array.from(select.querySelectorAll("optgroup")).map((g) =>
        g.getAttribute("label"),
      ),
    ).toEqual(["From this endpoint"]);
  });

  it("drops the curated list when the provider changes", async () => {
    // A suggestion for Anthropic offered on the OpenAI tab is worse than none.
    mockModels = {
      models: ["claude-sonnet-5"],
      listable: false,
      source: "curated",
      curated: ["claude-sonnet-5"],
      warning: "no key",
    };
    open();
    fireEvent.click(screen.getByRole("button", { name: "Anthropic" }));
    await fetchModels();
    expect((await screen.findByLabelText("Model")).tagName).toBe("SELECT");

    fireEvent.click(screen.getByRole("button", { name: "OpenAI" }));
    expect(screen.getByLabelText("Model")).toHaveProperty("tagName", "INPUT");
    expect(screen.queryByText(/Showing known models/i)).toBeNull();
  });

  it("still reports an endpoint that answered with nothing at all", async () => {
    mockModels = {
      models: [],
      listable: true,
      source: "none",
      curated: [],
      warning: null,
    };
    open();
    fireEvent.click(screen.getByRole("button", { name: "Custom" }));
    await fetchModels();
    expect(await screen.findByText(/returned no models/i)).toBeInTheDocument();
    expect(screen.getByLabelText("Model")).toHaveProperty("tagName", "INPUT");
  });
});
