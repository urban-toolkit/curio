/**
 * Regression tests for #186 / #195 — provenance recorded during a dataflow LOAD.
 *
 * `loadParsedTrill` used to hand `provenance = true` down to `addNode` and
 * `onConnect`, both of which snapshot `reactFlow.getNodes()`. React Flow only
 * syncs `useNodesState` into its zustand store from a useEffect, so inside that
 * synchronous loop the store still held the pre-load graph — which the same
 * function had just emptied. Every version came out with one node and no edges,
 * or no nodes and one edge.
 *
 * Two user-visible consequences, both reported:
 *   #186 — the provenance graph's thumbnails render nothing, because
 *          DataflowThumbnail drops any edge whose endpoints are missing.
 *   #195 — clicking such a version replays its edges through `onConnect` with an
 *          empty node list, and the cycle check dereferences the unresolved
 *          target. Malformed versions of exactly this shape are on disk today in
 *          `.curio/users/1/projects/*\/spec.trill.json`.
 *
 * TrillGenerator is deliberately REAL here: the whole point is what actually
 * lands in `provenanceJSON` / `list_of_trills`.
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
  projectsApi: { create: jest.fn(), update: jest.fn() },
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
import { TrillGenerator } from "../../TrillGenerator";

/** A node in the shape `generateCodeNode` produces and `generateTrill` reads. */
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

const makeDeps = (over: Record<string, unknown> = {}) =>
  ({
    nodes: [],
    edges: [],
    // The real setter runs its updater; a bare jest.fn() would mean `onConnect`
    // is never reached and the edge half of this file would pass vacuously.
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
    onConnect: jest.fn(),
    addNode: jest.fn(),
    defaultSaveOutputDataset: false,
    ...over,
  }) as any;

const NODES = [makeNode("a"), makeNode("b"), makeNode("c")];
const EDGES = [makeEdge("a", "b"), makeEdge("b", "c")];

/** Every version's preview, oldest first, skipping the empty `initialize` one. */
const previews = () =>
  TrillGenerator.provenanceJSON.nodes
    .slice(1)
    .map((v: any) => v.preview as { nodes: any[]; edges: any[] });

beforeEach(() => {
  jest.clearAllMocks();
  TrillGenerator.reset();
});

describe("loadParsedTrill provenance (#186)", () => {
  test("each version holds the cumulative graph, not one node from a stale store", async () => {
    const deps = makeDeps();
    const { result } = renderHook(() => useWorkflowOperations(deps));

    await act(async () => {
      await result.current.loadParsedTrill("wf", "", NODES, EDGES, true, false);
    });

    // 3 nodes + 2 edges = 5 versions on top of the initial empty one.
    const shapes = previews().map((p: { nodes: any[]; edges: any[] }) => [
      p.nodes.length,
      p.edges.length,
    ]);
    expect(shapes).toEqual([
      [1, 0], [2, 0], [3, 0],   // node versions accumulate
      [3, 1], [3, 2],           // edge versions keep the full node set
    ]);

    const last = previews().at(-1)!;
    expect(last.nodes.map((n: any) => n.id).sort()).toEqual(["a", "b", "c"]);
    expect(last.edges).toHaveLength(2);
  });

  test("no version carries an edge whose endpoints it does not hold (the #195 invariant)", async () => {
    const deps = makeDeps();
    const { result } = renderHook(() => useWorkflowOperations(deps));

    await act(async () => {
      await result.current.loadParsedTrill("wf", "", NODES, EDGES, true, false);
    });

    const versions = Object.entries(TrillGenerator.list_of_trills) as [string, any][];
    expect(versions.length).toBeGreaterThan(1);
    for (const [id, trill] of versions) {
      const present = new Set((trill.dataflow.nodes ?? []).map((n: any) => n.id));
      for (const edge of trill.dataflow.edges ?? []) {
        expect({ id, endpoint: edge.source, present: present.has(edge.source) })
          .toEqual({ id, endpoint: edge.source, present: true });
        expect({ id, endpoint: edge.target, present: present.has(edge.target) })
          .toEqual({ id, endpoint: edge.target, present: true });
      }
    }
  });

  test("the load itself never asks addNode / onConnect to record provenance", async () => {
    const deps = makeDeps();
    const { result } = renderHook(() => useWorkflowOperations(deps));

    await act(async () => {
      await result.current.loadParsedTrill("wf", "", NODES, EDGES, true, false);
    });

    expect(deps.addNode).toHaveBeenCalledTimes(3);
    for (const call of deps.addNode.mock.calls) expect(call[2]).toBe(false);

    expect(deps.onConnect).toHaveBeenCalledTimes(2);
    for (const call of deps.onConnect.mock.calls) expect(call[4]).toBe(false);
  });

  test("provenance=false records nothing beyond the initial version", async () => {
    const deps = makeDeps();
    const { result } = renderHook(() => useWorkflowOperations(deps));

    await act(async () => {
      await result.current.loadParsedTrill("wf", "", NODES, EDGES, false, false);
    });

    expect(previews()).toHaveLength(0);
  });
});
