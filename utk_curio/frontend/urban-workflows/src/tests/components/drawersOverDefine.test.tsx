/**
 * Drawers stack over Define scenario. A header drawer (a node's provenance)
 * or a catalog drawer (the Scenario Catalog) opened while Define is open
 * slides in over it, and one Escape closes only the drawer on top: each
 * drawer answers Escape only while it is the top layer (`isTopDrawer`), the
 * last open drawer in document order. Then Escape closes Define.
 *
 * The real Define panel, HeaderDrawer and Scenario Catalog drawer; the flow,
 * the canvas selection, the catalog's routes and the scenario commands are
 * mocked.
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
jest.mock("../../components/scenarios/useScenarioActions", () => ({
  useScenarioActions: () => ({}),
}));
jest.mock("../../hook/useSharedView", () => ({ useSharedView: () => false }));
// The canvas selection, as React Flow's store holds it: none.
jest.mock("reactflow", () => ({
  ...jest.requireActual("reactflow"),
  useStore: (selector: (s: any) => unknown) => selector({ nodeInternals: new Map() }),
}));

import { HeaderDrawer } from "../../components/layout/HeaderDrawer";
import { ScenarioCatalogDrawer } from "../../components/scenarios/catalog/ScenarioCatalogDrawer";
import { ScenarioDefinePanel } from "../../components/scenarios/define/ScenarioDefinePanel";
import { ScenarioUiContext, type ScenarioUi } from "../../components/scenarios/scenarioUi";

const setDefine = jest.fn();
const UI: ScenarioUi = {
  highlighted: null,
  setHighlighted: jest.fn(),
  define: { mode: "new" },
  setDefine,
  preview: null,
  setPreview: jest.fn(),
};

const closeOver = jest.fn();

/** Define scenario, and over it the drawer *over* opens, or none. */
function tree(over: "provenance" | "catalog" | null) {
  return (
    <MemoryRouter initialEntries={["/dataflow/p-current"]}>
      <ScenarioUiContext.Provider value={UI}>
        <ScenarioDefinePanel define={{ mode: "new" }} presented onExitComplete={jest.fn()} />
        {over === "provenance" && (
          <HeaderDrawer
            presented
            onRequestClose={closeOver}
            onExitComplete={jest.fn()}
            title="Node provenance"
            titleId="provenance-drawer-title"
            name="provenance"
            pinnable
            wide={false}
          >
            Runs of the node
          </HeaderDrawer>
        )}
        {over === "catalog" && (
          <ScenarioCatalogDrawer presented onRequestClose={closeOver} onExitComplete={jest.fn()} />
        )}
      </ScenarioUiContext.Provider>
    </MemoryRouter>
  );
}

beforeEach(() => {
  jest.clearAllMocks();
  for (const key of Object.keys(mockFlow)) delete mockFlow[key];
  Object.assign(mockFlow, {
    projectDirty: false,
    projectId: "p-current",
    scenarios: [],
    scenarioSets: [],
    nodes: [],
    edges: [],
    notebookOn: false,
    setScenarios: jest.fn(),
    workflowNameRef: { current: "Heights" },
  });
});

const escape = () => fireEvent.keyDown(window, { key: "Escape" });

describe.each([
  ["a header drawer", "provenance" as const],
  ["a catalog drawer", "catalog" as const],
])("Escape with %s over Define scenario", (_kind, over) => {
  test("closes the drawer on top alone, and then Define", () => {
    const { rerender } = render(tree(over));
    // Both are open, Define first in the page.
    expect(screen.getByRole("dialog", { name: "Define scenario" })).toBeInTheDocument();
    escape();
    expect(closeOver).toHaveBeenCalledTimes(1);
    expect(setDefine).not.toHaveBeenCalled();

    // Its drawer gone, Define is the top layer, and Escape closes it.
    rerender(tree(null));
    escape();
    expect(setDefine).toHaveBeenCalledWith(null);
    expect(closeOver).toHaveBeenCalledTimes(1);
  });

  test("its close button closes it alone", () => {
    render(tree(over));
    const name = over === "provenance" ? "Close Node provenance" : /^Close Scenario Catalog/;
    fireEvent.click(screen.getAllByRole("button", { name })[0]);
    expect(closeOver).toHaveBeenCalledTimes(1);
    expect(setDefine).not.toHaveBeenCalled();
  });
});

test("Define scenario has no scrim, sits at the catalog drawers' tier, and is not modal", () => {
  render(tree(null));
  const dialog = screen.getByRole("dialog", { name: "Define scenario" });
  expect(dialog).not.toHaveAttribute("aria-modal");
  expect(dialog).toHaveAttribute("data-testid", "scenario-define-panel");
  expect(screen.queryByRole("button", { name: "Dismiss Define scenario" })).toBeNull();
  const root = document.querySelector('[data-curio-scenario-define-drawer="true"]') as HTMLElement;
  expect(root.className).toContain("beside");
});
