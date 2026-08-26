import React from "react";
import { render, screen, waitFor } from "@testing-library/react";

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

jest.mock("../../providers/UserProvider", () => ({
  useUserContext: () => ({
    user: mockUser,
    updateLlmConfig: jest.fn().mockResolvedValue(undefined),
  }),
}));

let mockDefault: unknown = {
  apiType: null,
  baseUrl: null,
  model: null,
  hasApiKey: false,
};
let mockDefaultRejects = false;

jest.mock("../../api/agentsApi", () => ({
  agentsApi: {
    providerDefault: jest.fn(() =>
      mockDefaultRejects ? Promise.reject(new Error("nope")) : Promise.resolve(mockDefault),
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
});
