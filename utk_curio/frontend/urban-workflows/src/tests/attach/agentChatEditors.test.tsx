/**
 * The owner and the editors the owner invited share an agent's chat
 * (`agentEditors.ts`). A message someone else wrote names its writer above
 * it, and the viewer's own messages name nobody. On an editor's chat an
 * install a proposal makes waits for the dataflow owner's review, which its
 * card says in place of Apply and Dismiss; any other proposal keeps them. An
 * agent's change landed with no review, and its Undo is the editor's too.
 */
import React from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({ playAllNodes: jest.fn(), projectDirty: false }),
}));
jest.mock("../../services/packages/packagesApi", () => ({
  packagesApi: { catalog: jest.fn(), listInstalled: jest.fn(), resolve: jest.fn() },
}));

import { AgentChatPanel } from "../../components/agents/attach/AgentChatPanel";
import { WAITS_FOR_OWNER } from "../../components/agents/content/reviewCard/reviewCardText";
import { agentsOnCanvas } from "../../services/agents";
import type { AgentAttachment, AgentSessionTurn } from "../../services/agents";

const attachment: AgentAttachment = {
  attachmentId: "a1",
  coord: "agent.curio.node-builder@1",
  target: { kind: "canvas" as const },
  sessionId: "s1234567890",
  revision: 1,
  name: "Node Builder",
  category: "node",
  hooks: ["node"],
  intent: "Build the nodes the dataflow needs.",
  intentEdited: false,
  title: null,
  titleEdited: false,
};

const ALICE = { kind: "person" as const, account: "3", name: "Alice" };
const BOB = { kind: "person" as const, account: "7", name: "Bob" };

function renderPanel(overrides: Partial<React.ComponentProps<typeof AgentChatPanel>> = {}) {
  const props: React.ComponentProps<typeof AgentChatPanel> = {
    attachment,
    turns: [],
    onSend: jest.fn().mockResolvedValue(undefined),
    onClose: jest.fn(),
    ...overrides,
  };
  return render(<AgentChatPanel {...props} />, { wrapper: MemoryRouter });
}

/** The writer a message's bubble is named after, or null when it names none. */
function writerOf(text: string): string | null {
  const bubble = screen.getByText(text);
  return bubble.parentElement?.getAttribute("data-curio-writer") ?? null;
}

describe("a chat the owner and the editors share", () => {
  const turns: AgentSessionTurn[] = [
    { role: "user", text: "Count the trees on each block.", by: BOB },
    { role: "agent", text: "Here is the count." },
    { role: "user", text: "Now the parks.", by: ALICE },
    // The local copy of a message this tab just sent names nobody.
    { role: "user", text: "And the rivers." },
  ];

  it("names the writer of a message someone else wrote, and not the viewer's own", () => {
    renderPanel({ turns, viewerAccount: ALICE.account });
    expect(writerOf("Count the trees on each block.")).toBe("Bob");
    expect(screen.getByText("Bob")).toBeInTheDocument();
    expect(writerOf("Now the parks.")).toBeNull();
    expect(screen.queryByText("Alice")).toBeNull();
    expect(writerOf("And the rivers.")).toBeNull();
  });

  it("names the owner's messages on an editor's chat", () => {
    renderPanel({ turns, viewerAccount: BOB.account });
    expect(writerOf("Now the parks.")).toBe("Alice");
    expect(writerOf("Count the trees on each block.")).toBeNull();
    expect(screen.queryByText("Bob")).toBeNull();
  });
});

function proposalTurn(tool: string, summary: string): AgentSessionTurn {
  return {
    role: "agent",
    text: "Review it below.",
    content: [
      {
        type: "proposal",
        proposalId: `p-${tool}`,
        tool,
        summary,
        preview: summary,
        pins: { dirName: "street-trees" },
        status: "pending",
      },
    ],
  } as unknown as AgentSessionTurn;
}

function card(summary: string) {
  return within(screen.getByRole("group", { name: `Review proposal: ${summary}` }));
}

describe("an install an editor's chat holds", () => {
  const INSTALLS = [
    ["package.install", "Install the Street Trees package"],
    ["package.draft.apply", "Install the drafted package"],
    ["dataset.install", "Add the street trees dataset"],
    ["discovery.acquire", "Download dataset · Street trees"],
  ];

  it.each(INSTALLS)("%s waits for the owner's review, with no Apply or Dismiss", (tool, summary) => {
    renderPanel({
      turns: [proposalTurn(tool, summary)],
      installsWaitForOwner: true,
      onApplyProposal: jest.fn().mockResolvedValue(undefined),
      onDismissProposal: jest.fn().mockResolvedValue(undefined),
    });
    expect(card(summary).getByText(WAITS_FOR_OWNER)).toBeInTheDocument();
    expect(card(summary).queryByRole("button", { name: "Apply" })).toBeNull();
    expect(card(summary).queryByRole("button", { name: "Dismiss" })).toBeNull();
  });

  it.each(INSTALLS)("%s keeps Apply and Dismiss on the owner's chat", (tool, summary) => {
    renderPanel({
      turns: [proposalTurn(tool, summary)],
      onApplyProposal: jest.fn().mockResolvedValue(undefined),
      onDismissProposal: jest.fn().mockResolvedValue(undefined),
    });
    expect(card(summary).getByRole("button", { name: "Apply" })).toBeInTheDocument();
    expect(card(summary).getByRole("button", { name: "Dismiss" })).toBeInTheDocument();
    expect(card(summary).queryByText(WAITS_FOR_OWNER)).toBeNull();
  });

  it("a proposal that installs nothing into the account keeps Apply and Dismiss on an editor's chat", () => {
    // An agent added to this dataflow alone, the one review left that is not
    // the owner's account's: a node, its code or a plan lands with no review.
    const summary = "Install Node Builder in this project";
    renderPanel({
      turns: [proposalTurn("project.install", summary)],
      installsWaitForOwner: true,
      onApplyProposal: jest.fn().mockResolvedValue(undefined),
      onDismissProposal: jest.fn().mockResolvedValue(undefined),
    });
    expect(card(summary).getByRole("button", { name: "Apply" })).toBeInTheDocument();
    expect(card(summary).getByRole("button", { name: "Dismiss" })).toBeInTheDocument();
    expect(card(summary).queryByText(WAITS_FOR_OWNER)).toBeNull();
  });

  it("an agent's change on an editor's chat landed already: its card offers Undo and waits for no one", () => {
    const summary = "Replaced the content of the Python node · n1";
    const onUndoChange = jest.fn().mockResolvedValue(undefined);
    renderPanel({
      turns: [{
        role: "agent",
        text: "I wrote the node's code.",
        content: [{
          type: "change", changeId: "c1", tool: "node.content.write", kind: "content", summary,
          preview: "print(2)", status: "applied", lines: ["n1"], nodeId: "n1",
        }],
      } as unknown as AgentSessionTurn],
      installsWaitForOwner: true,
      onUndoChange,
    });
    const changed = within(screen.getByRole("group", { name: `Change: ${summary}` }));
    expect(changed.queryByText(WAITS_FOR_OWNER)).toBeNull();
    expect(changed.queryByRole("button", { name: "Apply" })).toBeNull();
    fireEvent.click(changed.getByRole("button", { name: "Undo" }));
    expect(onUndoChange).toHaveBeenCalledWith("c1");
  });
});

describe("who works with the dataflow's agents on a canvas", () => {
  it("the owner and an invited editor drive them, and a watcher has none", () => {
    expect(agentsOnCanvas("owner")).toEqual({ drives: true, installsWaitForOwner: false });
    expect(agentsOnCanvas("editor")).toEqual({ drives: true, installsWaitForOwner: true });
    expect(agentsOnCanvas("watcher")).toEqual({ drives: false, installsWaitForOwner: false });
  });
});
