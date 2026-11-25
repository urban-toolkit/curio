/**
 * An agent's package install opens its review (dev/84) over the whole page,
 * through ModalShell, as every other dialog opened from the chat does.
 *
 * The chat panel slides on a transform, and a transform makes the panel the box
 * a fixed element inside it is placed in. The review was drawn in the panel's
 * transcript, so its backdrop covered the panel only and its card was cut to
 * the panel's width. It was outside the modal stack as well, so Escape closed
 * the chat behind it and left the review open.
 */
import React from "react";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({ playAllNodes: jest.fn(), projectDirty: false }),
}));
jest.mock("../../services/packages/packagesApi", () => ({
  packagesApi: { catalog: jest.fn(), listInstalled: jest.fn(), resolve: jest.fn() },
}));
import { packagesApi } from "../../services/packages/packagesApi";

import { AgentChatPanel } from "../../components/agents/attach/AgentChatPanel";
import type { AgentAttachment, AgentSessionTurn } from "../../services/agents";

const attachment: AgentAttachment = {
  attachmentId: "a1",
  coord: "agent.test.my-explainer@1",
  target: { kind: "canvas" as const },
  sessionId: "s1234567890",
  revision: 1,
  name: "My Explainer",
  category: "node",
  hooks: ["node"],
  intent: "Explain the selected node's code and outputs.",
  intentEdited: false,
  title: null,
  titleEdited: false,
};

const packageTurns: AgentSessionTurn[] = [
  {
    role: "agent",
    text: "You need the weather package.",
    content: [
      {
        type: "proposal",
        proposalId: "pk1",
        tool: "package.install",
        summary: "Install package · Weather Analysis",
        preview: "the proposed node imports rasterio",
        pins: { dirName: "curio.weather@1" },
        status: "pending",
      } as never,
    ],
  } as AgentSessionTurn,
];

beforeEach(() => {
  (packagesApi.catalog as jest.Mock).mockResolvedValue({
    packages: [
      {
        dirName: "curio.weather@1",
        name: "Weather Analysis",
        publisher: "curio",
        version: "1.0.0",
        permissions: ["network.fetch"],
        dependencies: { python: { rasterio: ">=1.5.0" }, js: {}, packages: {} },
        installed: false,
      },
    ],
  });
  (packagesApi.listInstalled as jest.Mock).mockResolvedValue({ packages: [] });
  (packagesApi.resolve as jest.Mock).mockResolvedValue({ lockfile: {}, conflicts: [] });
});

function renderPanel(overrides: Partial<React.ComponentProps<typeof AgentChatPanel>> = {}) {
  const props: React.ComponentProps<typeof AgentChatPanel> = {
    attachment,
    turns: packageTurns,
    onSend: jest.fn().mockResolvedValue(undefined),
    onClose: jest.fn(),
    ...overrides,
  };
  render(<AgentChatPanel {...props} />, { wrapper: MemoryRouter });
  return props;
}

describe("an agent's package install review", () => {
  it("opens over the page, outside the sliding panel, as the dialog on top", async () => {
    renderPanel({ onApplyProposal: jest.fn().mockResolvedValue(undefined) });
    const panel = screen.getByRole("dialog", { name: "Chat with My Explainer" });
    fireEvent.click(within(panel).getByRole("button", { name: "Apply" }));

    const title = await screen.findByText('Add "Weather Analysis"');
    // Outside the panel, whose transform would make it the review's box.
    expect(panel.contains(title)).toBe(false);
    // A ModalShell's dialog: in the modal stack, and named by its title.
    const shell = title.closest<HTMLElement>('[data-curio-modal-shell="true"]');
    expect(shell).not.toBeNull();
    expect(shell).toHaveAttribute("role", "dialog");
    expect(screen.getByRole("dialog", { name: 'Add "Weather Analysis"' })).toBe(shell);
    // Its permissions and libraries, as the Node Catalog's review shows them.
    expect(within(shell!).getByText("network.fetch")).toBeInTheDocument();
    expect(within(shell!).getByText("python · rasterio")).toBeInTheDocument();
  });

  it("answers Escape itself: the review closes, the chat stays, nothing is applied", async () => {
    const onApplyProposal = jest.fn().mockResolvedValue(undefined);
    const { onClose } = renderPanel({ onApplyProposal });
    const panel = screen.getByRole("dialog", { name: "Chat with My Explainer" });
    fireEvent.click(within(panel).getByRole("button", { name: "Apply" }));
    await screen.findByText('Add "Weather Analysis"');

    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(screen.queryByText('Add "Weather Analysis"')).toBeNull());
    expect(onClose).not.toHaveBeenCalled();
    expect(onApplyProposal).not.toHaveBeenCalled();
    // The proposal stays pending, so its card can open the review again.
    await waitFor(() => expect(within(panel).getByRole("button", { name: "Apply" })).toBeEnabled());
  });
});
