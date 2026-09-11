/**
 * Agent avatars on a connection (#296).
 *
 * The twin of NodeAgentBadges.test.tsx, and deliberately asserting the same
 * accessible names: "Open chat with <name>" and "Detach <name>" are the
 * cross-surface contract that jest and Playwright both select on, so a
 * connection agent's chip has to answer to exactly what a node agent's does.
 */
import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";

const mockCtx = jest.fn();
jest.mock("../../components/agents/attach/AgentAttachmentsProvider", () => ({
  useAgentAttachmentsContext: () => mockCtx(),
}));

// EdgeLabelRenderer portals into a div React Flow only renders inside a live
// <ReactFlow>; outside one it returns null and would hide everything under test.
jest.mock("reactflow", () => ({
  EdgeLabelRenderer: ({ children }: any) => <>{children}</>,
}));

import { EdgeAgentBadges } from "../../components/agents/attach/EdgeAgentBadges";
import { EDGE_AGENT_BADGES_ATTR } from "../../utils/agentCatalogEvents";

function attachment(over: Partial<any> = {}): any {
  return {
    attachmentId: "att-1",
    coord: "agent.connection-builder@1.0.0",
    target: { kind: "connection", targetId: "edge-1" },
    sessionId: "s1",
    revision: 1,
    intent: null,
    intentEdited: false,
    title: null,
    titleEdited: false,
    name: "Connection Builder",
    category: "canvas",
    hooks: ["connection"],
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

const renderBadges = (edgeId = "edge-1") =>
  render(<EdgeAgentBadges edgeId={edgeId} labelX={120} labelY={80} />);

beforeEach(() => jest.clearAllMocks());

describe("EdgeAgentBadges", () => {
  it("renders nothing without a provider", () => {
    mockCtx.mockReturnValue(null);
    const { container } = renderBadges();
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing without an edge id", () => {
    // Rendered directly rather than through the helper: a default parameter
    // would substitute "edge-1" for the undefined this case is about.
    mockCtx.mockReturnValue(ctx({ attachments: [attachment()] }));
    const { container } = render(
      <EdgeAgentBadges edgeId={undefined} labelX={0} labelY={0} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when no agent is attached to this edge", () => {
    mockCtx.mockReturnValue(ctx({ attachments: [] }));
    const { container } = renderBadges();
    expect(container).toBeEmptyDOMElement();
  });

  it("shows only the agents attached to THIS connection", () => {
    mockCtx.mockReturnValue(
      ctx({
        attachments: [
          attachment({ attachmentId: "mine", name: "Mine" }),
          attachment({
            attachmentId: "other-edge",
            name: "OtherEdge",
            target: { kind: "connection", targetId: "edge-2" },
          }),
          attachment({
            attachmentId: "on-a-node",
            name: "OnANode",
            target: { kind: "node", targetId: "edge-1" },
          }),
          attachment({
            attachmentId: "on-canvas",
            name: "OnCanvas",
            target: { kind: "canvas" },
          }),
        ],
      }),
    );
    renderBadges();
    expect(screen.getByRole("button", { name: "Open chat with Mine" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Open chat with OtherEdge" })).toBeNull();
    // A node target whose targetId happens to equal an edge id must not match:
    // the kind is half of the key.
    expect(screen.queryByRole("button", { name: "Open chat with OnANode" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Open chat with OnCanvas" })).toBeNull();
  });

  it("opens the attachment's chat when the avatar is clicked", () => {
    const c = ctx({ attachments: [attachment()] });
    mockCtx.mockReturnValue(c);
    renderBadges();
    fireEvent.click(screen.getByRole("button", { name: "Open chat with Connection Builder" }));
    expect(c.openChat).toHaveBeenCalledWith("att-1");
  });

  it("closes the chat before detaching the attachment it was showing", () => {
    const c = ctx({ attachments: [attachment()], selectedId: "att-1" });
    mockCtx.mockReturnValue(c);
    renderBadges();
    fireEvent.click(screen.getByRole("button", { name: "Detach Connection Builder" }));
    expect(c.closeChat).toHaveBeenCalled();
    expect(c.detach).toHaveBeenCalledWith("att-1");
  });

  it("does not close the chat when detaching an attachment it was not showing", () => {
    const c = ctx({ attachments: [attachment()], selectedId: "someone-else" });
    mockCtx.mockReturnValue(c);
    renderBadges();
    fireEvent.click(screen.getByRole("button", { name: "Detach Connection Builder" }));
    expect(c.closeChat).not.toHaveBeenCalled();
    expect(c.detach).toHaveBeenCalledWith("att-1");
  });

  it("names its edge so a drop landing on the badge resolves to that connection", () => {
    mockCtx.mockReturnValue(ctx({ attachments: [attachment()] }));
    const { container } = renderBadges();
    const group = container.querySelector(`[${EDGE_AGENT_BADGES_ATTR}]`);
    expect(group?.getAttribute(EDGE_AGENT_BADGES_ATTR)).toBe("edge-1");
  });

  it("positions itself at the edge's label point", () => {
    mockCtx.mockReturnValue(ctx({ attachments: [attachment()] }));
    const { container } = renderBadges();
    const group = container.querySelector(`[${EDGE_AGENT_BADGES_ATTR}]`) as HTMLElement;
    expect(group.style.transform).toBe("translate(-50%, -50%) translate(120px, 80px)");
  });

  it("stands down from React Flow's pan and drag handlers", () => {
    mockCtx.mockReturnValue(ctx({ attachments: [attachment()] }));
    const { container } = renderBadges();
    const group = container.querySelector(`[${EDGE_AGENT_BADGES_ATTR}]`) as HTMLElement;
    expect(group.className).toContain("nopan");
    expect(group.className).toContain("nodrag");
  });
});
