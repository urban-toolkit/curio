/**
 * File > Load opens the picked file as a dataflow of its own (#751).
 *
 * The file used to be loaded into the open dataflow, so the next save wrote its
 * nodes into that dataflow's project, under that project's name: the projects
 * page listed nothing under the file's name, and the dataflow that had been open
 * lost its own nodes. Now the menu leaves the open dataflow the way File > New
 * does, hands the file over (`utils/openedDataflowFile.ts`) and goes to
 * `/dataflow/new`, and ProjectLoader puts it on the canvas once that route is
 * set up, so its first save creates a project of its own.
 *
 * The order is what these tests pin: the route's setup resets the provenance
 * and the package scope, so the file goes on the canvas after it, and the
 * account defaults the setup asks for must not land on the file's lockfile.
 */
import React from "react";
import { act, render, waitFor } from "@testing-library/react";

const mockLoadProject = jest.fn();
const mockLoadSharedProject = jest.fn();
const mockLoadTrill = jest.fn();
const mockMarkDirty = jest.fn();
const mockEnsureWorkflowDeps = jest.fn();
const mockShowToast = jest.fn();
const mockGetDefaults = jest.fn();
const mockResetProvenance = jest.fn();
const mockSetUnsavedDataflow = jest.fn();
const mockSetCurrentProjectPackages = jest.fn();

let mockRouteId = "new";
let mockProjectId: string | null = null;

jest.mock("react-router-dom", () => ({
  useParams: () => ({ id: mockRouteId }),
  useNavigate: () => jest.fn(),
}));
jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({
    loadProject: mockLoadProject,
    loadSharedProject: mockLoadSharedProject,
    setOutputs: jest.fn(),
    hydrateRestoredOutputs: jest.fn(),
    loadParsedTrill: jest.fn(),
    projectId: mockProjectId,
    attachLatestRun: jest.fn(),
    markDirty: mockMarkDirty,
  }),
}));
jest.mock("../../hook/useCode", () => ({
  useCode: () => ({ loadTrill: mockLoadTrill }),
}));
jest.mock("../../providers/packages/useEnsureWorkflowDeps", () => ({
  useEnsureWorkflowDeps: () => mockEnsureWorkflowDeps,
}));
jest.mock("../../TrillGenerator", () => ({
  TrillGenerator: { reset: (...args: unknown[]) => mockResetProvenance(...args) },
}));
jest.mock("../../registry/packageRegistryBootstrap", () => ({
  refreshPackageRegistry: jest.fn().mockResolvedValue(undefined),
}));
jest.mock("../../providers/ToastProvider", () => ({
  useToastContext: () => ({ showToast: mockShowToast }),
}));
jest.mock("../../registry/projectPackagesStore", () => ({
  clearCurrentProject: jest.fn(),
  beginProjectLoad: jest.fn(),
  settleProjectLoad: jest.fn(),
  setCurrentProject: jest.fn(),
  setUnsavedDataflow: (...args: unknown[]) => mockSetUnsavedDataflow(...args),
  setCurrentProjectPackages: (...args: unknown[]) => mockSetCurrentProjectPackages(...args),
}));
jest.mock("../../services/packages", () => ({
  packagesApi: { getDefaults: (...args: unknown[]) => mockGetDefaults(...args) },
}));

import { ProjectLoader } from "../../components/ProjectLoader";
import { openDataflowFile, takeOpenedDataflowFile } from "../../utils/openedDataflowFile";

const SAVED_ID = "11111111-2222-3333-4444-555555555555";
const SAVED = {
  dataflow: { name: "Rainfall by district", nodes: [{ id: "rainfall-1" }], edges: [] },
};
const FILE = {
  dataflow: {
    name: "Tree canopy by block",
    nodes: [{ id: "canopy-1" }, { id: "canopy-2" }],
    edges: [],
    packages: ["acme.trees@1"],
  },
};
const SECOND_FILE = {
  dataflow: { name: "Bus stops by route", nodes: [{ id: "stops-1" }], edges: [] },
};

const loader = () => (
  <ProjectLoader>
    <div>canvas</div>
  </ProjectLoader>
);

beforeEach(() => {
  jest.clearAllMocks();
  // The hand-over is module state: nothing may carry over from another test.
  takeOpenedDataflowFile();
  mockRouteId = "new";
  mockProjectId = null;
  mockGetDefaults.mockResolvedValue({ packages: ["acme.defaults@1"] });
  mockLoadTrill.mockReturnValue({ nodes: [], edges: [] });
});

it("puts the picked file on the canvas after /dataflow/new is set up", async () => {
  openDataflowFile(FILE);
  render(loader());

  await waitFor(() => expect(mockLoadTrill).toHaveBeenCalledWith(FILE));
  const loaded = mockLoadTrill.mock.invocationCallOrder[0];
  // After the setup, which would otherwise reset what the load records.
  expect(mockResetProvenance.mock.invocationCallOrder[0]).toBeLessThan(loaded);
  expect(mockSetUnsavedDataflow.mock.invocationCallOrder[0]).toBeLessThan(loaded);
  // Nothing of it is on disk: it is unsaved, and its first save creates it.
  expect(mockMarkDirty).toHaveBeenCalledTimes(1);
  expect(mockMarkDirty.mock.invocationCallOrder[0]).toBeGreaterThan(loaded);
  expect(mockEnsureWorkflowDeps).toHaveBeenCalledWith(FILE);
  // The file brings its own lockfile; the account defaults do not land on it.
  expect(mockGetDefaults).not.toHaveBeenCalled();
  expect(mockSetCurrentProjectPackages).not.toHaveBeenCalled();
});

it("starts an empty new dataflow from the account defaults, with no file", async () => {
  render(loader());

  await waitFor(() =>
    expect(mockSetCurrentProjectPackages).toHaveBeenCalledWith(["acme.defaults@1"]),
  );
  expect(mockLoadTrill).not.toHaveBeenCalled();
  expect(mockMarkDirty).not.toHaveBeenCalled();
});

it("opens a file picked on a saved dataflow only once the route is /dataflow/new", async () => {
  mockRouteId = SAVED_ID;
  mockLoadProject.mockResolvedValue({ spec: SAVED, outputs: [] });
  const view = render(loader());
  await waitFor(() => expect(mockLoadTrill).toHaveBeenCalledTimes(1));
  expect(mockLoadTrill.mock.calls[0][0]).toBe(SAVED);

  // The menu hands the file over, then navigates. On the saved dataflow's
  // route nothing is put over it, and it is not loaded again.
  act(() => openDataflowFile(FILE));
  expect(mockLoadTrill).toHaveBeenCalledTimes(1);
  expect(mockLoadProject).toHaveBeenCalledTimes(1);

  mockRouteId = "new";
  view.rerender(loader());
  await waitFor(() => expect(mockLoadTrill).toHaveBeenCalledTimes(2));
  expect(mockLoadTrill).toHaveBeenLastCalledWith(FILE);
  expect(mockSetUnsavedDataflow).toHaveBeenCalledTimes(1);
  expect(mockMarkDirty).toHaveBeenCalledTimes(1);
  expect(mockLoadProject).toHaveBeenCalledTimes(1);
  expect(mockGetDefaults).not.toHaveBeenCalled();
});

it("does not load the open dataflow again when a file is picked over it", async () => {
  // The route names the dataflow already on the canvas, as after the first
  // save of a new one, so the loader had nothing to fetch for it.
  mockRouteId = SAVED_ID;
  mockProjectId = SAVED_ID;
  const view = render(loader());

  // The menu drops the open project and hands the file over before the route
  // changes: for a moment the route names a dataflow the canvas has left.
  mockProjectId = null;
  act(() => openDataflowFile(FILE));
  expect(mockLoadProject).not.toHaveBeenCalled();
  expect(mockLoadTrill).not.toHaveBeenCalled();

  mockRouteId = "new";
  view.rerender(loader());
  await waitFor(() => expect(mockLoadTrill).toHaveBeenCalledWith(FILE));
  expect(mockLoadProject).not.toHaveBeenCalled();
});

it("opens a file picked on an unsaved dataflow, where the route does not change", async () => {
  render(loader());
  await waitFor(() => expect(mockGetDefaults).toHaveBeenCalledTimes(1));

  act(() => openDataflowFile(FILE));
  await waitFor(() => expect(mockLoadTrill).toHaveBeenCalledWith(FILE));
  expect(mockMarkDirty).toHaveBeenCalledTimes(1);

  act(() => openDataflowFile(SECOND_FILE));
  await waitFor(() => expect(mockLoadTrill).toHaveBeenLastCalledWith(SECOND_FILE));
  expect(mockLoadTrill).toHaveBeenCalledTimes(2);
  expect(mockMarkDirty).toHaveBeenCalledTimes(2);
  expect(mockEnsureWorkflowDeps).toHaveBeenLastCalledWith(SECOND_FILE);
});

it("opens the file once: the next new dataflow starts empty", async () => {
  openDataflowFile(FILE);
  const view = render(loader());
  await waitFor(() => expect(mockLoadTrill).toHaveBeenCalledWith(FILE));

  // `/dataflow` with no id takes the same branch as `/dataflow/new`.
  mockRouteId = "";
  view.rerender(loader());
  await waitFor(() => expect(mockGetDefaults).toHaveBeenCalledTimes(1));
  expect(mockLoadTrill).toHaveBeenCalledTimes(1);
  expect(mockMarkDirty).toHaveBeenCalledTimes(1);
});

it("reports a file whose replay throws, and does not mark it unsaved", async () => {
  mockLoadTrill.mockImplementation(() => {
    throw new Error("unknown node type acme/thing");
  });
  const spy = jest.spyOn(console, "error").mockImplementation(() => {});
  openDataflowFile(FILE);
  render(loader());

  await waitFor(() =>
    expect(mockShowToast).toHaveBeenCalledWith(
      "That dataflow could not be loaded: unknown node type acme/thing",
      "error",
    ),
  );
  expect(mockMarkDirty).not.toHaveBeenCalled();
  expect(mockEnsureWorkflowDeps).not.toHaveBeenCalled();
  spy.mockRestore();
});
