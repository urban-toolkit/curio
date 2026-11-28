/**
 * The Dataflow Builder's plan line names a planned node as its header on the
 * canvas does: its title, else its template's label. Only a node that is not
 * on the canvas is named by the first 8 characters of its id. The line names
 * the node a failure, a pause or a wait is about, and the node at work while
 * a batch runs, all the same way.
 */
import React from "react";
import { render, screen, within } from "@testing-library/react";
import { faCircle } from "@fortawesome/free-solid-svg-icons";

const PYTHON = "curio.builtin/python-computation@1";
const LOAD = "02590590-5a1e-4d4b-9c1e-1a2b3c4d5e6f";
const STATS = "7c1e9f30-2b4d-4e8a-b1c2-3d4e5f6a7b8c";
// A plan node that is no longer on the canvas.
const GONE = "9f3b2c1d-8e7f-4a6b-9c5d-4e3f2a1b0c9d";

/** The canvas's nodes, as the flow context holds them: a Python node renamed
 *  "Load roads" and one that kept its template's name. */
const mockNodes = [
  { id: LOAD, position: { x: 0, y: 0 }, data: { nodeId: LOAD, nodeType: PYTHON, title: "Load roads" } },
  { id: STATS, position: { x: 0, y: 0 }, data: { nodeId: STATS, nodeType: PYTHON } },
];
jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({ playAllNodes: jest.fn(), nodes: mockNodes }),
}));

import { AgentBuilderStrip } from "../../components/agents/attach/AgentBuilderStrip";
import { registerNode } from "../../registry/nodeRegistry";
import type { NodeDescriptor } from "../../registry/types";
import type { AgentAttachment, AgentRemedy } from "../../services/agents";

beforeAll(() => {
  registerNode({
    id: PYTHON,
    category: "computation",
    label: "Python Computation",
    icon: faCircle,
    inputPorts: [],
    outputPorts: [],
    editor: "code",
    inPalette: true,
    description: "",
    hasCode: true,
    hasWidgets: false,
    hasGrammar: false,
    adapter: { handles: [], editor: null, container: {}, useNodeBehavior: () => ({}) },
  } as unknown as NodeDescriptor);
});

const attachment = (session: AgentAttachment["builderSession"]): AgentAttachment =>
  ({
    attachmentId: "a1",
    coord: "agent.curio.dataflow-builder@1",
    target: { kind: "canvas" },
    sessionId: "s1",
    revision: 1,
    name: "Dataflow Builder",
    category: "canvas",
    hooks: ["canvas"],
    intent: null,
    intentEdited: false,
    title: null,
    titleEdited: false,
    builderSession: session,
  }) as AgentAttachment;

const remedy = (attachmentId: string, nodeId: string): AgentRemedy => ({
  kind: "dataset-selection",
  attachmentId,
  nodeId,
});

/** The line's words, while nothing runs. */
const words = () => document.querySelector<HTMLElement>("[data-curio-plan-words]");

test("the line names a failed node by its title", () => {
  render(
    <AgentBuilderStrip
      attachment={attachment({ phase: "applied", nodeRuns: { [LOAD]: "failed", [STATS]: "solved" } })}
      onSolve={jest.fn()}
    />,
  );
  expect(words()).toHaveTextContent(/^Failed · Load roads$/);
  expect(words()).not.toHaveTextContent(LOAD.slice(0, 8));
  // A name too long for the line is cut; its tooltip says it whole.
  expect(within(words()!).getByText("Load roads")).toHaveAttribute("data-tooltip", "Load roads");
});

test("a node without a title is named by its template's label, as its header is", () => {
  render(
    <AgentBuilderStrip
      attachment={attachment({ phase: "applied", nodeRuns: { [LOAD]: "solved", [STATS]: "failed" } })}
      onSolve={jest.fn()}
    />,
  );
  expect(words()).toHaveTextContent(/^Failed · Python Computation$/);
  expect(words()).not.toHaveTextContent(STATS.slice(0, 8));
});

test("only a node that is not on the canvas keeps its short id", () => {
  render(
    <AgentBuilderStrip
      attachment={attachment({ phase: "applied", nodeRuns: { [LOAD]: "solved", [GONE]: "failed" } })}
      onSolve={jest.fn()}
    />,
  );
  expect(words()).toHaveTextContent(new RegExp(`^Failed · ${GONE.slice(0, 8)}$`));
});

test("the node at work, while a batch runs, is named as its header is", () => {
  render(
    <AgentBuilderStrip
      attachment={attachment({ phase: "solving", nodeRuns: { [LOAD]: "pending", [STATS]: "pending" } })}
      onSolve={jest.fn()}
      solveProgress={{ [STATS]: "generating" }}
    />,
  );
  expect(screen.getByRole("group", { name: "Dataflow Builder" })).toHaveTextContent(
    /Solving Python Computation · \d+:\d\d · 0 of 2 built/,
  );
});

test("a node awaiting a source is named on the line as its header is", () => {
  render(
    <AgentBuilderStrip
      attachment={attachment({ phase: "applied", nodeRuns: { [LOAD]: "pending" } })}
      onSolve={jest.fn()}
      solveRemedies={{ [LOAD]: remedy("att-a", LOAD) }}
      onShowSources={jest.fn()}
    />,
  );
  expect(words()).toHaveTextContent(/^Paused · Load roads needs a source$/);
});
