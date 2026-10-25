/**
 * Which dataflow a canvas reads its outputs on (services/dataflowReads.ts).
 * While one is open, the canvas reads every output on that dataflow's routes,
 * where an output it saved is read from its owner's Data Catalog in place.
 *
 * It is the dataflow the route names, the owner's or a shared one, which a
 * visitor never holds, and the route's even while the canvas still holds the
 * dataflow before it. On /dataflow/new it is the id a new dataflow gets on its
 * first save. The dashboard page sets it too, behind what it carries.
 */
import React from "react";
import { render, waitFor } from "@testing-library/react";

const mockLoadProject = jest.fn();
const mockLoadSharedProject = jest.fn();
const mockLoadTrill = jest.fn();

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
    markDirty: jest.fn(),
    setWorkflowName: jest.fn(),
  }),
}));
jest.mock("../../hook/useCode", () => ({
  useCode: () => ({ loadTrill: mockLoadTrill }),
}));
jest.mock("../../providers/packages/useEnsureWorkflowDeps", () => ({
  useEnsureWorkflowDeps: () => jest.fn(),
}));
jest.mock("../../TrillGenerator", () => ({ TrillGenerator: { reset: jest.fn() } }));
jest.mock("../../registry/packageRegistryBootstrap", () => ({
  refreshPackageRegistry: jest.fn().mockResolvedValue(undefined),
}));
jest.mock("../../providers/ToastProvider", () => ({
  useToastContext: () => ({ showToast: jest.fn() }),
}));
jest.mock("../../registry/projectPackagesStore", () => ({
  clearCurrentProject: jest.fn(),
  beginProjectLoad: jest.fn(),
  settleProjectLoad: jest.fn(),
  setCurrentProject: jest.fn(),
  setUnsavedDataflow: jest.fn(),
  setCurrentProjectPackages: jest.fn(),
}));
jest.mock("../../services/packages", () => ({
  packagesApi: { getDefaults: jest.fn().mockResolvedValue({ packages: [] }) },
}));

import { ProjectLoader } from "../../components/ProjectLoader";
import { openDataflowId, setOpenDataflow } from "../../services/dataflowReads";

const ROUTE_ID = "11111111-2222-3333-4444-555555555555";
const HELD_ID = "66666666-7777-8888-9999-000000000000";
const SPEC = { dataflow: { nodes: [{ id: "py" }], edges: [] } };
const OUTPUTS = [{ node_id: "py", filename: "1700000000000_deadbeef", data_type: "dataframe" }];

const notFound = () => Object.assign(new Error("not found"), { status: 404 });

const renderLoader = (presentation = false) =>
  render(<ProjectLoader presentation={presentation}><span /></ProjectLoader>);

beforeEach(() => {
  jest.clearAllMocks();
  setOpenDataflow(null);
  mockRouteId = ROUTE_ID;
  mockProjectId = null;
  mockLoadTrill.mockReturnValue({ nodes: SPEC.dataflow.nodes, edges: [] });
  mockLoadProject.mockResolvedValue({ spec: SPEC, outputs: OUTPUTS });
});

afterEach(() => setOpenDataflow(null));

describe("the dataflow a canvas reads its outputs on", () => {
  it("is the one the route opens", async () => {
    renderLoader();

    await waitFor(() => expect(mockLoadTrill).toHaveBeenCalled());
    expect(openDataflowId()).toBe(ROUTE_ID);
  });

  it("is the route's for a visitor on a shared dataflow, who holds none", async () => {
    mockLoadProject.mockRejectedValue(notFound());
    mockLoadSharedProject.mockResolvedValue({ spec: SPEC, outputs: OUTPUTS });

    renderLoader();

    await waitFor(() => expect(mockLoadTrill).toHaveBeenCalled());
    expect(mockLoadSharedProject).toHaveBeenCalledWith(ROUTE_ID);
    expect(openDataflowId()).toBe(ROUTE_ID);
  });

  it("is the route's while the canvas still holds the dataflow before it", async () => {
    mockProjectId = HELD_ID;

    renderLoader();

    expect(openDataflowId()).toBe(ROUTE_ID);
    await waitFor(() => expect(mockLoadTrill).toHaveBeenCalled());
    expect(openDataflowId()).toBe(ROUTE_ID);
  });

  it("is the id a new dataflow gets on its first save", () => {
    mockRouteId = "new";
    mockProjectId = HELD_ID;

    renderLoader();

    expect(openDataflowId()).toBe(HELD_ID);
  });

  it("is none on a dataflow never saved", () => {
    mockRouteId = "new";

    renderLoader();

    expect(openDataflowId()).toBeNull();
  });

  it("is the route's on the dashboard page too, which reads what it carries first", async () => {
    // A page served without its data fetches its tiles' outputs, and a saved
    // one is read only on its dataflow's route: nothing copies it anywhere
    // a plain `/get` would find it.
    renderLoader(true);

    await waitFor(() => expect(mockLoadTrill).toHaveBeenCalled());
    expect(openDataflowId()).toBe(ROUTE_ID);
  });

  it("is none once the canvas closes", async () => {
    const { unmount } = renderLoader();
    await waitFor(() => expect(mockLoadTrill).toHaveBeenCalled());
    expect(openDataflowId()).toBe(ROUTE_ID);

    unmount();

    expect(openDataflowId()).toBeNull();
  });
});
