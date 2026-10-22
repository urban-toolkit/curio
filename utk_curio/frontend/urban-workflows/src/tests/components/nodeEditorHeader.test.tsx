/**
 * A node's header is the same for a built-in node and a package node (#662).
 * It reads only the editor's language and grammar and the node's inputs with
 * their boxes, never the node's kind or its spec, so the built-in Vega-Lite
 * node and one of Scout's charts (`curio.scout/bars`, a package template that
 * draws with the Vega-Lite grammar) over the same inputs list the same chips,
 * each dragging the same chip. A code node over those inputs shows no
 * Scenarios and no `inputs` tag.
 *
 * NodeEditor mounts its real GrammarEditor and CodeEditor; Monaco and the
 * Widgets tab are stubbed.
 */
import React from "react";
import { fireEvent, render, within } from "@testing-library/react";

const mockFlow: { nodes: any[]; edges: any[]; scenarios: any[] } = { nodes: [], edges: [], scenarios: [] };
jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({
    dashboardOn: false,
    markDirty: jest.fn(),
    markNodeStale: jest.fn(),
    requestAutoRun: jest.fn(),
    playNodesUpTo: jest.fn(),
    workflowNameRef: { current: "Header" },
    ...mockFlow,
  }),
}));

jest.mock("@monaco-editor/react", () => ({
  __esModule: true,
  default: ({ value }: any) => <textarea data-testid="monaco" value={value ?? ""} readOnly />,
}));

jest.mock("../../providers/CollaborationProvider", () => ({
  useCollab: () => ({
    enabled: false,
    connected: false,
    users: [],
    proposals: [],
    currentUserId: null,
    requestCodeChange: jest.fn(),
    approveCodeChange: jest.fn(),
    rejectCodeChange: jest.fn(),
    onRemote: jest.fn(() => jest.fn()),
  }),
}));

jest.mock("../../components/editing/WidgetsEditor", () => ({
  __esModule: true,
  default: () => <div data-testid="widgets-tab" />,
}));

import NodeEditor from "../../components/editing/NodeEditor";
import { clearVegaLiteTemplate, registerVegaLiteTemplate } from "../_support/vegaLiteTemplate";
import {
  chipsOf,
  draggedText,
  headerRow,
  openCategory,
  openEveryCategory,
  type StripCategory,
} from "../_support/stripCategories";

const SCOUT_BARS = "curio.scout/bars@1";
const WIDGETS = [
  { name: "y", type: "text", label: "Y column", default: "y", value: "mean" },
  { name: "y_title", type: "text", label: "Y axis title", default: "" },
];
const SPEC = '{\n  "data": {"name": "[!! inputs !!]"},\n  "mark": "bar"\n}';

/** Two shadows, each in its box, feeding each chart; a season Parameter node beside them. */
function setFlow(targets: string[]) {
  mockFlow.nodes = [
    { id: "shadow-a", type: "curio.scout/raster-calculator", data: { title: "Shadow over the ground" } },
    { id: "shadow-b", type: "curio.scout/raster-calculator", data: { title: "Shadow over the ground" } },
    {
      id: "season",
      type: "curio.builtin/parameter",
      data: { widgets: [{ name: "season", type: "text", label: "Season", default: "summer" }] },
    },
    ...targets.map((id) => ({ id, type: "x", data: { title: "Mean accumulated shadow" } })),
  ];
  mockFlow.edges = targets.flatMap((id) => [
    { id: `${id}-0`, source: "shadow-a", target: id, sourceHandle: "out", targetHandle: "in" },
    { id: `${id}-1`, source: "shadow-b", target: id, sourceHandle: "out", targetHandle: "in_1" },
  ]);
  mockFlow.scenarios = [
    { id: "existing", name: "Existing", color: "#2a9d8f", nodes: ["shadow-a"] },
    { id: "towers-removed", name: "Towers removed", color: "#e76f51", nodes: ["shadow-b"] },
  ];
}

function chartEditor(nodeId: string, nodeType: string) {
  return (
    <NodeEditor
      {...({
        setSendCodeCallback: jest.fn(),
        setOutputCallback: jest.fn(),
        data: { nodeId, widgets: WIDGETS, outputCallback: jest.fn() },
        output: { code: "", content: "" },
        nodeType,
        readOnly: false,
        applyGrammar: jest.fn(),
        code: false,
        grammar: true,
        widgets: true,
        defaultValue: SPEC,
      } as any)}
    />
  );
}

/** The header as a user meets it: its row, then each category's tags with what each drags. */
function headerOf(container: HTMLElement) {
  const row = headerRow(container).map((entry) => `${entry.label}${entry.open ? " open" : ""}`);
  openEveryCategory(container);
  const chips: Record<string, string[]> = {};
  for (const entry of headerRow(container)) {
    const group = container.querySelector(`[data-widget-strip] [data-strip-chips="${entry.category as StripCategory}"]`)!;
    chips[entry.category as string] = Array.from(group.querySelectorAll("[draggable]")).map((tag) => {
      const color = tag.getAttribute("data-color");
      return `${tag.textContent} -> ${draggedText(tag)}${color ? ` ${color}` : ""}`;
    });
  }
  return { row, chips };
}

beforeAll(() => registerVegaLiteTemplate(SCOUT_BARS));
afterAll(() => clearVegaLiteTemplate());

test("a built-in Vega-Lite node and a Scout chart over the same inputs give the same header", () => {
  setFlow(["builtin-chart", "scout-chart"]);
  const builtin = render(chartEditor("builtin-chart", "curio.builtin/vis-vega"));
  const builtinHeader = headerOf(builtin.container);
  builtin.unmount();
  const scout = render(chartEditor("scout-chart", SCOUT_BARS));
  const scoutHeader = headerOf(scout.container);

  expect(scoutHeader).toEqual(builtinHeader);
  expect(builtinHeader.row).toEqual(["Inputs 3", "Scenarios 5", "Widgets 2", "Shared 1"]);
  expect(builtinHeader.chips).toEqual({
    inputs: ["input_0 -> [!! input_0 !!]", "input_1 -> [!! input_1 !!]", "inputs -> [!! inputs !!]"],
    scenarios: [
      "ExistingTowers removed -> [!! scenario colors !!]",
      "text colors -> [!! scenario text_colors !!]",
      "order -> [!! scenario order !!]",
      "input_0Existing -> [!! scenario input_0 !!] #2a9d8f",
      "input_1Towers removed -> [!! scenario input_1 !!] #e76f51",
    ],
    widgets: ["y -> [!! y !!]", "y_title -> [!! y_title !!]"],
    shared: ["@season -> [!! @season !!]"],
  });
});

function codeEditor(nodeId: string) {
  return (
    <NodeEditor
      {...({
        setSendCodeCallback: jest.fn(),
        setOutputCallback: jest.fn(),
        data: { nodeId, widgets: WIDGETS, outputCallback: jest.fn() },
        output: { code: "", content: "" },
        nodeType: "curio.builtin/computation-analysis",
        readOnly: false,
        code: true,
        grammar: false,
        widgets: true,
        defaultValue: "return input_0",
      } as any)}
    />
  );
}

test("a code node over the same inputs shows no Scenarios and no inputs tag", () => {
  setFlow(["code-node"]);
  const view = render(codeEditor("code-node"));
  expect(headerOf(view.container)).toEqual({
    row: ["Inputs 2", "Widgets 2", "Shared 1"],
    chips: {
      inputs: ["input_0 -> [!! input_0 !!]", "input_1 -> [!! input_1 !!]"],
      widgets: ["y -> [!! y !!]", "y_title -> [!! y_title !!]"],
      shared: ["@season -> [!! @season !!]"],
    },
  });
});

test.each([
  ["a chart", "kept-open-chart", (nodeId: string) => chartEditor(nodeId, "curio.builtin/vis-vega")],
  ["a code node", "kept-open-code", (nodeId: string) => codeEditor(nodeId)],
] as const)("%s keeps Inputs and input_0's list open when its editor mounts again", (_kind, nodeId, editor) => {
  // As after a run or a tab switch: the node's editor mounts again.
  setFlow([nodeId]);
  const first = render(editor(nodeId));
  const chips = openCategory(first.container, "inputs");
  fireEvent.click(within(chips).getByRole("button", { name: "Show the columns of input_0" }));
  expect(chips.querySelector('[data-input-columns="0"]')).not.toBeNull();
  first.unmount();

  const again = render(editor(nodeId));
  expect(headerRow(again.container).find((entry) => entry.category === "inputs")?.open).toBe(true);
  const kept = chipsOf(again.container, "inputs");
  expect(kept).not.toBeNull();
  expect(kept!.querySelector('[data-input-columns="0"]')).not.toBeNull();
  expect(within(kept!).getByRole("button", { name: "Hide the columns of input_0" }).getAttribute("aria-expanded"))
    .toBe("true");
});
