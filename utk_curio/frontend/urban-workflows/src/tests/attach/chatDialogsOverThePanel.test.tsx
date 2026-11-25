/**
 * The questions the chat asks open over the chat.
 *
 * The panel sits at z-index 1100, above ModalShell's default layer (500), so
 * Clear conversation's question and the question before an agent's link
 * leaves unsaved work opened under the panel's left edge: their right half,
 * with the button that answers yes, was under the chat. A dialog opened from
 * a drawer takes ModalShell's overlay layer, which is above every drawer.
 */
import fs from "fs";
import path from "path";
import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

let mockProjectDirty = false;
jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({ playAllNodes: jest.fn(), projectDirty: mockProjectDirty }),
}));
jest.mock("../../services/packages/packagesApi", () => ({ packagesApi: {} }));

import { AgentChatPanel } from "../../components/agents/attach/AgentChatPanel";
import { ClearConversationDialog } from "../../components/agents/attach/chat/ClearConversationDialog";
import type { AgentAttachment } from "../../services/agents";

const SRC = path.resolve(__dirname, "../..");
const read = (rel: string) => fs.readFileSync(path.join(SRC, rel), "utf8");

/** Jest maps CSS modules to identity-obj-proxy: a ModalShell on the overlay
 *  layer carries the class `modalOverlay`. */
const OVERLAY = "modalOverlay";

const attachment: AgentAttachment = {
  attachmentId: "a1",
  coord: "agent.test.my-explainer@1",
  target: { kind: "canvas" as const },
  sessionId: "s1234567890",
  revision: 1,
  name: "My Explainer",
  category: "node",
  hooks: ["node"],
  intent: null,
  intentEdited: false,
  title: null,
  titleEdited: false,
};

afterEach(() => {
  mockProjectDirty = false;
});

describe("the chat's questions", () => {
  it("are asked on a layer above the chat panel", () => {
    const panelZ = /\n\.panel \{[^}]*\n\s*z-index:\s*(\d+);/.exec(
      read("components/agents/attach/AgentChatPanel.module.css"),
    );
    const tokens = read("styles/curioTokens.css");
    const layer = (name: string) => Number(new RegExp(`${name}:\\s*(\\d+);`).exec(tokens)?.[1]);
    expect(panelZ).not.toBeNull();
    expect(layer("--curio-z-modal")).toBeGreaterThan(Number(panelZ![1]));
    expect(layer("--curio-z-modal-backdrop")).toBeGreaterThan(Number(panelZ![1]));
    // The default layer is under it, which is why each question asks for the overlay.
    expect(layer("--curio-z-modal-base")).toBeLessThan(Number(panelZ![1]));
  });

  it("Clear conversation's question is on that layer", () => {
    render(<ClearConversationDialog target="the canvas" onConfirm={jest.fn()} onCancel={jest.fn()} />);
    expect(screen.getByRole("dialog", { name: "Clear this conversation?" }).className).toContain(OVERLAY);
  });

  it("the question before an agent's link leaves unsaved work is on that layer", () => {
    mockProjectDirty = true;
    render(
      <AgentChatPanel
        attachment={attachment}
        turns={[{ role: "agent", text: "See [Bike Routes](/catalog/data/imported.bikes)." }]}
        onSend={jest.fn().mockResolvedValue(undefined)}
        onClose={jest.fn()}
      />,
      { wrapper: MemoryRouter },
    );
    fireEvent.click(screen.getByRole("link", { name: "Bike Routes" }));
    expect(screen.getByRole("dialog", { name: "Discard unsaved changes?" }).className).toContain(OVERLAY);
  });
});
