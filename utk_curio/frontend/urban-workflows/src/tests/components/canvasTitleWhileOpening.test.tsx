/**
 * While the dataflow its link names is still opening, the canvas title says
 * so, from the canvas's first frame. Before, it read "DefaultDataflow", the
 * name of no dataflow, until the load landed. The name and the categories
 * cannot be changed meanwhile: the load puts the dataflow's own over them.
 *
 * A dataflow the canvas leaves while it opens (File > New, or File > Load with
 * its file) is opening no more: the title names the dataflow the canvas is on,
 * and the left one's answer, when it comes, puts nothing on the canvas. Before,
 * the title said "Opening dataflow…" until that answer came, and the answer
 * then put the left dataflow on the canvas under another route, whose runs
 * went to it (run 42191681614).
 *
 * UpMenu is drawn under the real ProjectLoader, whose load the test holds
 * until it lets it land; the bar's children that need providers of their own
 * are stubbed as in upMenuSave, and the categories say whether they take
 * changes.
 */
import React from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

jest.mock("vega", () => ({}), { virtual: true });
jest.mock("vega-lite", () => ({}), { virtual: true });

let mockFlow: any = {};
// The name the canvas holds: none until the load sets the dataflow's.
let mockWorkflowName = "DefaultDataflow";
const mockLoadTrill = jest.fn();

jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => mockFlow,
  useNodeActionsContext: () => ({
    workflowName: mockWorkflowName,
    setWorkflowName: jest.fn(),
    setAllMinimized: jest.fn(),
    allMinimized: 0,
    expandStatus: "expanded",
    setExpandStatus: jest.fn(),
  }),
}));
jest.mock("../../providers/ToastProvider", () => ({
  useToastContext: () => ({ showToast: jest.fn() }),
}));
jest.mock("../../providers/UserProvider", () => ({
  useUserContext: () => ({ skipProjectPage: false }),
}));
jest.mock("../../providers/CollaborationProvider", () => ({
  useCollab: () => ({ connected: true, users: [] }),
}));
jest.mock("../../providers/packages/useEnsureWorkflowDeps", () => ({ useEnsureWorkflowDeps: () => jest.fn() }));
jest.mock("../../hook/useSharedView", () => ({ useSharedView: () => false }));
jest.mock("../../hook/useCode", () => ({ useCode: () => ({ loadTrill: mockLoadTrill }) }));
jest.mock("../../components/layout/GlobalPageHeader", () => ({
  GlobalPageHeader: ({ children }: any) => <header>{children}</header>,
}));
jest.mock("../../components/menus", () => ({
  LibraryManagerWindow: () => null,
}));
jest.mock("../../components/menus/top/CatalogButtons", () => ({ CatalogButtons: () => null }));
jest.mock("../../components/menus/top/CanvasViewSwitch", () => ({ CanvasViewSwitch: () => null }));
jest.mock("../../components/menus/top/ShareMenu", () => ({ __esModule: true, default: () => null }));
// The categories, saying whether they take changes.
jest.mock("../../components/projects/DataflowCategoryInput", () => ({
  __esModule: true,
  default: ({ onChange }: any) => <span data-testid="categories" data-takes-changes={onChange ? "yes" : "no"} />,
}));
jest.mock("../../components/scenarios/useScenarioActions", () => ({
  useScenarioActions: () => ({
    saveSelectionAsScenario: jest.fn(),
    duplicate: jest.fn(),
  }),
}));
jest.mock("../../TrillGenerator", () => ({ TrillGenerator: { generateTrill: jest.fn(), reset: jest.fn() } }));
jest.mock("../../NotebookConvertor", () => ({ trillToNotebook: jest.fn(), serializeNotebook: jest.fn() }));
jest.mock("../../api/projectsApi", () => ({ projectsApi: { list: jest.fn().mockResolvedValue([]) } }));
jest.mock("../../services/packages", () => ({
  packagesApi: { getDefaults: jest.fn().mockResolvedValue({ packages: [] }) },
}));
jest.mock("../../registry/packageRegistryBootstrap", () => ({
  refreshPackageRegistry: jest.fn().mockResolvedValue(undefined),
}));
jest.mock("../../registry/projectPackagesStore", () => ({
  getCurrentProjectPackagesList: () => [],
  beginProjectLoad: jest.fn(),
  settleProjectLoad: jest.fn(),
  setCurrentProject: jest.fn(),
  setCurrentProjectPackages: jest.fn(),
  setUnsavedDataflow: jest.fn(),
  clearCurrentProject: jest.fn(),
}));

import UpMenu from "../../components/menus/top/UpMenu";
import { ProjectLoader, useProjectLoadState } from "../../components/ProjectLoader";
import { setUnsavedDataflow } from "../../registry/projectPackagesStore";

const ROUTED = "36363636-2222-4333-8444-000000000036";
const NAME = "Bus plan";
const LOADED = { spec: { dataflow: { name: NAME, nodes: [], edges: [] } }, outputs: [] };

/** The load state of each render, in order. */
let states: string[] = [];
function LoadStates() {
  states.push(useProjectLoadState());
  return null;
}

function heldLoad() {
  let land!: (result: unknown) => void;
  const promise = new Promise((resolve) => {
    land = resolve;
  });
  return { promise, land };
}

function renderCanvasBar() {
  return render(
    <MemoryRouter initialEntries={[`/dataflow/${ROUTED}`]}>
      <Routes>
        <Route
          path="/dataflow/:id?"
          element={
            <ProjectLoader>
              <LoadStates />
              <UpMenu />
            </ProjectLoader>
          }
        />
      </Routes>
    </MemoryRouter>,
  );
}

const title = () => screen.queryByRole("heading", { level: 1 })?.textContent ?? null;
const renaming = () => screen.queryByRole("textbox") !== null;
const categoriesTakeChanges = () => screen.getByTestId("categories").getAttribute("data-takes-changes");

let load: ReturnType<typeof heldLoad>;

beforeEach(() => {
  jest.clearAllMocks();
  states = [];
  mockWorkflowName = "DefaultDataflow";
  load = heldLoad();
  // The load sets the dataflow's name on the canvas, as loadParsedTrill does.
  mockLoadTrill.mockImplementation(() => {
    mockWorkflowName = NAME;
    return { nodes: [], edges: [] };
  });
  mockFlow = {
    workflowNameRef: { current: "DefaultDataflow" },
    projectId: null,
    projectName: "",
    projectDirty: false,
    projectSavedAt: null,
    boundDoc: null,
    whenChangesKept: jest.fn().mockResolvedValue(true),
    cleanCanvas: jest.fn(),
    renameDataflow: jest.fn(() => true),
    workflowCategories: {},
    serverCategories: {},
    scenarios: [],
    updateDataflowCategories: jest.fn(),
    saveAsNewProject: jest.fn(),
    discardProject: jest.fn(),
    packages: [],
    nodes: [],
    edges: [],
    canvasView: "canvas",
    setCanvasView: jest.fn(),
    autoRun: false,
    setAutoRun: jest.fn(),
    autoRunAvailable: false,
    saveDataflow: jest.fn(),
    viewerMode: "owner",
    loadProject: jest.fn(() => load.promise),
    loadSharedProject: jest.fn(),
    setOutputs: jest.fn(),
    hydrateRestoredOutputs: jest.fn(),
    attachLatestRun: jest.fn(),
    markDirty: jest.fn(),
    setWorkflowName: jest.fn(),
  };
});

test("the title says the dataflow is opening, from the first frame, then names it", async () => {
  renderCanvasBar();
  await waitFor(() => expect(mockFlow.loadProject).toHaveBeenCalled());
  const whileOpening = { firstFrame: states[0], title: title() };

  await act(async () => {
    load.land(LOADED);
  });
  await waitFor(() => expect(mockLoadTrill).toHaveBeenCalled());

  expect({ whileOpening, opened: title() }).toEqual({
    whileOpening: { firstFrame: "loading", title: "Opening dataflow…" },
    opened: NAME,
  });
});

test("the name and the categories wait for the dataflow, whose own the load puts over them", async () => {
  renderCanvasBar();
  await waitFor(() => expect(mockFlow.loadProject).toHaveBeenCalled());
  const heading = screen.queryByRole("heading", { level: 1 });
  if (heading) fireEvent.click(heading);
  const whileOpening = { renaming: renaming(), categories: categoriesTakeChanges() };

  await act(async () => {
    load.land(LOADED);
  });
  await waitFor(() => expect(mockLoadTrill).toHaveBeenCalled());
  const loaded = screen.queryByRole("heading", { level: 1 });
  if (loaded) fireEvent.click(loaded);

  expect({ whileOpening, opened: { renaming: renaming(), categories: categoriesTakeChanges() } }).toEqual({
    whileOpening: { renaming: false, categories: "no" },
    opened: { renaming: true, categories: "yes" },
  });
});

test("a dataflow left while it opens is opening no more, and its late answer puts nothing on the canvas", async () => {
  renderCanvasBar();
  await waitFor(() => expect(mockFlow.loadProject).toHaveBeenCalled());
  const whileOpening = title();

  // File > New while it opens, the way File > Load leaves it with its file.
  fireEvent.click(screen.getByTestId("file-menu-btn"));
  fireEvent.click(screen.getByRole("button", { name: "New dataflow" }));
  await waitFor(() => expect(setUnsavedDataflow).toHaveBeenCalled());
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
  const leftIt = title();

  // The left dataflow's answer comes after that.
  await act(async () => {
    load.land(LOADED);
    await new Promise((resolve) => setTimeout(resolve, 0));
  });

  expect({
    whileOpening,
    leftIt,
    answered: {
      title: title(),
      loadState: states[states.length - 1],
      putOnTheCanvas: mockLoadTrill.mock.calls.length,
      runsFollowed: mockFlow.attachLatestRun.mock.calls.length,
    },
  }).toEqual({
    whileOpening: "Opening dataflow…",
    leftIt: "DefaultDataflow",
    answered: { title: "DefaultDataflow", loadState: "idle", putOnTheCanvas: 0, runsFollowed: 0 },
  });
});
