import { renderHook, act, waitFor } from "@testing-library/react";

/**
 * Saves of the open dataflow run one after another, through the save queue
 * (`requestProjectSave`). Two PUTs of one dataflow at once were behind #909 (a
 * save stuck for SQLite's 30 s busy timeout) and #941 (a dashboard reading
 * outputs while a second save rewrote them), and most of them came from the
 * browser: the pin's save and the autosave saved directly, beside the queue.
 */

// One object for every render. A new one per render would give
// saveCurrentProject a new identity on every render, which re-arms the
// 30 second autosave interval each time.
const mockReactFlow = { getNodes: () => [], getEdges: () => [] };
jest.mock("reactflow", () => ({
  useReactFlow: () => mockReactFlow,
  useNodesInitialized: () => false,
}));
jest.mock("../../providers/ProvenanceProvider", () => ({
  useProvenanceContext: () => ({ getAllNodeProvenance: () => ({}) }),
}));
const mockShowToast = jest.fn();
jest.mock("../../providers/ToastProvider", () => ({
  useToastContext: () => ({ showToast: mockShowToast }),
}));
jest.mock("../../providers/UserProvider", () => ({
  useUserContext: () => ({ user: null, enableUserAuth: false }),
}));
jest.mock("../../api/projectsApi", () => ({
  projectsApi: { create: jest.fn(), update: jest.fn(), get: jest.fn() },
}));
jest.mock("../../TrillGenerator", () => ({
  TrillGenerator: {
    generateTrill: jest.fn(() => ({ dataflow: { datasets: [] } })),
    getSerializableDataflowProvenance: jest.fn(() => ({})),
    reset: jest.fn(),
  },
}));
jest.mock("../../utils/saveOutputDataset", () => ({
  buildSaveableLiveOutputs: jest.fn(() => []),
}));
jest.mock("../../registry/projectPackagesStore", () => ({
  getCurrentProjectPackagesList: jest.fn(() => []),
  // No routed dataflow and nothing loading: saves take their id from the
  // hook's own state, as they do once a load has landed.
  getCurrentProjectId: jest.fn(() => undefined),
  whenProjectSettled: jest.fn(async () => {}),
  setCurrentProject: jest.fn(),
  setCurrentProjectPackages: jest.fn(),
  subscribe: jest.fn(() => jest.fn()),
}));

import { useWorkflowOperations } from "../../hook/useWorkflowOperations";
import { useDashboardPinSave } from "../../providers/flow/useDashboardPins";
import { projectsApi } from "../../api/projectsApi";

/** Made once per test, so every render gets the same refs. */
const makeDeps = () => {
  const workflowNameRef = { current: "Loaded name" };
  const workflowDescriptionRef = { current: "" };
  return {
    nodes: [],
    edges: [],
    setNodes: jest.fn(),
    setEdges: jest.fn(),
    setOutputs: jest.fn(),
    outputsRef: { current: [] },
    setInteractions: jest.fn(),
    setDashboardPins: jest.fn(),
    setWorkflowName: jest.fn((n: string) => {
      workflowNameRef.current = n;
    }),
    workflowNameRef,
    setWorkflowDescription: jest.fn((d: string) => {
      workflowDescriptionRef.current = d || "";
    }),
    workflowDescriptionRef,
    onEdgesDelete: jest.fn(),
    onNodesDelete: jest.fn(),
    onNodesChange: jest.fn(),
    onConnect: jest.fn(),
    addNode: jest.fn(),
    defaultSaveOutputDataset: false,
  } as any;
};

/** A project loaded from the server, so saves take the update branch. */
async function loadedProject(result: any) {
  (projectsApi.get as jest.Mock).mockResolvedValue({
    project: { id: "proj-1", name: "Loaded name", updated_at: null },
    spec: { dataflow: { nodes: [], edges: [] } },
    outputs: [],
  });
  await act(async () => {
    await result.current.loadProject("proj-1");
  });
}

const SAVED = {
  id: "proj-1",
  name: "Loaded name",
  spec: { dataflow: { datasets: [], packages: [] } },
};

/** Hold the next PUT open until the returned function answers it. */
function holdNextUpdate(): () => void {
  let answer!: () => void;
  const answered = new Promise((resolve) => {
    answer = () => resolve(SAVED);
  });
  (projectsApi.update as jest.Mock).mockImplementationOnce(() => answered);
  return answer;
}

beforeEach(() => {
  jest.clearAllMocks();
  (projectsApi.update as jest.Mock).mockResolvedValue(SAVED);
});

afterEach(() => {
  jest.useRealTimers();
});

describe("the save queue", () => {
  it("starts the second of two saves only after the first has answered", async () => {
    const deps = makeDeps();
    const { result } = renderHook(() => useWorkflowOperations(deps));
    await loadedProject(result);

    const events: string[] = [];
    let answerFirst!: () => void;
    (projectsApi.update as jest.Mock)
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            answerFirst = () => {
              events.push("first answered");
              resolve(SAVED);
            };
          }),
      )
      .mockImplementationOnce(async () => {
        events.push("second sent");
        return SAVED;
      });

    let first!: Promise<unknown>;
    let second!: Promise<unknown>;
    act(() => {
      first = result.current.requestProjectSave();
      second = result.current.requestProjectSave();
    });
    // The first PUT is out; the second waits for its answer.
    expect(projectsApi.update).toHaveBeenCalledTimes(1);
    expect(events).toEqual([]);

    await act(async () => {
      answerFirst();
      await first;
      await second;
    });

    expect(projectsApi.update).toHaveBeenCalledTimes(2);
    expect(events).toEqual(["first answered", "second sent"]);
  });

  it("holds a pin's save until the save in flight has answered", async () => {
    // A pin saves 400 ms after the click. A Save clicked in between, as the
    // dashboard e2e tests do right after pinning, used to go out beside it.
    jest.useFakeTimers();
    const deps = makeDeps();
    const savePinChangeRef = { current: () => {} };
    const { result } = renderHook(() => {
      const ops = useWorkflowOperations(deps);
      useDashboardPinSave({
        savePinChangeRef,
        dashboardOn: false,
        workflowOps: ops,
        showToast: mockShowToast,
      });
      return ops;
    });
    await loadedProject(result);
    const answerSave = holdNextUpdate();

    let save!: Promise<unknown>;
    act(() => {
      save = result.current.requestProjectSave();
    });
    act(() => {
      savePinChangeRef.current();
    });
    act(() => {
      jest.advanceTimersByTime(400);
    });
    // Past the pin's debounce: its save waits in the queue.
    expect(projectsApi.update).toHaveBeenCalledTimes(1);

    jest.useRealTimers();
    await act(async () => {
      answerSave();
      await save;
    });
    // And goes out once the save before it has answered.
    await waitFor(() => expect(projectsApi.update).toHaveBeenCalledTimes(2));
    expect(mockShowToast).not.toHaveBeenCalled();
  });

  it("holds the 30 second autosave until the save in flight has answered", async () => {
    // Autosave plus Save is one of the overlaps #909 names.
    jest.useFakeTimers();
    const deps = makeDeps();
    const { result } = renderHook(() => useWorkflowOperations(deps));
    await loadedProject(result);
    // An edit, so the autosave is armed.
    act(() => {
      result.current.renameDataflow("Edited");
    });
    expect(result.current.projectDirty).toBe(true);
    const answerSave = holdNextUpdate();

    let save!: Promise<unknown>;
    act(() => {
      save = result.current.requestProjectSave();
    });
    act(() => {
      jest.advanceTimersByTime(30_000);
    });
    // The autosave came due while the save was out: it waits in the queue.
    expect(projectsApi.update).toHaveBeenCalledTimes(1);

    jest.useRealTimers();
    await act(async () => {
      answerSave();
      await save;
    });
    // And goes out once the save before it has answered.
    await waitFor(() => expect(projectsApi.update).toHaveBeenCalledTimes(2));
  });
});
