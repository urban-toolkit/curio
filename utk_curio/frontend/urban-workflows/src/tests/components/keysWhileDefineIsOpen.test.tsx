/**
 * Define scenario is a drawer beside the canvas, not a modal: the canvas stays
 * usable beside it, so it holds no layer of the modal stack and the canvas
 * keeps its keys. It counts only in the drawers' Escape order
 * (drawersOverDefine.test.tsx).
 *
 * - Ctrl/Cmd+Enter runs the selected node while Define is open.
 * - An Escape typed into the agents' chat closes the chat, and one typed into
 *   the fork picker closes its list; Define stays open with its pick.
 * - An Escape on the canvas closes Define, and so does one on an open
 *   palette's button, which leaves Escape alone.
 *
 * The real Define panel, HeaderDrawer, ModalShell, chat panel, fork picker and
 * the canvas's Ctrl/Cmd+Enter; the flow, the canvas's nodes, the catalog's
 * routes and the scenario commands are mocked.
 */
import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { MemoryRouter } from "react-router-dom";

jest.mock("vega", () => ({}), { virtual: true });
jest.mock("vega-lite", () => ({}), { virtual: true });

const mockFlow: Record<string, any> = {};
jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => mockFlow,
}));
jest.mock("../../providers/ToastProvider", () => ({
  useToastContext: () => ({ showToast: jest.fn() }),
}));
jest.mock("../../services/scenarioCatalog/scenarioCatalogApi", () => ({
  scenarioCatalogApi: { listCatalog: jest.fn(() => Promise.resolve({ items: [] })), getScenario: jest.fn() },
}));
jest.mock("../../services/packages/packagesApi", () => ({ packagesApi: {} }));
jest.mock("../../components/scenarios/useScenarioActions", () => ({
  useScenarioActions: () => ({}),
}));
jest.mock("../../hook/useSharedView", () => ({ useSharedView: () => false }));
// The canvas: its selection as React Flow's store holds it, none here, and its
// nodes as Ctrl/Cmd+Enter reads them.
let mockNodes: Array<{ id: string; selected?: boolean }> = [];
jest.mock("reactflow", () => ({
  ...jest.requireActual("reactflow"),
  useStore: (selector: (s: any) => unknown) => selector({ nodeInternals: new Map() }),
  useReactFlow: () => ({ getNodes: () => mockNodes }),
}));

import { AgentChatPanel } from "../../components/agents/attach/AgentChatPanel";
import { ForkFamilyPicker } from "../../components/packages/ForkFamilyPicker";
import { ScenarioDefinePanel } from "../../components/scenarios/define/ScenarioDefinePanel";
import { ScenarioUiContext, type ScenarioUi } from "../../components/scenarios/scenarioUi";
import { useRunSelectedNodeShortcut } from "../../hook/useRunSelectedNodeShortcut";

const setDefine = jest.fn();
const UI: ScenarioUi = {
  highlighted: null,
  setHighlighted: jest.fn(),
  define: { mode: "new", nodes: ["real"] },
  setDefine,
  preview: null,
  setPreview: jest.fn(),
};

const closeChat = jest.fn();
const ATTACHMENT: any = {
  attachmentId: "att-1",
  coord: "agent.curio.researcher@1",
  target: { kind: "canvas" },
  sessionId: "s1",
  revision: 1,
  intent: null,
  intentEdited: false,
  title: null,
  titleEdited: false,
  name: "Researcher",
  category: "canvas",
  hooks: ["canvas"],
};

/** The canvas's Ctrl/Cmd+Enter, as MainCanvas mounts it. */
function RunShortcut() {
  useRunSelectedNodeShortcut();
  return null;
}

/** The canvas, Define scenario open with the node it picked, and beside them
 *  the agents' chat, the fork picker, an open palette's button, or nothing. */
function tree(beside: "chat" | "picker" | "palette" | null) {
  return (
    <MemoryRouter initialEntries={["/dataflow/p-current"]}>
      <ScenarioUiContext.Provider value={UI}>
        <div className="react-flow__pane" data-testid="canvas" tabIndex={-1} />
        <RunShortcut />
        <ScenarioDefinePanel define={{ mode: "new", nodes: ["real"] }} presented onExitComplete={jest.fn()} />
        {beside === "chat" && (
          <AgentChatPanel
            attachment={ATTACHMENT}
            turns={[]}
            onSend={jest.fn()}
            onClose={closeChat}
            onExitComplete={jest.fn()}
            presented
          />
        )}
        {beside === "picker" && (
          <ForkFamilyPicker
            variant="dock"
            rootKey="acme.charts"
            options={[
              { key: "acme.charts", label: "Charts" },
              { key: "acme.charts-fork", label: "Charts, forked" },
            ]}
            value="acme.charts"
            onChange={jest.fn()}
          />
        )}
        {beside === "palette" && (
          // A tool rail palette's button, its palette open, as the rail draws
          // it: the palette leaves Escape alone.
          <button type="button" aria-expanded="true" aria-haspopup="true">
            Built-in
          </button>
        )}
      </ScenarioUiContext.Provider>
    </MemoryRouter>
  );
}

beforeEach(() => {
  jest.clearAllMocks();
  mockNodes = [{ id: "real", selected: true }];
  for (const key of Object.keys(mockFlow)) delete mockFlow[key];
  Object.assign(mockFlow, {
    projectDirty: false,
    projectId: "p-current",
    scenarios: [],
    scenarioSets: [],
    nodes: [
      {
        id: "real",
        type: "universal",
        position: { x: 0, y: 0 },
        data: { nodeId: "real", nodeType: "curio.builtin/computation-analysis", title: "Real heights" },
      },
    ],
    edges: [],
    notebookOn: false,
    setScenarios: jest.fn(),
    playNodesUpTo: jest.fn(),
    workflowNameRef: { current: "Heights" },
  });
});

const definePanel = () => screen.getByRole("dialog", { name: "Define scenario" });
const picked = () => screen.getByRole("region", { name: "Scenario-specific nodes" });

test.each([
  ["Ctrl", { ctrlKey: true }],
  ["Cmd", { metaKey: true }],
])("%s+Enter runs the selected node while Define scenario is open", (_key, chord) => {
  render(tree(null));
  expect(definePanel()).toBeInTheDocument();
  fireEvent.keyDown(document.body, { key: "Enter", ...chord });
  expect(mockFlow.playNodesUpTo).toHaveBeenCalledWith("real");
});

test("an Escape typed into the agents' chat closes the chat, and Define stays open with its pick", () => {
  render(tree("chat"));
  fireEvent.keyDown(screen.getByPlaceholderText(/message this agent/i), { key: "Escape" });
  expect(closeChat).toHaveBeenCalledTimes(1);
  expect(setDefine).not.toHaveBeenCalled();
  expect(definePanel()).toBeInTheDocument();
  expect(picked()).toHaveTextContent("Real heights");
});

test("an Escape typed into the open fork picker closes its list, and Define stays open with its pick", () => {
  render(tree("picker"));
  const picker = screen.getByRole("button", { name: "Charts" });
  fireEvent.click(picker);
  expect(screen.getByRole("listbox")).toBeInTheDocument();
  fireEvent.keyDown(picker, { key: "Escape" });
  expect(screen.queryByRole("listbox")).toBeNull();
  expect(setDefine).not.toHaveBeenCalled();
  expect(picked()).toHaveTextContent("Real heights");
});

test("an Escape on the canvas closes Define scenario", () => {
  render(tree(null));
  fireEvent.keyDown(screen.getByTestId("canvas"), { key: "Escape" });
  expect(setDefine).toHaveBeenCalledWith(null);
});

test("an Escape on an open palette's button, which leaves Escape alone, closes Define scenario", () => {
  render(tree("palette"));
  fireEvent.keyDown(screen.getByRole("button", { name: "Built-in" }), { key: "Escape" });
  expect(setDefine).toHaveBeenCalledWith(null);
});
