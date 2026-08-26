import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

/**
 * AI Settings is the one account-level place the models are configured.
 *
 * Before this, the answer to "how is my AI set up?" lived in two modals reached
 * from two different places: the header's LLM Settings held the provider, and
 * the agent drawer's cog held the spend limits that apply to it. They are two
 * halves of one question, so they are now two tabs of one surface.
 *
 * The provider itself did not move. `agents/provider_config.py` already read
 * the same `user.llm_*` fields this modal writes - the agents were always using
 * it. What changed is that the modal says so.
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

// The embedded account-policy editor. Its own behaviour is covered by
// tests/settings/; here it only needs to prove which tab hosts it.
jest.mock("../../components/agents/settings/AgentSettingsModal", () => ({
  AgentSettingsModal: ({ scope, embedded }: { scope: string; embedded?: boolean }) => (
    <div data-testid="agent-settings" data-scope={scope} data-embedded={String(!!embedded)}>
      agent limits
    </div>
  ),
}));

import AiSettingsModal from "../../components/AiSettingsModal";

const open = () => render(<AiSettingsModal isOpen onClose={jest.fn()} />);

beforeEach(() => {
  mockUser = { ...SIGNED_IN };
});

describe("AI Settings", () => {
  it("is titled AI Settings, not LLM Settings", () => {
    open();
    expect(screen.getByRole("heading", { name: "AI Settings" })).toBeInTheDocument();
    expect(screen.queryByText("LLM Settings")).toBeNull();
  });

  it("opens on the Provider tab", () => {
    open();
    expect(screen.getByRole("button", { name: "Provider" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    // The Provider *panel* is showing: its OpenAI/Anthropic/Gemini/Custom
    // picker is a button group, not a labelled form control.
    expect(screen.getByRole("button", { name: "OpenAI" })).toBeInTheDocument();
  });

  it("says which surfaces this provider answers", () => {
    // The linkage was invisible: an agent that stopped working gave no hint
    // that this modal was where to look.
    open();
    expect(screen.getByText(/agents/i)).toBeInTheDocument();
    expect(screen.getByText(/node-authoring assistants and chat/i)).toBeInTheDocument();
  });

  it("hosts the account-scope agent limits on its second tab", async () => {
    open();
    expect(screen.queryByTestId("agent-settings")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Agent limits" }));
    await waitFor(() => expect(screen.getByTestId("agent-settings")).toBeInTheDocument());
  });

  it("embeds that editor rather than stacking a second modal", async () => {
    open();
    fireEvent.click(screen.getByRole("button", { name: "Agent limits" }));
    const embedded = await screen.findByTestId("agent-settings");
    expect(embedded).toHaveAttribute("data-scope", "account");
    // `embedded` drops the editor's own ModalShell AND its role="dialog" - two
    // nested dialogs would make an unscoped get_by_role lookup ambiguous.
    expect(embedded).toHaveAttribute("data-embedded", "true");
  });

  it("renders nothing when closed", () => {
    const { container } = render(<AiSettingsModal isOpen={false} onClose={jest.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("AI Settings for a guest", () => {
  it("says who configures it instead of offering fields that cannot take effect", () => {
    mockUser = { is_guest: true };
    open();
    expect(screen.getByText(/configured by whoever runs this/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Agent limits" })).toBeNull();
  });
});
