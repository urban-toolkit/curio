/**
 * The chat panel slides, and the four ways that could go wrong (#295).
 *
 * The panel was the one right-hand surface in the product that appeared and
 * vanished instantly while its three catalog-drawer peers slid. Giving it the
 * same motion is easy; the reason this file exists is that a panel which stays
 * mounted through its own exit has failure modes an instant one cannot have.
 */
import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";

import styles from "../../components/agents/attach/AgentChatPanel.module.css";

jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({ projectId: "p1", workflowNameRef: { current: "wf" } }),
}));
jest.mock("../../api/packagesApi", () => ({ packagesApi: {} }));

import { AgentChatPanel } from "../../components/agents/attach/AgentChatPanel";

function attachment(over: Partial<any> = {}): any {
  return {
    attachmentId: "att-1",
    coord: "agent.chat-agent@1.0.0",
    target: { kind: "canvas" },
    sessionId: "s1",
    revision: 1,
    intent: null,
    intentEdited: false,
    title: null,
    titleEdited: false,
    name: "Chat",
    category: "canvas",
    hooks: ["canvas"],
    ...over,
  };
}

function renderPanel(props: Partial<any> = {}) {
  const onClose = jest.fn();
  const onExitComplete = jest.fn();
  const result = render(
    <AgentChatPanel
      attachment={attachment()}
      turns={[]}
      onSend={jest.fn()}
      onClose={onClose}
      onExitComplete={onExitComplete}
      {...props}
    />,
  );
  return { ...result, onClose, onExitComplete };
}

const panelEl = () => screen.getByRole("dialog", { hidden: true });

describe("AgentChatPanel presentation", () => {
  it("carries the presented class once it is at rest", () => {
    renderPanel({ presented: true });
    expect(panelEl().className).toContain(styles.panelPresented);
  });

  it("is off-screen and hidden from assistive tech while not presented", () => {
    // Mounted-but-closed is a real state now: it is how the slide gets a
    // starting point, and it is the whole of the exit.
    renderPanel({ presented: false });
    const panel = panelEl();
    expect(panel.className).not.toContain(styles.panelPresented);
    expect(panel).toHaveAttribute("aria-hidden", "true");
  });

  it("reports its exit on its OWN transform transition", () => {
    const { onExitComplete } = renderPanel({ presented: false });
    fireEvent.transitionEnd(panelEl(), { propertyName: "transform" });
    expect(onExitComplete).toHaveBeenCalledTimes(1);
  });

  it("ignores a transition that finished on something inside it", () => {
    // The panel is full of inner transitions - bubbles, chips, the run status
    // line - and every one of them bubbles a transitionend to this element. An
    // unguarded handler unmounted the panel the moment any child settled,
    // halfway through the slide.
    const { onExitComplete } = renderPanel({ presented: false });
    const inner = panelEl().querySelector("*") as HTMLElement;
    expect(inner).toBeTruthy();
    fireEvent.transitionEnd(inner, { propertyName: "transform" });
    expect(onExitComplete).not.toHaveBeenCalled();
  });

  it("ignores a transition of any property other than transform", () => {
    const { onExitComplete } = renderPanel({ presented: false });
    fireEvent.transitionEnd(panelEl(), { propertyName: "opacity" });
    expect(onExitComplete).not.toHaveBeenCalled();
  });

  it("does not report an exit while it is still open", () => {
    // The enter slide ends with a transform transitionend too. Reporting that
    // as an exit would unmount the panel the instant it finished arriving.
    const { onExitComplete } = renderPanel({ presented: true });
    fireEvent.transitionEnd(panelEl(), { propertyName: "transform" });
    expect(onExitComplete).not.toHaveBeenCalled();
  });

  it("Escape closes an open panel", () => {
    const { onClose } = renderPanel({ presented: true });
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("Escape is a no-op while the panel is sliding out", () => {
    // It is still mounted, so the listener is still attached. Closing
    // something already closing restarts the fallback timer against a panel
    // nobody can see.
    const { onClose } = renderPanel({ presented: false });
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).not.toHaveBeenCalled();
  });
});
