/**
 * One Escape closes one layer of the agents' chat: the header's More menu, a
 * rail group's list of nodes, the Suggestions menu, or a dialog the chat
 * opened (Clear conversation, Edit initial intent), never the chat under it as
 * well.
 *
 * Each of them listens for Escape on `document` or on `window`, as the chat
 * does, so one Escape reaches every listener in turn. In a browser React
 * commits what one listener did before the next one runs (a trusted event
 * drains the microtasks after each listener), so the chat's listener, which
 * runs last, found the menu or the dialog closed already and its layer of the
 * modal stack let go, and closed the chat too. jsdom runs every listener
 * first, so here each keydown listener added on `window` or `document` commits
 * its updates as it returns (`flushSync`), as a browser does.
 * drawersOverDefine.test.tsx models a drawer's close the same way.
 *
 * The real chat panel, rail, More menu, ModalShell and Clear dialog; the flow
 * and the packages API are mocked.
 */
import React from "react";
import { flushSync } from "react-dom";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import "@testing-library/jest-dom";
import { MemoryRouter } from "react-router-dom";

jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({ playAllNodes: jest.fn(), projectDirty: false }),
}));
jest.mock("../../services/packages/packagesApi", () => ({
  packagesApi: { catalog: jest.fn(), listInstalled: jest.fn(), resolve: jest.fn() },
}));

import { AgentChatPanel } from "../../components/agents/attach/AgentChatPanel";
import { modalStackDepth } from "../../components/ModalShell";
import type { AgentAttachment } from "../../services/agents";

/** Each keydown listener as it was added, by the listener its caller gave. */
const committing = new WeakMap<EventListenerOrEventListenerObject, EventListener>();

/** From now on, every keydown listener added on *target* commits what it did
 *  as it returns, as a browser's microtask checkpoint after a listener does.
 *  Returns the undo. */
function commitAfterEachListener(target: Window | Document): () => void {
  const add: EventTarget["addEventListener"] = target.addEventListener;
  const remove: EventTarget["removeEventListener"] = target.removeEventListener;
  const asAdded = (listener: EventListenerOrEventListenerObject): EventListener => {
    let wrapped = committing.get(listener);
    if (!wrapped) {
      wrapped = (event: Event) => {
        if (typeof listener === "function") listener.call(target, event);
        else listener.handleEvent(event);
        flushSync(() => {});
      };
      committing.set(listener, wrapped);
    }
    return wrapped;
  };
  Object.defineProperty(target, "addEventListener", {
    configurable: true,
    writable: true,
    value: (type: string, listener: EventListenerOrEventListenerObject | null, options?: boolean | AddEventListenerOptions) =>
      add.call(target, type, type === "keydown" && listener ? asAdded(listener) : listener, options),
  });
  Object.defineProperty(target, "removeEventListener", {
    configurable: true,
    writable: true,
    value: (type: string, listener: EventListenerOrEventListenerObject | null, options?: boolean | EventListenerOptions) =>
      remove.call(target, type, type === "keydown" && listener ? committing.get(listener) ?? listener : listener, options),
  });
  return () => {
    Object.defineProperty(target, "addEventListener", { configurable: true, writable: true, value: add });
    Object.defineProperty(target, "removeEventListener", { configurable: true, writable: true, value: remove });
  };
}

let undo: Array<() => void> = [];

beforeEach(() => {
  undo = [commitAfterEachListener(window), commitAfterEachListener(document)];
});

afterEach(() => {
  // Unmounted while the listeners still come off through the wrappers.
  cleanup();
  for (const restore of undo) restore();
  undo = [];
});

const BUILDER: AgentAttachment = {
  attachmentId: "dfb",
  coord: "agent.curio.dataflow-builder@1",
  target: { kind: "canvas" as const },
  sessionId: "s1",
  revision: 1,
  name: "Dataflow Builder",
  category: "canvas",
  hooks: ["canvas"],
  intent: null,
  intentEdited: false,
  title: null,
  titleEdited: false,
};

const nodeBuilderOn = (attachmentId: string, targetId: string): AgentAttachment => ({
  ...BUILDER,
  attachmentId,
  coord: "agent.curio.node-builder@1",
  name: "Node Builder",
  category: "node",
  target: { kind: "node" as const, targetId },
});

/** The Dataflow Builder on the canvas, and a Node Builder on three nodes: one
 *  rail entry and one group. */
const ON_THE_DATAFLOW = [BUILDER, nodeBuilderOn("nb1", "load"), nodeBuilderOn("nb2", "heat"), nodeBuilderOn("nb3", "map")];

function renderChat(overrides: Partial<React.ComponentProps<typeof AgentChatPanel>> = {}) {
  const props: React.ComponentProps<typeof AgentChatPanel> = {
    attachment: BUILDER,
    turns: [],
    attachments: ON_THE_DATAFLOW,
    onOpenAgentChat: jest.fn(),
    onSend: jest.fn().mockResolvedValue(undefined),
    onClose: jest.fn(),
    onSaveTitle: jest.fn().mockResolvedValue(undefined),
    onClearConversation: jest.fn().mockResolvedValue(undefined),
    ...overrides,
  };
  return { ...render(<AgentChatPanel {...props} />, { wrapper: MemoryRouter }), props };
}

const chat = () => screen.getByRole("dialog", { name: /^Chat with / });
const escapeOn = (target: Element | Window | Document) => fireEvent.keyDown(target, { key: "Escape" });

test("Escape closes the header's More menu, and the chat stays open", () => {
  const { props } = renderChat();
  const more = screen.getByRole("button", { name: /^More/ });
  fireEvent.click(more);
  const menu = screen.getByRole("menu", { name: "Chat menu" });
  expect(modalStackDepth()).toBe(1);

  escapeOn(document.activeElement ?? menu);
  expect(screen.queryByRole("menu", { name: "Chat menu" })).toBeNull();
  expect(props.onClose).not.toHaveBeenCalled();
  expect(chat()).toBeInTheDocument();
  expect(more).toHaveFocus();
  expect(modalStackDepth()).toBe(0);

  // With the menu gone, the next Escape is the chat's.
  escapeOn(window);
  expect(props.onClose).toHaveBeenCalledTimes(1);
});

test("Escape closes a rail group's list of nodes, and the chat stays open", () => {
  const { props } = renderChat();
  const rail = screen.getByRole("navigation", { name: "Agents on this dataflow" });
  const group = within(rail).getByRole("button", { name: /^Node Builder on 3 nodes/ });
  fireEvent.click(group);
  expect(screen.getByRole("menu", { name: "Node Builder on" })).toBeInTheDocument();

  escapeOn(document.activeElement ?? group);
  expect(screen.queryByRole("menu", { name: "Node Builder on" })).toBeNull();
  expect(props.onClose).not.toHaveBeenCalled();
  expect(chat()).toBeInTheDocument();
  expect(group).toHaveFocus();

  escapeOn(window);
  expect(props.onClose).toHaveBeenCalledTimes(1);
});

test("a dialog the chat opened takes Escape alone, though the chat listened again after it opened", async () => {
  const { props, rerender } = renderChat();
  fireEvent.click(screen.getByRole("button", { name: /^More/ }));
  fireEvent.click(
    within(screen.getByRole("menu", { name: "Chat menu" })).getByRole("menuitem", { name: "Clear conversation…" }),
  );
  const dialog = await screen.findByRole("dialog", { name: "Clear this conversation?" });

  // The provider updates while the dialog is open. Its close is a new function
  // each time, so the chat adds its Escape listener again, after the dialog's.
  const closeNow = jest.fn();
  rerender(<AgentChatPanel {...props} onClose={closeNow} />);

  escapeOn(dialog);
  expect(screen.queryByRole("dialog", { name: "Clear this conversation?" })).toBeNull();
  expect(props.onClearConversation).not.toHaveBeenCalled();
  expect(closeNow).not.toHaveBeenCalled();
  expect(props.onClose).not.toHaveBeenCalled();
  expect(chat()).toBeInTheDocument();

  escapeOn(window);
  expect(closeNow).toHaveBeenCalledTimes(1);
});

test("Escape closes the Suggestions menu, and the chat stays open", () => {
  const { props } = renderChat({
    turns: [
      { role: "user", text: "Map the libraries." },
      { role: "agent", text: "Planned.", content: [{ type: "suggestedPrompts", primary: "Solve the plan", alternatives: ["Show the plan"] }] },
    ],
  });
  const button = screen.getByRole("button", { name: "2 suggestions" });
  fireEvent.click(button);
  const menu = screen.getByRole("menu", { name: "Suggested messages" });
  expect(modalStackDepth()).toBe(1);

  escapeOn(document.activeElement ?? menu);
  expect(screen.queryByRole("menu", { name: "Suggested messages" })).toBeNull();
  expect(props.onClose).not.toHaveBeenCalled();
  expect(chat()).toBeInTheDocument();
  expect(button).toHaveFocus();
  expect(modalStackDepth()).toBe(0);

  escapeOn(window);
  expect(props.onClose).toHaveBeenCalledTimes(1);
});

test("Escape closes the Edit initial intent dialog alone, and the chat stays open", async () => {
  const { props } = renderChat({ onSaveIntent: jest.fn().mockResolvedValue(undefined) });
  fireEvent.click(screen.getByRole("button", { name: /^More/ }));
  fireEvent.click(
    within(screen.getByRole("menu", { name: "Chat menu" })).getByRole("menuitem", { name: /^Edit initial intent…/ }),
  );
  const dialog = await screen.findByRole("dialog", { name: "Initial intent" });

  escapeOn(dialog);
  expect(screen.queryByRole("dialog", { name: "Initial intent" })).toBeNull();
  expect(props.onSaveIntent).not.toHaveBeenCalled();
  expect(props.onClose).not.toHaveBeenCalled();
  expect(chat()).toBeInTheDocument();

  escapeOn(window);
  expect(props.onClose).toHaveBeenCalledTimes(1);
});
