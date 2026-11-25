/**
 * Clear conversation's question says what the agent stays attached to: the
 * canvas, its node by name, or its connection by the two nodes it joins. It
 * said "this node" for every agent, a canvas agent's included.
 */
import React from "react";
import { render, screen } from "@testing-library/react";

import { ClearConversationDialog } from "../../components/agents/attach/chat/ClearConversationDialog";

describe("Clear conversation's question", () => {
  it.each([
    ["the canvas"],
    ["Load buildings"],
    ["the connection from Load buildings to Join blocks"],
  ])("says the agent stays attached to %s", (target) => {
    render(<ClearConversationDialog target={target} onConfirm={jest.fn()} onCancel={jest.fn()} />);
    const dialog = screen.getByRole("dialog", { name: "Clear this conversation?" });
    expect(dialog).toHaveTextContent(`The transcript goes; the agent stays attached to ${target}.`);
    expect(dialog).not.toHaveTextContent("this node");
  });
});
