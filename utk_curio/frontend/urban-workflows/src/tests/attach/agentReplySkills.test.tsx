import React from "react";
import { act, render, renderHook, screen } from "@testing-library/react";

/**
 * Each chat reply lists the skills its run used, in a quiet line under it:
 * the skills its run was handed for its node, those its message named with
 * `/<name>`, those earlier turns took in, then those it loaded with
 * skill.read, each once, from the run's record. Each name says on hover how
 * the run came to hold it. A reply that just streamed in lists them as the
 * saved one will, so the line needs no reload.
 */

const mockRunAttachmentStream = jest.fn();
jest.mock("../../services/agents/agentsApi", () => ({
  agentsApi: {
    runAttachmentStream: (...args: unknown[]) => mockRunAttachmentStream(...args),
    getSession: jest.fn(),
  },
}));

// The turn's cards reach the flow provider's module graph (vega and the
// rest); the chat panel's own suite keeps it out the same way.
jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({ playAllNodes: jest.fn(), projectDirty: false }),
}));
jest.mock("../../services/packages/packagesApi", () => ({
  packagesApi: { catalog: jest.fn(), listInstalled: jest.fn(), resolve: jest.fn() },
}));

import { MemoryRouter } from "react-router-dom";

import { AgentTurn } from "../../components/agents/attach/chat/AgentTurn";
import { useAgentSession } from "../../providers/agents/useAgentSession";
import type { AgentAttachment, AgentAttachmentsState, AgentSessionTurn } from "../../services/agents";
import { getByTooltip } from "../_support/tooltips";

const attachment: AgentAttachment = {
  attachmentId: "a1",
  coord: "agent.curio.node-builder@1",
  target: { kind: "node", targetId: "n1" },
  sessionId: "s1",
  revision: 1,
  name: "Node Builder",
  category: "node",
  hooks: ["node"],
  intent: null,
  intentEdited: false,
  title: "Chart",
  titleEdited: false,
};

const actions = { onComposePrompt: jest.fn(), beginPackageReview: jest.fn() };

function renderTurn(turn: AgentSessionTurn) {
  return render(
    <MemoryRouter>
      <AgentTurn turn={turn} attachment={attachment} tint="" meta={null} actions={actions} />
    </MemoryRouter>,
  );
}

const line = () => document.querySelector('[data-curio-reply-skills="true"]');

describe("the line under a reply", () => {
  it("names the skills the run held and loaded, each once, in the record's order", () => {
    renderTurn({
      role: "agent",
      text: "Done.",
      execution: {
        executionId: "e1",
        usage: null,
        status: "ok",
        pins: {
          skills: {
            catalog: ["widgets", "map-edits", "provenance", "scenarios"],
            handed: ["widgets"],
            named: ["map-edits"],
            kept: ["scenarios"],
          },
        },
        skillsLoaded: ["provenance", "widgets"],
      },
    });
    expect(line()).toHaveTextContent("Skills: widgets, map-edits, scenarios, provenance");
    // How each came to be held, on hover of its name.
    expect(getByTooltip(document.body, "Handed for this chat's node or instruction")).toHaveTextContent("widgets");
    expect(getByTooltip(document.body, "Named with / in the message")).toHaveTextContent("map-edits");
    expect(getByTooltip(document.body, "Kept from earlier in this chat")).toHaveTextContent("scenarios");
    expect(getByTooltip(document.body, "Loaded for this reply")).toHaveTextContent("provenance");
  });

  it("is absent when the run used none, listed only a catalog, or failed", () => {
    const { unmount } = renderTurn({
      role: "agent",
      text: "Hello.",
      execution: { executionId: "e1", usage: null, status: "ok", pins: { skills: { catalog: ["widgets"] } } },
    });
    expect(line()).toBeNull();
    unmount();
    const second = renderTurn({ role: "agent", text: "Hello." });
    expect(line()).toBeNull();
    second.unmount();
    const failed = renderTurn({
      role: "agent",
      text: "(error) the run failed",
      error: true,
      execution: { executionId: "e1", usage: null, status: "error", pins: { skills: { handed: ["widgets"] } } },
    });
    expect(line()).toBeNull();
    failed.unmount();
    // The same record on a reply that did not fail names the skill.
    renderTurn({
      role: "agent",
      text: "Hello.",
      execution: { executionId: "e1", usage: null, status: "ok", pins: { skills: { handed: ["widgets"] } } },
    });
    expect(line()).toHaveTextContent("Skills: widgets");
  });
});

describe("a reply that just streamed in", () => {
  it("keeps the skills its run held and loaded, as the saved turn does", async () => {
    mockRunAttachmentStream.mockImplementation(
      async (_pid: string, _aid: string, _message: string, onDelta: (text: string) => void) => {
        onDelta("Done.");
        return {
          reply: "Done.",
          executionId: "e2",
          usage: { inputTokens: 1, outputTokens: 1 },
          durationMs: 5,
          skills: { handed: ["widgets"], named: ["map-edits"] },
          skillsLoaded: ["provenance"],
        };
      },
    );
    const state = {
      attachments: [attachment],
      busy: false,
      error: null,
      reload: jest.fn(() => Promise.resolve()),
      attach: jest.fn(),
      detach: jest.fn(),
      run: jest.fn(),
    } as unknown as AgentAttachmentsState;
    const { result } = renderHook(() => useAgentSession("p1", state));
    await act(async () => {
      await result.current.sendMessage("a1", "/map-edits remove the towers");
    });
    const turns = result.current.transcripts.a1;
    expect(turns.map((turn) => turn.role)).toEqual(["user", "agent"]);
    expect(turns[0].text).toBe("/map-edits remove the towers");
    const reply = turns[1];
    expect(reply.execution?.pins?.skills).toEqual({ handed: ["widgets"], named: ["map-edits"] });
    expect(reply.execution?.skillsLoaded).toEqual(["provenance"]);
    renderTurn(reply);
    expect(screen.getByText("Done.")).toBeInTheDocument();
    expect(line()).toHaveTextContent("Skills: widgets, map-edits, provenance");
  });
});
