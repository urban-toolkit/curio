/**
 * "Run stale nodes automatically" (#845) is a setting of the dataflow, saved
 * with it at `dataflow.autoRun` and off by default. Turning it on or off is an
 * unsaved change of a canvas never saved; the dataflow a save makes holds it;
 * opening a dataflow reads it; a version snapshot, which carries none, keeps
 * it; a new dataflow starts with it off. On a dataflow bound to its doc, the
 * doc takes it as every other field (dataflowDocBridge.test.tsx).
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
const mockCreate = jest.fn();
const mockUpdate = jest.fn();
jest.mock("../../api/projectsApi", () => ({
  projectsApi: {
    create: (...args: unknown[]) => mockCreate(...args),
    update: (...args: unknown[]) => mockUpdate(...args),
    get: jest.fn(),
  },
}));
jest.mock("../../utils/saveOutputDataset", () => ({
  buildSaveableLiveOutputs: jest.fn(() => []),
}));
jest.mock("../../registry/projectPackagesStore", () => ({
  getCurrentProjectPackagesList: jest.fn(() => []),
  getCurrentProjectId: jest.fn(() => undefined),
  whenProjectSettled: jest.fn(async () => {}),
  setCurrentProject: jest.fn(),
  setCurrentProjectPackages: jest.fn(),
  subscribe: jest.fn(() => jest.fn()),
}));

import { useWorkflowOperations } from "../../hook/useWorkflowOperations";

function deps() {
  return {
    nodes: [],
    edges: [],
    setNodes: jest.fn((u: any) => (typeof u === "function" ? u([]) : u)),
    setEdges: jest.fn(),
    setOutputs: jest.fn(),
    outputsRef: { current: [] },
    setInteractions: jest.fn(),
    setDashboardPins: jest.fn(),
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
  } as any;
}

/** loadParsedTrill as an open passes the dataflow's fields; *autoRun* last. */
async function load(result: any, autoRun: boolean | undefined) {
  await act(async () => {
    await result.current.loadParsedTrill("wf", "", [], [], true, false, [], "", [], {}, [], false, autoRun);
  });
}

beforeEach(() => {
  mockCreate.mockReset();
  const spec = { dataflow: { datasets: [], packages: [] } };
  mockCreate.mockResolvedValue({ id: "p1", name: "wf", spec, spec_revision: 1 });
  mockUpdate.mockReset();
  mockUpdate.mockResolvedValue({ id: "p1", name: "wf", spec, spec_revision: 2 });
});

describe("the auto-run setting", () => {
  it("is off for a new dataflow (#845)", () => {
    const { result } = renderHook(() => useWorkflowOperations(deps()));
    expect(result.current.autoRun).toBe(false);
  });

  it("is an unsaved change, and the dataflow a save makes holds it (#845)", async () => {
    const { result } = renderHook(() => useWorkflowOperations(deps()));
    act(() => result.current.setAutoRun(true));
    expect(result.current.autoRun).toBe(true);
    expect(result.current.projectDirty).toBe(true);

    await act(async () => {
      await result.current.saveDataflow();
    });
    expect(mockCreate).toHaveBeenCalledTimes(1);
    expect(mockCreate.mock.calls[0][0].spec.dataflow.autoRun).toBe(true);

    // Off is written as off in what a canvas sends, so the server never keeps
    // an "on" it already held: a copy made with it off holds it off.
    act(() => result.current.setAutoRun(false));
    await act(async () => {
      await result.current.saveAsNewProject("A copy", "p1");
    });
    expect(mockCreate).toHaveBeenCalledTimes(2);
    expect(mockCreate.mock.calls[1][0].spec.dataflow.autoRun).toBe(false);
    // No tab saves a dataflow it is open on.
    expect(mockUpdate).not.toHaveBeenCalled();
  });

  it("is read when a dataflow opens; a snapshot without it keeps it (#845)", async () => {
    const { result } = renderHook(() => useWorkflowOperations(deps()));
    await load(result, true);
    expect(result.current.autoRun).toBe(true);
    expect(result.current.projectDirty).toBe(false);

    await load(result, undefined);
    expect(result.current.autoRun).toBe(true);

    await load(result, false);
    expect(result.current.autoRun).toBe(false);
  });

  it("goes off when the dataflow is discarded for a new one (#845)", () => {
    const { result } = renderHook(() => useWorkflowOperations(deps()));
    act(() => result.current.setAutoRun(true));
    act(() => result.current.discardProject());
    expect(result.current.autoRun).toBe(false);
  });
});
