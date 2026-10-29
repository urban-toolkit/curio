/**
 * Define scenario, in three steps: the nodes unique to the scenario, selected
 * on the canvas and added, each list alike (rows with ×, + Add selected node); the shared context and outcomes Curio infers from them, which
 * the person confirms or edits; then its name and its scenario set, an
 * existing one or a new one. Save scenario writes it all, and nothing is
 * written before.
 *
 * The real panel and ScenarioUi; the flow, the canvas selection and the
 * toasts are mocked.
 */
import React from "react";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
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

// The canvas selection, as React Flow's store holds it.
const mockSelection: { ids: string[]; listeners: Set<() => void> } = { ids: [], listeners: new Set() };
jest.mock("reactflow", () => {
  const React = jest.requireActual("react");
  return {
    useStore: (selector: (s: any) => unknown) => {
      const [, bump] = React.useReducer((n: number) => n + 1, 0);
      React.useEffect(() => {
        mockSelection.listeners.add(bump);
        return () => mockSelection.listeners.delete(bump);
      }, []);
      return selector({
        nodeInternals: new Map(mockSelection.ids.map((id) => [id, { id, selected: true, hidden: false }])),
      });
    },
  };
});

function select(...ids: string[]) {
  act(() => {
    mockSelection.ids = ids;
    mockSelection.listeners.forEach((f) => f());
  });
}

const node = (id: string) => ({
  id,
  type: "universal",
  position: { x: 0, y: 0 },
  data: { nodeType: "curio.builtin/computation-analysis@1", title: id },
});

// load → heights → existing ─┐
//                 heights → around → towers ─┤→ chart, change
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

function renderPanel(define: NonNullable<ScenarioUi["define"]>, value = ui()) {
  render(
    <ScenarioUiContext.Provider value={{ ...value, define }}>
      <ScenarioDefinePanel define={define} />
    </ScenarioUiContext.Provider>,
  );
  return value;
}

const part = (name: string) => within(screen.getByRole("region", { name }));
const click = (name: string) => fireEvent.click(screen.getByRole("button", { name }));
/** "+ Add selected node" under one of the panel's lists. */
const addTo = (name: string) =>
  fireEvent.click(part(name).getByRole("button", { name: "+ Add selected node" }));

beforeEach(() => {
  jest.clearAllMocks();
  mockSelection.ids = [];
  for (const key of Object.keys(mockFlow)) delete mockFlow[key];
  Object.assign(mockFlow, {
    scenarios: [],
    scenarioSets: [],
    nodes: ["load", "heights", "around", "existing", "towers", "chart", "change"].map(node),
    edges: EDGES,
    setScenarios: jest.fn(),
    workflowNameRef: { current: "Park shade" },
  });
});

describe("defining a scenario", () => {
  test("asks for the scenario's nodes first: selected ones are added, and × takes one out", () => {
    renderPanel({ mode: "new" });
    expect(screen.getByRole("heading", { name: "Scenario-specific nodes" })).toBeInTheDocument();
    expect(part("Scenario-specific nodes").getByText("None")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Next: shared context & outcomes" })).toBeDisabled();
    select("towers", "existing");
    // Selected only: nothing is added yet.
    expect(part("Scenario-specific nodes").getByText("None")).toBeInTheDocument();
    addTo("Scenario-specific nodes");
    expect(part("Scenario-specific nodes").getByText("existing")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Next: shared context & outcomes" })).toBeEnabled();
    click("Remove towers");
    expect(part("Scenario-specific nodes").queryByText("towers")).toBeNull();
  });

  test("the canvas selection when it opens is there already", () => {
    renderPanel({ mode: "new", nodes: ["existing"] });
    expect(part("Scenario-specific nodes").getByText("existing")).toBeInTheDocument();
  });

  test("infers its context and outcomes, then puts it in a new set named after the dataflow", () => {
    const value = renderPanel({ mode: "new" });
    select("existing");
    addTo("Scenario-specific nodes");
    click("Next: shared context & outcomes");
    expect(screen.getByRole("listitem", { current: "step" })).toHaveTextContent("Shared context & outcomes");
    expect(part("Shared context").getByText("load")).toBeInTheDocument();
    expect(part("Shared context").getByText("heights")).toBeInTheDocument();
    expect(part("Shared context").queryByText("around")).toBeNull();
    expect(part("Shared outcomes").getByText("chart")).toBeInTheDocument();
    expect(value.setPreview).toHaveBeenLastCalledWith({ context: ["load", "heights"], outcomes: ["chart", "change"] });

    click("Next: name & set");
    expect(screen.getByRole("radio", { name: /Create a new scenario set/ })).toBeChecked();
    expect(screen.getByTestId("scenario-define-set-name")).toHaveValue("Park shade");
    fireEvent.change(screen.getByTestId("scenario-define-name"), { target: { value: "Existing" } });
    expect(mockFlow.setScenarios).not.toHaveBeenCalled();

    fireEvent.click(screen.getByTestId("scenario-define-save"));
    const [scenarios, sets] = mockFlow.setScenarios.mock.calls[0];
    expect(sets).toEqual([{ id: expect.stringMatching(/^set-/), name: "Park shade" }]);
    expect(scenarios).toEqual([
      expect.objectContaining({
        name: "Existing",
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
    click("Cancel");
    expect(mockFlow.setScenarios).not.toHaveBeenCalled();
    expect(value.setDefine).toHaveBeenCalledWith(null);
  });

  test("joins an existing set, telling what the set has from what is new to it", () => {
    mockFlow.scenarios = [EXISTING];
    mockFlow.scenarioSets = [{ id: "park", name: "Park shade" }];
    renderPanel({ mode: "new" });
    select("towers");
    addTo("Scenario-specific nodes");
    click("Next: shared context & outcomes");
    const context = screen.getByRole("region", { name: "Shared context" });
    expect(within(context).getByText("Already in the set").parentElement).toHaveTextContent("load");
    expect(within(context).getByText("New to the set").parentElement).toHaveTextContent("around");

    click("Next: name & set");
    expect(screen.getByRole("radio", { name: /Park shade/ })).toBeChecked();
    fireEvent.click(screen.getByTestId("scenario-define-save"));
    const [scenarios, sets] = mockFlow.setScenarios.mock.calls[0];
    expect(sets).toEqual([{ id: "park", name: "Park shade" }]);
    expect(scenarios[1]).toEqual(
      expect.objectContaining({ nodes: ["towers"], set: "park", context: ["load", "heights", "around"] }),
    );
  });

  test("a name another scenario of the chosen set has cannot be saved; a new set takes it", () => {
    mockFlow.scenarios = [EXISTING];
    mockFlow.scenarioSets = [{ id: "park", name: "Park shade" }];
    renderPanel({ mode: "new" });
    select("towers");
    addTo("Scenario-specific nodes");
    click("Next: shared context & outcomes");
    click("Next: name & set");
    fireEvent.change(screen.getByTestId("scenario-define-name"), { target: { value: "existing " } });
    expect(screen.getByRole("alert")).toHaveTextContent('"Existing" is already a scenario in "Park shade".');
    expect(screen.getByTestId("scenario-define-save")).toBeDisabled();

    fireEvent.click(screen.getByRole("radio", { name: /Create a new scenario set/ }));
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByTestId("scenario-define-save")).toBeEnabled();
  });

  test("a node already in a scenario cannot be one of its nodes", () => {
    mockFlow.scenarios = [EXISTING];
    mockFlow.scenarioSets = [{ id: "park", name: "Park shade" }];
    renderPanel({ mode: "new" });
    select("existing");
    addTo("Scenario-specific nodes");
    expect(mockShowToast).toHaveBeenCalledWith("Select a node outside every scenario on the canvas first.", "warning");
    expect(part("Scenario-specific nodes").getByText("None")).toBeInTheDocument();
  });

  test("a node is removed with ×, and a selected one is added", () => {
    renderPanel({ mode: "new", nodes: ["existing"] });
    click("Next: shared context & outcomes");
    click("Remove change");
    select("around");
    fireEvent.click(part("Shared context").getByRole("button", { name: "+ Add selected node" }));
    click("Next: name & set");
    fireEvent.click(screen.getByTestId("scenario-define-save"));
    const [scenarios] = mockFlow.setScenarios.mock.calls[0];
    // In the dataflow's order.
    expect(scenarios[0].context).toEqual(["load", "heights", "around"]);
    expect(scenarios[0].outcomes).toEqual(["chart"]);
  });

  test("Back keeps the edits made", () => {
    renderPanel({ mode: "new", nodes: ["existing"] });
    click("Next: shared context & outcomes");
    click("Remove change");
    click("Next: name & set");
    click("Back");
    expect(part("Shared outcomes").queryByText("change")).toBeNull();
  });
});

describe("Edit scenario", () => {
  const TOWERS = { id: "t", name: "Towers", color: "#e76f51", nodes: ["towers"], set: "park", context: ["load"], outcomes: ["chart"] };

  test("the same three steps, starting from the scenario's nodes", () => {
    mockFlow.scenarios = [{ ...EXISTING, outcomes: ["chart"] }];
    mockFlow.scenarioSets = [{ id: "park", name: "Park shade" }];
    renderPanel({ mode: "edit", scenarioId: "e" });
    expect(screen.getByRole("dialog", { name: "Define scenario" })).toHaveTextContent("Edit scenario: Existing");
    expect(screen.getAllByRole("listitem").map((li) => li.textContent)).toEqual(
      expect.arrayContaining(["1Scenario-specific nodes", "2Shared context & outcomes", "3Name & set"]),
    );
    expect(part("Scenario-specific nodes").getByText("existing")).toBeInTheDocument();
    click("Next: shared context & outcomes");
    // The same nodes: what it keeps, not inferred anew.
    expect(part("Shared outcomes").queryByText("change")).toBeNull();
    click("Remove heights");
    // Saved from step 2, in place.
    fireEvent.click(screen.getByTestId("scenario-define-save"));
    expect(mockFlow.setScenarios).toHaveBeenCalledWith(
      [{ ...EXISTING, context: ["load"], outcomes: ["chart"] }],
      [{ id: "park", name: "Park shade" }],
    );
  });

  test("changes its nodes, name, color and set, and a set it leaves empty goes", () => {
    mockFlow.scenarios = [EXISTING];
    mockFlow.scenarioSets = [{ id: "park", name: "Park shade" }];
    renderPanel({ mode: "edit", scenarioId: "e" });
    select("towers");
    addTo("Scenario-specific nodes");
    click("Next: shared context & outcomes");
    click("Next: name & set");
    expect(screen.getByTestId("scenario-define-name")).toHaveValue("Existing");
    expect(screen.getByTestId("scenario-define-color")).toHaveValue(EXISTING.color);
    fireEvent.change(screen.getByTestId("scenario-define-color"), { target: { value: "#123456" } });
    expect(screen.getByRole("radio", { name: /Park shade/ })).toBeChecked();
    fireEvent.change(screen.getByTestId("scenario-define-name"), { target: { value: "Both" } });
    fireEvent.click(screen.getByRole("radio", { name: /Create a new scenario set/ }));
    fireEvent.click(screen.getByTestId("scenario-define-save"));
    const [scenarios, sets] = mockFlow.setScenarios.mock.calls[0];
    expect(sets).toHaveLength(1);
    // The dataflow's name is taken by the set it leaves, so the new one is told apart.
    expect(sets[0]).toEqual(expect.objectContaining({ name: "Park shade 2" }));
    expect(sets[0].id).not.toBe("park");
    expect(scenarios).toEqual([
      expect.objectContaining({ id: "e", color: "#123456", name: "Both", nodes: ["existing", "towers"], set: sets[0].id }),
    ]);
  });

  test("its own name is fine; a sibling's is not", () => {
    mockFlow.scenarios = [EXISTING, TOWERS];
    mockFlow.scenarioSets = [{ id: "park", name: "Park shade" }];
    renderPanel({ mode: "edit", scenarioId: "e" });
    click("Next: shared context & outcomes");
    click("Next: name & set");
    expect(screen.queryByRole("alert")).toBeNull();
    fireEvent.change(screen.getByTestId("scenario-define-name"), { target: { value: "towers" } });
    expect(screen.getByRole("alert")).toHaveTextContent('"Towers" is already a scenario in "Park shade".');
    expect(screen.getByTestId("scenario-define-save")).toBeDisabled();
  });
});
