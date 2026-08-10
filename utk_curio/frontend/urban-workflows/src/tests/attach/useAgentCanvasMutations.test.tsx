import React from "react";
import { render, act, waitFor } from "@testing-library/react";

const mockCreateCodeNode = jest.fn();
jest.mock("../../hook/useCode", () => ({
  useCode: () => ({ createCodeNode: mockCreateCodeNode }),
}));

const mockApplyNodeContent = jest.fn();
const mockOnEdgesChange = jest.fn();
const mockApplyReviewedRemovals = jest.fn();
jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({
    applyNodeContent: mockApplyNodeContent,
    onEdgesChange: mockOnEdgesChange,
    applyReviewedRemovals: mockApplyReviewedRemovals,
  }),
}));

const mockFitViewWithMenuOffset = jest.fn();
jest.mock("../../utils/fitViewWithMenuOffset", () => ({
  fitViewWithMenuOffset: (...a: unknown[]) => mockFitViewWithMenuOffset(...a),
}));

const mockGetNodes = jest.fn(() => [] as Array<{ id: string }>);
const mockSetCenter = jest.fn();
const mockGetZoom = jest.fn(() => 0.8);
jest.mock("reactflow", () => ({
  useReactFlow: () => ({
    getNodes: mockGetNodes,
    setCenter: mockSetCenter,
    getZoom: mockGetZoom,
  }),
}));

const mockRefreshPackageRegistry = jest.fn(() => Promise.resolve());
jest.mock("../../registry/packageRegistryBootstrap", () => ({
  refreshPackageRegistry: (...a: unknown[]) => mockRefreshPackageRegistry(...a),
}));

const mockGetCurrentProjectPackages = jest.fn((): ReadonlySet<string> | null => new Set(["curio.builtin@1"]));
const mockSetCurrentProjectPackages = jest.fn();
jest.mock("../../registry/projectPackagesStore", () => ({
  getCurrentProjectPackages: () => mockGetCurrentProjectPackages(),
  setCurrentProjectPackages: (p: Iterable<string>) => mockSetCurrentProjectPackages(p),
}));

import { useAgentCanvasMutations } from "../../components/agents/attach/useAgentCanvasMutations";
import {
  notifyAgentCanvasMutation,
  subscribeAgentCanvasMutations,
} from "../../utils/agentCanvasEvents";

const Host: React.FC = () => {
  useAgentCanvasMutations();
  return null;
};

const NODE = {
  id: "server-minted-id",
  type: "curio.builtin/computation-analysis",
  content: "print('new')",
  goal: "sum it",
  x: 500,
  y: 60,
};

beforeEach(() => {
  jest.clearAllMocks();
  mockGetNodes.mockReturnValue([]);
});

describe("agentCanvasEvents", () => {
  it("notify reaches subscribers and unsubscribe stops delivery", () => {
    const seen: unknown[] = [];
    const off = subscribeAgentCanvasMutations((m) => seen.push(m));
    notifyAgentCanvasMutation({ kind: "node-content-applied", nodeId: "n1", content: "c" });
    off();
    notifyAgentCanvasMutation({ kind: "node-content-applied", nodeId: "n2", content: "c" });
    expect(seen).toEqual([{ kind: "node-content-applied", nodeId: "n1", content: "c" }]);
  });
});

describe("useAgentCanvasMutations (the apply→canvas bridge, dev/48 §3.3 + dev/51)", () => {
  it("node-created inserts through the existing factory with the SERVER id", () => {
    render(<Host />);
    act(() => notifyAgentCanvasMutation({ kind: "node-created", node: NODE }));
    expect(mockCreateCodeNode).toHaveBeenCalledWith("curio.builtin/computation-analysis", {
      nodeId: "server-minted-id",
      code: "print('new')",
      goal: "sum it",
      position: { x: 500, y: 60 },
    });
    // No registry writes for an existing template.
    expect(mockRefreshPackageRegistry).not.toHaveBeenCalled();
    expect(mockSetCurrentProjectPackages).not.toHaveBeenCalled();
  });

  it("centers the viewport on the created node at the current zoom (dev/51 defect 1)", () => {
    render(<Host />);
    act(() => notifyAgentCanvasMutation({ kind: "node-created", node: NODE }));
    expect(mockSetCenter).toHaveBeenCalledWith(675, 160, { zoom: 0.8, duration: 400 });
  });

  it("a double event is a no-op when the node already exists live", () => {
    mockGetNodes.mockReturnValue([{ id: "server-minted-id" }]);
    render(<Host />);
    act(() => notifyAgentCanvasMutation({ kind: "node-created", node: NODE }));
    expect(mockCreateCodeNode).not.toHaveBeenCalled();
  });

  it("a re-fired event before the store syncs is a no-op (dev/51 defect 3)", () => {
    // The store never reports the node (sync lag) — the processed-ids ref
    // must still stop the second insert.
    mockGetNodes.mockReturnValue([]);
    render(<Host />);
    act(() => notifyAgentCanvasMutation({ kind: "node-created", node: NODE }));
    act(() => notifyAgentCanvasMutation({ kind: "node-created", node: NODE }));
    expect(mockCreateCodeNode).toHaveBeenCalledTimes(1);
  });

  it("a created TEMPLATE lands in the store + registry BEFORE the node inserts", async () => {
    const order: string[] = [];
    mockSetCurrentProjectPackages.mockImplementation(() => order.push("store"));
    mockRefreshPackageRegistry.mockImplementation(() => {
      order.push("registry");
      return Promise.resolve();
    });
    mockCreateCodeNode.mockImplementation(() => order.push("insert"));
    render(<Host />);
    act(() =>
      notifyAgentCanvasMutation({
        kind: "node-created",
        node: { ...NODE, type: "curio.agent.scorer/scorer" },
        createdPackageDir: "curio.agent.scorer@1",
      }),
    );
    await waitFor(() => expect(order).toEqual(["store", "registry", "insert"]));
    const stored = mockSetCurrentProjectPackages.mock.calls[0][0] as string[];
    expect(Array.from(stored)).toEqual(["curio.builtin@1", "curio.agent.scorer@1"]);
  });

  it("node-content-applied routes through FlowProvider.applyNodeContent (dev/51 defect 2)", () => {
    render(<Host />);
    act(() =>
      notifyAgentCanvasMutation({
        kind: "node-content-applied",
        nodeId: "n1",
        content: "print(2)",
      }),
    );
    expect(mockApplyNodeContent).toHaveBeenCalledWith("n1", "print(2)");
  });
});

describe("graph-created (dev/52 — a whole applied plan)", () => {
  const GRAPH = {
    kind: "graph-created" as const,
    planId: "plan-1",
    nodes: [
      { id: "ga", type: "curio.builtin/computation-analysis", content: "", goal: "Load — l", x: 500, y: 60 },
      { id: "gb", type: "curio.builtin/computation-analysis", content: "", goal: "Analyze — a", x: 920, y: 60 },
    ],
    edges: [{ id: "e1", source: "ga", target: "gb" }],
  };

  it("bulk-inserts nodes and edges through the provider paths, then fits", async () => {
    jest.useFakeTimers();
    try {
      render(<Host />);
      act(() => notifyAgentCanvasMutation(GRAPH));
      expect(mockCreateCodeNode).toHaveBeenCalledTimes(2);
      expect(mockCreateCodeNode).toHaveBeenCalledWith(
        "curio.builtin/computation-analysis",
        expect.objectContaining({ nodeId: "ga", position: { x: 500, y: 60 } }),
      );
      const changes = mockOnEdgesChange.mock.calls[0][0];
      expect(changes).toHaveLength(1);
      expect(changes[0].type).toBe("add");
      expect(changes[0].item).toMatchObject({ id: "e1", source: "ga", target: "gb" });
      // dev/58: the edge components read display flags off `data` — the
      // bridge must always provide it (loadTrill parity), or the first
      // render of the inserted edge crashes the canvas.
      expect(changes[0].item.data).toEqual({});
      act(() => {
        jest.runAllTimers();
      });
      expect(mockFitViewWithMenuOffset).toHaveBeenCalled();
      // No single-node centering for a graph — it gets a fit instead.
      expect(mockSetCenter).not.toHaveBeenCalled();
    } finally {
      jest.useRealTimers();
    }
  });

  it("is idempotent per plan id", () => {
    render(<Host />);
    act(() => notifyAgentCanvasMutation(GRAPH));
    act(() => notifyAgentCanvasMutation(GRAPH));
    expect(mockCreateCodeNode).toHaveBeenCalledTimes(2); // not 4
  });

  it("passes the apply's explicit handles through (merge slots, dev/67-3)", () => {
    render(<Host />);
    act(() =>
      notifyAgentCanvasMutation({
        ...GRAPH,
        planId: "plan-handles",
        edges: [
          { id: "e-m", source: "ga", target: "gm", sourceHandle: "out", targetHandle: "in_1" },
          { id: "e-plain", source: "ga", target: "gb" },
        ],
      }),
    );
    const changes = mockOnEdgesChange.mock.calls[0][0];
    // The merge slot survives; handle-less edges keep loadTrill defaults.
    expect(changes[0].item).toMatchObject({ id: "e-m", targetHandle: "in_1", sourceHandle: "out" });
    expect(changes[1].item).toMatchObject({ id: "e-plain", targetHandle: "in", sourceHandle: "out" });
  });

  it("skips nodes already live (partial replays)", () => {
    mockGetNodes.mockReturnValue([{ id: "ga" }]);
    render(<Host />);
    act(() => notifyAgentCanvasMutation({ ...GRAPH, planId: "plan-2" }));
    expect(mockCreateCodeNode).toHaveBeenCalledTimes(1);
    expect(mockCreateCodeNode).toHaveBeenCalledWith(
      "curio.builtin/computation-analysis",
      expect.objectContaining({ nodeId: "gb" }),
    );
  });
});

describe("graph-created removals (dev/59)", () => {
  const REVISION = {
    kind: "graph-created" as const,
    planId: "rev-1",
    nodes: [
      { id: "new-a", type: "curio.builtin/computation-analysis", content: "", goal: "New — n", x: 500, y: 60 },
    ],
    edges: [{ id: "e-new", source: "new-a", target: "cleaner" }],
    removedNodeIds: ["old-loader"],
    removedEdgeIds: ["edge-1"],
  };

  it("applies removals through the REVIEWED path (nodes + edges in one call) BEFORE inserts", () => {
    // dev/62: victims and their cascade leave together — never through the
    // guarded manual path, which would refuse every connected victim.
    const order: string[] = [];
    mockGetNodes.mockReturnValue([{ id: "old-loader" }, { id: "cleaner" }]);
    mockApplyReviewedRemovals.mockImplementation(() => order.push("remove"));
    mockCreateCodeNode.mockImplementation(() => order.push("insert"));
    render(<Host />);
    act(() => notifyAgentCanvasMutation(REVISION));
    expect(mockApplyReviewedRemovals).toHaveBeenCalledWith(["old-loader"], ["edge-1"]);
    expect(order.indexOf("remove")).toBeLessThan(order.indexOf("insert"));
  });

  it("already-absent victims are filtered from the call (user deleted them live)", () => {
    mockGetNodes.mockReturnValue([{ id: "cleaner" }]); // victim already gone
    render(<Host />);
    act(() => notifyAgentCanvasMutation({ ...REVISION, planId: "rev-2" }));
    // The edge cascade still routes through the reviewed path (it no-ops on
    // absent edges internally); the gone victim never reappears in the call.
    expect(mockApplyReviewedRemovals).toHaveBeenCalledWith([], ["edge-1"]);
    expect(mockCreateCodeNode).toHaveBeenCalledTimes(1);
  });

  it("additive payloads never touch the removal machinery (regression)", () => {
    render(<Host />);
    act(() =>
      notifyAgentCanvasMutation({
        kind: "graph-created",
        planId: "rev-3",
        nodes: REVISION.nodes,
        edges: [],
      }),
    );
    expect(mockApplyReviewedRemovals).not.toHaveBeenCalled();
  });
});
