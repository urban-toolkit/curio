/**
 * Save, from the File menu or the save status button, goes through the save
 * queue (`requestProjectSave`) like every other save of the open dataflow, so
 * it never goes out beside the pin's save, the autosave or an install save
 * (#909, #941). Everything else about it stays: it waits for its save, says
 * why one failed, and moves a new dataflow to its own address.
 *
 * The bar's children that need providers of their own are stubbed; what is
 * left is UpMenu's own code and its menus.
 */
import React from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";

jest.mock("vega", () => ({}), { virtual: true });
jest.mock("vega-lite", () => ({}), { virtual: true });

let mockFlow: any = {};
const mockShowToast = jest.fn();

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
  useToastContext: () => ({ showToast: mockShowToast }),
}));
jest.mock("../../providers/UserProvider", () => ({
  useUserContext: () => ({ skipProjectPage: false }),
}));
jest.mock("../../providers/CollaborationProvider", () => ({
  useCollab: () => ({ enabled: false, panelOpen: false, setPanelOpen: jest.fn(), connected: false, users: [] }),
}));
jest.mock("../../hook/useSharedView", () => ({ useSharedView: () => false }));
jest.mock("../../components/layout/GlobalPageHeader", () => ({
  GlobalPageHeader: ({ children }: any) => <header>{children}</header>,
}));
jest.mock("../../components/menus", () => ({
  LibraryManagerWindow: () => null,
  TrillProvenanceWindow: () => null,
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

function flow(over: Record<string, unknown> = {}) {
  return {
    workflowNameRef: { current: "Chicago trips" },
    projectId: "p1",
    projectName: "Chicago trips",
    projectDirty: false,
    projectSavedAt: new Date(0),
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
    // Both ways to save are offered, so a Save that skips the queue shows.
    requestProjectSave: jest.fn().mockResolvedValue({ id: "p1" }),
    saveCurrentProject: jest.fn().mockResolvedValue(undefined),
    ...over,
  };
}

function Where() {
  return <output data-testid="where">{useLocation().pathname}</output>;
}

function renderMenu(at = "/dataflow/p1") {
  return render(
    <MemoryRouter initialEntries={[at]}>
      <UpMenu />
      <Where />
    </MemoryRouter>,
  );
}

/** The control the e2e `_save` helper clicks and reads. */
function saveStatus(): HTMLElement {
  const status = document.querySelector<HTMLElement>("[data-curio-save-state]");
  expect(status).not.toBeNull();
  return status!;
}

let errorSpy: jest.SpyInstance;

beforeEach(() => {
  jest.clearAllMocks();
  mockFlow = flow();
  errorSpy = jest.spyOn(console, "error").mockImplementation(() => {});
});

afterEach(() => {
  errorSpy.mockRestore();
});

describe("Save", () => {
  test("the save status button saves through the queue, and reads saving until it answers", async () => {
    let answer!: (detail: unknown) => void;
    mockFlow.requestProjectSave.mockImplementationOnce(
      () => new Promise((resolve) => { answer = resolve; }),
    );
    renderMenu();

    await act(async () => { fireEvent.click(saveStatus()); });

    expect(mockFlow.requestProjectSave).toHaveBeenCalledTimes(1);
    expect(mockFlow.requestProjectSave).toHaveBeenCalledWith();
    expect(mockFlow.saveCurrentProject).not.toHaveBeenCalled();
    // The state the e2e `_save` helper waits on: saving while the queued save
    // is out, saved once it has answered.
    expect(saveStatus().getAttribute("data-curio-save-state")).toBe("saving");

    await act(async () => { answer({ id: "p1" }); });

    expect(saveStatus().getAttribute("data-curio-save-state")).toBe("saved");
  });

  test("File, Save dataflow takes the same queue", async () => {
    renderMenu();

    fireEvent.click(screen.getByTestId("file-menu-btn"));
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Save dataflow" }));
    });

    expect(mockFlow.requestProjectSave).toHaveBeenCalledTimes(1);
    expect(mockFlow.saveCurrentProject).not.toHaveBeenCalled();
  });

  test("a save the queue could not make says why", async () => {
    mockFlow = flow({
      projectDirty: true,
      requestProjectSave: jest.fn().mockRejectedValue(new Error("The server is not answering.")),
    });
    renderMenu();

    await act(async () => { fireEvent.click(saveStatus()); });

    expect(mockFlow.requestProjectSave).toHaveBeenCalledTimes(1);
    expect(mockShowToast).toHaveBeenCalledWith("The server is not answering.", "error");
    expect(saveStatus().getAttribute("data-curio-save-state")).toBe("unsaved");
  });

  test("the first save of a new dataflow moves it to its own address", async () => {
    mockFlow = flow({
      projectId: null,
      projectSavedAt: null,
      requestProjectSave: jest.fn().mockResolvedValue({ id: "p9" }),
    });
    renderMenu("/dataflow/new");

    await act(async () => { fireEvent.click(saveStatus()); });

    expect(mockFlow.requestProjectSave).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("where").textContent).toBe("/dataflow/p9");
  });
});
