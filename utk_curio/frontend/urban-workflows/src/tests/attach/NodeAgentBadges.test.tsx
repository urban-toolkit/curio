import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";

const mockCtx = jest.fn();
jest.mock("../../components/agents/attach/AgentAttachmentsProvider", () => ({
  useAgentAttachmentsContext: () => mockCtx(),
}));

import { NodeAgentBadges } from "../../components/agents/attach/NodeAgentBadges";

function attachment(over: Partial<any>): any {
  return {
    attachmentId: "att-1",
    coord: "agent.node-explainer@1.0.0",
    target: { kind: "node", targetId: "n1" },
    sessionId: "s1",
    revision: 1,
    intent: null,
    intentEdited: false,
    title: null,
    titleEdited: false,
    name: "Node Explainer",
    category: "node",
    hooks: ["node"],
    ...over,
  };
}

function ctx(over: Partial<any> = {}) {
  return {
    attachments: [],
    busy: false,
    error: null,
    reload: jest.fn(),
    attach: jest.fn(),
    detach: jest.fn(),
    run: jest.fn(),
    selectedId: null,
    openChat: jest.fn(),
    closeChat: jest.fn(),
    ...over,
  };
}

beforeEach(() => jest.clearAllMocks());

describe("NodeAgentBadges", () => {
  it("renders nothing without a provider", () => {
    mockCtx.mockReturnValue(null);
    const { container } = render(<NodeAgentBadges nodeId="n1" />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows only node-target agents bound to this node", () => {
    mockCtx.mockReturnValue(
      ctx({
        attachments: [
          attachment({ attachmentId: "a-here", name: "Here", target: { kind: "node", targetId: "n1" } }),
          attachment({ attachmentId: "a-other", name: "OtherNode", target: { kind: "node", targetId: "n2" } }),
          attachment({ attachmentId: "a-canvas", name: "OnCanvas", target: { kind: "canvas" } }),
        ],
      }),
    );
    render(<NodeAgentBadges nodeId="n1" />);
    expect(screen.getByRole("button", { name: /Open chat with Here/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Open chat with OtherNode/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Open chat with OnCanvas/i })).not.toBeInTheDocument();
  });

  it("opens the chat for the clicked agent", () => {
    const openChat = jest.fn();
    mockCtx.mockReturnValue(
      ctx({ openChat, attachments: [attachment({ attachmentId: "a-here" })] }),
    );
    render(<NodeAgentBadges nodeId="n1" />);
    fireEvent.click(screen.getByRole("button", { name: /Open chat/i }));
    expect(openChat).toHaveBeenCalledWith("a-here");
  });

  it("detaches (and closes an open chat for it)", () => {
    const detach = jest.fn();
    const closeChat = jest.fn();
    mockCtx.mockReturnValue(
      ctx({
        detach,
        closeChat,
        selectedId: "a-here",
        attachments: [attachment({ attachmentId: "a-here" })],
      }),
    );
    render(<NodeAgentBadges nodeId="n1" />);
    fireEvent.click(screen.getByRole("button", { name: /Detach/i }));
    expect(closeChat).toHaveBeenCalled();
    expect(detach).toHaveBeenCalledWith("a-here");
  });

  it("renders nothing when no agent targets this node", () => {
    mockCtx.mockReturnValue(
      ctx({ attachments: [attachment({ target: { kind: "canvas" } })] }),
    );
    const { container } = render(<NodeAgentBadges nodeId="n1" />);
    expect(container).toBeEmptyDOMElement();
  });
});
