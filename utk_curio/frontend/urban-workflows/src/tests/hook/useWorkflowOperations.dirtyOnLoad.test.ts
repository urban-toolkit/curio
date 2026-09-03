/**
 * Regression test for #229 — a freshly loaded dataflow reported unsaved changes.
 *
 * `FlowProvider.onConnect` marks the project dirty as its first statement, which
 * is right: a user connecting two nodes IS an edit. But the LOAD path replays
 * every persisted edge through that same `onConnect`, once per edge, so any
 * dataflow with at least one edge finished hydrating dirty. `loadProject` clears
 * the flag BEFORE the replay runs, so it was deterministic rather than racy, and
 * the 30s auto-save then fired and rewrote the project for nothing — which is
 * why the indicator "turned green after a while".
 *
 * Not a react-flow layout-settling problem: `MainCanvas.handleNodesChange` marks
 * dirty only on `remove` and on `position` changes carrying a real position, and
 * mount-time measurement in reactflow 11 emits only `dimensions`.
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
jest.mock("../../registry/projectPackagesStore", () => ({
  getCurrentProjectPackagesList: jest.fn(() => []),
  setCurrentProject: jest.fn(),
  setCurrentProjectPackages: jest.fn(),
  subscribe: jest.fn(() => jest.fn()),
}));

import { useWorkflowOperations } from "../../hook/useWorkflowOperations";

const makeNode = (id: string) => ({
  id,
  type: "curioUniversalNode",
  position: { x: 0, y: 0 },
  data: { nodeId: id, nodeType: "curio.builtin/data-loading@1", input: "" },
});

const makeEdge = (source: string, target: string) => ({
  id: `reactflow__edge-${source}out-${target}in`,
  source,
  target,
  sourceHandle: "out",
  targetHandle: "in",
});

const NODES = [makeNode("a"), makeNode("b"), makeNode("c")];
const EDGES = [makeEdge("a", "b"), makeEdge("b", "c")];

/**
 * The hook's `markDirty` reaches `onConnect` through FlowProvider's
 * `markDirtyRef`, which the provider assigns after both are built. The fake
 * closes that loop: it calls back into the live `markDirty`, exactly as
 * `FlowProvider.onConnect` does at its first statement.
 */
function makeDeps(hookRef: { current: any }, over: Record<string, unknown> = {}) {
  return {
    nodes: [],
    edges: [],
    // The real setter runs its updater. A bare jest.fn() would never invoke it,
    // so the replay would not run and every test here would pass vacuously —
    // including against the unfixed code.
    setNodes: jest.fn((u: any) => (typeof u === "function" ? u([]) : u)),
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
    onConnect: jest.fn(() => {
      hookRef.current?.markDirty();
    }),
    addNode: jest.fn(),
    defaultSaveOutputDataset: false,
    ...over,
  } as any;
}

/** Render the hook with a deps object that can call back into it. */
function renderWithLoop(over: Record<string, unknown> = {}) {
  const hookRef: { current: any } = { current: null };
  const deps = makeDeps(hookRef, over);
  const rendered = renderHook(() => {
    const api = useWorkflowOperations(deps);
    hookRef.current = api;
    return api;
  });
  return { ...rendered, deps };
}

async function load(result: any, edges = EDGES) {
  await act(async () => {
    await result.current.loadParsedTrill("wf", "", NODES, edges, true, false);
  });
}

describe("loading a dataflow does not mark it dirty", () => {
  it("stays clean after replaying a dataflow that has edges", async () => {
    // The bug itself. Edges are essential: an edgeless dataflow never reproduced
    // it, which is why it looked intermittent to whoever hit it first.
    const { result, deps } = renderWithLoop();
    await load(result);

    expect(deps.onConnect).toHaveBeenCalledTimes(EDGES.length);
    expect(result.current.projectDirty).toBe(false);
  });

  it("still marks dirty for an edit made straight after the load", async () => {
    // The fix's real risk: a suppression window that outlives the replay would
    // swallow genuine edits and quietly lose the user's work.
    const { result } = renderWithLoop();
    await load(result);

    act(() => {
      result.current.markDirty();
    });

    expect(result.current.projectDirty).toBe(true);
  });

  it("suppresses only its own replay, twice over", async () => {
    // The flag is per-replay, not one-shot, so a second load behaves like the
    // first (React also re-runs the updater under StrictMode).
    const { result } = renderWithLoop();
    await load(result);
    await load(result);

    expect(result.current.projectDirty).toBe(false);
  });

  it("re-arms dirty tracking even when the replay throws", async () => {
    // `finally`, not a trailing assignment: a malformed spec must not leave
    // dirty-tracking wedged off for the rest of the session — that would lose
    // work silently, which is far worse than the bug being fixed.
    const onConnect = jest.fn(() => {
      throw new Error("malformed edge");
    });
    const { result } = renderWithLoop({ onConnect });

    // Caught INSIDE the act: letting the rejection escape leaves RTL's hook
    // result frozen at its pre-error snapshot, so the assertion below would be
    // measuring the harness rather than the ref.
    let thrown: unknown;
    await act(async () => {
      try {
        await result.current.loadParsedTrill("wf", "", NODES, EDGES, true, false);
      } catch (err) {
        thrown = err;
      }
    });
    expect(onConnect).toHaveBeenCalled();
    expect((thrown as Error)?.message).toBe("malformed edge");

    act(() => {
      result.current.markDirty();
    });
    expect(result.current.projectDirty).toBe(true);
  });
});
