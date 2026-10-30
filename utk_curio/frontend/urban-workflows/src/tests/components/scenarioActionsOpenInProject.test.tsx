/**
 * Define scenario opens the define panel, which saves nothing until its
 * Save; Duplicate
 * scenario opens it on the copy, at Name & set. A command that is refused
 * opens nothing.
 *
 * The real `useScenarioActions` and the real drawer provider; the flow, the
 * canvas store, the loader and the copy are mocked.
 */
import React from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import "@testing-library/jest-dom";
import { MemoryRouter } from "react-router-dom";

import * as scenarioUi from "../../components/scenarios/scenarioUi";
import { useScenarioActions } from "../../components/scenarios/useScenarioActions";
import { ScenarioCatalogDrawerProvider } from "../../providers/scenarioCatalog";
import { scenarioCatalogApi } from "../../services/scenarioCatalog/scenarioCatalogApi";

jest.mock("vega", () => ({}), { virtual: true });
jest.mock("vega-lite", () => ({}), { virtual: true });

jest.mock("../../services/scenarioCatalog/scenarioCatalogApi", () => ({
  scenarioCatalogApi: { listCatalog: jest.fn(), getScenario: jest.fn() },
}));

const mockFlow: Record<string, any> = {};
jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => mockFlow,
}));

const mockShowToast = jest.fn();
jest.mock("../../providers/ToastProvider", () => ({
  useToastContext: () => ({ showToast: mockShowToast }),
}));

jest.mock("../../hook/useCode", () => ({
  useCode: () => ({ loadTrill: jest.fn() }),
}));

jest.mock("../../hook/useSharedView", () => ({ useSharedView: () => false }));

const mockCanvas: { nodes: any[] } = { nodes: [] };
jest.mock("reactflow", () => ({
  ...jest.requireActual("reactflow"),
  useReactFlow: () => ({
    getNodes: () => mockCanvas.nodes,
    getEdges: () => [],
  }),
  // The define panel reads the selection from React Flow's store.
  useStore: (selector: (s: any) => unknown) =>
    selector({ nodeInternals: new Map(mockCanvas.nodes.map((n: any) => [n.id, n])) }),
}));

jest.mock("../../TrillGenerator", () => ({
  TrillGenerator: { generateTrill: () => ({ dataflow: { nodes: [], edges: [] } }) },
}));

jest.mock("../../utils/scenarios/duplicateSelection", () => ({
  duplicateSelection: () => ({ nodes: [], edges: [], ids: new Map([["scale", "scale-copy"]]) }),
}));

const api = scenarioCatalogApi as unknown as { listCatalog: jest.Mock };
const ScenarioUiProvider = (scenarioUi as any).ScenarioUiProvider as React.FC<{ children: React.ReactNode }>;

const DRAWER = '[data-curio-scenario-catalog-drawer="true"]';

function node(id: string, selected: boolean) {
  return {
    id,
    type: "universal",
    selected,
    position: { x: 0, y: 0 },
    width: 525,
    height: 350,
    data: { nodeType: "curio.builtin/computation-analysis@1", title: id },
  };
}

const Commands: React.FC = () => {
  const actions = useScenarioActions();
  return (
    <>
      <button onClick={actions.saveSelectionAsScenario}>save the selection</button>
      <button onClick={() => actions.duplicateScenario("s1")}>duplicate the scenario</button>
      <button onClick={actions.duplicate}>duplicate the selection</button>
    </>
  );
};

function renderCommands() {
  render(
    <MemoryRouter>
      <ScenarioUiProvider>
        <ScenarioCatalogDrawerProvider>
          <Commands />
        </ScenarioCatalogDrawerProvider>
      </ScenarioUiProvider>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  jest.clearAllMocks();
  mockCanvas.nodes = [node("load", false), node("scale", true)];
  for (const key of Object.keys(mockFlow)) delete mockFlow[key];
  Object.assign(mockFlow, {
    projectDirty: true,
    projectId: null,
    scenarios: [],
    scenarioSets: [],
    nodes: mockCanvas.nodes,
    edges: [],
    notebookOn: false,
    setScenarios: jest.fn(),
    playNodesUpTo: jest.fn(),
    markDirty: jest.fn(),
    workflowNameRef: { current: "Heights" },
    workflowGoal: "",
  });
  api.listCatalog.mockResolvedValue({ items: [] });
});

describe("the scenario commands", () => {
  test("Define scenario opens the define panel and saves nothing yet", async () => {
    renderCommands();
    fireEvent.click(screen.getByRole("button", { name: "save the selection" }));
    expect(await screen.findByTestId("scenario-define-panel")).toBeInTheDocument();
    expect(mockFlow.setScenarios).not.toHaveBeenCalled();
    expect(document.querySelector(DRAWER)).toBeNull();
  });

  test("Duplicate scenario copies it into its set, with its context and no outcomes, and opens the copy at Name & set", async () => {
    const original = {
      id: "s1", name: "Doubled", color: "#2a9d8f", nodes: ["scale"], set: "park", context: ["load"], outcomes: ["chart"],
    };
    mockFlow.scenarios = [original];
    mockFlow.scenarioSets = [{ id: "park", name: "Heights" }];
    mockFlow.setScenarios = jest.fn((next) => {
      mockFlow.scenarios = next;
    });
    renderCommands();
    fireEvent.click(screen.getByRole("button", { name: "duplicate the scenario" }));
    const [next] = mockFlow.setScenarios.mock.calls[0];
    expect(next[0]).toBe(original);
    expect(next[1]).toEqual(
      expect.objectContaining({ nodes: ["scale-copy"], set: "park", context: ["load"], outcomes: [] }),
    );
    expect(next[1].color).not.toBe(original.color);
    const panel = await screen.findByTestId("scenario-define-panel");
    expect(within(panel).getByRole("listitem", { current: "step" })).toHaveTextContent("Name & set");
    expect(within(panel).getByTestId("scenario-define-name")).toHaveValue(next[1].name);
    expect(within(panel).getByRole("radio", { name: /Heights/ })).toBeChecked();
    expect(document.querySelector(DRAWER)).toBeNull();
  });

  test("Duplicate scenario keeps a collapsed scenario collapsed, and its copy too, boxed just below", async () => {
    const original = {
      id: "s1", name: "Doubled", color: "#2a9d8f", nodes: ["scale"], set: "park", collapsed: true, box: { x: 40, y: 60 },
    };
    mockFlow.scenarios = [original];
    mockFlow.scenarioSets = [{ id: "park", name: "Heights" }];
    mockFlow.setScenarios = jest.fn((next) => {
      mockFlow.scenarios = next;
    });
    renderCommands();
    fireEvent.click(screen.getByRole("button", { name: "duplicate the scenario" }));
    const [next] = mockFlow.setScenarios.mock.calls[0];
    // The original is left as it was: still collapsed, its box where it was.
    expect(next[0]).toBe(original);
    expect(next[1]).toEqual(expect.objectContaining({ nodes: ["scale-copy"], collapsed: true }));
    expect(next[1].box.x).toBe(40);
    expect(next[1].box.y).toBeGreaterThan(60);
    await screen.findByTestId("scenario-define-panel");
  });

  test("a command that is refused opens nothing", async () => {
    mockCanvas.nodes = [node("load", false), node("scale", false)];
    mockFlow.nodes = mockCanvas.nodes;
    renderCommands();
    fireEvent.click(screen.getByRole("button", { name: "duplicate the selection" }));
    expect(mockShowToast).toHaveBeenCalledWith(
      "Select the nodes to duplicate first (Shift and drag).",
      "warning",
    );
    expect(mockFlow.setScenarios).not.toHaveBeenCalled();
    // Nothing is mounted, or the drawer would be sliding in.
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(document.querySelector(DRAWER)).toBeNull();
  });
});
