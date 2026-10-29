/**
 * Save, from the File menu or the save status button, is File > Save
 * (`saveDataflow`): it makes a dataflow not saved yet, and gives a saved one a
 * version named Saved. It waits for its answer, says why one failed, and
 * moves a new dataflow to its own address.
 *
 * The status reads, on a dataflow bound to its doc, Saved once the server has
 * every change, Saving... once a change has waited a moment, and Offline while
 * the tab cannot reach the server; on a canvas bound to no doc, Unsaved while
 * it holds changes no one keeps.
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
let mockConnected = true;
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
  useCollab: () => ({ connected: mockConnected, users: [] }),
}));
jest.mock("../../hook/useSharedView", () => ({ useSharedView: () => false }));
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
import { SAVING_SHOWN_AFTER_MS } from "../../providers/flow/useSaveState";

function flow(over: Record<string, unknown> = {}) {
  return {
    workflowNameRef: { current: "Chicago trips" },
    projectId: "p1",
    projectName: "Chicago trips",
    projectDirty: false,
    projectSavedAt: new Date(0),
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
    saveDataflow: jest.fn().mockResolvedValue({ id: "p1", created: false }),
    ...over,
  };
}

/**
 * The doc a canvas is bound to, as the status reads it: whether the server
 * has every change this tab made, a wait for it, and the doc's updates.
 */
function boundDoc() {
  const listeners = new Set<(update: Uint8Array, origin: unknown) => void>();
  let kept = true;
  let waiters: Array<(kept: boolean) => void> = [];
  const provider: any = {
    doc: {
      on: (_event: string, listener: any) => listeners.add(listener),
      off: (_event: string, listener: any) => listeners.delete(listener),
    },
    isKept: () => kept,
    whenKept: () => (kept ? Promise.resolve(true) : new Promise<boolean>((resolve) => waiters.push(resolve))),
  };
  return {
    provider,
    /** A change this tab made, on its way to the server. */
    change() {
      kept = false;
      listeners.forEach((listener) => listener(new Uint8Array(), "canvas"));
    },
    /** The server has every change. */
    keep() {
      kept = true;
      const answered = waiters;
      waiters = [];
      answered.forEach((resolve) => resolve(true));
    },
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

/** The control the e2e helpers click and read. */
function saveStatus(): HTMLElement {
  const status = document.querySelector<HTMLElement>("[data-curio-save-state]");
  expect(status).not.toBeNull();
  return status!;
}

const state = () => saveStatus().getAttribute("data-curio-save-state");
const pending = () => saveStatus().getAttribute("data-curio-changes-pending");

let errorSpy: jest.SpyInstance;

beforeEach(() => {
  jest.clearAllMocks();
  mockFlow = flow();
  mockConnected = true;
  errorSpy = jest.spyOn(console, "error").mockImplementation(() => {});
});

afterEach(() => {
  errorSpy.mockRestore();
  jest.useRealTimers();
});

describe("Save", () => {
  test("the save status button is File > Save, and reads saving until it answers", async () => {
    let answer!: (saved: unknown) => void;
    mockFlow.saveDataflow.mockImplementationOnce(
      () => new Promise((resolve) => { answer = resolve; }),
    );
    renderMenu();

    await act(async () => { fireEvent.click(saveStatus()); });

    expect(mockFlow.saveDataflow).toHaveBeenCalledTimes(1);
    expect(mockFlow.saveDataflow).toHaveBeenCalledWith();
    expect(state()).toBe("saving");

    await act(async () => { answer({ id: "p1", created: false }); });

    expect(state()).toBe("saved");
    // A saved dataflow stays where it is.
    expect(screen.getByTestId("where").textContent).toBe("/dataflow/p1");
  });

  test("File, Save dataflow does the same", async () => {
    renderMenu();

    fireEvent.click(screen.getByTestId("file-menu-btn"));
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Save dataflow" }));
    });

    expect(mockFlow.saveDataflow).toHaveBeenCalledTimes(1);
  });

  test("a save that could not be made says why", async () => {
    mockFlow = flow({
      projectDirty: true,
      saveDataflow: jest.fn().mockRejectedValue(new Error("The server is not answering.")),
    });
    renderMenu();

    await act(async () => { fireEvent.click(saveStatus()); });

    expect(mockFlow.saveDataflow).toHaveBeenCalledTimes(1);
    expect(mockShowToast).toHaveBeenCalledWith("The server is not answering.", "error");
    expect(state()).toBe("unsaved");
  });

  test("the first save of a new dataflow moves it to its own address", async () => {
    mockFlow = flow({
      projectId: null,
      projectSavedAt: null,
      saveDataflow: jest.fn().mockResolvedValue({ id: "p9", created: true }),
    });
    renderMenu("/dataflow/new");

    await act(async () => { fireEvent.click(saveStatus()); });

    expect(mockFlow.saveDataflow).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("where").textContent).toBe("/dataflow/p9");
  });
});

describe("the save status of a dataflow bound to its doc", () => {
  test("reads Saved while the server has every change, though no save was made", () => {
    const doc = boundDoc();
    mockFlow = flow({ boundDoc: doc.provider, projectSavedAt: null });
    renderMenu();

    expect(state()).toBe("saved");
    expect(pending()).toBe("false");
  });

  test("reads Saving... once a change has waited a moment, and Saved once the server has it", async () => {
    jest.useFakeTimers();
    const doc = boundDoc();
    mockFlow = flow({ boundDoc: doc.provider });
    renderMenu();

    act(() => { doc.change(); });
    // A change the server keeps at once never makes the bar flicker.
    expect(state()).toBe("saved");
    expect(pending()).toBe("true");

    act(() => { jest.advanceTimersByTime(SAVING_SHOWN_AFTER_MS); });
    expect(state()).toBe("saving");
    expect(saveStatus().textContent).toBe("Saving...");

    await act(async () => { doc.keep(); });
    expect(state()).toBe("saved");
    expect(pending()).toBe("false");
    expect(saveStatus().textContent).toBe("Saved");
  });

  test("reads Offline while the tab cannot reach the server and a change waits", () => {
    jest.useFakeTimers();
    mockConnected = false;
    const doc = boundDoc();
    mockFlow = flow({ boundDoc: doc.provider });
    renderMenu();

    act(() => { doc.change(); });
    act(() => { jest.advanceTimersByTime(SAVING_SHOWN_AFTER_MS); });

    expect(state()).toBe("offline");
    expect(saveStatus().textContent).toBe("Offline");
  });

  test("never reads Unsaved, whatever the canvas marked", () => {
    const doc = boundDoc();
    mockFlow = flow({ boundDoc: doc.provider, projectDirty: true });
    renderMenu();

    expect(state()).toBe("saved");
  });
});

describe("the save status of a canvas bound to no doc", () => {
  test("reads Unsaved while it holds changes no one keeps", () => {
    mockFlow = flow({ projectDirty: true });
    renderMenu();

    expect(state()).toBe("unsaved");
    expect(saveStatus().textContent).toBe("Unsaved");
  });

  test("reads Unsaved for a dataflow never saved", () => {
    mockFlow = flow({ projectId: null, projectSavedAt: null });
    renderMenu("/dataflow/new");

    expect(state()).toBe("unsaved");
  });
});
