/**
 * A routed dataflow is never "unsaved", only not loaded yet (#340).
 *
 * The id a save branches on arrives when ``loadProject`` answers, which is a
 * long way after the route resolved: ProjectLoader awaits a package-registry
 * refresh before it even sends the GET. Anything that saved in that window --
 * the Node Catalog drawer's import, install and remove all do -- read the empty
 * id as "this dataflow has never been saved" and took the create branch. CI
 * caught it as an e2e waiting out 120s for an install against the dataflow in
 * the URL while the app quietly installed into a SECOND dataflow it had just
 * minted:
 *
 *   POST /api/projects                              201   <- the fork
 *   POST /api/packages/upload                       201
 *   POST /api/packages/projects/<the fork>/install  201   <- not the URL's id
 *
 * The store knows the difference at every instant: ProjectLoader pins the
 * routed id synchronously and opens a latch, while ``/dataflow/new`` leaves the
 * id undefined. These tests drive the real store, because the discrimination
 * between the two is the fix.
 */
import { renderHook, act } from "@testing-library/react";

jest.mock("reactflow", () => ({
  useReactFlow: () => ({ getNodes: () => [], getEdges: () => [] }),
  useNodesInitialized: () => false,
}));
jest.mock("../../providers/ProvenanceProvider", () => ({
  useProvenanceContext: () => ({ getAllNodeProvenance: () => ({}) }),
}));
jest.mock("../../providers/ToastProvider", () => ({
  useToastContext: () => ({ showToast: jest.fn() }),
}));
jest.mock("../../providers/UserProvider", () => ({
  useUserContext: () => ({ user: null, enableUserAuth: false }),
}));
jest.mock("../../api/projectsApi", () => ({
  projectsApi: { create: jest.fn(), update: jest.fn(), get: jest.fn() },
}));
jest.mock("../../utils/saveOutputDataset", () => ({
  buildSaveableLiveOutputs: jest.fn(() => []),
}));

import { useWorkflowOperations } from "../../hook/useWorkflowOperations";
import { projectsApi } from "../../api/projectsApi";
import {
  beginProjectLoad,
  clearCurrentProject,
  setCurrentProject,
  settleProjectLoad,
  setUnsavedDataflow,
} from "../../registry/projectPackagesStore";

const ROUTED = "23266c80-b309-4fb0-b2a1-203fc5a6982e";

const makeDeps = () =>
  ({
    nodes: [],
    edges: [],
    setNodes: jest.fn(),
    setEdges: jest.fn(),
    setOutputs: jest.fn(),
    outputsRef: { current: [] },
    setInteractions: jest.fn(),
    setDashboardPins: jest.fn(),
    setPositionsInDashboard: jest.fn(),
    setPositionsInWorkflow: jest.fn(),
    setWorkflowName: jest.fn(),
    workflowNameRef: { current: "wf" },
    setWorkflowDescription: jest.fn(),
    workflowDescriptionRef: { current: "" },
    onEdgesDelete: jest.fn(),
    onNodesDelete: jest.fn(),
    onNodesChange: jest.fn(),
    onConnect: jest.fn(),
    addNode: jest.fn(),
    defaultSaveOutputDataset: false,
  }) as any;

const renderOps = () => renderHook(() => useWorkflowOperations(makeDeps()));

/** What ProjectLoader does the instant the route resolves, before any await. */
function routeTo(id: string) {
  setCurrentProject(id, []);
  beginProjectLoad(id);
}

beforeEach(() => {
  jest.clearAllMocks();
  clearCurrentProject();
  (projectsApi.get as jest.Mock).mockResolvedValue({
    project: { id: ROUTED, name: "wf", updated_at: null },
    spec: { dataflow: { nodes: [], edges: [] } },
    outputs: [],
  });
  (projectsApi.update as jest.Mock).mockImplementation(async (id: string) => ({
    id,
    name: "wf",
    spec: {},
  }));
  (projectsApi.create as jest.Mock).mockResolvedValue({
    id: "a-brand-new-dataflow",
    name: "wf",
    spec: {},
  });
});

describe("saving while the routed dataflow is still loading", () => {
  it("updates the routed dataflow instead of creating a second one", async () => {
    // The bug, in the order CI hit it: the route has resolved, the load has not
    // landed, and the drawer saves to get an id to install into.
    routeTo(ROUTED);
    const { result } = renderOps();

    let save: Promise<any>;
    await act(async () => {
      save = result.current.saveCurrentProject();
      // A microtask is all an unfixed build needs to POST /api/projects.
      await Promise.resolve();
    });
    expect(projectsApi.create).not.toHaveBeenCalled();

    // The load lands, exactly as ProjectLoader drives it.
    await act(async () => {
      await result.current.loadProject(ROUTED);
      settleProjectLoad(ROUTED);
      await save;
    });

    expect(projectsApi.create).not.toHaveBeenCalled();
    expect(projectsApi.update).toHaveBeenCalledTimes(1);
    expect((projectsApi.update as jest.Mock).mock.calls[0][0]).toBe(ROUTED);
  });

  it("serializes the canvas after the wait, not before it", async () => {
    // The wait sits ahead of the canvas read for this reason. Waiting after it
    // would name the right dataflow and then persist the empty pre-load canvas
    // over the stored one, turning a duplicate into a wipe.
    routeTo(ROUTED);
    const { result } = renderOps();

    let save: Promise<any>;
    await act(async () => {
      save = result.current.saveCurrentProject();
      await Promise.resolve();
    });

    await act(async () => {
      await result.current.loadProject(ROUTED);
      // Nodes exist by the time the latch opens, which is what ProjectLoader
      // guarantees by settling only after the spec is applied.
      settleProjectLoad(ROUTED);
      await save;
    });

    const [, body] = (projectsApi.update as jest.Mock).mock.calls[0];
    expect(body.spec).toBeDefined();
  });

  it("reports rather than forking when the load settles with no id", async () => {
    // A 404 that fell through to the shared endpoint, a load that overran its
    // bound, a failure already toasted by ProjectLoader. Creating here is the
    // fork; refusing leaves the dataflow on screen the only one there is.
    routeTo(ROUTED);
    const { result } = renderOps();

    let err: unknown;
    await act(async () => {
      settleProjectLoad(ROUTED);
      await result.current.saveCurrentProject().catch((e: unknown) => {
        err = e;
      });
    });

    expect((err as Error)?.message).toMatch(/still opening/i);
    expect(projectsApi.create).not.toHaveBeenCalled();
    expect(projectsApi.update).not.toHaveBeenCalled();
  });

  it("still creates for a dataflow that genuinely has no id", async () => {
    // ``/dataflow/new``: no routed id, no latch, so nothing to wait for and the
    // first save is what mints the dataflow. The fix must not touch this.
    setUnsavedDataflow([]);
    const { result } = renderOps();

    await act(async () => {
      await result.current.saveCurrentProject();
    });

    expect(projectsApi.create).toHaveBeenCalledTimes(1);
    expect(projectsApi.update).not.toHaveBeenCalled();
  });

  it("does not wait once the dataflow is loaded", async () => {
    // The common case has to stay synchronous-ish: a latch left open by a load
    // that already delivered its id would stall every later save.
    routeTo(ROUTED);
    const { result } = renderOps();
    await act(async () => {
      await result.current.loadProject(ROUTED);
      settleProjectLoad(ROUTED);
    });

    await act(async () => {
      await result.current.saveCurrentProject();
    });

    expect(projectsApi.update).toHaveBeenCalledTimes(1);
    expect(projectsApi.create).not.toHaveBeenCalled();
  });
});
