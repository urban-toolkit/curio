/**
 * The three scenario commands that opened the Scenarios panel, Save selection
 * as scenario, Save dataflow as scenario and Duplicate as scenario, now open
 * the Scenario Catalog drawer on its In project tab, where the new scenario is
 * listed. A command that is refused opens nothing.
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
      <button onClick={actions.saveDataflowAsScenario}>save the dataflow</button>
      <button onClick={() => actions.duplicate(true)}>duplicate as a scenario</button>
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

async function expectInProjectOpen() {
  await waitFor(() =>
    expect(document.querySelector(DRAWER)).toHaveAttribute("aria-hidden", "false"),
  );
  const drawer = document.querySelector(DRAWER) as HTMLElement;
  expect(within(drawer).getByRole("button", { name: /^In project/ })).toHaveAttribute("aria-pressed", "true");
}

beforeEach(() => {
  jest.clearAllMocks();
  mockCanvas.nodes = [node("load", false), node("scale", true)];
  for (const key of Object.keys(mockFlow)) delete mockFlow[key];
  Object.assign(mockFlow, {
    projectDirty: true,
    projectId: null,
    scenarios: [],
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

describe("the scenario commands open the In project tab", () => {
  test("Save selection as scenario", async () => {
    renderCommands();
    fireEvent.click(screen.getByRole("button", { name: "save the selection" }));
    expect(mockFlow.setScenarios).toHaveBeenCalledWith([
      expect.objectContaining({ nodes: ["scale"] }),
    ]);
    await expectInProjectOpen();
  });

  test("Save dataflow as scenario", async () => {
    renderCommands();
    fireEvent.click(screen.getByRole("button", { name: "save the dataflow" }));
    expect(mockFlow.setScenarios).toHaveBeenCalledWith([
      expect.objectContaining({ nodes: ["load", "scale"] }),
    ]);
    await expectInProjectOpen();
  });

  test("Duplicate as scenario", async () => {
    renderCommands();
    fireEvent.click(screen.getByRole("button", { name: "duplicate as a scenario" }));
    expect(mockFlow.setScenarios).toHaveBeenCalledWith([
      expect.objectContaining({ nodes: ["scale"] }),
      expect.objectContaining({ nodes: ["scale-copy"] }),
    ]);
    await expectInProjectOpen();
  });

  test("a command that is refused opens nothing", async () => {
    mockCanvas.nodes = [node("load", false), node("scale", false)];
    mockFlow.nodes = mockCanvas.nodes;
    renderCommands();
    fireEvent.click(screen.getByRole("button", { name: "save the selection" }));
    expect(mockShowToast).toHaveBeenCalledWith(
      "Select the nodes the scenario holds first (Shift and drag).",
      "warning",
    );
    expect(mockFlow.setScenarios).not.toHaveBeenCalled();
    // Nothing is mounted, or the drawer would be sliding in.
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(document.querySelector(DRAWER)).toBeNull();
  });
});
