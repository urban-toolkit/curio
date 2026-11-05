/**
 * The Dataflow Builder's plan pills ("Plan node progress") name each planned
 * node as its header on the canvas does: its title, else its template's label.
 * Only a node that is not on the canvas is named by the first 8 characters of
 * its id. Each pill's Solve button says the same name, and so does each Open
 * Dataset Finder button when several nodes await a source.
 */
import React from "react";
import { render, screen, within } from "@testing-library/react";
import { faCircle } from "@fortawesome/free-solid-svg-icons";

const PYTHON = "curio.builtin/computation-analysis@1";
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

function renderStrip(props: Partial<React.ComponentProps<typeof AgentBuilderStrip>> = {}) {
  return render(
    <AgentBuilderStrip
      attachment={attachment({
        phase: "applied",
        nodeRuns: { [LOAD]: "pending", [STATS]: "pending", [GONE]: "failed" },
      })}
      onSolve={jest.fn()}
      onComposePrompt={jest.fn()}
      onSolveNode={jest.fn()}
      {...props}
    />,
  );
}

test("a pill and its Solve button name the planned node by its title", () => {
  renderStrip();
  const pills = screen.getByRole("list", { name: "Plan node progress" });
  expect(within(pills).getByText("Load roads")).toBeInTheDocument();
  expect(pills).not.toHaveTextContent(LOAD.slice(0, 8));
  expect(screen.getByRole("button", { name: "Solve node Load roads on its own" })).toBeEnabled();
  // A name too long for the pill is cut; its tooltip says it whole.
  expect(within(pills).getByText("Load roads")).toHaveAttribute("data-tooltip", "Load roads");
});

test("a node without a title is named by its template's label, as its header is", () => {
  renderStrip();
  const pills = screen.getByRole("list", { name: "Plan node progress" });
  expect(within(pills).getByText("Python Computation")).toBeInTheDocument();
  expect(pills).not.toHaveTextContent(STATS.slice(0, 8));
  expect(screen.getByRole("button", { name: "Solve node Python Computation on its own" })).toBeEnabled();
});

test("only a node that is not on the canvas keeps its short id", () => {
  renderStrip();
  const pills = screen.getByRole("list", { name: "Plan node progress" });
  expect(within(pills).getByText(GONE.slice(0, 8))).toBeInTheDocument();
  expect(screen.getByRole("button", { name: `Solve node ${GONE.slice(0, 8)} on its own` })).toBeEnabled();
});

test("each node awaiting a source names its own Open Dataset Finder button", () => {
  renderStrip({
    attachment: attachment({ phase: "applied", nodeRuns: { [LOAD]: "pending", [STATS]: "pending" } }),
    solveRemedies: { [LOAD]: remedy("att-a", LOAD), [STATS]: remedy("att-b", STATS) },
    onOpenChat: jest.fn(),
    agentNameOf: () => "Dataset Finder",
  });
  const group = screen.getByRole("group", { name: "Nodes awaiting a dataset selection" });
  expect(within(group).getByRole("button", { name: "Open Dataset Finder for Load roads" })).toBeInTheDocument();
  expect(
    within(group).getByRole("button", { name: "Open Dataset Finder for Python Computation" }),
  ).toBeInTheDocument();
});
