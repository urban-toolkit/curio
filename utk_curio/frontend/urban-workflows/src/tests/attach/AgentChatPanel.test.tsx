import React from "react";
import { render, screen, fireEvent, waitFor, act, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

// The dev/52 builder strip imports useFlowContext; mocking the provider keeps
// FlowProvider's heavy module graph (vega etc.) out of this presentational
// suite — the strip itself is covered by AgentBuilderStrip.test.tsx.
let mockProjectDirty = false;
jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({ playAllNodes: jest.fn(), projectDirty: mockProjectDirty }),
}));

// dev/84: the package-install review flow loads the catalog + conflict probe;
// mocked so the panel suite stays network-free.
jest.mock("../../services/packages/packagesApi", () => ({
  packagesApi: { catalog: jest.fn(), listInstalled: jest.fn(), resolve: jest.fn() },
}));
import { packagesApi } from "../../services/packages/packagesApi";

import { AgentChatPanel } from "../../components/agents/attach/AgentChatPanel";
import { GOAL_EMPTY, GOAL_PLACEHOLDER, GOAL_TOOLTIP } from "../../components/agents/attach/chat/GoalLine";
import { modalStackDepth } from "../../components/ModalShell";
import { BUILDER_TEMPLATES, BUILD_RUNNING_HINT, type AgentAttachment, type AgentSessionTurn } from "../../services/agents";

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

const noTurns: AgentSessionTurn[] = [];

// What the shipped cards declare in their manifests: the panel offers each of
// its features to any agent that declares the capability behind it.
const NODE_BUILDER_CAPABILITIES = [
  "node.build",
  "dataset.fetch.author",
  "node.content.generate",
  "package.recommend",
  "package.build",
  "package.extend",
  "node.kind.author",
];
const DATASET_FINDER_CAPABILITIES = ["dataset.discover", "dataset.select"];
const DATAFLOW_BUILDER_CAPABILITIES = ["dataflow.orchestrate"];

function renderPanel(overrides: Partial<React.ComponentProps<typeof AgentChatPanel>> = {}) {
  const props: React.ComponentProps<typeof AgentChatPanel> = {
    attachment,
    turns: noTurns,
    onSend: jest.fn().mockResolvedValue(undefined),
    onClose: jest.fn(),
    ...overrides,
  };
  // The panel routes an agent's links to Curio pages, so it needs a router.
  return { ...render(<AgentChatPanel {...props} />, { wrapper: MemoryRouter }), props };
}

describe("an agent's link to a Curio page", () => {
  afterEach(() => {
    mockProjectDirty = false;
  });

  it("asks before leaving a dataflow with unsaved changes", () => {
    mockProjectDirty = true;
    renderPanel({
      turns: [{ role: "agent", text: "See [Bike Routes](/catalog/data/imported.bikes)." }],
    });
    fireEvent.click(screen.getByRole("link", { name: "Bike Routes" }));
    expect(screen.getByRole("dialog", { name: "Discard unsaved changes?" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Stay here" }));
    expect(screen.queryByRole("dialog", { name: "Discard unsaved changes?" })).toBeNull();
  });

  it("goes without asking when nothing is unsaved", () => {
    renderPanel({
      turns: [{ role: "agent", text: "See [Bike Routes](/catalog/data/imported.bikes)." }],
    });
    fireEvent.click(screen.getByRole("link", { name: "Bike Routes" }));
    expect(screen.queryByRole("dialog", { name: "Discard unsaved changes?" })).toBeNull();
  });
});

/** The header, one row: the glyph, the title, what the agent is attached to,
 *  More and Close. */
const chatHeader = () => document.querySelector<HTMLElement>('[data-curio-chat-header="true"]')!;
/** The header's words for what the agent is attached to. */
const chatTarget = () => document.querySelector<HTMLElement>("[data-curio-chat-target]")!;
/** Opens the header's More menu. */
const openMore = () => {
  fireEvent.click(screen.getByRole("button", { name: /^More/ }));
  return screen.getByRole("menu", { name: "Chat menu" });
};

describe("AgentChatPanel", () => {
  it("renders the concept header on one row: name, target, More and Close", () => {
    renderPanel({ onClearConversation: jest.fn() });
    const header = chatHeader();
    expect(within(header).getByText("My Explainer")).toBeInTheDocument();
    expect(chatTarget()).toHaveTextContent(/^on the canvas$/);
    expect(header.contains(chatTarget())).toBe(true);
    expect(within(header).getByRole("button", { name: /^More/ })).toBeInTheDocument();
    expect(within(header).getByRole("button", { name: "Close chat" })).toBeInTheDocument();
    // One row: no second line under it, and no arrows or "n / m" counter.
    expect(screen.queryByText(/attached to/i)).toBeNull();
    expect(screen.queryByRole("button", { name: "Previous agent" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Next agent" })).toBeNull();
    expect(screen.queryByText(/^\d+ \/ \d+$/)).toBeNull();
  });

  // #228: the header used to read "Attached to node 6bea6863-…" beside a
  // "session s1234567" chip. Neither told the user which node they were talking
  // to. Both ids are diagnostic, so they moved into the tooltip.
  it("names the node it is attached to instead of showing its id", () => {
    renderPanel({
      attachment: {
        ...attachment,
        target: { kind: "node" as const, targetId: "6bea6863-1f2e-4a11-9b0c-77d2e3f4a5b6" },
      },
      targetName: "Data Loading",
    });
    expect(chatTarget()).toHaveTextContent(/^on Data Loading$/);
    expect(screen.queryByText(/6bea6863/)).toBeNull();
  });

  it("names a connection by the two nodes it joins", () => {
    renderPanel({
      attachment: {
        ...attachment,
        target: { kind: "connection" as const, targetId: "reactflow__edge-7f3a2b1c" },
      },
      targetName: "from Load buildings to Join blocks",
    });
    expect(chatTarget()).toHaveTextContent(/^from Load buildings to Join blocks$/);
    expect(chatHeader()).not.toHaveTextContent("reactflow__edge-7f3a2b1c");
    expect(chatTarget()).toHaveAttribute("data-tooltip", expect.stringContaining("connection reactflow__edge-7f3a2b1c"));
  });

  it("falls back to the target kind and id when the node cannot be named", () => {
    renderPanel({
      attachment: {
        ...attachment,
        target: { kind: "node" as const, targetId: "6bea6863" },
      },
      targetName: null,
    });
    expect(chatTarget()).toHaveTextContent(/^on node 6bea6863$/);
  });

  it("keeps the session id available as a tooltip, not as header text", () => {
    renderPanel();
    expect(screen.queryByText(/session s1234567/)).toBeNull();
    expect(chatTarget()).toHaveAttribute(
      "data-tooltip",
      expect.stringContaining("session s1234567890") as unknown as string,
    );
  });

  it("sends the trimmed message through onSend", async () => {
    const onSend = jest.fn().mockResolvedValue(undefined);
    renderPanel({ onSend });
    fireEvent.change(screen.getByPlaceholderText(/^Message /), {
      target: { value: "  explain this  " },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(onSend).toHaveBeenCalledWith("explain this");
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Send" })).toBeDisabled(),
    );
  });

  // ── Multiline composer (memo dev/77): Enter sends, Shift+Enter stays a
  //    newline, pasted/typed line breaks reach onSend intact. ──

  it("Enter sends the message with interior newlines preserved", async () => {
    const onSend = jest.fn().mockResolvedValue(undefined);
    renderPanel({ onSend });
    const composer = screen.getByPlaceholderText(/^Message /);
    // jsdom's paste-equivalent: the value lands with its \n intact.
    fireEvent.change(composer, { target: { value: "line1\n\nline3\n" } });
    fireEvent.keyDown(composer, { key: "Enter" });
    expect(onSend).toHaveBeenCalledWith("line1\n\nline3");
    await waitFor(() => expect(composer).toHaveValue(""));
  });

  it("Shift+Enter does not send", () => {
    const onSend = jest.fn().mockResolvedValue(undefined);
    renderPanel({ onSend });
    const composer = screen.getByPlaceholderText(/^Message /);
    fireEvent.change(composer, { target: { value: "draft" } });
    fireEvent.keyDown(composer, { key: "Enter", shiftKey: true });
    expect(onSend).not.toHaveBeenCalled();
    expect(composer).toHaveValue("draft");
  });

  it("Enter during an IME composition does not send", () => {
    const onSend = jest.fn().mockResolvedValue(undefined);
    renderPanel({ onSend });
    const composer = screen.getByPlaceholderText(/^Message /);
    fireEvent.change(composer, { target: { value: "変換中" } });
    fireEvent.keyDown(composer, { key: "Enter", isComposing: true });
    expect(onSend).not.toHaveBeenCalled();
  });

  it("whitespace/newline-only input never sends", () => {
    const onSend = jest.fn().mockResolvedValue(undefined);
    renderPanel({ onSend });
    const composer = screen.getByPlaceholderText(/^Message /);
    fireEvent.change(composer, { target: { value: " \n \n " } });
    fireEvent.keyDown(composer, { key: "Enter" });
    expect(onSend).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
  });

  it("a user turn containing newlines keeps them in the transcript text", () => {
    renderPanel({ turns: [{ role: "user", text: "first\nsecond" }] });
    const bubble = screen.getByText((_, el) => el?.textContent === "first\nsecond");
    expect(bubble.className).toMatch(/msgUser/);
  });

  it("renders provided turns: user bubble, agent row, error tone", () => {
    renderPanel({
      turns: [
        { role: "user", text: "q1" },
        { role: "agent", text: "a1" },
        { role: "agent", text: "(error) boom", error: true },
      ],
    });
    expect(screen.getByText("q1")).toBeInTheDocument();
    expect(screen.getByText("a1")).toBeInTheDocument();
    const err = screen.getByText("(error) boom");
    expect(err.className).toMatch(/msgError/);
  });

  it("Send is disabled on empty input", () => {
    renderPanel();
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
  });

  it("the composer names the agent it messages, by the agent's own name", () => {
    renderPanel({ attachment: { ...attachment, title: "Dataset Import Help" } });
    const box = screen.getByRole("textbox", { name: "Message My Explainer" });
    expect(box).toHaveAttribute("placeholder", "Message My Explainer…");
  });

  it("the close button closes without detaching", () => {
    const onClose = jest.fn();
    renderPanel({ onClose });
    fireEvent.click(screen.getByRole("button", { name: "Close chat" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("Escape closes the panel", () => {
    const onClose = jest.fn();
    renderPanel({ onClose });
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("shows the prompt-sourced initial intent, with a placeholder when absent", () => {
    renderPanel();
    expect(screen.getByText(attachment.intent as string)).toBeInTheDocument();
    renderPanel({ attachment: { ...attachment, intent: null } });
    expect(screen.getByText(/no instruction prompt available/i)).toBeInTheDocument();
  });

  it("renders the intent as the first message, clamped with a show more/less toggle", () => {
    const long = "x".repeat(400);
    renderPanel({ attachment: { ...attachment, intent: long, intentEdited: true } });
    const bubble = screen.getByText(long);
    expect(bubble.className).toMatch(/msgUser/); // plain first-message styling
    const toggle = screen.getByRole("button", { name: /show more/i });
    fireEvent.click(toggle);
    expect(screen.getByRole("button", { name: /show less/i })).toBeInTheDocument();
  });

  it("edits the intent: save sends the draft; an emptied draft sends null", async () => {
    const onSaveIntent = jest.fn().mockResolvedValue(undefined);
    renderPanel({ onSaveIntent });
    fireEvent.click(screen.getByRole("button", { name: "Edit initial intent" }));
    const textarea = screen.getByRole("textbox", { name: /initial intent/i });
    fireEvent.change(textarea, { target: { value: "focus on cost" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(onSaveIntent).toHaveBeenCalledWith("focus on cost");
    await waitFor(() =>
      expect(screen.queryByRole("textbox", { name: /initial intent/i })).not.toBeInTheDocument(),
    );

    fireEvent.click(screen.getByRole("button", { name: "Edit initial intent" }));
    fireEvent.change(screen.getByRole("textbox", { name: /initial intent/i }), {
      target: { value: "   " },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(onSaveIntent).toHaveBeenLastCalledWith(null);
  });

  it("shows history loading and a retryable history error", () => {
    renderPanel({ loadingHistory: true });
    expect(screen.getByText(/loading conversation/i)).toBeInTheDocument();

    const onRetryHistory = jest.fn();
    renderPanel({ historyError: "boom", onRetryHistory });
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(onRetryHistory).toHaveBeenCalled();
  });

  // This used to spy on `window.confirm`. The panel raises the app's own
  // ConfirmDialog now (#197), so the assertion is that a dialog appears and
  // that confirming it is what runs the clear - not that the browser was asked.
  it("clear conversation asks in the app's own dialog, from More", async () => {
    const onClearConversation = jest.fn().mockResolvedValue(undefined);
    const confirmSpy = jest.spyOn(window, "confirm");
    renderPanel({ onClearConversation });
    fireEvent.click(within(openMore()).getByRole("menuitem", { name: "Clear conversation…" }));
    // Choosing it closes the menu.
    expect(screen.queryByRole("menu", { name: "Chat menu" })).toBeNull();

    const modal = await waitFor(() => {
      const el = document.querySelector('[data-curio-modal-shell="true"]');
      if (!el) throw new Error("no confirmation dialog is open");
      return el as HTMLElement;
    });
    expect(onClearConversation).not.toHaveBeenCalled();
    fireEvent.click(within(modal).getByRole("button", { name: "Clear" }));
    await waitFor(() => expect(onClearConversation).toHaveBeenCalledTimes(1));
    expect(confirmSpy).not.toHaveBeenCalled();
    confirmSpy.mockRestore();
  });

  it("cancelling the clear leaves the transcript alone", async () => {
    const onClearConversation = jest.fn().mockResolvedValue(undefined);
    renderPanel({ onClearConversation });
    fireEvent.click(within(openMore()).getByRole("menuitem", { name: "Clear conversation…" }));
    const modal = await waitFor(() => {
      const el = document.querySelector('[data-curio-modal-shell="true"]');
      if (!el) throw new Error("no confirmation dialog is open");
      return el as HTMLElement;
    });
    fireEvent.click(within(modal).getByRole("button", { name: "Keep it" }));
    await waitFor(() =>
      expect(document.querySelector('[data-curio-modal-shell="true"]')).toBeNull(),
    );
    expect(onClearConversation).not.toHaveBeenCalled();
  });

  it.each([
    ["a canvas agent", attachment, null, "the canvas"],
    ["a node agent", { ...attachment, target: { kind: "node" as const, targetId: "n1" } }, "Data Loading", "Data Loading"],
    [
      "a connection agent",
      { ...attachment, target: { kind: "connection" as const, targetId: "e1" } },
      "from Load buildings to Join blocks",
      "the connection from Load buildings to Join blocks",
    ],
  ])("the clear question names what %s stays attached to", async (_who, agent, targetName, words) => {
    renderPanel({ attachment: agent, targetName, onClearConversation: jest.fn() });
    fireEvent.click(within(openMore()).getByRole("menuitem", { name: "Clear conversation…" }));
    const dialog = await screen.findByRole("dialog", { name: "Clear this conversation?" });
    expect(dialog).toHaveTextContent(`The transcript goes; the agent stays attached to ${words}.`);
  });
});

/** Three agents on one dataflow, a Node Builder on three nodes among them. */
const builderOn = (attachmentId: string, targetId: string): AgentAttachment => ({
  ...attachment,
  attachmentId,
  coord: "agent.curio.node-builder@1",
  name: "Node Builder",
  target: { kind: "node" as const, targetId },
});
const RAIL_ATTACHMENTS: AgentAttachment[] = [
  { ...attachment, attachmentId: "dfb", coord: "agent.curio.dataflow-builder@1", name: "Dataflow Builder", category: "canvas" },
  { ...attachment, attachmentId: "df1", coord: "agent.curio.dataset-finder@1", name: "Dataset Finder", category: "data", target: { kind: "node" as const, targetId: "load" } },
  builderOn("nb1", "load"),
  { ...attachment, attachmentId: "df2", coord: "agent.curio.dataset-finder@1", name: "Dataset Finder", category: "data", target: { kind: "node" as const, targetId: "heat" } },
  builderOn("nb2", "heat"),
  builderOn("nb3", "map"),
];
const NODE_NAMES: Record<string, string> = { load: "Load buildings", heat: "Load heat", map: "Heat map" };
const railTargetNameOf = (a: AgentAttachment) =>
  a.target.kind === "node" ? NODE_NAMES[a.target.targetId ?? ""] ?? null : null;

function renderRail(open: AgentAttachment, overrides: Partial<React.ComponentProps<typeof AgentChatPanel>> = {}) {
  const onOpenAgentChat = jest.fn();
  const utils = renderPanel({
    attachment: open,
    attachments: RAIL_ATTACHMENTS,
    targetNameOf: railTargetNameOf,
    targetName: railTargetNameOf(open),
    onOpenAgentChat,
    ...overrides,
  });
  return { ...utils, onOpenAgentChat, rail: screen.getByRole("navigation", { name: "Agents on this dataflow" }) };
}

describe("AgentChatPanel's agents rail", () => {
  it("lists every agent in the attachments' order, an agent on three nodes or more as one entry", () => {
    const { rail } = renderRail(RAIL_ATTACHMENTS[0]);
    const entries = within(rail).getAllByRole("button");
    expect(entries.map((entry) => entry.getAttribute("aria-label"))).toEqual([
      "Dataflow Builder on the canvas",
      "Dataset Finder on Load buildings",
      "Node Builder on 3 nodes",
      "Dataset Finder on Load heat",
    ]);
    // Hovering an entry names what it is attached to.
    expect(entries[1]).toHaveAttribute("data-tooltip", "Dataset Finder on Load buildings");
    expect(within(entries[1]).getByText("Load buildings")).toBeInTheDocument();
    // The group shows how many it holds.
    expect(entries[2]).toHaveTextContent("3");
    expect(entries[2]).toHaveAttribute("aria-haspopup", "menu");
  });

  it("marks the open chat's entry, and only it", () => {
    const { rail } = renderRail(RAIL_ATTACHMENTS[3]);
    const current = within(rail).getAllByRole("button").filter((entry) => entry.getAttribute("aria-current") === "true");
    expect(current.map((entry) => entry.getAttribute("aria-label"))).toEqual(["Dataset Finder on Load heat"]);
  });

  it("opens each agent's chat from its entry", () => {
    const { rail, onOpenAgentChat } = renderRail(RAIL_ATTACHMENTS[0]);
    fireEvent.click(within(rail).getByRole("button", { name: "Dataset Finder on Load buildings" }));
    expect(onOpenAgentChat).toHaveBeenCalledWith("df1");
    fireEvent.click(within(rail).getByRole("button", { name: "Dataset Finder on Load heat" }));
    expect(onOpenAgentChat).toHaveBeenLastCalledWith("df2");
  });

  it("a group opens the list of its nodes, each opening that node's chat", () => {
    const { rail, onOpenAgentChat } = renderRail(RAIL_ATTACHMENTS[0]);
    const group = within(rail).getByRole("button", { name: "Node Builder on 3 nodes" });
    expect(group).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(group);
    expect(group).toHaveAttribute("aria-expanded", "true");
    const list = screen.getByRole("menu", { name: "Node Builder on" });
    expect(within(list).getAllByRole("menuitem").map((row) => row.textContent)).toEqual([
      "Load buildings",
      "Load heat",
      "Heat map",
    ]);
    expect(within(list).getByRole("menuitem", { name: "Load heat" })).toHaveAttribute(
      "data-tooltip",
      "Node Builder on Load heat",
    );
    fireEvent.click(within(list).getByRole("menuitem", { name: "Heat map" }));
    expect(onOpenAgentChat).toHaveBeenCalledWith("nb3");
    expect(screen.queryByRole("menu", { name: "Node Builder on" })).toBeNull();
  });

  it("marks a group open on one of its nodes, and names that node", () => {
    const { rail } = renderRail(RAIL_ATTACHMENTS[4]);
    const group = within(rail).getByRole("button", { name: /^Node Builder on 3 nodes/ });
    expect(group).toHaveAttribute("aria-current", "true");
    expect(group).toHaveAccessibleName("Node Builder on 3 nodes, open on Load heat");
    expect(within(group).getByText("Load heat")).toBeInTheDocument();
    fireEvent.click(group);
    expect(within(screen.getByRole("menu", { name: "Node Builder on" })).getByRole("menuitem", { name: "Load heat" }))
      .toHaveAttribute("aria-current", "true");
  });

  it("keeps an agent attached twice as two entries", () => {
    const { rail } = renderRail(RAIL_ATTACHMENTS[0], { attachments: RAIL_ATTACHMENTS.slice(0, 5) });
    expect(within(rail).getAllByRole("button", { name: /^Node Builder on Load/ })).toHaveLength(2);
    expect(within(rail).queryByRole("button", { name: /^Node Builder on \d+ nodes/ })).toBeNull();
  });

  it("Escape closes a group's list, not the chat", () => {
    const onClose = jest.fn();
    const { rail } = renderRail(RAIL_ATTACHMENTS[0], { onClose });
    fireEvent.click(within(rail).getByRole("button", { name: "Node Builder on 3 nodes" }));
    expect(screen.getByRole("menu", { name: "Node Builder on" })).toBeInTheDocument();
    fireEvent.keyDown(document.activeElement ?? window, { key: "Escape" });
    expect(screen.queryByRole("menu", { name: "Node Builder on" })).toBeNull();
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("shows an agent at work with its running dot, named on its entry", () => {
    const working: Record<string, string> = {
      df2: "Dataset Finder (asked by Ana)",
      nb3: "Node Builder (asked by Ana), editing Heat map",
    };
    const { rail } = renderRail(RAIL_ATTACHMENTS[0], { workingOf: (a) => working[a.attachmentId] ?? null });
    const entry = within(rail).getByRole("button", { name: "Dataset Finder on Load heat, at work" });
    // The running dot is the entry's one image: the glyph's icon beside it is
    // hidden from the accessibility tree, though it carries role="img" too.
    const images = (el: HTMLElement) => within(el).queryAllByRole("img").map((dot) => dot.getAttribute("aria-label"));
    expect(images(entry)).toEqual(["Dataset Finder (asked by Ana)"]);
    expect(images(within(rail).getByRole("button", { name: "Dataset Finder on Load buildings" }))).toEqual([]);
    // A group shows it when any of its nodes is at work, and its list says which.
    const group = within(rail).getByRole("button", { name: "Node Builder on 3 nodes, one at work" });
    expect(images(group)).toEqual(["Node Builder (asked by Ana), editing Heat map"]);
    fireEvent.click(group);
    const list = screen.getByRole("menu", { name: "Node Builder on" });
    expect(within(list).getByRole("menuitem", { name: /^Heat map/ })).toHaveTextContent("Heat mapat work");
    expect(within(list).getByRole("menuitem", { name: "Load heat" })).not.toHaveTextContent("at work");
  });

  it("without a caller's own rule, an agent solving in the background is at work", () => {
    const solving = { ...RAIL_ATTACHMENTS[1], liveJob: { executionId: "e1", kind: "solve-node", status: "running" as const, startedAt: 1 } };
    const { rail } = renderRail(RAIL_ATTACHMENTS[0], { attachments: [RAIL_ATTACHMENTS[0], solving] });
    expect(within(rail).getByRole("button", { name: "Dataset Finder on Load buildings, at work" })).toBeInTheDocument();
  });

  it("shows an agent that waits for you with its dot, named on its entry; a group shows it when any of its nodes waits", () => {
    // The listing says who waits for the user to pick a node's source: here
    // the second loader's Dataset Finder, and the Node Builder whose Solve of
    // Heat map asked for candidates.
    const waits: Record<string, string[]> = { df2: ["heat"], nb3: ["map"] };
    const attachments = RAIL_ATTACHMENTS.map((a) => ({ ...a, waitsForYou: waits[a.attachmentId] ?? [] }));
    const { rail } = renderRail(attachments[0], { attachments });
    const images = (el: HTMLElement) => within(el).queryAllByRole("img").map((dot) => dot.getAttribute("aria-label"));
    const entry = within(rail).getByRole("button", { name: "Dataset Finder on Load heat, waits for you" });
    expect(images(entry)).toEqual(["Waits for you"]);
    expect(images(within(rail).getByRole("button", { name: "Dataset Finder on Load buildings" }))).toEqual([]);
    const group = within(rail).getByRole("button", { name: "Node Builder on 3 nodes, one waits for you" });
    expect(images(group)).toEqual(["Waits for you"]);
    // Its list says which.
    fireEvent.click(group);
    const list = screen.getByRole("menu", { name: "Node Builder on" });
    expect(within(list).getByRole("menuitem", { name: /^Heat map/ })).toHaveTextContent("Heat mapwaits for you");
    expect(within(list).getByRole("menuitem", { name: "Load heat" })).not.toHaveTextContent("waits for you");
  });

  it("no rail without the dataflow's agents", () => {
    renderPanel();
    expect(screen.queryByRole("navigation", { name: "Agents on this dataflow" })).toBeNull();
  });

  it("tells two instances of one agent apart: by the conversation's title, and on one place by number", () => {
    const finder = (attachmentId: string, title: string | null = null): AgentAttachment => ({
      ...attachment,
      attachmentId,
      coord: "agent.curio.dataset-finder@1",
      name: "Dataset Finder",
      category: "data",
      title,
    });
    // Two untitled Dataset Finders on the canvas.
    const twins = renderRail(RAIL_ATTACHMENTS[0], { attachments: [RAIL_ATTACHMENTS[0], finder("f1"), finder("f2")] });
    const names = within(twins.rail).getAllByRole("button").map((entry) => entry.getAttribute("aria-label"));
    expect(new Set(names).size).toBe(names.length);
    expect(names).toEqual([
      "Dataflow Builder on the canvas",
      "Dataset Finder (1) on the canvas",
      "Dataset Finder (2) on the canvas",
    ]);
    twins.unmount();

    // A titled conversation is named as the dock's badge names it, on its
    // tooltip and in its name; its label is its agent's name, as every entry's.
    const titled = renderRail(RAIL_ATTACHMENTS[0], { attachments: [RAIL_ATTACHMENTS[0], finder("f1", "Parks"), finder("f2")] });
    const parks = within(titled.rail).getByRole("button", { name: "Dataset Finder: Parks on the canvas" });
    expect(parks).toHaveAttribute("data-tooltip", "Dataset Finder: Parks on the canvas");
    expect(within(parks).getByText("Dataset Finder")).toBeInTheDocument();
    expect(parks).not.toHaveTextContent("Parks");
    expect(within(titled.rail).getByRole("button", { name: "Dataset Finder on the canvas" })).toBeInTheDocument();
    titled.unmount();

    // In a group's list: two untitled on one node, and one titled.
    const group = [
      RAIL_ATTACHMENTS[0],
      builderOn("nb1", "load"),
      builderOn("nb2", "heat"),
      builderOn("nb3", "heat"),
      { ...builderOn("nb4", "heat"), title: "Heat colors" },
    ];
    const { rail } = renderRail(group[3], { attachments: group });
    const entry = within(rail).getByRole("button", { name: /^Node Builder on 4 nodes/ });
    expect(entry).toHaveAccessibleName("Node Builder on 4 nodes, open on Load heat (2)");
    fireEvent.click(entry);
    const rows = within(screen.getByRole("menu", { name: "Node Builder on" })).getAllByRole("menuitem");
    expect(rows.map((row) => row.textContent)).toEqual([
      "Load buildings",
      "Load heat (1)",
      "Load heat (2)",
      "Load heat: Heat colors",
    ]);
    expect(rows[3]).toHaveAttribute("data-tooltip", "Node Builder: Heat colors on Load heat");
  });

  // The boards label each entry with its agent's name, over what it is
  // attached to in smaller type; the conversation's title is on its tooltip.
  // How the label wraps is agentRailLabels.test.ts's.
  it("labels each entry with its agent's name over what it is attached to, its conversation's title on its tooltip and in its name", () => {
    const builder: AgentAttachment = { ...RAIL_ATTACHMENTS[0], title: "Heat islands" };
    const finder: AgentAttachment = { ...RAIL_ATTACHMENTS[1], title: "Parks by the river" };
    const { rail } = renderRail(builder, { attachments: [builder, finder] });

    const open = within(rail).getByRole("button", { name: "Dataflow Builder: Heat islands on the canvas" });
    expect(open).toHaveAttribute("aria-current", "true");
    expect(open).toHaveAttribute("data-tooltip", "Dataflow Builder: Heat islands on the canvas");
    expect(open).toHaveTextContent(/^Dataflow Builder$/);

    const entry = within(rail).getByRole("button", { name: "Dataset Finder: Parks by the river on Load buildings" });
    expect(entry).toHaveAttribute("data-tooltip", "Dataset Finder: Parks by the river on Load buildings");
    expect(within(entry).getByText("Dataset Finder")).toBeInTheDocument();
    expect(within(entry).getByText("Load buildings")).toBeInTheDocument();
    expect(entry).not.toHaveTextContent("Parks by the river");
  });

  it("labels twins with their agent's name and number, which their tooltips and names keep", () => {
    const finder = (attachmentId: string): AgentAttachment => ({
      ...attachment,
      attachmentId,
      coord: "agent.curio.dataset-finder@1",
      name: "Dataset Finder",
      category: "data",
      title: "Parks",
    });
    const { rail } = renderRail(RAIL_ATTACHMENTS[0], { attachments: [RAIL_ATTACHMENTS[0], finder("f1"), finder("f2")] });
    const twins = within(rail).getAllByRole("button").slice(1);
    const named = ["Dataset Finder: Parks (1) on the canvas", "Dataset Finder: Parks (2) on the canvas"];
    expect(twins.map((entry) => entry.getAttribute("aria-label"))).toEqual(named);
    expect(twins.map((entry) => entry.getAttribute("data-tooltip"))).toEqual(named);
    expect(twins.map((entry) => entry.textContent)).toEqual(["Dataset Finder (1)", "Dataset Finder (2)"]);
  });

  it("a group's list goes with its group, and lets go of its layer", () => {
    const onClose = jest.fn();
    const { rail, rerender, props } = renderRail(RAIL_ATTACHMENTS[0], { onClose });
    fireEvent.click(within(rail).getByRole("button", { name: "Node Builder on 3 nodes" }));
    expect(screen.getByRole("menu", { name: "Node Builder on" })).toBeInTheDocument();

    // One of its Node Builders is detached: two are left, each an entry of its own.
    rerender(<AgentChatPanel {...props} attachments={RAIL_ATTACHMENTS.filter((a) => a.attachmentId !== "nb3")} />);
    expect(screen.queryByRole("menu", { name: "Node Builder on" })).toBeNull();
    expect(modalStackDepth()).toBe(0);
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);

    // Attached again, the group comes back with its list closed.
    rerender(<AgentChatPanel {...props} attachments={RAIL_ATTACHMENTS} />);
    expect(screen.queryByRole("menu", { name: "Node Builder on" })).toBeNull();
  });

  it("counts the nodes of a group at work", () => {
    const working: Record<string, string> = {
      nb2: "Node Builder (asked by Ana), editing Load heat",
      nb3: "Node Builder (asked by Ana), editing Heat map",
    };
    const { rail } = renderRail(RAIL_ATTACHMENTS[0], { workingOf: (a) => working[a.attachmentId] ?? null });
    expect(within(rail).getByRole("button", { name: /^Node Builder on 3 nodes/ })).toHaveAccessibleName(
      "Node Builder on 3 nodes, 2 at work",
    );
  });

  it("choosing a node from a group's list leaves the focus on the group, not on the page", async () => {
    const user = userEvent.setup();
    const { rail, onOpenAgentChat } = renderRail(RAIL_ATTACHMENTS[0]);
    const group = within(rail).getByRole("button", { name: "Node Builder on 3 nodes" });
    await user.click(group);
    await user.click(within(screen.getByRole("menu", { name: "Node Builder on" })).getByRole("menuitem", { name: "Load heat" }));
    expect(onOpenAgentChat).toHaveBeenCalledWith("nb2");
    expect(screen.queryByRole("menu", { name: "Node Builder on" })).toBeNull();
    expect(document.activeElement).not.toBe(document.body);
    expect(group).toHaveFocus();
  });

  it("keeps a group's list inside the panel when its entry is low on the rail", () => {
    const { rail } = renderRail(RAIL_ATTACHMENTS[0]);
    const wrap = rail.parentElement as HTMLElement;
    const group = within(rail).getByRole("button", { name: "Node Builder on 3 nodes" });
    // jsdom lays nothing out, so the geometry is given: the panel's rail is
    // 600px tall from y 100, the group's entry is 560px down it, and its list
    // is 200px tall.
    const box = (top: number, height: number) =>
      ({ x: 0, y: top, left: 0, top, right: 78, bottom: top + height, width: 78, height, toJSON: () => ({}) }) as DOMRect;
    const isList = (el: Element) => el.getAttribute("role") === "menu";
    const spies = [
      jest.spyOn(Element.prototype, "getBoundingClientRect").mockImplementation(function (this: Element) {
        if (this === wrap || this === rail) return box(100, 600);
        if (this === group) return box(660, 56);
        return isList(this) ? box(0, 200) : box(0, 0);
      }),
      jest.spyOn(HTMLElement.prototype, "offsetTop", "get").mockImplementation(function (this: HTMLElement) {
        return this === group ? 560 : 0;
      }),
      jest.spyOn(HTMLElement.prototype, "offsetHeight", "get").mockImplementation(function (this: HTMLElement) {
        if (this === wrap || this === rail) return 600;
        if (this === group) return 56;
        return isList(this) ? 200 : 0;
      }),
      jest.spyOn(Element.prototype, "clientHeight", "get").mockImplementation(function (this: Element) {
        return this === wrap || this === rail ? 600 : 0;
      }),
    ];
    try {
      fireEvent.click(group);
      const list = screen.getByRole("menu", { name: "Node Builder on" });
      const top = parseFloat(list.style.top);
      expect(top).toBeGreaterThanOrEqual(0);
      expect(top + 200).toBeLessThanOrEqual(600);
    } finally {
      for (const spy of spies) spy.mockRestore();
    }
  });
});

describe("AgentChatPanel's More menu", () => {
  it("holds Rename conversation, Clear conversation and Tokens used", () => {
    renderPanel({
      onSaveTitle: jest.fn(),
      onClearConversation: jest.fn(),
      turns: [
        { role: "user", text: "q1" },
        { role: "agent", text: "a1", execution: { executionId: "e1", usage: { inputTokens: 1100, outputTokens: 300 }, status: "ok", durationMs: 10 } },
      ],
    });
    // Named by what it does, which the tokens never change ("keeps its name
    // while the conversation's tokens arrive", below).
    const more = screen.getByRole("button", { name: "More: rename, clear" });
    expect(more).toHaveAttribute("aria-haspopup", "menu");
    expect(more).toHaveAttribute("data-tooltip", "More");
    const menu = openMore();
    expect(within(menu).getAllByRole("menuitem").map((item) => item.textContent)).toEqual([
      "Rename conversation",
      "Clear conversation…",
      "Tokens used: 1.4k1.1k in, 300 out, over 1 reply",
    ]);
  });

  it("Rename conversation opens the title for editing", () => {
    const onSaveTitle = jest.fn().mockResolvedValue(undefined);
    renderPanel({ attachment: { ...attachment, title: "Dataset Import Help" }, onSaveTitle });
    fireEvent.click(within(openMore()).getByRole("menuitem", { name: "Rename conversation" }));
    const input = screen.getByRole("textbox", { name: "Conversation title" });
    expect(input).toHaveValue("Dataset Import Help");
    expect(input).toHaveFocus();
    fireEvent.change(input, { target: { value: "Renamed" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onSaveTitle).toHaveBeenCalledWith("Renamed");
  });

  it("Escape closes the menu, not the chat; a press elsewhere closes it too", () => {
    const onClose = jest.fn();
    renderPanel({ onClose, onClearConversation: jest.fn() });
    openMore();
    fireEvent.keyDown(document.activeElement ?? window, { key: "Escape" });
    expect(screen.queryByRole("menu", { name: "Chat menu" })).toBeNull();
    expect(onClose).not.toHaveBeenCalled();
    openMore();
    fireEvent.pointerDown(screen.getByRole("textbox", { name: /^Message/ }));
    expect(screen.queryByRole("menu", { name: "Chat menu" })).toBeNull();
  });

  it("is not there when it would hold nothing", () => {
    renderPanel();
    expect(screen.queryByRole("button", { name: /^More/ })).toBeNull();
  });

  const used: AgentSessionTurn[] = [
    { role: "user", text: "q1" },
    { role: "agent", text: "a1", execution: { executionId: "e1", usage: { inputTokens: 1100, outputTokens: 300 }, status: "ok", durationMs: 10 } },
  ];

  it("Tokens used is reached from the keyboard, and a menu of tokens alone opens on it", () => {
    const first = renderPanel({ onSaveTitle: jest.fn(), onClearConversation: jest.fn(), turns: used });
    const menu = openMore();
    expect(within(menu).getByRole("menuitem", { name: "Rename conversation" })).toHaveFocus();
    fireEvent.keyDown(document.activeElement as HTMLElement, { key: "End" });
    expect(screen.getByLabelText(/session token usage/i)).toHaveFocus();
    fireEvent.keyDown(document.activeElement as HTMLElement, { key: "ArrowDown" });
    expect(within(menu).getByRole("menuitem", { name: "Rename conversation" })).toHaveFocus();
    first.unmount();

    renderPanel({ turns: used });
    openMore();
    expect(screen.getByLabelText(/session token usage/i)).toHaveFocus();
  });

  it("keeps its name while the conversation's tokens arrive", () => {
    const { rerender, props } = renderPanel({ onSaveTitle: jest.fn(), onClearConversation: jest.fn() });
    const more = screen.getByRole("button", { name: /^More/ });
    expect(more).toHaveAccessibleName("More: rename, clear");
    rerender(
      <AgentChatPanel
        {...props}
        turns={[{ role: "user", text: "q1" }]}
        runStatus={{ phase: "running", startedAt: Date.now(), liveUsage: { inputTokens: 900, outputTokens: 100 } }}
      />,
    );
    expect(screen.getByRole("button", { name: /^More/ })).toBe(more);
    expect(more).toHaveAccessibleName("More: rename, clear");
    fireEvent.click(more);
    expect(screen.getByLabelText(/session token usage/i)).toHaveTextContent("Tokens used: 1.0k");
  });

  it("Tokens used pulses while the running reply can still add to it, and holds still once it ended", () => {
    const { rerender, props } = renderPanel({
      onSaveTitle: jest.fn(),
      turns: [{ role: "user", text: "q1" }],
      runStatus: { phase: "running", startedAt: Date.now(), liveUsage: { inputTokens: 900, outputTokens: 100 } },
    });
    openMore();
    expect(screen.getByText(/^Tokens used:/)).toHaveClass("menuTokensLive");
    rerender(<AgentChatPanel {...props} turns={used} runStatus={{ phase: "done", startedAt: Date.now(), durationMs: 10 }} />);
    expect(screen.getByText(/^Tokens used:/)).not.toHaveClass("menuTokensLive");
  });
});

describe("AgentChatPanel conversation title (memo dev/25)", () => {
  const titled = { ...attachment, title: "Dataset Import Help" };

  it("shows the composed '<name>: <title>' in the header and dialog label", () => {
    renderPanel({ attachment: titled, onSaveTitle: jest.fn() });
    expect(
      screen.getByRole("button", { name: "Rename conversation title" }),
    ).toHaveTextContent("My Explainer: Dataset Import Help");
    expect(
      screen.getByRole("dialog", { name: "Chat with My Explainer: Dataset Import Help" }),
    ).toBeInTheDocument();
  });

  it("shows the plain name when untitled, and a plain non-button label without onSaveTitle", () => {
    const first = renderPanel({ onSaveTitle: jest.fn() });
    expect(
      screen.getByRole("button", { name: "Rename conversation title" }),
    ).toHaveTextContent(/^My Explainer$/);
    first.unmount();
    renderPanel({ attachment: titled });
    expect(
      screen.queryByRole("button", { name: "Rename conversation title" }),
    ).not.toBeInTheDocument();
    expect(screen.getByText("My Explainer: Dataset Import Help")).toBeInTheDocument();
  });

  it("a single click swaps only the custom portion for an input, prefix fixed", () => {
    renderPanel({ attachment: titled, onSaveTitle: jest.fn() });
    fireEvent.click(screen.getByRole("button", { name: "Rename conversation title" }));
    const input = screen.getByRole("textbox", { name: "Conversation title" });
    expect(input).toHaveValue("Dataset Import Help");
    expect(input).toHaveAttribute("maxlength", "40");
    // The template-name prefix stays as static text, not inside the input.
    expect(screen.getByText("My Explainer:")).toBeInTheDocument();
  });

  it("Enter commits the trimmed title and shows it optimistically", async () => {
    const onSaveTitle = jest.fn().mockResolvedValue(undefined);
    renderPanel({ attachment: titled, onSaveTitle });
    fireEvent.click(screen.getByRole("button", { name: "Rename conversation title" }));
    const input = screen.getByRole("textbox", { name: "Conversation title" });
    fireEvent.change(input, { target: { value: "  Renamed Chat  " } });
    await act(async () => {
      fireEvent.keyDown(input, { key: "Enter" });
    });
    expect(onSaveTitle).toHaveBeenCalledWith("Renamed Chat");
    expect(
      screen.getByRole("button", { name: "Rename conversation title" }),
    ).toHaveTextContent("My Explainer: Renamed Chat");
  });

  it("blur commits too, and Enter + blur together save only once", async () => {
    const onSaveTitle = jest.fn().mockResolvedValue(undefined);
    renderPanel({ attachment: titled, onSaveTitle });
    fireEvent.click(screen.getByRole("button", { name: "Rename conversation title" }));
    const input = screen.getByRole("textbox", { name: "Conversation title" });
    fireEvent.change(input, { target: { value: "Blur Saved" } });
    await act(async () => {
      fireEvent.keyDown(input, { key: "Enter" });
      fireEvent.blur(input);
    });
    expect(onSaveTitle).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "Rename conversation title" }));
    const input2 = screen.getByRole("textbox", { name: "Conversation title" });
    fireEvent.change(input2, { target: { value: "Blur Saved Again" } });
    await act(async () => {
      fireEvent.blur(input2);
    });
    expect(onSaveTitle).toHaveBeenLastCalledWith("Blur Saved Again");
  });

  it("Escape cancels the edit without saving and without closing the panel", () => {
    const onSaveTitle = jest.fn();
    const onClose = jest.fn();
    renderPanel({ attachment: titled, onSaveTitle, onClose });
    fireEvent.click(screen.getByRole("button", { name: "Rename conversation title" }));
    const input = screen.getByRole("textbox", { name: "Conversation title" });
    fireEvent.change(input, { target: { value: "discarded" } });
    fireEvent.keyDown(input, { key: "Escape" });
    expect(onSaveTitle).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
    expect(
      screen.getByRole("button", { name: "Rename conversation title" }),
    ).toHaveTextContent("My Explainer: Dataset Import Help");
  });

  it("empty and unchanged submits are cancels — nothing is saved", () => {
    const onSaveTitle = jest.fn();
    renderPanel({ attachment: titled, onSaveTitle });
    fireEvent.click(screen.getByRole("button", { name: "Rename conversation title" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Conversation title" }), {
      target: { value: "   " },
    });
    fireEvent.keyDown(screen.getByRole("textbox", { name: "Conversation title" }), {
      key: "Enter",
    });
    expect(onSaveTitle).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Rename conversation title" }));
    fireEvent.keyDown(screen.getByRole("textbox", { name: "Conversation title" }), {
      key: "Enter",
    });
    expect(onSaveTitle).not.toHaveBeenCalled();
  });

  it("a failed save restores the previous title and shows the error", async () => {
    const onSaveTitle = jest.fn().mockRejectedValue(new Error("rename failed"));
    renderPanel({ attachment: titled, onSaveTitle });
    fireEvent.click(screen.getByRole("button", { name: "Rename conversation title" }));
    const input = screen.getByRole("textbox", { name: "Conversation title" });
    fireEvent.change(input, { target: { value: "Will Fail" } });
    await act(async () => {
      fireEvent.keyDown(input, { key: "Enter" });
    });
    expect(screen.getByText("rename failed")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Rename conversation title" }),
    ).toHaveTextContent("My Explainer: Dataset Import Help");
  });
});

/**
 * The dataflow's goal (the spec's `task`), the line under the header of every
 * agent's chat. In the canvas's dock, among the agents' chips, it read as a
 * chat box (#227): nothing typed in it is sent, and no agent answers it.
 */
describe("AgentChatPanel: the dataflow's goal, under the header", () => {
  const goalLine = () => document.querySelector<HTMLElement>("[data-curio-chat-goal]");
  const nodeAgent: AgentAttachment = {
    ...attachment,
    attachmentId: "a2",
    name: "Node Builder",
    target: { kind: "node" as const, targetId: "n1" },
  };

  it("is a line under the header, named by a standing label whose tooltip says who reads it", () => {
    renderPanel({ goal: "Find heat islands in Chicago", onSaveGoal: jest.fn() });
    const line = goalLine();
    expect(line).not.toBeNull();
    expect(GOAL_TOOLTIP).toBe("The dataflow's goal. The agents on this dataflow read it.");
    expect(within(line!).getByText("Goal")).toHaveAttribute("data-tooltip", GOAL_TOOLTIP);
    expect(within(line!).getByText("Find heat islands in Chicago")).toBeInTheDocument();
    // Beside the header, not inside it: the header's own frame clips to it.
    const header = document.querySelector<HTMLElement>("[data-curio-chat-header]")!;
    expect(header.contains(line)).toBe(false);
    // eslint-disable-next-line no-bitwise
    expect(header.compareDocumentPosition(line!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    // Above the conversation.
    const conversation = screen.getByText("Ask this agent something to get started.");
    // eslint-disable-next-line no-bitwise
    expect(line!.compareDocumentPosition(conversation) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("is in a node agent's chat too, and in none whose caller keeps no goal", () => {
    const first = renderPanel({ attachment: nodeAgent, goal: "Find heat islands", onSaveGoal: jest.fn() });
    expect(within(goalLine()!).getByText("Find heat islands")).toBeInTheDocument();
    first.unmount();
    renderPanel({ goal: "Find heat islands" });
    expect(goalLine()).toBeNull();
  });

  it("offers to add a goal while there is none, and its field says what it is for", () => {
    renderPanel({ goal: "", onSaveGoal: jest.fn() });
    fireEvent.click(screen.getByRole("button", { name: GOAL_EMPTY }));
    const field = screen.getByRole("textbox", { name: "Dataflow goal" });
    expect(field).toHaveValue("");
    expect(field).toHaveAttribute("placeholder", GOAL_PLACEHOLDER);
    expect(field).toHaveFocus();
    // The label stays, so the field keeps its name once a goal is typed.
    expect(within(goalLine()!).getByText("Goal")).toBeInTheDocument();
  });

  it("Edit opens the goal in the field, selected", () => {
    renderPanel({ goal: "Find heat islands", onSaveGoal: jest.fn() });
    const edit = screen.getByRole("button", { name: "Edit the goal" });
    expect(edit).toHaveAttribute("data-tooltip", "Edit the goal");
    fireEvent.click(edit);
    const field = screen.getByRole("textbox", { name: "Dataflow goal" }) as HTMLInputElement;
    expect(field).toHaveValue("Find heat islands");
    expect(field).toHaveFocus();
    expect([field.selectionStart, field.selectionEnd]).toEqual([0, "Find heat islands".length]);
  });

  it("Enter keeps the trimmed goal, once; typing alone keeps nothing", () => {
    const onSaveGoal = jest.fn();
    renderPanel({ goal: "", onSaveGoal });
    fireEvent.click(screen.getByRole("button", { name: GOAL_EMPTY }));
    const field = screen.getByRole("textbox", { name: "Dataflow goal" });
    fireEvent.change(field, { target: { value: "  Map tree canopy  " } });
    expect(onSaveGoal).not.toHaveBeenCalled();
    fireEvent.keyDown(field, { key: "Enter" });
    expect(onSaveGoal).toHaveBeenCalledTimes(1);
    expect(onSaveGoal).toHaveBeenCalledWith("Map tree canopy");
    expect(screen.queryByRole("textbox", { name: "Dataflow goal" })).toBeNull();
  });

  it("Save keeps the draft, an emptied one clears the goal, and an unchanged one keeps nothing", async () => {
    const user = userEvent.setup();
    const onSaveGoal = jest.fn();
    renderPanel({ goal: "Find heat islands", onSaveGoal });
    await user.click(screen.getByRole("button", { name: "Edit the goal" }));
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(onSaveGoal).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Edit the goal" }));
    await user.clear(screen.getByRole("textbox", { name: "Dataflow goal" }));
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(onSaveGoal).toHaveBeenCalledTimes(1);
    expect(onSaveGoal).toHaveBeenCalledWith("");
  });

  it("Cancel and Escape leave the goal as it was, and Escape leaves the chat open", async () => {
    const user = userEvent.setup();
    const onSaveGoal = jest.fn();
    const onClose = jest.fn();
    renderPanel({ goal: "Find heat islands", onSaveGoal, onClose });
    // A click on Cancel takes the focus out of the field first: that keeps
    // nothing either.
    await user.click(screen.getByRole("button", { name: "Edit the goal" }));
    await user.type(screen.getByRole("textbox", { name: "Dataflow goal" }), " by exposure");
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onSaveGoal).not.toHaveBeenCalled();
    expect(within(goalLine()!).getByText("Find heat islands")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Edit the goal" }));
    await user.type(screen.getByRole("textbox", { name: "Dataflow goal" }), " by exposure");
    await user.keyboard("{Escape}");
    expect(onSaveGoal).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.queryByRole("textbox", { name: "Dataflow goal" })).toBeNull();
    expect(screen.getByRole("button", { name: "Edit the goal" })).toHaveFocus();
    // With nothing being edited, Escape closes the chat.
    await user.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("is the dataflow's goal, not one agent's: a field left open stays open when the chat changes agents", () => {
    const onSaveGoal = jest.fn();
    const { rerender, props } = renderPanel({ goal: "Find heat islands", onSaveGoal });
    fireEvent.click(screen.getByRole("button", { name: "Edit the goal" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Dataflow goal" }), {
      target: { value: "Rank heat islands" },
    });
    rerender(<AgentChatPanel {...props} attachment={nodeAgent} />);
    const field = screen.getByRole("textbox", { name: "Dataflow goal" });
    expect(field).toHaveValue("Rank heat islands");
    fireEvent.keyDown(field, { key: "Enter" });
    expect(onSaveGoal).toHaveBeenCalledWith("Rank heat islands");
  });
});

describe("AgentChatPanel structured content (memo dev/39)", () => {
  const promptsTurns: AgentSessionTurn[] = [
    { role: "user", text: "find data" },
    {
      role: "agent",
      text: "Here are the options.",
      content: [
        {
          type: "suggestedPrompts",
          primary: "Build the NOAA node",
          alternatives: ["Show the fetch code", "Use the catalog copy"],
        },
      ],
    },
  ];

  it("renders agent markdown through the safe renderer", () => {
    const { container } = renderPanel({
      turns: [{ role: "agent", text: "Some **bold** answer" }],
    });
    expect(container.querySelector("strong")?.textContent).toBe("bold");
  });

  it("a fenced code block in an agent turn carries the Copy button (dev/78)", () => {
    const { container } = renderPanel({
      turns: [{ role: "agent", text: "Try this:\n\n```python\nprint('hi')\n```" }],
    });
    const bubble = container.querySelector(".msgAgent");
    expect(bubble?.querySelector("pre")?.textContent).toContain("print('hi')");
    const copy = screen.getByRole("button", { name: "Copy code" });
    expect(bubble?.contains(copy)).toBe(true);
  });

  it("renders cards from the agent turn's content", () => {
    renderPanel({
      turns: [
        {
          role: "agent",
          text: "Done.",
          content: [
            { type: "card", kind: "result", title: "Created node", lines: ["n1 → canvas"] },
          ],
        },
      ],
    });
    expect(screen.getByText("Created node")).toBeInTheDocument();
    expect(screen.getByText("n1 → canvas")).toBeInTheDocument();
  });

  it("prefills the primary prompt and renders the chip row", () => {
    renderPanel({ turns: promptsTurns });
    expect(screen.getByDisplayValue("Build the NOAA node")).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Suggested prompts" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Show the fetch code" })).toBeInTheDocument();
    // The prefilled primary makes Send active immediately (docs/08).
    expect(screen.getByRole("button", { name: "Send" })).not.toBeDisabled();
  });

  it("clicking a chip replaces the input draft", () => {
    renderPanel({ turns: promptsTurns });
    fireEvent.click(screen.getByRole("button", { name: "Use the catalog copy" }));
    expect(screen.getByDisplayValue("Use the catalog copy")).toBeInTheDocument();
  });

  it("a user-typed draft is never overwritten by a prefill", () => {
    const { rerender, props } = renderPanel({ turns: [{ role: "user", text: "q" }] });
    fireEvent.change(screen.getByPlaceholderText(/^Message /), {
      target: { value: "my own words" },
    });
    rerender(<AgentChatPanel {...props} turns={promptsTurns} />);
    expect(screen.getByDisplayValue("my own words")).toBeInTheDocument();
    expect(screen.queryByDisplayValue("Build the NOAA node")).toBeNull();
  });

  it("suggestions are stale once the user replied (no chip row)", () => {
    renderPanel({
      turns: [...promptsTurns, { role: "user", text: "next question" }],
    });
    expect(screen.queryByRole("group", { name: "Suggested prompts" })).toBeNull();
  });

  it("no chip row when alternatives are empty (prefill only)", () => {
    renderPanel({
      turns: [
        {
          role: "agent",
          text: "ok",
          content: [{ type: "suggestedPrompts", primary: "Only one", alternatives: [] }],
        },
      ],
    });
    expect(screen.queryByRole("group", { name: "Suggested prompts" })).toBeNull();
    expect(screen.getByDisplayValue("Only one")).toBeInTheDocument();
  });
});

describe("AgentChatPanel changes, reviews + tool activity (memo dev/41)", () => {
  it("renders a change part as the change card and wires its Undo", () => {
    const onUndoChange = jest.fn().mockResolvedValue(undefined);
    renderPanel({
      turns: [
        {
          role: "agent",
          text: "I wrote the node's code.",
          content: [
            {
              type: "change",
              changeId: "c1",
              tool: "node.content.write",
              kind: "content",
              summary: "Replaced the content of the Python node · n1",
              preview: "print(2)",
              status: "applied",
              lines: ["n1"],
              nodeId: "n1",
            } as never,
          ],
        },
      ],
      onUndoChange,
    });
    expect(screen.queryByRole("button", { name: "Apply" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    expect(onUndoChange).toHaveBeenCalledWith("c1");
  });

  it("renders an install's proposal part as the review card and wires apply", () => {
    const onApplyProposal = jest.fn().mockResolvedValue(undefined);
    renderPanel({
      turns: [
        {
          role: "agent",
          text: "This needs the Cities dataset.",
          content: [
            {
              type: "proposal",
              proposalId: "p1",
              tool: "dataset.install",
              summary: "Install dataset · Cities",
              preview: "Cities · csv · imported",
              pins: { datasetId: "imported.abc@1" },
              status: "pending",
            },
          ],
        },
      ],
      onApplyProposal,
    });
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));
    expect(onApplyProposal).toHaveBeenCalledWith("p1");
  });

  it("shows transient tool-activity system lines", () => {
    renderPanel({
      turns: [{ role: "user", text: "q" }],
      toolActivity: ["node.read …", "node.read · ok"],
    });
    expect(screen.getByText("node.read …")).toBeInTheDocument();
    expect(screen.getByText("node.read · ok")).toBeInTheDocument();
  });

  it("a reloaded reply keeps a failed tool call's reason under it (#447)", () => {
    renderPanel({
      turns: [
        { role: "user", text: "check the data endpoint" },
        savedReply("I could not reach that address.", {
          toolCalls: [
            { tool: "node.read", status: "ok", durationMs: 2 },
            { tool: "web.fetch", status: "error", durationMs: 4, reason: REFUSAL, egress: true },
          ],
        }),
      ],
    });
    expect(screen.getByText(`web.fetch · ${REFUSAL}`)).toBeInTheDocument();
    // A call that succeeded leaves no line.
    expect(screen.queryByText(/^node\.read ·/)).not.toBeInTheDocument();
  });

  it("an egress refusal keeps its line even when a later fetch in the turn succeeds (#447)", () => {
    renderPanel({
      turns: [
        { role: "user", text: "check both endpoints" },
        savedReply("The second address answered.", {
          toolCalls: [
            { tool: "web.fetch", status: "error", durationMs: 4, reason: REFUSAL, egress: true },
            { tool: "web.fetch", status: "ok", durationMs: 80 },
          ],
        }),
      ],
    });
    expect(screen.getByText(`web.fetch · ${REFUSAL}`)).toBeInTheDocument();
  });
});

/** The reason the egress policy gives for a non-public address (#447). */
const REFUSAL =
  "refused by the egress policy: host '127.0.0.1' resolves to a non-public address (127.0.0.1) - refused";

/** An agent reply as the server saves it, with the run's execution record
 * (pins, duration, usage) plus *execution*'s fields. */
function savedReply(
  text: string,
  execution: Record<string, unknown> = {},
  content?: unknown[],
): AgentSessionTurn {
  return {
    role: "agent",
    text,
    execution: {
      executionId: `e-${text.length}`,
      pins: { coord: "agent.curio.node-builder@1", promptSha256: "abc", tools: ["dataflow.read", "node.create"] },
      usage: { inputTokens: 10, outputTokens: 20 },
      durationMs: 1200,
      status: "ok",
      ...execution,
    },
    ...(content ? { content } : {}),
  } as unknown as AgentSessionTurn;
}

describe("AgentChatPanel says when a canvas agent changed nothing (#243)", () => {
  const NO_CHANGE = "No changes were made to the canvas";
  const nodeBuilder: AgentAttachment = {
    ...attachment,
    coord: "agent.curio.node-builder@1",
    name: "Node Builder",
    capabilities: NODE_BUILDER_CAPABILITIES,
  };
  const ask: AgentSessionTurn = { role: "user", text: "Add a node that loads the parks." };
  const created = {
    type: "change",
    changeId: "c1",
    tool: "node.create",
    kind: "node",
    summary: "Created a new Python node",
    preview: "print(1)",
    status: "applied",
    lines: ["Load parks · PYTHON_COMPUTATION"],
  };

  it("a reloaded Node Builder reply with only a dataflow.read call says so", () => {
    renderPanel({
      attachment: nodeBuilder,
      turns: [
        ask,
        savedReply("I have now added a new node to your dataflow.", {
          toolCalls: [{ tool: "dataflow.read", status: "ok", durationMs: 3 }],
        }),
      ],
    });
    expect(screen.getByText(NO_CHANGE)).toBeInTheDocument();
  });

  it("a reply that holds a node it added does not", () => {
    renderPanel({
      attachment: nodeBuilder,
      turns: [
        ask,
        savedReply("I added the node.", {
          toolCalls: [{ tool: "node.create", status: "applied", durationMs: 3 }],
        }, [created]),
      ],
    });
    expect(screen.getByText("I added the node.")).toBeInTheDocument();
    expect(screen.queryByText(NO_CHANGE)).not.toBeInTheDocument();
  });

  it("a reply that holds an install waiting for review does not either", () => {
    const install = {
      type: "proposal", proposalId: "pk1", tool: "package.install", summary: "Install package · Weather",
      preview: "weather", pins: { dirName: "curio.weather@1" }, status: "pending",
    };
    renderPanel({
      attachment: nodeBuilder,
      turns: [
        ask,
        savedReply("This needs the weather package.", {
          toolCalls: [{ tool: "package.install", status: "proposed", durationMs: 3 }],
        }, [install]),
      ],
    });
    expect(screen.queryByText(NO_CHANGE)).not.toBeInTheDocument();
  });

  it("a refused node.create the turn never recovered from keeps its reason, beside the no-change line (#447)", () => {
    renderPanel({
      attachment: nodeBuilder,
      turns: [
        ask,
        savedReply("I have now added a new node to your dataflow.", {
          toolCalls: [
            { tool: "node.create", status: "refused", durationMs: 1, reason: "template.content must be a non-empty string" },
          ],
        }),
      ],
    });
    expect(screen.getByText("node.create · template.content must be a non-empty string")).toBeInTheDocument();
    expect(screen.getByText(NO_CHANGE)).toBeInTheDocument();
  });

  it("a node.create the turn recovered from leaves no line beside the change (#447)", () => {
    renderPanel({
      attachment: nodeBuilder,
      turns: [
        ask,
        savedReply("I added the node.", {
          toolCalls: [
            { tool: "node.create", status: "refused", durationMs: 1, reason: "template.content must be a non-empty string" },
            { tool: "node.create", status: "applied", durationMs: 3 },
          ],
        }, [created]),
      ],
    });
    expect(screen.getByRole("group", { name: "Change: Created a new Python node" })).toBeInTheDocument();
    expect(screen.queryByText(/^node\.create ·/)).not.toBeInTheDocument();
  });

  it("a Solve verdict or a delegated task, which answer no message of the user's, does not", () => {
    renderPanel({
      attachment: nodeBuilder,
      turns: [
        ask,
        savedReply("I added the node.", {}, [created]),
        // A Solve verdict: written by the run, not a reply to a message.
        savedReply("Solved 'Load parks': the corrected code ran successfully.", {
          pins: { coord: "agent.curio.node-builder@1", tools: [], intentEdited: false },
        }),
        // A task another agent delegated here: the delegate's own record.
        { role: "user", text: "[Delegated by Dataflow Builder] write the code" },
        savedReply("Wrote the code for the node.", { parentExecutionId: "e-parent" }),
      ],
    });
    expect(screen.getByText("Wrote the code for the node.")).toBeInTheDocument();
    expect(screen.queryByText(NO_CHANGE)).not.toBeInTheDocument();
  });
});

describe("AgentChatPanel package-install review (memo dev/84)", () => {
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
    (packagesApi.catalog as jest.Mock).mockClear();
    (packagesApi.resolve as jest.Mock).mockClear();
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
    (packagesApi.resolve as jest.Mock).mockResolvedValue({ lockfile: {}, conflicts: [] });
    // dev/105 A1: the review reads the user's store as well as the catalog.
    (packagesApi.listInstalled as jest.Mock).mockClear();
    (packagesApi.listInstalled as jest.Mock).mockResolvedValue({ packages: [] });
  });

  it("Apply opens the existing install review dialog; only its Install button fires the apply", async () => {
    const onApplyProposal = jest.fn().mockResolvedValue(undefined);
    renderPanel({ turns: packageTurns, onApplyProposal });
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));
    // The dialog is the review surface: permissions + deps render, nothing
    // applied yet. (Queried by its title — the chat panel itself is a dialog.)
    await screen.findByText('Add "Weather Analysis"');
    expect(screen.getByText("network.fetch")).toBeInTheDocument();
    expect(screen.getByText("python · rasterio")).toBeInTheDocument();
    expect(onApplyProposal).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Add to project" }));
    await waitFor(() => expect(onApplyProposal).toHaveBeenCalledWith("pk1"));
    await waitFor(() =>
      expect(screen.queryByText('Add "Weather Analysis"')).toBeNull(),
    );
  });

  it("Cancel keeps the proposal pending — no apply, card still actionable", async () => {
    const onApplyProposal = jest.fn().mockResolvedValue(undefined);
    renderPanel({ turns: packageTurns, onApplyProposal });
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));
    await screen.findByText('Add "Weather Analysis"');
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() =>
      expect(screen.queryByText('Add "Weather Analysis"')).toBeNull(),
    );
    expect(onApplyProposal).not.toHaveBeenCalled();
    // The card's act() settles with the cancel — Apply is actionable again.
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Apply" })).toBeEnabled(),
    );
  });

  it("REGRESSION: non-package proposals still apply directly, no dialog", async () => {
    const onApplyProposal = jest.fn().mockResolvedValue(undefined);
    renderPanel({
      turns: [
        {
          role: "agent",
          text: "proposal",
          content: [
            {
              type: "proposal",
              proposalId: "p1",
              tool: "dataset.install",
              summary: "Install dataset · Cities",
              preview: "Cities · csv",
              pins: { datasetId: "d1" },
              status: "pending",
            } as never,
          ],
        } as AgentSessionTurn,
      ],
      onApplyProposal,
    });
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));
    await waitFor(() => expect(onApplyProposal).toHaveBeenCalledWith("p1"));
    expect(screen.queryByRole("button", { name: "Add to project" })).toBeNull();
    expect(packagesApi.catalog).not.toHaveBeenCalled();
  });
});

describe("AgentChatPanel has no attachment settings cog", () => {
  it("renders none, because there is no per-attachment settings surface", () => {
    // The cog was gated on an `onOpenSettings` prop that no production caller
    // ever passed: the modal behind it was deleted with the account-scope
    // settings move, and the panel kept a branch only its own test could
    // reach. A green test over an unreachable surface reads as coverage.
    renderPanel();
    expect(screen.queryByRole("button", { name: /attachment settings/i })).toBeNull();
  });
});

describe("AgentChatPanel delegation entries (memo dev/72)", () => {
  const delegation = {
    type: "delegation" as const,
    capability: "research.verify",
    coord: "agent.curio.researcher@1",
    name: "Researcher",
    category: "node",
    attachmentId: "att-r",
    status: "ok" as const,
    summary: "verified — 200",
  };

  it("an agent turn's delegation part renders the entry and routes the icon-link", () => {
    const onOpenAgentChat = jest.fn();
    renderPanel({
      turns: [{ role: "agent", text: "done", content: [delegation] }],
      onOpenAgentChat,
      delegateExists: (id) => id === "att-r",
    });
    expect(screen.getByText("research.verify")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Open Researcher's chat" }));
    expect(onOpenAgentChat).toHaveBeenCalledWith("att-r");
  });

  it("a detached home renders the entry without a link", () => {
    renderPanel({
      turns: [{ role: "agent", text: "done", content: [delegation] }],
      onOpenAgentChat: jest.fn(),
      delegateExists: () => false,
    });
    expect(screen.getByText("research.verify")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /open researcher/i }),
    ).toBeNull();
  });
});

describe("AgentChatPanel follow-at-bottom auto-scroll (memo dev/75)", () => {
  const BOTTOM = 700; // mocked scrollHeight 1000 − clientHeight 300

  /** jsdom does no layout — stub the transcript's scroll geometry. */
  function mockGeometry(el: HTMLElement) {
    let scrollTop = 0;
    Object.defineProperty(el, "scrollHeight", { configurable: true, get: () => 1000 });
    Object.defineProperty(el, "clientHeight", { configurable: true, get: () => 300 });
    Object.defineProperty(el, "scrollTop", {
      configurable: true,
      get: () => scrollTop,
      set: (v: number) => {
        scrollTop = v;
      },
    });
    (el as HTMLElement & { scrollTo: (opts: ScrollToOptions) => void }).scrollTo = (
      opts: ScrollToOptions,
    ) => {
      scrollTop = opts.top ?? 0;
    };
  }

  function renderWithTranscript(
    overrides: Partial<React.ComponentProps<typeof AgentChatPanel>> = {},
  ) {
    const utils = renderPanel({
      turns: [
        { role: "user", text: "q1" },
        { role: "agent", text: "streaming…" },
      ],
      ...overrides,
    });
    const transcript = utils.container.querySelector(".messages") as HTMLDivElement;
    mockGeometry(transcript);
    return { ...utils, transcript };
  }

  const userScroll = (el: HTMLElement, top: number) => {
    el.scrollTop = top;
    fireEvent.scroll(el);
  };

  it("no Jump-to-latest pill while the user is at the bottom", () => {
    renderWithTranscript();
    expect(
      screen.queryByRole("button", { name: /jump to latest/i }),
    ).toBeNull();
  });

  it("a streamed turn replacement while scrolled up never moves the transcript (regression)", () => {
    const { transcript, rerender, props } = renderWithTranscript();
    userScroll(transcript, 100);
    expect(
      screen.getByRole("button", { name: /jump to latest/i }),
    ).toBeInTheDocument();

    // The streaming shape: a new turns array with the last turn replaced.
    rerender(
      <AgentChatPanel
        {...props}
        turns={[
          { role: "user", text: "q1" },
          { role: "agent", text: "streaming… plus another chunk" },
        ]}
      />,
    );
    expect(transcript.scrollTop).toBe(100);
  });

  it("clicking the pill jumps to the latest message, resumes follow, and hides", () => {
    const { transcript, rerender, props } = renderWithTranscript();
    userScroll(transcript, 100);
    fireEvent.click(screen.getByRole("button", { name: /jump to latest/i }));
    expect(transcript.scrollTop).toBe(BOTTOM);
    expect(screen.queryByRole("button", { name: /jump to latest/i })).toBeNull();

    // Follow is re-engaged: the next streamed chunk keeps the view pinned.
    rerender(
      <AgentChatPanel
        {...props}
        turns={[
          { role: "user", text: "q1" },
          { role: "agent", text: "streaming… done" },
        ]}
      />,
    );
    expect(transcript.scrollTop).toBe(BOTTOM);
  });

  it("a wheel-up during streaming detaches before the next chunk re-pins (dev/79 race)", () => {
    const { transcript, rerender, props } = renderWithTranscript();
    // The wheel moves scrollTop synchronously; the next streamed chunk is
    // processed before the browser dispatches the coalesced scroll event.
    fireEvent.wheel(transcript, { deltaY: -120 });
    rerender(
      <AgentChatPanel
        {...props}
        turns={[
          { role: "user", text: "q1" },
          { role: "agent", text: "streaming… plus another chunk" },
        ]}
      />,
    );
    expect(transcript.scrollTop).toBe(0); // held at the user's position
    fireEvent.scroll(transcript);
    expect(
      screen.getByRole("button", { name: /jump to latest/i }),
    ).toBeInTheDocument();
  });

  it("the pill sits in a row of its own above the composer, outside the conversation", () => {
    const { transcript } = renderWithTranscript();
    userScroll(transcript, 100);
    const pill = screen.getByRole("button", { name: /jump to latest/i });
    expect(transcript.contains(pill)).toBe(false);
    const composer = screen.getByPlaceholderText(/^Message /);
    // eslint-disable-next-line no-bitwise
    expect(transcript.compareDocumentPosition(pill) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    // eslint-disable-next-line no-bitwise
    expect(pill.compareDocumentPosition(composer) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    // Its row is a sibling of the conversation, so it takes room of its own.
    expect(pill.parentElement!.className).toBe("jumpRow");
    expect(pill.parentElement!.parentElement).toBe(transcript.parentElement);
  });

  it("scrolling back to the bottom manually also hides the pill", () => {
    const { transcript } = renderWithTranscript();
    userScroll(transcript, 100);
    expect(
      screen.getByRole("button", { name: /jump to latest/i }),
    ).toBeInTheDocument();
    userScroll(transcript, BOTTOM);
    expect(screen.queryByRole("button", { name: /jump to latest/i })).toBeNull();
  });

  it("sending a message re-pins to the bottom even when scrolled up", async () => {
    const onSend = jest.fn().mockResolvedValue(undefined);
    const { transcript } = renderWithTranscript({ onSend });
    userScroll(transcript, 100);
    fireEvent.change(screen.getByPlaceholderText(/^Message /), {
      target: { value: "follow up" },
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Send" }));
    });
    expect(onSend).toHaveBeenCalledWith("follow up");
    expect(transcript.scrollTop).toBe(BOTTOM);
    expect(screen.queryByRole("button", { name: /jump to latest/i })).toBeNull();
  });

  describe("unread count on the pill (dev/83)", () => {
    it("a reply landing while scrolled up labels the pill '1 new' with the count in the accessible name", () => {
      const { transcript, rerender, props } = renderWithTranscript();
      userScroll(transcript, 100);
      rerender(
        <AgentChatPanel
          {...props}
          turns={[
            { role: "user", text: "q1" },
            { role: "agent", text: "streaming…" },
            { role: "agent", text: "a new reply" },
          ]}
        />,
      );
      expect(
        screen.getByRole("button", { name: "Jump to 1 new message" }),
      ).toHaveTextContent("1 new");
    });

    it("accumulates per landed turn; the jump resets it and a fresh detach starts from zero", () => {
      const { transcript, rerender, props } = renderWithTranscript();
      userScroll(transcript, 100);
      rerender(
        <AgentChatPanel
          {...props}
          turns={[
            { role: "user", text: "q1" },
            { role: "agent", text: "streaming…" },
            { role: "agent", text: "reply 2" },
            { role: "agent", text: "reply 3" },
          ]}
        />,
      );
      fireEvent.click(screen.getByRole("button", { name: "Jump to 2 new messages" }));
      expect(screen.queryByRole("button", { name: /jump to/i })).toBeNull();
      fireEvent.scroll(transcript); // the jump's scroll lands (browser event)
      userScroll(transcript, 100); // detach again — the baseline resets
      expect(
        screen.getByRole("button", { name: "Jump to latest messages" }),
      ).toHaveTextContent("Latest");
    });

    it("streamed chunk growth never increments — the pill stays 'Latest'", () => {
      const { transcript, rerender, props } = renderWithTranscript();
      userScroll(transcript, 100);
      rerender(
        <AgentChatPanel
          {...props}
          turns={[
            { role: "user", text: "q1" },
            { role: "agent", text: "streaming… plus a much longer chunk" },
          ]}
        />,
      );
      expect(
        screen.getByRole("button", { name: "Jump to latest messages" }),
      ).toHaveTextContent("Latest");
    });
  });
});


// ── Per-reply run status + token counters (memo dev/80, amended) ──

describe("AgentChatPanel per-reply run status (memo dev/80)", () => {
  // Fresh per use: a stale startedAt would drift the elapsed readout.
  const runningStatus = () => ({ phase: "running" as const, startedAt: Date.now() });

  const doneTurn = (text: string, tokens: [number, number], durationMs = 5000): AgentSessionTurn => ({
    role: "agent",
    text,
    execution: {
      executionId: `e-${text}`,
      usage: { inputTokens: tokens[0], outputTokens: tokens[1] },
      status: "ok",
      durationMs,
    },
  });

  it("before the first delta a standalone pending row shows the live indicator", () => {
    renderPanel({
      runStatus: runningStatus(),
      turns: [{ role: "user", text: "q1" }],
    });
    const status = screen.getByRole("status");
    expect(status).toHaveTextContent(/Cooking… · 0:00/);
    expect(status).toHaveTextContent(/agent is working/i);
  });

  it("while streaming, the live indicator rides the in-flight reply itself", () => {
    renderPanel({
      runStatus: runningStatus(),
      turns: [
        { role: "user", text: "q1" },
        { role: "agent", text: "partial rep" },
      ],
    });
    // Exactly one indicator: on the streaming turn, no extra pending row.
    const statuses = screen.getAllByRole("status");
    expect(statuses).toHaveLength(1);
    expect(statuses[0]).toHaveTextContent(/Cooking… · 0:00/);
  });

  it("every finalized reply carries its own duration and tokens", () => {
    renderPanel({
      turns: [
        { role: "user", text: "q1" },
        doneTurn("a1", [400, 1032], 12000),
        { role: "user", text: "q2" },
        doneTurn("a2", [100, 100], 900),
      ],
    });
    const statuses = screen.getAllByRole("status");
    expect(statuses).toHaveLength(2);
    expect(statuses[0]).toHaveTextContent("Finished in 12s · 1.4k tokens");
    expect(statuses[1]).toHaveTextContent("Finished in 1s · 200 tokens");
  });

  it("the cumulative counter accumulates across replies while each keeps its own", () => {
    renderPanel({
      turns: [
        { role: "user", text: "q1" },
        doneTurn("a1", [400, 1032]),
        { role: "user", text: "q2" },
        doneTurn("a2", [100, 100]),
      ],
    });
    // More's Tokens used: no strip above the composer any more.
    openMore();
    expect(screen.getByLabelText(/session token usage/i)).toHaveTextContent("Tokens used: 1.6k");
    expect(screen.getByLabelText(/session token usage/i)).toHaveTextContent("over 2 replies");
  });

  it("while a turn runs, Send stays ready: the message is asked and waits its turn", async () => {
    const onSend = jest.fn().mockResolvedValue(undefined);
    renderPanel({ runStatus: runningStatus(), onSend });
    fireEvent.change(screen.getByPlaceholderText(/^Message /), {
      target: { value: "queued question" },
    });
    const send = screen.getByRole("button", { name: "Send" });
    expect(send).not.toBeDisabled();
    expect(send).not.toHaveTextContent("…");
    fireEvent.click(send);
    expect(onSend).toHaveBeenCalledWith("queued question");
    await waitFor(() => expect(screen.getByPlaceholderText(/^Message /)).toHaveValue(""));
  });

  it("while a turn runs, Stop asks for it to stop, once, and goes with the turn", async () => {
    let finish: () => void = () => undefined;
    const onStopTurn = jest.fn(() => new Promise<void>((resolve) => { finish = resolve; }));
    const { rerender, props } = renderPanel({
      runStatus: runningStatus(), turns: [{ role: "user", text: "q1" }], onStopTurn,
    });
    const stop = screen.queryByRole("button", { name: "Stop" });
    expect(stop).toBeInTheDocument();
    // In the composer, in Send's place: the transcript holds no Stop of its own.
    expect(stop).toHaveAttribute("data-agent-turn-stop");
    expect(stop).toHaveAttribute("data-tooltip", "Stop the reply");
    expect((document.querySelector(".messages") as HTMLElement).contains(stop)).toBe(false);
    expect(screen.queryByRole("button", { name: "Send" })).toBeNull();
    expect(document.querySelectorAll("[data-agent-turn-stop]")).toHaveLength(1);
    fireEvent.click(stop as HTMLElement);
    expect(onStopTurn).toHaveBeenCalledTimes(1);
    const stopping = screen.getByRole("button", { name: "Stopping…" });
    expect(stopping).toBeDisabled();
    fireEvent.click(stopping);
    expect(onStopTurn).toHaveBeenCalledTimes(1);
    await act(async () => finish());
    rerender(<AgentChatPanel {...props} runStatus={{ phase: "done", startedAt: Date.now(), durationMs: 10 }} />);
    expect(screen.queryByRole("button", { name: /^Stop/ })).not.toBeInTheDocument();
    // Send is back in its place.
    expect(screen.getByRole("button", { name: "Send" })).toBeInTheDocument();
  });

  it("while a turn runs, a message typed brings Send back, and clearing it brings Stop back", () => {
    renderPanel({ runStatus: runningStatus(), turns: [{ role: "user", text: "q1" }], onStopTurn: jest.fn() });
    const composer = screen.getByPlaceholderText(/^Message /);
    fireEvent.change(composer, { target: { value: "and then?" } });
    expect(screen.getByRole("button", { name: "Send" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Stop" })).toBeNull();
    fireEvent.change(composer, { target: { value: "" } });
    expect(screen.getByRole("button", { name: "Stop" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Send" })).toBeNull();
  });

  it("the press that sends never lands on Stop, which takes Send's place as a button of its own", async () => {
    const user = userEvent.setup();
    const onSend = jest.fn().mockResolvedValue(undefined);
    const onStopTurn = jest.fn().mockResolvedValue(undefined);
    renderPanel({ runStatus: runningStatus(), turns: [{ role: "user", text: "q1" }], onSend, onStopTurn });
    const box = screen.getByRole("textbox", { name: /^Message / });
    await user.type(box, "and then?");
    const send = screen.getByRole("button", { name: "Send" });
    await user.click(send);
    expect(onSend).toHaveBeenCalledWith("and then?");

    // Not the Send that was pressed, relabelled: a button of its own.
    const stop = screen.getByRole("button", { name: "Stop" });
    expect(stop).not.toBe(send);
    expect(send).not.toBeInTheDocument();
    // The focus is back in the message box, so a held Enter sends nothing
    // more and stops nothing.
    expect(box).toHaveFocus();
    await user.keyboard("{Enter}");
    expect(onSend).toHaveBeenCalledTimes(1);
    expect(onStopTurn).not.toHaveBeenCalled();
    // A double click's second click lands where Send was, on Stop: it stops
    // nothing. A click of its own does.
    fireEvent.click(stop, { detail: 2 });
    expect(onStopTurn).not.toHaveBeenCalled();
    fireEvent.click(stop, { detail: 1 });
    expect(onStopTurn).toHaveBeenCalledTimes(1);
  });

  it("a stopped reply says who stopped it and after how long", () => {
    renderPanel({
      turns: [
        { role: "user", text: "Rewrite the sum." },
        {
          role: "agent",
          text: "I will rewrite it.",
          execution: {
            executionId: "e-stopped",
            usage: null,
            status: "stopped",
            durationMs: 8000,
            stoppedBy: { kind: "person", account: "7", name: "Ana" },
          },
        },
      ],
    });
    expect(screen.getByRole("status")).toHaveTextContent("Stopped by Ana after 8s");
  });

  it("the asks waiting their turn follow the transcript, each named by its writer, and its asker may withdraw their own", async () => {
    const onWithdrawAsk = jest.fn().mockResolvedValue(undefined);
    renderPanel({
      runStatus: runningStatus(),
      turns: [{ role: "user", text: "q1" }],
      viewerAccount: "3",
      waitingAsks: [
        { askId: "k-bob", by: { kind: "person", account: "7", name: "Bob" }, message: "And the map?", status: "waiting" },
        { askId: "k-mine", by: { kind: "person", account: "3", name: "Ana" }, message: "Mine too.", status: "waiting" },
        { askId: "k-now", by: null, message: "Just sent.", status: "sending" },
      ],
      onWithdrawAsk,
    });
    expect(screen.queryByText("And the map?")).toBeInTheDocument();
    const bobs = screen.getByText("And the map?").closest("[data-agent-ask]") as HTMLElement;
    expect(bobs).toHaveAttribute("data-agent-ask-status", "waiting");
    expect(within(bobs).getByText("Bob")).toBeInTheDocument();
    expect(within(bobs).getByText(/Waiting its turn/)).toBeInTheDocument();
    expect(within(bobs).queryByRole("button", { name: "Withdraw" })).not.toBeInTheDocument();
    const mine = screen.getByText("Mine too.").closest("[data-agent-ask]") as HTMLElement;
    expect(within(mine).queryByText("Ana")).not.toBeInTheDocument();
    const just = screen.getByText("Just sent.").closest("[data-agent-ask]") as HTMLElement;
    expect(within(just).queryByText(/Waiting its turn/)).not.toBeInTheDocument();
    fireEvent.click(within(mine).getByRole("button", { name: "Withdraw" }));
    expect(onWithdrawAsk).toHaveBeenCalledWith("k-mine");
    await waitFor(() => expect(within(mine).getByRole("button", { name: "Withdraw" })).toBeDisabled());
  });

  it("a wired-idle status re-enables send even while another chat's send is in flight (cycling leak fix)", async () => {
    // A never-resolving onSend leaves the panel-local `sending` flag true —
    // exactly the state carried across an attachment cycle. The provider's
    // per-attachment status (null = idle) must win.
    const onSend = jest.fn().mockReturnValue(new Promise(() => undefined));
    const { rerender, props } = renderPanel({ onSend, runStatus: runningStatus() });
    fireEvent.change(screen.getByPlaceholderText(/^Message /), {
      target: { value: "first" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    // Cycled to another attachment: its status is idle.
    rerender(
      <AgentChatPanel
        {...props}
        attachment={{ ...attachment, attachmentId: "a2", sessionId: "s2other" }}
        runStatus={null}
      />,
    );
    fireEvent.change(screen.getByPlaceholderText(/^Message /), {
      target: { value: "second chat draft" },
    });
    const send = screen.getByRole("button", { name: "Send" });
    expect(send).not.toBeDisabled();
    expect(send).not.toHaveTextContent("…");
  });

  it("an old-server finalized reply (no execution fields) falls back to the run record", () => {
    renderPanel({
      runStatus: {
        phase: "done",
        startedAt: Date.now() - 12000,
        durationMs: 12000,
        usage: { inputTokens: 400, outputTokens: 1032 },
      },
      turns: [
        { role: "user", text: "q1" },
        { role: "agent", text: "a1" },
      ],
    });
    expect(screen.getByRole("status")).toHaveTextContent("Finished in 12s · 1.4k tokens");
  });

  it("a turn the runtime wrote after the reply (a source's candidates) takes no run record of its own", () => {
    renderPanel({
      runStatus: {
        phase: "done",
        startedAt: Date.now() - 12000,
        durationMs: 12000,
        usage: { inputTokens: 400, outputTokens: 1032 },
      },
      turns: [
        { role: "user", text: "q1" },
        doneTurn("a1", [400, 1032], 12000),
        { role: "agent", text: "Load pedestrians needs a source." },
      ],
    });
    // One line, the reply's: the runtime's turn is not the reply again.
    const statuses = screen.getAllByRole("status");
    expect(statuses).toHaveLength(1);
    expect(statuses[0]).toHaveTextContent("Finished in 12s · 1.4k tokens");
  });

  it("a failed reply shows the failed state with elapsed-at-failure from the run record", () => {
    renderPanel({
      runStatus: { phase: "error", startedAt: Date.now() - 8000, durationMs: 8000 },
      turns: [
        { role: "user", text: "q1" },
        { role: "agent", text: "(error) boom", error: true },
      ],
    });
    expect(screen.getByRole("status")).toHaveTextContent("Failed after 8s");
  });

  it("a rehydrated error turn derives the failed state without a run record", () => {
    renderPanel({
      turns: [
        { role: "user", text: "q1" },
        { role: "agent", text: "(error) boom", error: true },
      ],
    });
    expect(screen.getByRole("status")).toHaveTextContent("Failed");
  });

  it("a pending install review marks only the newest reply", () => {
    renderPanel({
      attachment: {
        ...attachment,
        activeProposal: {
          proposalId: "p1",
          tool: "dataset.install",
          nodeId: "",
          summary: "Install dataset · Cities",
          status: "pending",
        },
      },
      turns: [
        { role: "user", text: "q1" },
        doneTurn("a1", [10, 10]),
        { role: "user", text: "q2" },
        doneTurn("a2", [10, 10]),
      ],
    });
    const chips = screen.getAllByText("Awaiting your review");
    expect(chips).toHaveLength(1);
    const statuses = screen.getAllByRole("status");
    expect(statuses[0]).not.toHaveTextContent("Awaiting your review");
    expect(statuses[1]).toHaveTextContent("Awaiting your review");
  });

  it("a review of a change saved before agents edited directly awaits nothing and keeps Dismiss alone", () => {
    const onApplyProposal = jest.fn().mockResolvedValue(undefined);
    const onDismissProposal = jest.fn().mockResolvedValue(undefined);
    const summary = "Replace the content of node n1";
    renderPanel({
      attachment: {
        ...attachment,
        activeProposal: { proposalId: "p-old", tool: "node.content.write", nodeId: "n1", summary, status: "pending" },
      },
      turns: [
        { role: "user", text: "q1" },
        {
          ...doneTurn("a1", [10, 10]),
          content: [{
            type: "proposal", proposalId: "p-old", tool: "node.content.write", summary,
            preview: "print(2)", pins: { nodeId: "n1" }, status: "pending",
          }],
        } as AgentSessionTurn,
      ],
      onApplyProposal,
      onDismissProposal,
    });
    expect(screen.queryByText("Awaiting your review")).toBeNull();
    const saved = within(screen.getByRole("group", { name: `Review proposal: ${summary}` }));
    expect(saved.queryByRole("button", { name: "Apply" })).toBeNull();
    // Read here, so a checkout without it fails this test alone.
    const { MADE_BEFORE_DIRECT_EDITS } = require("../../components/agents/content/reviewCard/reviewCardText");
    expect(MADE_BEFORE_DIRECT_EDITS).toEqual(expect.any(String));
    expect(saved.getByText(MADE_BEFORE_DIRECT_EDITS)).toBeInTheDocument();
    fireEvent.click(saved.getByRole("button", { name: "Dismiss" }));
    expect(onDismissProposal).toHaveBeenCalledWith("p-old");
    expect(onApplyProposal).not.toHaveBeenCalled();
  });

  it("the live cumulative counter includes the in-flight run's interim sums", () => {
    renderPanel({
      runStatus: {
        ...runningStatus(),
        liveUsage: { inputTokens: 1000, outputTokens: 500 },
      },
      turns: [
        { role: "user", text: "q1" },
        doneTurn("a1", [300, 200]),
        { role: "user", text: "q2" },
      ],
    });
    openMore();
    expect(screen.getByLabelText(/session token usage/i)).toHaveTextContent("Tokens used: 2.0k");
  });

  it("a pristine chat renders no status and no counter", () => {
    renderPanel({ onClearConversation: jest.fn() });
    expect(screen.queryByRole("status")).toBeNull();
    const menu = openMore();
    expect(screen.queryByLabelText(/session token usage/i)).toBeNull();
    expect(within(menu).queryByText(/Tokens used/)).toBeNull();
  });

  it("pre-dev/37 history (no execution record) renders no fabricated status", () => {
    renderPanel({
      turns: [
        { role: "user", text: "q1" },
        { role: "agent", text: "a1" },
      ],
    });
    expect(screen.queryByRole("status")).toBeNull();
  });
});


describe("AgentChatPanel — dev/114 candidates in the Node Builder chat", () => {
  const candidatesTurns: AgentSessionTurn[] = [
    { role: "user", text: "build a node that loads heat data" },
    {
      role: "agent",
      text: "Select a source and confirm.",
      content: [
        {
          type: "datasetCandidates",
          lanes: {
            external: [
              { name: "NOAA Climate Data API", sourceType: "api", url: "https://api.noaa.gov",
                verification: { status: "verified", httpStatus: 200 } },
            ],
            catalog: [],
          },
        },
      ],
    },
  ];

  it("a selection prefills the BUILD request when the host is Node Builder", () => {
    renderPanel({
      attachment: {
        ...attachment,
        coord: "agent.curio.node-builder@1",
        name: "Node Builder",
        capabilities: NODE_BUILDER_CAPABILITIES,
      },
      turns: candidatesTurns,
    });
    fireEvent.click(screen.getByRole("checkbox", { name: "Select NOAA Climate Data API" }));
    expect(screen.getByPlaceholderText(/^Message /)).toHaveValue(
      "Build the data-loading node — fetch from: NOAA Climate Data API (https://api.noaa.gov).",
    );
  });

  it("a selection prefills the hand-off confirmation in any other chat", () => {
    renderPanel({
      attachment: {
        ...attachment,
        coord: "agent.curio.dataset-finder@1",
        name: "Dataset Finder",
        capabilities: DATASET_FINDER_CAPABILITIES,
        nodeBuildDelegate: "Node Builder",
      },
      turns: candidatesTurns,
    });
    fireEvent.click(screen.getByRole("checkbox", { name: "Select NOAA Climate Data API" }));
    expect(screen.getByPlaceholderText(/^Message /)).toHaveValue(
      "Confirm my selection — hand off to Node Builder: NOAA Climate Data API.",
    );
  });
});

describe("AgentChatPanel — dev/115 the per-node Solve row", () => {
  const nodeAttachment: AgentAttachment = {
    ...attachment,
    coord: "agent.curio.node-builder@1",
    name: "Node Builder",
    target: { kind: "node" as const, targetId: "n1" },
    solvesNodes: true,
  };

  it("offers Solve this node for a node-attached agent, its hint on its tooltip, and reports the outcome", async () => {
    const onSolveNode = jest.fn().mockResolvedValue({ verdict: "pass", rounds: 2, proposalId: "p9" });
    renderPanel({ attachment: nodeAttachment, targetName: "Data Loading", onSolveNode });
    const row = screen.getByRole("group", { name: "Solve this node" });
    const button = within(row).getByRole("button", { name: "Solve this node" });
    // One line: what it does is the button's tooltip, not a line of its own.
    expect(button).toHaveAttribute("data-tooltip", expect.stringMatching(/only code that passed lands/));
    expect(row).not.toHaveTextContent(/only code that passed lands/);
    fireEvent.click(button);
    expect(onSolveNode).toHaveBeenCalledTimes(1);
    await waitFor(() =>
      expect(within(row).getByRole("status")).toHaveTextContent(/corrected code ran successfully/),
    );
  });

  it("a live per-node job shows Solving with the background copy and the narration", () => {
    renderPanel({
      attachment: { ...nodeAttachment, liveJob: { executionId: "e2", kind: "solve-node", status: "running", startedAt: 1 } },
      onSolveNode: jest.fn(),
      solveNodeActivity: "Round 2 — generating a fix…",
    });
    const row = screen.getByRole("group", { name: "Solve this node" });
    const solving = within(row).getByRole("button", { name: "Solving…" });
    expect(solving).toBeDisabled();
    expect(solving).toHaveAttribute("data-tooltip", "Solve keeps running if you close this panel.");
    expect(row).toHaveTextContent("Round 2 — generating a fix…");
  });

  it("a live per-node job with no narration yet says it keeps running", () => {
    renderPanel({
      attachment: { ...nodeAttachment, liveJob: { executionId: "e2", kind: "solve-node", status: "running", startedAt: 1 } },
      onSolveNode: jest.fn(),
    });
    expect(screen.getByRole("group", { name: "Solve this node" })).toHaveTextContent(
      "Solve keeps running if you close this panel.",
    );
  });

  it("no row for canvas attachments or without the callback", () => {
    renderPanel({ attachment: nodeAttachment });
    expect(screen.queryByRole("group", { name: "Solve this node" })).toBeNull();
    renderPanel({ onSolveNode: jest.fn() }); // canvas target
    expect(screen.queryByRole("group", { name: "Solve this node" })).toBeNull();
  });

  it("a Solve of the node that starts elsewhere shows its narration, not the last error, which it clears", async () => {
    const onSolveNode = jest.fn().mockRejectedValue(new Error("the sandbox refused the run"));
    const { rerender, props } = renderPanel({ attachment: nodeAttachment, onSolveNode });
    const row = screen.getByRole("group", { name: "Solve this node" });
    fireEvent.click(within(row).getByRole("button", { name: "Solve this node" }));
    expect(await within(row).findByText("the sandbox refused the run")).toBeInTheDocument();

    // The plan's row for this node, or another tab, starts a Solve of it.
    const running = { ...nodeAttachment, liveJob: { executionId: "e3", kind: "solve-node", status: "running" as const, startedAt: 1 } };
    rerender(<AgentChatPanel {...props} attachment={running} solveNodeActivity="Round 1: generating the code…" />);
    expect(within(row).getByRole("button", { name: "Solving…" })).toBeDisabled();
    expect(row).toHaveTextContent("Round 1: generating the code…");
    expect(row).not.toHaveTextContent("the sandbox refused the run");

    // It ends: the error it replaced does not come back.
    rerender(<AgentChatPanel {...props} attachment={nodeAttachment} solveNodeActivity={null} />);
    expect(within(row).getByRole("button", { name: "Solve this node" })).toBeEnabled();
    expect(row).not.toHaveTextContent("the sandbox refused the run");
  });
});

describe("AgentChatPanel keeps what each chat started to itself as the rail switches agents", () => {
  // The rail opens another agent's chat in the same panel, which does not
  // slide out and in again: what one chat started must not show in the next.
  const onNode = (attachmentId: string, targetId: string): AgentAttachment => ({
    ...attachment,
    attachmentId,
    sessionId: `s-${attachmentId}`,
    coord: "agent.curio.node-builder@1",
    name: "Node Builder",
    target: { kind: "node" as const, targetId },
    solvesNodes: true,
  });

  it("Solve this node, running or ended on one node's chat, is not shown on another's", async () => {
    let finish: (outcome: unknown) => void = () => undefined;
    const onSolveNode = jest.fn(() => new Promise((resolve) => { finish = resolve; }));
    const { rerender, props } = renderPanel({ attachment: onNode("a", "n-a"), onSolveNode });
    fireEvent.click(screen.getByRole("button", { name: "Solve this node" }));
    expect(screen.getByRole("button", { name: "Solving…" })).toBeDisabled();

    rerender(<AgentChatPanel {...props} attachment={onNode("b", "n-b")} />);
    const row = screen.getByRole("group", { name: "Solve this node" });
    expect(within(row).getByRole("button", { name: "Solve this node" })).toBeEnabled();
    expect(row).not.toHaveTextContent("Solve keeps running if you close this panel.");

    // The first node's Solve ends while the second's chat is open.
    await act(async () => finish({ verdict: "pass", unchanged: true }));
    expect(row).not.toHaveTextContent(/Verified/);
    expect(within(row).queryByRole("status")).toBeNull();
  });

  it("Stop asked of one chat's turn is not shown on another's, and is still asked on coming back", () => {
    const first = { phase: "running" as const, startedAt: 1000 };
    const onStopTurn = jest.fn(() => new Promise<void>(() => undefined));
    const { rerender, props } = renderPanel({
      attachment: onNode("a", "n-a"), runStatus: first, turns: [{ role: "user", text: "q1" }], onStopTurn,
    });
    fireEvent.click(screen.getByRole("button", { name: "Stop" }));
    expect(screen.getByRole("button", { name: "Stopping…" })).toBeDisabled();

    // Another chat, whose own turn runs.
    rerender(<AgentChatPanel {...props} attachment={onNode("b", "n-b")} runStatus={{ phase: "running", startedAt: 2000 }} />);
    expect(screen.queryByRole("button", { name: "Stopping…" })).toBeNull();
    expect(screen.getByRole("button", { name: "Stop" })).toBeEnabled();

    // Back on the first, whose turn was asked to stop and still runs.
    rerender(<AgentChatPanel {...props} attachment={onNode("a", "n-a")} runStatus={first} />);
    expect(screen.getByRole("button", { name: "Stopping…" })).toBeDisabled();
    expect(onStopTurn).toHaveBeenCalledTimes(1);
  });
});


describe("AgentChatPanel — dev/116 the per-node Solve row's remedy", () => {
  it("a source-missing outcome with a remedy offers Add key for the host", async () => {
    const { subscribeApiSettingsRequests } = await import("../../components/apiSettings/apiSettingsRequest");
    const seen: unknown[] = [];
    const off = subscribeApiSettingsRequests((f) => seen.push(f));
    const onSolveNode = jest.fn().mockResolvedValue({
      verdict: "fail", rounds: 2,
      remedy: { kind: "connection-key", host: "api.census.gov", suggestedName: "census" },
    });
    renderPanel({
      attachment: { ...attachment, coord: "agent.curio.node-builder@1", name: "Node Builder", target: { kind: "node" as const, targetId: "n1" }, solvesNodes: true },
      targetName: "Data Loading",
      onSolveNode,
    });
    const row = screen.getByRole("group", { name: "Solve this node" });
    fireEvent.click(within(row).getByRole("button", { name: "Solve this node" }));
    const add = await within(row).findByRole("button", { name: "Add key for api.census.gov" });
    expect(within(row).getByRole("status")).toHaveTextContent(/Not fixed after 2 attempts/);
    fireEvent.click(add);
    expect(seen).toEqual([{ section: "connection-keys", host: "api.census.gov", suggestedName: "census" }]);
    off();
  });

  it("a failed outcome names what stopped the loop, in the words the server uses", async () => {
    const { phrases: STOPPED_BY_PHRASES } = require("../../contracts/solveStopReasons.json") as {
      phrases: Readonly<Record<string, string>>;
    };
    const onSolveNode = jest.fn().mockResolvedValue({ verdict: "fail", rounds: 2, stoppedBy: "budget" });
    renderPanel({
      attachment: { ...attachment, coord: "agent.curio.node-builder@1", name: "Node Builder", target: { kind: "node" as const, targetId: "n1" }, solvesNodes: true },
      targetName: "Data Loading",
      onSolveNode,
    });
    const row = screen.getByRole("group", { name: "Solve this node" });
    fireEvent.click(within(row).getByRole("button", { name: "Solve this node" }));
    expect(await within(row).findByRole("status")).toHaveTextContent(
      `Not fixed after 2 attempts (${STOPPED_BY_PHRASES.budget}): every attempt is below`,
    );
  });

  it("says one attempt in the singular", async () => {
    const { phrases: STOPPED_BY_PHRASES } = require("../../contracts/solveStopReasons.json") as {
      phrases: Readonly<Record<string, string>>;
    };
    const onSolveNode = jest.fn().mockResolvedValue({ verdict: "fail", rounds: 1, stoppedBy: "budget" });
    renderPanel({
      attachment: { ...attachment, coord: "agent.curio.node-builder@1", name: "Node Builder", target: { kind: "node" as const, targetId: "n1" }, solvesNodes: true },
      targetName: "Data Loading",
      onSolveNode,
    });
    const row = screen.getByRole("group", { name: "Solve this node" });
    fireEvent.click(within(row).getByRole("button", { name: "Solve this node" }));
    expect(await within(row).findByRole("status")).toHaveTextContent(
      `Not fixed after 1 attempt (${STOPPED_BY_PHRASES.budget}): every attempt is below`,
    );
  });

  // dev/126: the awaiting-selection remedy — the twin of the key remedy. The
  // node's source is with the user, so the row offers the chat that holds the
  // candidates instead of a failure message with advice in it.
  it("an awaiting-source outcome offers the node's Dataset Finder", async () => {
    const onOpenAgentChat = jest.fn();
    const onSolveNode = jest.fn().mockResolvedValue({
      verdict: "awaiting-source",
      rounds: 3,
      remedy: { kind: "dataset-selection", attachmentId: "att-df", nodeId: "n1" },
    });
    renderPanel({
      attachment: {
        ...attachment,
        coord: "agent.curio.node-builder@1",
        name: "Node Builder",
        target: { kind: "node" as const, targetId: "n1" },
        solvesNodes: true,
      },
      targetName: "Data Loading",
      onSolveNode,
      onOpenAgentChat,
      agentNameOf: (id: string) => (id === "att-df" ? "Dataset Finder" : null),
    });
    const row = screen.getByRole("group", { name: "Solve this node" });
    fireEvent.click(within(row).getByRole("button", { name: "Solve this node" }));
    const open = await within(row).findByRole("button", {
      name: "Open Dataset Finder for this node",
    });
    expect(within(row).getByRole("status")).toHaveTextContent(/Awaiting a source/);
    expect(within(row).getByRole("status")).toHaveTextContent(/Nothing was generated or written/);
    fireEvent.click(open);
    expect(onOpenAgentChat).toHaveBeenCalledWith("att-df");
  });

  it("a Dataset Finder on a node can record the confirmed source", async () => {
    const onRecordDatasetSelection = jest
      .fn()
      .mockResolvedValue({ attachmentId: "att-df", nodeId: "n1", status: "resolved", picks: [] });
    renderPanel({
      attachment: {
        ...attachment,
        attachmentId: "att-df",
        coord: "agent.curio.dataset-finder@1",
        name: "Dataset Finder",
        capabilities: DATASET_FINDER_CAPABILITIES,
        target: { kind: "node" as const, targetId: "n1" },
      },
      turns: [
        {
          role: "agent" as const,
          text: "2 candidates",
          content: [
            {
              type: "datasetCandidates" as const,
              lanes: {
                external: [
                  {
                    name: "Chicago areas",
                    sourceType: "portal",
                    url: "https://data.example.org/areas.geojson",
                  },
                ],
                catalog: [],
              },
            },
          ],
        },
      ],
      onRecordDatasetSelection,
    });
    const card = screen.getByRole("group", { name: "Dataset candidates" });
    const confirm = within(card).getByRole("button", { name: /Use this source/ });
    expect(confirm).toBeDisabled();  // nothing selected yet
    fireEvent.click(within(card).getByRole("checkbox", { name: "Select Chicago areas" }));
    fireEvent.click(confirm);
    await screen.findByText(/Source recorded for this node/);
    // Identifiers ONLY: the server resolves the url against its own rows.
    expect(onRecordDatasetSelection).toHaveBeenCalledWith([
      { lane: "external", key: "https://data.example.org/areas.geojson" },
    ]);
  });

  // dev/127: the trail rides the transcript, so opening the panel shows it.
  it("renders a failed node's attempt trail from the transcript", () => {
    const onOpenAgentChat = jest.fn();
    renderPanel({
      turns: [
        {
          role: "agent" as const,
          text: "Solved 5 of 7 plan nodes.",
          content: [
            {
              type: "solveAttempts" as const,
              nodeId: "08b108a1",
              label: "Calculate Density",
              attachmentId: "att-nb",
              rounds: 2,
              stoppedBy: "budget",
              verdict: "fail",
              attempts: [
                {
                  round: 1,
                  verdict: "fail",
                  kind: "execution-error",
                  error: "KeyError: 'community_area'",
                  code: "merged = a.merge(b, on='community_area')",
                },
                {
                  round: 2,
                  verdict: "fail",
                  kind: "execution-error",
                  error: "AttributeError: 'DataFrame' object has no attribute 'crs'",
                  code: "return merged.to_crs(3395)",
                },
              ],
            },
          ],
        },
      ],
      onOpenAgentChat,
      agentNameOf: (id: string) => (id === "att-nb" ? "Node Builder" : null),
    });
    const card = screen.getByRole("group", { name: /Attempts to fix Calculate Density/ });
    expect(card).toHaveTextContent("KeyError: 'community_area'");
    expect(card).toHaveTextContent("return merged.to_crs(3395)");
    expect(card).toHaveTextContent(/this node's time budget was spent/);
    fireEvent.click(
      within(card).getByRole("button", { name: /Open the Node Builder for Calculate Density/ }),
    );
    expect(onOpenAgentChat).toHaveBeenCalledWith("att-nb");
  });

  it("a Dataset Finder on the canvas offers no per-node confirm", () => {
    renderPanel({
      attachment: {
        ...attachment,
        coord: "agent.curio.dataset-finder@1",
        name: "Dataset Finder",
        target: { kind: "canvas" as const },
      },
      turns: [
        {
          role: "agent" as const,
          text: "candidates",
          content: [
            {
              type: "datasetCandidates" as const,
              lanes: {
                external: [{ name: "Chicago areas", sourceType: "portal" }],
                catalog: [],
              },
            },
          ],
        },
      ],
      onRecordDatasetSelection: jest.fn(),
    });
    const card = screen.getByRole("group", { name: "Dataset candidates" });
    expect(
      within(card).queryByRole("button", { name: /Use this source/ }),
    ).toBeNull();
  });
});

// An agent is found by what its manifest declares, never by its id: a user's
// own copy of a shipped card, under another id and name, gets what the card gets.
describe("AgentChatPanel offers each feature by what the agent declares", () => {
  const candidates: AgentSessionTurn = {
    role: "agent" as const,
    text: "1 candidate",
    content: [
      {
        type: "datasetCandidates" as const,
        lanes: {
          external: [
            { name: "Chicago areas", sourceType: "portal", url: "https://data.example.org/areas.geojson" },
          ],
          catalog: [],
        },
      },
    ],
  };

  it("an agent that declares dataflow.orchestrate gets the plan line, under its own name", () => {
    renderPanel({
      attachment: {
        ...attachment,
        coord: "agent.test.my-orchestrator@1",
        name: "My Orchestrator",
        category: "canvas",
        capabilities: DATAFLOW_BUILDER_CAPABILITIES,
        builderSession: { phase: "applied", nodeRuns: { n1: "pending" } },
      },
      onSolve: jest.fn(),
    });
    const line = screen.getByRole("group", { name: "My Orchestrator" });
    expect(within(line).getByRole("button", { name: "Solve" })).toBeInTheDocument();
    // Under the Goal line's place and above the conversation.
    const header = chatHeader();
    // eslint-disable-next-line no-bitwise
    expect(header.compareDocumentPosition(line) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    // eslint-disable-next-line no-bitwise
    expect(line.compareDocumentPosition(document.querySelector(".messages")!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("an agent that does not declare it gets no plan line", () => {
    renderPanel({
      attachment: {
        ...attachment,
        coord: "agent.test.my-builder@2",
        name: "My Builder",
        capabilities: NODE_BUILDER_CAPABILITIES,
        builderSession: { phase: "applied", nodeRuns: { n1: "pending" } },
      },
      onSolve: jest.fn(),
    });
    expect(screen.queryByRole("group", { name: "My Builder" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Solve" })).toBeNull();
  });

  it("an orchestrating agent's empty conversation offers the six planning templates, which seed the message box", () => {
    const onSend = jest.fn().mockResolvedValue(undefined);
    renderPanel({
      attachment: {
        ...attachment,
        coord: "agent.test.my-orchestrator@1",
        name: "My Orchestrator",
        category: "canvas",
        capabilities: DATAFLOW_BUILDER_CAPABILITIES,
        builderSession: { phase: "idle" },
      },
      onSolve: jest.fn(),
      onSend,
    });
    // No plan yet: no plan line, and the templates in the conversation.
    expect(screen.queryByRole("group", { name: "My Orchestrator" })).toBeNull();
    const templates = screen.getByRole("group", { name: "Planning templates" });
    expect((document.querySelector(".messages") as HTMLElement).contains(templates)).toBe(true);
    expect(screen.getByText("Ask for a dataflow, or start from one of these:")).toBeInTheDocument();
    expect(within(templates).getAllByRole("button").map((b) => b.textContent)).toEqual(
      BUILDER_TEMPLATES.map((t) => t.label),
    );
    expect(BUILDER_TEMPLATES).toHaveLength(6);
    fireEvent.click(within(templates).getByRole("button", { name: "Load and Clean" }));
    expect(screen.getByPlaceholderText(/^Message /)).toHaveValue(BUILDER_TEMPLATES[0].seed);
    // Nothing is sent until Send.
    expect(onSend).not.toHaveBeenCalled();
  });

  it("the templates leave once the conversation has a message, and other agents never show them", () => {
    const orchestrator = {
      ...attachment,
      coord: "agent.test.my-orchestrator@1",
      name: "My Orchestrator",
      category: "canvas",
      capabilities: DATAFLOW_BUILDER_CAPABILITIES,
      builderSession: { phase: "idle" as const },
    };
    const first = renderPanel({ attachment: orchestrator, onSolve: jest.fn(), turns: [{ role: "user", text: "Map the parks" }] });
    expect(screen.queryByRole("group", { name: "Planning templates" })).toBeNull();
    first.unmount();
    renderPanel({ onSolve: jest.fn() });
    expect(screen.queryByRole("group", { name: "Planning templates" })).toBeNull();
    expect(screen.getByText("Ask this agent something to get started.")).toBeInTheDocument();
  });

  it("the templates are for a dataflow with no plan yet: a chat cleared after its plan landed offers none", () => {
    renderPanel({
      attachment: {
        ...attachment,
        coord: "agent.test.my-orchestrator@1",
        name: "My Orchestrator",
        category: "canvas",
        capabilities: DATAFLOW_BUILDER_CAPABILITIES,
        builderSession: { phase: "applied", appliedPlanId: "p1", nodeRuns: { n1: "pending", n2: "solved" } },
      },
      onSolve: jest.fn(),
      // Clear conversation emptied the transcript; the plan and its line stay.
      turns: [],
    });
    expect(screen.getByRole("group", { name: "My Orchestrator" })).toHaveTextContent("Planned · 2 nodes, 1 to solve");
    expect(screen.queryByRole("group", { name: "Planning templates" })).toBeNull();
    expect(screen.queryByText("Ask for a dataflow, or start from one of these:")).toBeNull();
    expect(screen.getByText("Ask this agent something to get started.")).toBeInTheDocument();
  });

  it("an agent that declares node.build says when its reply changed nothing", () => {
    renderPanel({
      attachment: {
        ...attachment,
        coord: "agent.test.my-builder@2",
        name: "My Builder",
        capabilities: NODE_BUILDER_CAPABILITIES,
      },
      turns: [
        { role: "user", text: "Add a node that loads the parks." },
        savedReply("I have now added a new node to your dataflow.", {
          toolCalls: [{ tool: "dataflow.read", status: "ok", durationMs: 3 }],
        }),
      ],
    });
    expect(screen.getByText("No changes were made to the canvas")).toBeInTheDocument();
  });

  it("a selection in an agent that declares node.build prefills the build request", () => {
    renderPanel({
      attachment: {
        ...attachment,
        coord: "agent.test.my-builder@2",
        name: "My Builder",
        capabilities: NODE_BUILDER_CAPABILITIES,
      },
      turns: [candidates],
    });
    fireEvent.click(screen.getByRole("checkbox", { name: "Select Chicago areas" }));
    expect(screen.getByPlaceholderText(/^Message /)).toHaveValue(
      "Build the data-loading node — fetch from: Chicago areas (https://data.example.org/areas.geojson).",
    );
  });

  it("an agent on a node that declares dataset.select records the confirmed source", async () => {
    const onRecordDatasetSelection = jest
      .fn()
      .mockResolvedValue({ attachmentId: "att-mine", nodeId: "n1", status: "resolved", picks: [] });
    renderPanel({
      attachment: {
        ...attachment,
        attachmentId: "att-mine",
        coord: "agent.test.my-finder@1",
        name: "My Finder",
        capabilities: DATASET_FINDER_CAPABILITIES,
        target: { kind: "node" as const, targetId: "n1" },
      },
      turns: [candidates],
      onRecordDatasetSelection,
    });
    const card = screen.getByRole("group", { name: "Dataset candidates" });
    fireEvent.click(within(card).getByRole("checkbox", { name: "Select Chicago areas" }));
    fireEvent.click(within(card).getByRole("button", { name: /Use this source/ }));
    await screen.findByText(/Source recorded for this node/);
    expect(onRecordDatasetSelection).toHaveBeenCalledWith([
      { lane: "external", key: "https://data.example.org/areas.geojson" },
    ]);
  });

  it("an agent on a node that only discovers datasets offers no confirm", () => {
    renderPanel({
      attachment: {
        ...attachment,
        coord: "agent.test.my-scout@1",
        name: "My Scout",
        capabilities: ["dataset.discover"],
        target: { kind: "node" as const, targetId: "n1" },
      },
      turns: [candidates],
      onRecordDatasetSelection: jest.fn(),
    });
    const card = screen.getByRole("group", { name: "Dataset candidates" });
    expect(within(card).queryByRole("button", { name: /Use this source/ })).toBeNull();
  });
});

// A label that opens another agent's chat, or hands it work, names that agent
// as its manifest does. The dataflow's agents here are a user's own copies of
// the shipped cards, "My Finder" and "My Builder", so a label that still names
// a shipped card shows the wrong agent.
describe("AgentChatPanel names the agent a label opens or hands work to", () => {
  const MY_AGENTS: Record<string, string> = {
    "att-my-finder": "My Finder",
    "att-my-builder": "My Builder",
  };
  const agentNameOf = (id: string) => MY_AGENTS[id] ?? null;
  const myBuilderOnTheNode: AgentAttachment = {
    ...attachment,
    attachmentId: "att-my-builder",
    coord: "agent.test.my-builder@2",
    name: "My Builder",
    capabilities: NODE_BUILDER_CAPABILITIES,
    target: { kind: "node" as const, targetId: "n1" },
    solvesNodes: true,
  };

  it("the per-node Solve row's awaiting-source notice and button name the node's own finder", async () => {
    const onOpenAgentChat = jest.fn();
    renderPanel({
      attachment: myBuilderOnTheNode,
      targetName: "Data Loading",
      onSolveNode: jest.fn().mockResolvedValue({
        verdict: "awaiting-source",
        rounds: 1,
        remedy: { kind: "dataset-selection", attachmentId: "att-my-finder", nodeId: "n1" },
      }),
      onOpenAgentChat,
      agentNameOf,
    });
    const row = screen.getByRole("group", { name: "Solve this node" });
    fireEvent.click(within(row).getByRole("button", { name: "Solve this node" }));
    const open = await within(row).findByRole("button", { name: "Open My Finder for this node" });
    expect(open).toHaveTextContent(/^Open My Finder$/);
    expect(open).toHaveAttribute(
      "data-tooltip",
      "Opens this node's My Finder chat, where its candidates wait for you: pick one with Use this source.",
    );
    expect(within(row).getByRole("status")).toHaveTextContent(
      "Awaiting a source: this node's My Finder has candidates for you to pick with Use this source. Nothing was generated or written.",
    );
    expect(row).not.toHaveTextContent(/Dataset Finder/);
    fireEvent.click(open);
    expect(onOpenAgentChat).toHaveBeenCalledWith("att-my-finder");
  });

  it("the attempts card opens the node's own builder under its name", () => {
    const onOpenAgentChat = jest.fn();
    renderPanel({
      turns: [
        {
          role: "agent" as const,
          text: "Solved 0 of 1 plan nodes.",
          content: [
            {
              type: "solveAttempts" as const,
              nodeId: "n1",
              label: "Load the parks",
              attachmentId: "att-my-builder",
              rounds: 1,
              stoppedBy: "budget",
              verdict: "fail",
              attempts: [
                {
                  round: 1,
                  verdict: "fail",
                  kind: "execution-error",
                  error: "KeyError: 'park_name'",
                  code: "return parks['park_name']",
                },
              ],
            },
          ],
        },
      ],
      onOpenAgentChat,
      agentNameOf,
    });
    const card = screen.getByRole("group", { name: /Attempts to fix Load the parks/ });
    const open = within(card).getByRole("button", { name: "Open the My Builder for Load the parks" });
    expect(open).toHaveTextContent(/^Open My Builder$/);
    expect(card).not.toHaveTextContent(/Node Builder/);
    fireEvent.click(open);
    expect(onOpenAgentChat).toHaveBeenCalledWith("att-my-builder");
  });

  it("a selection hands the source to the agent the finder hands nodes to build", () => {
    renderPanel({
      attachment: {
        ...attachment,
        attachmentId: "att-my-finder",
        coord: "agent.test.my-finder@1",
        name: "My Finder",
        capabilities: DATASET_FINDER_CAPABILITIES,
        nodeBuildDelegate: "My Builder",
      },
      turns: [
        {
          role: "agent" as const,
          text: "1 candidate",
          content: [
            {
              type: "datasetCandidates" as const,
              lanes: {
                external: [
                  { name: "Chicago areas", sourceType: "portal", url: "https://data.example.org/areas.geojson" },
                ],
                catalog: [],
              },
            },
          ],
        },
      ],
    });
    fireEvent.click(screen.getByRole("checkbox", { name: "Select Chicago areas" }));
    expect(screen.getByPlaceholderText(/^Message /)).toHaveValue(
      "Confirm my selection \u2014 hand off to My Builder: Chicago areas.",
    );
  });
});

// The Dataflow Builder's Build & validate reached a loader whose source is not
// settled: its Dataset Finder's candidates are in the Builder's chat too, the
// chat that asked for them, as a card whose pick records the source on the
// node's Finder.
describe("AgentChatPanel: a node's candidates in the chat that asked for them", () => {
  const BUILDER: AgentAttachment = {
    ...attachment,
    attachmentId: "dfb",
    coord: "agent.curio.dataflow-builder@1",
    name: "Dataflow Builder",
    category: "canvas",
    capabilities: DATAFLOW_BUILDER_CAPABILITIES,
    waitsForYou: ["n1"],
  };
  const AREAS = { name: "Chicago areas", sourceType: "portal" as const, url: "https://data.example.org/areas.geojson" };
  const LANES = { external: [AREAS], catalog: [] };
  const FINDER: AgentAttachment = {
    ...attachment,
    attachmentId: "att-df",
    coord: "agent.curio.dataset-finder@1",
    name: "Dataset Finder",
    category: "data",
    capabilities: DATASET_FINDER_CAPABILITIES,
    target: { kind: "node" as const, targetId: "n1" },
    waitsForYou: ["n1"],
    sourceRecord: { status: "candidates-pending", candidates: 1, askedBy: "dfb" },
    solvesNodes: false,
  };
  /** The Finder once the pick is recorded: it waits for nobody. */
  const RECORDED: AgentAttachment = {
    ...FINDER,
    waitsForYou: [],
    sourceRecord: { status: "resolved", askedBy: "dfb", picks: [{ ...AREAS, provider: "City of Chicago" }] },
  };
  const ASKED: AgentSessionTurn = {
    role: "agent" as const,
    text: "**Load boundaries** needs a source. Its Dataset Finder found 1 candidate: pick one with Use this source.",
    content: [{ type: "sourcePick" as const, finderAttachmentId: "att-df", nodeId: "n1", nodeLabel: "Load boundaries", lanes: LANES }],
  };
  const FOUND: AgentSessionTurn = {
    role: "agent" as const,
    text: "1 dataset candidate for this node.",
    content: [{ type: "datasetCandidates" as const, lanes: LANES }],
  };

  it("draws the card, named for its node, whose Use this source records the pick on the node's Dataset Finder", async () => {
    const onRecordSourcePick = jest
      .fn()
      .mockResolvedValue({ attachmentId: "att-df", nodeId: "n1", status: "resolved", picks: [] });
    renderPanel({ attachment: BUILDER, turns: [ASKED], attachments: [BUILDER, FINDER], onRecordSourcePick });
    const card = screen.getByRole("group", { name: "Sources for Load boundaries" });
    const use = within(card).getByRole("button", { name: "Use this source" });
    expect(use).toBeDisabled(); // nothing picked yet
    fireEvent.click(within(card).getByRole("checkbox", { name: "Select Chicago areas" }));
    await act(async () => {
      fireEvent.click(use);
    });
    // On the Finder's own route, by identifiers only.
    expect(onRecordSourcePick).toHaveBeenCalledWith("att-df", [
      { lane: "external", key: "https://data.example.org/areas.geojson" },
    ]);
  });

  it("opens the Finder's chat from the card", () => {
    const onOpenAgentChat = jest.fn();
    renderPanel({
      attachment: BUILDER,
      turns: [ASKED],
      attachments: [BUILDER, FINDER],
      onRecordSourcePick: jest.fn(),
      onOpenAgentChat,
      agentNameOf: (id: string) => (id === "att-df" ? "Dataset Finder" : null),
    });
    const card = screen.getByRole("group", { name: "Sources for Load boundaries" });
    fireEvent.click(within(card).getByRole("button", { name: "Its Dataset Finder's chat" }));
    expect(onOpenAgentChat).toHaveBeenCalledWith("att-df");
  });

  it("says Recorded, in both chats, once the Finder's record holds the pick", () => {
    const first = renderPanel({ attachment: BUILDER, turns: [ASKED], attachments: [BUILDER, RECORDED], onRecordSourcePick: jest.fn() });
    const card = screen.getByRole("group", { name: "Sources for Load boundaries" });
    expect(within(card).getByRole("status")).toHaveTextContent("Recorded: Chicago areas (City of Chicago).");
    expect(within(card).queryByRole("button", { name: "Use this source" })).toBeNull();
    first.unmount();
    // The Finder's own chat holds the same card, and says the same.
    renderPanel({ attachment: RECORDED, targetName: "Load boundaries", turns: [FOUND], onRecordDatasetSelection: jest.fn() });
    const own = screen.getByRole("group", { name: "Sources for Load boundaries" });
    expect(within(own).getByRole("status")).toHaveTextContent("Recorded: Chicago areas (City of Chicago).");
    expect(within(own).queryByRole("button", { name: "Use this source" })).toBeNull();
  });

  it("the Finder's own card reads Use this source and says the chat that asked holds it too", () => {
    renderPanel({
      attachment: FINDER,
      targetName: "Load boundaries",
      turns: [FOUND],
      onRecordDatasetSelection: jest.fn(),
      agentNameOf: (id: string) => (id === "dfb" ? "Dataflow Builder" : null),
    });
    const own = screen.getByRole("group", { name: "Sources for Load boundaries" });
    expect(within(own).getByRole("button", { name: "Use this source" })).toBeInTheDocument();
    expect(own).toHaveTextContent("The same card is in the Dataflow Builder's chat. A pick in either shows in both.");
  });

  it("a Dataset Finder's chat has no Solve this node: its agent solves no node", () => {
    renderPanel({ attachment: FINDER, targetName: "Load boundaries", turns: [FOUND], onSolveNode: jest.fn() });
    expect(screen.queryByRole("group", { name: "Solve this node" })).toBeNull();
  });
});

describe("AgentChatPanel: no Solve starts over a running build", () => {
  const LANDED: AgentAttachment = {
    ...attachment,
    attachmentId: "dfb",
    coord: "agent.curio.dataflow-builder@1",
    name: "Dataflow Builder",
    category: "canvas",
    capabilities: DATAFLOW_BUILDER_CAPABILITIES,
    planProposal: {
      proposalId: "pp1", tool: "dataflow.plan.write", nodeId: "", summary: "Plan \u00b7 1 node", status: "applied",
      appliedRefs: ["load"],
    },
    builderSession: { phase: "applied", planProposalId: "pp1", nodeStates: { load: "awaiting-source" }, nodeIds: { load: "n1" } },
  };
  const PLANNED: AgentSessionTurn = {
    role: "agent" as const,
    text: "I planned the loader.",
    content: [{
      type: "change" as const,
      changeId: "c-plan",
      tool: "dataflow.plan.write",
      kind: "plan",
      planId: "pp1",
      summary: "Plan \u00b7 1 node",
      status: "applied",
      lines: [],
      plan: {
        goal: "load the boundaries",
        nodes: [{ ref: "load", nodeType: "curio.builtin/data-loading", title: "Load boundaries", intent: "load them" }],
        edgeCount: 0,
        edges: [],
      },
    }],
  };

  it("the plan card's row Solve waits while this chat's build runs, saying why", () => {
    const { rerender, props } = renderPanel({ attachment: LANDED, turns: [PLANNED], onSolvePlanNode: jest.fn() });
    expect(screen.getByRole("button", { name: "Solve node Load boundaries" })).toBeEnabled();
    rerender(<AgentChatPanel {...props} simulating="auto" />);
    const solve = screen.getByRole("button", { name: "Solve node Load boundaries" });
    expect(solve).toBeDisabled();
    expect(solve).toHaveAttribute("data-tooltip", BUILD_RUNNING_HINT);
  });

  it("and while a build another tab runs, which the listing names", () => {
    const building: AgentAttachment = {
      ...LANDED,
      builderSession: { ...LANDED.builderSession!, simulateMode: "auto", simulatingSince: Date.now() / 1000 },
      buildRunning: "auto",
    };
    renderPanel({ attachment: building, turns: [PLANNED], onSolvePlanNode: jest.fn() });
    const solve = screen.getByRole("button", { name: "Solve node Load boundaries" });
    expect(solve).toBeDisabled();
    expect(solve).toHaveAttribute("data-tooltip", BUILD_RUNNING_HINT);
  });

  it("Solve this node waits while a build runs on its node's plan, saying why", () => {
    renderPanel({
      attachment: { ...attachment, coord: "agent.curio.node-builder@1", name: "Node Builder", target: { kind: "node" as const, targetId: "n1" }, solvesNodes: true },
      onSolveNode: jest.fn(),
      solveNodeBlocker: BUILD_RUNNING_HINT,
    });
    const solve = within(screen.getByRole("group", { name: "Solve this node" })).getByRole("button", { name: "Solve this node" });
    expect(solve).toBeDisabled();
    expect(solve).toHaveAttribute("data-tooltip", BUILD_RUNNING_HINT);
  });
});

// Solve this node in the chat that asked for the node's candidates: the card
// is in that chat, below, so the row points at it.
describe("AgentChatPanel: Solve this node points at the card in its own chat", () => {
  it("an awaiting-source outcome in a chat that holds the node's card says to pick on it, and shows it", async () => {
    const scrolled: Element[] = [];
    const scrollIntoView = Element.prototype.scrollIntoView;
    Element.prototype.scrollIntoView = function (this: Element) {
      scrolled.push(this);
    };
    try {
      renderPanel({
        attachment: { ...attachment, attachmentId: "nb1", coord: "agent.curio.node-builder@1", name: "Node Builder", target: { kind: "node" as const, targetId: "n1" }, solvesNodes: true, waitsForYou: ["n1"] },
        targetName: "Load boundaries",
        turns: [{
          role: "agent" as const,
          text: "**Load boundaries** needs a source. Its Dataset Finder found 1 candidate: pick one with Use this source.",
          content: [{
            type: "sourcePick" as const, finderAttachmentId: "att-df", nodeId: "n1", nodeLabel: "Load boundaries",
            lanes: { external: [{ name: "Chicago areas", sourceType: "portal" as const, url: "https://data.example.org/areas.geojson" }], catalog: [] },
          }],
        }],
        onRecordSourcePick: jest.fn(),
        onSolveNode: jest.fn().mockResolvedValue({
          verdict: "awaiting-source",
          rounds: 0,
          remedy: { kind: "dataset-selection", attachmentId: "att-df", nodeId: "n1" },
        }),
        onOpenAgentChat: jest.fn(),
        agentNameOf: (id: string) => (id === "att-df" ? "Dataset Finder" : null),
      });
      const row = screen.getByRole("group", { name: "Solve this node" });
      fireEvent.click(within(row).getByRole("button", { name: "Solve this node" }));
      const show = await within(row).findByRole("button", { name: "Show its sources" });
      expect(within(row).getByRole("status")).toHaveTextContent(
        "Awaiting a source: pick one on its card below with Use this source. Nothing was generated or written.",
      );
      expect(within(row).queryByRole("button", { name: /^Open Dataset Finder/ })).toBeNull();
      scrolled.length = 0;
      fireEvent.click(show);
      expect(scrolled).toEqual([screen.getByRole("group", { name: "Sources for Load boundaries" })]);
    } finally {
      Element.prototype.scrollIntoView = scrollIntoView;
    }
  });
});

// A card of a node's candidates follows its Finder's record, as the listing
// has it: it is live only while that record asks for its pick, it says
// Recorded only where the pick was made, and it is closed, saying why, once its
// candidates were replaced, its Finder or its node is gone, or no pick is
// needed.
describe("AgentChatPanel: a candidates card follows its Finder's record", () => {
  const BUILDER: AgentAttachment = {
    ...attachment,
    attachmentId: "dfb",
    coord: "agent.curio.dataflow-builder@1",
    name: "Dataflow Builder",
    category: "canvas",
    capabilities: DATAFLOW_BUILDER_CAPABILITIES,
    waitsForYou: ["n1"],
  };
  const AREAS = { name: "Chicago areas", sourceType: "portal" as const, url: "https://data.example.org/areas.geojson" };
  const BLOCKS = { name: "Chicago blocks", sourceType: "portal" as const, url: "https://data.example.org/blocks.geojson" };
  /** The Builder's turn that holds the card of one search of the loader's
   * Finder, *discoveryId*. */
  const asked = (discoveryId: string, row = AREAS): AgentSessionTurn => ({
    role: "agent" as const,
    text: "**Load boundaries** needs a source. Its Dataset Finder found 1 candidate: pick one with Use this source.",
    content: [{
      type: "sourcePick" as const, finderAttachmentId: "att-df", nodeId: "n1", nodeLabel: "Load boundaries",
      discoveryId, lanes: { external: [row], catalog: [] },
    }],
  });
  /** The Finder's own turn that holds the card of its search *discoveryId*. */
  const found = (discoveryId: string, row = AREAS): AgentSessionTurn => ({
    role: "agent" as const,
    text: "1 dataset candidate for this node.",
    content: [{ type: "datasetCandidates" as const, discoveryId, lanes: { external: [row], catalog: [] } }],
  });
  const finder = (sourceRecord: AgentAttachment["sourceRecord"], waitsForYou: string[] = []): AgentAttachment => ({
    ...attachment,
    attachmentId: "att-df",
    coord: "agent.curio.dataset-finder@1",
    name: "Dataset Finder",
    category: "data",
    capabilities: DATASET_FINDER_CAPABILITIES,
    target: { kind: "node" as const, targetId: "n1" },
    waitsForYou,
    sourceRecord,
    solvesNodes: false,
  });
  const PENDING_D2 = { status: "candidates-pending", candidates: 1, discoveryId: "d2", askedBy: "dfb", askers: ["dfb"] };
  const cards = () => screen.getAllByRole("group", { name: "Sources for Load boundaries" });

  it("a card of candidates a newer search replaced is closed, and shows the newest", () => {
    const scrolled: Element[] = [];
    const scrollIntoView = Element.prototype.scrollIntoView;
    Element.prototype.scrollIntoView = function (this: Element) {
      scrolled.push(this);
    };
    try {
      renderPanel({
        attachment: BUILDER,
        turns: [asked("d1"), asked("d2", BLOCKS)],
        attachments: [BUILDER, finder(PENDING_D2, ["n1"])],
        onRecordSourcePick: jest.fn(),
      });
      const [older, newer] = cards();
      expect(within(older).queryByRole("button", { name: "Use this source" })).toBeNull();
      expect(within(older).queryAllByRole("checkbox")).toHaveLength(0);
      expect(within(older).getByRole("status")).toHaveTextContent("Closed: newer candidates replaced these.");
      expect(within(newer).getByRole("button", { name: "Use this source" })).toBeInTheDocument();
      scrolled.length = 0;
      fireEvent.click(within(older).getByRole("button", { name: "Show the newest" }));
      expect(scrolled).toEqual([newer]);
    } finally {
      Element.prototype.scrollIntoView = scrollIntoView;
    }
  });

  it("a card whose Finder was taken off its node is closed and says so", () => {
    renderPanel({
      attachment: BUILDER,
      turns: [asked("d1")],
      attachments: [BUILDER],
      onRecordSourcePick: jest.fn(),
      nodeOnCanvas: () => true,
    });
    const [card] = cards();
    expect(within(card).queryByRole("button", { name: "Use this source" })).toBeNull();
    expect(within(card).getByRole("status")).toHaveTextContent("Closed: its Dataset Finder was taken off Load boundaries.");
  });

  it("a card whose node is gone is closed and says so", () => {
    renderPanel({
      attachment: BUILDER,
      turns: [asked("d1")],
      attachments: [BUILDER],
      onRecordSourcePick: jest.fn(),
      nodeOnCanvas: () => false,
    });
    const [card] = cards();
    expect(within(card).queryByRole("button", { name: "Use this source" })).toBeNull();
    expect(within(card).getByRole("status")).toHaveTextContent("Closed: Load boundaries is no longer on the canvas.");
  });

  it("says Recorded only on the card the pick was made on", () => {
    const picked = finder({
      status: "resolved",
      picks: [{ ...BLOCKS, provider: "City of Chicago" }],
      discoveryId: "d2",
      pickedFrom: "d2",
      askedBy: "dfb",
      askers: ["dfb"],
      next: "The Dataflow Builder goes on with its plan and builds the loader from this source.",
    });
    renderPanel({
      attachment: { ...BUILDER, waitsForYou: [] },
      turns: [asked("d1"), asked("d2", BLOCKS)],
      attachments: [{ ...BUILDER, waitsForYou: [] }, picked],
      onRecordSourcePick: jest.fn(),
    });
    const [older, newer] = cards();
    expect(within(older).getByRole("status")).not.toHaveTextContent("Recorded");
    expect(within(older).getByRole("status")).toHaveTextContent("Closed: newer candidates replaced these.");
    expect(within(newer).getByRole("status")).toHaveTextContent(
      "Recorded: Chicago blocks (City of Chicago). The Dataflow Builder goes on with its plan and builds the loader from this source.",
    );
  });

  it("is closed once no pick is needed: a skip, whose source is grounded already", () => {
    const skipped = finder({ status: "not-needed", skippedBecause: "/data/areas.csv", recordedAt: "2026-11-25T10:00:00+00:00" });
    renderPanel({
      attachment: { ...BUILDER, waitsForYou: [] },
      turns: [asked("d1")],
      attachments: [{ ...BUILDER, waitsForYou: [] }, skipped],
      onRecordSourcePick: jest.fn(),
    });
    const [card] = cards();
    expect(within(card).queryByRole("button", { name: "Use this source" })).toBeNull();
    expect(within(card).getByRole("status")).toHaveTextContent("no pick is needed");
  });

  it("records its pick with the card it was made on", async () => {
    const onRecordSourcePick = jest
      .fn()
      .mockResolvedValue({ attachmentId: "att-df", nodeId: "n1", status: "resolved", picks: [] });
    renderPanel({
      attachment: BUILDER,
      turns: [asked("d2")],
      attachments: [BUILDER, finder(PENDING_D2, ["n1"])],
      onRecordSourcePick,
    });
    const [card] = cards();
    fireEvent.click(within(card).getByRole("checkbox", { name: "Select Chicago areas" }));
    await act(async () => {
      fireEvent.click(within(card).getByRole("button", { name: "Use this source" }));
    });
    expect(onRecordSourcePick).toHaveBeenCalledWith("att-df", [{ lane: "external", key: AREAS.url }], "d2");
  });

  it("in the Finder's own chat, its newest card stays open after a pick on an older one", () => {
    const own = finder({ status: "resolved", picks: [{ ...AREAS }], discoveryId: "d2", pickedFrom: "d1" });
    renderPanel({
      attachment: own,
      targetName: "Load boundaries",
      turns: [found("d1"), found("d2", BLOCKS)],
      onRecordDatasetSelection: jest.fn(),
    });
    const [older, newer] = cards();
    expect(within(newer).getByRole("button", { name: "Use this source" })).toBeInTheDocument();
    expect(within(older).getByRole("status")).toHaveTextContent("Recorded: Chicago areas.");
  });

  it("the Finder's own card names every chat that holds the same card", () => {
    renderPanel({
      attachment: finder({ ...PENDING_D2, askers: ["dfb", "nb1"] }, ["n1"]),
      targetName: "Load boundaries",
      turns: [found("d2")],
      onRecordDatasetSelection: jest.fn(),
      agentNameOf: (id: string) => ({ dfb: "Dataflow Builder", nb1: "Node Builder" } as Record<string, string>)[id] ?? null,
    });
    const [own] = cards();
    expect(own).toHaveTextContent(
      "The same card is in the Dataflow Builder's and the Node Builder's chats. A pick in any shows in all.",
    );
  });
});

// A plan row's Solve that runs on the server, the one a pick goes on with
// among them, is work on its node: the listing names it (`validating`), its row
// shows it running, and no other row's Solve starts over it.
describe("AgentChatPanel: a row's Solve the server runs shows on the plan card", () => {
  const RUNNING: AgentAttachment = {
    ...attachment,
    attachmentId: "dfb",
    coord: "agent.curio.dataflow-builder@1",
    name: "Dataflow Builder",
    category: "canvas",
    capabilities: DATAFLOW_BUILDER_CAPABILITIES,
    planProposal: {
      proposalId: "pp1", tool: "dataflow.plan.write", nodeId: "", summary: "Plan · 2 nodes", status: "applied",
      appliedRefs: ["load", "stats"],
    },
    builderSession: {
      phase: "applied", planProposalId: "pp1",
      nodeStates: { load: "created", stats: "created" }, nodeIds: { load: "n1", stats: "n2" },
    },
    validating: { ref: "load", nodeId: "n1" },
  };
  const PLANNED: AgentSessionTurn = {
    role: "agent" as const,
    text: "I planned the loader and its statistics.",
    content: [{
      type: "change" as const,
      changeId: "c-plan",
      tool: "dataflow.plan.write",
      kind: "plan",
      planId: "pp1",
      summary: "Plan · 2 nodes",
      status: "applied",
      lines: [],
      plan: {
        goal: "load the boundaries",
        nodes: [
          { ref: "load", nodeType: "curio.builtin/data-loading", title: "Load boundaries", intent: "load them" },
          { ref: "stats", nodeType: "curio.builtin/python-computation", title: "Stats", intent: "count them" },
        ],
        edgeCount: 0,
        edges: [],
      },
    }],
  };

  it("its row reads Solving and waits, and the other rows' Solve waits for it, saying why", () => {
    renderPanel({ attachment: RUNNING, turns: [PLANNED], onSolvePlanNode: jest.fn() });
    const solving = screen.getByRole("button", { name: "Solve node Load boundaries" });
    expect(solving).toBeDisabled();
    expect(solving).toHaveTextContent("Solving…");
    const other = screen.getByRole("button", { name: "Solve node Stats" });
    expect(other).toBeDisabled();
    expect(other).toHaveAttribute("data-tooltip", "A node of this plan is being solved: wait for its Solve to end");
  });
});

// Solve this node that ends waiting for the node's source says what the source
// waits on: a pick, a download into the Data Catalog, or an install. Only a
// pick is asked for.
describe("AgentChatPanel: Solve this node says what the node's source waits on", () => {
  const NODE_BUILDER: AgentAttachment = {
    ...attachment,
    attachmentId: "nb1",
    coord: "agent.curio.node-builder@1",
    name: "Node Builder",
    target: { kind: "node" as const, targetId: "n1" },
    solvesNodes: true,
  };

  it.each([
    ["download", "Awaiting its source: it is downloading into the Data Catalog. Solve this node again once it lands."],
    [
      "install",
      "Awaiting its source: the dataset picked for it is not installed yet. Install it from the Data Catalog, then Solve this node again.",
    ],
  ])("a source waiting for its %s says so, and asks for no pick", async (wait, said) => {
    renderPanel({
      attachment: NODE_BUILDER,
      targetName: "Load boundaries",
      onSolveNode: jest.fn().mockResolvedValue({
        verdict: "awaiting-source",
        rounds: 0,
        sourceWait: wait,
        remedy: { kind: "dataset-selection", attachmentId: "att-df", nodeId: "n1" },
      }),
      onOpenAgentChat: jest.fn(),
      agentNameOf: (id: string) => (id === "att-df" ? "Dataset Finder" : null),
    });
    const row = screen.getByRole("group", { name: "Solve this node" });
    fireEvent.click(within(row).getByRole("button", { name: "Solve this node" }));
    await waitFor(() => expect(within(row).getByRole("status")).toHaveTextContent(said));
    expect(within(row).getByRole("status")).not.toHaveTextContent(/pick one|Use this source|confirm/);
    expect(within(row).queryByRole("button", { name: /^Open Dataset Finder/ })).toBeNull();
    expect(within(row).queryByRole("button", { name: "Show its sources" })).toBeNull();
  });
});
