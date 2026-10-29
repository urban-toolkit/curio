/**
 * A dataflow someone shares opens read-only, and File > Save dataflow saves a
 * copy of it to the visitor's projects (`handleSaveCopy`). The copy names the
 * dataflow it copies, so it gets that dataflow's saved outputs. A shared view
 * holds no project id (`loadSharedProject`), so the id is the one in the
 * route.
 *
 * The bar's children that need providers of their own are stubbed; what is
 * left is UpMenu's own code and its menus.
 */
import React from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";

jest.mock("vega", () => ({}), { virtual: true });
jest.mock("vega-lite", () => ({}), { virtual: true });

let mockFlow: any = {};

jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => mockFlow,
  useNodeActionsContext: () => ({
    workflowName: "Chicago trips",
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
  useCollab: () => ({ connected: false, users: [] }),
}));
jest.mock("../../hook/useSharedView", () => ({ useSharedView: () => true }));
jest.mock("../../components/layout/GlobalPageHeader", () => ({
  GlobalPageHeader: ({ children }: any) => <header>{children}</header>,
}));
jest.mock("../../components/menus", () => ({
  LibraryManagerWindow: () => null,
}));
jest.mock("../../components/menus/top/CatalogButtons", () => ({ CatalogButtons: () => null }));
jest.mock("../../components/menus/top/CanvasViewSwitch", () => ({ CanvasViewSwitch: () => null }));
jest.mock("../../components/menus/top/ShareMenu", () => ({ __esModule: true, default: () => null }));
jest.mock("../../components/projects/DataflowCategoryInput", () => ({ __esModule: true, default: () => null }));
jest.mock("../../components/scenarios/useScenarioActions", () => ({
  useScenarioActions: () => ({
    saveDataflowAsScenario: jest.fn(),
    saveSelectionAsScenario: jest.fn(),
    duplicate: jest.fn(),
  }),
}));
jest.mock("../../TrillGenerator", () => ({ TrillGenerator: { generateTrill: jest.fn() } }));
jest.mock("../../NotebookConvertor", () => ({ trillToNotebook: jest.fn(), serializeNotebook: jest.fn() }));
jest.mock("../../api/projectsApi", () => ({ projectsApi: { list: jest.fn().mockResolvedValue([]) } }));
jest.mock("../../registry/projectPackagesStore", () => ({ getCurrentProjectPackagesList: () => [] }));

import UpMenu from "../../components/menus/top/UpMenu";

const SHARED = "3f2b8c1e-5d4a-4c3b-9a2e-1f0e9d8c7b6a";

function sharedView() {
  return {
    workflowNameRef: { current: "Chicago trips" },
    projectId: null,
    projectName: "Chicago trips",
    projectDirty: false,
    projectSavedAt: null,
    viewerMode: "shared",
    cleanCanvas: jest.fn(),
    renameDataflow: jest.fn(() => true),
    workflowCategories: {},
    serverCategories: {},
    scenarios: [],
    updateDataflowCategories: jest.fn(),
    saveAsNewProject: jest.fn().mockResolvedValue({ id: "copy-1" }),
    discardProject: jest.fn(),
    packages: [],
    nodes: [],
    edges: [],
    canvasView: "canvas",
    setCanvasView: jest.fn(),
    autoRun: false,
    setAutoRun: jest.fn(),
    autoRunAvailable: false,
    requestProjectSave: jest.fn(),
    saveCurrentProject: jest.fn(),
  };
}

function Where() {
  return <output data-testid="where">{useLocation().pathname}</output>;
}

let errorSpy: jest.SpyInstance;

beforeEach(() => {
  jest.clearAllMocks();
  mockFlow = sharedView();
  errorSpy = jest.spyOn(console, "error").mockImplementation(() => {});
});

afterEach(() => {
  errorSpy.mockRestore();
});

test("saving a shared dataflow names it, by the id in its link, as the dataflow the copy copies", async () => {
  render(
    <MemoryRouter initialEntries={[`/dataflow/${SHARED}`]}>
      <Routes>
        <Route path="/dataflow/:id?" element={<><UpMenu /><Where /></>} />
      </Routes>
    </MemoryRouter>,
  );

  fireEvent.click(screen.getByTestId("file-menu-btn"));
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "Save dataflow" }));
  });

  expect(mockFlow.saveAsNewProject).toHaveBeenCalledTimes(1);
  expect(mockFlow.saveAsNewProject).toHaveBeenCalledWith("Chicago trips (copy)", SHARED);
  expect(mockFlow.requestProjectSave).not.toHaveBeenCalled();
  expect(screen.getByTestId("where").textContent).toBe("/dataflow/copy-1");
});

// The canvas title is cut short beside the agents' dock (UpMenu.module.css,
// canvasTitleBesideTheDock.test.ts), so its tooltip gives the whole name.
test("the canvas title's tooltip is its whole name", () => {
  render(
    <MemoryRouter initialEntries={[`/dataflow/${SHARED}`]}>
      <Routes>
        <Route path="/dataflow/:id?" element={<UpMenu />} />
      </Routes>
    </MemoryRouter>,
  );

  expect(screen.getByRole("heading", { level: 1, name: "Chicago trips" })).toHaveAttribute(
    "data-tooltip",
    "Chicago trips",
  );
});
