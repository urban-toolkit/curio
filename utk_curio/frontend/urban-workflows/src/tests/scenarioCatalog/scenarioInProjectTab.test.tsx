/**
 * The Scenario Catalog drawer's In project tab: this dataflow's scenarios, read
 * off the canvas, so an unsaved one shows too, with what the Scenarios panel
 * offered. Each card runs, collapses or expands its scenario, adds or removes
 * the selected nodes and deletes it; pointing at a card marks its fixed context
 * on the canvas; its details edit its name, color and description and list its
 * fixed context, levers and outcomes. A shared viewer reads them and changes
 * nothing.
 *
 * The actions themselves are `useScenarioActions`'s, mocked here: what is under
 * test is that each control reaches its own. That the scenario commands open
 * the drawer on this tab is `scenarioActionsOpenInProject.test.tsx`.
 */
import React from "react";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import "@testing-library/jest-dom";
import { MemoryRouter } from "react-router-dom";

import { ScenarioCatalogDrawer } from "../../components/scenarios/catalog/ScenarioCatalogDrawer";
import * as scenarioUi from "../../components/scenarios/scenarioUi";
import {
  ScenarioCatalogDrawerProvider,
  useScenarioCatalogDrawer,
} from "../../providers/scenarioCatalog";
import { scenarioCatalogApi } from "../../services/scenarioCatalog/scenarioCatalogApi";
import { heatScenario } from "../_support/scenarioRows";

// The node labels reach the node registry, whose built-in behaviors load
// Vega's ESM build: mocked virtually, as testing-gotchas prescribes.
jest.mock("vega", () => ({}), { virtual: true });
jest.mock("vega-lite", () => ({}), { virtual: true });

jest.mock("../../services/scenarioCatalog/scenarioCatalogApi", () => ({
  scenarioCatalogApi: { listCatalog: jest.fn(), getScenario: jest.fn() },
}));

const mockFlow: Record<string, any> = {};
jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => mockFlow,
}));

const mockActions = {
  saveSelectionAsScenario: jest.fn(),
  saveDataflowAsScenario: jest.fn(),
  duplicate: jest.fn(),
  runScenario: jest.fn(),
  update: jest.fn(),
  setCollapsed: jest.fn(),
  moveBox: jest.fn(),
  addSelected: jest.fn(),
  removeSelected: jest.fn(),
  remove: jest.fn(),
};
jest.mock("../../components/scenarios/useScenarioActions", () => ({
  useScenarioActions: () => mockActions,
}));

const mockView = { shared: false };
jest.mock("../../hook/useSharedView", () => ({
  useSharedView: () => mockView.shared,
}));

const api = scenarioCatalogApi as unknown as { listCatalog: jest.Mock; getScenario: jest.Mock };

// Read through the module so that a name main lacks fails its test, not the
// whole suite.
const ScenarioUiProvider = (scenarioUi as any).ScenarioUiProvider as React.FC<{ children: React.ReactNode }>;

/** A loader feeds a scale step, which feeds a chart. */
function liveNode(id: string, nodeType: string, title: string, x: number) {
  return {
    id,
    type: "universal",
    position: { x, y: 0 },
    width: 525,
    height: 350,
    data: { nodeType, title },
  };
}
const NODES = [
  liveNode("load", "curio.builtin/data-loading@1", "Load parcels", 0),
  liveNode("scale", "curio.builtin/computation-analysis@1", "Scale heights", 645),
  liveNode("chart", "curio.builtin/vis-vega@1", "Height chart", 1290),
];
const EDGES = [
  { id: "e1", source: "load", target: "scale", sourceHandle: "out", targetHandle: "in" },
  { id: "e2", source: "scale", target: "chart", sourceHandle: "out", targetHandle: "in" },
];

/** Never saved: the catalog's listing has neither. "Gone" lost its node. */
const DOUBLED = { id: "s-doubled", name: "Doubled", color: "#e86a3c", description: "Every height twice.", nodes: ["scale"] };
const CHARTED = { id: "s-charted", name: "Charted", color: "#3567c7", nodes: ["chart"], collapsed: true };
const GONE = { id: "s-gone", name: "Gone", color: "#2f8f4a", nodes: ["deleted-node"] };

const DRAWER = '[data-curio-scenario-catalog-drawer="true"]';

function resetFlow() {
  for (const key of Object.keys(mockFlow)) delete mockFlow[key];
  Object.assign(mockFlow, {
    projectDirty: true,
    projectId: null,
    scenarios: [DOUBLED, CHARTED],
    nodes: NODES,
    edges: EDGES,
    notebookOn: false,
    workflowNameRef: { current: "Heights" },
  });
}

/** What the canvas marks: the scenario whose fixed context is outlined. */
const HighlightProbe: React.FC = () => {
  const { highlighted } = scenarioUi.useScenarioUi();
  return <output data-testid="highlighted">{highlighted ?? ""}</output>;
};
const highlighted = () => screen.getByTestId("highlighted").textContent;

function renderDrawer(presented = true) {
  const tree = (open: boolean) => (
    <MemoryRouter initialEntries={["/dataflow/p-current"]}>
      <ScenarioUiProvider>
        <ScenarioCatalogDrawer presented={open} onRequestClose={jest.fn()} onExitComplete={jest.fn()} />
        <HighlightProbe />
      </ScenarioUiProvider>
    </MemoryRouter>
  );
  const utils = render(tree(presented));
  return { ...utils, setPresented: (open: boolean) => utils.rerender(tree(open)) };
}

const root = () => document.querySelector(DRAWER) as HTMLElement;
function tab(name: "Browse all" | "In project"): HTMLElement {
  return within(root()).getByRole("button", { name: new RegExp(`^${name}`) });
}
function card(id: string): HTMLElement {
  const el = root().querySelector(`[data-testid="scenario-card-${id}"]`);
  if (!el) throw new Error(`no In project card for ${id}`);
  return el as HTMLElement;
}
const button = (id: string, name: string) => within(card(id)).getByRole("button", { name });

async function openInProject() {
  renderDrawer();
  fireEvent.click(tab("In project"));
  await waitFor(() => expect(root().querySelector('[data-testid="scenario-card-s-doubled"]')).not.toBeNull());
}

beforeEach(() => {
  jest.clearAllMocks();
  resetFlow();
  mockView.shared = false;
  // The account's catalog lists another project's scenario only: the two of
  // this dataflow were never saved.
  api.listCatalog.mockResolvedValue({ items: [heatScenario()] });
  api.getScenario.mockResolvedValue(null);
});

describe("the Scenario Catalog drawer's In project tab", () => {
  test("the drawer has Browse all and In project, which counts this dataflow's scenarios", async () => {
    renderDrawer();
    expect(await within(root()).findByText("Cool roofs")).toBeInTheDocument();
    expect(tab("Browse all")).toHaveAttribute("aria-pressed", "true");
    expect(tab("In project")).toHaveAttribute("aria-pressed", "false");
    expect(tab("In project")).toHaveTextContent(/^In project2$/);
  });

  test("In project lists this dataflow's scenarios from the canvas, unsaved ones too", async () => {
    await openInProject();
    expect(tab("In project")).toHaveAttribute("aria-pressed", "true");
    expect(within(card("s-doubled")).getByText("Doubled")).toBeInTheDocument();
    expect(within(card("s-doubled")).getByText("Heights · 1 node")).toBeInTheDocument();
    expect(within(card("s-doubled")).getByText("Every height twice.")).toBeInTheDocument();
    expect(within(card("s-charted")).getByText("Charted")).toBeInTheDocument();
    // Browse all's listing is not In project's: its card is not here.
    expect(within(root()).queryByText("Cool roofs")).toBeNull();
    // Nothing of them is asked of the server.
    expect(api.getScenario).not.toHaveBeenCalled();
  });

  test("each card's buttons call their action on its scenario", async () => {
    await openInProject();
    fireEvent.click(button("s-doubled", "Run scenario"));
    expect(mockActions.runScenario).toHaveBeenCalledWith("s-doubled");
    fireEvent.click(button("s-doubled", "Collapse"));
    expect(mockActions.setCollapsed).toHaveBeenCalledWith("s-doubled", true);
    fireEvent.click(button("s-doubled", "Add selected"));
    expect(mockActions.addSelected).toHaveBeenCalledWith("s-doubled");
    fireEvent.click(button("s-doubled", "Remove selected"));
    expect(mockActions.removeSelected).toHaveBeenCalledWith("s-doubled");
    fireEvent.click(button("s-doubled", "Delete"));
    expect(mockActions.remove).toHaveBeenCalledWith("s-doubled");
    // Each acted on its own scenario only.
    expect(mockActions.setCollapsed).toHaveBeenCalledTimes(1);
  });

  test("a collapsed scenario's card offers Expand", async () => {
    await openInProject();
    expect(within(card("s-charted")).queryByRole("button", { name: "Collapse" })).toBeNull();
    fireEvent.click(button("s-charted", "Expand"));
    expect(mockActions.setCollapsed).toHaveBeenCalledWith("s-charted", false);
  });

  test("a scenario with no node left can neither run nor collapse", async () => {
    mockFlow.scenarios = [DOUBLED, CHARTED, GONE];
    await openInProject();
    expect(tab("In project")).toHaveTextContent(/^In project3$/);
    expect(within(card("s-gone")).getByText("Heights · 0 nodes")).toBeInTheDocument();
    expect(button("s-gone", "Run scenario")).toBeDisabled();
    expect(button("s-gone", "Collapse")).toBeDisabled();
    expect(button("s-gone", "Add selected")).toBeEnabled();
    expect(button("s-gone", "Delete")).toBeEnabled();
  });

  test("on top of the tab, Define scenario and Duplicate as scenario", async () => {
    await openInProject();
    fireEvent.click(within(root()).getByRole("button", { name: "Define scenario" }));
    expect(mockActions.saveSelectionAsScenario).toHaveBeenCalledTimes(1);
    fireEvent.click(within(root()).getByRole("button", { name: "Duplicate as scenario" }));
    expect(mockActions.duplicate).toHaveBeenCalledWith(true);
  });

  test("Duplicate as scenario is off in the notebook view, where nodes are not added", async () => {
    mockFlow.notebookOn = true;
    await openInProject();
    expect(within(root()).getByRole("button", { name: "Duplicate as scenario" })).toBeDisabled();
    expect(within(root()).getByRole("button", { name: "Define scenario" })).toBeEnabled();
  });

  test("a shared viewer reads the scenarios and finds no editing control", async () => {
    mockView.shared = true;
    await openInProject();
    expect(within(card("s-doubled")).getByText("Doubled")).toBeInTheDocument();
    for (const name of ["Run scenario", "Collapse", "Expand", "Add selected", "Remove selected", "Delete"]) {
      expect(within(root()).queryByRole("button", { name })).toBeNull();
    }
    expect(within(root()).queryByRole("button", { name: "Define scenario" })).toBeNull();
    expect(within(root()).queryByRole("button", { name: "Duplicate as scenario" })).toBeNull();
  });

  test("pointing at a card marks its fixed context on the canvas, and leaving it clears the mark", async () => {
    await openInProject();
    expect(highlighted()).toBe("");
    fireEvent.mouseEnter(card("s-doubled"));
    expect(highlighted()).toBe("s-doubled");
    fireEvent.mouseLeave(card("s-doubled"));
    expect(highlighted()).toBe("");
  });

  test("the mark goes when the tab changes, the drawer closes, or its scenario is deleted", async () => {
    const { setPresented } = renderDrawer();
    fireEvent.click(tab("In project"));
    await waitFor(() => expect(root().querySelector('[data-testid="scenario-card-s-doubled"]')).not.toBeNull());

    // A card that goes away under the pointer never sees it leave.
    fireEvent.mouseEnter(card("s-doubled"));
    fireEvent.click(tab("Browse all"));
    expect(highlighted()).toBe("");

    fireEvent.click(tab("In project"));
    fireEvent.mouseEnter(card("s-doubled"));
    setPresented(false);
    expect(highlighted()).toBe("");

    setPresented(true);
    fireEvent.mouseEnter(card("s-doubled"));
    fireEvent.click(button("s-doubled", "Delete"));
    expect(highlighted()).toBe("");
  });

  test("the search narrows In project too", async () => {
    await openInProject();
    fireEvent.change(within(root()).getByPlaceholderText("Search scenarios, projects…"), {
      target: { value: "char" },
    });
    await waitFor(() => expect(root().querySelector('[data-testid="scenario-card-s-doubled"]')).toBeNull());
    expect(card("s-charted")).toBeInTheDocument();
    // A description matches as well.
    fireEvent.change(within(root()).getByPlaceholderText("Search scenarios, projects…"), {
      target: { value: "twice" },
    });
    await waitFor(() => expect(root().querySelector('[data-testid="scenario-card-s-charted"]')).toBeNull());
    expect(card("s-doubled")).toBeInTheDocument();
  });

  test("a dataflow with no scenario says how to make one", async () => {
    mockFlow.scenarios = [];
    renderDrawer();
    expect(tab("In project")).toHaveTextContent(/^In project$/);
    fireEvent.click(tab("In project"));
    expect(
      await within(root()).findByText(
        "This dataflow has no scenarios yet. Select nodes (Shift and drag) and save them as a scenario, or duplicate them as one to compare two versions.",
      ),
    ).toBeInTheDocument();
  });

  test("View details shows its name, color and description, and its three lists read off the canvas", async () => {
    await openInProject();
    fireEvent.click(within(card("s-doubled")).getByRole("button", { name: "View Doubled (Heights) details" }));
    const modal = within(await screen.findByRole("dialog", { name: "Scenario details" }));
    expect(modal.getByRole("heading", { name: "Doubled" })).toBeInTheDocument();
    expect(modal.getByLabelText("Scenario name")).toHaveValue("Doubled");
    expect(modal.getByLabelText("Color of Doubled")).toHaveValue("#e86a3c");
    expect(modal.getByLabelText("Scenario description")).toHaveValue("Every height twice.");
    const region = (name: string) => within(modal.getByRole("region", { name }));
    expect(region("Shared context").getByText("Load parcels")).toBeInTheDocument();
    expect(region("Scenario nodes").getByText("Scale heights")).toBeInTheDocument();
    expect(region("Outcomes").getByText("Scale heights")).toBeInTheDocument();
    // Read off the canvas: no saved-output lines, and no request.
    expect(modal.queryByText("No saved output")).toBeNull();
    expect(api.getScenario).not.toHaveBeenCalled();
    // This dataflow is the one open: there is no other project to go to.
    expect(modal.queryByRole("button", { name: "Open source project" })).toBeNull();
  });

  test("the details edit the name, the color and the description", async () => {
    await openInProject();
    fireEvent.click(within(card("s-doubled")).getByRole("button", { name: "View Doubled (Heights) details" }));
    const modal = within(await screen.findByRole("dialog", { name: "Scenario details" }));

    const name = modal.getByLabelText("Scenario name");
    fireEvent.change(name, { target: { value: "Tripled" } });
    fireEvent.keyDown(name, { key: "Enter" });
    expect(mockActions.update).toHaveBeenCalledWith("s-doubled", { name: "Tripled" });

    fireEvent.change(modal.getByLabelText("Color of Doubled"), { target: { value: "#123456" } });
    expect(mockActions.update).toHaveBeenCalledWith("s-doubled", { color: "#123456" });

    const description = modal.getByLabelText("Scenario description");
    fireEvent.change(description, { target: { value: "Three times." } });
    fireEvent.blur(description);
    expect(mockActions.update).toHaveBeenCalledWith("s-doubled", { description: "Three times." });

    // An empty name is not a name: the field goes back to the scenario's.
    mockActions.update.mockClear();
    fireEvent.change(name, { target: { value: "  " } });
    fireEvent.blur(name);
    expect(mockActions.update).not.toHaveBeenCalled();
    expect(name).toHaveValue("Doubled");
  });

  test("a scenario with no node left says so in its details", async () => {
    mockFlow.scenarios = [GONE];
    renderDrawer();
    fireEvent.click(tab("In project"));
    fireEvent.click(await within(root()).findByRole("button", { name: "View Gone (Heights) details" }));
    const modal = within(await screen.findByRole("dialog", { name: "Scenario details" }));
    expect(within(modal.getByRole("region", { name: "Scenario nodes" })).getByText("No nodes: add some, or delete it.")).toBeInTheDocument();
  });

  test("a shared viewer's details only read", async () => {
    mockView.shared = true;
    await openInProject();
    fireEvent.click(within(card("s-doubled")).getByRole("button", { name: "View Doubled (Heights) details" }));
    const modal = within(await screen.findByRole("dialog", { name: "Scenario details" }));
    expect(modal.getByRole("heading", { name: "Doubled" })).toBeInTheDocument();
    expect(modal.getByText("Every height twice.")).toBeInTheDocument();
    expect(modal.queryByLabelText("Scenario name")).toBeNull();
    expect(modal.queryByLabelText("Color of Doubled")).toBeNull();
    expect(modal.queryByLabelText("Scenario description")).toBeNull();
    expect(within(modal.getByRole("region", { name: "Shared context" })).getByText("Load parcels")).toBeInTheDocument();
  });

  test("opened on In project, the drawer shows that tab; opened from the bar, Browse all", async () => {
    const Opener: React.FC = () => {
      const { openScenarioCatalogDrawer, closeScenarioCatalogDrawer } = useScenarioCatalogDrawer();
      return (
        <>
          <button onClick={() => (openScenarioCatalogDrawer as any)({ tab: "installed" })}>open on in project</button>
          <button onClick={() => openScenarioCatalogDrawer()}>open from the bar</button>
          <button onClick={closeScenarioCatalogDrawer}>close</button>
        </>
      );
    };
    render(
      <MemoryRouter>
        <ScenarioUiProvider>
          <ScenarioCatalogDrawerProvider>
            <Opener />
          </ScenarioCatalogDrawerProvider>
        </ScenarioUiProvider>
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByRole("button", { name: "open on in project" }));
    await waitFor(() => expect(root()).toHaveAttribute("aria-hidden", "false"));
    expect(tab("In project")).toHaveAttribute("aria-pressed", "true");
    expect(card("s-doubled")).toBeInTheDocument();

    // Asked again while open, it stays open on that tab: no second slide in.
    fireEvent.click(tab("Browse all"));
    fireEvent.click(screen.getByRole("button", { name: "open on in project" }));
    expect(root()).toHaveAttribute("aria-hidden", "false");
    expect(tab("In project")).toHaveAttribute("aria-pressed", "true");

    fireEvent.click(screen.getByRole("button", { name: "close" }));
    fireEvent.transitionEnd(root().querySelector("aside") as Element, { propertyName: "transform" });
    await waitFor(() => expect(document.querySelector(DRAWER)).toBeNull());
    fireEvent.click(screen.getByRole("button", { name: "open from the bar" }));
    await waitFor(() => expect(root()).toHaveAttribute("aria-hidden", "false"));
    expect(tab("Browse all")).toHaveAttribute("aria-pressed", "true");
    await act(async () => {});
  });
});
