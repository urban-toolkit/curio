/**
 * Drawers stack over Define scenario. A header drawer (a node's provenance)
 * or a catalog drawer (the Scenario Catalog) opened while Define is open
 * slides in over it, and one Escape closes only the drawer on top: each
 * drawer answers Escape only while it is the top layer (`isTopDrawer`), the
 * last open drawer in document order. Then Escape closes Define.
 *
 * Each drawer listens on `window`, so one Escape reaches every listener in
 * turn. In a browser React commits the top drawer's close between one
 * listener and the next, so a listener that runs after it finds that drawer
 * closed. Define's runs after it once Define renders again while the drawer
 * is over it (a canvas selection, a change to the flow): HeaderDrawer adds
 * its listener again. So the drawer here closes as its provider closes it,
 * the close committed at once (`flushSync`), and both orders of the two
 * listeners are tried.
 *
 * The real Define panel, HeaderDrawer and Scenario Catalog drawer; the flow,
 * the canvas selection, the catalog's routes and the scenario commands are
 * mocked.
 */
import React, { useCallback, useState } from "react";
import { flushSync } from "react-dom";
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

type Over = "provenance" | "catalog";

/** The drawer over Define. It closes as its provider closes it: mounted
 *  still, no longer presented, and committed before the next listener of the
 *  Escape runs, as in a browser. Its close is the same on every render, as a
 *  provider's is, so its listener keeps its place. */
function OverDrawer({ kind }: { kind: Over }) {
  const [presented, setPresented] = useState(true);
  const close = useCallback(() => {
    closeOver();
    flushSync(() => setPresented(false));
  }, []);
  return kind === "provenance" ? (
    <HeaderDrawer
      presented={presented}
      onRequestClose={close}
      onExitComplete={jest.fn()}
      title="Node provenance"
      titleId="provenance-drawer-title"
      name="provenance"
      pinnable
      wide={false}
    >
      Runs of the node
    </HeaderDrawer>
  ) : (
    <ScenarioCatalogDrawer presented={presented} onRequestClose={close} onExitComplete={jest.fn()} />
  );
}

/** Define scenario, unless *define* is false, and over it the drawer *over*
 *  opens, or none. Define comes first in the page. */
function tree(over: Over | null, define = true) {
  return (
    <MemoryRouter initialEntries={["/dataflow/p-current"]}>
      <ScenarioUiContext.Provider value={UI}>
        {define && <ScenarioDefinePanel define={{ mode: "new" }} presented onExitComplete={jest.fn()} />}
        {over && <OverDrawer kind={over} />}
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
const openDrawers = () => Array.from(document.querySelectorAll("[data-curio-open-drawer]"));

describe.each([
  ["a header drawer", "provenance" as const],
  ["a catalog drawer", "catalog" as const],
])("Escape with %s over Define scenario", (_kind, over) => {
  test.each([
    // The drawer opened over Define, which has not rendered since.
    ["Define's listener runs first", false],
    // Define rendered again while the drawer is over it, so its listener now
    // runs after the drawer's: here Define opens after the drawer.
    ["the drawer's listener runs first", true],
  ])("closes the drawer on top alone, and then Define, when %s", (_order, drawerFirst) => {
    const { rerender } = render(tree(over, !drawerFirst));
    if (drawerFirst) rerender(tree(over));
    // Both are open, Define first in the page.
    const define = screen.getByRole("dialog", { name: "Define scenario" });
    expect(openDrawers()).toHaveLength(2);
    expect(openDrawers()[0]).toBe(define);
    escape();
    expect(closeOver).toHaveBeenCalledTimes(1);
    expect(setDefine).not.toHaveBeenCalled();
    expect(openDrawers()).toEqual([define]);

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
