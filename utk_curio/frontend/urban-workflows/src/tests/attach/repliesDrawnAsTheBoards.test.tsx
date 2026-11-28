import React from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

/**
 * A reply as the boards draw it (fix round 3 of #1654):
 * - a Dataset Finder's candidates are left out of its reply only when a card
 *   shows them; with no card, the reply stays whole (board F4);
 * - a tool call a model wrote into its reply's text is never drawn (board F4);
 * - with Show run details on, a reply's skills, time, tokens and tools are one
 *   line (board S02-details).
 */

jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({ playAllNodes: jest.fn(), projectDirty: false }),
}));
jest.mock("../../services/packages/packagesApi", () => ({
  packagesApi: { catalog: jest.fn(), listInstalled: jest.fn(), resolve: jest.fn() },
}));

import { AgentChatPanel } from "../../components/agents/attach/AgentChatPanel";
import type { AgentAttachment, AgentSessionTurn } from "../../services/agents";

const agent = (over: Record<string, unknown> = {}) =>
  ({
    attachmentId: "a1",
    coord: "agent.curio.node-builder@1",
    target: { kind: "canvas" },
    sessionId: "s1",
    revision: 1,
    name: "Node Builder",
    category: "node",
    hooks: [],
    intent: null,
    intentEdited: false,
    title: null,
    titleEdited: false,
    ...over,
  }) as unknown as AgentAttachment;

const FINDER = agent({
  attachmentId: "att-df",
  coord: "agent.curio.dataset-finder@1",
  target: { kind: "node", targetId: "n1" },
  name: "Dataset Finder",
  category: "data",
  capabilities: ["dataset.discover", "dataset.select"],
});

function renderChat(attachment: AgentAttachment, turns: AgentSessionTurn[]) {
  return render(
    <AgentChatPanel
      attachment={attachment}
      turns={turns}
      onSend={jest.fn().mockResolvedValue(undefined)}
      onClose={jest.fn()}
      targetName="Load boundaries"
    />,
    { wrapper: MemoryRouter },
  );
}

const reply = (text: string, extra: Record<string, unknown> = {}) =>
  ({ role: "agent", text, ...extra }) as unknown as AgentSessionTurn;
const agentRows = () => document.querySelectorAll(".agentRow");

const PROSE = "The Data Catalog holds no boundaries; the rows below are what the portals hold.";
const BLOCK = JSON.stringify(
  {
    datasetCandidates: {
      lanes: { external: [{ name: "Chicago context", sourceType: "portal", url: "https://data.example.org/c" }], catalog: [] },
    },
  },
  null,
  2,
);

describe("a Finder's candidates are left out only where a card shows them", () => {
  it("draws a reply that was only its candidates when no card shows them", () => {
    renderChat(FINDER, [reply(BLOCK)]);
    expect(agentRows()).toHaveLength(1);
    expect(document.body.textContent).toContain("Chicago context");
  });

  it("draws the candidates a reply printed in a fence when no card shows them", () => {
    renderChat(FINDER, [reply(`${PROSE}\n\n\`\`\`curio.v1\n${BLOCK}\n\`\`\``)]);
    expect(screen.getByText(PROSE)).toBeInTheDocument();
    expect(document.body.textContent).toContain("datasetCandidates");
  });
});

describe("a tool call written into a reply's text is never drawn", () => {
  const CALLS = [
    ["a request block", '{"toolRequest": {"tool": "dataflow.read", "params": {}}}'],
    ["a delegation block", '{"delegateRequest": {"capability": "dataset.discover", "inputs": {}}}'],
    ["a bare call", '{"tool": "dataflow.read", "params": {"nodeId": "n1"}}'],
  ];

  it.each(CALLS)("draws the words around %s, and not the call", (_what, call) => {
    renderChat(agent(), [reply(`I read the dataflow first.\n\n\`\`\`json\n${call}\n\`\`\``)]);
    expect(screen.getByText("I read the dataflow first.")).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/"(?:tool|toolRequest|delegateRequest)"/);
  });

  it("draws no turn for a reply that was only a call", () => {
    renderChat(agent(), [reply('```json\n{"toolRequest": {"tool": "dataflow.read", "params": {}}}\n```')]);
    expect(agentRows()).toHaveLength(0);
  });

  it("draws no call the reply's cut left open", () => {
    renderChat(agent(), [reply('Reading it.\n\n```json\n{"toolRequest": {"tool": "dataflow.re')]);
    expect(screen.getByText("Reading it.")).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/toolRequest|dataflow\.re/);
  });

  it("draws any other JSON as it is", () => {
    renderChat(agent(), [reply('The columns:\n\n```json\n{"columns": ["area", "geometry"]}\n```')]);
    expect(document.body.textContent).toContain('"columns"');
  });
});

describe("Show run details draws a reply's run as one line", () => {
  const ran = reply("I planned 3 nodes.", {
    execution: {
      executionId: "e-ran",
      usage: { inputTokens: 36104, outputTokens: 2211 },
      status: "ok",
      durationMs: 14000,
      pins: { skills: { handed: ["reuse-first"] } },
      toolCalls: [
        { tool: "dataflow.read", status: "ok" },
        { tool: "catalog.search", status: "ok" },
        { tool: "dataflow.read", status: "ok" },
        { tool: "dataflow.plan.write", status: "applied" },
      ],
      skillsLoaded: ["data-sources"],
    },
  });

  it("says its skills, its time and tokens, and its tools on one line, as board S02-details does", () => {
    renderChat(agent(), [reply("Map the libraries.", { role: "user" }), ran]);
    fireEvent.click(screen.getByRole("button", { name: /^More/ }));
    fireEvent.click(
      within(screen.getByRole("menu", { name: "Chat menu" })).getByRole("menuitemcheckbox", { name: /^Show run details/ }),
    );
    expect(document.querySelector('[data-curio-run-details="true"]')).toHaveTextContent(
      /^skills reuse-first, data-sources · 14s · 38\.3k tokens \(36,104 in, 2,211 out\) · tools dataflow\.read, catalog\.search, dataflow\.plan\.write$/,
    );
  });
});
