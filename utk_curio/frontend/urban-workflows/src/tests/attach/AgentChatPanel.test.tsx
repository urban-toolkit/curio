import React from "react";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";

// The dev/52 builder strip imports useFlowContext; mocking the provider keeps
// FlowProvider's heavy module graph (vega etc.) out of this presentational
// suite — the strip itself is covered by AgentBuilderStrip.test.tsx.
jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({ playAllNodes: jest.fn() }),
}));

// dev/84: the package-install review flow loads the catalog + conflict probe;
// mocked so the panel suite stays network-free.
jest.mock("../../api/packagesApi", () => ({
  packagesApi: { catalog: jest.fn(), listInstalled: jest.fn(), resolve: jest.fn() },
}));
import { packagesApi } from "../../api/packagesApi";

import { AgentChatPanel } from "../../components/agents/attach/AgentChatPanel";
import type { AgentAttachment, AgentSessionTurn } from "../../api/agentsApi";

const attachment: AgentAttachment = {
  attachmentId: "a1",
  coord: "agent.node-explainer@1.0.0",
  target: { kind: "canvas" as const },
  sessionId: "s1234567890",
  revision: 1,
  name: "Node Explainer",
  category: "node",
  hooks: ["node"],
  intent: "Explain the selected node's code and outputs.",
  intentEdited: false,
  title: null,
  titleEdited: false,
};

const noTurns: AgentSessionTurn[] = [];

function renderPanel(overrides: Partial<React.ComponentProps<typeof AgentChatPanel>> = {}) {
  const props: React.ComponentProps<typeof AgentChatPanel> = {
    attachment,
    turns: noTurns,
    onSend: jest.fn().mockResolvedValue(undefined),
    onClose: jest.fn(),
    ...overrides,
  };
  return { ...render(<AgentChatPanel {...props} />), props };
}

describe("AgentChatPanel", () => {
  it("renders the concept header: name, target, session chip", () => {
    renderPanel();
    expect(screen.getByText("Node Explainer")).toBeInTheDocument();
    expect(screen.getByText(/attached to canvas/i)).toBeInTheDocument();
    expect(screen.getByText(/session s1234567/)).toBeInTheDocument();
  });

  it("sends the trimmed message through onSend", async () => {
    const onSend = jest.fn().mockResolvedValue(undefined);
    renderPanel({ onSend });
    fireEvent.change(screen.getByPlaceholderText(/message this agent/i), {
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
    const composer = screen.getByPlaceholderText(/message this agent/i);
    // jsdom's paste-equivalent: the value lands with its \n intact.
    fireEvent.change(composer, { target: { value: "line1\n\nline3\n" } });
    fireEvent.keyDown(composer, { key: "Enter" });
    expect(onSend).toHaveBeenCalledWith("line1\n\nline3");
    await waitFor(() => expect(composer).toHaveValue(""));
  });

  it("Shift+Enter does not send", () => {
    const onSend = jest.fn().mockResolvedValue(undefined);
    renderPanel({ onSend });
    const composer = screen.getByPlaceholderText(/message this agent/i);
    fireEvent.change(composer, { target: { value: "draft" } });
    fireEvent.keyDown(composer, { key: "Enter", shiftKey: true });
    expect(onSend).not.toHaveBeenCalled();
    expect(composer).toHaveValue("draft");
  });

  it("Enter during an IME composition does not send", () => {
    const onSend = jest.fn().mockResolvedValue(undefined);
    renderPanel({ onSend });
    const composer = screen.getByPlaceholderText(/message this agent/i);
    fireEvent.change(composer, { target: { value: "変換中" } });
    fireEvent.keyDown(composer, { key: "Enter", isComposing: true });
    expect(onSend).not.toHaveBeenCalled();
  });

  it("whitespace/newline-only input never sends", () => {
    const onSend = jest.fn().mockResolvedValue(undefined);
    renderPanel({ onSend });
    const composer = screen.getByPlaceholderText(/message this agent/i);
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

  it("clear conversation confirms first", async () => {
    const onClearConversation = jest.fn().mockResolvedValue(undefined);
    const confirmSpy = jest.spyOn(window, "confirm").mockReturnValue(true);
    renderPanel({ onClearConversation });
    fireEvent.click(screen.getByRole("button", { name: "Clear conversation" }));
    expect(confirmSpy).toHaveBeenCalled();
    await waitFor(() => expect(onClearConversation).toHaveBeenCalledTimes(1));
    confirmSpy.mockRestore();
  });

  it("header cycling (DEC-042): shows idx/total and walks prev/next", () => {
    const onPrev = jest.fn();
    const onNext = jest.fn();
    renderPanel({ index: 2, total: 4, onPrev, onNext });
    expect(screen.getByText("2 / 4")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Previous agent" }));
    fireEvent.click(screen.getByRole("button", { name: "Next agent" }));
    expect(onPrev).toHaveBeenCalledTimes(1);
    expect(onNext).toHaveBeenCalledTimes(1);
  });

  it("cycling arrows are disabled at the ends (no wrap)", () => {
    renderPanel({ index: 1, total: 3, onNext: jest.fn() });
    expect(screen.getByRole("button", { name: "Previous agent" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Next agent" })).toBeEnabled();
  });
});

describe("AgentChatPanel conversation title (memo dev/25)", () => {
  const titled = { ...attachment, title: "Dataset Import Help" };

  it("shows the composed '<name>: <title>' in the header and dialog label", () => {
    renderPanel({ attachment: titled, onSaveTitle: jest.fn() });
    expect(
      screen.getByRole("button", { name: "Rename conversation title" }),
    ).toHaveTextContent("Node Explainer: Dataset Import Help");
    expect(
      screen.getByRole("dialog", { name: "Chat with Node Explainer: Dataset Import Help" }),
    ).toBeInTheDocument();
  });

  it("shows the plain name when untitled, and a plain non-button label without onSaveTitle", () => {
    const first = renderPanel({ onSaveTitle: jest.fn() });
    expect(
      screen.getByRole("button", { name: "Rename conversation title" }),
    ).toHaveTextContent(/^Node Explainer$/);
    first.unmount();
    renderPanel({ attachment: titled });
    expect(
      screen.queryByRole("button", { name: "Rename conversation title" }),
    ).not.toBeInTheDocument();
    expect(screen.getByText("Node Explainer: Dataset Import Help")).toBeInTheDocument();
  });

  it("a single click swaps only the custom portion for an input, prefix fixed", () => {
    renderPanel({ attachment: titled, onSaveTitle: jest.fn() });
    fireEvent.click(screen.getByRole("button", { name: "Rename conversation title" }));
    const input = screen.getByRole("textbox", { name: "Conversation title" });
    expect(input).toHaveValue("Dataset Import Help");
    expect(input).toHaveAttribute("maxlength", "40");
    // The template-name prefix stays as static text, not inside the input.
    expect(screen.getByText("Node Explainer:")).toBeInTheDocument();
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
    ).toHaveTextContent("Node Explainer: Renamed Chat");
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
    ).toHaveTextContent("Node Explainer: Dataset Import Help");
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
    ).toHaveTextContent("Node Explainer: Dataset Import Help");
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
    fireEvent.change(screen.getByPlaceholderText(/message this agent/i), {
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

describe("AgentChatPanel review + tool activity (memo dev/41)", () => {
  it("renders a proposal part as the review card and wires apply", () => {
    const onApplyProposal = jest.fn().mockResolvedValue(undefined);
    renderPanel({
      turns: [
        {
          role: "agent",
          text: "Here is my proposal.",
          content: [
            {
              type: "proposal",
              proposalId: "p1",
              tool: "node.content.write",
              summary: "Replace the content of node 'n1'",
              preview: "print(2)",
              pins: { nodeId: "n1", contentSha256: "abc" },
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
    fireEvent.click(screen.getByRole("button", { name: "Add to dataflow" }));
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
    expect(screen.queryByRole("button", { name: "Add to dataflow" })).toBeNull();
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
    coord: "agent.node-researcher@1.0.0",
    name: "Node Researcher",
    category: "evaluate",
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
    fireEvent.click(screen.getByRole("button", { name: "Open Node Researcher's chat" }));
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
      screen.queryByRole("button", { name: /open node researcher/i }),
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
    fireEvent.change(screen.getByPlaceholderText(/message this agent/i), {
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
    expect(screen.getByLabelText(/session token usage/i)).toHaveTextContent("1.6k tokens");
  });

  it("while running the send button keeps its loading glyph and is disabled", () => {
    renderPanel({ runStatus: runningStatus() });
    fireEvent.change(screen.getByPlaceholderText(/message this agent/i), {
      target: { value: "queued question" },
    });
    const send = screen.getByRole("button", { name: "Send" });
    expect(send).toBeDisabled();
    expect(send).toHaveTextContent("…");
  });

  it("a wired-idle status re-enables send even while another chat's send is in flight (cycling leak fix)", async () => {
    // A never-resolving onSend leaves the panel-local `sending` flag true —
    // exactly the state carried across an attachment cycle. The provider's
    // per-attachment status (null = idle) must win.
    const onSend = jest.fn().mockReturnValue(new Promise(() => undefined));
    const { rerender, props } = renderPanel({ onSend, runStatus: runningStatus() });
    fireEvent.change(screen.getByPlaceholderText(/message this agent/i), {
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
    fireEvent.change(screen.getByPlaceholderText(/message this agent/i), {
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

  it("a pending review proposal marks only the newest reply", () => {
    renderPanel({
      attachment: {
        ...attachment,
        activeProposal: {
          proposalId: "p1",
          tool: "node.content.write",
          nodeId: "n1",
          summary: "write",
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
    expect(screen.getByLabelText(/session token usage/i)).toHaveTextContent("2.0k tokens");
  });

  it("a pristine chat renders no status and no counter", () => {
    renderPanel();
    expect(screen.queryByRole("status")).toBeNull();
    expect(screen.queryByLabelText(/session token usage/i)).toBeNull();
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
