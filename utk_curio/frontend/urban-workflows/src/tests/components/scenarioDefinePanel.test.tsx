/**
 * The define panel: a scenario is its own nodes, selected first; then a set,
 * new or one of this dataflow's; then the shared context and outcomes Curio
 * proposes from the edges, which the person edits; Save writes it all, and
 * nothing is written before.
 *
 * The real panel and ScenarioUi; the flow and the toasts are mocked.
 */
import React from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import "@testing-library/jest-dom";

import { ScenarioDefinePanel } from "../../components/scenarios/define/ScenarioDefinePanel";
import { ScenarioUiContext, type ScenarioUi } from "../../components/scenarios/scenarioUi";

const mockFlow: Record<string, any> = {};
jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => mockFlow,
}));
const mockShowToast = jest.fn();
jest.mock("../../providers/ToastProvider", () => ({
  useToastContext: () => ({ showToast: mockShowToast }),
}));

const node = (id: string, selected = false) => ({
  id,
  type: "universal",
  selected,
  position: { x: 0, y: 0 },
  data: { nodeType: "curio.builtin/computation-analysis@1", title: id },
});

// load → heights → existing ─┐
//                 heights → around → towers ─┤→ chart
const EDGES = [
  { source: "load", target: "heights" },
  { source: "heights", target: "existing" },
  { source: "heights", target: "around" },
  { source: "around", target: "towers" },
  { source: "existing", target: "chart" },
  { source: "towers", target: "chart" },
  { source: "existing", target: "change" },
  { source: "towers", target: "change" },
];
const EXISTING = {
  id: "e",
  name: "Existing",
  color: "#2a9d8f",
  nodes: ["existing"],
  set: "park",
  context: ["load", "heights"],
  outcomes: ["chart", "change"],
};

function ui(over: Partial<ScenarioUi> = {}): ScenarioUi {
  return {
    highlighted: null,
    setHighlighted: jest.fn(),
    define: null,
    setDefine: jest.fn(),
    preview: null,
    setPreview: jest.fn(),
    ...over,
  };
}

function renderPanel(define: ScenarioUi["define"], value = ui()) {
  render(
    <ScenarioUiContext.Provider value={{ ...value, define }}>
      <ScenarioDefinePanel define={define!} />
    </ScenarioUiContext.Provider>,
  );
  return value;
}

const part = (name: string) => within(screen.getByRole("region", { name }));

beforeEach(() => {
  jest.clearAllMocks();
  for (const key of Object.keys(mockFlow)) delete mockFlow[key];
  Object.assign(mockFlow, {
    scenarios: [],
    scenarioSets: [],
    nodes: ["load", "heights", "around", "existing", "towers", "chart", "change"].map((id) => node(id)),
    edges: EDGES,
    setScenarios: jest.fn(),
    workflowNameRef: { current: "Park shade" },
  });
});

describe("a new scenario", () => {
  test("goes in a new set named after the dataflow, with what Curio found upstream and downstream", () => {
    const value = renderPanel({ mode: "new", nodes: ["existing"] });
    expect(screen.getByRole("listitem", { current: "step" })).toHaveTextContent("Choose a set");
    expect(screen.getByTestId("scenario-define-set-name")).toHaveValue("Park shade");
    fireEvent.click(screen.getByRole("button", { name: "Next: review context & outcomes" }));

    expect(part("Shared context").getByText("load")).toBeInTheDocument();
    expect(part("Shared context").getByText("heights")).toBeInTheDocument();
    expect(part("Shared context").queryByText("around")).toBeNull();
    expect(part("Outcomes").getByText("chart")).toBeInTheDocument();
    expect(part("Outcomes").getByText("change")).toBeInTheDocument();
    expect(mockFlow.setScenarios).not.toHaveBeenCalled();

    fireEvent.click(screen.getByTestId("scenario-define-save"));
    const [scenarios, sets] = mockFlow.setScenarios.mock.calls[0];
    expect(sets).toEqual([{ id: expect.stringMatching(/^set-/), name: "Park shade" }]);
    expect(scenarios).toEqual([
      expect.objectContaining({
        nodes: ["existing"],
        set: sets[0].id,
        context: ["load", "heights"],
        outcomes: ["chart", "change"],
      }),
    ]);
    expect(value.setDefine).toHaveBeenCalledWith(null);
  });

  test("Cancel writes nothing", () => {
    const value = renderPanel({ mode: "new", nodes: ["existing"] });
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(mockFlow.setScenarios).not.toHaveBeenCalled();
    expect(value.setDefine).toHaveBeenCalledWith(null);
  });

  test("joins an existing set, telling what the set has from what is new to it", () => {
    mockFlow.scenarios = [EXISTING];
    mockFlow.scenarioSets = [{ id: "park", name: "Park shade" }];
    renderPanel({ mode: "new", nodes: ["towers"] });
    expect(screen.getByRole("radio", { name: /Park shade/ })).toBeChecked();
    fireEvent.click(screen.getByRole("button", { name: "Next: review context & outcomes" }));

    const context = screen.getByRole("region", { name: "Shared context" });
    expect(within(context).getByText("Already in the set").parentElement).toHaveTextContent("load");
    expect(within(context).getByText("New to the set").parentElement).toHaveTextContent("around");

    fireEvent.click(screen.getByTestId("scenario-define-save"));
    const [scenarios, sets] = mockFlow.setScenarios.mock.calls[0];
    expect(sets).toEqual([{ id: "park", name: "Park shade" }]);
    expect(scenarios[1]).toEqual(
      expect.objectContaining({ nodes: ["towers"], set: "park", context: ["load", "heights", "around"] }),
    );
  });

  test("a node is removed with ×, and a selected one is added", () => {
    mockFlow.nodes = mockFlow.nodes.map((n: any) => (n.id === "around" ? { ...n, selected: true } : n));
    renderPanel({ mode: "new", nodes: ["existing"] });
    fireEvent.click(screen.getByRole("button", { name: "Next: review context & outcomes" }));
    fireEvent.click(screen.getByRole("button", { name: "Remove change" }));
    fireEvent.click(part("Shared context").getByRole("button", { name: "+ Add selected node" }));
    fireEvent.click(screen.getByTestId("scenario-define-save"));
    const [scenarios] = mockFlow.setScenarios.mock.calls[0];
    // In the dataflow's order.
    expect(scenarios[0].context).toEqual(["load", "heights", "around"]);
    expect(scenarios[0].outcomes).toEqual(["chart"]);
  });

  test("the canvas marks what the panel holds", () => {
    const value = renderPanel({ mode: "new", nodes: ["existing"] });
    expect(value.setPreview).toHaveBeenCalledWith({ context: ["load", "heights"], outcomes: ["chart", "change"] });
  });
});

describe("editing a scenario's context and outcomes", () => {
  test("starts from what it keeps and saves only those", () => {
    mockFlow.scenarios = [{ ...EXISTING, outcomes: ["chart"] }];
    mockFlow.scenarioSets = [{ id: "park", name: "Park shade" }];
    renderPanel({ mode: "edit", scenarioId: "e" });
    expect(part("Outcomes").queryByText("change")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Remove heights" }));
    fireEvent.click(screen.getByTestId("scenario-define-save"));
    expect(mockFlow.setScenarios).toHaveBeenCalledWith([
      { ...EXISTING, context: ["load"], outcomes: ["chart"] },
    ]);
  });
});
