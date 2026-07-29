import React from "react";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
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

describe("AgentChatPanel attachment settings cog (memo dev/42)", () => {
  it("renders the labeled cog beneath the header and opens settings", () => {
    const onOpenSettings = jest.fn();
    renderPanel({ onOpenSettings });
    const cog = screen.getByRole("button", { name: /attachment settings/i });
    // DEC-042: the cog lives in the content area, never the dark header.
    expect(cog.className).toMatch(/attachmentSettingsBtn/);
    fireEvent.click(cog);
    expect(onOpenSettings).toHaveBeenCalledTimes(1);
  });

  it("no cog when the callback is absent", () => {
    renderPanel();
    expect(screen.queryByRole("button", { name: /attachment settings/i })).toBeNull();
  });
});
